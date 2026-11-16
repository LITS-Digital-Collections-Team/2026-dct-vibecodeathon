# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
email_synthesis_manifest.py — Track which wiki/email/ archive files have
already been synthesized into topic/people/organization pages.

Distinct from .email_archive_manifest.json (tracks Gmail -> wiki/email/
archiving) and .manifest.json (tracks raw_ingest/ -> wiki/ ingestion).
This manifest tracks the third, optional pass: wiki/email/ -> wiki/topics|
people|organizations synthesis. See EMAIL_ARCHIVE_TASK.md, "Optional:
Synthesis Pass".

Keyed by thread_id for conversation files (stable across re-runs even as
a thread accumulates more messages), or by filename for digest/marketing/
candidate-log files (which have no thread_id). Each entry records the
message_count (or entry_count) seen at synthesis time, so a later run can
tell whether a conversation has grown new messages since it was last
synthesized without re-reading the file.

Schema of each manifest entry:
    {
        "output_file":   str,        # path of the wiki/email/ source file
        "message_count": int,        # message_count (or entry_count) at synthesis time
        "wiki_pages":    [str, ...], # topic/people/org pages updated or created
        "synthesized":   str,        # ISO 8601 datetime
    }
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import WIKI_ROOT

SYNTHESIS_MANIFEST_FILE = WIKI_ROOT / ".email_synthesis_manifest.json"

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def _frontmatter(filepath: Path) -> dict:
    """Parse the minimal set of frontmatter fields this module needs."""
    text = filepath.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    block = match.group(1)
    fields = {}
    for key in ("thread_id", "message_count", "entry_count", "type"):
        m = re.search(rf'^{key}:\s*"?([^"\n]+)"?\s*$', block, re.MULTILINE)
        if m:
            fields[key] = m.group(1).strip()
    return fields


def synthesis_key(filepath: Path) -> str:
    """
    Return the manifest key for *filepath*: its thread_id if present
    (conversation files), otherwise its filename (digest/marketing/
    candidate-log files, which are living documents with no thread_id).
    """
    fm = _frontmatter(filepath)
    return fm.get("thread_id") or filepath.name


def current_count(filepath: Path) -> int:
    """Return message_count (conversations) or entry_count (logs) as int."""
    fm = _frontmatter(filepath)
    raw = fm.get("message_count") or fm.get("entry_count") or "0"
    try:
        return int(raw)
    except ValueError:
        return 0


def load_synthesis_manifest() -> dict:
    if not SYNTHESIS_MANIFEST_FILE.exists():
        return {}
    with open(SYNTHESIS_MANIFEST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_synthesis_manifest(manifest: dict) -> None:
    from scripts.locking import merge_save_json  # locked, atomic, merges concurrent entries
    merge_save_json(SYNTHESIS_MANIFEST_FILE, manifest)


def needs_synthesis(filepath: Path, manifest: dict) -> bool:
    """True if *filepath* has never been synthesized, or has grown since."""
    key = synthesis_key(filepath)
    entry = manifest.get(key)
    if entry is None:
        return True
    return current_count(filepath) > entry.get("message_count", 0)


def mark_synthesized(filepath: Path, wiki_pages: list, manifest: dict) -> dict:
    """
    Record *filepath* as synthesized up to its current message/entry count.

    Does not write to disk — call save_synthesis_manifest() afterwards.
    """
    key = synthesis_key(filepath)
    manifest[key] = {
        "output_file":   str(filepath),
        "message_count": current_count(filepath),
        "wiki_pages":    [str(p) for p in wiki_pages],
        "synthesized":   datetime.now(timezone.utc).isoformat(),
    }
    return manifest


if __name__ == "__main__":
    manifest = load_synthesis_manifest()
    if not manifest:
        print("Synthesis manifest is empty — no email archive files have been synthesized yet.")
        sys.exit(0)

    print(f"{'Key':<20}  {'Count':<6}  {'Synthesized (UTC)':<26}  Output file")
    print("-" * 100)
    for key, entry in manifest.items():
        print(
            f"{key:<20}  "
            f"{entry.get('message_count', 0):<6}  "
            f"{entry.get('synthesized', ''):<26}  "
            f"{entry.get('output_file', '')}"
        )
