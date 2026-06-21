"""PAVE — Proxy Analysis and Verification Engine."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("pave-proxy")
except PackageNotFoundError:
    __version__ = "dev"
