# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Developed with assistance from Claude (Anthropic).
# Reviewed and tested; verify behavior in your own environment.

"""
ingest_asana_project.py — Ingest a single Asana-sourced markdown file into
the wiki, refreshing the existing topic page if the project has been
ingested before.

Why a dedicated path?
---------------------
The general document-ingest flow (Stage 2 of WIKI_UPDATE_TASK.md) synthesises
prose freshly for each new file and relies on the content-hash manifest to
avoid reprocessing a byte-identical file.  That works well for one-off
documents (PDFs, briefings, etc.) but not for Asana-project histories, which
are *idempotent summaries of live project state*.  Re-running should update
the existing topic page, not create a duplicate.

This helper routes Asana-sourced files through a path that is aware of the
stable project_gid and preserves user-authored content.

What it does
------------
  1. Parse the YAML front-matter of the raw file to read project_gid,
     title, and other Asana metadata.
  2. Look up project_gid in .asana_manifest.json.
  3. If the raw content is byte-identical to the cached version from the
     last run, exit 0 with "unchanged: <path>" and touch nothing.
  4. Otherwise, write or update the topic page at wiki/topics/<slug>.md.
     - If the page already has the auto-markers
       (`<!-- asana:auto-start -->` / `<!-- asana:auto-end -->`), only
       the content between them is replaced; everything else (e.g. a
       user-authored "Notes" section) is preserved.
     - If the page exists but has no markers, the refreshed snapshot is
       appended rather than overwriting whatever is there.
     - If the page does not exist, a fresh page is written using the
       template below.
  5. Update the cache and the Asana manifest.
  6. Print the wiki page path to stdout so Stage 2 can record it in the
     main content-hash manifest.

Exit codes:
  0 — success (printed either the wiki page path or "unchanged: <path>")
  1 — error (missing frontmatter, no project_gid, file not found, etc.)

Usage:
    python scripts/ingest_asana_project.py raw_ingest/asana/dc-brothertown.md
"""

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import TOPICS_DIR, WIKI_ROOT
from scripts.asana_manifest import (
    get_cached_content,
    load_asana_manifest,
    lookup_project,
    mark_project_ingested,
    save_asana_manifest,
    write_cache,
)


# ---------------------------------------------------------------------------
# Markers used to delimit the auto-generated section inside a topic page.
# Content *between* the markers is overwritten on every refresh; content
# *outside* the markers is preserved verbatim.
# ---------------------------------------------------------------------------

AUTO_START = "<!-- asana:auto-start -->"
AUTO_END = "<!-- asana:auto-end -->"


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------
# PyYAML is the proper tool; if it isn't installed we fall back to a tiny
# parser that handles the flat `key: value` frontmatter produced by our
# Asana ingest.  Nothing nested is expected, so this is safe enough for
# the minimal-computing setup.

try:
    import yaml  # type: ignore

    def parse_frontmatter_yaml(text: str) -> dict:
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}

except ImportError:

    def parse_frontmatter_yaml(text: str) -> dict:
        out: dict = {}
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            # Strip surrounding quotes if present.
            v = value.strip()
            if (v.startswith('"') and v.endswith('"')) or (
                v.startswith("'") and v.endswith("'")
            ):
                v = v[1:-1]
            out[key.strip()] = v
        return out


def split_frontmatter(text: str) -> tuple[dict, str]:
    """
    Split *text* into (frontmatter_dict, body_str).
    Raises ValueError on malformed or missing frontmatter.
    """
    if not text.startswith("---"):
        raise ValueError("File does not begin with '---' (no frontmatter)")
    # The regex captures everything between the two '---' delimiters as
    # group 1 (YAML text) and everything after the closing delimiter as
    # group 2 (document body).  re.DOTALL lets '.' match newlines.
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        raise ValueError("Malformed frontmatter block")
    fm = parse_frontmatter_yaml(m.group(1))
    body = m.group(2)
    return fm, body


