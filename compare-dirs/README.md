# compare_dirs.py

Compare two or more directories by file content and report anything missing from one or more of them. Uses MD5 hashing by default (SHA256 also available), so a file is considered present as long as its content exists somewhere in the target directory — the filename and location don't need to match.

Useful for verifying that a backup, copy, or delivery is complete.

## Requirements

Python 3.8 or later. No third-party packages required.

## Usage

```bash
# Compare two directories
python compare_dirs.py /path/to/dir1 /path/to/dir2

# Compare three or more directories
python compare_dirs.py dir1 dir2 dir3

# Save results to a CSV file
python compare_dirs.py dir1 dir2 --output diff_results.csv

# Use SHA256 instead of the default MD5
python compare_dirs.py dir1 dir2 --hash sha256

# Combine options
python compare_dirs.py dir1 dir2 --hash sha256 --output diff_results.csv

# Disable checkpointing (resume support is on by default, see below)
python compare_dirs.py dir1 dir2 --no-checkpoint

# Reuse an existing hash listing for dir1 instead of rehashing its files
python compare_dirs.py dir1 dir2 --import-hashes dir1=dir1_hashes.txt
```

## Output

Results are printed to the terminal, one line per discrepancy:

```
Missing from dir2: images/photo.jpg (a3f1c2d4...)
Missing from dir1: documents/report.pdf (9b8e7f6a...)

Total discrepancies: 2
  Missing from dir1: 1
  Missing from dir2: 1
```

If no discrepancies are found, only the summary is printed:

```
Total discrepancies: 0
  Missing from dir1: 0
  Missing from dir2: 0
```

### CSV output

With `--output`, results are saved as a spreadsheet with one row per discrepancy and one column per directory, showing `present` or `MISSING`:

| md5_hash | file_path | name | dir1 | dir2 |
|---|---|---|---|---|
| a3f1c2d4... | images/photo.jpg | photo.jpg | present | MISSING |
| 9b8e7f6a... | documents/report.pdf | report.pdf | MISSING | present |

The hash column is named `md5_hash` or `sha256_hash` depending on the algorithm used.

If the output file already exists, the script will prompt you to enter a different filename or press Enter to overwrite.

## How it works

The script walks each directory recursively, computing a hash for every file (MD5 by default, or SHA256 with `--hash sha256`). It then compares the sets of hashes and reports any hash that is missing from at least one directory. The following files are silently skipped: `.DS_Store`, `Thumbs.db`, `desktop.ini`.

File paths in the output are stored relative to each directory root, so `sub/folder/file.txt` rather than `/full/path/to/dir1/sub/folder/file.txt`.

## Resuming an interrupted scan

Hashing a large directory, especially over a network share, can take a long time, and the connection can drop partway through. By default, the script saves each file's hash (keyed by its size and modification time) to a checkpoint file as it goes, under `.compare_dirs_checkpoints/` in the current directory. If the scan is interrupted — a network error or Ctrl+C — just re-run the exact same command. Files already recorded in the checkpoint are skipped instead of rehashed, so only new or changed files need to be processed.

```bash
# Use a custom checkpoint location instead of the default .compare_dirs_checkpoints/
python compare_dirs.py dir1 dir2 --checkpoint-dir /path/to/checkpoints

# Turn off checkpointing entirely
python compare_dirs.py dir1 dir2 --no-checkpoint
```

## Importing pre-computed hashes

If you already have a hash listing for one of the directories — say, from a previous `md5sum`/`sha256sum` run, or one of this script's own checkpoint files — you can supply it with `--import-hashes DIR=HASHFILE` to skip rehashing those files entirely:

```bash
python compare_dirs.py dir1 dir2 --import-hashes dir1=dir1_hashes.txt
```

`HASHFILE` can be either a plain text listing in the standard `<hash>  <relative_path>` per-line format, or one of this script's own checkpoint JSON files. `DIR` must match one of the positional directories exactly, and the option can be repeated to supply hashes for more than one directory. Imported hashes are trusted as-is and are not re-verified against file size or modification time, so make sure the listing is still accurate and uses the same hash algorithm as `--hash` (MD5 by default) before relying on it.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | All directories contain the same content |
| `1` | One or more files are missing from at least one directory |
| `2` | Scan was interrupted (e.g. network error or Ctrl+C); re-run the same command to resume |

The exit code makes it easy to use the script in shell scripts or CI pipelines:

```bash
python compare_dirs.py original/ backup/ || echo "Backup is incomplete!"
```

## Attribution

This script was created with assistance from Claude Sonnet 4.5 (claude.ai).

## License
**Code** `(compare_dirs.py)`:

Copyright (C) 2026 Kim Hoffman, Hamilton College LITS.

Licensed under the GNU General Public License, version 3 or any later version.

Full text: https://www.gnu.org/licenses/gpl-3.0.html

**This document:**

Copyright (C) 2026 Kim Hoffman, Hamilton College LITS.

Licensed under the GNU Free Documentation License, version 1.3 or any later version, with no Invariant Sections, no Front-Cover Texts, and no Back-Cover Texts.

Full text: https://www.gnu.org/licenses/fdl.html