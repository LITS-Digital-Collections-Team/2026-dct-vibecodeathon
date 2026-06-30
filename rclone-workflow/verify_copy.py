#!/usr/bin/env python3
"""
verify_copy.py
Standalone verification script: checksums a destination and compares it against
a pre-computed source checksum file produced by rclone_workflow.py.

Only flags:
  - Files in the source checksum file that are missing from the destination
  - Files present in both with different hashes

Pre-existing destination files (not in the source checksum file) are ignored.

Usage:
    python verify_copy.py <destination> <source_checksums> [options]

Examples:
    python verify_copy.py \\\\libdata.hamilton.edu\\Data\\ rclone_20260611_114946.md5
    python verify_copy.py \\\\libdata.hamilton.edu\\Data\\ rclone_20260611_114946.md5 --log-dir C:\\logs
"""

import argparse
import hashlib
import sys
import logging
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(".")


def _is_network_path(path: Path) -> bool:
    """Return True if path is a UNC/network path (e.g. \\\\server\\share)."""
    s = str(path.resolve())
    return s.startswith("\\\\") or s.startswith("//")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a destination against a pre-computed source checksum file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("destination",      help="Destination path to checksum")
    parser.add_argument("source_checksums", help="Source checksum file (.md5) from rclone_workflow.py step 1")
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=LOG_DIR,
        metavar="DIR",
        help="Directory for the destination checksum file and log (default: current directory)",
    )
    args, _ = parser.parse_known_args()
    return args


def setup_logging(log_dir: Path, timestamp: str) -> tuple[logging.Logger, Path]:
    log_file = (log_dir / f"verify_{timestamp}.log").resolve()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
    except OSError as e:
        print(f"ERROR: cannot write log to {log_file}: {e}", file=sys.stderr)
        sys.exit(1)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), file_handler],
    )
    return logging.getLogger(__name__), log_file


def checksum_destination(
    dest_root: str,
    source_file: Path,
    dest_checksum_file: Path,
    log: logging.Logger,
) -> int:
    """
    Compute MD5 checksums for each file listed in source_file by reading them
    directly from dest_root using Python's hashlib.

    Only the files that were copied (those in source_file) are read — the
    destination directory is never enumerated and pre-existing content is never
    touched.

    Writes results to dest_checksum_file in rclone md5sum format.
    Returns the count of files that could not be checksummed.
    """
    paths: list[str] = []
    with open(source_file, "r", newline="") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = line.split("  ", 1)
            if len(parts) == 2:
                paths.append(parts[1])

    total = len(paths)
    log.info("Computing MD5 checksums for %d destination files...", total)
    dest  = Path(dest_root)
    errors = 0
    report_every = max(1, total // 100)   # log progress ~every 1%

    with open(dest_checksum_file, "w", newline="\n") as out:
        for i, rel_path in enumerate(paths, 1):
            full_path = dest / Path(rel_path)
            try:
                h = hashlib.md5()
                with open(full_path, "rb") as fh:
                    while chunk := fh.read(4 * 1024 * 1024):
                        h.update(chunk)
                out.write(f"{h.hexdigest()}  {rel_path}\n")
            except OSError as e:
                log.warning("Cannot checksum %s: %s", rel_path, e)
                errors += 1

            if i % report_every == 0 or i == total:
                log.info("  %d / %d files  (%d%%)...", i, total, i * 100 // total)

    return errors


def compare_checksums(source_file: Path, dest_file: Path, log: logging.Logger) -> None:
    log.info("=== Step 2: compare checksums ===")

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
            "Verification PASSED — all %d source files present and correct at destination.\n",
            len(source),
        )
    else:
        log.error(
            "Verification FAILED — %d file(s) missing, %d hash mismatch(es) "
            "out of %d source files. "
            "Pre-existing destination-only files are not counted.",
            len(missing), len(mismatches), len(source),
        )
        sys.exit(1)


def main() -> None:
    args      = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if _is_network_path(args.log_dir):
        print(
            "WARNING: --log-dir is a network path. If the network becomes unavailable "
            "the script may hang on any log or checksum file write. "
            "Consider using a local directory instead (e.g. --log-dir C:\\logs).",
            file=sys.stderr,
        )

    log, log_file = setup_logging(args.log_dir, timestamp)

    source_checksums = Path(args.source_checksums).resolve()
    if not source_checksums.exists():
        print(f"ERROR: source checksum file not found: {source_checksums}", file=sys.stderr)
        sys.exit(1)

    dest_checksum_file = (args.log_dir / f"verify_{timestamp}_dest.md5").resolve()

    log.info("verify_copy.py starting")
    log.info("  Destination         : %s", args.destination)
    log.info("  Source checksums    : %s", source_checksums)
    log.info("  Dest checksum file  : %s", dest_checksum_file)
    log.info("  Log file            : %s\n", log_file)

    print("\n[Step 1/2] Checksumming destination files (progress logged every 1%)...", flush=True)
    log.info("=== Step 1: checksum destination ===")
    errors = checksum_destination(args.destination, source_checksums, dest_checksum_file, log)
    log.info("Destination checksums saved -> %s\n", dest_checksum_file)
    print(f"[Step 1/2] Done. Destination checksums saved -> {dest_checksum_file}", flush=True)
    if errors > 0:
        log.warning(
            "Step 1 completed with %d error(s) — some files could not be checksummed "
            "(see above). The comparison will cover only the files that were "
            "successfully hashed; results may be incomplete.",
            errors,
        )

    print("\n[Step 2/2] Comparing checksums...", flush=True)
    compare_checksums(source_checksums, dest_checksum_file, log)
    print("[Step 2/2] Done.", flush=True)

    log.info("Done. Log -> %s", log_file)


if __name__ == "__main__":
    main()
