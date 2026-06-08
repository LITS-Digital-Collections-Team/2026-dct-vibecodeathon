# rclone_workflow.py

A Python wrapper that chains three `rclone` operations in sequence, aborting immediately on any failure:

1. **md5sum** — checksum the source before touching anything
2. **copy** — transfer files to the destination
3. **check** — verify source and destination match

Both the log and checksum file are timestamped and written to the log directory.

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
| `--dry-run`, `-n` | Simulate the copy; skips md5sum and check steps |
| `--log-dir DIR` | Where to write log and checksum files (default: current directory) |
| `...` | Any additional flags are forwarded directly to `rclone copy` and `rclone check` |

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

Each run produces two timestamped files in the log directory (skipped in dry-run mode):

| File | Contents |
|---|---|
| `rclone_YYYYMMDD_HHMMSS.log` | Full log of all steps and rclone output |
| `rclone_YYYYMMDD_HHMMSS.md5` | MD5 checksums of the source tree pre-copy |

Dry runs produce `rclone_YYYYMMDD_HHMMSS_dryrun.log` only.

## Default rclone flags

These are applied automatically and can be overridden via extra flags:

| Flag | Applied to | Value | Purpose |
|---|---|---|---|
| `--checkers` | copy + check | 8 | Parallel checksum goroutines |
| `--retries` | copy + check | 3 | Retry failed transfers |
| `--transfers` | copy only | 4 | Parallel file transfers |
| `--progress` | copy only | — | Show live transfer stats |

## Behaviour on failure

Any non-zero exit code from `rclone` causes the script to log the error and exit immediately with the same code, leaving the destination in whatever state it reached. The `.md5` checksum file can be used to audit the source after the fact.

## Attribution

This script was created with assistance from Claude Sonnet 4.5 (claude.ai).

## License
**Code** `(rclone_workflow.py)`:

Copyright (C) 2026 Kim Hoffman, Hamilton College LITS.

Licensed under the GNU General Public License, version 3 or any later version.

Full text: https://www.gnu.org/licenses/gpl-3.0.html

**This document:**

Copyright (C) 2026 Kim Hoffman, Hamilton College LITS.

Licensed under the GNU Free Documentation License, version 1.3 or any later version, with no Invariant Sections, no Front-Cover Texts, and no Back-Cover Texts.

Full text: https://www.gnu.org/licenses/fdl.html
