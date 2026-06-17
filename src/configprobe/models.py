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
    dns_leak: Optional[bool] = None
    ipv6_leak: Optional[bool] = None
    tls_tampered: Optional[bool] = None
    response_tampered: Optional[bool] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "config_id":        self.config.config_id,
            "protocol":         self.config.protocol,
            "server":           self.config.server,
            "port":             self.config.port,
            "name":             self.config.name,
            "source":           self.config.source,
            "timestamp":        self.timestamp,
            "success":          self.success,
            "latency_ms":       self.latency_ms,
            "exit_ip":          self.exit_ip,
            "local_ip":         self.local_ip,
            "is_redirecting":   self.is_redirecting,
            "country":          self.country,
            "country_code":     self.country_code,
            "city":             self.city,
            "org":              self.org,
            "asn":              self.asn,
            "is_datacenter":    self.is_datacenter,
            "is_blacklisted":   self.is_blacklisted,
            "dns_leak":         self.dns_leak,
            "ipv6_leak":        self.ipv6_leak,
            "tls_tampered":     self.tls_tampered,
            "response_tampered": self.response_tampered,
            "error":            self.error,
        }
