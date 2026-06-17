import logging
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import requests

from .config import CONNECTION_TIMEOUT, IP_CHECK_URL, MAX_WORKERS, TCP_PRECHECK_TIMEOUT
from .models import ProxyConfig, TestResult
from .runners import Hysteria2Process, XrayProcess, ensure_hysteria2, ensure_xray

logger = logging.getLogger(__name__)

CURL_ERRORS = {
    5:  "SOCKS proxy error",
    6:  "DNS lookup failed",
    7:  "Connection refused",
    28: "Timeout",
    35: "SSL handshake failed",
    56: "Network receive error",
}


def get_local_ip() -> str:
    try:
        resp = requests.get(IP_CHECK_URL, timeout=10)
        return resp.text.strip()
    except Exception:
        return ""


def _tcp_reachable(host: str, port: int) -> bool:
    try:
        socket.inet_pton(socket.AF_INET, host)
    except OSError:
        try:
            socket.inet_pton(socket.AF_INET6, host)
        except OSError:
            return True

    try:
        with socket.create_connection((host, port), timeout=TCP_PRECHECK_TIMEOUT):
            return True
    except OSError:
        return False


def _test_via_curl(
    port: int, timeout: int = CONNECTION_TIMEOUT
) -> tuple[Optional[str], Optional[float], Optional[str]]:
    cmd = [
        "curl", "--silent", "--max-time", str(timeout),
        "--socks5-hostname", f"127.0.0.1:{port}",
        IP_CHECK_URL,
    ]
    t0 = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        elapsed_ms = (time.monotonic() - t0) * 1000
        if result.returncode == 0:
            ip = result.stdout.strip()
            if ip:
                return ip, round(elapsed_ms, 2), None
            return None, None, "Empty response"
        err = CURL_ERRORS.get(result.returncode, f"curl error {result.returncode}")
        return None, None, err
    except subprocess.TimeoutExpired:
        return None, None, "Timeout"
    except Exception as e:
        return None, None, str(e)[:120]


def _test_socks_direct(cfg: ProxyConfig) -> tuple[Optional[str], Optional[float], Optional[str]]:
    p = cfg.params
    user, pw = p.get("username", ""), p.get("password", "")
    proxy = f"{user}:{pw}@{cfg.server}:{cfg.port}" if user else f"{cfg.server}:{cfg.port}"
    cmd = [
        "curl", "--silent", "--max-time", str(CONNECTION_TIMEOUT),
        "--socks5-hostname", proxy,
        IP_CHECK_URL,
    ]
    t0 = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=CONNECTION_TIMEOUT + 2)
        elapsed_ms = (time.monotonic() - t0) * 1000
        if result.returncode == 0:
            ip = result.stdout.strip()
            if ip:
                return ip, round(elapsed_ms, 2), None
        return None, None, CURL_ERRORS.get(result.returncode, f"curl error {result.returncode}")
    except subprocess.TimeoutExpired:
        return None, None, "Timeout"
    except Exception as e:
        return None, None, str(e)[:120]


def test_one(cfg: ProxyConfig, local_ip: str, xray_bin: Path, hy2_bin: Optional[Path] = None) -> TestResult:
    result = TestResult(config=cfg, local_ip=local_ip, timestamp=datetime.utcnow().isoformat())

    if cfg.protocol == "tuic":
        result.error = "Protocol not testable (tuic requires separate client)"
        return result

    if cfg.protocol == "socks":
        exit_ip, latency_ms, err = _test_socks_direct(cfg)
        if exit_ip:
            result.success, result.latency_ms = True, latency_ms
            result.exit_ip = exit_ip
            result.is_redirecting = (exit_ip != local_ip)
        else:
            result.error = err
        return result

    if not _tcp_reachable(cfg.server, cfg.port):
        result.error = "Host unreachable"
        return result

    if cfg.protocol == "hysteria2":
        if hy2_bin is None:
            result.error = "hysteria2 binary not available"
            return result
        runner = Hysteria2Process(cfg, hy2_bin)
        startup_err = "hysteria2 failed to start"
    else:
        runner = XrayProcess(cfg, xray_bin)
        startup_err = "xray failed to start"

    with runner as port:
        if port is None:
            result.error = startup_err
            return result
        exit_ip, latency_ms, err = _test_via_curl(port)

    if exit_ip:
        result.success = True
        result.latency_ms = latency_ms
        result.exit_ip = exit_ip
        result.is_redirecting = (exit_ip != local_ip) and bool(exit_ip)
    else:
        result.error = err

    return result


def run_tests(
    configs: List[ProxyConfig],
    max_workers: int = MAX_WORKERS,
    progress_cb=None,
    progress_interval: int = 1,
) -> List[TestResult]:
    xray_bin = ensure_xray()
    hy2_bin = None
    if any(c.protocol == "hysteria2" for c in configs):
        try:
            hy2_bin = ensure_hysteria2()
        except Exception as e:
            logger.warning(f"hysteria2 binary unavailable: {e} — hy2 configs will be skipped")

    local_ip = get_local_ip()
    logger.info(f"Local IP: {local_ip or '(unknown)'}")
    logger.info(f"Testing {len(configs)} configs with {max_workers} worker(s)")

    results: List[TestResult] = []
    working_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(test_one, cfg, local_ip, xray_bin, hy2_bin): cfg
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

            if progress_cb:
                progress_cb(done, total, res)
            elif progress_interval <= 1:
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
    batch_url = "http://ip-api.com/batch?fields=query,status,country,countryCode,city,org,as,hosting"
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
                        "country":       item.get("country"),
                        "country_code":  item.get("countryCode"),
                        "city":          item.get("city"),
                        "org":           item.get("org"),
                        "asn":           item.get("as"),
                        "is_datacenter": item.get("hosting", False),
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
