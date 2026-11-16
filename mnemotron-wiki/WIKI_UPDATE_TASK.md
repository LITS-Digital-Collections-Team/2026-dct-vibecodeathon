<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
This file is part of Mnemotron Wiki. See LICENSE for terms.

AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude Sonnet 5.5). It may not have been fully reviewed by a human; test it in your own environment before relying on it.
-->

# Mnemotron Wiki — Update Task

> Created with assistance from Claude Code (Claude Sonnet 5.5); may not have been fully reviewed by a human.

These are the instructions Claude follows when running a wiki update: turning
the files in `raw_ingest/` into topic pages, people and organization dossiers,
converted documents, and (optionally) daily entries. Run it on demand ("run the
wiki update task") or from a scheduler using headless Claude Code
(`claude -p`).

The material this wiki is built for is working material: notes, meeting
transcripts, email digests, calendar summaries, reports, PDFs and Word
documents. Output goes to `wiki/topics/`, `wiki/people/`,
`wiki/organizations/`, `wiki/documents/`, `wiki/daily/` and (if you use the
email archive) `wiki/email/`. For faithful source transcription of archival or
scholarly corpora, use the sibling research tool (`mnemotron-wiki-r`); this
document does not cover that workflow.

---

## Overview and what is optional

The update task has five stages, run in order. Only Stage 2 and Stage 3
are essential. Everything else can be skipped, and skipping it never breaks
the rest.

| Stage | Name | Required? | Needs |
|-------|------|-----------|-------|
| 0 | Pre-processing (summarise large transcripts) | Optional | A Claude backend (`scripts/llm.py`) |
| 1 | Briefing digest (daily entry) | Optional | A briefing file in `raw_ingest/claude-briefings/`; see `ASANA_AND_BRIEFINGS.md` |
| 2 | Document ingest (parallel work units) | Required | Local files in `raw_ingest/` |
| 3 | Index update | Required | Nothing external |
| 4 | Git commit | Optional | A git repository |

If `raw_ingest/claude-briefings/` is empty or does not exist, skip Stage 1 entirely. If
`raw_ingest/` has no large transcripts, Stage 0 exits immediately by itself.

Files placed in `raw_ingest/gmail/`, `raw_ingest/calendar/`, `raw_ingest/asana/` and
`raw_ingest/claude-briefings/` are produced by optional integrations (see
`README.md`). The core task works fine with none of them.

### How scripts reach Claude

Scripts that need a language model (`summarize_transcripts.py`,
`generate_daily_entry.py`, `ingest_document.py`, `build_index.py --use-api`,
and others) call it through `scripts/llm.py`. It uses either the headless
Claude Code CLI or the Anthropic API, chosen by the environment variable
`MNEMOTRON_BACKEND` (`cli`, `api` or `auto`). You do not need to do anything
about this beyond making sure one of the two works. If a script reports an
`LLMError`, fall back to the manual procedure given for that stage.
`python scripts/check_auth.py` diagnoses which backend is usable; see
`AUTHENTICATION.md` for credential options.

### Running headless

Everything below is written as concrete shell and Python commands so that an
agent without a human in the loop can execute it.

- Work from the wiki root (the directory containing this file); all paths are
  relative to it. Run scripts as `python scripts/<name>.py`.
- Do not stop to ask questions. When something is ambiguous, apply the rule
  stated in this document; if none applies, choose the conservative option
  (leave the file in place, log it under `## Ingest Errors`) and continue.
- Parallel work uses the agent/subagent facility of your runner (the Agent
  tool in Claude Code; a spawn-agent function in other runners). If your
  runner has none, process the same work units sequentially. The results are
  identical; it is only slower.
- Background agents need Edit/Write and basic shell permissions. See
  `setup.sh`, which writes a ready-made
  `.claude/settings.json` if none exists.
- At the end, print a short report: files ingested, pages created or updated,
  files moved to `raw_ingest/failed/`, and whether a commit was made.

---

## Paths

All paths are relative to the wiki root.

| Purpose | Path |
|---------|------|
| Drop zone (all unprocessed input) | `raw_ingest/` |
| Daily briefings (optional input) | `raw_ingest/claude-briefings/` |
| Asana exports (optional input) | `raw_ingest/asana/` |
| Calendar summaries (optional input) | `raw_ingest/calendar/` |
| Email digests (optional input) | `raw_ingest/gmail/` |
| Failed ingest quarantine | `raw_ingest/failed/` |
| Daily entries | `wiki/daily/` |
| Topic pages | `wiki/topics/` |
| People dossiers | `wiki/people/` |
| Organization dossiers | `wiki/organizations/` |
| Converted documents (PDF/DOC/DOCX/HTML) | `wiki/documents/` |
| Index | `wiki/INDEX.md` |
| Content-hash manifest | `.manifest.json` |
| Asana project manifest (optional) | `.asana_manifest.json` |
| Agent claim manifest (page ownership) | `wiki/.agent-manifest.json` |

Create any directory that does not yet exist the first time you need it.

---

## Scripts used by this task

| Script | Stage | Purpose |
|--------|-------|---------|
| `scripts/summarize_transcripts.py` | 0 | Replace large transcripts with compact structured summaries |
| `scripts/generate_daily_entry.py` | 1 | Briefing (+ optional Asana weekly) to a dated daily entry |
| `scripts/check_ingest.py` | 2 | List unprocessed files in `raw_ingest/` (never scans `failed/`) |
| `scripts/classify_ingest.py` | 2 | Build the parallel/sequential work-unit plan |
| `scripts/extract_text.py` | 2 | Print the plain text of one file (OCR for scans) |
| `scripts/ingest_document.py` | 2 | End-to-end PDF/DOC/DOCX/HTML to `wiki/documents/` |
| `scripts/ingest_asana_project.py` | 2 | Idempotent refresh of an Asana project topic page (optional) |
| `scripts/agent_manifest.py` | 2 | Claim and release wiki pages for exclusive ownership |
| `scripts/manifest.py` | 2 | `load_manifest`, `mark_processed`, `save_manifest` |
| `scripts/build_index.py` | 3 | Regenerate `wiki/INDEX.md` |
| `scripts/fetch_urls.py` | pre-2, manual | Optional: fetch public URLs referenced by ingest files |
| `scripts/enrich_person.py` | any, manual | Optional: gather public profile info for a person page |
| `scripts/generate_todo.py` | after, manual | Optional: prioritized to-do list from the wiki |

Supporting modules (`config.py`, `llm.py`, `convert_document.py`,
`document_ingest.py`, `slug.py`) are imported by the scripts above; you do not
call them directly except `convert_document.py <file>` for debugging.

---

## Stage 0: Pre-processing (optional)

Run from the wiki root:

```bash
python scripts/summarize_transcripts.py
# Preview only:
python scripts/summarize_transcripts.py --dry-run
```

The script scans `raw_ingest/` for large or transcript-like files (raw meeting
recordings, interview or coaching-session transcripts, any file whose name
contains `_transcript`, or a large file with dialogue-style timestamps) and
replaces each one with a compact structured `*_summary.md` file. The originals
are recorded in the manifest and deleted. The summaries then appear in
Stage 2's `check_ingest.py` output and are processed as ordinary ingest
documents. Files already named `*_summary*` are never re-summarised.

If no eligible files are present, the script exits immediately with no side
effects. The goal is to keep the synthesis context clean: a 30-50 KB verbatim
transcript becomes a roughly 1 KB structured summary before any wiki-writing
happens. Use `--threshold N` to change the byte threshold, or name specific
files to target them.

**Skip this stage** if you have no transcripts, or if you want verbatim
transcripts kept for synthesis. If the script fails, continue to Stage 1 or 2;
large transcripts will then be handled in context by Stage 2.

---

## Stage 1: Briefing digest (optional)

**Requires:** a daily briefing file in `raw_ingest/claude-briefings/` (any Markdown
summary of your day, produced by whatever tool you use), and optionally a
weekly Asana export in `raw_ingest/asana/`. See
`ASANA_AND_BRIEFINGS.md`. **If you have none, skip to Stage 2.**

Run from the wiki root:

```bash
python scripts/generate_daily_entry.py <briefing_file>
# With a weekly Asana summary:
python scripts/generate_daily_entry.py <briefing_file> \
    --asana-weekly raw_ingest/asana/asana-weekly-YYYY-MM-DD.md
# Auto-discover the most recent unprocessed briefing for today:
python scripts/generate_daily_entry.py --auto
# Choose a date explicitly:
python scripts/generate_daily_entry.py --auto --date YYYY-MM-DD
```

`<briefing_file>` is the most recent file in `raw_ingest/claude-briefings/` dated today.
For several unprocessed briefings (catching up on earlier days), run the
script once per briefing in chronological order.

The script handles everything automatically:

- Calls Claude to synthesise the daily entry at `wiki/daily/YYYY-MM-DD.md`.
- Detects a `## Relationship Pulse` section (if your briefing has one) and
  updates `wiki/topics/relationship-pulse.md` in a separate call.
- Marks the Asana weekly, if any, in the manifest and leaves the file in
  place as an archive.
- Marks the briefing in the manifest and deletes it.

If the script fails or is unavailable, use the **manual fallback** below.

### Manual fallback

1. Gather today's input files:
   a. **Briefing**: list `raw_ingest/claude-briefings/` by modification time, most
      recent first. Read the file or files dated today.
   b. **Weekly Asana summary**: list `raw_ingest/asana/` for
      `asana-weekly-*.md`. If one is dated today, read it.
2. If neither source has a file dated today, skip to Stage 2.
3. Determine today's date (`YYYY-MM-DD`) in the configured time zone
   (`TIMEZONE` in `scripts/config.py`, default UTC).
4. Check whether `wiki/daily/YYYY-MM-DD.md` already exists.
   - If it exists, append new content under a `## Update` heading with the
     current time, rather than overwriting.
   - If not, create it from the daily entry template below.
5. Synthesise the content into concise prose:
   - What were the key points of the briefing?
   - Which tracked tasks are active, overdue, or newly completed? (Draw from
     the briefing's task section and, if present, the weekly Asana summary.)
   - Does anything cross-reference existing topic pages? If so, add a
     `## Related Topics` section with links.
5b. **Relationship Pulse (only if present).** If the briefing has a
   `## Relationship Pulse` section, extract it and update
   `wiki/topics/relationship-pulse.md`:
   - For each person listed, update their row in the Status Table: set Last
     Contact, update Notes, and note any upcoming scheduled contact.
   - If a person has no row yet, add one.
   - Do NOT repeat the pulse in the daily entry. Mention only that it was
     updated, with a link: `Relationship Pulse updated - see
     [relationship-pulse](../topics/relationship-pulse.md).`
   - The relationship-pulse page is a live status board, not a task list.
     Its purpose is ambient awareness of recurring, low-novelty
     relationships that are at risk of being neglected because they are not
     urgent. Tone: factual and scannable; do not editorialise.
6. If a weekly Asana summary was consumed, mark it processed in the manifest
   so Stage 2 does not also convert it into a standalone topic page:

   ```python
   python - <<'EOF'
   import sys
   sys.path.insert(0, ".")
   from pathlib import Path
   from scripts.manifest import load_manifest, mark_processed, save_manifest

   filepath = Path("raw_ingest/asana/asana-weekly-YYYY-MM-DD.md")
   wiki_page = Path("wiki/daily/YYYY-MM-DD.md")
   manifest = load_manifest()
   manifest = mark_processed(filepath, wiki_page, manifest)
   save_manifest(manifest)
   print(f"Marked as processed: {filepath.name}")
   EOF
   ```

   Leave the file in `raw_ingest/asana/` as an archived record; do NOT delete it.
   The manifest entry is enough to keep Stage 2 from reprocessing it.

7. Mark the briefing processed in the manifest, then delete it (same pattern):

   ```python
   python - <<'EOF'
   import sys
   sys.path.insert(0, ".")
   from pathlib import Path
   from scripts.manifest import load_manifest, mark_processed, save_manifest

   filepath = Path("raw_ingest/claude-briefings/morning-brief_YYYY-MM-DD.md")
   wiki_page = Path("wiki/daily/YYYY-MM-DD.md")
   manifest = load_manifest()
   manifest = mark_processed(filepath, wiki_page, manifest)
   save_manifest(manifest)
   print(f"Marked as processed: {filepath.name}")
   EOF
   ```

   ```bash
   rm raw_ingest/claude-briefings/morning-brief_YYYY-MM-DD.md
   ```

   This prevents Stage 2 from re-ingesting the briefing as a standalone topic
   page.

### Daily entry template

```markdown
---
date: YYYY-MM-DD
sources:
  - [briefing filename]
  - [asana summary filename, if present]
---

# YYYY-MM-DD

## Briefing Summary

[Concise prose summary of the briefing: key themes, decisions, follow-ups
flagged. 2-5 sentences.]

## Tasks

[Summary of active and recently changed tasks. Group by project if helpful.
Note anything overdue or newly completed. Omit if there is no task data.]

## Related Topics

- [Link to topic page if applicable]
```

---

## Stage 2: Document ingest

**Note:** `check_ingest.py` never scans `raw_ingest/failed/`. Do not move files out
of that directory unless you intend to reprocess them manually.

**People and organizations:** When you meet content that names specific people
or organizations not yet in the wiki, create or update their dossier pages
(see "People and organizations" below) alongside any topic pages you produce.

### 2.0 Classify and plan

After Stages 0 and 1, get the full picture of what remains:

```bash
python scripts/classify_ingest.py --pretty
# Optional: let the LLM reclassify low-confidence items (uses scripts/llm.py)
python scripts/classify_ingest.py --pretty --use-api
```

Omit `--use-api` for a fast, deterministic, offline-only pass. (The flag name
is historical; it enables LLM-assisted classification through whichever
backend `llm.py` is configured to use.) `--text` prints a human-readable
summary instead of JSON.

The output JSON has these keys:

- **`parallel_units`**: each unit targets a distinct wiki page; units can be
  dispatched as concurrent agent calls.
- **`sequential_units`**: several files share one target page; process them
  as one group, in one agent (or in your own context).
- **`unclassified`**: low-confidence matches; treat like `sequential_units`.
- **`briefings`**: briefings already handled in Stage 1; ignore.

**Document-conversion files** (`.pdf`, `.doc`, `.docx`, `.odt`, `.html`,
`.htm`) are classified `type: "document-conversion"` and normally land in
`parallel_units`, because each source file maps to its own page in
`wiki/documents/` and nothing can conflict. They are handled entirely
differently from topic and people units (see 2.1). Do not run
`extract_text.py` or write a topic page for these; the dedicated script does
everything.

### 2.1 Parallel dispatch (for `parallel_units`)

For every unit in `parallel_units`, start an independent agent. Launch them
all at once; do not wait for one to finish before starting the next. (If your
runner cannot spawn agents, run the units one after another.)

**Exclusive page ownership.** The rule that makes parallelism safe: at any
moment, exactly one agent owns each wiki page it may write. The classifier
already groups files that target the same page into one unit. On top of that,
each agent claims its pages through the claim manifest before writing and
releases them at the end:

```bash
python scripts/agent_manifest.py check wiki/people/jane-doe.md          # non-zero exit = conflict, wait
python scripts/agent_manifest.py claim AGENT_ID "ingest: <short description>" \
    wiki/people/jane-doe.md wiki/topics/example-project.md
# ... do the work ...
python scripts/agent_manifest.py release AGENT_ID
```

Rules that follow from this:

- An agent writes only to pages it has claimed, plus the new pages it creates
  (claim those at creation). It must not edit a page owned by another unit.
- Dossier pages (people, organizations) for people who appear in files of
  several units are a common collision point. If an agent finds it needs to
  update a page that another live claim covers, it must not write to it.
  Instead it records the needed change under a `## Deferred Updates` note in
  its report, and the coordinator applies it after all agents finish.
- Agents never touch `wiki/INDEX.md` (Stage 3 owns it) or other agents'
  manifest entries.
- Stale claims from crashed agents are cleaned up with
  `python scripts/agent_manifest.py prune --hours 4`; run it before dispatch.
  `python scripts/agent_manifest.py list` shows current claims.

**Document-conversion units skip the template below entirely.** For a unit
with `type: "document-conversion"` (or any file ending in `.pdf`, `.doc`,
`.docx`, `.odt`, `.html`, `.htm`), the point is that neither you nor your
agents need to read the source file. Conversion, header synthesis, manifest
recording and deletion all happen inside one script call:

```bash
python scripts/ingest_document.py <filepath>
```

On success it prints the absolute path of the new page under
`wiki/documents/` and exits 0; nothing further to do for that file. On a
non-zero exit, the source file is left in place: move it to `raw_ingest/failed/`
and log it under `## Ingest Errors` in today's daily entry (or, if you keep no
daily entries, in your final report). Because each call is self-contained and
cheap, run several directly (not even via an agent) rather than spending an
agent dispatch on them. Reserve agents for units that require reading content
and judging which wiki page to update.

**Everything else** (topic and people units) uses the agent prompt below.

**Agent prompt template** (fill in the bracketed fields):

```
You are processing ingest files for the wiki at <WIKI_ROOT>. Your job: read
the ingest files, update the target wiki pages, record each file in the
manifest, and delete the source files. Work from the wiki root. Do not ask
questions; follow the rules below.

INGEST FILES:
[list each file path]

PREDICTED TARGET PAGES (read these first to understand current state):
[list each target page path]

OWNERSHIP: before writing, run
  python scripts/agent_manifest.py check <pages>
  python scripts/agent_manifest.py claim <AGENT_ID> "<description>" <pages>
Write only to pages you have claimed or newly created (claim new pages too).
If you need to change a page someone else owns, do not write it; report the
change under "Deferred updates". When finished, release:
  python scripts/agent_manifest.py release <AGENT_ID>
Never edit wiki/INDEX.md.

INSTRUCTIONS - follow Stage 2 (general path) and "People and organizations"
from WIKI_UPDATE_TASK.md:
- Run `python scripts/extract_text.py <filepath>` for each ingest file.
- Analyse the extracted text: what is the document about? Does an existing
  page need updating, or does this warrant a new page?
- Write or update the wiki page(s) using the topic-page or people-page
  templates from WIKI_UPDATE_TASK.md.
- Apply the People and Organizations rules: update or create dossier pages
  for any people or organizations that appear with meaningful content.
- Record each source file in the manifest:
    python - <<'EOF'
    import sys; sys.path.insert(0, ".")
    from pathlib import Path
    from scripts.manifest import load_manifest, mark_processed, save_manifest
    filepath = Path("<source_file>")
    wiki_page = Path("<wiki_page>")
    manifest = load_manifest()
    manifest = mark_processed(filepath, wiki_page, manifest)
    save_manifest(manifest)
    print(f"Marked: {filepath.name}")
    EOF
  (Only after the page write succeeded. Reload the manifest immediately
  before saving; other agents are writing it too.)
- Delete the source file: `rm <filepath>`
- If extraction fails, do NOT delete the file; report it as an error.
- Return a one-paragraph summary of the pages written or updated, any
  errors, and any deferred updates.
```

Collect the agents' reports. If any agent reports an extraction error, move
that file to `raw_ingest/failed/` and log it under `## Ingest Errors` in today's
daily entry. Apply any deferred updates yourself, then run
`python scripts/agent_manifest.py list` to confirm no claims remain.

### 2.2 Sequential processing (for `sequential_units` and `unclassified`)

Process these groups in your own context (or one agent per group), one group
at a time, using the same steps as the general path (extract, analyse,
write/update, manifest, delete). Because the files share target pages, they
must be handled by one context to avoid write conflicts.

### 2.3 Fallback: no classify output

If `classify_ingest.py` is unavailable or errors, fall back to a plain
sequential flow:

1. Run `python scripts/check_ingest.py`. It prints the paths of files in
   `raw_ingest/` not yet in the manifest (`failed/` is excluded).
2. If the output is empty, skip to Stage 3.
3. For each file, check its extension first. If it is `.pdf`, `.doc`, `.docx`,
   `.odt`, `.html` or `.htm`, use the **document-conversion path (3c)**.
   Otherwise decide whether it is an **Asana-project file** (3a) or a general
   file (3b).

#### 3a. Asana-project path (optional; only if you use the Asana integration)

A file is an Asana-project file if it is a `.md` file (normally under
`raw_ingest/asana/`) whose YAML front matter has `source: Asana` and a
`project_gid`. Weekly summaries (`asana-weekly-*.md`) are NOT Asana-project
files; they should already have been marked processed in Stage 1. If one
still shows up here because Stage 1 was skipped, treat it as a general file
and synthesise it as a topic page.

For Asana-project files use the dedicated helper instead of general
synthesis. It refreshes existing topic pages in place and preserves
user-authored content:

```bash
python scripts/ingest_asana_project.py <filepath>
```

The helper reads `project_gid` from the front matter, looks it up in
`.asana_manifest.json` (an index keyed by project id, distinct from the
content-hash `.manifest.json`), and:

- if the raw content is byte-identical to the cached copy from the last run,
  prints `unchanged: <wiki_page>` and writes nothing;
- otherwise writes or refreshes `wiki/topics/<slug>.md`. Only the content
  between `<!-- asana:auto-start -->` and `<!-- asana:auto-end -->` is
  replaced; anything outside (for example a hand-written `## Notes` section)
  is preserved verbatim;
- updates its cache (`scripts/.cache/asana/<project_gid>.md`) and the Asana
  manifest, then prints the absolute path of the topic page.

After the helper runs:

- If stdout starts with `unchanged:`, still record the raw file in the main
  manifest (so `check_ingest.py` will not list it again) and delete it.
- Otherwise treat the printed path as `<wiki_page_path>` and continue with
  sub-steps e and f of the general path below.
- On a non-zero exit, move the raw file to `raw_ingest/failed/` and log it under
  `## Ingest Errors`.

Skip sub-steps a and c-d of the general path for Asana-project files.

#### 3b. General path

For every other file:

a. Run `python scripts/extract_text.py <filepath>`. It prints extracted plain
   text (and any metadata) to stdout.
b. If there is an extraction error, move the file to quarantine and log it:
   ```bash
   mkdir -p raw_ingest/failed
   mv <filepath> raw_ingest/failed/
   ```
   Add a note under `## Ingest Errors` in today's daily entry (create the
   entry if it does not exist), skip the file and continue.
