import socket
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import requests

from .. import config as _cfg
from ..config import IP_CHECK_URL
from ..models import ProxyConfig, TestResult

CURL_ERRORS = {
    5:  "SOCKS proxy error",
    6:  "DNS lookup failed",
    7:  "Connection refused",
    28: "Timeout",
    35: "SSL handshake failed",
    56: "Network receive error",
}


class ProtocolTester(ABC):
    def __init__(self, cfg: ProxyConfig, local_ip: str):
        self.cfg = cfg
        self.local_ip = local_ip

    @abstractmethod
    def connect(self) -> tuple[Optional[str], Optional[float], Optional[str], dict]:
        """Start proxy and attempt connection.

        Returns (exit_ip, latency_ms, error, extra). Exactly one of exit_ip or
        error is set; latency_ms and extra are set only on success.
        """

    def is_connected(self, exit_ip: Optional[str]) -> bool:
        """True when we got an exit IP that differs from the local IP."""
        return bool(exit_ip) and exit_ip != self.local_ip

    @staticmethod
    def get_info(exit_ip: str) -> dict:
        """Single-IP geo + blacklist lookup via ip-api.com.

        Returns a dict with country, city, org, asn, is_datacenter,
        is_blacklisted. Empty dict on any failure.
        """
        try:
            resp = requests.get(
                f"http://ip-api.com/json/{exit_ip}"
                "?fields=status,country,countryCode,city,org,as,hosting,proxy",
                timeout=10,
            )
            data = resp.json()
            if data.get("status") == "success":
                return {
                    "country":        data.get("country"),
                    "country_code":   data.get("countryCode"),
                    "city":           data.get("city"),
                    "org":            data.get("org"),
                    "asn":            data.get("as"),
                    "is_datacenter":  data.get("hosting", False),
                    "is_blacklisted": data.get("proxy", False),
                }
        except Exception:
            pass
        return {}

    def run(self) -> TestResult:
        """Full test pipeline: connect → check → build TestResult.

        Geo enrichment (get_info) is intentionally omitted here so that
        run_tests() can batch all lookups in one call for efficiency.
        dns_leak and ipv6_leak are also computed later by run_tests().
        """
        result = TestResult(config=self.cfg, local_ip=self.local_ip)
        exit_ip, latency_ms, err, extra = self.connect()
        if exit_ip and self.is_connected(exit_ip):
            result.success              = True
            result.latency_ms           = latency_ms
            result.exit_ip              = exit_ip
            result.is_redirecting       = True
            result.dns_resolver_ip      = extra.get("dns_resolver_ip")
            result.dns_resolver_country = extra.get("dns_resolver_country")
            result.ipv6_exit_ip         = extra.get("ipv6_exit_ip")
            result.proxy_detected       = extra.get("proxy_detected")
            result.x_forwarded_for      = extra.get("x_forwarded_for")
        else:
            result.error = err
        return result

    @staticmethod
    def _collect_info(proxy_addr: str) -> dict:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from ..checks import CHECKS
        info: dict = {}
        with ThreadPoolExecutor(max_workers=len(CHECKS)) as pool:
            futures = {pool.submit(c.run, proxy_addr): c for c in CHECKS}
            for future in as_completed(futures):
                try:
                    info.update(future.result())
                except Exception:
                    pass
        return info

    @staticmethod
    def _tcp_reachable(host: str, port: int) -> bool:
        """Pre-check TCP reachability for IP addresses (skips hostnames)."""
        try:
            socket.inet_pton(socket.AF_INET, host)
        except OSError:
            try:
                socket.inet_pton(socket.AF_INET6, host)
            except OSError:
                return True  # hostname — let curl handle DNS
        try:
            with socket.create_connection((host, port), timeout=_cfg.TCP_PRECHECK_TIMEOUT):
                return True
        except OSError:
            return False

    @staticmethod
    def _curl_via_socks(
        proxy_addr: str,
        timeout: int | None = None,
    ) -> tuple[Optional[str], Optional[float], Optional[str]]:
        if timeout is None:
            timeout = _cfg.CONNECTION_TIMEOUT
        """Run curl through a SOCKS5 proxy at proxy_addr.

        proxy_addr may be "host:port" or "user:pass@host:port".
        Returns (exit_ip, latency_ms, error).
        """
        cmd = [
            "curl", "--silent", "--max-time", str(timeout),
            "--socks5-hostname", proxy_addr,
            IP_CHECK_URL,
        ]
        t0 = time.monotonic()
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
            elapsed_ms = (time.monotonic() - t0) * 1000
            if res.returncode == 0:
                ip = res.stdout.strip()
                if ip:
                    return ip, round(elapsed_ms, 2), None
                return None, None, "Empty response"
            return None, None, CURL_ERRORS.get(res.returncode, f"curl error {res.returncode}")
        except subprocess.TimeoutExpired:
            return None, None, "Timeout"
        except Exception as e:
            return None, None, str(e)[:120]


class XrayBasedTester(ProtocolTester):
    """Intermediate base for protocols handled by Xray-core (vless/vmess/ss/trojan)."""

    def __init__(self, cfg: ProxyConfig, local_ip: str, xray_bin: Path):
        super().__init__(cfg, local_ip)
        self.xray_bin = xray_bin

    def connect(self) -> tuple[Optional[str], Optional[float], Optional[str], dict]:
        if not self._tcp_reachable(self.cfg.server, self.cfg.port):
            return None, None, "Host unreachable", {}
        from ..runners import XrayProcess
        with XrayProcess(self.cfg, self.xray_bin) as port:
            if port is None:
                return None, None, "xray failed to start", {}
            proxy_addr = f"127.0.0.1:{port}"
            exit_ip, latency_ms, err = self._curl_via_socks(proxy_addr)
            extra = self._collect_info(proxy_addr) if exit_ip else {}
            return exit_ip, latency_ms, err, extra


class SingboxBasedTester(ProtocolTester):
    """Intermediate base for protocols handled by sing-box (tuic/ssr)."""

    def __init__(self, cfg: ProxyConfig, local_ip: str, singbox_bin: Optional[Path]):
        super().__init__(cfg, local_ip)
        self.singbox_bin = singbox_bin

    def connect(self) -> tuple[Optional[str], Optional[float], Optional[str], dict]:
        if self.singbox_bin is None:
            return None, None, f"{self.cfg.protocol}: sing-box binary not available", {}
        if not self._tcp_reachable(self.cfg.server, self.cfg.port):
            return None, None, "Host unreachable", {}
        from ..runners import SingboxProcess
        with SingboxProcess(self.cfg, self.singbox_bin) as port:
            if port is None:
                return None, None, "sing-box failed to start", {}
            proxy_addr = f"127.0.0.1:{port}"
            exit_ip, latency_ms, err = self._curl_via_socks(proxy_addr)
            extra = self._collect_info(proxy_addr) if exit_ip else {}
            return exit_ip, latency_ms, err, extra
