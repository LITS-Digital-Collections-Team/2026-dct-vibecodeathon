# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
check_email_synthesis.py — List wiki/email/ archive files that are due
for the optional synthesis pass (see EMAIL_ARCHIVE_TASK.md, "Optional:
Synthesis Pass") and group them by target wiki page.

Scope: type: email-conversation files only, by default — digest/marketing/
candidate-log files are living logs, not correspondence, and are excluded
unless --include-logs is passed. A file is "due" if it has never been
synthesized, or has grown (more messages) since its last synthesis pass,
per .email_synthesis_manifest.json.

Output is grouped by target wiki page (parsed from each file's own
"## Related Wiki Pages" section, which the email archive task already
computed at archive time — this script does not re-derive relevance).
Grouping by page, not by file, is deliberate: a synthesis agent assigned
to page P only ever writes to P, so distinct pages can be dispatched as
parallel Agent subagents with no write conflicts, even when a single
email touches multiple pages (it will then appear under each of them).
Files with no Related Wiki Pages links are listed separately as orphans.

Within each page's file list (and within orphans), files are sorted
oldest-first by date_last_message (falling back to date_started) — see
"Concurrency and processing order" in EMAIL_ARCHIVE_TASK.md's Synthesis
Pass section for why. Process a page's assigned files in the order
given, don't re-sort or cherry-pick.

Usage:
    python scripts/check_email_synthesis.py --days 60
    python scripts/check_email_synthesis.py --since 2026-06-01
    python scripts/check_email_synthesis.py --days 60 --pretty
    python scripts/check_email_synthesis.py --days 60 --include-logs
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import WIKI_DIR, EMAIL_DIR
from scripts.email_synthesis_manifest import load_synthesis_manifest, needs_synthesis


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_RELATED_SECTION_RE = re.compile(
    r"^## Related Wiki Pages\s*\n(.*?)(?=\n## |\Z)", re.DOTALL | re.MULTILINE
)
_RELATED_LINK_RE = re.compile(r"\[([^\]]+)\]\((\.\./[^)]+\.md)\)")


def parse_email_file(filepath: Path) -> dict:
    text = filepath.read_text(encoding="utf-8")
    fm_match = _FRONTMATTER_RE.match(text)
    fm_block = fm_match.group(1) if fm_match else ""

    def field(key):
        m = re.search(rf'^{key}:\s*"?([^"\n]+)"?\s*$', fm_block, re.MULTILINE)
        return m.group(1).strip() if m else None

    participants = re.findall(r'^\s*-\s*"?([^"\n]+)"?\s*$',
                               re.search(r"participants:\s*\n((?:\s*-.*\n?)+)", fm_block).group(1),
                               re.MULTILINE) if "participants:" in fm_block else []

    related_pages = []
    rel_match = _RELATED_SECTION_RE.search(text)
    if rel_match:
        # Resolve the "../people/slug.md"-style relative link to a wiki-root-relative path.
        for label, rel_link in _RELATED_LINK_RE.findall(rel_match.group(1)):
            resolved = (EMAIL_DIR / rel_link).resolve()
            try:
                resolved_str = str(resolved.relative_to(WIKI_DIR.parent))
            except ValueError:
                resolved_str = rel_link
            related_pages.append({"label": label, "path": resolved_str})

    return {
        "path": str(filepath.relative_to(WIKI_DIR.parent)),
        "type": field("type"),
        "thread_id": field("thread_id"),
        "subject": field("subject"),
        "participants": participants,
        "date_started": field("date_started"),
        "date_last_message": field("date_last_message"),
        "message_count": field("message_count"),
        "related_wiki_pages": related_pages,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, help="Lookback window in days from today")
    parser.add_argument("--since", type=str, help="Fixed start date, YYYY-MM-DD")
    parser.add_argument("--include-logs", action="store_true",
                         help="Also consider digest/marketing/candidate-log files")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    if args.since:
        cutoff = args.since
    elif args.days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
    else:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    manifest = load_synthesis_manifest()

    due = []
    skipped_out_of_window = 0
    skipped_up_to_date = 0
    skipped_by_type = 0

    for filepath in sorted(EMAIL_DIR.glob("*.md")):
        info = parse_email_file(filepath)
        if not args.include_logs and info["type"] != "email-conversation":
            skipped_by_type += 1
            continue
        date_key = info.get("date_last_message") or info.get("date_started")
        if date_key and date_key < cutoff:
            skipped_out_of_window += 1
            continue
        if not needs_synthesis(filepath, manifest):
            skipped_up_to_date += 1
            continue
        due.append(info)

    # Oldest-first, so per-page groups (and orphans) are naturally chronological.
    # A file with neither date sorts first (empty string < any real date) — rare,
    # and better surfaced early than hidden at the end.
    due.sort(key=lambda info: info.get("date_last_message") or info.get("date_started") or "")

    pages = {}
    orphans = []
    for info in due:
        if not info["related_wiki_pages"]:
            orphans.append(info)
            continue
        for target in info["related_wiki_pages"]:
            pages.setdefault(target["path"], []).append(info)

    result = {
        "cutoff": cutoff,
        "due_count": len(due),
        "skipped_out_of_window": skipped_out_of_window,
        "skipped_up_to_date": skipped_up_to_date,
        "skipped_by_type": skipped_by_type,
        "pages": pages,
        "orphans": orphans,
    }

    indent = 2 if args.pretty else None
    print(json.dumps(result, indent=indent, ensure_ascii=False))


if __name__ == "__main__":
    main()
