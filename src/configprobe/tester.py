import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import requests

from .config import IP_CHECK_URL, MAX_WORKERS
from .protocols import create_tester
from .models import ProxyConfig, TestResult
from .runners import ensure_hysteria2, ensure_singbox, ensure_xray

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    try:
        return requests.get(IP_CHECK_URL, timeout=10).text.strip()
    except Exception:
        return ""


def run_tests(
    configs: List[ProxyConfig],
    max_workers: int = MAX_WORKERS,
    progress_interval: int = 1,
) -> List[TestResult]:
    xray_bin = ensure_xray()

    hy2_bin = None
    if any(c.protocol == "hysteria2" for c in configs):
        try:
            hy2_bin = ensure_hysteria2()
        except Exception as e:
            logger.warning(f"hysteria2 binary unavailable: {e} — hy2 configs will be skipped")

    singbox_bin = None
    if any(c.protocol in ("tuic", "ssr") for c in configs):
        try:
            singbox_bin = ensure_singbox()
        except Exception as e:
            logger.warning(f"sing-box binary unavailable: {e} — tuic/ssr configs will be skipped")

    local_ip = get_local_ip()
    logger.info(f"Local IP: {local_ip or '(unknown)'}")
    logger.info(f"Testing {len(configs)} configs with {max_workers} worker(s)")

    results: List[TestResult] = []
    working_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(
                create_tester(cfg, local_ip, xray_bin, hy2_bin, singbox_bin).run
            ): cfg
            for cfg in configs
        }
        total = len(future_map)
        done = 0

        for future in as_completed(future_map):
            done += 1
            cfg = future_map[future]
            try:
                res = future.result()
            except Exception as e:
                res = TestResult(config=cfg, local_ip=local_ip, error=str(e))

            results.append(res)
            if res.success:
                working_count += 1

            if progress_interval <= 1:
                _log_progress(done, total, res)
            elif done % progress_interval == 0 or done == total:
                _log_summary(done, total, working_count)

    _enrich_geo(results)
    return results


def _log_progress(done: int, total: int, res: TestResult):
    icon = "✓" if res.success else "✗"
    tail = (
        f" → {res.exit_ip} ({res.latency_ms:.0f}ms)" if res.success
        else f" [{res.error}]"
    )
    logger.info(
        f"[{done:4}/{total}] {icon} "
        f"{res.config.protocol}://{res.config.server}:{res.config.port}{tail}"
    )


def _log_summary(done: int, total: int, working: int):
    pct = done * 100 / total if total else 0
    logger.info(f"[{done:5}/{total}]  {working} working  ({pct:.1f}% tested)")


def _enrich_geo(results: List[TestResult]):
    successful = [r for r in results if r.success and r.exit_ip]
    unique_ips = list({r.exit_ip for r in successful})
    if not unique_ips:
        return

    logger.info(f"Fetching geo info for {len(unique_ips)} unique exit IP(s) (batch mode)...")
    geo_cache: dict = {}
    batch_url = "http://ip-api.com/batch?fields=query,status,country,countryCode,city,org,as,hosting,proxy"
    batch_size = 100

    for i in range(0, len(unique_ips), batch_size):
        batch = unique_ips[i : i + batch_size]
        try:
            resp = requests.post(
                batch_url,
                json=[{"query": ip} for ip in batch],
                timeout=30,
            )
            for item in resp.json():
                if item.get("status") == "success":
                    geo_cache[item["query"]] = {
                        "country":        item.get("country"),
                        "country_code":   item.get("countryCode"),
                        "city":           item.get("city"),
                        "org":            item.get("org"),
                        "asn":            item.get("as"),
                        "is_datacenter":  item.get("hosting", False),
                        "is_blacklisted": item.get("proxy", False),
                    }
        except Exception as e:
            logger.debug(f"Geo batch lookup failed: {e}")

        if i + batch_size < len(unique_ips):
            time.sleep(4)

    for res in successful:
        geo = geo_cache.get(res.exit_ip, {})
        res.country       = geo.get("country")
        res.country_code  = geo.get("country_code")
        res.city          = geo.get("city")
        res.org           = geo.get("org")
        res.asn           = geo.get("asn")
        res.is_datacenter = geo.get("is_datacenter")
        res.is_blacklisted = geo.get("is_blacklisted")
