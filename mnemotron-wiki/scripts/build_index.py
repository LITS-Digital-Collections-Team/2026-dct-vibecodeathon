# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
build_index.py — Regenerate wiki/INDEX.md from current wiki content.

Covers daily, topics, people, organizations, documents and email pages.
Sections whose folders are empty or absent are omitted.  The Ingested Documents Log is updated incrementally: existing
rows (with hand-written notes) are preserved and new manifest entries are
appended.

Usage:
    python scripts/build_index.py            # regenerate INDEX.md
    python scripts/build_index.py --dry-run  # print stats, don't write
    python scripts/build_index.py --use-api  # use the LLM for missing summaries
"""

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import (
    DAILY_DIR,
    DOCUMENTS_DIR,
    EMAIL_DIR,
    MANIFEST_FILE,
    ORGS_DIR,
    PEOPLE_DIR,
    TOPICS_DIR,
    WIKI_DIR,
    WIKI_ROOT,
    local_today,
)

INDEX_FILE = WIKI_DIR / "INDEX.md"
TODAY = local_today().isoformat()


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

def _summarise_daily(text: str, use_api: bool, label: str) -> str:
    """Extract or generate a one-line summary for a daily entry."""
    # Try ## Briefing Summary first
    section = _extract_section(text, "Briefing Summary")
    if section:
        return _first_sentence(section)
    # Fallback: ## Update
    section = _extract_section(text, "Update")
    if section:
        return _first_sentence(section)
    # Fallback: first 100 chars of body (skip frontmatter and headings)
    body_lines = [
        ln for ln in text.splitlines()
        if ln.strip() and not ln.startswith("#") and not ln.startswith("---")
    ]
    if body_lines:
        snippet = " ".join(body_lines)[:100].strip()
        if snippet:
            return snippet
    # Optional API call
    if use_api:
        return _llm_summary(text, label)
    return ""


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


# ---------------------------------------------------------------------------
# Weekly / summary entry label formatting
# ---------------------------------------------------------------------------

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _format_week_label(stem: str) -> str:
    """Convert a special daily filename stem into a human-readable label.

    Patterns:
        YYYY-MM-DD-week        → "Week of Mon D–D" (or "Mon D–Mon D")
        YYYY-MM-DD-ytd-summary → "YTD Summary — Mon D through Mon D"
        YYYY-MM-monthly        → "Monthly Report — Month YYYY"
    """
    # --- weekly ---
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})-week$", stem)
    if m:
        try:
            start = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            end = start + timedelta(days=4)
            if start.month == end.month:
                return f"Week of {_MONTH_NAMES[start.month]} {start.day}–{end.day}"
            return (
                f"Week of {_MONTH_NAMES[start.month]} {start.day}"
                f"–{_MONTH_NAMES[end.month]} {end.day}"
            )
        except ValueError:
            pass

    # --- ytd-summary ---
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})-ytd-summary$", stem)
    if m:
        try:
            end_dt = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return (
                f"YTD Summary — Feb 2 through "
                f"{_MONTH_NAMES[end_dt.month]} {end_dt.day}"
            )
        except ValueError:
            pass

    # --- monthly ---
    m = re.match(r"^(\d{4})-(\d{2})-monthly$", stem)
    if m:
        try:
            yr, mo = int(m.group(1)), int(m.group(2))
            return f"Monthly Report — {_MONTH_NAMES[mo]} {yr}"
        except ValueError:
            pass

    # Fallback: stem with hyphens → spaces, title-cased
    return stem.replace("-", " ").title()


def _is_regular_daily(stem: str) -> bool:
    """Return True if stem matches YYYY-MM-DD (8-char date, regular entry)."""
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", stem))


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_daily_section(use_api: bool) -> Tuple[str, str]:
    """Return (regular_table_md, weekly_table_md)."""
    if not DAILY_DIR.exists():
        return "*(no daily entries found)*\n", "*(no weekly entries found)*\n"

    regular: List[Tuple[str, Path]] = []   # (date_str, path)
    weekly: List[Tuple[str, Path]] = []    # (stem, path)

    for md in sorted(DAILY_DIR.glob("*.md")):
        stem = md.stem
        if _is_regular_daily(stem):
            regular.append((stem, md))
        else:
            weekly.append((stem, md))

    # Regular entries — sorted descending by date
    regular.sort(key=lambda x: x[0], reverse=True)
    reg_rows = []
    for date_str, path in regular:
        rel = path.relative_to(WIKI_DIR).as_posix()
        text = path.read_text(encoding="utf-8")
        summary = _summarise_daily(text, use_api, date_str)
        row = f"| [{date_str}]({rel}) | {summary} |"
        reg_rows.append(row)

    reg_header = "| Date | Summary |\n| --- | --- |"
    reg_table = reg_header + "\n" + "\n".join(reg_rows) if reg_rows else "*(none)*"

    # Weekly/summary entries — sorted descending by stem (date prefix)
    weekly.sort(key=lambda x: x[0], reverse=True)
    wk_rows = []
    for stem, path in weekly:
        rel = path.relative_to(WIKI_DIR).as_posix()
        label = _format_week_label(stem)
        text = path.read_text(encoding="utf-8")
        summary = _summarise_daily(text, use_api, stem)
        row = f"| [{label}]({rel}) | {summary} |"
        wk_rows.append(row)

    wk_header = "| Week | Summary |\n| --- | --- |"
    wk_table = wk_header + "\n" + "\n".join(wk_rows) if wk_rows else "*(none)*"

    return reg_table, wk_table


def _build_topics_section() -> str:
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
        rows.append(f"| [{title}]({rel}) | {desc} |")

    header = "| Page | Description |\n| --- | --- |"
    return header + "\n" + "\n".join(rows) if rows else "*(none)*"


def _build_people_section() -> str:
    """Return markdown table of people, sorted by last name."""
    if not PEOPLE_DIR.exists():
        return "*(no people found)*\n"

    entries: List[Tuple[str, str]] = []  # (last_name_lower, row)
    for md in PEOPLE_DIR.glob("*.md"):
        rel = md.relative_to(WIKI_DIR).as_posix()
        text = md.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        name = fm.get("name", _page_title(md))
        title = fm.get("title", "")
        org = fm.get("organization", "")
        relationship = fm.get("relationship", "")
        last_name = name.strip().split()[-1].lower() if name.strip() else ""
        row = f"| [{name}]({rel}) | {title} | {org} | {relationship} |"
        entries.append((last_name, row))

    entries.sort(key=lambda x: x[0])
    header = "| Name | Title | Organization | Relationship |\n| --- | --- | --- | --- |"
    rows = [r for _, r in entries]
    return header + "\n" + "\n".join(rows) if rows else "*(none)*"


def _build_email_section() -> str:
    """Return markdown table of email archive pages (wiki/email/)."""
    rows = []
    for md in sorted(EMAIL_DIR.glob("*.md"), reverse=True) if EMAIL_DIR.exists() else []:
        rel = md.relative_to(WIKI_DIR).as_posix()
        fm = _parse_frontmatter(md.read_text(encoding="utf-8"))
        title = fm.get("subject") or fm.get("title") or _page_title(md)
        rows.append(f"| [{title}]({rel}) | {fm.get('date', fm.get('last_updated', ''))} |")
    header = "| Email | Date |\n| --- | --- |"
    return header + "\n" + "\n".join(rows) if rows else ""


def _build_documents_section() -> str:
    """Return markdown table of converted documents (wiki/documents/)."""
    if not DOCUMENTS_DIR.exists():
        return "*(no documents found)*\n"

    rows = []
    for md in sorted(DOCUMENTS_DIR.glob("*.md")):
        rel = md.relative_to(WIKI_DIR).as_posix()
        title = _page_title(md)
        text = md.read_text(encoding="utf-8")
        m = re.search(r"^\*\*Summary:\*\*\s*(.+)$", text, re.MULTILINE)
        desc = _first_sentence(m.group(1)) if m else ""
        fm = _parse_frontmatter(text)
        source = fm.get("source_file", "")
        rows.append(f"| [{title}]({rel}) | {desc} | {source} |")

    header = "| Document | Summary | Source File |\n| --- | --- | --- |"
    return header + "\n" + "\n".join(rows) if rows else "*(none)*"


def _build_orgs_section() -> str:
    """Return markdown table of organizations."""
    if not ORGS_DIR.exists():
        return "*(no organizations found)*\n"

    rows = []
    for md in sorted(ORGS_DIR.glob("*.md")):
        rel = md.relative_to(WIKI_DIR).as_posix()
        title = _page_title(md)
        text = md.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        org_type = fm.get("organization_type", fm.get("type", ""))
        section = _extract_section(text, "Profile")
        desc = _first_sentence(section) if section else ""
        rows.append(f"| [{title}]({rel}) | {org_type} | {desc} |")

    header = "| Organization | Type | Description |\n| --- | --- | --- |"
    return header + "\n" + "\n".join(rows) if rows else "*(none)*"


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
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            manifest: Dict = json.load(f)
        for entry in manifest.values():
            filename = entry.get("filename", "")
            if filename in known_filenames:
                continue
            processed = entry.get("processed", "")
            date_str = processed[:10] if processed else ""
            wiki_page = entry.get("wiki_page", "")
            # Build a relative link: wiki_page is like "wiki/people/foo.md"
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
    reg_table, wk_table = _build_daily_section(use_api)
    has_daily = DAILY_DIR.exists() and any(DAILY_DIR.glob("*.md"))
    topics_table = _build_topics_section()
    ingest_table = _build_ingest_section(index_text)

    # (heading, table markdown) in display order; empty/absent sections are skipped.
    optional = [
        ("People", _build_people_section() if PEOPLE_DIR.exists() and any(PEOPLE_DIR.glob("*.md")) else ""),
        ("Organizations", _build_orgs_section() if ORGS_DIR.exists() and any(ORGS_DIR.glob("*.md")) else ""),
        ("Documents", _build_documents_section() if DOCUMENTS_DIR.exists() and any(DOCUMENTS_DIR.glob("*.md")) else ""),
        ("Email", _build_email_section()),
    ]

    parts = [
        f"---\nupdated: {TODAY}\n---\n",
        "# Wiki Index\n",
        f"*Maintained by Claude. Last updated: {TODAY} (auto-generated by build_index.py)*\n",
        "---\n",
    ]
    if has_daily:
        parts.append(f"## Daily Entries\n\n{reg_table}\n\n### Weekly Journal Entries\n\n{wk_table}\n\n---\n")
    parts.append(f"## Topics\n\n{topics_table}\n\n---\n")
    for heading, table in optional:
        if table:
            parts.append(f"## {heading}\n\n{table}\n\n---\n")
    parts.append(f"## Ingested Documents Log\n\n{ingest_table}\n\n---\n")
    parts.append("*This file is auto-generated. Do not edit manually.*\n")
    content = "\n".join(parts)

    # Stats
    print(
        f"  Daily entries:   {reg_table.count(chr(10) + '| [')} regular, "
        f"{wk_table.count(chr(10) + '| [')} weekly/summary\n"
        f"  Topics:          {topics_table.count(chr(10) + '| [')}"
    )
    for heading, table in optional:
        if table:
            print(f"  {heading + ':':<16} {table.count(chr(10) + '| [')}")
    print(f"  Ingest rows:     {max(ingest_table.count(chr(10) + '| ') - 1, 0)}")

    if dry_run:
        print("--dry-run: INDEX.md not written.")
        return

    INDEX_FILE.write_text(content, encoding="utf-8")
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
        help="Call the LLM for entries where no summary can be extracted.",
    )
    args = parser.parse_args()

    os.chdir(WIKI_ROOT)
    if args.dry_run and args.use_api:
        print("--dry-run: skipping --use-llm (no Claude calls are made in a dry run).")
        args.use_api = False
    build_index(dry_run=args.dry_run, use_api=args.use_api)
