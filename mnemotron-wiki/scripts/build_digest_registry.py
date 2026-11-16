# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
build_digest_registry.py — Cache a sender/subject -> digest-file lookup
derived from the `source_pattern` frontmatter already present in every
`wiki/email/digest-*.md` file.

EMAIL_ARCHIVE_TASK.md's Stage 3 "first sighting vs. recurring" heuristic
required each backfill chunk to re-scan every existing digest file and
infer whether a sender was already an established source. Since digest
files already declare their own matching pattern in frontmatter, this
just parses that once into a directly queryable registry instead.

Usage as a CLI:
    python3 scripts/build_digest_registry.py             # build if stale
    python3 scripts/build_digest_registry.py --force      # rebuild always
    python3 scripts/build_digest_registry.py --test 'sender@x.com' 'Some Subject'

Usage as a library:
    import sys; sys.path.insert(0, 'scripts')
    from build_digest_registry import load_digest_registry, match_digest_source
    registry = load_digest_registry()
    output_file = match_digest_source('alerts@example.org',
                                       'Daily report ... is ready to review',
                                       registry)
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import EMAIL_DIR, WIKI_ROOT

REGISTRY_FILE = WIKI_ROOT / ".digest_registry.json"


def _parse_frontmatter_scalars(text):
    """Minimal scalar-only frontmatter parse (digest files have no list fields
    we need here)."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}
    fm = {}
    for line in match.group(1).splitlines():
        kv = re.match(r'^(\w[\w-]*):\s*"?(.*?)"?\s*$', line)
        if kv:
            fm[kv.group(1)] = kv.group(2)
    return fm


def _extract_emails(text):
    return sorted(set(m.lower() for m in re.findall(r"[\w.+-]+@[\w.-]+", text)))


def _extract_subject_patterns(text):
    """Subject patterns in source_pattern are always single-quoted."""
    return re.findall(r"'([^']+)'", text)


def _pattern_to_regex(pattern):
    """Turn a human-written subject pattern into a compiled case-insensitive
    regex. Recognizes the wildcard conventions actually used in this repo's
    source_pattern fields: `<Placeholder>`, literal `...`, `[A|B|C]` bracket
    alternation (only when it contains a `|` — a bracket with no pipe, like
    Drupal's literal "[Security-news]" subject prefix, is NOT alternation
    and must match literally, brackets included), and a bare standalone `N`
    used informally as a number placeholder in a few patterns (e.g. "You
    have N overdue tasks"). Everything else is a literal string."""
    tokens = re.split(r"(<[^>]+>|\.\.\.|\[[^\]]*\|[^\]]*\]|\bN\b)", pattern)
    parts = []
    for tok in tokens:
        if not tok:
            continue
        if re.match(r"^<[^>]+>$", tok) or tok == "...":
            parts.append(".*")
        elif tok == "N":
            parts.append(r"\d+")
        elif re.match(r"^\[[^\]]*\|[^\]]*\]$", tok):
            alts = tok[1:-1].split("|")
            parts.append("(?:" + "|".join(re.escape(a) for a in alts) + ")")
        else:
            parts.append(re.escape(tok))
    return re.compile("".join(parts), re.IGNORECASE)


def build_registry():
    sources = []
    for f in sorted(EMAIL_DIR.glob("digest-*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        fm = _parse_frontmatter_scalars(text)
        pattern_text = fm.get("source_pattern", "")
        sources.append({
            "output_file": f"wiki/email/{f.name}",
            "source_name": fm.get("source_name", f.stem),
            "emails": _extract_emails(pattern_text),
            "subject_patterns": _extract_subject_patterns(pattern_text),
        })
    return {"sources": sources}


def _newest_source_mtime():
    newest = 0.0
    for f in EMAIL_DIR.glob("digest-*.md"):
        newest = max(newest, f.stat().st_mtime)
    return newest


def load_digest_registry(force=False):
    if not force and REGISTRY_FILE.exists():
        if REGISTRY_FILE.stat().st_mtime >= _newest_source_mtime():
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    registry = build_registry()
    REGISTRY_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    return registry


def match_digest_source(sender_email, subject, registry):
    """Return the output_file of the digest this sender/subject belongs to,
    or None if it doesn't match any known digest source. `None` means
    "not a known recurring digest source" — apply Stage 3's first-sighting
    heuristic fresh, don't assume it's a new one-off."""
    sender_email = (sender_email or "").lower()
    email_match = re.search(r"[\w.+-]+@[\w.-]+", sender_email)
    sender_email = email_match.group(0) if email_match else sender_email
    subject = subject or ""

    candidates = [s for s in registry["sources"] if sender_email in s["emails"]]
    if not candidates:
        return None
    if len(candidates) == 1 and not candidates[0]["subject_patterns"]:
        return candidates[0]["output_file"]
    for c in candidates:
        for pattern in c["subject_patterns"]:
            if _pattern_to_regex(pattern).search(subject):
                return c["output_file"]
    return None


def _main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Rebuild even if cache looks fresh")
    parser.add_argument("--test", nargs=2, metavar=("SENDER", "SUBJECT"), help="Test a sender/subject match")
    args = parser.parse_args()

    registry = load_digest_registry(force=args.force)
    print(f"Digest sources indexed: {len(registry['sources'])}")
    print(f"Cached at: {REGISTRY_FILE}")
    if args.test:
        result = match_digest_source(args.test[0], args.test[1], registry)
        print(f"Match: {result!r}")


if __name__ == "__main__":
    _main()
