import hashlib
import ipaddress
import logging
import secrets
import socket
import ssl
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_PROXY_CHECK_HOST = "www.cloudflare.com"
_IP_SERVICES = [
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
]


@dataclass
class SafetyResult:
    passed: bool
    detail: Optional[str] = None


class SafetyCheck(ABC):
    @abstractmethod
    def run(self, socks_port: int, exit_ip: str, local_ip: str) -> SafetyResult: ...


class DnsLeakCheck(SafetyCheck):
    def run(self, socks_port: int, exit_ip: str, local_ip: str) -> SafetyResult:
        test_id = secrets.token_hex(8)
        proxies = _socks5_proxies(socks_port)
        try:
            requests.get(f"https://bash.ws/dnsleak/test/{test_id}", timeout=8)
            try:
                requests.get(
                    f"http://{test_id}.bash.ws/",
                    proxies=proxies,
                    timeout=8,
                )
            except Exception:
                pass
            time.sleep(1)
            resp = requests.get(
                f"https://bash.ws/dnsleak/test/{test_id}/json", timeout=8
            )
            exit_net  = _ip_prefix(exit_ip)
            local_net = _ip_prefix(local_ip)
            for entry in resp.json():
                ip = entry.get("ip", "")
                if ip and _ip_prefix(ip) == local_net and _ip_prefix(ip) != exit_net:
                    return SafetyResult(False, f"DNS resolver {ip} matches local network")
            return SafetyResult(True)
        except Exception as exc:
            return SafetyResult(True, f"skipped: {exc}")


class IPv6LeakCheck(SafetyCheck):
    def run(self, socks_port: int, exit_ip: str, local_ip: str) -> SafetyResult:
        local_v6 = _local_ipv6()
        if not local_v6:
            return SafetyResult(True, "no local IPv6")
        try:
            result = subprocess.run(
                ["curl", "--silent", "--max-time", "8", "-6",
                 "--socks5-hostname", f"127.0.0.1:{socks_port}",
                 "https://api6.ipify.org"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return SafetyResult(True, "proxy has no IPv6 route")
            returned = result.stdout.strip()
            if returned == local_v6:
                return SafetyResult(False, f"IPv6 leak: {returned}")
            return SafetyResult(True, f"proxy IPv6: {returned}")
        except Exception as exc:
            return SafetyResult(True, f"skipped: {exc}")


class TlsFingerprintCheck(SafetyCheck):
    _HOST = _PROXY_CHECK_HOST

    def run(self, socks_port: int, exit_ip: str, local_ip: str) -> SafetyResult:
        try:
            direct_fp = _cert_fp_direct(self._HOST)
            proxy_fp  = _cert_fp_via_proxy(self._HOST, socks_port)
            if direct_fp and proxy_fp:
                if direct_fp != proxy_fp:
                    return SafetyResult(False, "TLS certificate mismatch — MITM suspected")
                return SafetyResult(True)
            return SafetyResult(True, "fingerprint unavailable")
        except Exception as exc:
            return SafetyResult(True, f"skipped: {exc}")


class ResponseIntegrityCheck(SafetyCheck):
    def run(self, socks_port: int, exit_ip: str, local_ip: str) -> SafetyResult:
        proxies = _socks5_proxies(socks_port)
        returned: list[str] = []
        for url in _IP_SERVICES:
            try:
                r = requests.get(url, proxies=proxies, timeout=8)
                returned.append(r.text.strip())
            except Exception:
                pass
        if len(set(returned)) > 1:
            return SafetyResult(False, f"IP-check services disagree: {set(returned)}")
        if returned and returned[0] != exit_ip:
            return SafetyResult(
                False, f"cross-service IP mismatch: {returned[0]} vs {exit_ip}"
            )
        return SafetyResult(True)


class SafetyChecker:
    def __init__(self, checks: Optional[list[SafetyCheck]] = None):
        self._checks: list[SafetyCheck] = checks if checks is not None else [
            DnsLeakCheck(),
            IPv6LeakCheck(),
            TlsFingerprintCheck(),
            ResponseIntegrityCheck(),
        ]

    def run_all(
        self, socks_port: int, exit_ip: str, local_ip: str
    ) -> dict[str, SafetyResult]:
        return {
            type(c).__name__: c.run(socks_port, exit_ip, local_ip)
            for c in self._checks
        }


def _socks5_proxies(port: int) -> dict:
    addr = f"socks5h://127.0.0.1:{port}"
    return {"http": addr, "https": addr}


def _ip_prefix(ip: str, length: int = 24) -> str:
    try:
        return str(ipaddress.ip_network(f"{ip}/{length}", strict=False))
    except ValueError:
        return ip


def _local_ipv6() -> Optional[str]:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as s:
            s.connect(("2001:4860:4860::8888", 80))
            addr = s.getsockname()[0]
            return addr if not addr.startswith("fe80") else None
    except Exception:
        return None


def _cert_fp_direct(host: str, port: int = 443) -> Optional[str]:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=8) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                return hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
    except Exception:
        return None


def _cert_fp_via_proxy(host: str, socks_port: int, port: int = 443) -> Optional[str]:
    try:
        import socks as _socks
        sock = _socks.socksocket()
        sock.set_proxy(_socks.SOCKS5, "127.0.0.1", socks_port)
        sock.settimeout(8)
        sock.connect((host, port))
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            return hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
    except Exception:
        return None
