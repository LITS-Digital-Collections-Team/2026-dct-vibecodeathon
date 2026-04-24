# Mnemotron Wiki — Update Task

Instructions for Claude when running a wiki update. Can be triggered on demand
("run the wiki update task") or scheduled as an automated task.

---

## Overview

The wiki update task runs in four stages:

1. **Briefing digest** — Synthesize today's morning briefing (from
   `raw_ingest/claude-briefings/`) and any weekly Asana summary (from
   `raw_ingest/asana/`) into a dated daily entry.
2. **Document ingest** — Process any remaining new files in `raw_ingest/`
   into topic pages.
3. **Index update** — Regenerate `wiki/INDEX.md` to reflect all current
   content.
4. **Git commit** — Commit all changes with a dated message.

**Optional connectors** (Gmail, Google Calendar, Asana) feed into
`raw_ingest/` and are processed by Stage 2. They are configured separately;
see the connector task files if enabled.

---

## Paths

All paths are relative to the wiki root (the directory containing this file).

| Purpose | Path |
|---------|------|
| Wiki root | *(this directory)* |
| Morning briefings | `raw_ingest/claude-briefings/` |
| Asana summaries | `raw_ingest/asana/` |
| Gmail ingest output | `raw_ingest/gmail/` |
| Calendar ingest output | `raw_ingest/calendar/` |
| Failed ingest quarantine | `raw_ingest/failed/` |
| Daily entries | `wiki/daily/` |
| Topic pages | `wiki/topics/` |
| People pages | `wiki/people/` |
| Organization pages | `wiki/organizations/` |
| Main index | `wiki/INDEX.md` |
| Content manifest | `.manifest.json` |
| Asana project manifest | `.asana_manifest.json` |

---

## Stage 1: Briefing Digest

1. Check `raw_ingest/claude-briefings/` for a file dated today. Check
   `raw_ingest/asana/` for a weekly summary (`asana-weekly-*.md`) dated
   today (Mondays only).
2. If neither exists, skip to Stage 2.
3. Determine today's date (YYYY-MM-DD). Check whether `wiki/daily/YYYY-MM-DD.md`
   already exists.
   - If it exists, append under a `## Update` heading with the current time.
   - If not, create it using the template below.
4. Synthesize content from both sources into concise prose.
5. Mark the weekly Asana summary (if consumed) as processed in `.manifest.json`
   so Stage 2 does not reprocess it. Leave the file in place.
6. Mark the briefing file as processed in `.manifest.json`, then delete it.

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

[Concise prose summary — key themes, decisions, follow-ups. 2–5 sentences.]

## Asana

[Summary of active and recently changed tasks. Group by project if helpful.
Note anything overdue or newly completed.]

## Related Topics

- [Link to topic page if applicable]
```

### Marking files processed (run from wiki root)

```python
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from pathlib import Path
from scripts.manifest import load_manifest, mark_processed, save_manifest

filepath = Path("raw_ingest/claude-briefings/morning-brief_YYYY-MM-DD.md")
wiki_page = Path("wiki/daily/YYYY-MM-DD.md")
manifest = load_manifest()
manifest = mark_processed(filepath, wiki_page, manifest)
save_manifest(manifest)
print(f"Marked: {filepath.name}")
EOF
```

---

## Stage 2: Document Ingest

**Note:** `check_ingest.py` never scans `raw_ingest/failed/`. Do not move
files out of that directory unless you intend to manually reprocess them.

**People and organizations:** When you encounter content naming specific
people or organizations not yet in the wiki, create or update their dossier
pages (see Stage 2b below) alongside any topic pages.

1. Run: `python scripts/check_ingest.py`
   Prints paths of files in `raw_ingest/` not yet in the manifest.
2. If the output is empty, skip to Stage 3.
3. For each file, decide whether it is an **Asana-project file** (see 3a)
   or a **general file** (see 3b).

   An Asana-project file has `source: Asana` and a `project_gid` in its
   YAML frontmatter AND lives under `raw_ingest/asana/`. Weekly Asana
   summaries (`asana-weekly-*.md`) are NOT Asana-project files.

   *(Asana connector is optional. If not using Asana, all files follow the
   general path.)*

### 3a. Asana-project path

```bash
python scripts/ingest_asana_project.py <filepath>
```

- If stdout starts with `unchanged:` — mark in manifest, delete raw file, done.
- Otherwise — treat printed path as `<wiki_page_path>`, proceed to steps e–f below.
- On non-zero exit — move file to `raw_ingest/failed/`, log under `## Ingest Errors` in today's daily entry.

### 3b. General path

For every non-Asana file:

a. Run: `python scripts/extract_text.py <filepath>`  
   If extraction fails, move to `raw_ingest/failed/` and log the error.

