# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Developed with assistance from Claude (Anthropic).
# Reviewed and tested; verify behavior in your own environment.

"""
check_ingest.py — List files in raw_ingest/ that have not yet been processed.

This is the script Claude runs at the start of each wiki update to find
new documents to analyse.  It prints one filepath per line so that the
output can be read easily by Claude or piped to other tools.

Usage:
    python scripts/check_ingest.py            # print unprocessed files
    python scripts/check_ingest.py --all      # print all files (inc. processed)
    python scripts/check_ingest.py --summary  # counts only
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import RAW_INGEST_DIR, FAILED_INGEST_DIR, SUPPORTED_EXTENSIONS
from scripts.manifest import load_manifest, is_processed


def get_ingest_files(include_processed: bool = False) -> list[Path]:
    """
    Return a sorted list of files in raw_ingest/.

    By default only files not yet in the manifest are returned.
    Pass include_processed=True to return all supported files.
    """
    if not RAW_INGEST_DIR.exists():
        return []

    manifest = load_manifest()
    results = []

    for filepath in sorted(RAW_INGEST_DIR.rglob("*")):
        # Skip directories and unsupported file types.
        if not filepath.is_file():
            continue
        # Never scan the quarantine directory.
        if FAILED_INGEST_DIR in filepath.parents:
            continue
        if filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        # Skip hidden files (e.g. .DS_Store).
        if filepath.name.startswith("."):
            continue

        if include_processed or not is_processed(filepath, manifest):
            results.append(filepath)

    return results


if __name__ == "__main__":
    show_all = "--all" in sys.argv
    summary_only = "--summary" in sys.argv

    unprocessed = get_ingest_files(include_processed=False)
    all_files = get_ingest_files(include_processed=True)
    processed_count = len(all_files) - len(unprocessed)

    if summary_only:
        print(f"Total files in raw_ingest/: {len(all_files)}")
        print(f"  Already processed:        {processed_count}")
        print(f"  Awaiting processing:      {len(unprocessed)}")
        sys.exit(0)

    if show_all:
        files_to_show = all_files
        label = "all"
    else:
        files_to_show = unprocessed
        label = "unprocessed"

    if not files_to_show:
        print(f"No {label} files found in {RAW_INGEST_DIR}")
        sys.exit(0)

    for f in files_to_show:
        print(f)
