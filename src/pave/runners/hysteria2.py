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
import yaml

from ..config import XRAY_DIR, XRAY_STARTUP_TIMEOUT
from ..models import ProxyConfig
from .base import ProxyRunner

logger = logging.getLogger(__name__)

HY2_BINARY = XRAY_DIR / "hysteria2"


def ensure_hysteria2() -> Path:
    import shutil
    system = shutil.which("hysteria2") or shutil.which("hysteria")
    if system:
        logger.debug(f"Using system hysteria2 at {system}")
        return Path(system)

    XRAY_DIR.mkdir(parents=True, exist_ok=True)
    if HY2_BINARY.exists():
        logger.debug(f"Using hysteria2 at {HY2_BINARY}")
        return HY2_BINARY

    logger.info("Downloading hysteria2 from apernet/hysteria ...")

    api = "https://api.github.com/repos/apernet/hysteria/releases/latest"
    resp = requests.get(api, timeout=30)
    resp.raise_for_status()
    version = resp.json()["tag_name"]

    arch = platform.machine().lower()
    if arch in ("x86_64", "amd64"):
        suffix = "linux-amd64"
    elif arch in ("aarch64", "arm64"):
        suffix = "linux-arm64"
    else:
        suffix = "linux-amd64"

    url = f"https://github.com/apernet/hysteria/releases/download/{version}/hysteria-{suffix}"
    logger.info(f"Downloading {url}")

    with requests.get(url, timeout=120, stream=True) as r:
        r.raise_for_status()
        with open(HY2_BINARY, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)

    HY2_BINARY.chmod(0o755)
    logger.info(f"hysteria2 installed at {HY2_BINARY}")
    return HY2_BINARY


def build_hy2_config(cfg: ProxyConfig, socks_port: int) -> dict:
    p = cfg.params
    hy2_cfg: dict = {
        "server": f"{cfg.server}:{cfg.port}",
        "auth":   p.get("password", ""),
        "socks5": {"listen": f"127.0.0.1:{socks_port}"},
        "tls": {
            "sni":      p.get("sni", "") or cfg.server,
            "insecure": p.get("insecure", "1") in ("1", "true", True),
        },
    }
    if p.get("obfs"):
        hy2_cfg["obfs"] = {
            "type":    p["obfs"],
            p["obfs"]: {"password": p.get("obfs_password", "")},
        }
    return hy2_cfg


def _find_free_port(start: int = 11808, attempts: int = 200) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found for hysteria2")


def _wait_for_port(port: int, timeout: float = XRAY_STARTUP_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class Hysteria2Process(ProxyRunner):
    def __init__(self, cfg: ProxyConfig, binary: Path):
        self._cfg = cfg
        self._binary = binary
        self._proc: Optional[subprocess.Popen] = None
        self._cfg_file: Optional[str] = None
        self.port: Optional[int] = None

    def __enter__(self) -> Optional[int]:
        try:
            self.port = _find_free_port()
            hy2_cfg = build_hy2_config(self._cfg, self.port)

            fd, self._cfg_file = tempfile.mkstemp(suffix=".yaml", prefix="hy2_")
            with os.fdopen(fd, "w") as fh:
                yaml.dump(hy2_cfg, fh)

            self._proc = subprocess.Popen(
                [str(self._binary), "client", "-c", self._cfg_file],
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
            logger.debug(f"Hysteria2Process start failed for {self._cfg.server}: {e}")
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
