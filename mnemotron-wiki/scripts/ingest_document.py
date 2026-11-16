# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
ingest_document.py — End-to-end ingest for one PDF/DOC/DOCX/HTML source file
(or a legacy pre-converted Markdown file lacking a header).

Converts the source to structured Markdown, synthesises a short header
(summary + related wiki links), writes it to wiki/documents/, records the
source in the manifest, and deletes the original from raw_ingest/ — all in
one script call so the interactive session never needs to read the full
document into context.

Usage (from the wiki root):
    python scripts/ingest_document.py raw_ingest/report.pdf
    python scripts/ingest_document.py raw_ingest/old-article.md --already-markdown

Exit codes:
    0  Success — prints the absolute wiki page path to stdout.
    1  Failure — error message to stderr; source file left in place.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import DOCUMENT_CONVERSION_EXTENSIONS, WIKI_ROOT
from scripts.document_ingest import guess_title, synthesize_header, write_document_page
from scripts.manifest import load_manifest, mark_processed, save_manifest


def ingest_document(filepath: Path, already_markdown: bool = False) -> Path:
    """Run the full pipeline for *filepath*. Raises on any failure."""
    ext = filepath.suffix.lower()

    if already_markdown or ext == ".md":
        body = filepath.read_text(encoding="utf-8", errors="replace").strip()
        metadata: dict = {}
        source_type = "md"
    else:
        if ext not in DOCUMENT_CONVERSION_EXTENSIONS:
            raise ValueError(
                f"Unsupported extension for document conversion: {ext} "
                f"(expected one of {sorted(DOCUMENT_CONVERSION_EXTENSIONS)}, "
                "or pass --already-markdown for a pre-converted .md file)"
            )
        from scripts.convert_document import convert_to_markdown
        result = convert_to_markdown(filepath)
        if result["error"]:
            raise RuntimeError(result["error"])
        body, metadata, source_type = result["text"], result["metadata"], result["type"]

    if not body.strip():
        raise RuntimeError("Conversion produced no text content.")

    title = guess_title(filepath, metadata, body)
    header = synthesize_header(title, body)
    wiki_page = write_document_page(filepath, body, metadata, header, source_type)

    manifest = load_manifest()
    manifest = mark_processed(filepath, wiki_page, manifest)
    save_manifest(manifest)

    filepath.unlink()
    return wiki_page


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert a PDF/DOC/DOCX/HTML (or pre-converted Markdown) "
                     "ingest file into a wiki/documents/ page."
    )
    parser.add_argument("filepath", type=Path)
    parser.add_argument(
        "--already-markdown", action="store_true",
        help="Treat the source as already-converted Markdown; skip conversion "
             "and only add the header. For backfilling legacy files.",
    )
    args = parser.parse_args()

    target = args.filepath
    if not target.is_absolute():
        target = WIKI_ROOT / target
    if not target.exists():
        print(f"Error: file not found: {target}", file=sys.stderr)
        sys.exit(1)

    try:
        page = ingest_document(target, already_markdown=args.already_markdown)
    except Exception as exc:
        print(f"Ingest error: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(page)