c. Analyse the text. Determine what the document is about; whether a topic
   page exists that it should merge into or it warrants a new page; and the
   3-5 key facts, findings or items worth retaining.
d. Write or update the topic page at `wiki/topics/<slug>.md` using the topic
   page template below.
e. Record the file in the manifest:

   ```python
   python - <<'EOF'
   import sys
   sys.path.insert(0, ".")
   from pathlib import Path
   from scripts.manifest import load_manifest, mark_processed, save_manifest

   filepath = Path("<filepath>")
   wiki_page = Path("<wiki_page_path>")
   manifest = load_manifest()
   manifest = mark_processed(filepath, wiki_page, manifest)
   save_manifest(manifest)
   print(f"Marked as processed: {filepath.name}")
   EOF
   ```

f. Delete the source file: `rm <filepath>`. Only do this after the manifest
   step succeeded. If the manifest step fails, leave the file so it is retried
   on the next run.

#### 3c. Document-conversion path (PDF/DOC/DOCX/HTML)

For `.pdf`, `.doc`, `.docx`, `.odt`, `.html`, `.htm`, run the dedicated script
instead of steps a-f:

```bash
python scripts/ingest_document.py <filepath>
```

This single call extracts the text (OCR for scanned PDFs, where OCR is
available), converts it to structured Markdown (headings, lists, tables; no
images or embedded objects), synthesises a short header (a 1-2 sentence
summary plus links to clearly related existing topic and people pages),
writes `wiki/documents/<slug>.md`, records the manifest entry and deletes the
source. On success it prints the absolute path of the new page. On a non-zero
exit, move the file to `raw_ingest/failed/` and log it under `## Ingest Errors`.

