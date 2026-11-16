# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
config.py — Central configuration for Mnemotron Wiki (research tool).

Every other script imports its paths and settings from here.  Nothing here
needs editing for a normal install: paths are derived from this file's own
location.

Quick reference
---------------
Paths:        WIKI_ROOT, RAW_INGEST_DIR (INGEST_DIR is a backward-compatible
              alias), FAILED_INGEST_DIR, WIKI_DIR, SOURCES_DIR, TOPICS_DIR,
              ENTITIES_DIR, MANIFEST_FILE
Extensions:   TEXT_EXTENSIONS, IMAGE_EXTENSIONS, SUPPORTED_EXTENSIONS
OCR tuning:   TESSERACT_MIN_WORDS, TESSERACT_MIN_ALPHA_RATIO,
              PDF_OCR_DPI, JPEG_QUALITY
Git:          GIT_COMMIT_TEMPLATE

Optional per-machine settings
-----------------------------
scripts/llm.py reads an optional ``config.local.json`` next to the scripts/
folder (git-ignored; never put credentials in it) for the Claude backend:

    {"llm": {"backend": "cli"}}

See AUTHENTICATION.md for every key.  Nothing else reads that file.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Core paths
# ---------------------------------------------------------------------------

# Absolute path to the wiki root — the folder that contains this scripts/
# directory.  Derived from this file's own location so it works on any
# machine without editing.
WIKI_ROOT = Path(__file__).resolve().parent.parent

# Drop zone: place new documents here for Claude to process.  Successfully
# processed files are deleted after ingest; files that fail are moved to
# FAILED_INGEST_DIR and never retried automatically.
RAW_INGEST_DIR = WIKI_ROOT / "raw_ingest"
INGEST_DIR = RAW_INGEST_DIR  # backward-compatible alias

# Quarantine: files that failed text extraction or OCR land here.  Inspect
# them manually to diagnose the problem before deciding what to do with them.
FAILED_INGEST_DIR = RAW_INGEST_DIR / "failed"

# Root of all wiki content produced by Claude.
WIKI_DIR = WIKI_ROOT / "wiki"

# One markdown page per ingested document (faithful transcription / extraction).
SOURCES_DIR = WIKI_DIR / "sources"
# One markdown page per topic (Claude-synthesised from multiple sources).
TOPICS_DIR = WIKI_DIR / "topics"
# One page per named entity (person, organisation, place) in the research material.
ENTITIES_DIR = WIKI_DIR / "entities"

# JSON file that tracks every processed file by content hash (MD5).
# Commit this file to preserve ingest history across machines.
MANIFEST_FILE = WIKI_ROOT / ".manifest.json"

# ---------------------------------------------------------------------------
# Ingest settings
# ---------------------------------------------------------------------------

# File extensions routed through the standard text-extraction pipeline.
# PDFs with fewer than ~100 non-whitespace characters are automatically
# re-routed to the OCR pipeline (see extract_text.py).
TEXT_EXTENSIONS = {
    ".pdf", ".md", ".txt", ".html", ".htm", ".csv", ".docx", ".odt", ".doc",
    ".eml", ".json", ".jsonl", ".xml",
}

# File extensions routed through the OCR pipeline (ocr.py).
IMAGE_EXTENSIONS = {
    ".tif", ".tiff", ".jpg", ".jpeg", ".png", ".webp", ".gif",
}

# All extensions that check_ingest.py will include in its file listing.
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS

# ---------------------------------------------------------------------------
# OCR settings
# ---------------------------------------------------------------------------

# Minimum number of whitespace-separated tokens a Tesseract result must
# contain to be considered usable.  Very short output usually means Tesseract
# could not find any text.
TESSERACT_MIN_WORDS = 15

# Minimum fraction of non-whitespace characters that must be alphabetic for a
# Tesseract result to be considered usable.  A low ratio (lots of punctuation,
# digits, or box-drawing characters relative to letters) suggests severe
# garbling or a non-text image.
TESSERACT_MIN_ALPHA_RATIO = 0.45

# DPI used when rasterising PDF pages for OCR.  300 is the standard for print;
# 400–600 may help with very fine text but increases processing time and memory.
PDF_OCR_DPI = 300

# JPEG quality (1–95) used when converting TIFF, PNG, or PDF pages to JPEG
# before OCR.  92 gives high quality with moderate file size.
JPEG_QUALITY = 92

# The Claude Vision model is chosen by scripts/llm.py (see MNEMOTRON_CLI_VISION_MODEL
# and MNEMOTRON_API_VISION_MODEL there), not here.

# ---------------------------------------------------------------------------
# Git settings
# ---------------------------------------------------------------------------

# Template for automated git commit messages.  {date} is replaced with the
# current date in YYYY-MM-DD format by the ingest task.
GIT_COMMIT_TEMPLATE = "wiki update {date}"
