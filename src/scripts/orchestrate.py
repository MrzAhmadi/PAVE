#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent


def _uid_gid() -> str:
    return f"{os.getuid()}:{os.getgid()}"


def _docker_compose_run(extra_args: list[str], log_path: Path, prefix: str = "") -> int:
    cmd = ["docker", "compose", "run", "--rm", f"--user={_uid_gid()}", "pave"] + extra_args
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=SRC_DIR,
        )
        for line in proc.stdout:
            log.write(line)
            log.flush()
            print(f"{prefix}{line}", end="", flush=True)
        proc.wait()
    return proc.returncode


def _build_image() -> None:
    print("[setup] Ensuring Docker image is up to date...")
    subprocess.run(
        ["docker", "compose", "build", "--quiet", "pave"],
        check=True,
        cwd=SRC_DIR,
    )
    print("[setup] Image ready.\n")


def _create_output_dirs(outdir: Path, containers: int) -> None:
    (outdir / "logs").mkdir(parents=True, exist_ok=True)
    for i in range(containers):
        (outdir / f"shard_{i}").mkdir(parents=True, exist_ok=True)
    (outdir / "merged").mkdir(parents=True, exist_ok=True)


def _prefetch(outdir: Path) -> tuple[int, Path]:
    config_file = outdir / "configs_deduped.txt"
    print("[fetch] Fetching and deduplicating all subscription configs...")
    rc = _docker_compose_run(
        ["-i", "/subs/subscriptions.txt", "--fetch-only", "/results/configs_deduped.txt"],
        log_path=outdir / "logs" / "fetch.log",
    )
    if rc != 0 or not config_file.exists():
        print(f"ERROR: Pre-fetch failed — {config_file} not created.")
        sys.exit(1)
    total = len([l for l in config_file.read_text(encoding="utf-8").splitlines() if l.strip()])
    print(f"\n[fetch] Done — {total} unique configs ready.\n")
    return total, config_file


def _run_shard(
    i: int,
    containers: int,
    workers: int,
    outdir: Path,
    progress_interval: int,
    limit: int | None,
    timeout: int | None = None,
) -> int:
    args = [
        "--config-file", "/results/configs_deduped.txt",
        "-w", str(workers),
        "-f", "both",
        "-o", f"/results/shard_{i}",
        "--shards", str(containers),
        "--shard", str(i),
        "--progress-interval", str(progress_interval),
    ]
    if limit is not None:
        args.extend(["-l", str(limit)])
    if timeout is not None:
        args.extend(["--timeout", str(timeout)])
    return _docker_compose_run(
        args,
        log_path=outdir / "logs" / f"shard_{i}.log",
        prefix=f"[shard {i}] ",
    )


def _merge_results(containers: int, outdir: Path) -> None:
    merge_script = Path(__file__).parent / "merge_results.py"
    subprocess.run(
        [
            sys.executable, str(merge_script),
            "--shards", str(containers),
            "--input-dir", str(outdir),
            "--output-dir", str(outdir / "merged"),
        ],
        check=True,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Orchestrate parallel Docker PAVE runs.")
    p.add_argument("containers", type=int, nargs="?", default=12,
                   help="Number of parallel Docker containers (default: 12).")
    p.add_argument("limit", type=int, nargs="?", default=None,
                   help="Optional config limit per shard (smoke test).")
    p.add_argument("--workers", type=int, default=50,
                   help="Concurrent workers per container (default: 50).")
    p.add_argument("--outdir", type=Path, default=Path("config_results"),
                   help="Host output directory (default: config_results).")
    p.add_argument("--progress-interval", type=int, default=250,
                   help="Log summary every N configs per container (default: 250).")
    p.add_argument("--timeout", type=int, default=None, metavar="SEC",
                   help="Per-config connection timeout in seconds (default: 6).")
    args = p.parse_args()

    outdir = args.outdir
    if not outdir.is_absolute():
        outdir = SRC_DIR / outdir

    start = time.time()
    sep = "=" * 40
    print(sep)
    print(" PAVE — Parallel Container Run")
    print(f" Containers : {args.containers}")
    print(f" Workers    : {args.workers} each ({args.containers * args.workers} total concurrent)")
    print(f" Output dir : {outdir}/")
    print(sep + "\n")

    _build_image()
    _create_output_dirs(outdir, args.containers)
    total_configs, config_file = _prefetch(outdir)

    approx = (total_configs + args.containers - 1) // args.containers
    print(f"Launching {args.containers} containers (~{approx} configs each)...")
    print(f"(progress logged every {args.progress_interval} configs per container)")
    print(f"(full logs → {outdir}/logs/shard_N.log)\n")

    failed = 0
    with ThreadPoolExecutor(max_workers=args.containers) as pool:
        future_map = {
            pool.submit(
                _run_shard, i, args.containers, args.workers,
                outdir, args.progress_interval, args.limit, args.timeout,
            ): i
            for i in range(args.containers)
        }
        for future in as_completed(future_map):
            i = future_map[future]
            rc = future.result()
            if rc != 0:
                print(f"WARNING: shard {i} exited with code {rc}.")
                failed += 1

    elapsed = int(time.time() - start)
    mins, secs = divmod(elapsed, 60)

    print(f"\n{sep}")
    print(" All containers finished.")
    print(f" Failures   : {failed} / {args.containers}")
    print(f" Elapsed    : {mins}m {secs}s")
    print(" Merging results...")
    print(sep)

    _merge_results(args.containers, outdir)

    print(f"\n{sep}")
    print(f" Done!  Total time: {mins}m {secs}s")
    print(f" Results → {outdir}/merged/results.csv")
    print(f"         → {outdir}/merged/results.json")
    print(f" Shard logs → {outdir}/logs/")
    print(f" Config list → {config_file}")
    print(sep)


if __name__ == "__main__":
    main()
