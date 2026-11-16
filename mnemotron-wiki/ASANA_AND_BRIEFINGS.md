<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
This file is part of Mnemotron Wiki. See LICENSE for terms.

AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude Sonnet 5.5). It may not have been fully reviewed by a human; test it in your own environment before relying on it.
-->

# Asana Projects and Daily Briefings — Optional Inputs

> Created with assistance from Claude Code (Claude Sonnet 5.5); may not have been fully reviewed by a human.

This document covers two optional inputs to the wiki update task
(`WIKI_UPDATE_TASK.md`): **project-management exports** (written for Asana,
adaptable to any tracker) and **daily briefings**, plus two helper scripts
that consume them.

**Requires:** nothing for the scripts themselves beyond local files and a
working Claude backend (`scripts/llm.py`). To *produce* the input files you
need either (a) a connector or export for your task tracker, and/or (b)
something that writes a daily Markdown summary of your day, or you can write
those files by hand. **If you have neither, skip this document.** The core
wiki works without them.

How to skip: leave `raw_ingest/asana/` and `raw_ingest/claude-briefings/` empty or absent.
Stage 1 of the update task is skipped when there are no briefings, and
Stage 2 simply has no Asana-project files to route.

---

## Part A: Project exports (Asana)

### What it does

A project export is a Markdown file describing the live state of one project:
its tasks, status and recent activity. Unlike a one-off document, a project
export is an *idempotent snapshot*. Re-exporting it next week should update
the existing topic page, not create a duplicate. `scripts/ingest_asana_project.py`
provides that behaviour, using a second manifest keyed on the project's stable
id instead of the content hash.

### Producing the input

Any method that yields a Markdown file with the front matter below works: a
Claude session with a task-tracker connector, a script you write against the
tracker's API, or editing by hand. Place the file in `raw_ingest/asana/`.

```markdown
---
source: Asana
project_gid: "1200000000000000"      # stable project id; REQUIRED
title: "Example Project"             # becomes the topic title and slug
permalink: "https://app.example.com/projects/1200000000000000"
created_at: "2026-01-15"
tasks_total: 42
tasks_complete: 30
tasks_incomplete: 12
current_status: "On track"
---

# Example Project

(tasks, sections, recent activity... free-form Markdown)
```

