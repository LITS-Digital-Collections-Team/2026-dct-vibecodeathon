#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.
#
# setup.sh — One-time initialization for Mnemotron Wiki.
#
# Run it from anywhere; it works on the folder that contains this file:
#
#     bash setup.sh
#
# What it does:
#   1. Creates raw_ingest/ (the drop zone) with its failed/, gmail/,
#      calendar/, asana/ and claude-briefings/ subfolders
#   2. Creates the wiki/ folders: topics, people, organizations, documents,
#      daily, email
#   3. Initializes a git repository if there is none
#   4. Installs the Python dependencies (pip install -r scripts/requirements.txt)
#   5. Checks for Tesseract and poppler (warns only)
#   6. Checks which Claude backend is usable and prints guidance
#
# It never reads, writes, or asks for credentials.
#
# Environment:
#   PYTHON=python3        interpreter to use (default: python3)
#   SKIP_PIP=1            skip the pip install step

set -euo pipefail
WIKI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WIKI_ROOT"
PYTHON="${PYTHON:-python3}"

echo "=== Mnemotron Wiki — Setup ==="
echo "Wiki root: $WIKI_ROOT"
echo

# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------

echo "Creating directories..."
mkdir -p raw_ingest/failed raw_ingest/gmail raw_ingest/calendar raw_ingest/asana raw_ingest/claude-briefings
mkdir -p wiki/topics wiki/people wiki/organizations wiki/documents wiki/daily wiki/email
echo "  OK  (drop files into raw_ingest/; failures are quarantined in raw_ingest/failed/)"

# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

echo
if [ ! -d ".git" ]; then
  if command -v git &>/dev/null; then
    echo "Initializing git repository..."
    git init
    echo "  OK"
  else
    echo "git not found — skipping repository init (install git to version the wiki)."
  fi
else
  echo "Git repository already exists — skipping init."
fi

# ---------------------------------------------------------------------------
# Python dependencies
# ---------------------------------------------------------------------------

echo
if ! command -v "$PYTHON" &>/dev/null; then
  echo "ERROR: $PYTHON not found. Install Python 3.9+ or set PYTHON=/path/to/python." >&2
  exit 1
fi
if [ "${SKIP_PIP:-0}" = "1" ]; then
  echo "SKIP_PIP=1 — skipping Python dependency install."
else
  echo "Installing Python dependencies..."
  "$PYTHON" -m pip install -r scripts/requirements.txt
  echo "  OK"
fi

# ---------------------------------------------------------------------------
# System dependency checks (warn only — do not fail)
# ---------------------------------------------------------------------------

echo
echo "Checking system dependencies (optional, needed for scans/images)..."

if command -v tesseract &>/dev/null; then
  echo "  tesseract: $(tesseract --version 2>&1 | head -1)  [ok]"
else
  echo "  tesseract: NOT FOUND"
  echo "    -> macOS: brew install tesseract   Debian/Ubuntu: sudo apt install tesseract-ocr"
  echo "    -> Without Tesseract, OCR falls back to Claude vision for every page."
fi

if command -v pdftoppm &>/dev/null; then
  echo "  poppler (pdftoppm): found  [ok]"
else
  echo "  poppler: NOT FOUND"
  echo "    -> macOS: brew install poppler   Debian/Ubuntu: sudo apt install poppler-utils"
  echo "    -> Without poppler, scanned PDFs cannot be rasterized for OCR."
fi

# ---------------------------------------------------------------------------
# Claude backend check (no credentials are read or written)
# ---------------------------------------------------------------------------

echo
echo "Checking Claude backends used by the helper scripts (scripts/llm.py)..."
HAVE_CLI=0
HAVE_KEY=0
if command -v claude &>/dev/null; then
  HAVE_CLI=1
  echo "  claude CLI: found on PATH  [ok]"
else
  echo "  claude CLI: not found"
fi
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  HAVE_KEY=1
  echo "  ANTHROPIC_API_KEY: set in this shell  [ok]"
else
  echo "  ANTHROPIC_API_KEY: not set"
fi

if [ "$HAVE_CLI" = "1" ]; then
  echo "  -> Default backend: the headless Claude Code CLI (MNEMOTRON_BACKEND=cli)."
  echo "     It uses whatever login the CLI already has; no API key needed."
elif [ "$HAVE_KEY" = "1" ]; then
  echo "  -> Default backend: the Anthropic API (MNEMOTRON_BACKEND=api)."
  echo "     Requires the optional SDK:  $PYTHON -m pip install anthropic"
else
  echo "  -> No LLM backend is available yet. Pick one:"
  echo "       a) Install Claude Code (https://claude.com/claude-code) and sign in, or"
  echo "       b) export ANTHROPIC_API_KEY in your shell and run:"
  echo "            $PYTHON -m pip install anthropic"
  echo "            export MNEMOTRON_BACKEND=api"
  echo "     Scripts that do not call an LLM (check_ingest, build_index without"
  echo "     --use-api, wiki_export, ...) work either way."
fi

# ---------------------------------------------------------------------------
# Claude project permissions (lets background agents edit wiki files)
# ---------------------------------------------------------------------------

if [ ! -f ".claude/settings.json" ]; then
  mkdir -p .claude
  cat > .claude/settings.json <<'EOF'
{
  "permissions": {
    "allow": [
      "Edit",
      "Write",
      "Bash(grep*)",
      "Bash(find*)",
      "Bash(git add*)",
      "Bash(git commit*)",
      "Bash(git status*)",
      "Bash(git log*)",
      "Bash(wc*)",
      "Bash(ls*)",
      "Bash(python scripts/*)",
      "Bash(python3 scripts/*)"
    ]
  }
}
EOF
  echo
  echo "Created .claude/settings.json  (lets Claude agents edit wiki files and run the helper scripts)"
  echo "  Review it before use; delete it if you prefer to approve each action."
fi

# ---------------------------------------------------------------------------
# Initialize manifest
# ---------------------------------------------------------------------------

if [ ! -f ".manifest.json" ]; then
  echo "{}" > .manifest.json
  echo
  echo "Created empty .manifest.json"
fi

# ---------------------------------------------------------------------------
# Starter index
# ---------------------------------------------------------------------------

if [ ! -f "wiki/INDEX.md" ]; then
  DATE=$(date +%Y-%m-%d)
  cat > wiki/INDEX.md <<EOF
---
updated: $DATE
---

# Wiki Index

*Index will be populated automatically by the ingest task.*
EOF
  echo "Created wiki/INDEX.md"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo
echo "=== Setup complete ==="
echo
echo "Next steps:"
echo "  1. Drop documents into raw_ingest/"
echo "  2. See which files are waiting:   $PYTHON scripts/check_ingest.py"
echo "  3. Tell Claude to run the ingest task:"
echo "       WIKI_UPDATE_TASK.md  (optional connector tasks: GMAIL_INGEST_TASK.md,"
echo "       CALENDAR_INGEST_TASK.md, EMAIL_ARCHIVE_TASK.md; see ASANA_AND_BRIEFINGS.md)"
echo "  4. Diagnose Claude access:         $PYTHON scripts/check_auth.py   (see AUTHENTICATION.md)"
echo "  5. Optional personal settings (time zone, owner name, ...):"
echo "       see the header of scripts/config.py (config.local.json or MNEMOTRON_* variables)."
echo "  6. To export the wiki to static HTML:"
echo "       $PYTHON wiki_export.py     (output: wiki-export/index.html)"
echo