b. Analyze the extracted text:
   - What is this document about?
   - Does a topic page already exist to merge into, or does it need a new page?
   - What are the 3–5 key facts worth retaining?

c. Write or update the topic page at `wiki/topics/<slug>.md`.

d. Mark the file in the manifest:

```python
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from pathlib import Path
from scripts.manifest import load_manifest, mark_processed, save_manifest

filepath = Path("<filepath>")
wiki_page = Path("<wiki_page_path>")
manifest = load_manifest()
manifest = mark_processed(filepath, wiki_page, manifest)
save_manifest(manifest)
print(f"Marked: {filepath.name}")
EOF
```

e. Delete the source file: `rm <filepath>`  
   Only after the manifest step succeeds.

### Topic page template

```markdown
---
updated: YYYY-MM-DD
sources:
  - [source filename]
tags:
  - [tag]
---

# Topic Title

## Summary

[2–4 sentence overview.]

## Key Points

[Prose paragraphs. Avoid bullet lists where prose works better.]

## Source Documents

| Document | Date Ingested | Notes |
|----------|--------------|-------|
| [filename] | YYYY-MM-DD | [note] |

## Related Topics

- [Links to other pages]
```

---

## Stage 2b: People and Organizations

Maintain dossier pages as you process documents.

### When to create or update

- **Create** a new page when a person or organization appears in source
  material and no page yet exists.
- **Update** an existing page when new interactions, topics, or facts emerge.
- **Update the Personal Overview section** whenever new email, journal, or
  calendar data meaningfully changes the picture of who someone is or how
  they work. The Personal Overview is cumulative — reflect the full pattern
  of interactions, not just the most recent.
- Do not create pages for every name mentioned in passing. Focus on people
  with a meaningful ongoing relationship to your work.

### People page template

File: `wiki/people/<firstname-lastname>.md`

```markdown
---
name: "Full Name"
email: email@domain.edu
title: "Job Title"
department: "Department"
organization: "Organization"
relationship: direct-report | supervisor | colleague | external | vendor | self
updated: YYYY-MM-DD
---

# Full Name

## Profile

[1–2 sentences: who they are and their relevance to your work.]

## Personal Overview

[3–6 sentences synthesizing this person's distinguishing characteristics,
communication style, working habits, and character as revealed by journals,
email, and calendar data. Write this as an interpretive summary — not a list
of facts — that helps you quickly recall who this person is and how to work
with them effectively.]

## Working Relationship

[Nature of the relationship, how you interact, shared projects. 2–4 sentences.]

## Topics

- [Subject or project they are involved in]

## Interactions

| Date | Context |
|------|---------|
| YYYY-MM-DD | [Brief note on the meeting, event, or exchange] |

## Related Topics

- [Links to topic pages]
```

### Organization page template

File: `wiki/organizations/<slug>.md`

```markdown
---
name: "Short Name"
full_name: "Full Legal Name"
organization_type: division | team | department | external-vendor | peer-institution | other
relationship: internal | vendor | peer | external
updated: YYYY-MM-DD
---

# Organization Name

## Profile

[1–2 sentences: what it is and its relevance to your work.]

## Key People

| Name | Role | Relationship |
|------|------|-------------|
| [Name](../people/name.md) | Title | colleague / direct report / etc. |

## Related Topics

- [Links]
```

---

## Stage 3: Index Update

Rewrite `wiki/INDEX.md`:

1. **Daily entries** — list all files in `wiki/daily/`, newest first.
2. **Topics** — list all files in `wiki/topics/`, alphabetically.
3. **People** — list all files in `wiki/people/`, alphabetically by last name.
4. **Organizations** — list all files in `wiki/organizations/`, alphabetically.
5. **Ingested Documents** — read `.manifest.json` and list filename, date, and wiki page.

---

## Stage 4: Git Commit

```bash
git add wiki/ .manifest.json .asana_manifest.json
git commit -m "wiki update $(date +%Y-%m-%d)"
```

If nothing has changed since the last run, skip the commit.

---

## Style notes

- Write wiki pages in plain prose, not bullet lists, unless list structure
  genuinely aids comprehension.
- Prefer concise, factual language appropriate for a personal reference document.
- Use relative links between wiki pages (`[Topic](../topics/slug.md)`) so the
  wiki stays portable.
- Frontmatter is YAML and must be valid. Quote date strings.
- Do not delete or overwrite existing topic content without good reason.
  Prefer appending or updating clearly marked sections.
- Asana topic pages wrap auto-generated content in
  `<!-- asana:auto-start -->` / `<!-- asana:auto-end -->` markers.
  Content outside those markers is preserved across refreshes.

---

*Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS.
Licensed under the GNU Free Documentation License, Version 1.3 or any later
version; with no Invariant Sections, no Front-Cover Texts, and no Back-Cover
Texts. See README.md for full license terms.*
