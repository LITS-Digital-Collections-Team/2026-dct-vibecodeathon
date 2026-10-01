#!/usr/bin/env python3
"""
compare_dirs.py

Walk two or more directories, compute MD5 hashes for every file,
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
import json
import os
import sys


# Files to silently skip when scanning directories
IGNORE_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}

# Read files in 64 KB chunks so large files don't load fully into memory
CHUNK_SIZE = 65536

# Save the checkpoint file to disk after this many newly-hashed files
CHECKPOINT_INTERVAL = 50

# Default location for checkpoint files, used unless --checkpoint-dir or
# --no-checkpoint is given
DEFAULT_CHECKPOINT_DIR = '.compare_dirs_checkpoints'


def checkpoint_path_for(dirpath, checkpoint_dir):
    """Derive a stable checkpoint filename for a scanned directory."""
    safe_name = "".join(c if c.isalnum() else "_" for c in os.path.abspath(dirpath))
    return os.path.join(checkpoint_dir, f"{safe_name}.json")


def load_checkpoint(path):
    """Load a checkpoint file, returning {} if it doesn't exist or is unreadable."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        print(f"Warning: could not read checkpoint {path}, starting fresh.", file=sys.stderr)
        return {}


def save_checkpoint(path, records):
    """Write the checkpoint atomically so a crash mid-write can't corrupt it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(records, f)
    os.replace(tmp_path, path)


def load_external_hashes(path):
    """Load a pre-computed hash listing supplied by the user.

    Supports two formats, auto-detected:
      - This script's own checkpoint JSON: {rel_path: {size, mtime, hash}}
      - Plain md5sum/sha256sum-style text: "<hash>  <rel_path>" per line

    Returns a dict {rel_path: hash}. Hashes from a plain-text listing carry no
    size/mtime, so they are trusted as-is rather than freshness-checked --
    the caller is asserting these hashes are already known-good.
    """
    with open(path, 'r') as f:
        content = f.read()

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return {rel_path: entry['hash'] for rel_path, entry in data.items()}
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    hashes = {}
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        hash_val, rel_path = parts
        rel_path = rel_path.strip().lstrip('*')  # md5sum marks binary mode with a leading '*'
        rel_path = rel_path.replace('\\', os.sep).replace('/', os.sep)
        hashes[rel_path] = hash_val
    return hashes


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


def hash_file(path, algorithm='md5'):
    """Compute the hash of a file, reading in chunks.

    Chunked reading keeps memory usage flat regardless of file size.
    Supported algorithms: 'md5', 'sha256'.
    """
    h = hashlib.new(algorithm)
    with open(path, 'rb') as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def scan_directory(dirpath, algorithm='md5', checkpoint_file=None, external_hashes=None):
    """Recursively walk a directory and return a dict mapping hash -> {FILE_PATH, NAME}.

    FILE_PATH is stored relative to dirpath so paths are comparable across
    different root directories. Files in IGNORE_NAMES are silently skipped.
    Permission errors are warned and skipped rather than crashing the script.

    If checkpoint_file is given, per-file results (size, mtime, hash) are
    loaded from it up front and skipped on this run if the file is unchanged,
    and progress is saved back to it periodically. If the walk is interrupted
    (Ctrl+C, or the directory becoming unreachable, e.g. a network drop), the
    checkpoint is saved before exiting so a re-run of the same command can
    resume instead of re-hashing everything.

    If external_hashes is given (a {rel_path: hash} dict from a pre-computed
    hash listing), those hashes are trusted outright and never recomputed,
    even on a file's first pass through this directory.
    """
    items = {}

    if not os.path.exists(dirpath):
        print(f"Error: directory not found: {dirpath}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(dirpath):
        print(f"Error: not a directory: {dirpath}", file=sys.stderr)
        sys.exit(1)

    records = load_checkpoint(checkpoint_file) if checkpoint_file else {}
    if records:
        print(f"  Resuming {dirpath} from checkpoint: {len(records)} files already hashed.")
    external_hashes = external_hashes or {}
    if external_hashes:
        print(f"  Loaded {len(external_hashes)} pre-computed hashes for {dirpath}.")
    unsaved_count = 0

    def flush():
        if checkpoint_file and unsaved_count:
            save_checkpoint(checkpoint_file, records)

    file_count = 0
    try:
        for root, dirs, files in os.walk(dirpath):
            dirs.sort()  # Sort for deterministic traversal order
            for name in sorted(files):
                if name in IGNORE_NAMES:
                    continue

                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, dirpath)

                try:
                    stat = os.stat(abs_path)
                    record = records.get(rel_path)
                    if record and record.get('size') == stat.st_size and record.get('mtime') == stat.st_mtime:
                        key = record['hash']
                    elif rel_path in external_hashes:
                        key = external_hashes[rel_path]
                        records[rel_path] = {'size': stat.st_size, 'mtime': stat.st_mtime, 'hash': key}
                        unsaved_count += 1
                        if checkpoint_file and unsaved_count >= CHECKPOINT_INTERVAL:
                            flush()
                            unsaved_count = 0
                    else:
                        # Show a live progress line that overwrites itself
                        print(f"  Scanning {dirpath}: {file_count} files hashed...", end='\r')
                        key = hash_file(abs_path, algorithm)
                        records[rel_path] = {'size': stat.st_size, 'mtime': stat.st_mtime, 'hash': key}
                        unsaved_count += 1
                        if checkpoint_file and unsaved_count >= CHECKPOINT_INTERVAL:
                            flush()
                            unsaved_count = 0

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
    except (OSError, KeyboardInterrupt) as e:
        flush()
        print(f"\n\nInterrupted while scanning {dirpath}: {e}", file=sys.stderr)
        if checkpoint_file:
            print(f"Progress saved to {checkpoint_file} ({len(records)} files).", file=sys.stderr)
            print("Re-run the same command to resume from here.", file=sys.stderr)
        raise SystemExit(2)

    flush()

    # Print final count on a clean line
    print(f"  Scanned {dirpath}: {file_count} files hashed.       ")
    return items


def build_diff_rows(all_items, algorithm='md5'):
    """Build a truth-table of discrepancies across N directories.

    Args:
        all_items: dict of {dirpath: {hash: {FILE_PATH, NAME}}}
        algorithm: hash algorithm name used (for the output column label)

    Returns:
        (rows, dirnames) where each row is a dict with keys:
            <algorithm>_hash, file_path, name, <dir_1>, <dir_2>, ...
        Each directory key is set to 'present' or 'MISSING'.
        Only hashes absent from at least one directory are included.
    """
    hash_col = f'{algorithm}_hash'
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
                hash_col:      key,
                'file_path':   sample['FILE_PATH'],
                'name':        sample['NAME'],
            }
            for d in dirnames:
                row[d] = 'present' if presence[d] else 'MISSING'
            rows.append(row)

    return rows, dirnames


def write_csv(output_path, rows, dirnames, algorithm='md5'):
    """Write diff rows to a CSV file.

    Columns: <algorithm>_hash, file_path, name, then one column per input
    directory showing 'present' or 'MISSING'. This truth-table layout is easy
    to filter by directory in Excel or Numbers.
    """
    fieldnames = [f'{algorithm}_hash', 'file_path', 'name'] + dirnames
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
    parser.add_argument(
        '--hash', '-H',
        dest='algorithm',
        choices=['md5', 'sha256'],
        default='md5',
        help='Hash algorithm to use (default: md5)',
    )
    parser.add_argument(
        '--checkpoint-dir',
        dest='checkpoint_dir',
        default=DEFAULT_CHECKPOINT_DIR,
        help='Directory to store per-source checkpoint files, enabling resume '
             f'after an interruption (e.g. a network drop or Ctrl+C). Defaults '
             f'to "{DEFAULT_CHECKPOINT_DIR}" in the current directory. Re-running '
             'the same command from the same location picks up where it left '
             'off instead of re-hashing everything.',
    )
    parser.add_argument(
        '--no-checkpoint',
        dest='checkpoint_dir',
        action='store_const',
        const=None,
        help='Disable checkpointing entirely (no resume support).',
    )
    parser.add_argument(
        '--import-hashes',
        dest='import_hashes',
        action='append',
        default=[],
        metavar='DIR=HASHFILE',
        help='Reuse pre-computed hashes for one of the directories being '
             'compared instead of rehashing its files. DIR must match one of '
             'the positional directories exactly. HASHFILE may be an '
             'md5sum/sha256sum-style text listing ("<hash>  <rel_path>" per '
             'line) or one of this script\'s own checkpoint JSON files. Can '
             'be repeated for multiple directories.',
    )
    args = parser.parse_args()

    if len(args.dirs) < 2:
        parser.error('At least two directories are required.')

    import_hashes_by_dir = {}
    for entry in args.import_hashes:
        if '=' not in entry:
            parser.error(f'--import-hashes must be in the form DIR=HASHFILE, got: {entry}')
        dir_key, hash_file_path = entry.split('=', 1)
        if dir_key not in args.dirs:
            parser.error(f'--import-hashes directory "{dir_key}" is not one of the directories being compared: {args.dirs}')
        import_hashes_by_dir[dir_key] = load_external_hashes(hash_file_path)

    # Scan each directory and build hash -> file maps
    print(f"Hashing files ({args.algorithm})...")
    all_items = {}
    for d in args.dirs:
        checkpoint_file = checkpoint_path_for(d, args.checkpoint_dir) if args.checkpoint_dir else None
        all_items[d] = scan_directory(d, args.algorithm, checkpoint_file, import_hashes_by_dir.get(d))

    # Find hashes missing from one or more directories
    diff_rows, dirnames = build_diff_rows(all_items, args.algorithm)

    print()

    # Print one line per discrepancy to stdout
    for r in diff_rows:
        missing_from = [d for d in dirnames if r[d] == 'MISSING']
        print(f"Missing from {', '.join(missing_from)}: {r['file_path']} ({r[f'{args.algorithm}_hash']})")

    # Print per-directory summary
    print(f"\nTotal discrepancies: {len(diff_rows)}")
    for d in dirnames:
        count = sum(1 for r in diff_rows if r[d] == 'MISSING')
        print(f"  Missing from {d}: {count}")

    if args.output:
        # Resolve the output path, prompting if the file already exists
        output_path = resolve_output_path(args.output)
        write_csv(output_path, diff_rows, dirnames, args.algorithm)

    # Exit 1 if mismatches found so shell scripts and CI can detect failure
    sys.exit(1 if diff_rows else 0)


if __name__ == '__main__':
    main()