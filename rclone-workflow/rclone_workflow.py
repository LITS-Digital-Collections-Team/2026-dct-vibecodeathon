#!/usr/bin/env python3
"""
rclone_workflow.py
Chains: md5sum → copy → verify
Exits immediately on any step failure.

Resumable: progress is recorded in a per-job state file in the log directory.
If the run is interrupted (Ctrl+C, network drop, killed process), re-run the
same command and it picks up at the step that did not finish. Use --restart
to discard saved progress and start over.

Usage:
    python rclone_workflow.py <source> <destination> [options]

Examples:
    python rclone_workflow.py /data/photos gdrive:backup
    python rclone_workflow.py /data/photos gdrive:backup --dry-run
    python rclone_workflow.py /data/photos gdrive:backup --bwlimit 10M --transfers 8
    python rclone_workflow.py /data/photos gdrive:backup --restart
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
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
    "--stats", "10s",
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

EXIT_INTERRUPTED = 130
# rclone's documented exit codes. This script passes them through unchanged, so
# the code shown in "FAILED (exit code N)" is rclone's, not the script's.
# (The script's own code for an interruption is EXIT_INTERRUPTED.)
RCLONE_EXIT_CODES = {
    1: "error not otherwise categorised",
    2: "syntax or usage error",
    3: "directory not found (also seen when a source or destination drive/share "
       "disappears mid-run)",
    4: "file not found",
    5: "temporary error (retrying may fix it)",
    6: "less serious errors that are not retried",
    7: "fatal error that retrying will not fix (e.g. account suspended)",
    8: "transfer limit exceeded (--max-transfer)",
    9: "operation successful but no files transferred",
    10: "duration limit exceeded (--max-duration)",
}
_CHECKSUM_LINE = re.compile(r"^[0-9a-fA-F]{32}  .+")


def _is_network_path(path: Path) -> bool:
    """Return True if path is a UNC/network path (e.g. \\\\server\\share)."""
    s = str(path.resolve())
    return s.startswith("\\\\") or s.startswith("//")


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="rclone workflow: md5sum → copy → verify (resumable)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("source",      help="Source path or rclone remote (e.g. /data or gdrive:folder)")
    parser.add_argument("destination", help="Destination path or rclone remote")
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Pass --dry-run to copy — skips md5sum and verify steps entirely "
             "(no progress is saved)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=LOG_DIR,
        metavar="DIR",
        help="Directory for log, checksum and progress files (default: current directory). "
             "Use the same directory when resuming.",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Discard saved progress for this source/destination and start a fresh run",
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
        # FileHandler appends, so a resumed run continues the same log file.
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


# ── Interrupt handling ────────────────────────────────────────────────────────
def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def install_signal_handlers() -> None:
    """Turn SIGTERM / SIGBREAK / SIGHUP into KeyboardInterrupt so every
    interruption takes the same clean-up path as Ctrl+C."""
    for name in ("SIGTERM", "SIGBREAK", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _raise_interrupt)
            except (ValueError, OSError):
                pass


def _terminate(proc: subprocess.Popen) -> None:
    """Stop a child process, escalating to kill if it ignores terminate."""
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    except OSError:
        pass


# ── Job state (resume support) ────────────────────────────────────────────────
STEPS = ("checksum_source", "copy", "verify")
STATE_VERSION = 1


class JobState:
    """
    Progress record for one source/destination pair, saved as JSON in the log
    directory. Every update is written atomically (temp file + rename), so a
    crash never leaves a half-written state file.
    """

    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data

    @staticmethod
    def path_for(log_dir: Path, source: str, destination: str) -> Path:
        job_id = hashlib.sha1(f"{source}\0{destination}".encode("utf-8")).hexdigest()[:12]
        return (log_dir / f"rclone_{job_id}.state.json").resolve()

    @classmethod
    def new(cls, path: Path, source: str, destination: str,
            extra_flags: list[str], timestamp: str) -> "JobState":
        return cls(path, {
            "version": STATE_VERSION,
            "source": source,
            "destination": destination,
            "extra_flags": list(extra_flags),
            "timestamp": timestamp,
            "steps": {step: "pending" for step in STEPS},
        })

    @classmethod
    def load(cls, path: Path) -> "JobState":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
            raise ValueError("unsupported or malformed state file")
        for key in ("source", "destination", "extra_flags", "timestamp"):
            if key not in data:
                raise ValueError(f"missing field {key!r}")
        steps = data.get("steps")
        if not isinstance(steps, dict) or set(steps) != set(STEPS):
            raise ValueError("missing or malformed 'steps'")
        return cls(path, data)

    @property
    def timestamp(self) -> str:
        return self.data["timestamp"]

    @property
    def extra_flags(self) -> list[str]:
        return self.data["extra_flags"]

    @property
    def complete(self) -> bool:
        return all(self.is_done(s) for s in STEPS)

    def is_done(self, step: str) -> bool:
        return self.data["steps"][step] == "done"

    def mark(self, step: str) -> None:
        self.data["steps"][step] = "done"
        self.save()

    def reset(self, *steps: str) -> None:
        for step in steps:
            self.data["steps"][step] = "pending"
        self.save()

    def save(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


def open_job(args: argparse.Namespace, state_path: Path) -> tuple[JobState, bool, list[str]]:
    """
    Load saved progress for this source/destination, or start a new job.
    Returns (state, resumed, notes). Exits with an error if the saved state is
    unreadable or was created with different rclone flags.
    """
    notes: list[str] = []
    flags = args.extra_flags or []

    if args.restart and state_path.exists():
        state_path.unlink()
        notes.append(f"--restart: discarded saved progress ({state_path})")

    if state_path.exists():
        try:
            state = JobState.load(state_path)
        except (OSError, ValueError) as e:
            print(f"ERROR: cannot read saved progress {state_path}: {e}\n"
                  "Re-run with --restart to discard it and start over.", file=sys.stderr)
            sys.exit(1)
        if state.complete:
            notes.append("Previous run for this source/destination finished; starting a new run.")
        elif state.extra_flags != flags:
            print("ERROR: an unfinished run exists for this source/destination but was "
                  "started with different rclone flags.\n"
                  f"  saved  : {' '.join(state.extra_flags) or '(none)'}\n"
                  f"  current: {' '.join(flags) or '(none)'}\n"
                  "Re-run with the same flags to resume, or add --restart to start over.",
                  file=sys.stderr)
            sys.exit(1)
        else:
            return state, True, notes

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    state = JobState.new(state_path, args.source, args.destination, flags, timestamp)
    return state, False, notes


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
        is_check: bool = False,
        warn_only: bool = False,
        resume_hint: str | None = None) -> int:
    """
    Run a shell command and stream its output live to the terminal and log.
    - stderr is always streamed live (rclone progress/stats).
    - stdout is streamed live to the terminal when stdout_path is None.
    - When stdout_path is given, stdout is written directly to that file
      without buffering in memory (used for md5sum on large trees).
    - Set is_copy=True for `rclone copy` and is_check=True for `rclone md5sum`
      (destination verify step) so that exit code 1 (completed with errors) is
      distinguished from higher exit codes (did not complete successfully).
    - Set warn_only=True to log errors and return the exit code instead of
      aborting, allowing the caller to decide how to proceed.
    - On failure, the meaning of rclone's exit code is logged, followed by
      resume_hint (if given) telling the user how to continue.
    - If the run is interrupted (KeyboardInterrupt), the child process is
      terminated before the exception propagates.
    Returns the exit code. Exits the process on non-zero unless warn_only=True.
    """
    log.info("=== %s ===", label)
    log.info("Command: %s", " ".join(cmd))

    stderr_lines: list[str] = []

    # Open with newline="\n" to write Unix line endings on Windows.
    stdout_dest = open(stdout_path, "w", newline="\n") if stdout_path else subprocess.PIPE

    try:
        with subprocess.Popen(cmd, stdout=stdout_dest, stderr=subprocess.PIPE,
                              text=True, bufsize=1) as proc:
            try:
                if stdout_path is None:
                    t_out = threading.Thread(
                        target=_drain,
                        args=(proc.stdout, log.info, [], True),
                        daemon=True,
                    )
                    t_out.start()
                t_err = threading.Thread(
                    target=_drain,
                    args=(proc.stderr, log.info, stderr_lines, True),
                    daemon=True,
                )
                t_err.start()
                if stdout_path is None:
                    t_out.join()
                t_err.join()
                rc = proc.wait()
            except BaseException:
                # Interrupted (Ctrl+C, SIGTERM, ...): don't leave rclone running.
                _terminate(proc)
                raise
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
        meaning = RCLONE_EXIT_CODES.get(rc)
        if meaning:
            log.error("rclone exit code %d: %s.", rc, meaning)
        if resume_hint:
            log.error("%s", resume_hint)
        if warn_only:
            return rc
        sys.exit(rc)

    log.info("OK\n")
    return 0


# ── Checksum comparison ───────────────────────────────────────────────────────
def compare_checksums(source_file: Path, dest_file: Path, log: logging.Logger) -> bool:
    """
    Compare source and destination checksum files and report discrepancies.

    Only flags:
      - Files in source missing from destination (not copied or lost)
      - Files in both with different hashes (corrupted or modified in transit)

    Files present at the destination but absent from source are intentionally
    ignored, so pre-existing destination content does not cause false errors.

    Returns True if every source file was verified, False otherwise.
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
        return True

    log.error(
        "Step 3b: verification FAILED — %d file(s) missing, %d hash mismatch(es) "
        "out of %d source files. "
        "Pre-existing destination-only files are not counted.",
        len(missing), len(mismatches), len(source),
    )
    return False


