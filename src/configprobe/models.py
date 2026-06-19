from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
import hashlib


@dataclass
class ProxyConfig:
    raw: str
    protocol: str
    server: str
    port: int
    name: str
    params: Dict[str, Any] = field(default_factory=dict)
    source: str = ""

    @property
    def config_id(self) -> str:
        return hashlib.md5(self.raw.encode()).hexdigest()[:12]

    @property
    def dedup_key(self) -> str:
        auth = self.params.get("uuid") or self.params.get("password") or ""
        return f"{self.protocol}|{self.server.lower()}|{self.port}|{auth}"


@dataclass
class TestResult:
    config: ProxyConfig
    local_ip: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    success: bool = False
    latency_ms: Optional[float] = None
    exit_ip: Optional[str] = None
    is_redirecting: bool = False
    country: Optional[str] = None
    country_code: Optional[str] = None
    city: Optional[str] = None
    org: Optional[str] = None
    asn: Optional[str] = None
    is_datacenter: Optional[bool] = None
    is_blacklisted: Optional[bool] = None
    dns_resolver_ip: Optional[str] = None
    dns_resolver_country: Optional[str] = None
    dns_leak: Optional[bool] = None
    ipv6_exit_ip: Optional[str] = None
    ipv6_leak: Optional[bool] = None
    proxy_detected: Optional[bool] = None
    x_forwarded_for: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "config_id":            self.config.config_id,
            "raw_config":           self.config.raw,
            "protocol":             self.config.protocol,
            "server":               self.config.server,
            "port":                 self.config.port,
            "name":                 self.config.name,
            "source":               self.config.source,
            "timestamp":            self.timestamp,
            "success":              self.success,
            "latency_ms":           self.latency_ms,
            "exit_ip":              self.exit_ip,
            "local_ip":             self.local_ip,
            "is_redirecting":       self.is_redirecting,
            "country":              self.country,
            "country_code":         self.country_code,
            "city":                 self.city,
            "org":                  self.org,
            "asn":                  self.asn,
            "is_datacenter":        self.is_datacenter,
            "is_blacklisted":       self.is_blacklisted,
            "dns_resolver_ip":      self.dns_resolver_ip,
            "dns_resolver_country": self.dns_resolver_country,
            "dns_leak":             self.dns_leak,
            "ipv6_exit_ip":         self.ipv6_exit_ip,
            "ipv6_leak":            self.ipv6_leak,
            "proxy_detected":       self.proxy_detected,
            "x_forwarded_for":      self.x_forwarded_for,
            "error":                self.error,
        }
