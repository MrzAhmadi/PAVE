from pathlib import Path
from typing import Optional

from ..models import ProxyConfig
from .base import SingboxBasedTester


class ShadowsocksRProtocolTester(SingboxBasedTester):
    """ShadowsocksR (ssr) protocol — routed through sing-box."""

    PROTOCOL = "ssr"

    def __init__(self, cfg: ProxyConfig, local_ip: str, singbox_bin: Optional[Path]):
        super().__init__(cfg, local_ip, singbox_bin)
