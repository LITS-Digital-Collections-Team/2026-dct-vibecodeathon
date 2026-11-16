# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
build_relevance_index.py — Cache the wiki/people|topics|organizations
lookup used by EMAIL_ARCHIVE_TASK.md's relevance gate and targeted search.

Every backfill chunk used to re-parse all three directories from scratch.
Since that content barely changes between one chunk and the next in the
same backfill, this builds it once into `.relevance_index.json` and only
rebuilds when a source file is newer than the cache.

Usage as a CLI:
    python3 scripts/build_relevance_index.py             # build if stale
    python3 scripts/build_relevance_index.py --force     # rebuild always
    python3 scripts/build_relevance_index.py --print     # rebuild (if stale) and print it

Usage as a library (preferred, from an email-archive-task agent):
    import sys; sys.path.insert(0, 'scripts')
    from build_relevance_index import load_relevance_index, match_person, wiki_link_for_person
    index = load_relevance_index()
    slug = match_person('jdoe@example.edu', index)          # -> 'jane-doe'
    link = wiki_link_for_person('jdoe@example.edu', index)  # -> '../people/jane-doe.md'
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import ORGS_DIR, PEOPLE_DIR, TOPICS_DIR, WIKI_ROOT

INDEX_FILE = WIKI_ROOT / ".relevance_index.json"


# ---------------------------------------------------------------------------
# Frontmatter parsing (scalars + simple YAML lists)
# ---------------------------------------------------------------------------

