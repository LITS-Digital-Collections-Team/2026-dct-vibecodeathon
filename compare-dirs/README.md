# compare_dirs.py

Compare two or more directories by file content and report anything missing from one or more of them. Uses SHA256 hashing, so a file is considered present as long as its content exists somewhere in the target directory — the filename and location don't need to match.

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

| sha256_hash | file_path | name | dir1 | dir2 |
|---|---|---|---|---|
| a3f1c2d4... | images/photo.jpg | photo.jpg | present | MISSING |
| 9b8e7f6a... | documents/report.pdf | report.pdf | MISSING | present |

If the output file already exists, the script will prompt you to enter a different filename or press Enter to overwrite.

## How it works

The script walks each directory recursively, computing a SHA256 hash for every file. It then compares the sets of hashes and reports any hash that is missing from at least one directory. The following files are silently skipped: `.DS_Store`, `Thumbs.db`, `desktop.ini`.

File paths in the output are stored relative to each directory root, so `sub/folder/file.txt` rather than `/full/path/to/dir1/sub/folder/file.txt`.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | All directories contain the same content |
| `1` | One or more files are missing from at least one directory |

The exit code makes it easy to use the script in shell scripts or CI pipelines:

```bash
python compare_dirs.py original/ backup/ || echo "Backup is incomplete!"
```

## Attribution

This script was created with assistance from Claude Sonnet 4.5 (claude.ai).

## License
**Code** |(compare_dirs.py)|:
Copyright (C) 2026 Kim Hoffman, Hamilton College LITS.
Licensed under the GNU General Public License, version 3 or any later version.
Full text: https://www.gnu.org/licenses/gpl-3.0.html

**This document:**
Copyright (C) 2026 Kim Hoffman, Hamilton College LITS.
Licensed under the GNU Free Documentation License, version 1.3 or any later version, with no Invariant Sections, no Front-Cover Texts, and no Back-Cover Texts.
Full text: https://www.gnu.org/licenses/fdl.html