**Backfilling headerless legacy Markdown.** If a file in `raw_ingest/` is already
plain Markdown converted from a PDF by some other means (no front matter, no
summary or related-links header, just the article body), pass
`--already-markdown` to skip conversion and only add the header:

```bash
python scripts/ingest_document.py <filepath> --already-markdown
```

### Optional pre-steps before Stage 2

- **Fetch referenced URLs.** If ingest files cite public web pages that you
  want considered, run `python scripts/fetch_urls.py` (all unprocessed files),
  `--file PATH` (one file), or `--dry-run` (list URLs only). It writes sidecar
  `.md` files with the fetched content. It is never run automatically; it
  skips video-conference links, authenticated documents, social networks and
  non-content assets. Skip it if you do not want network access.
- **Enrich a person.** `python scripts/enrich_person.py <slug>` (or
  `--name "Jane Doe" --email jdoe@example.edu --title "Librarian" --org
  "Example University"`) gathers public profile information for a person.
  By default it writes an ingest file for the next run to synthesise into the
  person's Read, Observed Patterns and Signals sections; with `--synthesize`
  it updates the Profile section and front matter of an existing
  `wiki/people/<slug>.md` directly. `--dry-run`, `--no-scholar` and
  `--no-linkedin` limit what it does. It needs network access and is purely
  optional.

