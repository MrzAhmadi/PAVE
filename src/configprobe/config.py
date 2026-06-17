from pathlib import Path

XRAY_DIR = Path.home() / ".configprobe"
XRAY_BINARY = XRAY_DIR / "xray"

IP_CHECK_URL = "https://api.ipify.org"

CONNECTION_TIMEOUT = 6
XRAY_STARTUP_TIMEOUT = 3
TCP_PRECHECK_TIMEOUT = 2
MAX_WORKERS = 50
