import json
import logging
import os
import platform
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import requests

from ..config import XRAY_DIR, XRAY_STARTUP_TIMEOUT
from ..models import ProxyConfig
from .base import ProxyRunner

logger = logging.getLogger(__name__)

SB_BINARY = XRAY_DIR / "sing-box"


def ensure_singbox() -> Path:
    import shutil
    system = shutil.which("sing-box")
    if system:
        logger.debug(f"Using system sing-box at {system}")
        return Path(system)

    XRAY_DIR.mkdir(parents=True, exist_ok=True)
    if SB_BINARY.exists():
        logger.debug(f"Using sing-box at {SB_BINARY}")
        return SB_BINARY

    logger.info("Downloading sing-box from SagerNet/sing-box ...")

    api = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"
    resp = requests.get(api, timeout=30)
    resp.raise_for_status()
    version = resp.json()["tag_name"]
    ver = version.lstrip("v")

    arch = platform.machine().lower()
    if arch in ("x86_64", "amd64"):
        suffix = "linux-amd64"
    elif arch in ("aarch64", "arm64"):
        suffix = "linux-arm64"
    else:
        suffix = "linux-amd64"

    url = f"https://github.com/SagerNet/sing-box/releases/download/{version}/sing-box-{ver}-{suffix}.tar.gz"
    logger.info(f"Downloading {url}")

    import tarfile
    tar_path = XRAY_DIR / "sing-box.tar.gz"
    with requests.get(url, timeout=120, stream=True) as r:
        r.raise_for_status()
        with open(tar_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)

    with tarfile.open(tar_path) as tf:
        for member in tf.getmembers():
            if member.name.endswith("/sing-box") or member.name == "sing-box":
                member.name = "sing-box"
                tf.extract(member, XRAY_DIR)
                break

    tar_path.unlink(missing_ok=True)
    SB_BINARY.chmod(0o755)
    logger.info(f"sing-box {version} installed at {SB_BINARY}")
    return SB_BINARY


def build_singbox_config(cfg: ProxyConfig, socks_port: int) -> dict:
    return {
        "log": {"level": "error", "output": "stderr"},
        "inbounds": [{
            "type":        "socks",
            "listen":      "127.0.0.1",
            "listen_port": socks_port,
        }],
        "outbounds": [_build_outbound(cfg)],
    }


def _build_outbound(cfg: ProxyConfig) -> dict:
    if cfg.protocol == "tuic":
        return _tuic_outbound(cfg)
    elif cfg.protocol == "ssr":
        return _ssr_outbound(cfg)
    else:
        raise ValueError(f"sing-box runner does not handle protocol: {cfg.protocol}")


def _tuic_outbound(cfg: ProxyConfig) -> dict:
    p = cfg.params
    alpn = [a.strip() for a in p.get("alpn", "h3").split(",") if a.strip()] or ["h3"]
    return {
        "type":                "tuic",
        "server":              cfg.server,
        "server_port":         cfg.port,
        "uuid":                p.get("uuid", ""),
        "password":            p.get("password", ""),
        "congestion_control":  p.get("congestion_control", "bbr"),
        "tls": {
            "enabled":     True,
            "server_name": p.get("sni", "") or cfg.server,
            "insecure":    p.get("insecure", "0") in ("1", "true", True),
            "alpn":        alpn,
        },
    }


def _ssr_outbound(cfg: ProxyConfig) -> dict:
    p = cfg.params
    return {
        "type":           "shadowsocksr",
        "server":         cfg.server,
        "server_port":    cfg.port,
        "method":         p.get("method", "aes-256-cfb"),
        "password":       p.get("password", ""),
        "protocol":       p.get("protocol", "origin"),
        "protocol_param": p.get("protocol_param", ""),
        "obfs":           p.get("obfs", "plain"),
        "obfs_param":     p.get("obfs_param", ""),
    }


def _find_free_port(start: int = 12808, attempts: int = 200) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free TCP port available for sing-box")


def _wait_for_port(port: int, timeout: float = XRAY_STARTUP_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class SingboxProcess(ProxyRunner):
    def __init__(self, cfg: ProxyConfig, binary: Path):
        self._cfg = cfg
        self._binary = binary
        self._proc: Optional[subprocess.Popen] = None
        self._cfg_file: Optional[str] = None
        self.port: Optional[int] = None

    def __enter__(self) -> Optional[int]:
        try:
            self.port = _find_free_port()
            sb_cfg = build_singbox_config(self._cfg, self.port)

            fd, self._cfg_file = tempfile.mkstemp(suffix=".json", prefix="singbox_")
            with os.fdopen(fd, "w") as fh:
                json.dump(sb_cfg, fh)

            self._proc = subprocess.Popen(
                [str(self._binary), "run", "-c", self._cfg_file],
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
            logger.debug(f"SingboxProcess start failed for {self._cfg.server}: {e}")
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
