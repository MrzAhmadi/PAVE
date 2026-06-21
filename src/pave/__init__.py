"""PAVE — Proxy Analysis and Verification Engine."""

from pathlib import Path

try:
    __version__ = (Path(__file__).parent / "_version.txt").read_text().strip()
except Exception:
    __version__ = "dev"
