from pathlib import Path
from typing import Optional

from ..models import ProxyConfig
from .base import ProtocolTester


class Hysteria2ProtocolTester(ProtocolTester):
    """Hysteria2 protocol — routed through the hysteria2 binary."""

    PROTOCOL = "hysteria2"

    def __init__(self, cfg: ProxyConfig, local_ip: str, hy2_bin: Optional[Path]):
        super().__init__(cfg, local_ip)
        self.hy2_bin = hy2_bin

    def connect(self) -> tuple[Optional[str], Optional[float], Optional[str], dict]:
        if self.hy2_bin is None:
            return None, None, "hysteria2 binary not available", {}
        if not self._tcp_reachable(self.cfg.server, self.cfg.port):
            return None, None, "Host unreachable", {}
        from ..runners import Hysteria2Process
        with Hysteria2Process(self.cfg, self.hy2_bin) as port:
            if port is None:
                return None, None, "hysteria2 failed to start", {}
            proxy_addr = f"127.0.0.1:{port}"
            exit_ip, latency_ms, err = self._curl_via_socks(proxy_addr)
            extra = self._collect_info(proxy_addr) if exit_ip else {}
            return exit_ip, latency_ms, err, extra
