import csv
import json
import logging
from pathlib import Path
from typing import List

from .models import TestResult

logger = logging.getLogger(__name__)

CSV_FIELDS = [
    "config_id", "raw_config", "protocol", "server", "port", "name", "source",
    "timestamp", "success", "latency_ms", "exit_ip", "local_ip",
    "is_redirecting", "country", "country_code", "city", "org", "asn",
    "is_datacenter", "is_blacklisted",
    "dns_resolver_ip", "dns_resolver_country", "dns_leak",
    "ipv6_exit_ip", "ipv6_leak",
    "proxy_detected", "x_forwarded_for",
    "error",
]


def save_csv(results: List[TestResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r.to_dict())
    logger.info(f"CSV saved → {path}  ({len(results)} rows)")


def save_json(results: List[TestResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([r.to_dict() for r in results], fh, indent=2, ensure_ascii=False)
    logger.info(f"JSON saved → {path}  ({len(results)} entries)")


def print_summary(results: List[TestResult]) -> None:
    total         = len(results)
    successful    = [r for r in results if r.success]
    redirecting   = sum(1 for r in successful if r.is_redirecting)

    proto_counts: dict = {}
    country_counts: dict = {}
    latencies: list = []

    for r in successful:
        proto_counts[r.config.protocol] = proto_counts.get(r.config.protocol, 0) + 1
        if r.is_redirecting:
            if r.country:
                country_counts[r.country] = country_counts.get(r.country, 0) + 1
            if r.latency_ms:
                latencies.append(r.latency_ms)

    bar = "=" * 52
    print(f"\n{bar}")
    print(f"  PAVE — Results Summary")
    print(bar)
    print(f"  Total tested   : {total}")
    pct = f"{len(successful)/total*100:.1f}%" if total else "—"
    print(f"  Reachable      : {len(successful)} ({pct})")
    pct2 = f"{redirecting/total*100:.1f}%" if total else "—"
    print(f"  Redirecting    : {redirecting} ({pct2})")

    blacklisted = sum(1 for r in successful if r.is_blacklisted)

    if successful:
        print(f"\n  Blacklisted IPs  : {blacklisted}")

    if proto_counts:
        print(f"\n  Protocol breakdown (working):")
        for proto, cnt in sorted(proto_counts.items(), key=lambda x: -x[1]):
            print(f"    {proto:<10} {cnt}")

    if country_counts:
        top = sorted(country_counts.items(), key=lambda x: -x[1])[:10]
        print(f"\n  Top exit countries:")
        for country, cnt in top:
            print(f"    {country:<25} {cnt}")

    if latencies:
        avg = sum(latencies) / len(latencies)
        mn  = min(latencies)
        mx  = max(latencies)
        print(f"\n  Latency (working configs):")
        print(f"    avg={avg:.0f}ms  min={mn:.0f}ms  max={mx:.0f}ms")

    if successful:
        n_succ    = len(successful)
        proxy_det = sum(1 for r in successful if r.proxy_detected)
        ipv6_cap  = sum(1 for r in successful if r.ipv6_exit_ip)
        ipv6_leak = sum(1 for r in successful if r.ipv6_leak)
        print(f"\n  Security (working configs):")
        print(f"    Proxy-detected by ip-api   : {proxy_det} ({proxy_det/n_succ*100:.1f}%)")
        print(f"    IPv6-capable exits         : {ipv6_cap} ({ipv6_cap/n_succ*100:.1f}%)")
        if ipv6_leak:
            print(f"    IPv6 leak (country mismatch): {ipv6_leak}")

    print(bar)
