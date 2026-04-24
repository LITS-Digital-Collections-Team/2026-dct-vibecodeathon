# Mnemotron Wiki — Calendar Ingest Task

**Optional connector.** Only needed if you want to pull meeting and event
information from Google Calendar into your wiki. Requires the Google Calendar
MCP connector configured in Claude.

This task reads upcoming and recent calendar events, identifies professionally
relevant meetings and patterns, and writes structured markdown to
`raw_ingest/calendar/` for the wiki update task to process.

---

## What this task does — and does not do

**Calendar data is structural, not substantive.**

This task records *who meets with whom*, *how often*, and *what is coming up*.
It does NOT record what was discussed, what was decided, or what a meeting
revealed about someone's communication style or character. That content comes
from email (Gmail ingest task) and work journals (raw_ingest drop).

**Separation from the Gmail ingest task:**
- Gmail → meeting *content*: decisions, action items, exchanges, character data
- Calendar → meeting *structure*: cadence, attendees, recurring series, upcoming commitments

If you encounter a calendar event that has useful description text or notes
attached, include only the structural facts (title, attendees, date). Do not
synthesize that text into character or relationship observations — that is the
Gmail task's job.

**Separation from the wiki update task:**
- The wiki update task creates and maintains wiki pages.
- This task only writes raw files to `raw_ingest/calendar/`. It does not
  write to `wiki/` directly and does not run `manifest.py`.

---

## Prerequisites

1. Google Calendar MCP connector enabled in your Claude session (claude.ai
   integrations or Claude Code MCP settings).
2. `.calendar_manifest.json` at the wiki root (created automatically on first run).

---

## Configuration

| Setting | Value |
|---------|-------|
| Output directory | `raw_ingest/calendar/` |
| Manifest file | `.calendar_manifest.json` |
| Lookback window (past events) | 7 days |
| Lookahead window (upcoming) | 14 days |
| Calendar account | *(your institutional calendar)* |

---

## Stage 1: Load Context

1. Read `.calendar_manifest.json` if it exists; if not, treat as `{}`.
   The manifest maps event IDs to processing metadata.
2. Note existing wiki pages in `wiki/people/` and `wiki/topics/` —
   filenames and frontmatter `name` fields are enough; no need to read full files.
3. Read `wiki/topics/meeting-cadence.md` if it exists. Note what recurring
   meetings are already documented so you only write a recurring-meetings file
   if something has materially changed.

---

## Stage 2: Retrieve Events

Use the Google Calendar MCP connector to retrieve:

1. Events in the past 7 days (recently completed meetings)
2. Events in the next 14 days (upcoming meetings worth noting)

For each event: title, date/time, attendees (names and/or email addresses),
location or video link if present, and any description text.
Skip events already in `.calendar_manifest.json`.

---

## Stage 3: Filter

Discard events that are clearly out of scope:

- All-day events that are just blocked time, focus time, or OOO markers
- Automated reminders and calendar notifications with no attendees
- Personal calendar events (non-work appointments)
- Calendar invite delivery confirmations (accept/decline responses that
  landed on the calendar — not meetings themselves)
- Events with a single attendee (just the user — solo work blocks, reminders)

When uncertain, retain the event.

---

## Stage 4: Cluster

Group retained events into categories:

**Recurring 1-on-1 meetings** — group by series. Note the person, cadence,
format (in-person/video), and whether it already appears in `meeting-cadence.md`.

**Recurring team/group meetings** — group by series. Note attendees, cadence,
and whether the series is already documented.

**One-off significant events** — anything not part of a known recurring series
that has two or more attendees and a title suggesting a substantive meeting
(not a lunch, social event, or calendar blocker).

**Upcoming commitments** — anything in the next 14 days that is multi-day,
involves travel, or is a workshop/conference/training event.

**New contacts** — attendees who appear in calendar events but do not yet have
a page in `wiki/people/`. Flag these for stub page creation.

---

## Stage 5: Write Output Files