# ── Source checksumming (chunked, resumable) ──────────────────────────────────
def _as_filter_rules(filter_flags: list[str]) -> list[str]:
    """Convert ['--exclude', 'X', ...] pairs to ordered ['--filter', '- X', ...] rules.

    Per-folder checksumming needs an include rule alongside the excludes, and
    rclone parses --include and --exclude in an indeterminate order when mixed.
    Ordered --filter rules are first-match-wins, so the excludes reliably win."""
    prefixes = {"--exclude": "- ", "--include": "+ ", "--filter": ""}
    rules: list[str] = []
    it = iter(filter_flags)
    for flag in it:
        if flag not in prefixes:
            raise ValueError(f"unsupported filter flag in DEFAULT_FILTER_FLAGS/run exclusions: {flag}")
        rules += ["--filter", prefixes[flag] + next(it)]
    return rules


def _glob_escape(name: str) -> str:
    """Escape characters that rclone treats as filter wildcards."""
    return re.sub(r"([\\*?\[\]{}])", r"\\\1", name)


def checksum_source_chunked(
    source: str,
    chunks_dir: Path,
    out_file: Path,
    partial_file: Path,
    exclude_flags: list[str],
    log: logging.Logger,
    resume_hint: str | None = None,
) -> int:
    """
    Checksum the source one top-level folder at a time so an interruption only
    costs the folder that was in progress.

    The source's top-level folders are listed once and saved to a manifest in
    chunks_dir. Each folder (plus one chunk for files directly in the source
    root) is hashed with its own `rclone md5sum` into <n>.md5; chunks that
    already exist are skipped on resume. When every chunk is done they are
    concatenated into partial_file, which is renamed to out_file.

    Paths in each chunk are relative to the source root, so merging is plain
    concatenation. Returns the total number of checksum lines written.
    """
    chunks_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = chunks_dir / "manifest.json"
    rules = _as_filter_rules(exclude_flags)

    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            folders: list[str] = json.load(f)["folders"]
        log.info("Step 1: using saved listing of %d top-level folder(s).", len(folders))
    else:
        listing = chunks_dir / "listing.txt"
        run(["rclone", "lsf", source, "--dirs-only"] + rules,
            "Step 1: list top-level folders", log,
            stdout_path=listing, resume_hint=resume_hint)
        with open(listing, "r", newline="") as f:
            folders = [ln.rstrip("\r\n").rstrip("/") for ln in f if ln.strip()]
        tmp = manifest_path.with_name(manifest_path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"folders": folders}, f, indent=2)
        os.replace(tmp, manifest_path)
        log.info("Step 1: found %d top-level folder(s).", len(folders))

    # Chunk 0 is the files sitting directly in the source root; the rest are folders.
    jobs: list[tuple[str, list[str]]] = [
        ("(files in the source root)", ["--max-depth", "1"] + rules),
    ]
    for name in folders:
        jobs.append((name, rules + ["--filter", f"+ /{_glob_escape(name)}/**", "--filter", "- **"]))

    total = len(jobs)
    skipped = 0
    for i, (label, filt) in enumerate(jobs):
        chunk = chunks_dir / f"{i:05d}.md5"
        if chunk.exists():
            skipped += 1
            continue
        part = chunk.with_name(chunk.name + ".partial")
        print(f"  [{i + 1}/{total}] {label}", flush=True)
        run(["rclone", "md5sum", source] + filt,
            f"Step 1: md5sum source [{i + 1}/{total}] {label}", log,
            stdout_path=part, resume_hint=resume_hint)
        os.replace(part, chunk)
    if skipped:
        log.info("Step 1: %d of %d chunk(s) were already done and were skipped.", skipped, total)

    lines = 0
    with open(partial_file, "wb") as out:
        for i in range(total):
            with open(chunks_dir / f"{i:05d}.md5", "rb") as f:
                data = f.read()
            lines += data.count(b"\n")
            out.write(data)
    os.replace(partial_file, out_file)
    return lines


