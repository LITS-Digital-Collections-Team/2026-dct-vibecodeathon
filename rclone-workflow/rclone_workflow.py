#!/usr/bin/env python3
"""
rclone_workflow.py
Chains: md5sum → copy → verify
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
# Shared: applied to both `rclone copy` and `rclone md5sum` (verify steps)
DEFAULT_SHARED_FLAGS = [
    "--checkers", "8",
    "--retries", "3",
]
# Filter flags: applied to `rclone copy` and the source md5sum so that
# whatever the copy skips is also absent from the source checksums.
# Add or remove exclusion patterns here as needed.
DEFAULT_FILTER_FLAGS = [
    "--exclude", "Thumbs.db",
    "--exclude", ".DS_Store",
]
# Copy-only: applied only to `rclone copy`
DEFAULT_COPY_FLAGS = DEFAULT_SHARED_FLAGS + [
    "--progress",
    "--transfers", "4",
]

LOG_DIR = Path(".")   # directory to write log and checksum files


def _is_network_path(path: Path) -> bool:
    """Return True if path is a UNC/network path (e.g. \\\\server\\share)."""
    s = str(path.resolve())
    return s.startswith("\\\\") or s.startswith("//")


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="rclone workflow: md5sum → copy → verify",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("source",      help="Source path or rclone remote (e.g. /data or gdrive:folder)")
    parser.add_argument("destination", help="Destination path or rclone remote")
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Pass --dry-run to copy — skips md5sum and verify steps entirely",
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
        stdout_path: Path | None = None,
        is_copy: bool = False,
        is_check: bool = False) -> None:
    """
    Run a shell command and stream its output live to the terminal and log.
    - stderr is always streamed live (rclone progress/stats).
    - stdout is streamed live to the terminal when stdout_path is None.
    - When stdout_path is given, stdout is written directly to that file
      without buffering in memory (used for md5sum on large trees).
    - Set is_copy=True for `rclone copy` and is_check=True for `rclone md5sum`
      (destination verify step) so that exit code 1 (completed with errors) is
      distinguished from higher exit codes (did not complete successfully).
    Exits the process immediately if the command returns a non-zero exit code.
    """
    log.info("=== %s ===", label)
    log.info("Command: %s", " ".join(cmd))

    stderr_lines: list[str] = []

    # Open with newline="\n" to write Unix line endings on Windows.
    stdout_dest = open(stdout_path, "w", newline="\n") if stdout_path else subprocess.PIPE

    try:
        with subprocess.Popen(cmd, stdout=stdout_dest, stderr=subprocess.PIPE,
                              text=True, bufsize=1) as proc:
            if stdout_path is None:
                t_out = threading.Thread(
                    target=_drain,
                    args=(proc.stdout, log.info, [], True),
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
        if is_copy and rc == 1:
            log.error(
                "%s COMPLETED but some files failed to transfer (exit code 1). "
                "rclone exits with code 1 when one or more files could not be copied after retries. "
                "Review the output above for details.",
                label,
            )
        elif is_copy:
            log.error(
                "%s DID NOT COMPLETE SUCCESSFULLY (exit code %d). "
                "The copy encountered an unexpected error and may not have finished. "
                "Review the output above for details.",
                label, rc,
            )
        elif is_check and rc == 1:
            log.error(
                "%s COMPLETED but encountered errors (exit code 1). "
                "Review the output above for details.",
                label,
            )
        elif is_check:
            log.error(
                "%s DID NOT COMPLETE SUCCESSFULLY (exit code %d). "
                "An unexpected error occurred and the step may not have finished. "
                "Review the output above for details.",
                label, rc,
            )
        else:
            log.error("FAILED (exit code %d) — aborting.", rc)
        sys.exit(rc)

    log.info("OK\n")


# ── Checksum comparison ───────────────────────────────────────────────────────
def compare_checksums(source_file: Path, dest_file: Path, log: logging.Logger) -> None:
    """
    Compare source and destination checksum files and report discrepancies.

    Only flags:
      - Files in source missing from destination (not copied or lost)
      - Files in both with different hashes (corrupted or modified in transit)

    Files present at the destination but absent from source are intentionally
    ignored, so pre-existing destination content does not cause false errors.

    Exits with code 1 if any errors are found.
    """
    log.info("=== Step 3b: compare checksums ===")

    def parse(path: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        with open(path, "r", newline="") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                parts = line.split("  ", 1)
                if len(parts) == 2:
                    result[parts[1]] = parts[0].lower()
                else:
                    log.warning("Skipping unparseable line: %s", line)
        return result

    log.info("Parsing source checksums: %s", source_file)
    source = parse(source_file)
    log.info("Parsing dest checksums  : %s", dest_file)
    dest   = parse(dest_file)
    log.info("Source files: %d  |  Dest files: %d\n", len(source), len(dest))

    missing:    list[str] = []
    mismatches: list[str] = []

    for path, src_hash in source.items():
        if path not in dest:
            missing.append(path)
            log.error("MISSING from destination: %s", path)
        elif dest[path] != src_hash:
            mismatches.append(path)
            log.error("HASH MISMATCH: %s  (source: %s  dest: %s)", path, src_hash, dest[path])

    if not missing and not mismatches:
        log.info(
            "Step 3b: all %d source files verified at destination — no errors.\n",
            len(source),
        )
    else:
        log.error(
            "Step 3b: verification FAILED — %d file(s) missing, %d hash mismatch(es) "
            "out of %d source files. "
            "Pre-existing destination-only files are not counted.",
            len(missing), len(mismatches), len(source),
        )
        sys.exit(1)


# ── Workflow ──────────────────────────────────────────────────────────────────
def main() -> None:
    if not shutil.which("rclone"):
        print("ERROR: rclone not found on PATH. Install it from https://rclone.org/install/", file=sys.stderr)
        sys.exit(1)

    args      = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if _is_network_path(args.log_dir):
        print(
            "WARNING: --log-dir is a network path. If the network becomes unavailable "
            "the script may hang on any log or checksum file write. "
            "Consider using a local directory instead (e.g. --log-dir C:\\logs).",
            file=sys.stderr,
        )

    log, log_file = setup_logging(args.log_dir, args.dry_run, timestamp)

    dry_run_flags      = ["--dry-run"] if args.dry_run else []
    checksum_file      = (args.log_dir / f"rclone_{timestamp}.md5").resolve()
    dest_checksum_file = (args.log_dir / f"rclone_{timestamp}_dest.md5").resolve()

    # Exclude this run's own log and checksum files from copy, source md5sum,
    # and destination md5sum so they don't appear as false errors if log_dir
    # is inside the source or destination tree.
    run_exclusions = [
        "--exclude", log_file.name,
        "--exclude", checksum_file.name,
        "--exclude", dest_checksum_file.name,
    ]

    copy_flags   = DEFAULT_COPY_FLAGS + DEFAULT_FILTER_FLAGS + run_exclusions + dry_run_flags + (args.extra_flags or [])
    # verify_flags are used for the destination md5sum (step 3a). run_exclusions
    # are included so the log and checksum files don't appear in the dest checksums
    # and trigger spurious "missing from source" errors in the comparison.
    verify_flags = DEFAULT_SHARED_FLAGS + run_exclusions + (args.extra_flags or [])

    log.info("rclone workflow starting%s", "  [DRY RUN — no files will be transferred]" if args.dry_run else "")
    log.info("  Source              : %s", args.source)
    log.info("  Destination         : %s", args.destination)
    log.info("  Copy flags          : %s", " ".join(copy_flags))
    log.info("  Verify flags        : %s", " ".join(verify_flags))
    log.info("  Source checksum file: %s", checksum_file)
    log.info("  Dest checksum file  : %s", dest_checksum_file)
    log.info("  Log file            : %s\n", log_file)

    # Step 1 — checksum the source before touching anything (skipped in dry run)
    if args.dry_run:
        log.info("Step 1: md5sum source — skipped (dry run)\n")
    else:
        run(
            ["rclone", "md5sum", args.source] + DEFAULT_FILTER_FLAGS + run_exclusions,
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
        is_copy=True,
    )

    # Step 3 — verify destination against pre-computed source checksums.
    # Step 3a checksums the destination (source is never re-read).
    # Step 3b compares the two checksum files in Python, flagging only files
    # that are missing or corrupted — pre-existing destination files are ignored.
    if args.dry_run:
        log.info("Step 3: verify — skipped (dry run)\n")
    else:
        run(
            ["rclone", "md5sum", args.destination] + verify_flags,
            "Step 3a: md5sum destination",
            log,
            stdout_path=dest_checksum_file,
            is_check=True,
        )
        log.info("Destination checksums saved -> %s\n", dest_checksum_file)

        compare_checksums(checksum_file, dest_checksum_file, log)

    log.info("Workflow complete%s. Log -> %s", " (dry run)" if args.dry_run else "", log_file)



if __name__ == "__main__":
    main()