### Topic page template

```markdown
---
updated: YYYY-MM-DD
sources:
  - [filename of source document]
tags:
  - [relevant tag]
---

# [Topic Title]

## Summary

[2-4 sentence overview of the topic.]

## Key Points

[Prose paragraphs covering the main content. Avoid excessive bullet lists;
write in complete sentences where possible.]

## Source Documents

| Document | Date Ingested | Notes |
|----------|--------------|-------|
| [filename] | YYYY-MM-DD | [brief note] |

## Related Topics

- [Links to other topic pages if applicable]
```

---

## People and organizations

As you process documents in Stage 2, maintain dossier pages for the people and
organizations that appear in the source material. "The owner" below means the
person whose wiki this is: the author of the notes and the person whose
working relationships the wiki tracks. Write their perspective in the first
person singular (or "the owner" if the wiki has several contributors),
consistently within a wiki.

### When to create or update a page

- **Create** a page when a person or organization appears in source material
  and no page yet exists for them.
- **Update** an existing page when new interactions, topics or facts emerge
  (a new meeting, a change of role, a new collaboration).
- **Update the Read** whenever new sources reveal a meaningful shift in how
  the owner experiences or assesses this person. Be honest about impressions
  that are uncomfortable or uncertain. Add a Revisions entry when the new Read
  contradicts a prior one.
