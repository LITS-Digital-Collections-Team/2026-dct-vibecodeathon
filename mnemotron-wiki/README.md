# Mnemotron Wiki

**A personal knowledge base that builds itself from your work.**

Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS  
Code: GPL-3.0-or-later | Documentation: GFDL-1.3-or-later | See [License](#license)

> **AI-generated code notice:** This software was developed with the
> assistance of Claude (Anthropic). All code has been reviewed and tested.
> Users are responsible for validating behavior in their own environments.

Mnemotron Wiki is a Claude-powered system that synthesizes professional
documents, email, calendar data, and project notes into a structured,
searchable Markdown wiki. You supply the raw material; Claude distills it
into dossiers, topic pages, and a running index. Everything lives in plain
Markdown files that you own, version with git, and read in any editor.

---

## Contents

- [How it works](#how-it-works)
- [Privacy and data handling](#privacy-and-data-handling) ← **read before setup**
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Detailed setup](#detailed-setup)
- [Usage guide](#usage-guide)
- [Optional connectors](#optional-connectors)
- [Utility scripts reference](#utility-scripts-reference)
- [Customizing the pipeline](#customizing-the-pipeline)
- [Scheduling automated runs](#scheduling-automated-runs)
- [Directory reference](#directory-reference)
- [License](#license)
- [Credits](#credits)

---

## How it works

The system has three layers.

**1. Drop zone (`raw_ingest/`)**  
Drop any supported document here: PDFs, Word files, meeting notes, email
exports. Optional connector tasks (Gmail, Google Calendar, Asana) can also
write here automatically before a wiki update runs.

**2. The wiki update task**  
Say "run the wiki update task" in a Claude session. Claude reads
`WIKI_UPDATE_TASK.md`, scans `raw_ingest/` for new files, synthesizes each
document into wiki pages, updates the main index, and commits to git. A
content-hash manifest ensures nothing is processed twice.

**3. The wiki (`wiki/`)**  
Plain Markdown files in four directories:

| Directory | Contents |
|-----------|----------|
| `wiki/daily/` | Dated journal entries (from briefings or Asana summaries) |
| `wiki/topics/` | One page per project, initiative, or concept |
| `wiki/people/` | One dossier per person |
| `wiki/organizations/` | One page per org, team, or department |

A typical run looks like this:

```
$ cd /path/to/my-wiki
$ claude
> Run the wiki update task.

[Claude scans raw_ingest/, processes 3 new files, updates 2 topic pages,
creates 1 new people page, regenerates INDEX.md, and commits.]

Wiki update complete — 2026-04-24
  Files processed:  3
  Pages updated:    2
  Pages created:    1
  Commit:           wiki update 2026-04-24
```

---

## Privacy and data handling

**Read this section before setting up the system.**

### What stays on your machine

Your wiki files are plain Markdown stored locally in a git repository. They
do not leave your machine unless you push to a remote git repository or send
them to Claude during processing.

### What leaves your machine

When you run the wiki update task or any connector task, Claude reads the
text of your source documents and writes results back to local files. The
content you are processing — meeting notes, emails, calendar events, PDFs —
is transmitted to Anthropic's servers during that processing session.

**You are responsible for deciding what is appropriate to send.** This
system can be configured to process highly sensitive professional data.
Consider the sensitivity of each category before enabling it.

---

### Guidance by account type

#### Institutional accounts (enterprise agreements, BAAs)

If you are using Claude through an institutional agreement — a university,
employer, or organization with a Business Associate Agreement or Data
Processing Agreement with Anthropic — your institution's data handling
policies govern what you may process. Before using this system with work data:

- Consult your IT security or legal team about what categories of data may
  be processed by an external AI service.
- Ask specifically about: employee communications, HR records, student
  records (FERPA in the US), financial data, health information (HIPAA),
  and legal documents.
- Verify whether your institution's agreement with Anthropic covers your
  specific use case (personal knowledge management vs. official workflows).

#### Claude.ai personal accounts (Free, Pro, Team plans)

By default, Anthropic may use content from conversations on personal plans
to improve its models. If you are on a personal plan:

- **Review** Anthropic's current Privacy Policy and Terms of Service before
  processing any sensitive content. Policies change; always check the
  current version at anthropic.com.
- **Enable privacy controls** in your account settings. At the time of
  writing, claude.ai offers options to disable conversation history and
  opt out of model training — verify current options in your account.
- **Do not process** personnel records, salary or compensation data,
  medical or health information, legal documents under privilege, student
  records, or other regulated content through a personal plan without first
  understanding the privacy implications.
- **Be aware** that even with privacy settings enabled, Anthropic retains
  usage metadata (timestamps, token counts, feature usage).
- Consider whether the people you correspond with have consented to having
  their communications summarized by a third-party AI service.

#### Anthropic API (direct access)

Per Anthropic's API usage policy, content submitted via the API is not used
to train models by default. However:

- Verify the current API data retention and usage terms at anthropic.com
  before processing sensitive data — policies may change.
- API-based Claude Code sessions have better data handling guarantees than
  personal claude.ai plans, but institutional review is still advisable for
  regulated content.

---

### Special warnings for connector data

**Gmail connector:** Email is among the most sensitive data this system can
process. Threads may contain personnel matters, compensation discussions,
medical information, legal communications, and personal conversations. Use
the filter rules in `GMAIL_INGEST_TASK.md` carefully. Err on the side of
exclusion — if a thread would be uncomfortable to have summarized in a work
document, it should not be processed.

**Google Calendar connector:** Calendar data reveals sensitive patterns:
who you meet with, how often, and your schedule structure. The calendar
connector is designed to capture structural information only (cadence,
attendees, meeting series) and explicitly excludes meeting content. Review
filter rules in `CALENDAR_INGEST_TASK.md` and exclude personal appointments.

---

### Git remotes

If you push this repository to a remote (GitHub, GitLab, etc.):

- **Use a private repository.** Never push wiki content to a public repo.
- Your wiki content (dossiers, topic pages, daily entries) will be stored
  on the hosting service's servers.
- Consider whether your institution's policies permit storing work notes in
  personal or externally hosted repositories.

---

## Requirements

**Required:**
- Python 3.10 or later
- Claude Code CLI, or claude.ai with Projects and file tools enabled
- An Anthropic account (institutional, personal, or API)
- Git

**Optional (only needed for connectors):**
- Gmail MCP connector configured in your Claude session
- Google Calendar MCP connector configured in your Claude session
- Asana MCP connector configured in your Claude session

---

## Quick start

```bash
# 1. Clone or download
git clone <repo-url> my-wiki
cd my-wiki

# 2. Install Python dependencies
pip install -r scripts/requirements.txt

# 3. Personalize the starter files (see Detailed Setup)

# 4. Open a Claude session in the wiki root
claude

# 5. In your Claude session, say:
Run the wiki update task.
```

On first run with an empty `raw_ingest/`, the task scans, finds nothing
to process, updates `wiki/INDEX.md`, and commits. That is the expected
behavior — you are now ready to feed it content.

---

## Detailed setup

### Step 1: Clone or download

```bash
git clone <repo-url> my-wiki
cd my-wiki
```

If you downloaded a zip instead of cloning:

```bash
cd my-wiki
git init
git add .
git commit -m "initial mnemotron-wiki setup"
```

### Step 2: Install Python dependencies

```bash
pip install -r scripts/requirements.txt
```

| Package | Used for |
|---------|----------|
| `pdfminer.six` | PDF text extraction |
| `python-docx` | DOCX and ODT extraction |
| `beautifulsoup4` | HTML extraction |
| `lxml` | HTML parser (required by BeautifulSoup) |
| `pyyaml` | YAML frontmatter parsing (optional but recommended) |

If you are not using Asana, you can skip `pyyaml` — the scripts include a
minimal fallback parser for flat YAML frontmatter.

### Step 3: Personalize the starter files

**Your self-page:** Rename `wiki/people/your-name.md` and fill in your
own information. Claude uses this as context for understanding who you are
and what you work on.

```bash
mv wiki/people/your-name.md wiki/people/alex-chen.md
# Edit the file to replace placeholder content with your own
```

**Your organization:** Edit `wiki/organizations/lits.md` to describe your
institution or team. Replace all placeholder content.

**The index:** Edit `wiki/INDEX.md` to update the People and Organizations
tables so they point to your renamed files.

### Step 4: Open a Claude session in the wiki root

With Claude Code CLI:

```bash
cd /path/to/my-wiki
claude
```

With claude.ai Projects:
1. Create a new Project in claude.ai.
2. Enable file tools under Project settings.
3. Set the file tool's working directory to your wiki root.

### Step 5: Run the first wiki update

In your Claude session:

```
Run the wiki update task.
```

Claude reads `WIKI_UPDATE_TASK.md` automatically — you do not need to paste
it into the conversation. It will scan, find nothing to process on first
run, regenerate the index, and commit.

---

## Usage guide

### Feeding content to the wiki

Drop any supported file into `raw_ingest/` and run the wiki update task.
Claude will extract the text, decide whether to create a new page or merge
into an existing one, write the page, update the manifest, and delete the
source file.

**Supported file types:**

| Extension | Notes |
|-----------|-------|
| `.pdf` | Text-layer PDFs only; scanned image PDFs extract minimal text |
| `.docx` / `.odt` | Word-compatible documents |
| `.md` / `.txt` | Plain text or Markdown |
| `.html` / `.htm` | Strips tags; extracts visible text |
| `.csv` | Reformatted as pipe-separated text for readability |
| `.eml` | Email export format; extracts headers and body text |

**Example workflow:**

```bash
# Drop some files
cp ~/Downloads/q2-planning-notes.pdf raw_ingest/
cp ~/Downloads/annual-review-2025.docx raw_ingest/

# Check what is waiting to be processed
python scripts/check_ingest.py
# raw_ingest/q2-planning-notes.pdf
# raw_ingest/annual-review-2025.docx

# In your Claude session:
Run the wiki update task.
```

After the run, `raw_ingest/` will be empty (files are deleted after
successful processing) and the wiki will have new or updated pages.

**What gets created from a planning notes PDF:**

- A new `wiki/topics/q2-planning.md` (or an update to an existing page)
  with a summary, key points, and source document reference.
- New stub pages under `wiki/people/` for any people named in the notes
  who do not yet have a dossier page.
- An updated `wiki/INDEX.md`.

### People pages

Claude creates and updates people pages as names appear in source material.
A typical page looks like this:

```markdown
---
name: "Jordan Smith"
email: jsmith@example.edu
title: "Director of Digital Initiatives"
department: "Library"
organization: "Example University"
relationship: colleague
updated: 2026-04-15
---

# Jordan Smith

## Profile

Director of Digital Initiatives at Example University. Primary contact for
the shared metadata standards project.

## Personal Overview

Jordan communicates in terse, decision-focused emails — rarely more than
three sentences — but follows up quickly when action is needed. Tends to
front-load context in meeting agendas and prefers written summaries to
verbal debriefs.

## Working Relationship

Quarterly check-ins on the shared metadata project; occasional collaboration
on grant proposals.

## Interactions

| Date | Context |
|------|---------|
| 2026-04-10 | Metadata standards call — reviewed draft schema |
| 2026-03-22 | Intro meeting via DCT listserv |
```

The **Personal Overview** section is cumulative: it synthesizes
communication style, working habits, and character from all available
sources — documents, email, and calendar data. It grows richer over time.

You can add your own notes to any section. Claude preserves your edits
and builds on them on subsequent runs.

### Topic pages

Topic pages cover projects, initiatives, programs, or recurring themes:

```markdown
---
updated: 2026-04-15
sources:
  - q2-planning-notes.pdf
tags:
  - planning
  - digital-collections
---

# Q2 Planning

## Summary

Quarterly planning session for Digital Collections. Team agreed to
prioritize the IA upload backlog with a target of 500 items by June 30.

## Key Points

The upload workflow bottleneck was identified as metadata review, not
the upload tooling itself. A dedicated metadata sprint is planned for May.
Three staff members will receive ArchivesSpace training before the sprint.

## Source Documents

| Document | Date Ingested | Notes |
|----------|--------------|-------|
| q2-planning-notes.pdf | 2026-04-15 | Q2 planning session notes |
```

### Daily entries

If you use morning briefings (Markdown files dropped into
`raw_ingest/claude-briefings/` named `morning-brief_YYYY-MM-DD.md`), the
wiki update task synthesizes them into dated daily entries at
`wiki/daily/YYYY-MM-DD.md`.

---

## Optional connectors

All connectors are independent. Use none, one, or all of them. Each writes
to a subdirectory of `raw_ingest/`, which the wiki update task processes
on the next run.

### Gmail connector

Reads recent email threads and writes structured summaries to
`raw_ingest/gmail/`. These become dossier updates for people pages and
topic updates for project pages.

**Setup:**

1. Connect the Gmail MCP server in your Claude session:
   - **Claude Code CLI:** Add it to `mcp_servers` in your Claude Code
     settings (see Claude Code documentation for MCP configuration).
   - **claude.ai:** Settings → Integrations → Gmail.
2. In your Claude session:
   ```
   Run the Gmail ingest task.
   ```
3. Claude retrieves threads, filters noise (notifications, newsletters,
   automated alerts), clusters by person and topic, and writes summaries.
4. Run the wiki update task to incorporate the summaries into the wiki.

**First run:** Looks back 30 days. Subsequent runs look back 7 days.

**What gets filtered:** `noreply` senders, automated system notifications,
calendar invites with no message body, mailing list digests, IT/HR system
messages. Review and adjust the rules in `GMAIL_INGEST_TASK.md` Stage 3.

**Privacy note:** Review the [Gmail warning](#special-warnings-for-connector-data)
above before enabling this connector.

---

### Google Calendar connector

Reads recent and upcoming calendar events and writes structural summaries
to `raw_ingest/calendar/`. These contribute to a `meeting-cadence.md`
topic page and add attendance rows to people pages.

**Important:** The calendar connector captures *structure only* — who meets
with whom and how often. It does not record what was discussed. Use the
Gmail connector for meeting content.

**Setup:**

1. Connect the Google Calendar MCP connector in your Claude session
   (Claude Code `mcp_servers` config, or claude.ai Integrations).
2. In your Claude session:
   ```
   Run the calendar ingest task.
   ```

**What it produces:**

- A `recurring-<slug>-<YYYYMMDD>.md` file when the meeting cadence
  changes (new series, discontinued series, or changed attendees). The
  wiki update task synthesizes this into `wiki/topics/meeting-cadence.md`.
- An `events-notable-<YYYYMMDD>.md` file listing one-off significant
  meetings, upcoming commitments, and new contacts.

**Lookback/lookahead:** Defaults to 7 days past, 14 days ahead. Adjust
in the Configuration table in `CALENDAR_INGEST_TASK.md`.

---

### Asana connector

Ingests Asana project histories as topic pages. Asana files are idempotent
refreshes of live project state: re-running the task updates the existing
page rather than creating a duplicate.

**How idempotency works:**

The Asana ingest uses a separate manifest (`.asana_manifest.json`) keyed
by `project_gid` rather than content hash. Claude can recognize the same
project across multiple exports even when the content changes (updated task
counts, new status messages, etc.).

Auto-generated content is wrapped in markers so user-authored notes are
never overwritten:

```
<!-- asana:auto-start -->
... Asana snapshot and task history (regenerated each run) ...
<!-- asana:auto-end -->

## Notes
Your notes here are preserved across every refresh.
```

**Setup:**

1. Connect the Asana MCP connector in your Claude session.
2. Export a project history to `raw_ingest/asana/` in the format described
   in `WIKI_UPDATE_TASK.md` Stage 3a. Asana files are identified by
   `source: Asana` and a `project_gid` in the frontmatter.
3. Run the wiki update task.

---

## Utility scripts reference

Run all scripts from the wiki root directory.

### `scripts/check_ingest.py` — list unprocessed files

```bash
python scripts/check_ingest.py              # files awaiting processing
python scripts/check_ingest.py --all        # all files including processed
python scripts/check_ingest.py --summary    # counts only
```

Example output:
```
raw_ingest/q2-planning-notes.pdf
raw_ingest/annual-review-2025.docx
```

Use this before a wiki update to see what is in the queue, or after to
confirm everything was processed.

### `scripts/manifest.py` — list processed files

```bash
python scripts/manifest.py
```

Example output:
```
Filename                                  Processed (UTC)            Wiki page
----------------------------------------------------------------------------------------------------
q2-planning-notes.pdf                     2026-04-15T14:32:00+00:00  wiki/topics/q2-planning.md
annual-review-2025.docx                   2026-04-15T14:35:00+00:00  wiki/topics/annual-review.md
```

### `scripts/extract_text.py` — test text extraction

Verify a file will extract correctly before dropping it in `raw_ingest/`:

```bash
python scripts/extract_text.py path/to/document.pdf
```

Example output:
```
--- metadata ---
  title: Q2 Planning Session Notes
  author: Alex Chen
--- text ---
Q2 Planning — Digital Collections

Present: Alex Chen, Jordan Smith, ...
[full extracted text...]
```

If the command returns an error or empty text, the file will likely land
in `raw_ingest/failed/` during a real run. Common causes:

| Problem | Cause | Fix |
|---------|-------|-----|
| Empty output from a PDF | Scanned image PDF with no text layer | Run OCR first (e.g., `ocrmypdf`) |
| `PasswordError` | Encrypted PDF | Remove password protection before dropping |
| `PackageNotFoundError` | Missing dependency | Run `pip install -r scripts/requirements.txt` |

### `scripts/asana_manifest.py` — list Asana projects

```bash
python scripts/asana_manifest.py
```

Example output:
```
Project (gid)          Slug                                          Last ingested  Wiki page
----------------------------------------------------------------------------------------------------------
1234567890123456       dc-brothertown-project                        2026-04-15     wiki/topics/dc-brothertown-project.md
```

---

## Customizing the pipeline

The `*_TASK.md` files are Claude's instructions. Edit them to change
pipeline behavior — no code changes required. Claude reads the updated
instructions on the next run.

**Common customizations:**

| What to change | Where |
|----------------|-------|
| What topics get their own pages | `WIKI_UPDATE_TASK.md` Stage 2 |
| Topic page format and sections | `WIKI_UPDATE_TASK.md` Stage 2 (template) |
| People page format | `WIKI_UPDATE_TASK.md` Stage 2b (template) |
| Gmail filter rules | `GMAIL_INGEST_TASK.md` Stage 3 |
| Gmail lookback window | `GMAIL_INGEST_TASK.md` Configuration table |
| Calendar lookback/lookahead windows | `CALENDAR_INGEST_TASK.md` Configuration table |
| Supported file extensions | `SUPPORTED_EXTENSIONS` in `scripts/config.py` |
| Adding a new file type extractor | `scripts/extract_text.py` — add a function and register it in `_EXTRACTORS` |

---

## Scheduling automated runs

### Claude Code cron (recommended)

In your Claude session:

```
/cron add "30 8 * * 1-5" "Run the wiki update task."
```

To run Gmail ingest before the wiki update each weekday:

```
/cron add "15 8 * * 1-5" "Run the Gmail ingest task."
/cron add "30 8 * * 1-5" "Run the wiki update task."
```

### System cron (Linux/macOS)

```bash
crontab -e

# Daily wiki update at 8:30 AM, weekdays
30 8 * * 1-5 cd /path/to/my-wiki && claude -p "Run the wiki update task."
```

### launchd (macOS)

Create a `.plist` file in `~/Library/LaunchAgents/` to schedule via
launchd. See Apple developer documentation for the `.plist` schema.

### Suggested schedule

| Task | Frequency | Notes |
|------|-----------|-------|
| Wiki update | Daily (morning) | Processes whatever landed overnight |
| Gmail ingest | Daily, before wiki update | Run first; wiki update incorporates it |
| Calendar ingest | Weekly or as needed | Meeting cadence changes slowly |
| Asana ingest | Weekly | After significant project activity |

---

## Directory reference

```
mnemotron-wiki/
├── README.md                   ← you are here
├── LICENSE                     ← GPL-3.0 (code) / GFDL-1.3 (docs)
├── WIKI_UPDATE_TASK.md         ← main pipeline instructions for Claude
├── GMAIL_INGEST_TASK.md        ← Gmail connector instructions
├── CALENDAR_INGEST_TASK.md     ← Calendar connector instructions
├── .manifest.json              ← processed-file index (do not edit)
├── .asana_manifest.json        ← Asana project index (do not edit)
├── .gitignore
├── scripts/
│   ├── config.py               ← all path configuration
│   ├── manifest.py             ← content-hash manifest library
│   ├── check_ingest.py         ← list unprocessed files
│   ├── extract_text.py         ← extract text from PDF, DOCX, HTML, etc.
│   ├── asana_manifest.py       ← Asana project tracking (optional)
│   ├── ingest_asana_project.py ← Asana-specific ingest path (optional)
│   └── requirements.txt        ← Python dependencies
├── raw_ingest/
│   ├── claude-briefings/       ← morning briefing files
│   ├── asana/                  ← Asana project exports (optional)
│   ├── gmail/                  ← Gmail ingest output (optional)
│   ├── calendar/               ← Calendar ingest output (optional)
│   └── failed/                 ← extraction failures (quarantine)
└── wiki/
    ├── INDEX.md                ← auto-maintained table of contents
    ├── daily/                  ← dated journal entries
    ├── topics/                 ← project and concept pages
    ├── people/                 ← person dossiers
    └── organizations/          ← organization pages
```

### Files managed automatically (do not edit manually)

Editing manifest files can cause the pipeline to reprocess already-ingested
content or skip content it has not actually processed.

| File | Managed by |
|------|-----------|
| `.manifest.json` | Wiki update task |
| `.asana_manifest.json` | Wiki update task (Asana path) |
| `.calendar_manifest.json` | Calendar connector |
| `.gmail_manifest.json` | Gmail connector |

---

## License

### Code (GPL-3.0-or-later)

All Python scripts and supporting code in this repository are licensed under
the GNU General Public License, version 3 or any later version.

```
Mnemotron Wiki
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.
```

Full license text: <https://www.gnu.org/licenses/gpl-3.0.html>

### Documentation (GFDL-1.3-or-later)

All documentation in this repository — README.md, WIKI_UPDATE_TASK.md,
GMAIL_INGEST_TASK.md, CALENDAR_INGEST_TASK.md — is licensed under the GNU
Free Documentation License, Version 1.3 or any later version published by
the Free Software Foundation; with no Invariant Sections, no Front-Cover
Texts, and no Back-Cover Texts.

Full license text: <https://www.gnu.org/licenses/fdl-1.3.html>

### AI-generated code notice

Portions of this software were developed with the assistance of Claude
(Anthropic). All code has been reviewed and tested. Users are responsible
for validating behavior in their own environments. No warranty is provided,
express or implied.

---

## Credits

**Author:** Patrick R. Wallace  
**Institution:** Hamilton College Library and Information Technology Services (LITS)  
**Year:** 2026

Mnemotron Wiki was developed at Hamilton College LITS as a personal
knowledge management tool for AI-assisted institutional work environments.