def _parse_frontmatter(text):
    """Parse frontmatter into a dict of scalars and lists. No PyYAML —
    handles `key: value` and `key:\\n  - item\\n  - item` list blocks, which
    is all this repo's frontmatter actually uses."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}
    fm = {}
    lines = match.group(1).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        kv = re.match(r'^(\w[\w-]*):\s*"?([^"]*)"?\s*$', line)
        if kv:
            key, val = kv.group(1), kv.group(2).strip()
            if val:
                fm[key] = val
                i += 1
                continue
            # Possible list block on following indented lines
            items = []
            j = i + 1
            while j < len(lines) and re.match(r"^\s+-\s+", lines[j]):
                item = re.sub(r"^\s+-\s+", "", lines[j]).strip().strip('"')
                items.append(item)
                j += 1
            if items:
                fm[key] = items
                i = j
                continue
        i += 1
    return fm


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------

_GENERIC_WORDS = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "update", "updates", "notes", "report", "reports", "meeting", "meetings",
    "situation", "plan", "planning", "project", "projects", "program", "programs",
    "team", "group", "call", "review", "status", "usage", "personal",
    "responsible", "strategic", "process", "processes", "guidelines",
}


def _slug_from_path(path):
    return path.stem


def build_index():
    people = {}          # email (lowercase) -> {slug, name}
    people_by_name = {}  # lowercase name -> slug
    for f in sorted(PEOPLE_DIR.glob("*.md")):
        fm = _parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
        slug = _slug_from_path(f)
        name = fm.get("name", slug)
        entry = {"slug": slug, "name": name}
        emails = fm.get("email") or []
        if isinstance(emails, str):          # "a@x.org" or "a@x.org, b@y.org"
            emails = [e for e in re.split(r"[,;\s]+", emails) if e]
        for addr in emails:                  # block-style YAML list also works
            people[str(addr).strip().lower()] = entry
        if name:
            people_by_name[name.lower()] = slug

    topics = []           # [{slug, title, tags}]
    topics_by_tag = {}     # lowercase tag -> slug
    word_doc_count = {}    # lowercase word -> number of distinct topic titles containing it
    word_to_slug = {}      # lowercase word -> slug (last writer; refined below)
    for f in sorted(TOPICS_DIR.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        fm = _parse_frontmatter(text)
        slug = _slug_from_path(f)
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else slug
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        topics.append({"slug": slug, "title": title, "tags": tags})
        for tag in tags:
            topics_by_tag[tag.lower()] = slug
        for word in set(re.findall(r"[A-Za-z0-9]+", title.lower())):
            if len(word) >= 4:  # skip short/stopword-ish tokens
                word_doc_count[word] = word_doc_count.get(word, 0) + 1
                word_to_slug[word] = slug

    # Domain-generic words (e.g. "digital", "collections") recur across many
    # topic titles and would match almost everything if used as a signal —
    # drop any word that appears in more than one topic's title, keeping
    # only words distinctive enough to identify a single topic. Also drop a
    # small set of words that are unique-per-title by coincidence but too
    # generic in ordinary English to mean anything on their own (calendar
    # words, common status/meeting vocabulary).
    topics_by_title_word = {
        word: slug
        for word, slug in word_to_slug.items()
        if word_doc_count[word] == 1 and word not in _GENERIC_WORDS
    }

    orgs = []              # [{slug, name}]
    orgs_by_name = {}      # lowercase name -> slug
    for f in sorted(ORGS_DIR.glob("*.md")):
        fm = _parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
        slug = _slug_from_path(f)
        name = fm.get("name", slug)
        full_name = fm.get("full_name", "")
        orgs.append({"slug": slug, "name": name, "full_name": full_name})
        orgs_by_name[name.lower()] = slug
        if full_name:
            orgs_by_name[full_name.lower()] = slug

    return {
        "people": people,
        "people_by_name": people_by_name,
        "topics": topics,
        "topics_by_tag": topics_by_tag,
        "topics_by_title_word": topics_by_title_word,
        "orgs": orgs,
        "orgs_by_name": orgs_by_name,
    }


# ---------------------------------------------------------------------------
# Staleness-checked load
# ---------------------------------------------------------------------------

def _newest_source_mtime():
    newest = 0.0
    for d in (PEOPLE_DIR, TOPICS_DIR, ORGS_DIR):
        for f in d.glob("*.md"):
            newest = max(newest, f.stat().st_mtime)
    return newest


def load_relevance_index(force=False):
    """Load the cached index, rebuilding it if missing, forced, or stale
    relative to the newest wiki/people|topics|organizations file."""
    if not force and INDEX_FILE.exists():
        cache_mtime = INDEX_FILE.stat().st_mtime
        if cache_mtime >= _newest_source_mtime():
            return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    index = build_index()
    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    return index


# ---------------------------------------------------------------------------
# Matching helpers — used by both Stage 2 (targeted search) and Stage 3
# (relevance gate) and Stage 4 (Related Wiki Pages)
# ---------------------------------------------------------------------------

def match_person(email_or_name, index):
    """Return a person slug for an email address or display name, or None."""
    if not email_or_name:
        return None
    key = email_or_name.strip().lower()
    email_match = re.search(r"[\w.+-]+@[\w.-]+", key)
    if email_match and email_match.group(0) in index["people"]:
        return index["people"][email_match.group(0)]["slug"]
    # Try bare/display-name match (strip a trailing "<email>" if present)
    name_only = re.sub(r"<[^>]*>", "", key).strip()
    return index["people_by_name"].get(name_only)


def match_topics(text, index):
    """Return a list of topic slugs whose tag or title word appears in text.

    Uses word-boundary matching throughout — a plain substring check would
    let a short tag like "ai" match inside unrelated words (e.g. "available").
    """
    if not text:
        return []
    lower = text.lower()
    hits = set()
    for tag, slug in index["topics_by_tag"].items():
        if re.search(r"\b" + re.escape(tag) + r"\b", lower):
            hits.add(slug)
    for word, slug in index["topics_by_title_word"].items():
        if re.search(r"\b" + re.escape(word) + r"\b", lower):
            hits.add(slug)
    return sorted(hits)


def match_orgs(text, index):
    """Return a list of organization slugs named in text (word-boundary
    matched — short acronyms like "IT" are as prone to false substring
    hits as short topic tags are)."""
    if not text:
        return []
    lower = text.lower()
    return sorted(
        slug
        for name, slug in index["orgs_by_name"].items()
        if name and re.search(r"\b" + re.escape(name) + r"\b", lower)
    )


def wiki_link_for_person(email_or_name, index):
    slug = match_person(email_or_name, index)
    return f"../people/{slug}.md" if slug else None


def wiki_link_for_topic(slug):
    return f"../topics/{slug}.md"


def wiki_link_for_org(slug):
    return f"../organizations/{slug}.md"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Rebuild even if cache looks fresh")
    parser.add_argument("--print", dest="do_print", action="store_true", help="Print the index")
    args = parser.parse_args()

    index = load_relevance_index(force=args.force)
    print(f"People:  {len(index['people'])} with email, {len(index['people_by_name'])} total")
    print(f"Topics:  {len(index['topics'])} ({len(index['topics_by_tag'])} tags indexed)")
    print(f"Orgs:    {len(index['orgs'])}")
    print(f"Cached at: {INDEX_FILE}")
    if args.do_print:
        print(json.dumps(index, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
