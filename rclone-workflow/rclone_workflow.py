#!/usr/bin/env python3
"""
rclone_workflow.py
Chains: md5sum → copy → check
Exits immediately on any step failure.

Usage:
    python rclone_workflow.py <source> <destination> [options]

Examples:
    python rclone_workflow.py /data/photos gdrive:backup
    python rclone_workflow.py /data/photos gdrive:backup --dry-run
    python rclone_workflow.py /data/photos gdrive:backup --bwlimit 10M --transfers 8
"""

import argparse
import shutil
import subprocess
import sys
import logging
import threading
from datetime import datetime
from pathlib import Path

# ── Default flags ──────────────────────────────────────────────────────────────
# Shared: applied to both `rclone copy` and `rclone check`
DEFAULT_SHARED_FLAGS = [
    "--checkers", "8",
    "--retries", "3",
]
# Copy-only: applied only to `rclone copy`
DEFAULT_COPY_FLAGS = DEFAULT_SHARED_FLAGS + [
    "--progress",
    "--transfers", "4",
]

LOG_DIR = Path(".")   # directory to write log and checksum files


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="rclone workflow: md5sum → copy → check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("source",      help="Source path or rclone remote (e.g. /data or gdrive:folder)")
    parser.add_argument("destination", help="Destination path or rclone remote")
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Pass --dry-run to copy and check — no files are transferred or deleted",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=LOG_DIR,
        metavar="DIR",
        help="Directory for log and checksum files (default: current directory)",
    )
    args, extra_flags = parser.parse_known_args()
    args.extra_flags = extra_flags
    return args


# ── Logging setup ─────────────────────────────────────────────────────────────
def setup_logging(log_dir: Path, dry_run: bool, timestamp: str) -> tuple[logging.Logger, Path]:
    suffix    = "_dryrun" if dry_run else ""
    log_file  = (log_dir / f"rclone_{timestamp}{suffix}.log").resolve()

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
    except OSError as e:
        print(f"ERROR: cannot write log to {log_file.resolve()}: {e}", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            file_handler,
        ],
    )
    return logging.getLogger(__name__), log_file


# ── Helpers ───────────────────────────────────────────────────────────────────
def _drain(stream, log_fn, collect: list[str], live: bool) -> None:
    """Read lines from *stream*, log each one, optionally print live."""
    for line in iter(stream.readline, ""):
        stripped = line.rstrip()
        if stripped:
            log_fn(stripped)
            collect.append(stripped)
            if live:
                print(stripped, flush=True)
    stream.close()


def run(cmd: list[str], label: str, log: logging.Logger,
        stdout_path: Path | None = None) -> None:
    """
    Run a shell command and stream its output live to the terminal and log.
    - stderr is always streamed live (rclone progress/stats).
    - stdout is streamed live to the terminal when stdout_path is None.
    - When stdout_path is given, stdout is written directly to that file
      without buffering in memory (used for md5sum on large trees).
    Exits the process immediately if the command returns a non-zero exit code.
    """
    log.info("=== %s ===", label)
    log.info("Command: %s", " ".join(cmd))

    stderr_lines: list[str] = []

    stdout_dest = open(stdout_path, "w") if stdout_path else subprocess.PIPE

    try:
        with subprocess.Popen(cmd, stdout=stdout_dest, stderr=subprocess.PIPE,
                              text=True, bufsize=1) as proc:
            if stdout_path is None:
                stdout_lines: list[str] = []
                t_out = threading.Thread(
                    target=_drain,
                    args=(proc.stdout, log.info, stdout_lines, True),
                )
                t_out.start()
            t_err = threading.Thread(
                target=_drain,
                args=(proc.stderr, log.info, stderr_lines, True),
            )
            t_err.start()
            if stdout_path is None:
                t_out.join()
            t_err.join()
            rc = proc.wait()
    finally:
        if stdout_path:
            stdout_dest.close()

    if rc != 0:
        log.error("FAILED (exit code %d) — aborting.", rc)
        sys.exit(rc)

    log.info("OK\n")


# ── Workflow ──────────────────────────────────────────────────────────────────
def main() -> None:
    if not shutil.which("rclone"):
        print("ERROR: rclone not found on PATH. Install it from https://rclone.org/install/", file=sys.stderr)
        sys.exit(1)

    args      = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log, log_file = setup_logging(args.log_dir, args.dry_run, timestamp)

    dry_run_flags = ["--dry-run"] if args.dry_run else []
    copy_flags    = DEFAULT_COPY_FLAGS + dry_run_flags + (args.extra_flags or [])

    log.info("rclone workflow starting%s", "  [DRY RUN — no files will be transferred]" if args.dry_run else "")
    log.info("  Source      : %s", args.source)
    log.info("  Destination : %s", args.destination)
    log.info("  Copy flags  : %s", " ".join(copy_flags))
    log.info("  Log file    : %s\n", log_file)

    # Step 1 — checksum the source before touching anything (skipped in dry run)
    if args.dry_run:
        log.info("Step 1: md5sum source — skipped (dry run)\n")
    else:
        checksum_file = (args.log_dir / f"rclone_{timestamp}.md5").resolve()
        run(
            ["rclone", "md5sum", args.source],
            "Step 1: md5sum source",
            log,
            stdout_path=checksum_file,
        )
        log.info("Checksums saved -> %s\n", checksum_file)

    # Step 2 — copy source to destination
    run(
        ["rclone", "copy", args.source, args.destination] + copy_flags,
        "Step 2: copy" + (" [DRY RUN]" if args.dry_run else ""),
        log,
    )

    # Step 3 — verify source and destination match (skipped in dry run)
    if args.dry_run:
        log.info("Step 3: check — skipped (dry run)\n")
    else:
        run(
            ["rclone", "check", args.source, args.destination]
            + DEFAULT_SHARED_FLAGS + (args.extra_flags or []),
            "Step 3: check",
            log,
        )

    log.info("Workflow complete%s. Log -> %s", " (dry run)" if args.dry_run else "", log_file)



if __name__ == "__main__":
    main()
