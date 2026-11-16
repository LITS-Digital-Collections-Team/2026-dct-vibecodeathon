# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
build_index.py — Regenerate wiki/INDEX.md from current wiki content.

Indexes the research layout: wiki/topics, wiki/sources and wiki/entities.
Sections whose folders are empty or absent are omitted.  The Ingested
Documents Log is updated incrementally: existing rows (with hand-written
notes) are preserved and new manifest entries are appended.  INDEX.md is
written atomically.

Usage:
    python scripts/build_index.py            # regenerate INDEX.md
    python scripts/build_index.py --dry-run  # print stats, don't write
    python scripts/build_index.py --use-api  # use the LLM (scripts/llm.py) for missing topic summaries
"""

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import (
    ENTITIES_DIR,
    MANIFEST_FILE,
    SOURCES_DIR,
    TOPICS_DIR,
    WIKI_DIR,
    WIKI_ROOT,
)
from scripts.locking import atomic_write_text, read_json

INDEX_FILE = WIKI_DIR / "INDEX.md"
TODAY = date.today().isoformat()


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> Dict[str, str]:
    """Parse YAML frontmatter between --- delimiters using regex; no PyYAML."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}
    fm: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        kv = re.match(r'^(\w[\w-]*):\s*"?([^"]*)"?\s*$', line)
        if kv:
            fm[kv.group(1)] = kv.group(2).strip()
    return fm


