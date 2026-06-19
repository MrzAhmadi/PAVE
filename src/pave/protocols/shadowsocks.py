from pathlib import Path

from ..models import ProxyConfig
from .base import XrayBasedTester


class ShadowsocksProtocolTester(XrayBasedTester):
    """Shadowsocks (ss) protocol — routed through Xray-core."""

    PROTOCOL = "ss"

    def __init__(self, cfg: ProxyConfig, local_ip: str, xray_bin: Path):
        super().__init__(cfg, local_ip, xray_bin)
