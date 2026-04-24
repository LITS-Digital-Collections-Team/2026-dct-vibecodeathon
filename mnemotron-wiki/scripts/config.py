# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Developed with assistance from Claude (Anthropic).
# Reviewed and tested; verify behavior in your own environment.

"""
config.py — Central configuration for Mnemotron Wiki.

Edit this file if you move the project or want to change directory names.
All other scripts import from here, so this is the only place you need to
make path changes.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Core paths
# ---------------------------------------------------------------------------

# Root of the wiki repository (the folder containing this scripts/ directory).
# Derived from this file's location so it works on any machine without editing.
WIKI_ROOT = Path(__file__).resolve().parent.parent

# Drop documents here for Claude to ingest. Successfully processed files are
# deleted after each run; files that cannot be extracted are moved to
# raw_ingest/failed/ and skipped on future runs.
RAW_INGEST_DIR = WIKI_ROOT / "raw_ingest"

# Files that failed extraction are quarantined here and never retried
# automatically. Inspect them manually to diagnose the problem.
FAILED_INGEST_DIR = RAW_INGEST_DIR / "failed"

# Claude writes all wiki content here.
WIKI_DIR = WIKI_ROOT / "wiki"

# Dated entries synthesized from briefings and Asana summaries.
DAILY_DIR = WIKI_DIR / "daily"

# Synthesized reference pages, one per topic or project.
TOPICS_DIR = WIKI_DIR / "topics"

# One page per person (colleagues, collaborators, external contacts).
PEOPLE_DIR = WIKI_DIR / "people"

# One page per organization, team, department, or workgroup.
ORGS_DIR = WIKI_DIR / "organizations"

# JSON file tracking which ingest documents have already been processed.
MANIFEST_FILE = WIKI_ROOT / ".manifest.json"

# Where morning briefings (from the Claude automated briefing tool) are dropped.
BRIEFINGS_DIR = RAW_INGEST_DIR / "claude-briefings"

# ---------------------------------------------------------------------------
# Ingest settings
# ---------------------------------------------------------------------------

# File extensions Claude will attempt to process from raw_ingest/.
# Add or remove extensions as needed.
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".md",
    ".txt",
    ".csv",
    ".html",
    ".htm",
    ".docx",
    ".odt",
    ".eml",
}

# ---------------------------------------------------------------------------
# Git settings
# ---------------------------------------------------------------------------

# Commit message template; {date} is filled in automatically.
GIT_COMMIT_TEMPLATE = "wiki update {date}"