- **Update Observed Patterns** when new sources add behavioural facts not
  already captured. Note the source channel (`[email]`, `[journal]`,
  `[meeting]`, `[chat]`, `[calendar]`) for each significant observation.
  Contradiction between channels (for example professional in email, avoidant
  in the journal) is itself worth noting.
- **Update Signals** when a new pattern of friction, alignment or useful
  dynamic emerges. Signals must be operationally useful: things the owner
  should have in mind before a meeting or interaction. Omit neutral facts that
  do not affect the working relationship. Aim for 3-8 bullets.
- **Add a Revisions entry** whenever new information contradicts something
  already on the page: a changed position, corrected fact or revised
  impression. Do not silently overwrite prior content that tells a different
  story; log what changed and why.
- You need not create pages for every name mentioned in passing. Focus on
  people and organizations with a meaningful ongoing relationship to the
  owner's work.
- When substantially updating an older page, migrate it to the current
  template: split any "Personal Overview" section into Your Read and Observed
  Patterns, add Signals and Revisions sections, and add a Source column to the
  Interactions table.
- **Privacy.** These pages can hold candid, sensitive impressions. Keep the
  wiki private, and do not copy raw private material (full emails, medical or
  disciplinary details) into pages; summarise only what the owner needs for
  working relationships.