# ── Destination checksumming ──────────────────────────────────────────────────
def recover_partial_checksums(dest_checksum_file: Path, log: logging.Logger) -> set[str]:
    """
    Read a destination checksum file left behind by an interrupted run and
    return the set of relative paths already hashed.

    Only complete, well-formed lines are kept. A truncated final line (the run
    was killed mid-write) or any malformed line is dropped, and the file is
    rewritten without it so new results can be appended safely.
    """
    if not dest_checksum_file.exists():
        return set()

    good: list[str] = []
    dropped = 0
    with open(dest_checksum_file, "r", newline="") as f:
        for raw in f:
            if raw.endswith("\n") and _CHECKSUM_LINE.match(raw.rstrip("\r\n")):
                good.append(raw)
            else:
                dropped += 1

    if dropped:
        log.warning("Dropped %d incomplete line(s) from the partial destination checksum file.", dropped)
        with open(dest_checksum_file, "w", newline="\n") as f:
            f.writelines(good)

    return {line.rstrip("\r\n").split("  ", 1)[1] for line in good}


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
    touched. This avoids the path-filtering limitations of rclone --files-from
    on Windows/SMB paths.

    Resumable: each result is appended and flushed to dest_checksum_file as it
    is computed. If the file already exists from an interrupted run, files
    already hashed are skipped.

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
    already = recover_partial_checksums(dest_checksum_file, log)
    if already:
        log.info("Resuming: %d of %d destination files already checksummed.", len(already), total)
    log.info("Computing MD5 checksums for %d destination files...", total - len(already))
    dest  = Path(dest_root)
    errors = 0
    report_every = max(1, total // 100)   # log progress ~every 1%

    with open(dest_checksum_file, "a", newline="\n") as out:
        for i, rel_path in enumerate(paths, 1):
            if rel_path not in already:
                full_path = dest / Path(rel_path)
                try:
                    h = hashlib.md5()
                    with open(full_path, "rb") as fh:
                        while chunk := fh.read(4 * 1024 * 1024):
                            h.update(chunk)
                    out.write(f"{h.hexdigest()}  {rel_path}\n")
                    out.flush()
                except OSError as e:
                    log.warning("Cannot checksum %s: %s", rel_path, e)
                    errors += 1

            if i % report_every == 0 or i == total:
                log.info("  %d / %d files  (%d%%)...", i, total, i * 100 // total)

    return errors


# ── Workflow ──────────────────────────────────────────────────────────────────
def main() -> None:
    if not shutil.which("rclone"):
        print("ERROR: rclone not found on PATH. Install it from https://rclone.org/install/", file=sys.stderr)
        sys.exit(1)

    args = parse_args()
    install_signal_handlers()

    if _is_network_path(args.log_dir):
        print(
            "WARNING: --log-dir is a network path. If the network becomes unavailable "
            "the script may hang on any log or checksum file write. "
            "Consider using a local directory instead (e.g. --log-dir C:\\logs).",
            file=sys.stderr,
        )

    # Dry runs never read or write progress state.
    state: JobState | None = None
    resumed = False
    notes: list[str] = []
    if args.dry_run:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    else:
        state_path = JobState.path_for(args.log_dir, args.source, args.destination)
        state, resumed, notes = open_job(args, state_path)
        timestamp = state.timestamp

    log, log_file = setup_logging(args.log_dir, args.dry_run, timestamp)

    dry_run_flags       = ["--dry-run"] if args.dry_run else []
    checksum_file       = (args.log_dir / f"rclone_{timestamp}.md5").resolve()
    checksum_partial    = checksum_file.with_name(checksum_file.name + ".partial")
    checksum_chunks_dir = checksum_file.with_name(checksum_file.name + ".chunks")
    dest_checksum_file  = (args.log_dir / f"rclone_{timestamp}_dest.md5").resolve()

    # Exclude this run's own log, checksum and progress files from copy, source
    # md5sum, and destination md5sum so they don't appear as false errors if
    # log_dir is inside the source or destination tree.
    run_exclusions = [
        "--exclude", log_file.name,
        "--exclude", checksum_file.name,
        "--exclude", checksum_partial.name,
        "--exclude", checksum_chunks_dir.name + "/**",
        "--exclude", dest_checksum_file.name,
    ]
    if state is not None:
        run_exclusions += [
            "--exclude", state.path.name,
            "--exclude", state.path.name + ".tmp",
        ]

    copy_flags = DEFAULT_COPY_FLAGS + DEFAULT_FILTER_FLAGS + run_exclusions + dry_run_flags + (args.extra_flags or [])

    for note in notes:
        log.info("%s", note)
    if state is not None:
        try:
            state.save()
        except OSError as e:
            log.error("Cannot write progress file %s: %s", state.path, e)
            sys.exit(1)

    log.info("rclone workflow starting%s", "  [DRY RUN — no files will be transferred]" if args.dry_run else "")
    if resumed:
        log.info("RESUMING an interrupted run (started %s):", timestamp)
        for step in STEPS:
            log.info("  %-16s %s", step, "done — will be skipped" if state.is_done(step) else "pending")
    log.info("  Source              : %s", args.source)
    log.info("  Destination         : %s", args.destination)
    log.info("  Copy flags          : %s", " ".join(copy_flags))
    log.info("  Source checksum file: %s", checksum_file)
    log.info("  Dest checksum file  : %s", dest_checksum_file)
    log.info("  Log file            : %s", log_file)
    if state is not None:
        log.info("  Progress file       : %s", state.path)
    log.info("")

    resume_hint = (
        "Progress is saved. Fix the cause (for example, reconnect the drive or share), "
        "then re-run the same command to resume from this step."
    )

    current = "starting up"
    try:
        # Step 1 — checksum the source before touching anything (skipped in dry run).
        # Written to a .partial file and renamed only on success, so an
        # interrupted run can never leave a truncated file under the real name.
        current = "Step 1 (md5sum source)"
        if args.dry_run:
            log.info("Step 1: md5sum source — skipped (dry run)\n")
        elif state.is_done("checksum_source") and checksum_file.exists():
            log.info("Step 1: md5sum source — already done, reusing %s\n", checksum_file)
            print(f"\n[Step 1/3] Already done. Reusing {checksum_file}", flush=True)
        else:
            print("\n[Step 1/3] Checksumming source one top-level folder at a time "
                  "(this may take a while for large trees)...", flush=True)
            n_files = checksum_source_chunked(
                args.source, checksum_chunks_dir, checksum_file, checksum_partial,
                DEFAULT_FILTER_FLAGS + run_exclusions, log, resume_hint,
            )
            state.mark("checksum_source")
            shutil.rmtree(checksum_chunks_dir, ignore_errors=True)
            log.info("Checksums for %d file(s) saved -> %s\n", n_files, checksum_file)
            print(f"[Step 1/3] Done. Checksums saved -> {checksum_file}", flush=True)

        # Step 2 — copy source to destination. `rclone copy` is idempotent, so
        # re-running an interrupted copy only transfers what is still missing.
        current = "Step 2 (copy)"
        if not args.dry_run and state.is_done("copy"):
            log.info("Step 2: copy — already done\n")
            print("\n[Step 2/3] Already done.", flush=True)
        else:
            print("\n[Step 2/3] Copying files...", flush=True)
            if not args.dry_run:
                # Any destination checksums on disk predate this copy; discard them.
                dest_checksum_file.unlink(missing_ok=True)
            run(
                ["rclone", "copy", args.source, args.destination] + copy_flags,
                "Step 2: copy" + (" [DRY RUN]" if args.dry_run else ""),
                log,
                is_copy=True,
                resume_hint=None if args.dry_run else resume_hint,
            )
            if not args.dry_run:
                state.mark("copy")
            print("[Step 2/3] Done.", flush=True)

        # Step 3 — verify destination against pre-computed source checksums.
        # Step 3a checksums the destination (source is never re-read) and can
        # resume part-way through. Step 3b compares the two checksum files in
        # Python, flagging only files that are missing or corrupted —
        # pre-existing destination files are ignored.
        current = "Step 3 (verify)"
        if args.dry_run:
            log.info("Step 3: verify — skipped (dry run)\n")
        else:
            print("\n[Step 3a/3] Checksumming destination files (progress logged every 1%)...", flush=True)
            log.info("=== Step 3a: checksum destination ===")
            errors = checksum_destination(args.destination, checksum_file, dest_checksum_file, log)
            log.info("Destination checksums saved -> %s\n", dest_checksum_file)
            print(f"[Step 3a/3] Done. Destination checksums saved -> {dest_checksum_file}", flush=True)
            if errors > 0:
                log.warning(
                    "Step 3a completed with %d error(s) — some destination files could not be "
                    "checksummed (see above). Step 3b will compare only the files that were "
                    "successfully hashed; results may be incomplete.",
                    errors,
                )

            print("\n[Step 3b/3] Comparing checksums...", flush=True)
            if not compare_checksums(checksum_file, dest_checksum_file, log):
                # Make the next run re-copy (idempotent) and re-verify instead of
                # re-reading the same stale destination checksums.
                dest_checksum_file.unlink(missing_ok=True)
                state.reset("copy", "verify")
                log.error(
                    "Verification failed. Re-run the same command to re-copy and re-verify "
                    "against the saved source checksums, or add --restart to take a new "
                    "source snapshot."
                )
                sys.exit(1)
            state.mark("verify")
            print("[Step 3b/3] Done.", flush=True)

    except KeyboardInterrupt:
        log.warning("")
        log.warning("INTERRUPTED during %s.", current)
        if state is not None:
            log.warning("Progress is saved. Re-run the same command to resume: %s", state.path)
        sys.exit(EXIT_INTERRUPTED)

    log.info("Workflow complete%s. Log -> %s", " (dry run)" if args.dry_run else "", log_file)


if __name__ == "__main__":
    main()
