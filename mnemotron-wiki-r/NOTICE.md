<!--
SPDX-License-Identifier: GFDL-1.3-or-later
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude Sonnet 5.5); may not have been fully reviewed by a human.
-->

# Notice — Third-Party Software and Services

> Created with assistance from Claude Code (Claude Sonnet 5.5); may not have been fully reviewed by a human.

Mnemotron Wiki (c) 2026 Patrick R. Wallace, Hamilton College LITS, is licensed
as described in `LICENSE`. It does not bundle any third-party code. It *calls*
the following, each under its own terms, which you must accept separately:

| Component | Role | Terms |
|-----------|------|-------|
| Claude Code (CLI) | Optional headless backend (`MNEMOTRON_BACKEND=cli`) | Anthropic's Commercial/Consumer Terms and Claude Code terms. Automated use must stay within your plan's terms. |
| Anthropic API + `anthropic` SDK | Optional API backend (`MNEMOTRON_BACKEND=api`) | Anthropic Commercial Terms; SDK is MIT-licensed |
| Tesseract OCR, poppler | Local OCR / PDF rasterization (optional) | Apache-2.0 / GPL-2.0-or-later (separate executables, invoked as subprocesses) |
| pdfminer.six, python-docx, beautifulsoup4, lxml, markdown, Pillow, pytesseract, pdf2image, internetarchive | Python libraries installed via pip | MIT / BSD / Apache-2.0 / AGPL-3.0 (`internetarchive`); see each package |
| Internet Archive | Optional source for `ia_ingest.py` | Respect the Archive's terms of use and item rights |

Not affiliated with or endorsed by Anthropic or the Internet Archive. "Claude" is a trademark of Anthropic.

Content you ingest may be copyrighted or private. Check the rights and privacy
obligations attached to your sources before processing them or publishing a wiki.