### People pages

Location: `wiki/people/<firstname-lastname>.md`

Use this template. Omit any section with no known content yet.

```markdown
---
name: "Jane Doe"
email: jdoe@example.edu           # omit if unknown
title: "Job Title"                # omit if unknown
department: "Department"          # omit if unknown
organization: "Example University"
relationship: direct-report | supervisor | colleague | external | vendor
updated: YYYY-MM-DD
---

# Jane Doe

## Profile

[1-2 sentence description of who they are and their relevance to the owner's
work.]

## Your Read

[The owner's own interpretation of this person: how they read to the
owner, gut-level impressions, things the owner finds admirable or difficult,
concerns carried about the relationship. Write explicitly from the owner's
perspective, in the second person ("You've found...", "You're wary of..."). Be
honest about discomfort and uncertainty; do not sanitise into a neutral
professional summary. Update when the owner's view meaningfully changes; add a
Revisions entry if it contradicts a prior one. For new pages, omit this
section if there is insufficient data for a genuine assessment.]

## Observed Patterns

[Factual behavioural observations drawn from sources. Note the channel in
brackets for each significant observation: [email], [journal], [meeting],
[chat], [calendar]. Channel matters: email shows curated communication;
journals capture unfiltered reactions; transcripts show real-time behaviour.
When the same person appears differently across channels, note that tension.
These are things that happened or were said, not interpretations. For new
pages, populate as source data allows.]

## Signals

[Operationally useful watch items: power dynamics, communication preferences,
sensitivities, things that have caused friction, things that have worked
well. Aim for 3-8 bullets. Good signals help the owner prepare before a
meeting or interaction. Omit neutral facts that do not affect the working
relationship. Update as new patterns emerge. Omit the section entirely if the
page is new and data is insufficient.]

## Working Relationship

[Nature of the relationship, how they interact, what projects or initiatives
they share. 2-4 sentences.]

## Topics

[Bulleted list of specific subjects discussed, collaborated on or relevant to
this person. One line each.]

## Interactions

| Date | Context | Source |
|------|---------|--------|
| YYYY-MM-DD | [Brief note on the meeting, event or exchange] | [email/meeting/journal/chat] |

## Revisions

| Date | What changed | Why |
|------|-------------|-----|
| YYYY-MM-DD | [What was updated or corrected] | [What new information contradicted or superseded prior content] |

## Related Topics

- [Link to topic page if applicable]
```

