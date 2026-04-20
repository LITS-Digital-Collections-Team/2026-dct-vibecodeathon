# claude-wiki

**AI-powered markdown knowledge base updater**

`claude-wiki` watches one or more source directories for new files and uses [Claude](https://www.anthropic.com/claude) to analyze their content, then writes targeted updates — new notes, cross-references, summaries — to a markdown wiki you own and control. Drop a document in the ingest folder, run the script, and your wiki grows.

---

## Table of Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
  - [Config file fields](#config-file-fields)
- [Usage](#usage)
  - [Initialize a new project](#initialize-a-new-project)
  - [Run an update](#run-an-update)
  - [Dry run](#dry-run)
  - [Command-line reference](#command-line-reference)
- [How It Works](#how-it-works)
  - [Architecture](#architecture)
  - [The agentic loop](#the-agentic-loop)
  - [Caching and cost](#caching-and-cost)
  - [Safety guarantees](#safety-guarantees)
- [Customization](#customization)
  - [Custom rules](#custom-rules)
  - [Multiple source directories](#multiple-source-directories)
  - [Using a smaller model](#using-a-smaller-model)
- [File type support](#file-type-support)
- [Processed-files log](#processed-files-log)
- [Examples](#examples)
  - [Research project](#example-research-project)
  - [Meeting notes](#example-meeting-notes)
  - [Multiple ingest directories](#example-multiple-ingest-directories)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Overview

Most people end up with scattered notes, inboxed PDFs, and half-processed documents that never make it into their reference system. `claude-wiki` automates the "processing" step: you drop new material into a source directory, run the script, and Claude reads your existing wiki, reads the new file, and makes targeted, conservative edits — adding cross-references, creating new notes where warranted, updating an index, or summarizing long documents into a wiki entry.

Key design principles:

- **You own the files.** Claude writes only to your designated wiki directory. Source files are never touched.
- **Conservative edits.** Claude is instructed to prefer updating existing notes over creating new ones, and to preserve your voice and phrasing.
- **Idempotent.** Already-processed files are tracked in a log. Re-running the script processes only new files.
- **Configurable.** A single JSON file controls directory structure, model choice, and project-specific writing conventions.

---

## Requirements

- Python 3.10 or later
- An [Anthropic API key](https://console.anthropic.com/) (set as `ANTHROPIC_API_KEY` in your environment)
- The `anthropic` Python package (see [Installation](#installation))
- Source files must be plain text (`.txt`, `.md`, `.csv`, `.json`, `.html`, etc.). PDFs and binary files are skipped automatically.

---

## Installation

```bash
# 1. Clone or copy this directory into your project
cp -r tools/claude-wiki /your/project/

# 2. Install the dependency (ideally in a virtual environment)
cd /your/project/claude-wiki
pip install -r requirements.txt

# 3. Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## Quick Start

```bash
# From your project directory:
python claude_wiki.py --init

# Edit the generated claude-wiki.json for your project, then:
echo "Meeting notes from Monday..." > ingest/meeting-2026-04-20.txt
python claude_wiki.py
```

That's it. Check your `wiki/` directory for new and updated notes.

---

## Configuration

`claude-wiki` is configured via a `claude-wiki.json` file in your project root. Running `--init` creates one with defaults. You can also copy `example-config.json` as a starting point.

The script searches for `claude-wiki.json` by walking up from the current directory (like `git` finding `.git`), so you can run it from any subdirectory of your project.

### Config file fields

| Field | Type | Default | Description |
|---|---|---|---|
| `wiki_dir` | string | `"wiki"` | Directory where wiki `.md` files live, relative to the config file |
| `source_dirs` | array of strings | `["ingest"]` | Directories to watch for new source files |
| `processed_log` | string or null | `"<wiki_dir>/.processed_files.json"` | Where to persist the list of already-processed files |
| `model` | string | `"claude-opus-4-7"` | Claude model to use |
| `wiki_description` | string | `"a personal markdown knowledge base"` | Short description of the wiki, included in Claude's system prompt |
| `skip_extensions` | array of strings | `[]` | Additional file extensions to skip (PDFs are always skipped) |
| `custom_rules` | array of strings | `[]` | Additional instructions injected into Claude's system prompt |
| `max_tokens` | integer | `8096` | Maximum tokens per Claude response turn |

**Example `claude-wiki.json`:**

```json
{
  "wiki_dir": "wiki",
  "source_dirs": ["ingest", "meeting-notes"],
  "model": "claude-opus-4-7",
  "wiki_description": "a research knowledge base for the Acme Digitization Project",
  "skip_extensions": ["xlsx", "docx"],
  "custom_rules": [
    "Always use ISO 8601 dates (YYYY-MM-DD) in new notes",
    "Tag each new note with a project phase: Planning, Active, or Complete"
  ],
  "max_tokens": 8096
}
```

---

## Usage

### Initialize a new project

```bash
# In your project directory:
python /path/to/claude_wiki.py --init

# Or specify a target directory:
python /path/to/claude_wiki.py --init /path/to/my-project
```

This creates:
- `claude-wiki.json` — starter config (edit this)
- `wiki/` — your wiki directory (empty to start)
- `ingest/` — drop new source files here

### Run an update

```bash
# Auto-detects claude-wiki.json by walking up from cwd:
python claude_wiki.py

# Or point to a specific config:
python claude_wiki.py --config /path/to/my-project/claude-wiki.json
```

Output will look something like:

```
Found 2 new file(s) to process.

Processing: ingest/quarterly-report.txt
    wrote: wiki/quarterly-report-summary.md
    patched: wiki/index.md
  done: Created new summary note for quarterly report; added entry to index.

Processing: ingest/meeting-2026-04-15.txt
    patched: wiki/meetings.md
  done: Appended April 15 meeting summary to meetings.md.

Wiki update complete.
```

### Dry run

See what would be processed without making any changes:

```bash
python claude_wiki.py --dry-run
```

### Command-line reference

```
usage: claude_wiki [-h] [--config PATH] [--init [DIR]] [--dry-run]

options:
  -h, --help      Show this help message and exit
  --config PATH   Path to claude-wiki.json (default: auto-detected)
  --init [DIR]    Scaffold a new claude-wiki.json in DIR (default: cwd)
  --dry-run       List new files without processing them
```

---

## How It Works

### Architecture

```
source_dirs/          wiki/
  new-doc.txt    →    index.md          (updated)
  meeting.txt    →    new-note.md       (created)
                      meetings.md       (updated)
```

1. **Discovery.** The script scans all configured `source_dirs` and compares against the processed-files log to find new files.
2. **Context assembly.** It reads every `.md` file in `wiki_dir` and formats them as context for Claude.
3. **Processing loop.** For each new file, it sends the wiki context + file content to Claude and runs a tool-use loop until Claude signals completion.
4. **Tracking.** Successfully processed files are added to `.processed_files.json` immediately after completion.

### The agentic loop

Claude is given three tools:

| Tool | What it does |
|---|---|
| `write_file` | Create or overwrite a wiki `.md` file |
| `patch_file` | Replace a specific string in an existing wiki file |
| `done` | Signal completion (ends the loop) |

Claude reads the current wiki state and the new file, then calls tools as needed before calling `done`. The script executes each tool call, sends results back to Claude, and repeats until `done` is received.

Claude uses [adaptive thinking](https://docs.anthropic.com/en/docs/about-claude/models/overview) (`thinking: {type: "adaptive"}`), which means it internally reasons through complex decisions before generating output. This is what makes it reliable at finding the right existing note to update rather than blindly creating duplicates.

### Caching and cost

Two blocks in each request are marked for [prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching):

1. **The system prompt** — stable across all tool-loop turns and across runs.
2. **The wiki context** — stable within a single file's processing loop, and across runs when the wiki hasn't changed since the last run.

In practice this means: the first file processed in a run pays full price for the wiki context; subsequent files in the same run are cache hits. Re-running the script against the same wiki state (e.g., adding more files to ingest without editing the wiki) also benefits from caching. The minimum cacheable prefix on Opus 4.7 is 4096 tokens; small wikis may not hit this threshold initially.

### Safety guarantees

The script enforces the following at execution time (not based on trust in Claude's output):

- `write_file` and `patch_file` only succeed if the resolved path is inside `wiki_dir`. Any path that resolves outside — whether through `../` traversal, symlinks, or absolute paths — is rejected with an error message returned to Claude.
- Source directory paths are explicitly checked; no file in `source_dirs` can be written even if it happens to resolve inside `wiki_dir`.
- PDFs and configured `skip_extensions` are marked processed without being read, so they never re-appear in subsequent runs.

---

## Customization

### Custom rules

The `custom_rules` array in `claude-wiki.json` injects additional instructions directly into Claude's system prompt. Use this to encode project-specific conventions:

```json
"custom_rules": [
  "Use Dublin Core metadata terms when describing digital objects",
  "Every new note must include a 'Status' line: Draft, Review, or Final",
  "Abbreviations: use 'LITS' not 'Library and Information Technology Services'"
]
```

### Multiple source directories

```json
"source_dirs": [
  "ingest",
  "meeting-notes",
  "shared-docs/incoming"
]
```

All directories are scanned on each run. Files from all of them feed into the same wiki.

### Using a smaller model

For lower cost on simple or short documents:

```json
"model": "claude-haiku-4-5"
```

Note: smaller models are less reliable at finding the right existing note to update versus creating duplicates. Opus 4.7 is recommended for wikis with more than a handful of notes.

---

## File type support

| Type | Behavior |
|---|---|
| `.md`, `.txt`, `.csv`, `.json`, `.html`, `.xml` | Read and processed |
| `.pdf` | Skipped with notice; marked processed |
| `.xlsx`, `.docx`, and others in `skip_extensions` | Skipped with notice; marked processed |
| Binary files (images, etc.) | Will be attempted; garbled output is possible. Add the extension to `skip_extensions` |

---

## Processed-files log

The file `wiki/.processed_files.json` (or wherever `processed_log` points) records every file path that has been successfully processed. It is updated after each successful file, so a run that fails midway will retry incomplete files on the next run.

To reprocess a file (e.g., because you edited the source or want to refresh the wiki entry), remove its path from the JSON array — or delete the log entirely to reprocess everything from scratch.

---

## Examples

### Example: Research project

```
my-research/
  claude-wiki.json
  ingest/
    smith-2024-digital-preservation.txt   ← drop papers here
    jones-2025-metadata-standards.txt
  wiki/
    index.md
    smith-2024.md                         ← created by claude-wiki
    metadata-standards.md                 ← updated by claude-wiki
```

`claude-wiki.json`:
```json
{
  "wiki_dir": "wiki",
  "source_dirs": ["ingest"],
  "wiki_description": "a literature review knowledge base for digital preservation research",
  "custom_rules": [
    "Always note the year and author in new note titles",
    "Add a 'Key argument' section at the top of each paper summary note"
  ]
}
```

### Example: Meeting notes

```json
{
  "wiki_dir": "knowledge-base",
  "source_dirs": ["raw-meeting-notes"],
  "wiki_description": "a project knowledge base for the Hamilton Digitization Initiative",
  "custom_rules": [
    "Append meeting summaries to knowledge-base/meetings.md, don't create per-meeting files",
    "Extract action items into knowledge-base/action-items.md"
  ]
}
```

### Example: Multiple ingest directories

```json
{
  "wiki_dir": "wiki",
  "source_dirs": [
    "vendor-docs",
    "internal-memos",
    "meeting-notes"
  ],
  "wiki_description": "a technical knowledge base for the Systems team",
  "skip_extensions": ["pdf", "xlsx"]
}
```

---

## Troubleshooting

**`ANTHROPIC_API_KEY environment variable is not set`**
Set the key before running: `export ANTHROPIC_API_KEY="sk-ant-..."`

**`No new files to process`**
Either all files in source directories are already in `.processed_files.json`, or the source directories don't exist yet. Check with `--dry-run`.

**`old_text not found in wiki/some-note.md`**
Claude tried to patch a note but the text it was targeting has changed. This is safe — the error is returned to Claude, which usually retries with corrected text or uses `write_file` instead. If it happens frequently, check that Claude's wiki context is current (re-run after any manual wiki edits).

**`path is outside wiki_dir — write rejected`**
Claude tried to write a file outside the allowed directory. The error is returned to Claude and the run continues. This can happen if `wiki_description` or `custom_rules` mention paths that confuse the model. Review your config for ambiguous path references.

**Large wikis are slow**
The wiki context is read from disk on every file. For wikis with many large notes, consider splitting the wiki into subdirectories and running separate config files per section.

---

## License

Copyright (C) 2026 Patrick R. Wallace, Hamilton College Library and Information Technology Services (LITS).

This program is free software: you can redistribute it and/or modify it under the terms of the **GNU General Public License, version 3** (GPL-3.0-or-later), as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful, but **without any warranty**; without even the implied warranty of merchantability or fitness for a particular purpose. See the GNU General Public License for more details.

Full license text: <https://www.gnu.org/licenses/gpl-3.0.html>

---

*Developed during the Hamilton College LITS AI Evaluation Sprint, April–May 2026.*
