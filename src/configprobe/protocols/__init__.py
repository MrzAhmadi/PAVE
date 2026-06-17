from pathlib import Path
from typing import Optional

from ..models import ProxyConfig
from .base import ProtocolTester
from .hysteria2 import Hysteria2ProtocolTester
from .shadowsocks import ShadowsocksProtocolTester
from .shadowsocksr import ShadowsocksRProtocolTester
from .socks import SocksProtocolTester
from .trojan import TrojanProtocolTester
from .tuic import TuicProtocolTester
from .vless import VlessProtocolTester
from .vmess import VmessProtocolTester

__all__ = [
    "ProtocolTester",
    "VlessProtocolTester",
    "VmessProtocolTester",
    "ShadowsocksProtocolTester",
    "ShadowsocksRProtocolTester",
    "TrojanProtocolTester",
    "Hysteria2ProtocolTester",
    "TuicProtocolTester",
    "SocksProtocolTester",
    "create_tester",
]


def create_tester(
    cfg: ProxyConfig,
    local_ip: str,
    xray_bin: Path,
    hy2_bin: Optional[Path] = None,
    singbox_bin: Optional[Path] = None,
) -> ProtocolTester:
    """Return the appropriate ProtocolTester for the given proxy's protocol."""
    p = cfg.protocol
    if p == "vless":
        return VlessProtocolTester(cfg, local_ip, xray_bin)
    if p == "vmess":
        return VmessProtocolTester(cfg, local_ip, xray_bin)
    if p == "ss":
        return ShadowsocksProtocolTester(cfg, local_ip, xray_bin)
    if p == "trojan":
        return TrojanProtocolTester(cfg, local_ip, xray_bin)
    if p == "hysteria2":
        return Hysteria2ProtocolTester(cfg, local_ip, hy2_bin)
    if p == "tuic":
        return TuicProtocolTester(cfg, local_ip, singbox_bin)
    if p == "ssr":
        return ShadowsocksRProtocolTester(cfg, local_ip, singbox_bin)
    if p == "socks":
        return SocksProtocolTester(cfg, local_ip)
    raise ValueError(f"Unsupported protocol: {p}")