**Relationship values:**

- `direct-report`: reports to the owner
- `supervisor`: the owner's supervisory chain
- `colleague`: peer inside the owner's own organization; no reporting line
- `external`: outside the organization (peer institutions, consultants,
  collaborators)
- `vendor`: external service provider

### Source channels

When writing Observed Patterns and Interactions, note the source channel in
brackets. In priority order of reliability for the owner's internal state and
for candid behaviour:

- `[journal]`: the owner's unfiltered work journal; highest signal for their
  internal state and unguarded reactions
- `[meeting]`: meeting transcript or notes; shows real-time behaviour
- `[chat]`: chat tools; informal, often candid
- `[email]`: curated communication; note when it conflicts with the journal
- `[calendar]`: attendance, scheduling, pattern of cancellations

When observations from different channels conflict, note the conflict
explicitly rather than averaging or omitting one. Channel disagreement is
often the most informative observation. Only use channels the wiki actually
has material for.

### Organization pages

Location: `wiki/organizations/<slug>.md`

Use this template. Sections can be omitted if not yet applicable.

```markdown
---
name: "Short Name"
full_name: "Full Legal or Official Name"  # omit if same as name
abbreviation: "ABC"                        # omit if none
organization_type: division | team | department | external-vendor | peer-institution | other
parent: "Parent Org Name"                  # omit if none / unknown
relationship: internal | vendor | peer | external
updated: YYYY-MM-DD
---

# Organization Name

## Profile

[1-2 sentences describing what the organization is and its relevance to the
owner's work.]

## Structure (optional)

[Relevant sub-units, teams or reporting lines.]

## Key People

| Name | Role | Relationship |
|------|------|-------------|
| [Jane Doe](../people/jane-doe.md) | Title | colleague / direct report / etc. |

## Active Work Areas (optional)

[Bullets covering current projects or initiatives.]

## Related Topics

- [Link to topic page]
```

