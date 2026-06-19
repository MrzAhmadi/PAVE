from pathlib import Path
from typing import Optional

from ..models import ProxyConfig
from .base import SingboxBasedTester


class TuicProtocolTester(SingboxBasedTester):
    """TUIC protocol — routed through sing-box."""

    PROTOCOL = "tuic"

    def __init__(self, cfg: ProxyConfig, local_ip: str, singbox_bin: Optional[Path]):
        super().__init__(cfg, local_ip, singbox_bin)