def slugify(name: str) -> str:
    """Lower-case, ascii-only slug with dashes."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


# ---------------------------------------------------------------------------
# Rendering the auto-generated block
# ---------------------------------------------------------------------------

def render_auto_block(fm: dict, body: str) -> str:
    """Render the content that lives between AUTO_START and AUTO_END."""
    perma = str(fm.get("permalink", "")).strip()
    created = str(fm.get("created_at", "")).strip()
    total = fm.get("tasks_total", "")
    done = fm.get("tasks_complete", "")
    todo = fm.get("tasks_incomplete", "")
    status = str(fm.get("current_status", "")).strip()

    lines: list[str] = [AUTO_START, ""]
    lines.append("## Asana snapshot")
    lines.append("")
    if perma:
        lines.append(f"- Permalink: {perma}")
    if created:
        lines.append(f"- Created: {created}")
    if total != "" and total is not None:
        lines.append(
            f"- Tasks: {done}/{total} complete ({todo} incomplete)"
        )
    if status and status.lower() != "none":
        lines.append(f"- Current status: {status}")
    lines.append(f"- Last refreshed: {date.today().isoformat()}")
    lines.append("")
    lines.append("## Project history")
    lines.append("")
    lines.append(body.strip())
    lines.append("")
    lines.append(AUTO_END)
    return "\n".join(lines)


def render_new_page(fm: dict, auto_block: str) -> str:
    """Build a fresh topic page from scratch."""
    title = str(fm.get("title", "Untitled Asana project")).strip()
    gid = str(fm.get("project_gid", "")).strip()

    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: {title}")
    lines.append(f"project_gid: {gid}")
    lines.append("source: Asana")
    lines.append(f"last_updated: {date.today().isoformat()}")
    lines.append("tags:")
    lines.append("  - asana")
    lines.append("  - digital-collections")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(auto_block)
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "_Manual notes go here; content outside the auto-markers is "
        "preserved across refreshes._"
    )
    lines.append("")
    return "\n".join(lines)


def update_frontmatter_date(page_text: str) -> str:
    """
    Update (or insert) the `last_updated` field in an existing page's
    frontmatter.  Idempotent; leaves everything else untouched.
    """
    today = date.today().isoformat()
    m = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)", page_text, re.DOTALL)
    if not m:
        return page_text
    head, fm_body, tail = m.group(1), m.group(2), m.group(3)
    if re.search(r"^last_updated:", fm_body, re.MULTILINE):
        fm_body = re.sub(
            r"^last_updated:.*$",
            f"last_updated: {today}",
            fm_body,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        fm_body = fm_body.rstrip() + f"\nlast_updated: {today}"
    return head + fm_body + tail + page_text[m.end():]


def refresh_existing_page(existing: str, auto_block: str) -> str:
    """
    Return *existing* with its auto-block replaced by *auto_block*.
    If the markers are missing, append a dated refresh snapshot rather
    than overwriting anything the user may have written.
    """
    if AUTO_START in existing and AUTO_END in existing:
        pattern = re.compile(
            re.escape(AUTO_START) + r".*?" + re.escape(AUTO_END),
            re.DOTALL,
        )
        updated = pattern.sub(auto_block, existing, count=1)
        return update_frontmatter_date(updated)

    # Legacy page without markers: append instead of overwriting.
    return (
        existing.rstrip()
        + f"\n\n## Refreshed snapshot ({date.today().isoformat()})\n\n"
        + auto_block
        + "\n"
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: python scripts/ingest_asana_project.py <filepath>",
            file=sys.stderr,
        )
        sys.exit(1)

    filepath = Path(sys.argv[1]).resolve()
    if not filepath.exists():
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    raw = filepath.read_text(encoding="utf-8")

    try:
        fm, body = split_frontmatter(raw)
    except ValueError as e:
        print(f"Error parsing frontmatter: {e}", file=sys.stderr)
        sys.exit(1)

    gid = str(fm.get("project_gid", "")).strip()
    if not gid:
        print("Error: frontmatter has no project_gid", file=sys.stderr)
        sys.exit(1)

    title = str(fm.get("title", filepath.stem)).strip()
    slug = slugify(title)

    manifest = load_asana_manifest()
    existing_entry = lookup_project(gid, manifest)

    # Fast path: if the raw file is byte-identical to the last ingestion,
    # there is nothing to regenerate.  Print the existing wiki page path
    # (the caller still records it in the main manifest) and exit cleanly.
    cached = get_cached_content(gid)
    if cached is not None and cached == raw and existing_entry:
        print(f"unchanged: {existing_entry['wiki_page']}")
        sys.exit(0)

    # Determine target page.  Prefer the existing manifest mapping so that
    # a renamed Asana project keeps the same topic-page filename — changing
    # it would break every relative link in the wiki that points to it.
    if existing_entry and existing_entry.get("wiki_page"):
        topic_page = WIKI_ROOT / existing_entry["wiki_page"]
    else:
        topic_page = TOPICS_DIR / f"{slug}.md"

    auto_block = render_auto_block(fm, body)

    if topic_page.exists():
        new_text = refresh_existing_page(
            topic_page.read_text(encoding="utf-8"),
            auto_block,
        )
    else:
        new_text = render_new_page(fm, auto_block)

    topic_page.parent.mkdir(parents=True, exist_ok=True)
    topic_page.write_text(new_text, encoding="utf-8")

    # Update cache and manifest.
    write_cache(gid, raw)
    manifest = mark_project_ingested(
        project_gid=gid,
        project_name=title,
        slug=slug,
        wiki_page=topic_page,
        raw_content=raw,
        raw_filename=filepath.name,
        manifest=manifest,
    )
    save_asana_manifest(manifest)

    # The Asana manifest and the file-content cache are both updated before
    # we print, so if this process is interrupted after printing, the
    # manifest is still consistent with what was written to disk.
    #
    # Stdout contract: print the topic-page path (absolute) so Stage 2 can
    # call mark_processed() in the main content-hash manifest.  Any other
    # output on stdout (warnings, debug messages) would confuse the caller.
    print(topic_page)


if __name__ == "__main__":
    main()
