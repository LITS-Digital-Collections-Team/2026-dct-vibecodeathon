# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
record_email_synthesis.py — The ONLY sanctioned way to write to
.email_synthesis_manifest.json for the optional Synthesis Pass (see
EMAIL_ARCHIVE_TASK.md, "Optional: Synthesis Pass" -> "Concurrency and
processing order").

Why this exists: on the 2026-08-12 run, several parallel synthesis
agents each called load_synthesis_manifest() / mark_synthesized() /
save_synthesis_manifest() directly. Because each agent's in-memory copy
of the manifest didn't include the others' concurrent additions, the
last agent to save silently clobbered everyone else's — 53 of 117
expected entries were lost until manually reconciled. Running as a
single process with one load and one save (this script) makes that race
structurally impossible: there is exactly one writer, and it writes
once.

Usage — after all of a run's page-agents have reported back which files
they fully resolved (incorporated or explicitly judged as adding
nothing), build one JSON resolutions file mapping each fully-resolved
email file to the list of wiki pages it was resolved against, then run:

    python scripts/record_email_synthesis.py resolutions.json

resolutions.json shape:
    {
        "wiki/email/<file>.md": ["wiki/people/<slug>.md", "wiki/topics/<slug>.md"],
        "wiki/email/<other>.md": ["wiki/topics/<slug>.md"],
        ...
    }

A file should only appear here once ALL of its Related Wiki Pages links
(per check_email_synthesis.py's grouping) have been addressed by some
agent this run — see EMAIL_ARCHIVE_TASK.md Step 3. Partially-resolved
files (e.g. one target page's agent failed or wasn't dispatched this
run) should be omitted so a later run picks them up again.

Entries are written oldest-to-newest by each file's date_last_message
(falling back to date_started), so the manifest's on-disk key order
reads as a chronological log of the archive, matching how the rest of
this task orders things (digest/marketing/candidate-log tables are also
append-oldest-at-the-bottom). This is a readability property, not a
correctness requirement — JSON object key order doesn't affect lookups
— but keep it, since a manifest that reads chronologically is much
easier to eyeball during a debugging session.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import WIKI_ROOT
from scripts.email_synthesis_manifest import (
    load_synthesis_manifest,
    mark_synthesized,
    save_synthesis_manifest,
)

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def _sort_key(path_str: str) -> str:
    """date_last_message, falling back to date_started, falling back to ''."""
    fp = WIKI_ROOT / path_str
    if not fp.exists():
        return ""
    text = fp.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    block = match.group(1) if match else ""
    for key in ("date_last_message", "date_started"):
        m = re.search(rf'^{key}:\s*"?([^"\n]+)"?\s*$', block, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resolutions", type=str,
                         help="Path to a JSON file mapping email file path -> [wiki pages]. Use '-' for stdin.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print what would be recorded without writing the manifest")
    args = parser.parse_args()

    raw = sys.stdin.read() if args.resolutions == "-" else Path(args.resolutions).read_text()
    resolutions = json.loads(raw)

    if not resolutions:
        print("Nothing to record — resolutions file was empty.")
        return

    ordered_paths = sorted(resolutions.keys(), key=_sort_key)

    print(f"Recording {len(ordered_paths)} file(s), oldest to most recent:")
    for path in ordered_paths:
        print(f"  {_sort_key(path) or '(no date)':<12}  {path}  -> {resolutions[path]}")

    if args.dry_run:
        print("\n--dry-run: manifest not written.")
        return

    manifest = load_synthesis_manifest()
    missing = []
    for path in ordered_paths:
        fp = WIKI_ROOT / path
        if not fp.exists():
            missing.append(path)
            continue
        manifest = mark_synthesized(fp, wiki_pages=resolutions[path], manifest=manifest)
    save_synthesis_manifest(manifest)

    print(f"\nDone. Manifest now has {len(manifest)} entries.")
    if missing:
        print(f"Skipped {len(missing)} path(s) that don't exist on disk: {missing}")


if __name__ == "__main__":
    main()
