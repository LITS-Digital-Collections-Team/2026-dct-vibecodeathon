# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
slug.py — Shared slugify helper.

Split out from classify_ingest.py / document_ingest.py so neither module
needs to import the other just to build a filename slug.
"""

import re


def slugify(text: str) -> str:
    """Lowercase, hyphenate, and strip punctuation from *text*.

    "The McDonaldization of Academic Libraries!" -> "the-mcdonaldization-of-academic-libraries"
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "untitled"
