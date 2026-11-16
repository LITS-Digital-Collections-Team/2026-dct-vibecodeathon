# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
config.py — Central configuration for Mnemotron Wiki.

Every other script imports its paths and settings from here.  Nothing here
needs editing for a normal install: paths are derived from this file's own
location, and personal settings come from environment variables or an
optional ``config.local.json`` (see below) so the repository stays generic.

Quick reference
---------------
Paths:        WIKI_ROOT, RAW_INGEST_DIR (INGEST_DIR is an alias),
              FAILED_INGEST_DIR, BRIEFINGS_DIR, WIKI_DIR, TOPICS_DIR,
              PEOPLE_DIR, ORGS_DIR, DOCUMENTS_DIR, DAILY_DIR, EMAIL_DIR,
              MANIFEST_FILE, LOG_ROOT
Extensions:   TEXT_EXTENSIONS, IMAGE_EXTENSIONS, SUPPORTED_EXTENSIONS,
              DOCUMENT_CONVERSION_EXTENSIONS
OCR tuning:   TESSERACT_MIN_WORDS, TESSERACT_MIN_ALPHA_RATIO,
              PDF_OCR_DPI, JPEG_QUALITY, PDF_MIN_WORDS_PER_PAGE
Personal:     TIMEZONE, OWNER_NAME, OWNER_ROLE, OWNER_EMAILS,
              FILENAME_STOPWORDS, INSTITUTION_DOMAINS, DIRECTORY_URL_TEMPLATES, TOPIC_KEYWORDS,
              CONTACT_EMAIL, ALWAYS_READ_TOPICS
Git:          GIT_COMMIT_TEMPLATE

Optional personal settings
--------------------------
Create ``config.local.json`` next to the scripts/ folder (it is git-ignored
by convention; never put credentials in it).  Every key is optional:

    {
      "timezone": "America/Chicago",
      "owner_name": "Jane Doe",
      "owner_role": "Head of Digital Collections at Example University",
      "owner_emails": ["jdoe@example.edu"],
      "filename_stopwords": ["jane", "jdoe", "office", "standup"],
      "institution_domains": ["example.edu"],
      "directory_url_templates": ["https://www.example.edu/people/{username}"],
      "contact_email": "jdoe@example.edu",
      "always_read_topics": ["meeting-cadence.md"],
      "topic_keywords": {"grant|funding": "Funding"},
      "log_dir": "logs"
    }

Each setting can also be given as an environment variable, which wins over
the JSON file:

    MNEMOTRON_TIMEZONE          IANA zone name (default "UTC")
    MNEMOTRON_OWNER_NAME        name of the person the wiki is about/for
    MNEMOTRON_OWNER_ROLE        one-line description used in LLM prompts
    MNEMOTRON_OWNER_EMAILS      comma-separated own e-mail addresses
    MNEMOTRON_FILENAME_STOPWORDS  comma-separated extra words ignored when
                                matching file names to wiki pages
    MNEMOTRON_INSTITUTION_DOMAINS comma-separated domains treated as "your
                                institution" when enriching people / fetching URLs
    MNEMOTRON_CONTACT_EMAIL     contact address put in the User-Agent of
                                scripts that fetch web pages (optional)
    MNEMOTRON_ALWAYS_READ_TOPICS comma-separated topic files generate_todo.py
                                always reads
    MNEMOTRON_LOG_DIR           where generate_todo.py writes its logs
