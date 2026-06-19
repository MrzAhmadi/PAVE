import json
import subprocess
from abc import ABC, abstractmethod


class ProxyCheck(ABC):
    @abstractmethod
    def run(self, proxy_addr: str) -> dict:
        ...

    @staticmethod
    def _curl(proxy_addr: str, url: str, timeout: int = 8) -> str:
        res = subprocess.run(
            ["curl", "--silent", "--max-time", str(timeout),
             "--socks5-hostname", proxy_addr, url],
            capture_output=True, text=True, timeout=timeout + 2,
        )
        if res.returncode == 0:
            return res.stdout.strip()
        return ""


class DnsCheck(ProxyCheck):
    _URL = "http://edns.ip-api.com/json"

    def run(self, proxy_addr: str) -> dict:
        try:
            raw = self._curl(proxy_addr, self._URL)
            if raw:
                data = json.loads(raw)
                if data.get("status") == "fail":
                    return {"dns_resolver_ip": None, "dns_resolver_country": None}
                resolver = data.get("dns") or data.get("query")
                country  = data.get("country")
                if resolver:
                    return {
                        "dns_resolver_ip":      resolver,
                        "dns_resolver_country": country,
                    }
        except Exception:
            pass
        return {"dns_resolver_ip": None, "dns_resolver_country": None}


class IPv6LeakCheck(ProxyCheck):
    _URL = "https://ipv6.icanhazip.com"

    def run(self, proxy_addr: str) -> dict:
        try:
            addr = self._curl(proxy_addr, self._URL)
            if addr:
                return {"ipv6_exit_ip": addr}
        except Exception:
            pass
        return {"ipv6_exit_ip": None}


class ProxyDetectionCheck(ProxyCheck):
    _URL = "http://ip-api.com/json?fields=proxy"

    def run(self, proxy_addr: str) -> dict:
        try:
            raw = self._curl(proxy_addr, self._URL)
            if raw:
                return {"proxy_detected": json.loads(raw).get("proxy")}
        except Exception:
            pass
        return {"proxy_detected": None}


class HeaderLeakCheck(ProxyCheck):
    _URL = "https://httpbin.org/headers"

    def run(self, proxy_addr: str) -> dict:
        try:
            raw = self._curl(proxy_addr, self._URL)
            if raw:
                headers = json.loads(raw).get("headers", {})
                xfwd = headers.get("X-Forwarded-For") or headers.get("X-Real-Ip")
                return {"x_forwarded_for": xfwd}
        except Exception:
            pass
        return {"x_forwarded_for": None}


CHECKS: list[ProxyCheck] = [
    DnsCheck(),
    IPv6LeakCheck(),
    ProxyDetectionCheck(),
    HeaderLeakCheck(),
]
