#!/usr/bin/env python3

import argparse
import logging
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from configprobe.config import MAX_WORKERS
from configprobe.fetcher import fetch_subscription
from configprobe.models import ProxyConfig
from configprobe.parser import parse_config
from configprobe.reporter import print_summary, save_csv, save_json
from configprobe.tester import run_tests


def deduplicate(configs: List[ProxyConfig]) -> List[ProxyConfig]:
    seen_raw:  set = set()
    seen_cred: set = set()
    out: List[ProxyConfig] = []

    for cfg in configs:
        if cfg.raw in seen_raw:
            continue
        seen_raw.add(cfg.raw)

        key = cfg.dedup_key
        if key in seen_cred:
            continue
        seen_cred.add(key)

        out.append(cfg)

    return out


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="configprobe",
        description="Fetch, deduplicate, test and analyse free proxy configs.",
    )
    p.add_argument(
        "-i", "--input",
        type=Path, default=None, metavar="FILE",
        help="Text file containing subscription URLs, one per line (# lines are comments).",
    )
    p.add_argument(
        "-u", "--url",
        action="append", default=[], metavar="URL",
        help="Extra subscription URL(s) to include (repeatable).",
    )
    p.add_argument(
        "--fetch-only",
        type=Path, default=None, metavar="FILE",
        help="Fetch & deduplicate all configs, write raw URLs to FILE, then exit.",
    )
    p.add_argument(
        "--config-file",
        type=Path, default=None, metavar="FILE",
        help="Load pre-fetched deduped configs from FILE instead of fetching subscriptions.",
    )
    p.add_argument(
        "-l", "--limit",
        type=int, default=None, metavar="N",
        help="Max configs to test after deduplication (omit = test all).",
    )
    p.add_argument(
        "-w", "--workers",
        type=int, default=MAX_WORKERS, metavar="N",
        help=f"Concurrent test workers (default: {MAX_WORKERS}).",
    )
    p.add_argument(
        "-o", "--output",
        type=Path, default=None, metavar="DIR",
        help="Output directory (default: results/YYYY-MM-DD_HH-MM/).",
    )
    p.add_argument(
        "-f", "--format",
        choices=["csv", "json", "both"], default="csv",
        help="Output format (default: csv).",
    )
    p.add_argument(
        "--timeout",
        type=int, default=None, metavar="SEC",
        help="Per-config connection timeout in seconds.",
    )
    p.add_argument(
        "--shards",
        type=int, default=1, metavar="N",
        help="Total number of parallel containers sharing the work (default: 1).",
    )
    p.add_argument(
        "--shard",
        type=int, default=0, metavar="I",
        help="Index of THIS container's slice, 0-based (default: 0).",
    )
    p.add_argument(
        "--progress-interval",
        type=int, default=1, metavar="N",
        help="Log a summary line every N configs tested (1 = log every config).",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return p


def _read_url_file(path: Path) -> List[str]:
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def _fetch_all(args) -> Tuple[List[ProxyConfig], dict]:
    raw_entries: List[Tuple[str, str]] = []

    if args.input:
        if not args.input.exists():
            logging.error(f"Input file not found: {args.input}")
            return [], {}
        file_urls = _read_url_file(args.input)
        if not file_urls:
            logging.error(f"No valid URLs found in {args.input}")
            return [], {}
        logging.info(f"Loaded {len(file_urls)} subscription URL(s) from {args.input}")
        for url in file_urls:
            raw_entries.extend(fetch_subscription(url, source_name=url))

    for url in args.url:
        raw_entries.extend(fetch_subscription(url, source_name=url))

    if not raw_entries:
        logging.error("No configs fetched — check your internet connection.")
        return [], {}

    total_raw = len(raw_entries)

    unique_raw: List[Tuple[str, str]] = []
    seen_lines: set = set()
    for raw, src in raw_entries:
        if raw not in seen_lines:
            seen_lines.add(raw)
            unique_raw.append((raw, src))
    raw_dupes = total_raw - len(unique_raw)

    configs: List[ProxyConfig] = []
    parse_failures = 0
    for raw, source in unique_raw:
        cfg = parse_config(raw, source=source)
        if cfg:
            configs.append(cfg)
        else:
            parse_failures += 1

    before_cred = len(configs)
    configs = deduplicate(configs)
    cred_dupes = before_cred - len(configs)

    stats = {
        "total_raw":      total_raw,
        "raw_dupes":      raw_dupes,
        "parse_failures": parse_failures,
        "before_cred":    before_cred,
        "cred_dupes":     cred_dupes,
        "final":          len(configs),
    }
    return configs, stats


def _print_fetch_stats(stats: dict):
    print(f"Fetched  : {stats['total_raw']} raw lines  ({stats['raw_dupes']} exact duplicates removed)")
    print(f"Parsed   : {stats['before_cred']} valid  ({stats['parse_failures']} unparseable)")
    print(f"Unique   : {stats['final']} configs after credential-level dedup  ({stats['cred_dupes']} same-server duplicates removed)")


def main() -> int:
    args = build_arg_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.timeout is not None:
        import configprobe.config as cfg_mod
        cfg_mod.CONNECTION_TIMEOUT = args.timeout

    if args.fetch_only:
        if not args.input and not args.url:
            logging.error("--fetch-only requires -i FILE or -u URL to know where to fetch from.")
            return 1
        configs, stats = _fetch_all(args)
        if not configs:
            return 1
        out = args.fetch_only
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            for cfg in configs:
                fh.write(cfg.raw + "\n")
        print()
        _print_fetch_stats(stats)
        print(f"\nWrote    : {stats['final']} configs → {out}")
        return 0

    if args.config_file:
        if not args.config_file.exists():
            logging.error(f"Config file not found: {args.config_file}")
            return 1
        raw_lines = [
            l.strip()
            for l in args.config_file.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        configs: List[ProxyConfig] = []
        for raw in raw_lines:
            cfg = parse_config(raw, source=str(args.config_file))
            if cfg:
                configs.append(cfg)
        configs = deduplicate(configs)
        print(f"\nLoaded   : {len(raw_lines)} lines from {args.config_file}")
        print(f"Parsed   : {len(configs)} valid configs (after dedup)")
    else:
        if not args.input and not args.url:
            logging.error("No input source specified. Use -i FILE, -u URL, or --config-file FILE.")
            return 1
        configs, stats = _fetch_all(args)
        if not configs:
            return 1
        print()
        _print_fetch_stats(stats)

    if not configs:
        logging.error("No unique valid configs to test.")
        return 1

    if args.limit and args.limit < len(configs):
        configs = configs[: args.limit]
        print(f"Limited  : testing first {args.limit} configs")

    if args.shards > 1:
        if not (0 <= args.shard < args.shards):
            logging.error(f"--shard {args.shard} is out of range for --shards {args.shards}")
            return 1
        chunk = math.ceil(len(configs) / args.shards)
        start = args.shard * chunk
        end   = min(start + chunk, len(configs))
        configs = configs[start:end]
        print(f"Shard    : {args.shard + 1}/{args.shards}  → configs [{start}:{end}]  ({len(configs)} to test)")

    print()

    results = run_tests(configs, max_workers=args.workers, progress_interval=args.progress_interval)

    print_summary(results)

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_dir = args.output or Path("results") / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.format in ("csv", "both"):
        save_csv(results, out_dir / "results.csv")
    if args.format in ("json", "both"):
        save_json(results, out_dir / "results.json")

    print(f"\nResults saved to: {out_dir}/")
    return 0 if any(r.is_redirecting for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