Write to `raw_ingest/calendar/`. Only write a file for a category if it
contains new information not already captured in the wiki.

### Recurring meetings file

Write only if `wiki/topics/meeting-cadence.md` does not exist, OR if the
recurring meeting landscape has changed (new series, discontinued series,
cadence or attendee change).

Filename: `recurring-<slug>-<YYYYMMDD>.md`

```markdown
---
type: calendar-recurring
source: google-calendar
date_extracted: YYYY-MM-DD
wiki_page: "wiki/topics/meeting-cadence.md"
---

# Recurring Meetings: [category or "all"]

## Summary

[One sentence: what changed or what this covers.]

## 1-on-1s

| Series | Person | Cadence | Format | Notes |
|--------|--------|---------|--------|-------|
| [title] | [name] | [weekly/biweekly] | [in-person/video] | [any structural note] |

## Team / Group Meetings

| Series | Attendees | Cadence | Format | Notes |
|--------|-----------|---------|--------|-------|
| [title] | [names] | [cadence] | [format] | [note] |
```

### Notable events file

Write if there are one-off significant meetings or upcoming multi-day
commitments not already in the wiki.

Filename: `events-notable-<YYYYMMDD>.md`

```markdown
---
type: calendar-events
source: google-calendar
date_extracted: YYYY-MM-DD
period_start: YYYY-MM-DD
period_end: YYYY-MM-DD
---

# Notable Calendar Events: [date range]

## Recent (Past 7 Days)

| Date | Event | Attendees | Notes |
|------|-------|-----------|-------|
| YYYY-MM-DD | [title] | [names] | [structural note only — no content summary] |

## Upcoming (Next 14 Days)

| Date | Event | Attendees | Notes |
|------|-------|-----------|-------|
| YYYY-MM-DD | [title] | [names] | [structural note] |

## New Contacts

People appearing in calendar events who do not yet have wiki pages:

| Name | Email (if visible) | Context |
|------|--------------------|---------|
| [name] | [email] | [which meeting they appear in] |
```

---

## Stage 6: Update Calendar Manifest

Record every event ID from this run in `.calendar_manifest.json`. Merge with
existing manifest; do not overwrite. Events that were filtered out in Stage 3
should also be recorded (with `"output_file": null`) so they are not
re-evaluated on the next run.

```json
{
  "<event_id>": {
    "processed": "YYYY-MM-DD",
    "output_file": "raw_ingest/calendar/events-notable-YYYYMMDD.md"
  }
}
```

---

## Stage 7: Report

```
Calendar ingest complete — YYYY-MM-DD
  Events retrieved:     N
  Filtered out:         N
  New events clustered: N
  Output files written:
    raw_ingest/calendar/events-notable-YYYYMMDD.md   (if written)
    raw_ingest/calendar/recurring-YYYYMMDD.md        (if written)
  New contacts flagged: N
  Manifest entries added: N
```

Note if no output files were written (no new structural information found).

---

## Relationship to other tasks

**Wiki update task** — picks up files from `raw_ingest/calendar/` in Stage 2
and synthesizes them into wiki pages. `calendar-recurring` type files update
`wiki/topics/meeting-cadence.md`. `calendar-events` type files contribute
interaction rows to people pages and, for upcoming multi-day commitments, may
update relevant topic pages.

**Gmail ingest task** — handles meeting *content*. If a calendar event
prompted a substantive email thread (a meeting request that became a real
conversation, a post-meeting follow-up), that content is captured by Gmail,
not here. Do not duplicate it.

**People pages** — the wiki update task adds interaction rows when it
processes calendar output. Those rows record structural facts only:
`| YYYY-MM-DD | [Meeting title] — attended |`. Richer context belongs in
Gmail dossier updates, not calendar-sourced rows.

---

*Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS.
Licensed under the GNU Free Documentation License, Version 1.3 or any later
version; with no Invariant Sections, no Front-Cover Texts, and no Back-Cover
Texts. See README.md for full license terms.*
