<!--
SPDX-License-Identifier: GFDL-1.3-or-later
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS

Permission is granted to copy, distribute and/or modify this document
under the terms of the GNU Free Documentation License, Version 1.3 or
any later version published by the Free Software Foundation; with no
Invariant Sections, no Front-Cover Texts, and no Back-Cover Texts.
Full license text: https://www.gnu.org/licenses/fdl.html
-->

# Mnemotron Wiki for Research

A Claude-powered knowledge base for managing a research corpus. Drop source
documents into `ingest/` and Claude processes them into a structured,
cross-referenced markdown wiki — extracting text from native PDFs and web
pages, and transcribing scanned documents through an offline-first OCR
pipeline. All source content is retained in markdown; raw scan files and
PDFs are discarded after ingest.

---

## Contents

1. [Overview](#1-overview)
2. [System requirements](#2-system-requirements)
3. [Installation](#3-installation)
4. [Day-to-day workflow](#4-day-to-day-workflow)
5. [Supported formats](#5-supported-formats)
6. [OCR pipeline](#6-ocr-pipeline)
7. [Wiki structure](#7-wiki-structure)
8. [Configuration reference](#8-configuration-reference)
9. [Script reference](#9-script-reference)
10. [Troubleshooting](#10-troubleshooting)
11. [License](#11-license)

---

## 1. Overview

Mnemotron Wiki for Research turns a pile of heterogeneous research documents
into a navigable, cross-referenced knowledge base. The central design
principles are:

**Offline-first OCR.** Tesseract runs locally for printed text. Claude Vision
is used only when Tesseract's output fails a quality check on a given page, or
when the content is handwritten. A lightweight thumbnail pre-flight avoids
wasting time running full-resolution Tesseract on documents it cannot read.

**Retain in markdown, discard originals.** After ingest, each document's
content is preserved as a markdown page in `wiki/sources/`. Raw scan images,
PDFs, and other originals are deleted. The `wiki/` folder is the canonical
archive.

**Synthesis over filing.** Claude does not merely file documents — it reads
each source and updates or creates thematic pages in `wiki/topics/` that
synthesize findings across multiple sources, with inline citations back to the
source pages.

**Idempotent manifest.** A content-hash manifest (`.manifest.json`) ensures no
file is ever processed twice, even if renamed or moved within `ingest/`.

---

## 2. System requirements

| Requirement | Minimum version | Purpose |
|-------------|----------------|---------|
| Python | 3.9 | Everything |
| Git | Any recent | Version control for the wiki |
| Tesseract | 4.0 | Offline print OCR |
| poppler (`pdftoppm`) | Any recent | PDF-to-image rasterization for scanned PDFs |
| `ANTHROPIC_API_KEY` | — | Claude Vision OCR fallback; handwriting transcription |

**macOS installation (Homebrew):**

```bash
brew install tesseract poppler
```

**Linux (Debian/Ubuntu):**

```bash
sudo apt install tesseract-ocr poppler-utils
```

Tesseract and poppler are optional in the sense that the tool will still run
without them — but scanned PDFs and image files will immediately fall back to
Claude Vision for every page, which costs API tokens. See
[Troubleshooting](#10-troubleshooting) for advice on verifying your
installation.

---

## 3. Installation

```bash
# Clone or copy the mnemotron-wiki-r directory, then:
cd mnemotron-wiki-r
bash setup.sh
```

`setup.sh` will:

1. Create the `ingest/`, `ingest/failed/`, and `wiki/` subdirectories if
   absent.
2. Run `git init` if the directory is not already a git repository.
3. Install all Python packages from `scripts/requirements.txt`.
4. Check for Tesseract and poppler and print a warning for each that is
   missing.
5. Create an empty `.manifest.json` if one does not exist.

After setup, set your Anthropic API key in your shell environment (add to
`~/.zprofile` or `~/.bash_profile` to make it persistent):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## 4. Day-to-day workflow

### 4.1 Dropping files into `ingest/`

Copy or move source documents into the `ingest/` folder. Any supported file
format is accepted (see [Section 5](#5-supported-formats)). Subdirectories
within `ingest/` are scanned recursively, so you can organize incoming
material into subfolders if convenient.

**Naming conventions for OCR hints:**

The OCR pipeline defaults to treating image files as printed text and will try
Tesseract first. To tell the pipeline a file contains handwriting, add one of
these suffixes before the file extension:

| Suffix | Meaning |
|--------|---------|
| `-hw` | Handwritten — skip Tesseract, use Claude Vision directly |
| `-handwritten` | Same |
| `-written` | Same |

Examples:

```
ingest/field-notes-2026-03-15-hw.tiff   ← handwritten
ingest/census-page-1870.tif             ← print (Tesseract first)
ingest/interview-transcript.pdf         ← native PDF or scanned print
```

### 4.2 Running the ingest task

Open a Claude Code session in the `mnemotron-wiki-r` directory and say any of:

- `run the research wiki ingest task`
- `ingest new documents`
- `process the ingest folder`

Claude reads `RESEARCH_WIKI_TASK.md`, which contains the full pipeline
instructions. It will:

1. Find all unprocessed files in `ingest/`.
2. Extract text or OCR each file.
3. Write a `wiki/sources/` page for each document.
4. Create or update `wiki/topics/` pages synthesizing the content.
5. Create or update `wiki/entities/` pages for key people, organizations, and
   places.
6. Regenerate `wiki/INDEX.md`.
7. Commit all changes to git.

### 4.3 Checking what is queued

At any time, check which files are waiting to be processed:

```bash
python scripts/check_ingest.py           # list unprocessed files
python scripts/check_ingest.py --summary # counts only
python scripts/check_ingest.py --all     # include already-processed files
```

### 4.4 Reviewing the manifest

To see a log of every file that has been processed:

```bash
python scripts/manifest.py
```

Output columns: original filename, UTC timestamp of processing, wiki source
page created.

### 4.5 Handling failed files

Files that cannot be processed (extraction error, OCR failure) are moved to
`ingest/failed/` and are never automatically retried. Inspect them to
understand what went wrong (poor scan quality, corrupted file, unsupported
content type), then either fix the file and move it back to `ingest/`, or
discard it.

---

## 5. Supported formats

### Native text formats (text extraction, no OCR)

| Extension | Library | Notes |
|-----------|---------|-------|
| `.pdf` | pdfminer.six | If the text layer has fewer than ~100 characters, the file is automatically re-routed to the OCR pipeline |
| `.html`, `.htm` | BeautifulSoup + lxml | Script, style, and navigation elements are stripped |
| `.txt`, `.md` | Direct read | UTF-8, with replacement for undecodable bytes |
| `.csv` | stdlib csv | Rendered as pipe-separated plain text for readability |
| `.docx`, `.odt` | python-docx | Paragraph text extracted; core properties (title, author) captured as metadata |

### Image and scanned formats (OCR pipeline)

| Extension | Notes |
|-----------|-------|
| `.tif`, `.tiff` | Multi-page TIFFs are split into per-page JPEGs automatically |
| `.jpg`, `.jpeg` | Passed directly to OCR |
| `.png` | Converted to JPEG before OCR |

---

## 6. OCR pipeline

### 6.1 Decision tree

```
Input image or scanned PDF
        │
        ├─ hint == "handwritten"? ──yes──► Claude Vision (all pages)
        │
        └─ hint == "print" / "auto"
                │
                ▼
        [Pre-flight] Run Tesseract on 25%-scale thumbnail of page 1
                │
        Quality OK? ──no──► skip Tesseract; Claude Vision (all pages)
                │
               yes
                │
                ▼
        For each page at full resolution:
                │
                ├─ Tesseract → quality OK? ──yes──► keep Tesseract text
                │
                └─ quality poor ──────────────────► Claude Vision (this page only)
                │
                ▼
        Combine pages; report method ("tesseract" | "claude" | "tesseract+claude")
```

### 6.2 Quality checks

Each Tesseract result is evaluated against three independent criteria. All
three must pass for the result to be considered acceptable:

| Check | Threshold | What it catches |
|-------|-----------|-----------------|
| Word count | ≥ 15 words | Blank or near-blank output |
| Alpha ratio | ≥ 45% of non-whitespace chars are alphabetic | Symbol noise, severe garbling |
| Mean word length | ≥ 2.0 characters/word | Single-character noise streams |

Thresholds are configurable in `scripts/config.py` (see
[Section 8](#8-configuration-reference)).

### 6.3 Pre-flight thumbnail

Before running Tesseract at full resolution, a 25%-scale thumbnail of the
first page is created and tested. This takes under 200 ms and avoids running
a slow full-resolution Tesseract pass on every page of a document that is
clearly not readable by Tesseract (e.g., a photograph, a very poor scan, or
a document Tesseract's language models cannot handle).

If the thumbnail fails, Claude Vision is used for all pages without any
Tesseract attempt.

### 6.4 Per-page fallback

Tesseract is run on each page individually. Pages that pass quality checks
keep their Tesseract transcription. Pages that fail fall back to Claude Vision
for that page only. This avoids the waste of re-processing an entire
multi-page document through Claude because a single page happened to be
difficult for Tesseract.

### 6.5 Post-OCR repair

When the OCR method includes Tesseract, `RESEARCH_WIKI_TASK.md` instructs
Claude to review the raw output before writing the source page and repair:

- Common character substitutions (0/O, 1/l/I, rn/m, ligature encoding)
- Hyphenated line-break artifacts ("doc-\nument" → "document")
- Noise-only lines (isolated punctuation, short repeated header/footer text)
- Redundant whitespace
- Ligature encoding artifacts (ﬁ→fi, ﬂ→fl, ﬀ→ff, etc.)

Uncertain readings are marked `[?word?]`; illegible passages are marked
`[illegible]`; tables and formulas that OCR cannot reproduce are flagged with
a bracketed note rather than a reconstruction attempt.

---

## 7. Wiki structure

```
wiki/
├── INDEX.md        ← auto-maintained index of all wiki content
├── sources/        ← one page per ingested document
├── topics/         ← thematic synthesis pages
└── entities/       ← people, organizations, places
```

### 7.1 Source pages (`wiki/sources/`)

One page per ingested document. Contains:

- YAML frontmatter: title, type, OCR method, ingest date, original filename,
  tags.
- **Source Information** — provenance, authorship, approximate date.
- **Content** — full extracted or transcribed text, lightly formatted as
  markdown.
- **Notes** — OCR quality assessment and manual-review flag (Tesseract output
  only).

Source pages are **transcriptions**, not interpretations. They are faithful to
the source material; analysis belongs in topic pages.

### 7.2 Topic pages (`wiki/topics/`)

One page per research topic or concept. Contains:

- YAML frontmatter: updated date, tags.
- **Overview** — 2–4 sentences.
- **Key Points** — prose synthesis with inline citations to source pages.
- **Open Questions** — unresolved gaps; updated as sources accumulate.
- **Sources** table — links to contributing source pages with notes on each
  source's contribution.
- **Related Topics** — links to other topic pages.

### 7.3 Entity pages (`wiki/entities/`)

One page per named person, organization, or place that figures substantively
in the research. Contains:

- YAML frontmatter: name, entity_type, updated date.
- **Overview**, **Relevance to Research**, **Notes**.
- **Related Sources** and **Related Topics** link lists.

### 7.4 Index (`wiki/INDEX.md`)

Auto-regenerated at the end of each ingest run. Lists all sources (with type
and ingest date), all topics (with one-sentence summaries), all entities (with
type), and an ingested-documents log from `.manifest.json`.

---

## 8. Configuration reference

All settings live in `scripts/config.py`. Edit that file to change paths or
tune OCR behavior; all other scripts import from it.

### Paths

| Variable | Default | Description |
|----------|---------|-------------|
| `WIKI_ROOT` | *(derived)* | Absolute path to the wiki root; derived from `config.py`'s location so it works on any machine |
| `INGEST_DIR` | `ingest/` | Drop zone for new documents |
| `FAILED_INGEST_DIR` | `ingest/failed/` | Quarantine for files that fail processing |
| `WIKI_DIR` | `wiki/` | All wiki content |
| `SOURCES_DIR` | `wiki/sources/` | Retained source transcriptions |
| `TOPICS_DIR` | `wiki/topics/` | Synthesized topic pages |
| `ENTITIES_DIR` | `wiki/entities/` | Entity pages |
| `MANIFEST_FILE` | `.manifest.json` | Content-hash manifest |

### Ingest settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TEXT_EXTENSIONS` | `{.pdf, .md, .txt, ...}` | Extensions routed to text extraction |
| `IMAGE_EXTENSIONS` | `{.tif, .tiff, .jpg, .jpeg, .png}` | Extensions routed to OCR |
| `SUPPORTED_EXTENSIONS` | Union of above | All extensions `check_ingest.py` will list |

### OCR settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TESSERACT_MIN_WORDS` | `15` | Minimum word count for a Tesseract result to pass quality check. Raise to be stricter. |
| `TESSERACT_MIN_ALPHA_RATIO` | `0.45` | Minimum fraction of non-whitespace chars that must be alphabetic. Raise for cleaner scans. |
| `PDF_OCR_DPI` | `300` | DPI for rasterizing PDF pages. 300 is standard; raise to 400–600 for very fine print. |
| `JPEG_QUALITY` | `92` | JPEG compression quality for converted images (1–95). |
| `OCR_CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model used for Vision OCR fallback and handwriting. |

---

## 9. Script reference

All scripts can be run from the wiki root. They accept a `--help` flag.

### `scripts/config.py`

Not a runnable script. Central configuration hub imported by all other
scripts. Edit this file to change any path or OCR setting.

### `scripts/manifest.py`

Tracks processed files using content hashes (MD5) so a renamed but unchanged
file is not reprocessed.

```bash
python scripts/manifest.py        # print all processed files
```

**Key functions (for import):**

| Function | Description |
|----------|-------------|
| `load_manifest()` | Load `.manifest.json`; return `{}` if absent |
| `save_manifest(manifest)` | Write manifest to disk |
| `is_processed(filepath, manifest)` | Check whether a file's hash is in the manifest |
| `mark_processed(filepath, wiki_page, manifest)` | Record a file as processed (in-memory; call `save_manifest` afterwards) |
| `file_hash(filepath)` | Return MD5 hex digest of file contents |

### `scripts/check_ingest.py`

Lists files in `ingest/` that have not yet been processed.

```bash
python scripts/check_ingest.py            # unprocessed files only
python scripts/check_ingest.py --all      # all supported files
python scripts/check_ingest.py --summary  # counts only
```

**Import:**

```python
from scripts.check_ingest import get_ingest_files
files = get_ingest_files()              # unprocessed only
files = get_ingest_files(include_processed=True)
```

### `scripts/extract_text.py`

Extracts plain text from native (non-scanned) document formats. Never raises;
errors are returned in `result["error"]`. Scanned PDFs are detected
automatically (exit code 2 on CLI, `is_scan=True` on import).

```bash
python scripts/extract_text.py path/to/document.pdf
# text → stdout, metadata → stderr, exit 2 if scanned PDF
```

**Import:**

```python
from scripts.extract_text import extract_text
result = extract_text(Path("paper.pdf"))
# result["text"], result["metadata"], result["is_scan"], result["error"]
```

### `scripts/ocr.py`

Runs the OCR pipeline (Tesseract → Claude Vision fallback) on image files and
scanned PDFs.

```bash
python scripts/ocr.py path/to/scan.tiff
python scripts/ocr.py path/to/scan.tiff --hint handwritten
python scripts/ocr.py path/to/scanned.pdf --hint print
# text → stdout, progress → stderr
```

**Import:**

```python
from scripts.ocr import ocr_file
result = ocr_file(Path("scan.tiff"), hint="auto")
# result["text"], result["method"], result["pages"], result["error"]
# result["pages"]: [{"page": 1, "method": "tesseract"}, ...]
```

`hint` values:

| Value | Behavior |
|-------|----------|
| `"auto"` *(default)* | Same as `"print"` |
| `"print"` | Thumbnail pre-flight, then per-page Tesseract with Claude fallback |
| `"handwritten"` | Skip Tesseract; Claude Vision for all pages |

---

## 10. Troubleshooting

### `tesseract: command not found`

Tesseract is not installed or not on `PATH`. Install it:

```bash
brew install tesseract          # macOS
sudo apt install tesseract-ocr  # Debian/Ubuntu
```

Without Tesseract, all OCR falls back to Claude Vision. This works but uses
API tokens for every page of every scan.

### `pdftoppm: command not found` / `pdf2image` errors

poppler is not installed. Install it:

```bash
brew install poppler          # macOS
sudo apt install poppler-utils # Debian/Ubuntu
```

Without poppler, `pdf2image` cannot rasterize PDFs and all scanned PDF
processing will fail at the image-preparation step.

### `ANTHROPIC_API_KEY is not set`

Set the environment variable before running Claude:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

For a permanent setting, add the export to `~/.zprofile` (macOS/zsh) or
`~/.bashrc` (Linux/bash).

This key is required for:
- Handwritten document transcription (all pages)
- Print OCR pages where Tesseract quality is too low
- Any page in a document where the Tesseract pre-flight fails

### OCR output is mostly garbage

If Tesseract is producing mostly noise, try raising the quality thresholds in
`config.py` so more pages fall back to Claude:

```python
TESSERACT_MIN_WORDS = 25          # was 15
TESSERACT_MIN_ALPHA_RATIO = 0.55  # was 0.45
```

Alternatively, use `--hint print` and raise `PDF_OCR_DPI = 400` for very fine
print (increases processing time and file sizes).

### A file keeps appearing in `check_ingest.py` output after processing

The manifest tracks content by MD5 hash. If the file has been modified since
it was processed, its hash will differ and it will appear unprocessed. This is
intentional — a changed file is treated as new content.

If you want to suppress a file without reprocessing it, move it to
`ingest/failed/` (it will be excluded from future scans) or delete it.

### The ingest task created a source page but the content looks wrong

Source pages are meant to be faithful transcriptions. If the content is
garbled from OCR:

1. Check `ocr_method` in the page frontmatter.
2. If `tesseract`, try running `python scripts/ocr.py <original_file>` manually
   and inspect the raw output.
3. If quality is poor, increase thresholds (see above) or add `--hint
   handwritten` if the scan is difficult print.
4. Delete the bad source page, move the original file back to `ingest/`, and
   re-run the ingest task.

---

## 11. License

**Code** (`scripts/*.py`, `setup.sh`):  
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS.  
Licensed under the GNU General Public License, version 3 or any later version.  
Full text: <https://www.gnu.org/licenses/gpl-3.0.html>

**This document and other documentation files**:  
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS.  
Licensed under the GNU Free Documentation License, version 1.3 or any later
version, with no Invariant Sections, no Front-Cover Texts, and no Back-Cover
Texts.  
Full text: <https://www.gnu.org/licenses/fdl.html>

**Claude instruction documents** (`RESEARCH_WIKI_TASK.md` and similar):  
Dedicated to the public domain under CC0 1.0 Universal.  
Full text: <https://creativecommons.org/publicdomain/zero/1.0/>

**Wiki content** (`wiki/`):  
Copyright belongs to the wiki's author(s). The default license for wiki
content created by users of this tool is not set by this project; apply
whichever license is appropriate to your research context.