def _extract_section(text: str, heading: str) -> str:
    """Return the content of a ## heading section (up to next ## heading or EOF)."""
    pattern = re.compile(
        r"^##\s+" + re.escape(heading) + r"\s*\n(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(1).strip()


def _first_sentence(text: str) -> str:
    """Return the first sentence from text (up to . ! ? then space/end).

    Strips markdown syntax, leading bullets and blockquote chars.
    Caps at 150 chars when no sentence boundary is found.
    """
    if not text:
        return ""
    # Strip blockquote and bullet leaders from each line, then rejoin
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^[\s>*\-#]+", "", line).strip()
        if line:
            lines.append(line)
    clean = " ".join(lines)
    # Remove markdown links [label](url) → label
    clean = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", clean)
    # Remove bold/italic markers
    clean = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", clean)
    clean = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", clean)
    # Remove inline code
    clean = re.sub(r"`[^`]*`", "", clean)
    # Normalise whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    # Find first sentence boundary
    match = re.search(r"[.!?](?:\s|$)", clean)
    if match:
        return clean[: match.end()].strip()
    return clean[:150].strip()


def _page_title(filepath: Path) -> str:
    """Return the first # heading from a file, or stem with hyphens→spaces."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except OSError:
        return filepath.stem.replace("-", " ").title()
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return filepath.stem.replace("-", " ").title()


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def _llm_summary(text: str, label: str) -> str:
    """Call Claude for a one-liner summary (--use-api only)."""
    try:
        from scripts.llm import generate
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from llm import generate
    try:
        return generate(
            "",
            f"Summarise the following wiki entry ({label}) in one "
            f"sentence (max 150 chars).\n\n{text[:3000]}",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] the LLM call failed for {label}: {exc}", file=sys.stderr)
        return ""


def _build_topics_section(use_api: bool = False) -> str:
    """Return markdown table of topics."""
    if not TOPICS_DIR.exists():
        return "*(no topics found)*\n"

    rows = []
    for md in sorted(TOPICS_DIR.glob("*.md")):
        rel = md.relative_to(WIKI_DIR).as_posix()
        title = _page_title(md)
        text = md.read_text(encoding="utf-8")
        section = _extract_section(text, "Summary") or _extract_section(text, "Overview")
        if section:
            desc = _first_sentence(section)
        else:
            # First non-heading, non-frontmatter paragraph
            body_lines = [
                ln for ln in text.splitlines()
                if ln.strip() and not ln.startswith("#") and not ln.startswith("---")
            ]
            desc = _first_sentence(" ".join(body_lines)) if body_lines else ""
        if not desc and use_api:
            desc = _llm_summary(text, title)
        rows.append(f"| [{title}]({rel}) | {desc} |")

    header = "| Page | Description |\n| --- | --- |"
    return header + "\n" + "\n".join(rows) if rows else "*(none)*"


def _build_sources_section() -> str:
    """Return markdown table of source pages (research mode: wiki/sources/)."""
    rows = []
    for md in sorted(SOURCES_DIR.glob("*.md")) if SOURCES_DIR.exists() else []:
        rel = md.relative_to(WIKI_DIR).as_posix()
        fm = _parse_frontmatter(md.read_text(encoding="utf-8"))
        title = fm.get("title") or _page_title(md)
        rows.append(f"| [{title}]({rel}) | {fm.get('type', '')} | {fm.get('ingested', '')} |")
    header = "| Title | Type | Ingested |\n| --- | --- | --- |"
    return header + "\n" + "\n".join(rows) if rows else ""


def _build_entities_section() -> str:
    """Return markdown table of entity pages (research mode: wiki/entities/)."""
    rows = []
    for md in sorted(ENTITIES_DIR.glob("*.md")) if ENTITIES_DIR.exists() else []:
        rel = md.relative_to(WIKI_DIR).as_posix()
        fm = _parse_frontmatter(md.read_text(encoding="utf-8"))
        name = fm.get("name") or _page_title(md)
        rows.append(f"| [{name}]({rel}) | {fm.get('entity_type', '')} |")
    header = "| Name | Type |\n| --- | --- |"
    return header + "\n" + "\n".join(rows) if rows else ""


# ---------------------------------------------------------------------------
# Ingested Documents — incremental update
# ---------------------------------------------------------------------------

def _existing_ingest_rows(index_text: str) -> Tuple[List[str], set]:
    """Return (existing_rows, set_of_known_filenames) from current INDEX.md."""
    section = (_extract_section(index_text, "Ingested Documents Log")
               or _extract_section(index_text, "Ingested Documents"))
    rows: List[str] = []
    known: set = set()
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        # Skip header rows
        stripped = line.strip("| \t")
        if (stripped.startswith(("Document", "Original File", "Filename"))
                or stripped.startswith("---")):
            continue
        rows.append(line)
        # First column is the filename
        cols = [c.strip() for c in line.split("|") if c.strip()]
        if cols:
            known.add(cols[0])
    return rows, known


def _build_ingest_section(index_text: str) -> str:
    """Return the full Ingested Documents table, preserving existing rows."""
    existing_rows, known_filenames = _existing_ingest_rows(index_text)

    new_rows: List[str] = []
    manifest = read_json(MANIFEST_FILE, {})
    if isinstance(manifest, dict):
        for entry in manifest.values():
            if not isinstance(entry, dict):
                continue
            filename = entry.get("filename", "")
            if filename in known_filenames:
                continue
            processed = entry.get("processed", "")
            date_str = processed[:10] if processed else ""
            wiki_page = entry.get("wiki_page", "")
            # Build a relative link: wiki_page is like "wiki/sources/foo.md"
            if wiki_page:
                page_path = Path(wiki_page)
                stem = page_path.stem
                # Relative from wiki/ — strip leading "wiki/" prefix
                parts = page_path.parts
                try:
                    wiki_idx = parts.index("wiki")
                    rel_parts = parts[wiki_idx + 1:]
                    rel = "/".join(rel_parts)
                except ValueError:
                    rel = wiki_page
                wiki_cell = f"[{stem}]({rel})"
            else:
                wiki_cell = ""
            new_rows.append(f"| {filename} | {date_str} | {wiki_cell} |")
            known_filenames.add(filename)

    header = "| Original File | Date Processed | Wiki Page |\n| --- | --- | --- |"
    all_rows = existing_rows + new_rows
    return header + "\n" + "\n".join(all_rows) if all_rows else header


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------

def build_index(dry_run: bool = False, use_api: bool = False) -> None:
    """Regenerate wiki/INDEX.md."""
    if dry_run:
        use_api = False  # a dry run never calls Claude
    # Load existing index text for incremental ingest section
    index_text = INDEX_FILE.read_text(encoding="utf-8") if INDEX_FILE.exists() else ""

    print("Building index sections…")
    topics_table = _build_topics_section(use_api)
    sources_table = _build_sources_section()
    entities_table = _build_entities_section()
    ingest_table = _build_ingest_section(index_text)

    parts = [
        f"---\nupdated: {TODAY}\n---\n",
        "# Research Wiki Index\n",
        f"*Maintained by Claude. Last updated: {TODAY} (auto-generated by build_index.py)*\n",
        "---\n",
        f"## Topics\n\n{topics_table}\n\n---\n",
    ]
    if sources_table:
        parts.append(f"## Sources\n\n{sources_table}\n\n---\n")
    if entities_table:
        parts.append(f"## Entities\n\n{entities_table}\n\n---\n")
    parts.append(f"## Ingested Documents Log\n\n{ingest_table}\n\n---\n")
    parts.append("*This file is auto-generated. Do not edit manually.*\n")
    content = "\n".join(parts)

    # Stats
    print(f"  Topics:          {topics_table.count(chr(10) + '| [')}")
    print(f"  Sources:         {sources_table.count(chr(10) + '| [')}")
    print(f"  Entities:        {entities_table.count(chr(10) + '| [')}")
    print(f"  Ingest rows:     {max(ingest_table.count(chr(10) + '| ') - 1, 0)}")

    if dry_run:
        print("--dry-run: INDEX.md not written.")
        return

    atomic_write_text(INDEX_FILE, content)
    print(f"Written: {INDEX_FILE}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Regenerate wiki/INDEX.md from current wiki content."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats but do not write INDEX.md. Makes no Claude calls.",
    )
    parser.add_argument(
        "--use-api", "--use-llm", dest="use_api",
        action="store_true",
        help="Call the LLM (scripts/llm.py) for topics where no summary can be extracted.",
    )
    args = parser.parse_args()

    os.chdir(WIKI_ROOT)
    if args.dry_run and args.use_api:
        print("--dry-run: skipping --use-llm (no Claude calls are made in a dry run).")
        args.use_api = False
    build_index(dry_run=args.dry_run, use_api=args.use_api)
