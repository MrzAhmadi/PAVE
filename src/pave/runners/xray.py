import json
import logging
import os
import platform
import socket
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

import requests

from ..config import XRAY_BINARY, XRAY_DIR, XRAY_STARTUP_TIMEOUT
from ..models import ProxyConfig
from .base import ProxyRunner

logger = logging.getLogger(__name__)


def ensure_xray() -> Path:
    import shutil
    system = shutil.which("xray")
    if system:
        logger.debug(f"Using system xray at {system}")
        return Path(system)

    XRAY_DIR.mkdir(parents=True, exist_ok=True)

    if XRAY_BINARY.exists():
        logger.debug(f"Using xray at {XRAY_BINARY}")
        return XRAY_BINARY

    logger.info("xray not found — downloading latest release from XTLS/Xray-core ...")

    api = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"
    resp = requests.get(api, timeout=30)
    resp.raise_for_status()
    version = resp.json()["tag_name"]

    arch = platform.machine().lower()
    if arch in ("x86_64", "amd64"):
        suffix = "64"
    elif arch in ("aarch64", "arm64"):
        suffix = "arm64-v8a"
    elif arch.startswith("arm"):
        suffix = "arm32-v7a"
    else:
        suffix = "64"

    url = f"https://github.com/XTLS/Xray-core/releases/download/{version}/Xray-linux-{suffix}.zip"
    logger.info(f"Downloading {url}")

    zip_path = XRAY_DIR / "xray.zip"
    with requests.get(url, timeout=120, stream=True) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extract("xray", XRAY_DIR)
    zip_path.unlink(missing_ok=True)

    XRAY_BINARY.chmod(0o755)
    logger.info(f"xray {version} installed at {XRAY_BINARY}")
    return XRAY_BINARY


def build_xray_config(cfg: ProxyConfig, socks_port: int) -> dict:
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": socks_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": False},
            "sniffing": {"enabled": False},
        }],
        "outbounds": [
            _build_outbound(cfg),
            {"protocol": "freedom", "tag": "direct"},
        ],
    }


def _build_outbound(cfg: ProxyConfig) -> dict:
    p = cfg.protocol
    if p == "vless":
        return _vless_outbound(cfg)
    elif p == "vmess":
        return _vmess_outbound(cfg)
    elif p == "ss":
        return _ss_outbound(cfg)
    elif p == "trojan":
        return _trojan_outbound(cfg)
    else:
        raise ValueError(f"Unsupported protocol: {p}")


def _vless_outbound(cfg: ProxyConfig) -> dict:
    p = cfg.params
    user: dict = {
        "id": p.get("uuid", ""),
        "encryption": p.get("encryption", "none"),
    }
    if p.get("flow"):
        user["flow"] = p["flow"]
    return {
        "protocol": "vless",
        "settings": {"vnext": [{"address": cfg.server, "port": cfg.port, "users": [user]}]},
        "streamSettings": _stream_settings(p),
    }


def _vmess_outbound(cfg: ProxyConfig) -> dict:
    p = cfg.params
    vmess_p = dict(p)
    vmess_p["security"] = p.get("tls", "") or "none"
    return {
        "protocol": "vmess",
        "settings": {
            "vnext": [{
                "address": cfg.server,
                "port":    cfg.port,
                "users": [{
                    "id":       p.get("uuid", ""),
                    "alterId":  int(p.get("alterId", 0) or 0),
                    "security": p.get("security", "auto"),
                }],
            }]
        },
        "streamSettings": _stream_settings(vmess_p),
    }


def _ss_outbound(cfg: ProxyConfig) -> dict:
    p = cfg.params
    return {
        "protocol": "shadowsocks",
        "settings": {
            "servers": [{
                "address":  cfg.server,
                "port":     cfg.port,
                "method":   p.get("method", "aes-256-gcm"),
                "password": p.get("password", ""),
                "level":    0,
            }]
        },
    }


def _trojan_outbound(cfg: ProxyConfig) -> dict:
    p = cfg.params
    return {
        "protocol": "trojan",
        "settings": {
            "servers": [{
                "address":  cfg.server,
                "port":     cfg.port,
                "password": p.get("password", ""),
                "level":    0,
            }]
        },
        "streamSettings": _stream_settings(p),
    }