Only `source: Asana` and `project_gid` are essential (the stage 2 routing
rule is "a `.md` file whose front matter has `source: Asana` and a
`project_gid`"); the other fields are shown in the topic page's header when
present. If you use a different tracker, keep `source: Asana` and any stable
unique id in `project_gid` so the helper recognises the file, or adapt the
script.

Generation tip for an agent: list the projects the owner cares about, and for
each write one file named `<short-project-slug>.md` into `raw_ingest/asana/`.
Overwrite the previous export of the same project; the helper compares it to
its cache.

### Ingesting: `scripts/ingest_asana_project.py`

```bash
python scripts/ingest_asana_project.py raw_ingest/asana/example-project.md
```

Behaviour:

1. Parses the front matter; fails (exit 1) if there is none or no
   `project_gid`.
2. Looks the id up in `.asana_manifest.json`.
3. If the raw content is byte-identical to the cached copy in
   `scripts/.cache/asana/<project_gid>.md`, prints `unchanged: <wiki_page>`
   and touches nothing.
4. Otherwise writes or refreshes `wiki/topics/<slug>.md`:
   - page has the markers `<!-- asana:auto-start -->` and
     `<!-- asana:auto-end -->`: only the content between them is replaced;
   - page exists but has no markers: the refreshed snapshot is appended;
   - page does not exist: a new page is created.
5. Updates the cache and `.asana_manifest.json`, then prints the page path.

Exit codes: `0` success (path or `unchanged:`), `1` error.

After a successful run, record the raw file in the main manifest
(`scripts.manifest.mark_processed`) and delete it, exactly as in the general
path of the update task (this is what keeps `check_ingest.py` from listing
it again). On exit `1`, move the file to `raw_ingest/failed/`. Keep hand-written
notes (for example a `## Notes` section) *outside* the markers.

`scripts/asana_manifest.py` is the supporting module (load/save the
manifest, look up a project, read and write the cache). You do not run it
directly.

### Weekly summaries

A file named `asana-weekly-YYYY-MM-DD.md` in `raw_ingest/asana/` is treated as a
*weekly summary* of tracked work across projects, not a project snapshot. It
is consumed by the briefing step (Part B, `--asana-weekly`), marked processed
in the manifest, and left in place as an archive. It has no required front
matter; write it as a concise Markdown list of active, overdue and newly
completed tasks.

### Using a different tracker

Nothing in the wiki depends on Asana specifically. For Jira, Linear, Trello,
GitHub Projects and so on, produce the same style of file (stable id in
`project_gid`, `source: Asana` or a small edit of the script's check) or skip
the helper and let the file be ingested as an ordinary topic by the general
path. The weekly-summary path works with any Markdown file.

---

## Part B: Daily briefings

### What it does

A *briefing* is a Markdown file summarising one day: what is on the calendar,
what email needs attention, what tasks are due, and optionally a
*Relationship Pulse* (status of recurring, low-urgency relationships).
`scripts/generate_daily_entry.py` turns it into a dated wiki entry at
`wiki/daily/YYYY-MM-DD.md`, so the wiki has a running daily log. The task
also (Stage 1 of the update task) marks the briefing processed and deletes
it, so it is not re-ingested as an ordinary topic.

### Producing the input

Anything that writes a Markdown file to `raw_ingest/claude-briefings/` named
`morning-brief_YYYY-MM-DD.md` works: a scheduled Claude run, another tool,
or you. The file needs no particular structure. The script synthesises
whatever it contains; sections it recognises:

- a heading containing `Relationship Pulse` (any heading level, optional
  emoji prefix): extracted and merged into
  `wiki/topics/relationship-pulse.md` as a status table, not repeated in the
  daily entry;
- any task or tracker section: summarised under `## Tasks` in the entry.

The `morning-brief_` prefix matters for `--auto` discovery. If your tool uses
another name, pass the file path explicitly instead of `--auto`.

### Running: `scripts/generate_daily_entry.py`

```bash
python scripts/generate_daily_entry.py raw_ingest/claude-briefings/morning-brief_2026-01-05.md
python scripts/generate_daily_entry.py raw_ingest/claude-briefings/morning-brief_2026-01-05.md \
    --asana-weekly raw_ingest/asana/asana-weekly-2026-01-05.md
python scripts/generate_daily_entry.py --auto               # newest unprocessed briefing
python scripts/generate_daily_entry.py --auto --date 2026-01-05
```

- If `wiki/daily/<date>.md` already exists, the script appends an `## Update`
  section instead of overwriting.
- It calls Claude through `scripts/llm.py`. Failures fall back to the manual
  procedure in Stage 1 of `WIKI_UPDATE_TASK.md`.
- The briefing date comes from the filename; `--date` overrides it.
- `--auto` with nothing to do prints "No unprocessed briefing files found."
  and exits 0, so it is safe to call unconditionally in a scheduled job.

### Optional: to-do generation, `scripts/generate_todo.py`

Reads recent daily entries, the day's briefing (if any), the meeting-cadence
topic and selected topic pages, then asks Claude for a prioritised to-do list
and writes it to a file.

```bash
python scripts/generate_todo.py                       # today
python scripts/generate_todo.py --date 2026-01-05
python scripts/generate_todo.py --dry-run             # show plan; no Claude call, no file
python scripts/generate_todo.py --print               # call Claude, print the list, do not write
python scripts/generate_todo.py --output todo.md      # choose the output file
python scripts/generate_todo.py --include-asana       # include tracker tasks (off by default)
python scripts/generate_todo.py --topics example-project other-topic
```

It is a convenience for people who keep daily entries and is independent of
the ingest pipeline: nothing in the wiki task requires it. The default output
location is set in the script's configuration; use `--output` to override it.
The topics always included as context are a configuration list in the script;
edit that list to name your own pages.

---

## Choosing what to run

| You have | Do |
|----------|----|
| Only local files | Skip this document entirely |
| A daily summary tool | Part B; run Stage 1 of the update task |
| A task tracker | Part A; optionally also write a weekly summary |
| Both | Run Part B with `--asana-weekly` on the day the weekly file is dated |