### Index note for Stage 3

After creating or updating people and organization pages, Stage 3 must list
them: all files in `wiki/people/` alphabetically by last name in the People
table, and all files in `wiki/organizations/` alphabetically in the
Organizations table.

---

## Stage 3: Index update

Run from the wiki root:

```bash
python scripts/build_index.py
# Use the LLM to write summaries for pages lacking a ## Summary section:
python scripts/build_index.py --use-api
# Print stats without writing:
python scripts/build_index.py --dry-run
```

The script regenerates all structural sections of `wiki/INDEX.md` (Daily
Entries, Topics, People, Organizations, Documents) from the current wiki files,
and appends new manifest entries to the Ingested Documents table while
preserving existing rows and their hand-written notes. If the script
fails, use the manual fallback.

### Manual fallback

1. List `wiki/daily/` by date, newest first. Add each to the Daily Entries
   table with a one-sentence summary from its `## Briefing Summary`.
2. List `wiki/topics/` alphabetically. Add each to the Topics table with a
   one-sentence description from its `## Summary`.
3. List `wiki/people/` alphabetically by last name. Add each to the People
   table with title, organization and relationship from its front matter.
4. List `wiki/organizations/` alphabetically. Add each to the Organizations
   table with a one-line description.
5. Read `.manifest.json` and populate the Ingested Documents table with
   filename, processed date and wiki page.

---

## Stage 4: Git commit (optional)

**Requires:** the wiki directory is a git repository. Otherwise skip.

From the wiki root:

```bash
git add wiki/ .manifest.json
# Only if you use the Asana integration:
[ -f .asana_manifest.json ] && git add .asana_manifest.json
git commit -m "wiki update $(date +%Y-%m-%d)"
```

If there are no changes, skip the commit and say so in your report. Do not
push unless explicitly told to.

---

## Checklist for a complete run

- [ ] Stage 0 run (or deliberately skipped); no large transcripts remain.
- [ ] Stage 1 run if briefings exist; briefing marked processed and removed;
      weekly Asana summary marked processed and left in place.
- [ ] `classify_ingest.py` plan obtained (or the `check_ingest.py` fallback
      used).
- [ ] Every unit dispatched exactly once; every agent claimed and released its
      pages; no claims remain in `agent_manifest.py list`.
- [ ] Every ingested file is in `.manifest.json` and removed from `raw_ingest/`;
      every failed file is in `raw_ingest/failed/` and logged under
      `## Ingest Errors`.
- [ ] Deferred updates from agents applied.
- [ ] New people and organizations have pages; updated ones have a Revisions
      entry wherever new information contradicted old.
- [ ] Front matter is valid YAML on every page touched.
- [ ] `build_index.py` run; `wiki/INDEX.md` lists all pages.
- [ ] Commit made (or skipped with reason).
- [ ] Final report printed.

---

## Notes on tone and style

- Write wiki pages in plain prose, not bullet lists, unless tabular or list
  structure genuinely aids comprehension.
- Prefer concise, factual language appropriate for a personal reference
  document.
- Use relative links between wiki pages (`[Topic](../topics/slug.md)`) so the
  wiki remains portable.
- Front matter (the `---` block at the top of each file) is YAML and must be
  valid YAML. Quote values that contain colons.
- Do not delete or overwrite existing topic page content without good reason;
  prefer appending or updating clearly marked sections.
- Asana-sourced topic pages wrap their auto-generated content in
  `<!-- asana:auto-start -->` and `<!-- asana:auto-end -->` HTML comments.
  Everything between those markers is replaced on every refresh by
  `ingest_asana_project.py`; everything outside (including any hand-written
  `## Notes` section) is preserved. Keep hand-written notes outside the
  markers so they survive future runs.
- `wiki/documents/` pages preserve only text content and structural metadata
  (headings, lists, tables) from their source file: never images or other
  embedded or linked objects, and no styling beyond what marks document
  structure. They are reference material, not synthesised prose; do not
  rewrite the body. Only the header (summary plus related links) is
  wiki-authored.
- Dates use `YYYY-MM-DD`, in the configured time zone (`TIMEZONE` in
  `scripts/config.py`).
- Never put credentials, tokens or private keys in wiki pages.
