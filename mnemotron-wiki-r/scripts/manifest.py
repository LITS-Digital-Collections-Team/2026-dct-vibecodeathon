# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
manifest.py — Content-hash manifest for tracking processed ingest files.

Design
------
Files are identified by the MD5 hash of their *contents*, not their names or
paths.  This means:

  - Renaming or moving a file within raw_ingest/ does not cause it to be
    reprocessed (the hash is unchanged).
  - Modifying a file (even trivially) causes it to be treated as new content
    (the hash changes).  This is intentional: changed content should be
    re-evaluated.

The manifest is stored as a JSON file (.manifest.json at the wiki root) and
is intended to be committed to git so that ingest history persists across
machines and clones.

Manifest entry schema
---------------------
Each entry is keyed by the file's MD5 hex digest:

    {
        "<md5-hex>": {
            "filename":   str,   # original filename at time of processing
            "path":       str,   # full path at time of processing
            "processed":  str,   # ISO 8601 UTC datetime
            "wiki_page":  str    # path of the wiki/sources/ page created
        },
        ...
    }

Usage (import)
--------------
    from scripts.manifest import load_manifest, is_processed, mark_processed, save_manifest

Usage (CLI — list all processed files)
---------------------------------------
    python scripts/manifest.py
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow the script to be run directly from the wiki root or imported as a
# module from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import MANIFEST_FILE, WIKI_ROOT


# ---------------------------------------------------------------------------
# Core utilities
# ---------------------------------------------------------------------------

def file_hash(filepath: Path) -> str:
    """Return the MD5 hex digest of *filepath*'s byte contents.

    Reads in 64 KB chunks so large files (scanned PDFs, high-res TIFFs) are
    hashed without loading the entire file into memory.
    """
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    """Load the manifest from disk.

    Returns an empty dict if the manifest file does not yet exist, so callers
    do not need to check for the file's existence before using the manifest.
    """
    from scripts.locking import read_json
    return read_json(MANIFEST_FILE, {})


def save_manifest(manifest: dict) -> None:
    """Write *manifest* to disk (pretty-printed) without losing concurrent updates.

    The write is locked, atomic, and a *merge*: entries another process added
    since this manifest was loaded are kept.  To remove entries, use
    ``locking.merge_save_json(MANIFEST_FILE, {}, delete_keys=[...])``.
    """
    from scripts.locking import merge_save_json
    merge_save_json(MANIFEST_FILE, manifest)


def is_processed(filepath: Path, manifest: dict) -> bool:
    """Return True if *filepath*'s content hash is already in *manifest*."""
    return file_hash(filepath) in manifest


def _portable(p) -> str:
    """Store paths relative to the wiki root so manifests contain no machine-specific
    absolute paths (safe to commit or share). Paths outside the root stay as given."""
    p = Path(p)
    try:
        return p.resolve().relative_to(WIKI_ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return str(p)


def mark_processed(filepath: Path, wiki_page: Path, manifest: dict) -> dict:
    """Record *filepath* as processed and return the updated manifest.

    Does **not** write to disk — call :func:`save_manifest` afterwards.
    The separation allows callers to mark several files before writing once.
    """
    key = file_hash(filepath)
    manifest[key] = {
        "filename":  filepath.name,
        "path":      _portable(filepath),
        "processed": datetime.now(timezone.utc).isoformat(),
        "wiki_page": _portable(wiki_page),
    }
    return manifest


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    manifest = load_manifest()
    if not manifest:
        print("Manifest is empty — no files have been processed yet.")
        sys.exit(0)

    print(f"{'Filename':<45}  {'Processed (UTC)':<26}  Wiki page")
    print("-" * 110)
    for entry in manifest.values():
        print(
            f"{entry['filename']:<45}  "
            f"{entry['processed']:<26}  "
            f"{entry['wiki_page']}"
        )
