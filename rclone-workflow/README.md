# rclone_workflow.py

A Python wrapper that chains three operations in sequence, aborting immediately on any failure:

1. **md5sum** — checksum the source before touching anything
2. **copy** — transfer files to the destination
3. **verify** — checksum the destination and compare against the step 1 checksums

The verify step never re-reads the source, so it works correctly even when the source is a flaky or slow network drive. Only files missing from the destination or with hash mismatches are reported as errors — pre-existing files at the destination are ignored.

Both the log and checksum files are timestamped and written to the log directory.

## Requirements

- Python 3.10+
- [`rclone`](https://rclone.org/install/) on your `PATH`

## Usage

```
python rclone_workflow.py <source> <destination> [--dry-run] [--log-dir DIR] [extra rclone flags...]
```

| Argument | Description |
|---|---|
| `source` | Local path or rclone remote, e.g. `/data/photos` or `gdrive:folder` |
| `destination` | Local path or rclone remote |
| `--dry-run`, `-n` | Simulate the copy; skips md5sum and verify steps |
| `--log-dir DIR` | Where to write log and checksum files (default: current directory) |
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

Each run produces three timestamped files in the log directory (skipped in dry-run mode):

| File | Contents |
|---|---|
| `rclone_YYYYMMDD_HHMMSS.log` | Full log of all steps and rclone output |
| `rclone_YYYYMMDD_HHMMSS.md5` | MD5 checksums of the source tree, taken before the copy |
| `rclone_YYYYMMDD_HHMMSS_dest.md5` | MD5 checksums of the copied files at the destination, taken after the copy |

Dry runs produce `rclone_YYYYMMDD_HHMMSS_dryrun.log` only.

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
python verify_copy.py <destination> <source_checksums> [--log-dir DIR] [extra rclone flags...]
```

| Argument | Description |
|---|---|
| `destination` | The destination path or rclone remote to checksum |
| `source_checksums` | The `.md5` file produced by `rclone_workflow.py` step 1 |
| `--log-dir DIR` | Where to write the destination checksum file and log (default: current directory) |

### Example

```bash
python verify_copy.py \\libdata.hamilton.edu\Data\ rclone_20260611_114946.md5 --log-dir C:\logs
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

## Behaviour on failure

Steps 1 and 2 abort immediately on any non-zero rclone exit code, leaving the destination in whatever state it reached. The source `.md5` checksum file can be used to audit the source after the fact.

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
