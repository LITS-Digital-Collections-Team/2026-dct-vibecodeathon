#!/usr/bin/env python3
"""
compare_dirs.py

Walk two or more directories, compute SHA256 hashes for every file,
and report any files whose content is missing from one or more directories.
A file is considered present as long as its hash exists somewhere in the
directory -- its name and location do not need to match.

Useful for verifying that a copy, backup, or delivery is complete.

Usage:
    python compare_dirs.py DIR1 DIR2 [DIR3 ...]
    python compare_dirs.py DIR1 DIR2 --output diff_results.csv

Exit codes:
    0 -- all directories contain the same content (no discrepancies)
    1 -- one or more files are missing from at least one directory

Attribution:
    This script was created with assistance from Claude Sonnet 4.5 (claude.ai).
"""
import csv
import argparse
import hashlib
import os
import sys


# Files to silently skip when scanning directories
IGNORE_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}

# Read files in 64 KB chunks so large files don't load fully into memory
CHUNK_SIZE = 65536


def resolve_output_path(path):
    """Return a confirmed output path, prompting if the file already exists.

    If the given path exists, the user is asked to enter a different name or
    press Enter to overwrite. This repeats until a safe path is chosen or an
    overwrite is confirmed.
    """
    while os.path.exists(path):
        print(f"Output file '{path}' already exists.")
        response = input("  Enter a new filename, or press Enter to overwrite: ").strip()
        if response == '':
            # Empty input -- user confirmed overwrite
            break
        path = response
    return path


def hash_file(path):
    """Compute the SHA256 hash of a file, reading in chunks.

    Chunked reading keeps memory usage flat regardless of file size.
    """
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def scan_directory(dirpath):
    """Recursively walk a directory and return a dict mapping hash -> {FILE_PATH, NAME}.

    FILE_PATH is stored relative to dirpath so paths are comparable across
    different root directories. Files in IGNORE_NAMES are silently skipped.
    Permission errors are warned and skipped rather than crashing the script.
    """
    items = {}

    if not os.path.exists(dirpath):
        print(f"Error: directory not found: {dirpath}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(dirpath):
        print(f"Error: not a directory: {dirpath}", file=sys.stderr)
        sys.exit(1)

    file_count = 0
    for root, dirs, files in os.walk(dirpath):
        dirs.sort()  # Sort for deterministic traversal order
        for name in sorted(files):
            if name in IGNORE_NAMES:
                continue

            abs_path = os.path.join(root, name)
            rel_path = os.path.relpath(abs_path, dirpath)

            try:
                # Show a live progress line that overwrites itself
                print(f"  Scanning {dirpath}: {file_count} files hashed...", end='\r')
                key = hash_file(abs_path)
                file_count += 1

                if key in items:
                    # Two files in the same directory with identical content
                    print(f"\nWarning: duplicate content in {dirpath}: "
                          f"{rel_path} matches {items[key]['FILE_PATH']}")
                else:
                    items[key] = {
                        'FILE_PATH': rel_path,
                        'NAME':      name,
                    }
            except PermissionError:
                print(f"\nWarning: permission denied, skipping: {abs_path}", file=sys.stderr)

    # Print final count on a clean line
    print(f"  Scanned {dirpath}: {file_count} files hashed.       ")
    return items


def build_diff_rows(all_items):
    """Build a truth-table of discrepancies across N directories.

    Args:
        all_items: dict of {dirpath: {hash: {FILE_PATH, NAME}}}

    Returns:
        (rows, dirnames) where each row is a dict with keys:
            sha256_hash, file_path, name, <dir_1>, <dir_2>, ...
        Each directory key is set to 'present' or 'MISSING'.
        Only hashes absent from at least one directory are included.
    """
    dirnames = list(all_items.keys())

    # Union of every hash seen across all directories
    all_hashes = set()
    for items in all_items.values():
        all_hashes.update(items.keys())

    rows = []
    for key in sorted(all_hashes):
        # Check which directories contain this hash
        presence = {d: key in all_items[d] for d in dirnames}

        # Skip hashes present in every directory -- nothing to report
        if not all(presence.values()):
            # Pull metadata from the first directory that has this hash
            sample = next(all_items[d][key] for d in dirnames if key in all_items[d])
            row = {
                'sha256_hash': key,
                'file_path':   sample['FILE_PATH'],
                'name':        sample['NAME'],
            }
            for d in dirnames:
                row[d] = 'present' if presence[d] else 'MISSING'
            rows.append(row)

    return rows, dirnames


def write_csv(output_path, rows, dirnames):
    """Write diff rows to a CSV file.

    Columns: sha256_hash, file_path, name, then one column per input directory
    showing 'present' or 'MISSING'. This truth-table layout is easy to filter
    by directory in Excel or Numbers.
    """
    fieldnames = ['sha256_hash', 'file_path', 'name'] + dirnames
    with open(output_path, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Results written to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Compare two or more directories by file content (SHA256 hash).'
    )
    parser.add_argument('dirs', nargs='+', help='Two or more directories to compare')
    parser.add_argument(
        '--output', '-o',
        help='Write differences to this CSV file (e.g. diff_results.csv)',
        default=None,
    )
    args = parser.parse_args()

    if len(args.dirs) < 2:
        parser.error('At least two directories are required.')

    # Scan each directory and build hash -> file maps
    print("Hashing files...")
    all_items = {d: scan_directory(d) for d in args.dirs}

    # Find hashes missing from one or more directories
    diff_rows, dirnames = build_diff_rows(all_items)

    print()

    # Print one line per discrepancy to stdout
    for r in diff_rows:
        missing_from = [d for d in dirnames if r[d] == 'MISSING']
        print(f"Missing from {', '.join(missing_from)}: {r['file_path']} ({r['sha256_hash']})")

    # Print per-directory summary
    print(f"\nTotal discrepancies: {len(diff_rows)}")
    for d in dirnames:
        count = sum(1 for r in diff_rows if r[d] == 'MISSING')
        print(f"  Missing from {d}: {count}")

    if args.output:
        # Resolve the output path, prompting if the file already exists
        output_path = resolve_output_path(args.output)
        write_csv(output_path, diff_rows, dirnames)

    # Exit 1 if mismatches found so shell scripts and CI can detect failure
    sys.exit(1 if diff_rows else 0)


if __name__ == '__main__':
    main()