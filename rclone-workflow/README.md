# rclone_workflow.py

A Python wrapper that chains three operations in sequence, aborting immediately on any failure:

1. **md5sum** — checksum the source before touching anything
2. **copy** — transfer files to the destination
3. **verify** — checksum the destination and compare against the step 1 checksums

The verify step never re-reads the source, so it works correctly even when the source is a flaky or slow network drive. Only files missing from the destination or with hash mismatches are reported as errors — pre-existing files at the destination are ignored.

Both the log and checksum files are timestamped and written to the log directory.

The workflow is **resumable**: if it is interrupted at any step, re-run the same command and it continues from where it stopped (see [Resuming an interrupted run](#resuming-an-interrupted-run)).

## Requirements

- Python 3.10+
- [`rclone`](https://rclone.org/install/) on your `PATH`

## Usage

```
python rclone_workflow.py <source> <destination> [--dry-run] [--log-dir DIR] [--restart] [extra rclone flags...]
```

| Argument | Description |
|---|---|
| `source` | Local path or rclone remote, e.g. `/data/photos` or `gdrive:folder` |
| `destination` | Local path or rclone remote |
| `--dry-run`, `-n` | Simulate the copy; skips md5sum and verify steps |
| `--log-dir DIR` | Where to write log, checksum and progress files (default: current directory). Use the same directory when resuming |
| `--restart` | Discard saved progress for this source/destination and start a fresh run |
| `...` | Any additional flags are forwarded directly to `rclone copy` and the verify steps |

## Examples

```bash
# Basic copy
python rclone_workflow.py /data/photos gdrive:backup

# Preview what would be transferred
python rclone_workflow.py /data/photos gdrive:backup --dry-run

# Throttle bandwidth and increase parallelism
python rclone_workflow.py /data/photos gdrive:backup --bwlimit 10M --transfers 8

# Write logs to a specific directory
python rclone_workflow.py /data/photos gdrive:backup --log-dir /var/log/rclone

# Combine: custom log dir and extra rclone flags
python rclone_workflow.py /data/photos gdrive:backup --log-dir /var/log/rclone --bwlimit 10M
```

## Output files

Each run produces these files in the log directory (skipped in dry-run mode):

| File | Contents |
|---|---|
| `rclone_YYYYMMDD_HHMMSS.log` | Full log of all steps and rclone output (a resumed run appends to the same log) |
| `rclone_YYYYMMDD_HHMMSS.md5` | MD5 checksums of the source tree, taken before the copy. Assembled from per-folder chunks and renamed into place only when complete, so a file with this name is always whole |
| `rclone_YYYYMMDD_HHMMSS.md5.chunks/` | Temporary folder holding one checksum file per top-level source folder while step 1 runs. Deleted automatically when step 1 finishes; if you see one, a run was interrupted in step 1 |
| `rclone_YYYYMMDD_HHMMSS_dest.md5` | MD5 checksums of the copied files at the destination, taken after the copy. Appended as it goes, so it may be partial after an interruption |
| `rclone_<jobid>.state.json` | Progress record for this source/destination pair (which steps are done). `<jobid>` is a hash of the source and destination |

Dry runs produce `rclone_YYYYMMDD_HHMMSS_dryrun.log` only and never read or write progress state.

> **Note:** Use a local directory for `--log-dir` wherever possible. If the log directory is on a network path and the connection drops, the script may hang on any write to the log or checksum files.

## Default rclone flags

These are applied automatically and can be overridden via extra flags:

| Flag | Applied to | Value | Purpose |
|---|---|---|---|
| `--checkers` | copy only | 8 | Parallel checksum goroutines |
| `--retries` | copy only | 3 | Retry failed transfers |
| `--stats` | copy only | 10s | Print progress every 10 seconds |
| `--transfers` | copy only | 4 | Parallel file transfers |
| `--progress` | copy only | — | Show live transfer stats |

The destination verify step (step 3a) uses Python's `hashlib` directly and does not invoke rclone.

## verify_copy.py

A standalone script for verifying a destination against a source checksum file produced by `rclone_workflow.py`. Useful for re-verifying a previous copy at any time, or when the full workflow cannot be re-run.

### Usage

```
python verify_copy.py <destination> <source_checksums> [--log-dir DIR] [--resume FILE]
```

| Argument | Description |
|---|---|
| `destination` | The destination path or rclone remote to checksum |
| `source_checksums` | The `.md5` file produced by `rclone_workflow.py` step 1 |
| `--log-dir DIR` | Where to write the destination checksum file and log (default: current directory) |
| `--resume FILE` | Partial `verify_*_dest.md5` file from an interrupted run; files already hashed in it are not re-read |

### Example

```bash
python verify_copy.py \\libdata.hamilton.edu\Data\ rclone_20260611_114946.md5 --log-dir C:\logs

# Continue an interrupted verification
python verify_copy.py \\libdata.hamilton.edu\Data\ rclone_20260611_114946.md5 --resume C:\logs\verify_20260612_090000_dest.md5
```

### Output files

| File | Contents |
|---|---|
| `verify_YYYYMMDD_HHMMSS.log` | Full log of the verification run |
| `verify_YYYYMMDD_HHMMSS_dest.md5` | MD5 checksums of the copied files at the destination |

### What it checks

The script computes MD5 checksums directly using Python for each file listed in the source checksum file, reading them from the destination path. The destination directory is never enumerated and pre-existing content is never read. It reports:

- Files present in the source checksums but **missing** from the destination
- Files present in both but with **different hashes**

Files at the destination that are not in the source checksum file (e.g. pre-existing content) are silently ignored. Verification is always against a snapshot in time — if the source has changed since the checksum file was created, those changes will not be reflected.

> **Note:** Use a local directory for `--log-dir`. If the log directory is on a network path and the connection drops, the script may hang.

---

## Resuming an interrupted run

Progress is saved to `rclone_<jobid>.state.json` after each step. If the run is interrupted — Ctrl+C, a dropped network connection, a killed process — re-run **the same command** (same source, destination, `--log-dir` and rclone flags):

| Interrupted during | On re-run |
|---|---|
| Step 1 (source md5sum) | Step 1 continues. The source is checksummed one top-level folder at a time, so only the folder that was in progress is redone; finished folders are reused |
| Step 2 (copy) | Step 1 is skipped and its checksums reused. The copy re-runs; `rclone copy` only transfers what is still missing or different. An interrupted file restarts from the beginning |
| Step 3a (destination checksums) | Steps 1 and 2 are skipped. Files already hashed are not re-read. A truncated last line is discarded |
| Step 3b (comparison) | Steps 1 and 2 are skipped and the destination checksums are reused |

Notes:

- **Step 1 granularity.** The unit of progress is a top-level folder of the source (plus one unit for files sitting directly in the source root). A source with one enormous top-level folder gets little benefit, because that folder is a single unit. The list of folders is saved when step 1 first runs and reused on resume, so a folder added to the source afterwards is not in the snapshot. Use `--restart` to pick it up.
- **Same flags required.** If the extra rclone flags differ from those the unfinished run was started with, the script refuses to resume, since filters change what the source snapshot contains. Re-run with the original flags, or add `--restart`.
- **Finished runs don't resume.** Re-running a command whose last run completed starts a new run.
- **Verification failure.** If step 3b finds missing files or hash mismatches, the copy and verify steps are marked pending. Re-running the command re-copies (only what is missing or changed) and re-verifies against the *same* source snapshot. Use `--restart` to take a new snapshot instead. Note that a file the copy skipped because its size and modification time matched cannot be repaired by re-copying; add `--checksum` on the original run if that matters.
- **Source changes.** The step 1 snapshot is reused on resume. If the source changed in the meantime, the differences will be reported by the verify step. Use `--restart` to take a fresh snapshot.
- **Interrupt handling.** On Ctrl+C, SIGTERM or Ctrl+Break the script stops the running rclone process, logs where it was, and exits with code 130. A hard kill of the Python process (for example from Task Manager) cannot clean up, so check for a stray `rclone` process; the saved progress is still safe to resume from.
- **Starting over.** `--restart` deletes the saved progress for that source/destination. Old checksum and log files are left in place.

## Behaviour on failure

Steps 1 and 2 abort immediately on any non-zero rclone exit code, leaving the destination in whatever state it reached. The script exits with **rclone's own exit code**, and the log explains what it means (for example, `3` is "directory not found", which is also what rclone reports when a source or destination drive or share disappears mid-run). Progress is saved, and the log ends with a reminder to re-run the same command to resume.

The script's own exit code for an interruption (Ctrl+C, SIGTERM, Ctrl+Break) is `130`, always preceded by an `INTERRUPTED during …` message.

Step 3a (destination checksum) continues to the comparison step even if some files could not be checksummed — a warning is logged and the comparison proceeds with whatever was successfully hashed. Step 3b (comparison) exits with code 1 if any files are missing or have hash mismatches.

## Attribution

This script was created with assistance from Claude Sonnet 4.6 (claude.ai).

## License
**Code** `(rclone_workflow.py, verify_copy.py)`:

Copyright (C) 2026 Kim Hoffman, Hamilton College LITS.

Licensed under the GNU General Public License, version 3 or any later version.

Full text: https://www.gnu.org/licenses/gpl-3.0.html

**This document:**

Copyright (C) 2026 Kim Hoffman, Hamilton College LITS.

Licensed under the GNU Free Documentation License, version 1.3 or any later version, with no Invariant Sections, no Front-Cover Texts, and no Back-Cover Texts.

Full text: https://www.gnu.org/licenses/fdl.html
