# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
generate_daily_entry.py — Synthesize a morning briefing into a daily wiki entry.

Calls Claude to produce a dated wiki entry from a morning briefing file,
optionally incorporating an Asana weekly export. If the briefing contains a
Relationship Pulse section, the LLM also updates wiki/topics/relationship-pulse.md.

Usage (from wiki root):
    python scripts/generate_daily_entry.py raw_ingest/briefings/morning-brief_2026-06-05.md
    python scripts/generate_daily_entry.py raw_ingest/briefings/morning-brief_2026-06-05.md \\
        --asana-weekly raw_ingest/asana/asana-weekly-2026-06-01.md
    python scripts/generate_daily_entry.py --auto   # auto-discover most-recent unprocessed briefing today
    python scripts/generate_daily_entry.py --auto --date 2026-06-05
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import WIKI_ROOT, DAILY_DIR, TOPICS_DIR, BRIEFINGS_DIR, OWNER_NAME, OWNER_ROLE
from scripts.manifest import load_manifest, is_processed, mark_processed, save_manifest

# ---------------------------------------------------------------------------
# Model and prompt constants
# ---------------------------------------------------------------------------

MODEL = None  # None = backend default (see scripts/llm.py)
MAX_TOKENS_DAILY = 1500
MAX_TOKENS_PULSE = 2048

_DAILY_TEMPLATE = """\
You write concise dated daily wiki entries for a personal work wiki maintained
by {owner}.

Entry format rules:
- Briefing Summary: 2–4 sentences of prose (not bullets). Cover: key meetings,
  notable emails or actions needed, overall character of the day. Be specific
  about meeting names and times. Do NOT reproduce the full schedule; synthesize.
- Asana section: if Asana data is present, 2–4 sentences of prose covering
  overdue items and near-term deadlines. If absent, one sentence noting this.
- Related Topics: only include links clearly referenced in the briefing.
  Use relative paths like ../people/name.md or ../topics/slug.md.
- Do not invent content not present in the source.
- Do not include a Relationship Pulse section in the daily entry.\
"""

_owner = ", ".join(x for x in (OWNER_NAME, OWNER_ROLE) if x) or "the wiki owner"
DAILY_SYSTEM_PROMPT = _DAILY_TEMPLATE.replace("{owner}", _owner)

PULSE_SYSTEM_PROMPT = """\
You update a Relationship Pulse status table in a personal work wiki.
The table tracks recurring professional relationships at risk of neglect.
Return the COMPLETE updated file — all content, not just the changed section.
Make only the changes indicated. Do not add new rows unless the person
appears in the pulse section but has no existing row.\
"""

# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_PULSE_RE = re.compile(r"^#+\s+(?:🤝\s+)?Relationship Pulse", re.MULTILINE | re.IGNORECASE)


def extract_date_from_filename(filepath: Path) -> Optional[str]:
    """Extract YYYY-MM-DD from a filename like morning-brief_2026-06-05.md."""
    m = _DATE_RE.search(filepath.stem)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Pulse section extraction
# ---------------------------------------------------------------------------

def extract_pulse_section(text: str) -> Optional[str]:
    """
    Return the content of the Relationship Pulse section, or None if absent.

    Captures from the heading line through to the next ## heading or EOF.
    """
    m = _PULSE_RE.search(text)
    if not m:
        return None
    start = m.start()
    # Find the next heading at the same or higher level after the pulse heading
    rest = text[m.end():]
    next_heading = re.search(r"^##", rest, re.MULTILINE)
    if next_heading:
        section = text[start: m.end() + next_heading.start()]
    else:
        section = text[start:]
    return section.strip()


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

def call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> str:
    """Call Claude; return response text."""
    try:
        from scripts.llm import generate
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from llm import generate

    return generate(system_prompt, user_prompt, model=MODEL, max_tokens=max_tokens)


def generate_daily_entry(
    date: str,
    briefing_path: Path,
    briefing_content: str,
    asana_path: Optional[Path],
    asana_content: Optional[str],
    existing_content: Optional[str],
) -> str:
    """Build the user prompt and call the LLM for the daily wiki entry."""
    filename = briefing_path.name
    asana_context = (
        f"ASANA WEEKLY CONTENT:\n{asana_content}\n" if asana_content else ""
    )
    asana_source_line = (
        f"  - {asana_path.name}\n" if asana_path else ""
    )

    if existing_content:
        existing_entry_instruction = (
            "The daily entry for this date already exists. "
            "Produce ONLY an ## Update section (with current timestamp note) "
            "containing new information not already in the existing entry:\n\n"
            + existing_content
        )
    else:
        existing_entry_instruction = ""

    user_prompt = (
        f"Date: {date}\n"
        f"Briefing file: {filename}\n\n"
        f"{asana_context}"
        f"BRIEFING CONTENT:\n{briefing_content}\n\n"
        f"{existing_entry_instruction}\n\n"
        "OUTPUT — write exactly this format (omit Related Topics if none):\n\n"
        "---\n"
        f"date: {date}\n"
        "sources:\n"
        f"  - {filename}\n"
        f"{asana_source_line}"
        "---\n\n"
        f"# {date}\n\n"
        "## Briefing Summary\n\n"
        "[prose]\n\n"
        "## Asana\n\n"
        "[prose]\n\n"
        "## Related Topics\n\n"
        "- [Name](../people/name.md) or [Topic](../topics/slug.md) — only if clearly relevant"
    )

    return call_llm(DAILY_SYSTEM_PROMPT, user_prompt, MAX_TOKENS_DAILY)


