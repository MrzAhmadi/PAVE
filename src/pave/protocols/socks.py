from typing import Optional

from ..models import ProxyConfig
from .base import ProtocolTester


class SocksProtocolTester(ProtocolTester):
    """Plain SOCKS5 proxy — tested via a direct curl connection (no subprocess runner)."""

    PROTOCOL = "socks"

    def __init__(self, cfg: ProxyConfig, local_ip: str):
        super().__init__(cfg, local_ip)

    def connect(self) -> tuple[Optional[str], Optional[float], Optional[str], dict]:
        p = self.cfg.params
        user, pw = p.get("username", ""), p.get("password", "")
        proxy_addr = (
            f"{user}:{pw}@{self.cfg.server}:{self.cfg.port}"
            if user
            else f"{self.cfg.server}:{self.cfg.port}"
        )
        exit_ip, latency_ms, err = self._curl_via_socks(proxy_addr)
        extra = self._collect_info(proxy_addr) if exit_ip else {}
        return exit_ip, latency_ms, err, extra
