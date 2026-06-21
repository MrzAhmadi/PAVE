"""PAVE command-line interface — `pave run -s FILE`."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from importlib.resources import files as _res_files
from pathlib import Path

from pave import __version__

IMAGE = "pave:latest"
BAR   = "─" * 52


# ── docker helpers ────────────────────────────────────────────────────────────

def _uid_gid() -> str:
    return f"{os.getuid()}:{os.getgid()}"


def _image_exists() -> bool:
    r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    return r.returncode == 0


def _build_image(verbose: bool) -> None:
    print("[build] Building Docker image …")
    docker_dir = Path(str(_res_files("pave._docker")))
    pave_src   = Path(str(_res_files("pave")))

    with tempfile.TemporaryDirectory(prefix="pave_build_") as _tmp:
        tmp = Path(_tmp)
        shutil.copy2(docker_dir / "Dockerfile",      tmp / "Dockerfile")
        shutil.copy2(docker_dir / "requirements.txt", tmp / "requirements.txt")
        shutil.copy2(docker_dir / "entrypoint.py",   tmp / "entrypoint.py")
        shutil.copytree(
            pave_src, tmp / "pave",
            ignore=shutil.ignore_patterns("_docker", "cli.py", "__pycache__", "*.pyc"),
        )
        cmd = ["docker", "build", "-t", IMAGE, str(tmp)]
        if not verbose:
            cmd += ["--quiet"]
        subprocess.run(cmd, check=True)

    print("[build] Done.\n")


def _docker_run(subs: Path, outdir: Path, pave_args: list[str],
                log_path: Path, prefix: str = "") -> int:
    cmd = [
        "docker", "run", "--rm",
        f"--user={_uid_gid()}",
        "-v", f"{subs}:/subs/subscriptions.txt:ro",
        "-v", f"{outdir}:/results",
        IMAGE,
    ] + pave_args

    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in proc.stdout:
            log.write(line)
            log.flush()
            print(f"{prefix}{line}", end="", flush=True)
        proc.wait()
    return proc.returncode


# ── pipeline stages ───────────────────────────────────────────────────────────

def _fetch(subs: Path, outdir: Path, verbose: bool) -> int:
    print("[fetch] Fetching and deduplicating subscription configs …")
    pave_args = ["-i", "/subs/subscriptions.txt",
                 "--fetch-only", "/results/configs_deduped.txt"]
    if verbose:
        pave_args.append("--verbose")
    rc = _docker_run(subs, outdir, pave_args, log_path=outdir / "logs" / "fetch.log")
    config_file = outdir / "configs_deduped.txt"
    if rc != 0 or not config_file.exists():
        sys.exit("ERROR: fetch failed — no configs written.")
    total = sum(1 for ln in config_file.read_text(encoding="utf-8").splitlines() if ln.strip())
    print(f"[fetch] Done — {total:,} unique configs ready.\n")
    return total


def _run_shard(i: int, args: argparse.Namespace, subs: Path, outdir: Path) -> int:
    pave_args = [
        "--config-file",       "/results/configs_deduped.txt",
        "-w",                  str(args.workers),
        "-f",                  args.format,
        "-o",                  f"/results/shard_{i}",
        "--shards",            str(args.containers),
        "--shard",             str(i),
        "--progress-interval", str(args.progress_interval),
    ]
    if args.limit           is not None: pave_args += ["-l",                str(args.limit)]
    if args.timeout         is not None: pave_args += ["--timeout",         str(args.timeout)]
    if args.tcp_timeout     is not None: pave_args += ["--tcp-timeout",     str(args.tcp_timeout)]
    if args.startup_timeout is not None: pave_args += ["--startup-timeout", str(args.startup_timeout)]
    if args.verbose:                     pave_args.append("--verbose")
    return _docker_run(
        subs, outdir, pave_args,
        log_path=outdir / "logs" / f"shard_{i}.log",
        prefix=f"[{i:02d}] ",
    )


def _merge(containers: int, outdir: Path) -> tuple[int, int]:
    all_rows: list[dict] = []
    fieldnames: list[str] = []
    for i in range(containers):
        shard_csv = outdir / f"shard_{i}" / "results.csv"
        if not shard_csv.exists():
            continue
        with open(shard_csv, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if not fieldnames and reader.fieldnames:
                fieldnames = list(reader.fieldnames)
            all_rows.extend(reader)

    with open(outdir / "results.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    with open(outdir / "results.json", "w", encoding="utf-8") as fh:
        json.dump(all_rows, fh, indent=2, ensure_ascii=False)

    working = sum(1 for r in all_rows if r.get("is_redirecting") in ("True", True))
    return len(all_rows), working


def _cleanup_shards(containers: int, outdir: Path) -> None:
    for i in range(containers):
        shard_dir = outdir / f"shard_{i}"
        if shard_dir.exists():
            shutil.rmtree(shard_dir)
    (outdir / "configs_deduped.txt").unlink(missing_ok=True)


# ── argument parser ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="pave",
        description="PAVE — Proxy Analysis and Verification Engine",
    )
    root.add_argument("--version", action="version", version=f"pave {__version__}")

    sub = root.add_subparsers(dest="command", metavar="<command>")

    run = sub.add_parser(
        "run",
        help="Fetch, test, and export proxy configs",
        description="Fetch, deduplicate, and test proxy configs in parallel Docker containers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  pave run -s subscriptions.txt
  pave run -s subs.txt -n 20 -o results/run-01
  pave run -s subs.txt -n 2 -l 50 -w 10
  pave run -s subs.txt -n 20 --timeout 20 --no-build
""",
    )

    req = run.add_argument_group("required")
    req.add_argument("-s", "--subs", type=Path, required=True, metavar="FILE",
                     help="Subscriptions file (one URL per line, # = comment)")

    g = run.add_argument_group("scale")
    g.add_argument("-n", "--containers", type=int, default=12, metavar="N",
                   help="Parallel Docker containers (default: 12)")
    g.add_argument("-w", "--workers", type=int, default=50, metavar="N",
                   help="Concurrent workers per container (default: 50)")

    g = run.add_argument_group("output")
    g.add_argument("-o", "--outdir", type=Path, default=None, metavar="DIR",
                   help="Results directory (default: results/YYYY-MM-DD_HH-MM)")
    g.add_argument("-f", "--format", choices=["csv", "json", "both"], default="both",
                   help="Output format (default: both)")
    g.add_argument("-l", "--limit", type=int, default=None, metavar="N",
                   help="Max configs per shard — useful for smoke tests")

    g = run.add_argument_group("timeouts")
    g.add_argument("--timeout", type=int, default=None, metavar="SEC",
                   help="curl connection timeout per config (default: 15)")
    g.add_argument("--tcp-timeout", type=int, default=None, metavar="SEC",
                   help="TCP reachability pre-check timeout (default: 2)")
    g.add_argument("--startup-timeout", type=int, default=None, metavar="SEC",
                   help="Proxy binary startup timeout — xray/hy2/sing-box (default: 3)")

    g = run.add_argument_group("behaviour")
    g.add_argument("--progress-interval", type=int, default=250, metavar="N",
                   help="Log a progress line every N configs per container (default: 250)")
    g.add_argument("--no-build", action="store_true",
                   help="Skip Docker image build")
    g.add_argument("-v", "--verbose", action="store_true",
                   help="DEBUG-level logging inside containers")

    # ── pave serve ────────────────────────────────────────────────────────────
    serve = sub.add_parser(
        "serve",
        help="Open the results dashboard in your browser",
        description="Serve the PAVE web dashboard and open it in your browser.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  pave serve                          # open dashboard (upload CSV manually)
  pave serve -r results/              # load results dir automatically
  pave serve -r results/run-01 -p 9000
""",
    )
    serve.add_argument("-r", "--results", type=Path, default=None, metavar="DIR",
                       help="Results directory to serve (e.g. results/2024-01-01_12-00)")
    serve.add_argument("-p", "--port", type=int, default=8000, metavar="PORT",
                       help="Port to listen on (default: 8000)")
    serve.add_argument("--no-browser", action="store_true",
                       help="Do not open browser automatically")

    # ── pave version ──────────────────────────────────────────────────────────
    sub.add_parser(
        "version",
        help="Show version and environment info",
    )

    return root


# ── commands ──────────────────────────────────────────────────────────────────

def _cmd_run(args: argparse.Namespace) -> None:
    subs = args.subs.resolve()
    if not subs.exists():
        sys.exit(f"ERROR: subscriptions file not found: {subs}")

    ts     = datetime.now().strftime("%Y-%m-%d_%H-%M")
    outdir = (args.outdir or Path("results") / ts).resolve()
    (outdir / "logs").mkdir(parents=True, exist_ok=True)
    for i in range(args.containers):
        (outdir / f"shard_{i}").mkdir(exist_ok=True)

    print(BAR)
    print("  PAVE — Parallel Proxy Verification")
    print(f"  Subscriptions   : {subs}")
    print(f"  Containers      : {args.containers}")
    print(f"  Workers         : {args.workers} × {args.containers} = {args.workers * args.containers} total")
    print(f"  Output          : {outdir}/")
    if args.timeout:         print(f"  Conn timeout    : {args.timeout}s")
    if args.tcp_timeout:     print(f"  TCP timeout     : {args.tcp_timeout}s")
    if args.startup_timeout: print(f"  Startup timeout : {args.startup_timeout}s")
    if args.limit:           print(f"  Limit           : {args.limit} configs/shard  [smoke-test]")
    print(BAR + "\n")

    if not args.no_build or not _image_exists():
        _build_image(args.verbose)

    total     = _fetch(subs, outdir, args.verbose)
    per_shard = (total + args.containers - 1) // args.containers
    print(f"Launching {args.containers} containers (~{per_shard:,} configs each) …")
    print(f"Progress every {args.progress_interval} configs  ·  logs → {outdir}/logs/\n")

    failed = 0
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.containers) as pool:
        futures = {pool.submit(_run_shard, i, args, subs, outdir): i
                   for i in range(args.containers)}
        for fut in as_completed(futures):
            i = futures[fut]
            if fut.result() != 0:
                print(f"WARNING: shard {i} exited non-zero.")
                failed += 1

    elapsed    = int(time.monotonic() - t0)
    mins, secs = divmod(elapsed, 60)

    print(f"\n{BAR}")
    print(f"  {args.containers} containers finished  ({failed} failed)  {mins}m {secs}s")
    print("  Merging results and cleaning up …")
    print(BAR)

    total_rows, working = _merge(args.containers, outdir)
    _cleanup_shards(args.containers, outdir)

    print(f"\n{BAR}")
    print(f"  Done — {mins}m {secs}s total")
    print(f"  Configs tested : {total_rows:,}  ({working:,} working)")
    print(f"  CSV            → {outdir}/results.csv")
    print(f"  JSON           → {outdir}/results.json")
    print(f"  Logs           → {outdir}/logs/")
    print(BAR)


def _cmd_version(_args: argparse.Namespace) -> None:
    import platform
    print(f"pave        {__version__}")
    print(f"python      {platform.python_version()}")
    r = subprocess.run(["docker", "--version"], capture_output=True, text=True)
    docker_ver = r.stdout.strip().removeprefix("Docker version ") if r.returncode == 0 else "not found"
    print(f"docker      {docker_ver}")


def _cmd_serve(args: argparse.Namespace) -> None:
    import mimetypes
    import socketserver
    import webbrowser
    from http.server import BaseHTTPRequestHandler

    webapp_dir  = Path(str(_res_files("pave._webapp")))
    results_dir = args.results.resolve() if args.results else None
    port        = args.port

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            raw = self.path.split("?")[0].split("#")[0]
            if results_dir and raw.startswith("/results/"):
                rel       = raw[len("/results/"):]
                file_path = results_dir / rel.lstrip("/")
            else:
                file_path = webapp_dir / (raw.lstrip("/") or "index.html")
            try:
                data = file_path.read_bytes()
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                self.send_error(404)
                return
            mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    url = f"http://localhost:{port}"
    print(BAR)
    print("  PAVE Dashboard")
    print(f"  URL      : {url}")
    if results_dir:
        print(f"  Results  : {results_dir}")
    else:
        print("  Results  : none — use the Upload button in the browser")
    print("  Stop     : Ctrl+C")
    print(BAR + "\n")

    if not args.no_browser:
        webbrowser.open(url)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), _Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    if args.command == "run":     _cmd_run(args)
    if args.command == "serve":   _cmd_serve(args)
    if args.command == "version": _cmd_version(args)


if __name__ == "__main__":
    main()
