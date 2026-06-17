#!/usr/bin/env python3

import argparse
import csv
import json
import logging
from pathlib import Path
from typing import List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


def merge(shards: int, input_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    all_rows: List[dict] = []
    fieldnames: List[str] = []

    for i in range(shards):
        shard_csv = input_dir / f"shard_{i}" / "results.csv"
        if not shard_csv.exists():
            logger.warning(f"Missing shard file: {shard_csv}")
            continue

        with open(shard_csv, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if not fieldnames and reader.fieldnames:
                fieldnames = list(reader.fieldnames)
            for row in reader:
                all_rows.append(row)

        logger.info(f"Shard {i}: loaded {shard_csv}")

    if not all_rows:
        logger.error("No rows found — nothing to merge.")
        return

    csv_out = output_dir / "results.csv"
    with open(csv_out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    json_out = output_dir / "results.json"
    with open(json_out, "w", encoding="utf-8") as fh:
        json.dump(all_rows, fh, indent=2, ensure_ascii=False)

    total   = len(all_rows)
    working = sum(1 for r in all_rows if r.get("is_redirecting") in ("True", True))
    logger.info(f"Merged {shards} shards → {total} rows  ({working} working)")
    logger.info(f"CSV  → {csv_out}")
    logger.info(f"JSON → {json_out}")


def main() -> None:
    p = argparse.ArgumentParser(description="Merge shard CSV results into one file.")
    p.add_argument("--shards",      type=int,  required=True,  help="Number of shards to merge.")
    p.add_argument("--input-dir",   type=Path, default=Path("results"), help="Directory containing shard_N/ folders.")
    p.add_argument("--output-dir",  type=Path, default=None,   help="Output directory (default: <input-dir>/merged).")
    args = p.parse_args()

    output_dir = args.output_dir or args.input_dir / "merged"
    merge(args.shards, args.input_dir, output_dir)


if __name__ == "__main__":
    main()