"""

import json
import os
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

# Where morning-briefing / daily-summary files are dropped (optional feature).
BRIEFINGS_DIR = RAW_INGEST_DIR / "claude-briefings"

# Root of all wiki content produced by Claude.
WIKI_DIR = WIKI_ROOT / "wiki"

# One markdown page per topic or project (Claude-synthesised from many inputs).
TOPICS_DIR = WIKI_DIR / "topics"

# One page per person (colleagues, collaborators, external contacts).
PEOPLE_DIR = WIKI_DIR / "people"
# One page per organisation, team, department, or workgroup.
ORGS_DIR = WIKI_DIR / "organizations"
# Converted PDF/DOC/DOCX/HTML documents, one page per source file.
DOCUMENTS_DIR = WIKI_DIR / "documents"
# Dated entries synthesised from briefings and task-manager summaries.
DAILY_DIR = WIKI_DIR / "daily"
# Email archive pages (one per thread / digest).
EMAIL_DIR = WIKI_DIR / "email"

# JSON file that tracks every processed file by content hash (MD5).
# Commit this file to preserve ingest history across machines.
MANIFEST_FILE = WIKI_ROOT / ".manifest.json"

# ---------------------------------------------------------------------------
# Optional personal settings (config.local.json / environment variables)
# ---------------------------------------------------------------------------

def _load_local() -> dict:
    path = WIKI_ROOT / "config.local.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


_LOCAL = _load_local()


def _setting(key: str, env: str, default=""):
    """Environment variable > config.local.json > default."""
    value = os.environ.get(env)
    if value is not None and value.strip():
        return value.strip()
    return _LOCAL.get(key, default)


def _as_list(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    return [str(v).strip() for v in (value or []) if str(v).strip()]


# IANA time-zone name used when converting e-mail timestamps and dating
# generated entries.  Never hard-coded elsewhere.
TIMEZONE = str(_setting("timezone", "MNEMOTRON_TIMEZONE", "UTC"))

# Who the wiki is for.  Used only to word LLM prompts and to recognise the
# owner's own addresses; leave blank for a neutral wording.
OWNER_NAME = str(_setting("owner_name", "MNEMOTRON_OWNER_NAME", ""))
OWNER_ROLE = str(_setting("owner_role", "MNEMOTRON_OWNER_ROLE", ""))
OWNER_EMAILS = [e.lower() for e in _as_list(_setting("owner_emails", "MNEMOTRON_OWNER_EMAILS", []))]

# Words ignored when matching ingest file names against wiki page names
# (classify_ingest.py).  The owner's name parts are added automatically.
_GENERIC_STOPWORDS = {
    "transcript", "notes", "meeting", "session", "1on1", "gmt", "room",
    "zoom", "call", "recording", "summary", "personal",
}
FILENAME_STOPWORDS = (
    _GENERIC_STOPWORDS
    | {w.lower() for w in _as_list(_setting("filename_stopwords", "MNEMOTRON_FILENAME_STOPWORDS", []))}
    | {w.lower() for w in OWNER_NAME.split() if len(w) >= 3}
)

# Domains that count as "your own institution" (people enrichment, URL
# fetching rules).  Empty by default.
INSTITUTION_DOMAINS = [d.lower().lstrip("@") for d in
                       _as_list(_setting("institution_domains", "MNEMOTRON_INSTITUTION_DOMAINS", []))]

# Regex -> label pairs used by ingest_takeout.py to tag e-mail dossier updates
# with topics.  Override or extend with a "topic_keywords" object in
# config.local.json ({"regex": "Label", ...}); the local file replaces these.
_DEFAULT_TOPIC_KEYWORDS = {
    "born.digital|digitization|digitise|digital collection": "Digitization",
    "copyright|fair use|licensing": "Copyright and Licensing",
    "ocr|handwriting|transcription": "OCR / Transcription Workflows",
    "preservation|metadata|cataloging": "Digital Preservation",
    "budget|funding|grant": "Budget and Funding",
    "project management|roadmap|milestone": "Project Management",
}
_tk = _LOCAL.get("topic_keywords")
TOPIC_KEYWORDS = dict(_tk) if isinstance(_tk, dict) and _tk else _DEFAULT_TOPIC_KEYWORDS

# Optional URL templates for your institution's people-directory pages, tried
# by enrich_person.py when a person's e-mail domain is one of
# INSTITUTION_DOMAINS.  Use {username} (the part of the e-mail before "@"),
# e.g. "https://www.example.edu/people/{username}".  Empty by default.
DIRECTORY_URL_TEMPLATES = _as_list(_setting("directory_url_templates", "MNEMOTRON_DIRECTORY_URL_TEMPLATES", []))

# Optional contact address appended to the User-Agent of web-fetching scripts.
CONTACT_EMAIL = str(_setting("contact_email", "MNEMOTRON_CONTACT_EMAIL", ""))

# Where generate_todo.py writes dated to-do logs (relative paths are resolved
# against WIKI_ROOT).
LOG_ROOT = Path(str(_setting("log_dir", "MNEMOTRON_LOG_DIR", "logs")))
if not LOG_ROOT.is_absolute():
    LOG_ROOT = WIKI_ROOT / LOG_ROOT

# Topic page file names that generate_todo.py always includes as context.
ALWAYS_READ_TOPICS = _as_list(_setting("always_read_topics", "MNEMOTRON_ALWAYS_READ_TOPICS", ["meeting-cadence.md"]))


def get_timezone():
    """Return a tzinfo for TIMEZONE (falls back to UTC if unknown/unavailable)."""
    from datetime import timezone
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TIMEZONE)
    except Exception:  # unknown zone name or no tz database installed
        return timezone.utc


def local_now():
    """Current time in the configured TIMEZONE."""
    from datetime import datetime
    return datetime.now(get_timezone())


def local_today():
    """Current date in the configured TIMEZONE."""
    return local_now().date()


# ---------------------------------------------------------------------------
# Ingest settings
# ---------------------------------------------------------------------------

# File extensions routed through the standard text-extraction pipeline.
# PDFs with fewer than ~100 non-whitespace characters are automatically
# re-routed to the OCR pipeline (see extract_text.py).
TEXT_EXTENSIONS = {
    ".pdf", ".md", ".txt", ".html", ".htm", ".csv", ".docx", ".odt", ".doc",
    ".eml", ".json", ".jsonl", ".xml", ".vcf", ".ics",
}

# File extensions routed through the OCR pipeline (ocr.py).
IMAGE_EXTENSIONS = {
    ".tif", ".tiff", ".jpg", ".jpeg", ".png", ".webp", ".gif",
}

# All extensions that check_ingest.py will include in its file listing.
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS

# Extensions routed through the document-conversion pipeline
# (scripts/ingest_document.py) : they land in
# wiki/documents/ as structured Markdown with a synthesised header instead of
# being folded into a topic or people page.
DOCUMENT_CONVERSION_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".odt", ".html", ".htm",
}

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

# A pdfminer extraction averaging fewer than this many words per page is
# treated as a scanned (image-only) PDF and routed to OCR (document conversion).
PDF_MIN_WORDS_PER_PAGE = 20

# The Claude Vision model is chosen by scripts/llm.py (see MNEMOTRON_CLI_VISION_MODEL
# and MNEMOTRON_API_VISION_MODEL there), not here.

# ---------------------------------------------------------------------------
# Git settings
# ---------------------------------------------------------------------------

# Template for automated git commit messages.  {date} is replaced with the
# current date in YYYY-MM-DD format by the ingest task.
GIT_COMMIT_TEMPLATE = "wiki update {date}"
