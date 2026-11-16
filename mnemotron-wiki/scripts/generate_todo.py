#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
generate_todo.py — Generate a prioritized to-do list from wiki content.

Reads recent daily entries, upcoming calendar events (meeting-cadence.md),
open action item threads, and selected topic pages, then calls Claude
to synthesize a prioritized to-do list. Writes output to the configured
log directory.

Usage:
    python scripts/generate_todo.py
    python scripts/generate_todo.py --date 2026-06-18
    python scripts/generate_todo.py --output /path/to/output.md
    python scripts/generate_todo.py --include-asana   # include Asana tasks (off by default)
    python scripts/generate_todo.py --dry-run         # gather context and show what would happen; NO Claude call, no file
    python scripts/generate_todo.py --print           # call Claude, print the list to stdout, don't write a file
    python scripts/generate_todo.py --topics example-project another-topic

Default output directory: <LOG_ROOT>/<YYYY-MM>/  (LOG_ROOT: see config.py, default ./logs)
Default output filename:  <YYYYMMDD>.md
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import (
    WIKI_ROOT, DAILY_DIR as WIKI_DAILY, TOPICS_DIR as WIKI_TOPICS, LOG_ROOT,
    ALWAYS_READ_TOPICS, BRIEFINGS_DIR, OWNER_NAME, OWNER_ROLE, local_today,
)

_OWNER = ", ".join(x for x in (OWNER_NAME, OWNER_ROLE) if x) or "the wiki owner"

SYSTEM_PROMPT = """You are a personal work assistant generating a prioritized to-do list for
{owner}.

Your output is a Markdown to-do list organized by time horizon:
  Today / Tomorrow / This Week / Next Week / Hard Deadlines / Ongoing & Monitoring

Rules:
- {asana_rule}
- Do not invent tasks not grounded in the provided context.
- Group related items together. Keep each item to 1–3 lines: what, why/context, source.
- Flag hard deadlines explicitly with their dates.
- Include upcoming calendar events as lightweight prep reminders.
- Include open relationship or reconnection items only if they are time-sensitive or flagged
  as high-priority in the wiki.
- Keep total length practical — a to-do list, not a project plan.
- Use [ ] checkboxes for all action items.
- Add a brief _italicized_ source note after each item (e.g., _[1:1 with Jane, 6/18]_).

Output plain Markdown only. No preamble, no explanations outside the list."""

ASANA_EXCLUDE_RULE = (
    "Do NOT include tasks that are primarily tracked in Asana — these are handled through "
    "Asana directly. Only include items that arrived via email, 1:1 meetings, calendar events, "
    "or wiki open-thread context. If an item overlaps with Asana but also has independent "
    "relevance (e.g., a relationship follow-up or a deadline context), include only the "
    "non-Asana aspect."
)

ASANA_INCLUDE_RULE = (
    "Include all action items, including those tracked in Asana."
)


def read_recent_daily_entries(today: date, n: int = 3) -> list[tuple[str, str]]:
    entries = []
    for delta in range(n):
        d = today - timedelta(days=delta)
        p = WIKI_DAILY / f"{d.isoformat()}.md"
        if p.exists():
            entries.append((d.isoformat(), p.read_text(encoding="utf-8")))
    return entries


def read_topics(topic_slugs: list[str]) -> list[tuple[str, str]]:
    results = []
    for slug in topic_slugs:
        fname = slug if slug.endswith(".md") else f"{slug}.md"
        p = WIKI_TOPICS / fname
        if p.exists():
            results.append((slug, p.read_text(encoding="utf-8")))
    return results


def read_morning_brief(today: date):
    p = BRIEFINGS_DIR / f"morning-brief_{today.isoformat()}.md"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def build_context(today: date, extra_topics: list[str], include_asana: bool) -> str:
    parts = [f"Today's date: {today.isoformat()} ({today.strftime('%A')})\n"]

    brief = read_morning_brief(today)
    if brief:
        parts.append(f"## Morning Briefing\n\n{brief}\n")

    entries = read_recent_daily_entries(today, n=3)
    if entries:
        parts.append("## Recent Daily Entries\n")
        for dt, content in entries:
            parts.append(f"### {dt}\n\n{content}\n")

    all_topics = list(dict.fromkeys(ALWAYS_READ_TOPICS + extra_topics))
    topic_data = read_topics(all_topics)
    if topic_data:
        parts.append("## Relevant Topic Pages\n")
        for slug, content in topic_data:
            parts.append(f"### {slug}\n\n{content}\n")

    return "\n".join(parts)


def generate_todo(context: str, include_asana: bool, today: date) -> str:
    try:
        from scripts.llm import generate
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from llm import generate

    asana_rule = ASANA_INCLUDE_RULE if include_asana else ASANA_EXCLUDE_RULE
    system = SYSTEM_PROMPT.format(asana_rule=asana_rule, owner=_OWNER)

    return generate(
        system,
        f"Generate a to-do list for {today.isoformat()} based on the following "
        f"wiki context:\n\n{context}",
    )


def default_output_path(today: date) -> Path:
    month_dir = LOG_ROOT / today.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    return month_dir / f"{today.strftime('%Y%m%d')}.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a prioritized to-do list from wiki content.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Date to generate for (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path. Defaults to <LOG_ROOT>/YYYY-MM/YYYYMMDD.md (see config.py).",
    )
    parser.add_argument(
        "--include-asana",
        action="store_true",
        default=False,
        help="Include Asana-tracked tasks in the output (default: excluded).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Gather the wiki context and report what would be sent and written. "
             "Makes NO Claude call and writes nothing.",
    )
    parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        default=False,
        help="Call Claude, then print the to-do list to stdout instead of writing a file.",
    )
    parser.add_argument(
        "--topics",
        nargs="*",
        default=[],
        metavar="SLUG",
        help="Additional topic page slugs to include in context (e.g. example-project).",
    )
    args = parser.parse_args()

    today = date.fromisoformat(args.date) if args.date else local_today()

    print(f"Generating to-do list for {today.isoformat()}...", file=sys.stderr)
    context = build_context(today, args.topics, args.include_asana)

    if args.dry_run:
        out_path = Path(args.output) if args.output else default_output_path(today)
        print(f"--dry-run: no Claude call made and nothing written.\n"
              f"  Context gathered: {len(context):,} characters\n"
              f"  Would write:      {out_path}\n"
              f"  (Use --print to call Claude and print the result without writing a file.)")
        return

    print("Calling the LLM to synthesize list...", file=sys.stderr)
    todo_text = generate_todo(context, args.include_asana, today)

    header = (
        f"# To-Do — {today.strftime('%A, %B %-d, %Y')}\n\n"
        f"_Generated by generate_todo.py from wiki context. "
        f"{'Asana tasks included.' if args.include_asana else 'Asana tasks excluded (default).'}_ \n\n---\n\n"
    )
    output = header + todo_text

    if args.print_only:
        print(output)
        return

    out_path = Path(args.output) if args.output else default_output_path(today)
    out_path.write_text(output)
    print(f"  → Written to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
