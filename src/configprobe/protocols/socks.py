from typing import Optional

from ..models import ProxyConfig
from .base import ProtocolTester


class SocksProtocolTester(ProtocolTester):
    """Plain SOCKS5 proxy — tested via a direct curl connection (no subprocess runner)."""

    PROTOCOL = "socks"

    def __init__(self, cfg: ProxyConfig, local_ip: str):
        super().__init__(cfg, local_ip)

    def connect(self) -> tuple[Optional[str], Optional[float], Optional[str]]:
        p = self.cfg.params
        user, pw = p.get("username", ""), p.get("password", "")
        proxy = (
            f"{user}:{pw}@{self.cfg.server}:{self.cfg.port}"
            if user
            else f"{self.cfg.server}:{self.cfg.port}"
        )
        return self._curl_via_socks(proxy)
