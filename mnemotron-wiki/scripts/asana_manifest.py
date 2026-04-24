# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Developed with assistance from Claude (Anthropic).
# Reviewed and tested; verify behavior in your own environment.

"""
asana_manifest.py — Track which Asana projects have a corresponding wiki page.

The main .manifest.json is keyed by the MD5 hash of a raw file's contents,
which is correct for "have I seen THIS file?" but cannot answer
"is there already a wiki page for THIS Asana project?"  When a project
history is re-generated later (with slightly different task counts,
status text, etc.) the content hash changes and the main manifest treats
it as a new document — which would produce a duplicate topic page.

This manifest solves that by indexing on the stable Asana identifier
(project_gid).  Each entry records where the topic page lives, when it
was last refreshed, and the hash of the raw content last ingested so we
can skip no-op refreshes.

Schema of each entry (keyed by project_gid as a string):

    {
        "project_name":       str,   # human-readable name ("DC-Brothertown")
        "slug":               str,   # slug used in the topic-page filename
        "wiki_page":          str,   # path relative to WIKI_ROOT
        "last_ingested":      str,   # ISO date (YYYY-MM-DD)
        "last_content_hash":  str,   # MD5 of the raw markdown last ingested
        "last_raw_filename":  str    # name of the raw file last ingested
    }

The cache directory (scripts/.cache/asana/) stores a verbatim copy of the
last-ingested raw markdown per project, so future runs can diff byte-for-byte
and skip refreshes that would produce no change.

Usage (as a module):
    from scripts.asana_manifest import (
        load_asana_manifest,
        lookup_project,
        mark_project_ingested,
        save_asana_manifest,
        get_cached_content,
        write_cache,
    )

Usage (command line — list all known projects):
    python scripts/asana_manifest.py
"""

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

# Allow running as a script or importing as a sibling module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import WIKI_ROOT

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ASANA_MANIFEST_FILE = WIKI_ROOT / ".asana_manifest.json"
ASANA_CACHE_DIR = WIKI_ROOT / "scripts" / ".cache" / "asana"


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def content_hash(text: str) -> str:
    """Return the MD5 hex digest of *text* (utf-8 encoded)."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------

def load_asana_manifest() -> dict:
    """Load the Asana manifest from disk, returning {} if it doesn't exist."""
    if not ASANA_MANIFEST_FILE.exists():
        return {}
    with open(ASANA_MANIFEST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_asana_manifest(manifest: dict) -> None:
    """Write *manifest* back to disk, pretty-printed and sorted for readability."""
    with open(ASANA_MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, sort_keys=True)


def lookup_project(project_gid: str, manifest: dict) -> dict | None:
    """Return the manifest entry for *project_gid*, or None."""
    return manifest.get(str(project_gid))


def mark_project_ingested(
    project_gid: str,
    project_name: str,
    slug: str,
    wiki_page: Path,
    raw_content: str,
    raw_filename: str,
    manifest: dict,
) -> dict:
    """
    Record an ingestion in *manifest* (in-memory).
    Caller must call save_asana_manifest() to persist.
    """
    # Store wiki_page as a path relative to WIKI_ROOT so the manifest is
    # portable across machines (local laptop vs. Cowork VM mount).
    if wiki_page.is_absolute():
        try:
            rel = wiki_page.relative_to(WIKI_ROOT)
        except ValueError:
            rel = wiki_page
        wiki_str = str(rel)
    else:
        wiki_str = str(wiki_page)

    manifest[str(project_gid)] = {
        "project_name":      project_name,
        "slug":               slug,
        "wiki_page":          wiki_str,
        "last_ingested":      date.today().isoformat(),
        "last_content_hash":  content_hash(raw_content),
        "last_raw_filename":  raw_filename,
    }
    return manifest


# ---------------------------------------------------------------------------
# Cache (used for byte-diffing raw content between runs)
# ---------------------------------------------------------------------------

def get_cached_content(project_gid: str) -> str | None:
    """Return the cached raw markdown for *project_gid*, or None if absent."""
    cache_file = ASANA_CACHE_DIR / f"{project_gid}.md"
    if not cache_file.exists():
        return None
    return cache_file.read_text(encoding="utf-8")


def write_cache(project_gid: str, raw_content: str) -> None:
    """Save raw markdown to the cache for diff on future runs."""
    ASANA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = ASANA_CACHE_DIR / f"{project_gid}.md"
    cache_file.write_text(raw_content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Command-line interface — list all known projects
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    manifest = load_asana_manifest()
    if not manifest:
        print("Asana manifest is empty — no projects ingested yet.")
        sys.exit(0)

    print(f"{'Project (gid)':<22} {'Slug':<45} {'Last ingested':<14} Wiki page")
    print("-" * 110)
    for gid, entry in sorted(
        manifest.items(), key=lambda kv: kv[1].get("slug", "")
    ):
        print(
            f"{gid:<22} "
            f"{entry.get('slug', ''):<45} "
            f"{entry.get('last_ingested', ''):<14} "
            f"{entry.get('wiki_page', '')}"
        )