def _stream_settings(p: dict) -> dict:
    network = p.get("type", "tcp")
    if network in ("h2", "http"):
        network = "h2"

    security = p.get("security", "none")
    stream: dict = {"network": network}

    if security == "tls":
        sni = p.get("sni", "") or p.get("host", "")
        fp  = p.get("fp", "")
        tls: dict = {"allowInsecure": p.get("allowInsecure", "1") in ("1", "true", True)}
        if sni:
            tls["serverName"] = sni
        if fp:
            tls["fingerprint"] = fp
        stream["security"] = "tls"
        stream["tlsSettings"] = tls

    elif security == "reality":
        stream["security"] = "reality"
        stream["realitySettings"] = {
            "serverName":  p.get("sni", ""),
            "fingerprint": p.get("fp", "chrome") or "chrome",
            "publicKey":   p.get("pbk", ""),
            "shortId":     p.get("sid", ""),
            "spiderX":     p.get("spx", ""),
        }
    else:
        stream["security"] = "none"

    if network == "ws":
        ws: dict = {"path": p.get("path", "/")}
        host = p.get("host", "")
        if host:
            ws["headers"] = {"Host": host}
        stream["wsSettings"] = ws

    elif network == "grpc":
        service_name = p.get("serviceName", "") or p.get("path", "")
        stream["grpcSettings"] = {
            "serviceName": service_name,
            "multiMode":   p.get("mode", "gun") == "multi",
        }

    elif network == "h2":
        h2: dict = {"path": p.get("path", "/")}
        host = p.get("host", "")
        if host:
            h2["host"] = [host]
        stream["httpSettings"] = h2

    elif network == "tcp":
        header_type = p.get("headerType", "none")
        if header_type == "http":
            stream["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "path":    [p.get("path", "/")],
                        "headers": {"Host": [p.get("host", "")]},
                    },
                }
            }

    elif network in ("kcp", "mkcp"):
        stream["network"] = "kcp"
        stream["kcpSettings"] = {"header": {"type": p.get("headerType", "none")}}

    elif network == "quic":
        stream["quicSettings"] = {
            "security": p.get("quicSecurity", "none"),
            "key":      p.get("key", ""),
            "header":   {"type": p.get("headerType", "none")},
        }

    elif network == "httpupgrade":
        stream["httpupgradeSettings"] = {
            "path": p.get("path", "/"),
            "host": p.get("host", ""),
        }

    elif network == "splithttp":
        stream["splithttpSettings"] = {
            "path": p.get("path", "/"),
            "host": p.get("host", ""),
        }

    return stream


def _find_free_port(start: int = 10808, attempts: int = 200) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free TCP port available in range")


def _wait_for_port(port: int, timeout: float = XRAY_STARTUP_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class XrayProcess(ProxyRunner):
    def __init__(self, cfg: ProxyConfig, binary: Path):
        self._cfg = cfg
        self._binary = binary
        self._proc: Optional[subprocess.Popen] = None
        self._cfg_file: Optional[str] = None
        self.port: Optional[int] = None

    def __enter__(self) -> Optional[int]:
        try:
            self.port = _find_free_port()
            xray_cfg = build_xray_config(self._cfg, self.port)

            fd, self._cfg_file = tempfile.mkstemp(suffix=".json", prefix="xray_")
            with os.fdopen(fd, "w") as fh:
                json.dump(xray_cfg, fh)

            self._proc = subprocess.Popen(
                [str(self._binary), "run", "-config", self._cfg_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            if not _wait_for_port(self.port):
                self._teardown()
                return None

            if self._proc.poll() is not None:
                self._teardown()
                return None

            return self.port

        except Exception as e:
            logger.debug(f"XrayProcess start failed for {self._cfg.server}: {e}")
            self._teardown()
            return None

    def __exit__(self, *_):
        self._teardown()

    def _teardown(self):
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

        if self._cfg_file:
            try:
                os.unlink(self._cfg_file)
            except OSError:
                pass
            self._cfg_file = None
