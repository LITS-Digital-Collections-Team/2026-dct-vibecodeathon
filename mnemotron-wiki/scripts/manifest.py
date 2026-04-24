# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Developed with assistance from Claude (Anthropic).
# Reviewed and tested; verify behavior in your own environment.

"""
manifest.py — Track which files in raw_ingest/ have already been processed.

The manifest is stored as a JSON file at WIKI_ROOT/.manifest.json.
Each entry is keyed by the MD5 hash of the file's contents, so a file
that is renamed but not changed will not be re-processed.

Schema of each manifest entry:
    {
        "filename":   str,   # original filename at time of processing
        "path":       str,   # full path at time of processing
        "processed":  str,   # ISO 8601 datetime
        "wiki_page":  str,   # path of the wiki page created for this file
    }

Usage (from another script):
    from scripts.manifest import load_manifest, is_processed, mark_processed, save_manifest

Usage (command line — list all processed files):
    python scripts/manifest.py
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running as a script or importing from a sibling module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import MANIFEST_FILE


# ---------------------------------------------------------------------------
# Core utilities
# ---------------------------------------------------------------------------

def file_hash(filepath: Path) -> str:
    """Return the MD5 hex digest of *filepath*'s contents."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        # Read in 64 KB chunks to handle large files without loading them
        # entirely into memory.
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    """
    Load the manifest from disk.

    Returns an empty dict if the manifest file does not yet exist.
    """
    if not MANIFEST_FILE.exists():
        return {}
    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest: dict) -> None:
    """Write *manifest* back to disk, pretty-printed for readability."""
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def is_processed(filepath: Path, manifest: dict) -> bool:
    """Return True if *filepath* is already recorded in *manifest*."""
    return file_hash(filepath) in manifest


def mark_processed(filepath: Path, wiki_page: Path, manifest: dict) -> dict:
    """
    Record *filepath* as processed and return the updated manifest.

    Does not write to disk — call save_manifest() afterwards.
    """
    key = file_hash(filepath)
    manifest[key] = {
        "filename":  filepath.name,
        "path":      str(filepath),
        "processed": datetime.now(timezone.utc).isoformat(),
        "wiki_page": str(wiki_page),
    }
    return manifest


# ---------------------------------------------------------------------------
# Command-line interface — list all processed files
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    manifest = load_manifest()
    if not manifest:
        print("Manifest is empty — no files have been processed yet.")
        sys.exit(0)

    print(f"{'Filename':<40}  {'Processed (UTC)':<26}  Wiki page")
    print("-" * 100)
    for entry in manifest.values():
        print(
            f"{entry['filename']:<40}  "
            f"{entry['processed']:<26}  "
            f"{entry['wiki_page']}"
        )