def update_relationship_pulse(
    date: str,
    pulse_section: str,
    current_pulse_content: str,
) -> str:
    """Call the LLM to produce an updated relationship-pulse.md and return it."""
    user_prompt = (
        f"CURRENT RELATIONSHIP-PULSE.MD:\n{current_pulse_content}\n\n"
        f"NEW PULSE DATA FROM TODAY'S BRIEFING ({date}):\n{pulse_section}\n\n"
        "Update the Status Table:\n"
        "- For each person in the pulse section: update Last Contact, Upcoming, and Notes columns\n"
        "- Add new rows only for people who appear but have no existing row\n"
        "- Return the complete updated file verbatim"
    )
    return call_llm(PULSE_SYSTEM_PROMPT, user_prompt, MAX_TOKENS_PULSE)


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------

def find_unprocessed_briefing(manifest: dict) -> Optional[Path]:
    """
    Scan BRIEFINGS_DIR for unprocessed briefing files and return the most
    recent one (by filename date, then mtime as tiebreaker).
    """
    if not BRIEFINGS_DIR.exists():
        return None

    candidates = []
    for f in BRIEFINGS_DIR.glob("morning-brief_*.md"):
        if f.is_file() and not is_processed(f, manifest):
            date_str = extract_date_from_filename(f)
            candidates.append((date_str or "", f.stat().st_mtime, f))

    if not candidates:
        return None

    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return candidates[0][2]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthesize a morning briefing into a daily wiki entry."
    )
    parser.add_argument(
        "briefing",
        nargs="?",
        help="Path to the morning briefing .md file.",
    )
    parser.add_argument(
        "--asana-weekly",
        metavar="FILE",
        help="Optional path to an Asana weekly export to incorporate.",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Override the date extracted from the briefing filename.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-discover the most recent unprocessed briefing.",
    )
    args = parser.parse_args()

    os.chdir(WIKI_ROOT)

    manifest = load_manifest()

    # Resolve briefing path
    if args.auto:
        briefing_path = find_unprocessed_briefing(manifest)
        if briefing_path is None:
            print("No unprocessed briefing files found.")
            sys.exit(0)
    elif args.briefing:
        briefing_path = Path(args.briefing)
    else:
        parser.error("Provide a briefing file path or use --auto.")

    if not briefing_path.exists():
        print(f"Error: briefing file not found: {briefing_path}", file=sys.stderr)
        sys.exit(1)

    # Resolve date
    date = args.date or extract_date_from_filename(briefing_path)
    if not date:
        print(
            f"Error: could not extract date from filename '{briefing_path.name}'. "
            "Use --date YYYY-MM-DD to provide it explicitly.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve optional Asana weekly
    asana_path: Optional[Path] = None
    asana_content: Optional[str] = None
    if args.asana_weekly:
        asana_path = Path(args.asana_weekly)
        if not asana_path.exists():
            print(f"Error: Asana weekly file not found: {asana_path}", file=sys.stderr)
            sys.exit(1)
        asana_content = asana_path.read_text(encoding="utf-8", errors="replace")

    # Read briefing
    briefing_content = briefing_path.read_text(encoding="utf-8", errors="replace")

    # Check for existing daily entry
    daily_file = DAILY_DIR / f"{date}.md"
    existing_content: Optional[str] = None
    if daily_file.exists():
        existing_content = daily_file.read_text(encoding="utf-8", errors="replace")
        print(f"Note: daily entry for {date} already exists — will append an ## Update section.")

    # --- Generate daily entry ---
    print(f"Generating daily entry for {date}...")
    try:
        entry_text = generate_daily_entry(
            date=date,
            briefing_path=briefing_path,
            briefing_content=briefing_content,
            asana_path=asana_path,
            asana_content=asana_content,
            existing_content=existing_content,
        )
    except Exception as exc:
        print(f"Error calling the LLM for daily entry: {exc}", file=sys.stderr)
        sys.exit(1)

    # Write or append daily entry
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing wiki/daily/{date}.md")
    if existing_content:
        # Append the Update section returned by the LLM
        updated = existing_content.rstrip() + "\n\n" + entry_text.strip() + "\n"
        daily_file.write_text(updated, encoding="utf-8")
    else:
        daily_file.write_text(entry_text, encoding="utf-8")

    # --- Update Relationship Pulse if section present ---
    pulse_section = extract_pulse_section(briefing_content)
    if pulse_section:
        pulse_file = TOPICS_DIR / "relationship-pulse.md"
        if pulse_file.exists():
            current_pulse = pulse_file.read_text(encoding="utf-8", errors="replace")
        else:
            current_pulse = (
                "---\nupdated: \"\"\ntags:\n  - relationships\n---\n\n"
                "# Relationship Pulse\n\n"
                "## Status Table\n\n"
                "| Person | Relationship | Last Contact | Upcoming | Notes |\n"
                "|--------|-------------|-------------|----------|-------|\n"
            )
        print("Updating relationship-pulse.md")
        try:
            updated_pulse = update_relationship_pulse(
                date=date,
                pulse_section=pulse_section,
                current_pulse_content=current_pulse,
            )
        except Exception as exc:
            print(f"Error calling the LLM for relationship pulse: {exc}", file=sys.stderr)
            sys.exit(1)
        TOPICS_DIR.mkdir(parents=True, exist_ok=True)
        pulse_file.write_text(updated_pulse, encoding="utf-8")

    # --- Manifest and cleanup ---
    wiki_page = Path(f"wiki/daily/{date}.md")

    if asana_path:
        manifest = mark_processed(asana_path, wiki_page, manifest)
        save_manifest(manifest)

    manifest = mark_processed(briefing_path, wiki_page, manifest)
    save_manifest(manifest)

    briefing_path.unlink()

    print("Done.")


if __name__ == "__main__":
    main()
