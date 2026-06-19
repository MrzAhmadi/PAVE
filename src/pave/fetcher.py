import base64
import logging
from typing import List, Tuple

import requests

logger = logging.getLogger(__name__)

SUPPORTED_PREFIXES = (
    "vless://", "vmess://", "ss://", "trojan://",
    "ssr://", "hysteria2://", "hy2://",
    "socks://", "socks4://", "socks5://",
    "tuic://",
)


def fetch_subscription(url: str, source_name: str = "") -> List[Tuple[str, str]]:
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "PAVE/1.0"})
        resp.raise_for_status()
        content = resp.text.strip()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return []

    lines = _decode_content(content)
    label = source_name or url

    configs: List[Tuple[str, str]] = []
    for line in lines:
        line = line.strip()
        if line and any(line.startswith(p) for p in SUPPORTED_PREFIXES):
            configs.append((line, label))

    logger.info(f"Fetched {len(configs)} configs from {label}")
    return configs


def _decode_content(content: str) -> List[str]:
    lines = content.splitlines()
    plain_count = sum(1 for l in lines if any(l.strip().startswith(p) for p in SUPPORTED_PREFIXES))
    if plain_count > len(lines) * 0.1:
        return lines

    try:
        clean = content.replace("\n", "").replace("\r", "").replace(" ", "")
        padding = "=" * (-len(clean) % 4)
        decoded = base64.b64decode(clean + padding).decode("utf-8", errors="ignore")
        if any(decoded.startswith(p) for p in SUPPORTED_PREFIXES):
            return decoded.splitlines()
    except Exception:
        pass

    return lines
