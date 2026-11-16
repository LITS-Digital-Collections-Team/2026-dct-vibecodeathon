# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
document_ingest.py — Shared helpers for the wiki/documents/ pipeline.

Builds the header (short summary + related-page links) that gets prepended
to every converted document, and writes the final page to wiki/documents/.
Kept separate from ingest_document.py so it can be unit-tested / reused
without pulling in the CLI argument handling.
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import DOCUMENTS_DIR, WIKI_ROOT, local_today
from scripts.slug import slugify

TODAY = local_today().isoformat()


# ---------------------------------------------------------------------------
# Title / summary helpers
# ---------------------------------------------------------------------------

def guess_title(filepath: Path, metadata: dict, body: str) -> str:
    """Prefer explicit metadata, then a leading '# ' heading, then filename."""
    if metadata.get("title"):
        return metadata["title"].strip()
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return filepath.stem.replace("_", " ").replace("-", " ").strip().title()


def _first_sentence(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    m = re.search(r"[.!?](?:\s|$)", clean)
    return (clean[: m.end()] if m else clean[:200]).strip()


# ---------------------------------------------------------------------------
# Header synthesis (one cheap LLM call; degrades gracefully offline)
# ---------------------------------------------------------------------------

def _candidate_pages(limit: int = 80) -> list[str]:
    """Existing topic/people pages the LLM can choose "related" links from."""
    from scripts.classify_ingest import build_people_index, build_topic_index

    pages = sorted(set(list(build_people_index().values()) + list(build_topic_index().values())))
    return pages[:limit]


def synthesize_header(title: str, body: str) -> dict:
    """Return {"summary": str, "related": [wiki_page_path, ...]}.

    Tries a single LLM call (cheap, offloaded from the interactive
    session); falls back to a heuristic summary with no related links if
    the `claude` CLI is unavailable or errors.
    """
    candidates = _candidate_pages()
    try:
        from scripts.llm import generate
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from llm import generate

    pages_str = "\n".join(f"  {p}" for p in candidates)
    prompt = (
        f"DOCUMENT TITLE: {title}\n\n"
        f"EXCERPT (first ~2000 characters):\n{body[:2000]}\n\n"
        f"KNOWN WIKI PAGES (partial list):\n{pages_str}\n\n"
        "Return JSON only: "
        '{"summary": "1-2 sentence summary of the document", '
        '"related": ["wiki/topics/...", ...]}\n'
        "Include a wiki page in \"related\" only if the document is clearly "
        "relevant to it. Empty list if none are clearly relevant."
    )
    try:
        raw = generate(
            "You write short, factual summaries of reference documents for a "
            "personal work wiki. Return JSON only, no commentary.",
            prompt,
        )
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip()).rstrip("`").strip()
        data = json.loads(raw)
        summary = str(data.get("summary", "")).strip()
        related = [p for p in data.get("related", []) if isinstance(p, str) and p in candidates]
        if summary:
            return {"summary": summary, "related": related}
    except Exception as exc:
        print(f"  [warn] header synthesis failed, using fallback: {exc}", file=sys.stderr)

    return {"summary": _first_sentence(body) or "(no summary available)", "related": []}


# ---------------------------------------------------------------------------
# Page writer
# ---------------------------------------------------------------------------

def _related_line(related: list[str]) -> str:
    if not related:
        return "**Related:** _None identified._"
    links = []
    for page in related:
        rel_path = Path(page)
        try:
            wiki_idx = rel_path.parts.index("wiki")
            rel = "../" + "/".join(rel_path.parts[wiki_idx + 1:])
        except ValueError:
            rel = str(rel_path)
        links.append(f"[{rel_path.stem}]({rel})")
    return "**Related:** " + ", ".join(links)


def write_document_page(
    source_filepath: Path,
    body: str,
    metadata: dict,
    header: dict,
    source_type: str,
) -> Path:
    """Assemble frontmatter + header + body and write to wiki/documents/.

    Returns the absolute path of the written page. If the slug collides
    with an existing (different) document, a numeric suffix is appended.
    """
    title = guess_title(source_filepath, metadata, body)
    slug = slugify(title) or slugify(source_filepath.stem)

    # A pre-converted source (--already-markdown) may carry its own leading
    # YAML frontmatter block; drop it so it isn't duplicated inside the page
    # (our own frontmatter above already covers title/date/source metadata).
    fm_match = re.match(r"^---\s*\n.*?\n---\s*\n", body, re.DOTALL)
    if fm_match:
        body = body[fm_match.end():].lstrip("\n")

    # The header below already renders `title` as the page's H1; strip a
    # leading H1 from the body so it isn't duplicated immediately after.
    body_lines = body.split("\n", 1)
    if body_lines and re.match(r"^#\s+", body_lines[0]):
        body = body_lines[1] if len(body_lines) > 1 else ""
        body = body.lstrip("\n")

    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCUMENTS_DIR / f"{slug}.md"
    n = 2
    while out_path.exists():
        out_path = DOCUMENTS_DIR / f"{slug}-{n}.md"
        n += 1

    frontmatter_lines = [
        "---",
        f'title: "{title}"',
        f"source_file: {source_filepath.name}",
        f"source_type: {source_type}",
        f"ingested: {TODAY}",
        "tags:",
        "  - document",
        "---",
        "",
        f"# {title}",
        "",
        f"**Summary:** {header['summary']}",
        "",
        _related_line(header["related"]),
        "",
        "---",
        "",
        "",
    ]

    out_path.write_text("\n".join(frontmatter_lines) + body.strip() + "\n", encoding="utf-8")
    return out_path
