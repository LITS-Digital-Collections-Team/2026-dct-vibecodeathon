<!--
SPDX-License-Identifier: GFDL-1.3-or-later
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
Permission is granted to copy, distribute and/or modify this document under the terms of the GNU Free Documentation License, Version 1.3 or any later version published by the Free Software Foundation; with no Invariant Sections, no Front-Cover Texts, and no Back-Cover Texts.

AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude Sonnet 5.5). It may not have been fully reviewed by a human; test it in your own environment before relying on it.
-->

# Mnemotron Wiki

**A personal knowledge base that builds itself from your work.**

Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS  
Code and Claude instruction documents (`*_TASK.md`): GPL-3.0-or-later | Documentation: GFDL-1.3-or-later | See [License](#license)

> **AI-assisted software notice:** This software was created with assistance
> from Claude Code (Claude Sonnet 5.5). It may not have been fully reviewed by
> a human. Test it in your own environment before relying on it; you are
> responsible for validating its behavior and for what you send to any AI
> service.

Mnemotron Wiki is a Claude-powered system that synthesizes professional
documents, email, calendar data, and project notes into a structured,
searchable Markdown wiki. You supply the raw material; Claude distills it
into dossiers, topic pages, converted-document pages, and a running index. Everything lives in plain
Markdown files that you own, version with git, and read in any editor.

---

## Contents

- [How it works](#how-it-works)
- [Privacy and data handling](#privacy-and-data-handling) ← **read before setup**
- [Requirements](#requirements)
- [Claude backends](#claude-backends)
- [Concurrency and parallel agents](#concurrency-and-parallel-agents)
- [Quick start](#quick-start)
- [Detailed setup](#detailed-setup)
- [Usage guide](#usage-guide)
- [Optional connectors](#optional-connectors)
- [Organization-specific connectors](#organization-specific-connectors)
- [Email archive (verbatim)](#email-archive-verbatim)
- [Exporting a static site](#exporting-a-static-site)
- [Utility scripts reference](#utility-scripts-reference)
- [Customizing the pipeline](#customizing-the-pipeline)
- [Scheduling automated runs](#scheduling-automated-runs)
- [Directory reference](#directory-reference)
- [Relationship to the sibling tool](#relationship-to-the-sibling-tool)
- [License](#license)
- [Credits](#credits)

---

## How it works

The system has three layers.

**1. Drop zone (`raw_ingest/`)**  
Drop any supported document here: PDFs (including scans, via OCR), Word
files, meeting notes, email exports. Optional connector tasks (Gmail, Google
Calendar, Asana, daily briefings) can also write here before a wiki update
runs.

**2. The wiki update task**  
Say "run the wiki update task" in a Claude session. Claude reads
`WIKI_UPDATE_TASK.md`, scans `raw_ingest/` for new files, synthesizes each
document into wiki pages, updates the main index, and commits to git. A
content-hash manifest ensures nothing is processed twice.

**3. The wiki (`wiki/`)**  
Plain Markdown files in six directories:

| Directory | Contents |
|-----------|----------|
| `wiki/daily/` | Dated journal entries (from briefings or Asana summaries) |
| `wiki/topics/` | One page per project, initiative, or concept |
| `wiki/people/` | One dossier per person |
| `wiki/organizations/` | One page per org, team, or department |
| `wiki/documents/` | Converted PDF / Word / HTML documents, each with a short generated summary header and links to related pages |
| `wiki/email/` | Verbatim archived email — a separate, on-demand task; see [Email archive (verbatim)](#email-archive-verbatim) |

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
- Python 3.9 or later
- A way for Claude to run: either the Claude Code CLI (`claude`, the default)
  or an Anthropic API key — see [Claude backends](#claude-backends)
- Git

**Optional:**
- Tesseract and poppler (`tesseract`, `pdftoppm`) for offline OCR of scanned
  PDFs and images; without them OCR falls back to Claude vision
- Gmail, Google Calendar and Asana MCP connectors (only for the
  [optional connectors](#optional-connectors); local-file alternatives exist)

---

## Claude backends

Every script that needs a language model calls it through `scripts/llm.py`,
which supports two backends:

| Backend | Selected by | Notes |
|---------|-------------|-------|
| `cli` (default when `claude` is on your PATH) | `MNEMOTRON_BACKEND=cli` | Runs the headless Claude Code CLI (`claude -p`). Uses the login the CLI already has; no API key and no Python package needed. |
| `api` | `MNEMOTRON_BACKEND=api` | Uses the Anthropic API via the optional `anthropic` package. Credentials come from `ANTHROPIC_API_KEY`, `MNEMOTRON_API_KEY_FILE`, `MNEMOTRON_API_KEY_COMMAND`, or the SDK's own mechanisms. |

You can also set the backend (and per-backend options) in
`config.local.json`. Run `python scripts/check_auth.py` to see which backend
is usable and why (add `--call` to make one tiny real request). Full details,
including credential handling, are in [AUTHENTICATION.md](AUTHENTICATION.md).
Scripts that do not call a model (`check_ingest.py`, `build_index.py` without
`--use-api`, `wiki_export.py`, ...) need neither.


### Running the task documents on either backend

The `*_TASK.md` files are instructions for an agent that can read and write files and run
the helper scripts. `scripts/run_task.py` provides that agent on **either** backend, so no
functionality depends on how you authenticate:

```bash
python scripts/run_task.py WIKI_UPDATE_TASK.md --dry-run            # show the plan; no Claude call
python scripts/run_task.py WIKI_UPDATE_TASK.md --prompt "optional extra instructions"
python scripts/run_task.py WIKI_UPDATE_TASK.md --backend api         # force the API agent for this run
```

* **`cli` backend:** headless Claude Code does the agent work with an explicit permission
  allowlist (file edits, the wiki's own scripts, read-only git plus add/commit). Claude Code's
  subagents and any MCP connectors configured in Claude Code are available (allow them with
  `--allow-tool "mcp__<server>__*"`).
* **`api` backend:** a built-in sandboxed tool-use loop over the Messages API (file tools inside
  the wiki root, allowlisted commands without a shell, `run_subtask` workers with exclusive page
  ownership, optional remote MCP servers via `--mcp NAME=https://URL`). Needs only an API key.
* One run at a time per wiki (a lock refuses overlaps unless `--force`).
* Both modes are bounded by your plan or API budget; use `--max-budget-usd` (cli) or `--max-turns`
  (api) to cap a run. Content you process is sent to Anthropic.

---

## Concurrency and parallel agents

Stage 2 of the update task dispatches independent work units to parallel
agents. To keep that safe:

- **Page claims.** `scripts/agent_manifest.py check|claim|release|prune|list`
  records which agent owns which wiki pages in `wiki/.agent-manifest.json`.
  Claims are atomic. Before dispatch, run `check` on the pages in your plan;
  each agent claims its pages, writes only those, and releases them. Parallel
  agents never edit the same page. `prune --hours N` clears claims left by
  crashed agents.
- **Locked, atomic writes.** `scripts/locking.py` provides file locks, atomic
  writes and merge-on-save helpers. Every script that writes a manifest, log
  or JSON cache uses them, so concurrent runs cannot corrupt or silently
  overwrite each other's entries.
- The shared manifests and logs are still best written by one orchestrating
  context; the task documents say where.

---

## Quick start

```bash
# 1. Clone or download
git clone <repo-url> my-wiki
cd my-wiki

# 2. One-time setup: creates folders, installs Python dependencies,
#    and checks which Claude backend is usable
bash setup.sh

# 3. Personalize the starter files (see Detailed Setup); optional personal
#    settings go in config.local.json (see the header of scripts/config.py)

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

### Step 2: Run setup and install Python dependencies

```bash
bash setup.sh            # creates folders, installs dependencies, checks Claude access
# or, by hand:
python3 -m pip install -r scripts/requirements.txt
```

| Package | Used for |
|---------|----------|
| `pdfminer.six` | PDF text extraction |
| `python-docx` | DOCX and ODT extraction |
| `beautifulsoup4` | HTML extraction |
| `lxml` | HTML parser (required by BeautifulSoup) |
| `markdown` | Markdown → HTML conversion (`wiki_export.py` only) |
| `requests` | HTTP client (`enrich_person.py` and `fetch_urls.py` only) |
| `pyyaml` | YAML frontmatter parsing (`ingest_takeout.py`, `ingest_asana_project.py`) |
| `Pillow`, `pytesseract`, `pdf2image` | OCR of scanned PDFs and images (`ocr.py`; also need the `tesseract` and poppler system packages) |
| `anthropic` | *Optional.* Only for the `api` backend (see [Claude backends](#claude-backends)); not needed with the Claude Code CLI |

Only `pdfminer.six`, `python-docx`, `beautifulsoup4`, and `lxml` are needed
for the core pipeline. The rest support optional scripts; skip them if you are
not using those scripts.

### Step 3: Personalize the starter files

**Your self-page:** Rename `wiki/people/your-name.md` and fill in your
own information. Claude uses this as context for understanding who you are
and what you work on.

```bash
mv wiki/people/your-name.md wiki/people/jane-doe.md
# Edit the file to replace placeholder content with your own
```

**Your organization:** Edit `wiki/organizations/example-org.md` (rename it
too, if you like) to describe your institution or team. Replace all
placeholder content.

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
| `.pdf` | Text-layer PDFs are converted to `wiki/documents/` pages; scanned PDFs are detected and routed through OCR (`scripts/ocr.py`: Tesseract first, Claude vision as fallback) |
| `.docx` / `.doc` / `.odt` | Word-compatible documents (converted to `wiki/documents/` pages; `.doc` uses `textutil` on macOS or `docx2txt`) |
| `.png` / `.jpg` / `.tif` / ... | Images: screenshots get a quick text extraction; scans go through OCR |
| `.ics` / `.vcf` / `.json` / `.jsonl` / `.xml` | Calendar, contact and structured data, extracted as text |
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

### Converted documents

PDF, Word and HTML files are converted into structured Markdown pages in
`wiki/documents/` by `scripts/ingest_document.py` (which uses
`convert_document.py`, `document_ingest.py` and, for scans, `ocr.py`). Each
page gets a short summary header and links to related people, organization and
topic pages. The conversion happens in one script call, so the full document
text never has to pass through your interactive session. `classify_ingest.py`
marks these files as `document-conversion` units.

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

## Your Read

You've found Jordan's decisiveness reassuring in a project that otherwise
moves slowly — quick, terse email replies that rarely need a follow-up
question. There's mild uncertainty about whether "terse" ever tips into
"disengaged"; worth a direct check-in next quarter rather than assuming.

## Observed Patterns

- Replies to email within a few hours, rarely more than three sentences
  [email]
- Front-loads context in meeting agendas rather than narrating it live
  [meeting]
- Prefers written summaries to verbal debriefs; said so directly on a call
  [meeting]

## Signals

- Send the agenda 24 hours ahead — Jordan reads it before the call and
  expects to start from decisions, not context-setting
- Fast to commit, fast to expect the same back — open action items left
  unacknowledged for more than a few days read as a dropped ball

## Working Relationship

Quarterly check-ins on the shared metadata project; occasional collaboration
on grant proposals.

## Topics

- Shared metadata standards project
- Occasional grant-proposal collaboration

## Interactions

| Date | Context | Source |
|------|---------|--------|
| 2026-04-10 | Metadata standards call — reviewed draft schema | meeting |
| 2026-03-22 | Intro meeting via the metadata standards listserv | email |

## Revisions

| Date | What changed | Why |
|------|-------------|-----|
| 2026-04-10 | Added Signals section | Enough interactions accumulated to identify a working pattern |
```

**Your Read**, **Observed Patterns**, **Signals**, and **Revisions** are the
cumulative, interpretive layer — built from all available sources (documents,
email, calendar data) and refined over time:

- **Your Read** is your own first-person impression of the person — written
  explicitly from your perspective ("You've found...", "You're wary of...").
  Be honest about discomfort or uncertainty rather than sanitizing it into a
  neutral summary. Omitted on brand-new pages until there's enough to say
  something genuine.
- **Observed Patterns** are factual behavioral observations tagged with the
  source channel — `[journal]`, `[meeting]`, `[chat]`, `[email]`,
  `[calendar]`, in roughly that order of reliability for unfiltered signal.
  When channels disagree (professional in email, frustrated in a journal
  entry), that disagreement is itself worth recording, not averaged away.
- **Signals** distill the above into 3–8 operationally useful bullets: things
  worth knowing before your next meeting or email with this person. Neutral
  facts that don't affect the working relationship are left out.
- **Revisions** logs it when new information contradicts something already
  on the page, rather than silently overwriting a prior impression.

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
`wiki/daily/YYYY-MM-DD.md`. Briefings and Asana project exports are covered in
[ASANA_AND_BRIEFINGS.md](ASANA_AND_BRIEFINGS.md); you can write those files by
hand or produce them with whatever tool you already use.

---

## Optional connectors

All connectors are independent and optional. Use none, one, or all of them.
Each writes to a subdirectory of `raw_ingest/`, which the wiki update task
processes on the next run. Each connector document begins with a **Requires**
box; if you do not have what it asks for, skip that document. Nothing else
depends on it, and every one has a local-file alternative.

| Connector | Document | Requires | Writes to | Local-file alternative |
|-----------|----------|----------|-----------|------------------------|
| Gmail | `GMAIL_INGEST_TASK.md` | A Gmail connector (search threads, get thread) | `raw_ingest/gmail/` | Google Takeout via `ingest_takeout.py` |
| Calendar | `CALENDAR_INGEST_TASK.md` | A calendar connector (list events with attendees) | `raw_ingest/calendar/` | Export an `.ics` file into `raw_ingest/` |
| Email archive | `EMAIL_ARCHIVE_TASK.md` | A Gmail connector, or a local mail export | `wiki/email/` | A local `.eml` / mbox export |
| Asana and briefings | `ASANA_AND_BRIEFINGS.md` | Project-export or briefing Markdown files | `raw_ingest/asana/`, `raw_ingest/claude-briefings/` | Write the Markdown yourself |

Integration tasks only write raw files under `raw_ingest/` (plus their own
small manifests); the wiki update task is the one place that writes wiki
pages.

### Gmail connector

Reads recent email threads and writes structured summaries to
`raw_ingest/gmail/`. These become dossier updates for people pages and
topic updates for project pages.

**Setup:**

1. Make a Gmail connector available to your Claude session (see the Claude
   Code or claude.ai documentation for connecting MCP servers).
2. In your Claude session:
   ```
   Run the Gmail ingest task.
   ```
3. Claude retrieves threads, filters noise (notifications, newsletters,
   automated alerts), clusters by person and topic, and writes summaries.
4. Run the wiki update task to incorporate the summaries into the wiki.

**First run:** Looks back 90 days on a true first run (empty manifest, no
prior Gmail-derived content anywhere in the wiki). If the manifest is
missing but the wiki already has content from earlier Gmail ingest, the
actual gap can't be determined, so it falls back to a more conservative 30
days instead. Subsequent runs look back 7 days.

**What gets filtered:** `noreply` senders, automated system notifications,
calendar invites with no message body, mailing list digests, IT/HR system
messages. Review and adjust the rules in `GMAIL_INGEST_TASK.md` Stage 3.

**Privacy note:** Review the [Gmail warning](#special-warnings-for-connector-data)
above before enabling this connector.

**Alternative: bulk import from a Google Takeout export.** If you don't want
to (or can't) connect the live Gmail MCP server, `scripts/ingest_takeout.py`
processes a Google Takeout `.zip` export directly — no connector required.
It detects Gmail `.mbox` files and Google Chat JSON inside the archive and
writes the same kind of structured files to `raw_ingest/gmail/` that the
live connector would produce:

```bash
python scripts/ingest_takeout.py path/to/takeout.zip --list   # preview contents
python scripts/ingest_takeout.py path/to/takeout.zip --days 30
python scripts/ingest_takeout.py path/to/takeout.zip --since 2026-05-01
```

Pass your own address(es) with `--self jdoe@example.edu` (or set
`owner_emails` in `config.local.json`) so sent mail isn't misclustered under
your own name. This is a good option for a one-time
historical backfill; use the live connector for ongoing/incremental ingest.

---

### Google Calendar connector

Reads recent and upcoming calendar events and writes structural summaries
to `raw_ingest/calendar/`. These contribute to a `meeting-cadence.md`
topic page and add attendance rows to people pages.

**Important:** The calendar connector captures *structure only* — who meets
with whom and how often. It does not record what was discussed. Use the
Gmail connector for meeting content.

**Setup:**

1. Make a calendar connector available to your Claude session.
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

1. Make a task-tracker connector available, or write the export by hand.
2. Export a project history to `raw_ingest/asana/` in the format described
   in `ASANA_AND_BRIEFINGS.md` and `WIKI_UPDATE_TASK.md` Stage 2 (Asana path). Asana files are identified by
   `source: Asana` and a `project_gid` in the frontmatter.
3. Run the wiki update task.

---

## Organization-specific connectors

Everything above is deliberately generic: nothing in this repository assumes a
particular institution, vendor, or internal system. If your organization has
its own sources (a ticketing system, a chat export, a meeting-notes tool, a
shared drive), you can add them without touching the core. Have the source
write Markdown or text files into `raw_ingest/` (or a subfolder), following
the same rule as the connectors above: integrations write raw files, and the
wiki update task is the only thing that writes wiki pages. Describe the
connector in its own `*_TASK.md`-style document with a **Requires** box and a
local-file alternative, and add any names or filters it needs to
`config.local.json`, not to the shared files. Skip all of this if you have no
such sources.

---

## Email archive (verbatim)

A separate, on-demand task from the Gmail connector above. Where the Gmail
ingest task filters for professional relevance and writes short synthesized
summaries, this task keeps the full, unedited conversation record — headers
and body text exactly as sent — for anything that connects to your existing
wiki content.

**Say "run the email archive task"** in a Claude session. It is not scheduled
and does not run automatically; run it whenever you want to bring the archive
up to date.

**What it keeps is relevance-gated, not everything.** A thread is archived in
full only if it connects — even loosely — to something already documented in
`wiki/people/`, `wiki/topics/`, or `wiki/organizations/`. Institutional-domain
membership alone (e.g. any `@your-institution.edu` address) does not count;
the bar is a connection to a *specific* documented person, topic, or
organization. This keeps the archive from being dominated by mail that has no
lasting connection to anything you actually track. Everything else is sorted
into one of:

| Bucket | Where it goes | What's kept |
|--------|---------------|-------------|
| Full conversation | `wiki/email/<date>-<subject-slug>-<thread-id>.md` | Complete verbatim thread, one file per Gmail thread |
| Digest-eligible (recurring automated senders) | `wiki/email/digest-<source-slug>.md` | One row per occurrence — date, subject, one-line note |
| Marketing/promotional | `wiki/email/marketing-log.md` | One row per message — date, sender, subject only |
| Candidate (real correspondence, but not yet connected to a wiki page) | `wiki/email/candidate-entities-log.md` | One row per thread, flagged for a possible future page |
| Trivial (sign-in alerts, MFA codes, bounce receipts) | Not logged at all | — |

**No attachment content is ever fetched or embedded** — filenames only.
Quoted reply history is stripped from each message (it's already stored, in
full, as its own message entry earlier in the same file) so each conversation
file grows by exactly the new text each reply adds.

**Performance:** two cache files keep repeated/backfill runs cheap —
`.relevance_index.json` (a cached lookup of every documented person/topic/org,
built by `scripts/build_relevance_index.py`) and `.digest_registry.json` (a
cached sender/subject → digest-file lookup, built by
`scripts/build_digest_registry.py`). Both rebuild automatically whenever the
wiki content they're derived from changes, and are safe to delete at any time
if something looks wrong — they regenerate on the next run.

**Synthesis pass (optional).** After archiving, `EMAIL_ARCHIVE_TASK.md` also
describes an on-demand synthesis pass that folds archived threads into topic,
people and organization pages. `scripts/check_email_synthesis.py` lists the
archived files not yet synthesized; `scripts/record_email_synthesis.py` records
the outcome in `.email_synthesis_manifest.json` (a single load-once, save-once
writer, called by the orchestrating context, never by page agents). Page
agents claim their pages as described in
[Concurrency and parallel agents](#concurrency-and-parallel-agents).

**Large backfills** (e.g. "archive everything since January") should be run
in chunks (a month at a time is a reasonable default) rather than as one
giant window — see `EMAIL_ARCHIVE_TASK.md` for the full chunking guidance.

**Privacy note:** this task keeps correspondence verbatim, with no
summarization and no content-based filtering beyond the trivial/marketing/
digest/relevance rules above — review the
[Gmail warning](#special-warnings-for-connector-data) above, and decide for
yourself whether sensitive personal content sent from your own account
belongs in a verbatim archive before enabling this task. The default policy
in `EMAIL_ARCHIVE_TASK.md` is inclusive (archive rather than redact); edit
that file if you want different defaults.

---

## Exporting a static site

`wiki_export.py` renders the entire wiki to self-contained static HTML —
useful for browsing your wiki in a browser, or publishing a private read-only
copy without exposing the raw Markdown source or git history.

```bash
python wiki_export.py                          # writes to ./wiki-export/
python wiki_export.py -o /path/to/output       # custom output directory
```

By default it exports index, topics, people, organizations and daily pages;
`--all` (or `--documents`, `--email`) adds the larger sections.

Each Markdown page becomes an HTML page with the same relative path, internal
links are rewritten to point at the exported `.html` files, and an index page
is generated for each directory. The output has no build step and no
JavaScript dependency — copy the output folder anywhere a static file server
can serve it. Nothing is uploaded anywhere by this script; treat the output
directory with the same privacy care as the wiki itself if you choose to host
it (see [Git remotes](#git-remotes) above).

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
  author: Jane Doe
--- text ---
Q2 Planning — Digital Collections

Present: Jane Doe, Jordan Smith, ...
[full extracted text...]
```

If the command returns an error or empty text, the file will likely land
in `raw_ingest/failed/` during a real run. Common causes:

| Problem | Cause | Fix |
|---------|-------|-----|
| Empty output from a PDF | Scanned image PDF with no text layer | Use `scripts/ocr.py` (documents route there automatically) |
| `PasswordError` | Encrypted PDF | Remove password protection before dropping |
| `PackageNotFoundError` | Missing dependency | Run `pip install -r scripts/requirements.txt` |

### `scripts/ocr.py`, `convert_document.py`, `document_ingest.py`, `ingest_document.py` — document conversion

`ingest_document.py` is the end-to-end entry point: it converts one PDF, Word
or HTML file to structured Markdown (`convert_document.py`), OCRs scanned pages
(`ocr.py`: Tesseract first, Claude vision as a per-page fallback), builds the
summary header and related-page links (`document_ingest.py`), writes
`wiki/documents/<slug>.md`, records the source in the manifest, and deletes the
original from `raw_ingest/`. `slug.py` is the shared slug helper.

```bash
python scripts/ingest_document.py raw_ingest/report.pdf
python scripts/ingest_document.py raw_ingest/old-article.md --already-markdown
python scripts/ocr.py path/to/scan.pdf --help     # OCR options
```

### `scripts/check_auth.py` / `llm.py` — Claude access

`check_auth.py` reports which backend is usable (`--call` makes one tiny real
request). `llm.py` is the only module that talks to Claude; see
[Claude backends](#claude-backends) and [AUTHENTICATION.md](AUTHENTICATION.md).

### `scripts/run_task.py` — run a task document on either backend

```bash
python scripts/run_task.py WIKI_UPDATE_TASK.md --dry-run
python scripts/run_task.py WIKI_UPDATE_TASK.md --backend api --prompt "..."
```

See [Running the task documents on either backend](#running-the-task-documents-on-either-backend).

### `scripts/agent_manifest.py` / `locking.py` — parallel-agent safety

```bash
python scripts/agent_manifest.py list
python scripts/agent_manifest.py check wiki/topics/q2-planning.md
python scripts/agent_manifest.py prune --hours 4
```

See [Concurrency and parallel agents](#concurrency-and-parallel-agents).

### `scripts/asana_manifest.py` — list Asana projects

```bash
python scripts/asana_manifest.py
```

Example output:
```
Project (gid)          Slug                                          Last ingested  Wiki page
----------------------------------------------------------------------------------------------------------
1234567890123456       metadata-standards-project                    2026-04-15     wiki/topics/metadata-standards-project.md
```

### `scripts/classify_ingest.py` — plan a parallel ingest dispatch

Before Stage 2 of the wiki update task processes `raw_ingest/`, this script
predicts which wiki page each unprocessed file targets and groups files into
work units — files that target the same page are bundled so a later write
can't clobber an earlier one; everything else can be dispatched as
independent, parallel subagent calls.

```bash
python scripts/classify_ingest.py           # JSON dispatch plan
python scripts/classify_ingest.py --text    # human-readable summary
```

### `scripts/build_index.py` — regenerate `wiki/INDEX.md`

Rebuilds the master index from current wiki content. Hand-written notes in
the existing Ingested Documents table are preserved; new manifest entries
are appended.

```bash
python scripts/build_index.py             # regenerate INDEX.md
python scripts/build_index.py --dry-run   # print stats, don't write
```

### `scripts/build_relevance_index.py` / `scripts/build_digest_registry.py` — email archive caches

Support the [email archive task](#email-archive-verbatim). Both cache an
expensive lookup (documented people/topics/orgs, and known recurring digest
senders, respectively) to a JSON file at the wiki root, and only rebuild when
their source content changes — safe to delete at any time.

```bash
python scripts/build_relevance_index.py --print   # rebuild if stale, print result
python scripts/build_digest_registry.py --test 'sender@example.com' 'Some Subject'
```

### `scripts/check_email_synthesis.py` / `record_email_synthesis.py` / `email_synthesis_manifest.py` — email synthesis pass

Support the optional synthesis pass of the email archive task:
`check_email_synthesis.py --days 60` lists archived emails not yet folded into
topic/people/organization pages (oldest first); `record_email_synthesis.py`
records resolutions in `.email_synthesis_manifest.json` in one locked write.

### `scripts/email_archive_helpers.py` — email quoting/parsing helpers

Strips quoted reply history from a Gmail thread's body text without losing
real content, and parses oversized `get_thread` responses that were saved to
a file instead of returned inline. Used internally by the email archive task
via Bash, not typically run standalone.

### `scripts/enrich_person.py` — fetch public profile info for a people page

Looks up an institutional directory page, Google Scholar profile, and
LinkedIn URL (URL only — content is never scraped, per LinkedIn's ToS) for a
person, and writes a structured file to `raw_ingest/` for the next wiki
update to synthesize into that person's page.

```bash
python scripts/enrich_person.py jordan-smith                 # use an existing people page
python scripts/enrich_person.py --name "Jordan Smith" \
    --email jsmith@example.edu --title "Director of Digital Initiatives"
```

### `scripts/fetch_urls.py` — fetch linked page content before ingest

Scans unprocessed `raw_ingest/` files for URLs, fetches publicly accessible
ones (skipping video-call links, authenticated Google/Microsoft docs,
social media, and non-content assets), and writes a sidecar `.md` file
Claude can use to enrich its analysis. Not run automatically — run it
manually before a wiki update when you want linked content included.

```bash
python scripts/fetch_urls.py --dry-run    # preview what would be fetched
python scripts/fetch_urls.py
```

### `scripts/summarize_transcripts.py` — pre-summarize large transcripts

Raw meeting/call transcripts are often 30–100KB of verbatim dialogue —
processing one directly fills the synthesis context window and degrades
quality for whatever else is in the same run. This script detects
large/transcript-like files, calls Claude (via `scripts/llm.py`) for a
structured ~1KB summary, and replaces the original with `*_summary.md` for Stage 2 to
process normally.

```bash
python scripts/summarize_transcripts.py             # process all eligible files
python scripts/summarize_transcripts.py --dry-run   # show what would change
```

### `scripts/ingest_takeout.py` — bulk-import a Google Takeout export

See [Alternative: bulk import from a Google Takeout export](#gmail-connector)
above.

### `scripts/generate_daily_entry.py` / `scripts/generate_todo.py` — optional standalone helpers

Two small utilities that call Claude through `scripts/llm.py` rather than
running inside your interactive session:

- `generate_daily_entry.py` turns one morning-briefing file into a dated
  `wiki/daily/` entry — the same synthesis the wiki update task's Stage 1
  does, callable standalone for testing or reprocessing a single day.
- `generate_todo.py` reads recent daily entries, topic pages, and (if
  present) `meeting-cadence.md`, and produces a prioritized to-do list
  organized by time horizon. Writes to `<wiki root>/logs/<YYYY-MM>/` by
  default; change it with `log_dir` in `config.local.json` or
  `MNEMOTRON_LOG_DIR`.

```bash
python scripts/generate_daily_entry.py raw_ingest/claude-briefings/morning-brief_2026-06-05.md
python scripts/generate_todo.py --dry-run   # gather context, show what would happen; no Claude call
python scripts/generate_todo.py --print     # call Claude, print the list instead of writing a file
```

**Convention:** `--dry-run` never calls Claude (in every script that has it). Where a script can also print instead of write, that is a separate `--print` flag.

Both work with either backend; see [Claude backends](#claude-backends) and the
[Anthropic API](#anthropic-api-direct-access) note on data handling.

---

## Customizing the pipeline

The `*_TASK.md` files are Claude's instructions (licensed GPL-3.0-or-later,
like the code). Edit them to change
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
| Email archive relevance gate / classification rules | `EMAIL_ARCHIVE_TASK.md` Stage 3 |
| Email archive lookback window / backfill chunking | `EMAIL_ARCHIVE_TASK.md` Configuration table |
| Briefing and Asana export formats | `ASANA_AND_BRIEFINGS.md` |
| Supported file extensions | `TEXT_EXTENSIONS` / `IMAGE_EXTENSIONS` in `scripts/config.py` |
| Your name, time zone, institution domains, directory URLs | `config.local.json` or `MNEMOTRON_*` variables (see the header of `scripts/config.py`) |
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
| Email archive | On demand only | Not scheduled — run manually when you want the archive brought up to date |

---

## Directory reference

```
mnemotron-wiki/
├── README.md                   ← you are here
├── AUTHENTICATION.md           ← Claude backends and credentials
├── LICENSE, LICENSES/, NOTICE.md  ← licensing and third-party notices
├── setup.sh                    ← one-time setup (folders, dependencies, backend check)
├── config.local.json           ← optional personal settings (git-ignored, never commit)
├── WIKI_UPDATE_TASK.md         ← main pipeline instructions for Claude
├── GMAIL_INGEST_TASK.md        ← Gmail connector instructions (optional)
├── CALENDAR_INGEST_TASK.md     ← Calendar connector instructions (optional)
├── EMAIL_ARCHIVE_TASK.md       ← verbatim email archive + synthesis pass (on-demand, optional)
├── ASANA_AND_BRIEFINGS.md      ← Asana exports and daily briefings (optional)
├── wiki_export.py              ← render the wiki to static HTML
├── .manifest.json              ← processed-file index (do not edit)
├── .asana_manifest.json        ← Asana project index (do not edit)
├── .calendar_manifest.json     ← calendar connector index (do not edit)
├── .gmail_manifest.json        ← Gmail connector index (do not edit)
├── .email_archive_manifest.json ← email archive task index (do not edit)
├── .email_synthesis_manifest.json ← email synthesis index (created on first use)
├── .relevance_index.json       ← cached people/topics/orgs lookup (do not edit)
├── .digest_registry.json       ← cached digest-source lookup (do not edit)
├── .gitignore
├── scripts/
│   ├── config.py               ← paths and personal settings
│   ├── llm.py                  ← the only module that calls Claude (cli / api backends)
│   ├── check_auth.py           ← diagnose Claude access
│   ├── locking.py              ← file locks, atomic and merge-on-save writes
│   ├── agent_manifest.py       ← page-claim protocol for parallel agents
│   ├── run_task.py             ← run a task document on the cli or api backend
│   ├── manifest.py             ← content-hash manifest library
│   ├── slug.py                 ← shared slug helper
│   ├── check_ingest.py         ← list unprocessed files
│   ├── extract_text.py         ← extract text from PDF, DOCX, HTML, etc.
│   ├── ocr.py                  ← OCR for scans (Tesseract, Claude vision fallback)
│   ├── convert_document.py     ← PDF/DOC/DOCX/HTML → structured Markdown
│   ├── document_ingest.py      ← header + page writer for wiki/documents/
│   ├── ingest_document.py      ← end-to-end document conversion
│   ├── classify_ingest.py      ← plan a parallel ingest dispatch
│   ├── build_index.py          ← regenerate wiki/INDEX.md
│   ├── asana_manifest.py       ← Asana project tracking (optional)
│   ├── ingest_asana_project.py ← Asana-specific ingest path (optional)
│   ├── ingest_takeout.py       ← bulk-import a Google Takeout export (optional)
│   ├── build_relevance_index.py    ← email archive cache: people/topics/orgs lookup
│   ├── build_digest_registry.py    ← email archive cache: digest-source lookup
│   ├── email_archive_helpers.py    ← email quoting/parsing helpers
│   ├── check_email_synthesis.py    ← list archived emails awaiting synthesis
│   ├── record_email_synthesis.py   ← record synthesis outcomes (single writer)
│   ├── email_synthesis_manifest.py ← synthesis manifest library
│   ├── enrich_person.py        ← fetch public profile info for a people page
│   ├── fetch_urls.py           ← fetch linked page content before ingest
│   ├── summarize_transcripts.py← pre-summarize large transcripts
│   ├── generate_daily_entry.py ← standalone daily-entry synthesis
│   ├── generate_todo.py        ← standalone to-do list generation
│   └── requirements.txt        ← Python dependencies
├── raw_ingest/
│   ├── claude-briefings/       ← morning briefing files
│   ├── asana/                  ← Asana project exports (optional)
│   ├── gmail/                  ← Gmail ingest output (optional)
│   ├── calendar/               ← Calendar ingest output (optional)
│   └── failed/                 ← extraction failures (quarantine)
└── wiki/
    ├── INDEX.md                ← auto-maintained table of contents
    ├── .agent-manifest.json    ← active page claims (runtime; git-ignored)
    ├── daily/                  ← dated journal entries
    ├── topics/                 ← project and concept pages
    ├── people/                 ← person dossiers
    ├── organizations/          ← organization pages
    ├── documents/              ← converted PDF / Word / HTML documents
    └── email/                  ← verbatim archived email (on-demand task)
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
| `.email_archive_manifest.json` | Email archive task |
| `.email_synthesis_manifest.json` | Email synthesis pass (via `record_email_synthesis.py`) |
| `wiki/.agent-manifest.json` | `agent_manifest.py` (page claims) |
| `.relevance_index.json` | Email archive task (derived cache — safe to delete) |
| `.digest_registry.json` | Email archive task (derived cache — safe to delete) |

---

## Relationship to the sibling tool

Mnemotron Wiki has a sibling, `mnemotron-wiki-r`, maintained separately.

- **This tool (personal)** builds a working-reference wiki: topics, people,
  organizations, converted documents, daily entries and email, from notes,
  transcripts, reports and optional connector data. It emphasizes ongoing
  relationships and projects.
- **The research tool (`mnemotron-wiki-r`)** normalizes heterogeneous research
  corpora (primary and secondary sources, scans, handwriting) into faithful
  source transcriptions plus synthesized topic and entity pages, with Internet
  Archive ingest, batch running, link synthesis and quality reports. It has no
  email, calendar, Asana, briefing, daily or to-do layer.

They share `scripts/llm.py`, `locking.py`, `agent_manifest.py`, `manifest.py`,
`check_auth.py`, `AUTHENTICATION.md`, the `raw_ingest/` drop-folder convention
and the license scheme, so improvements to those carry across. They
intentionally differ in wiki layout, task documents, and which scripts and
connectors they include.

---

## License

This project uses two licenses, chosen by what each file is.

| What | License |
|------|---------|
| Python and shell scripts (`.py`, `.sh`), and the Claude instruction documents (`WIKI_UPDATE_TASK.md`, `GMAIL_INGEST_TASK.md`, `CALENDAR_INGEST_TASK.md`, `EMAIL_ARCHIVE_TASK.md`, `ASANA_AND_BRIEFINGS.md`) — files whose purpose is to be executed or to instruct Claude | GPL-3.0-or-later |
| Documentation for people (`README.md`, `AUTHENTICATION.md`, `NOTICE.md`) | GFDL-1.3-or-later, no Invariant Sections, Front-Cover Texts or Back-Cover Texts |

Full texts are in `LICENSES/`; the scheme is described in `LICENSE`. Every
source file carries an SPDX identifier and an AI-assistance notice. The sample
pages under `wiki/` and the placeholder content in `raw_ingest/` are fictional
examples.

Third-party software and services this project calls (but does not bundle) are
listed in [NOTICE.md](NOTICE.md).

### AI assistance notice

This software was created with assistance from Claude Code (Claude Sonnet
5.5). It may not have been fully reviewed by a human. Users are responsible
for validating behavior in their own environments. No warranty is provided,
express or implied.

---

## Credits

**Author:** Patrick R. Wallace, Hamilton College LITS  
**Year:** 2026

Mnemotron Wiki was developed as a personal knowledge management tool for
AI-assisted institutional work environments.
