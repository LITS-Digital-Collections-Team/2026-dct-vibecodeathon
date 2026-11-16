<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
This file is part of Mnemotron Wiki. See LICENSE for terms.

AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude Sonnet 5.5). It may not have been fully reviewed by a human; test it in your own environment before relying on it.
-->

# Calendar Ingest Task — Instructions for Claude

> Created with assistance from Claude Code (Claude Sonnet 5.5); may not have been fully reviewed by a human.

**Requires:** a calendar connector that Claude can call (for example an MCP
connector for Google Calendar or another calendar service) that can list
events in a date range and return each event's id, title, start/end, and
attendees. **If you do not have one, skip this document.** Local alternatives:
export your calendar as an `.ics` file and drop it in `raw_ingest/` (reference
mode will treat it as an ordinary document), or write the two output files
described in Stage 5 by hand.

This file contains the instructions Claude follows when the calendar ingest
task runs. Run it on demand ("run the calendar ingest task"), from a
scheduler using headless Claude Code (`claude -p`), or through the API agent
runner. It works without a human in the loop.

The task reads calendar events, identifies professionally relevant meetings
and patterns, and writes structured Markdown files to `raw_ingest/calendar/` for
the wiki update task (`WIKI_UPDATE_TASK.md`) to process.

---

## What this task does, and does not do

**Calendar data is structural, not substantive.**

This task records *who meets with whom*, *how often*, and *what is coming up*.
It does NOT record what was discussed, what was decided, or what a meeting
revealed about someone's communication style or character. That content comes
from email (the Gmail ingest, `GMAIL_INGEST_TASK.md`) and from journals and
notes dropped in `raw_ingest/`.

**Separation from the Gmail ingest task:**

- Gmail: meeting *content*: decisions, action items, exchanges, character data
- Calendar: meeting *structure*: cadence, attendees, recurring series,
  upcoming commitments

If an event has useful description text or notes attached, include only the
structural facts (title, attendees, date). Do not synthesise that text into
character or relationship observations; that is the email task's job.

**Separation from the wiki update task:**

- The wiki update task creates and maintains wiki pages.
- This task only writes raw files to `raw_ingest/calendar/` and updates its own
  calendar manifest. It does not write to `wiki/` and does not touch
  `.manifest.json` (the content-hash manifest used by the wiki task).

---

## Configuration

Set these in the invocation prompt or in this table. Defaults are shown.

| Setting | Default |
|---------|---------|
| Wiki root | the directory containing this task file's parent folder |
| Output directory | `raw_ingest/calendar/` |
| Calendar manifest | `.calendar_manifest.json` (wiki root) |
| Lookback window (past events) | 7 days |
| Lookahead window (upcoming) | 14 days |
| Calendar account | the connector's default (primary) calendar; name another if needed |
| Time zone | `TIMEZONE` in `scripts/config.py` (default UTC) |
| Owner identity | the owner's own address(es); used to drop solo events |

If `.calendar_manifest.json` already exists, it maps event IDs to processing
metadata. Never overwrite it; merge new entries. If it does not exist, create
it as `{}`.

---

## Stage 1: Load context

1. Read `.calendar_manifest.json` (or start from `{}`). Note which event IDs
   have already been processed so they are not emitted again.
2. Read the filenames (and front-matter `name` fields) in `wiki/people/` to
   build a lookup table of who already has a dossier page. If `wiki/people/`
   does not exist, treat everyone as new.
3. Read `wiki/topics/meeting-cadence.md` if it exists. Note which recurring
   meetings are already documented, so you write a recurring-meetings file
   only if something has materially changed.

---

## Stage 2: Retrieve events

Use the calendar connector to retrieve:

1. Events in the past 7 days (recently completed)
2. Events in the next 14 days (upcoming)

For each event: id, title, date/time, attendees (names and/or email
addresses), location or video link if present, and any description text.

Skip events whose IDs already appear in `.calendar_manifest.json`.

If the connector is unavailable or returns an error, write nothing, report the
error, and stop. Do not fabricate events.

---

## Stage 3: Filter

Discard events that are clearly out of scope:

- All-day blocks that are just out-of-office markers, focus time or holds
- Automated reminders and calendar notifications with no attendees
- Personal calendar events (non-work appointments)
- Invite-delivery confirmations (accept/decline notices that landed on the
  calendar; they are not meetings themselves)
- Events with a single attendee (just the owner: solo work blocks, reminders)

When uncertain, retain.

---

## Stage 4: Cluster

Group retained events into categories:

**Recurring 1-on-1 meetings.** Group by series (for example "Owner/Jane Doe
1-on-1"). Note person, cadence, location/format, and whether it appears in
`meeting-cadence.md` already.

**Recurring team/group meetings.** Group by series (for example "Platform Team
Meeting", "Quarterly Review"). Note attendees, cadence and existing coverage.

**One-off significant events.** Anything not part of a known recurring series
that has two or more attendees and a title suggesting a substantive meeting
(not a lunch, social event or calendar blocker). Note title, attendees, date.

**Upcoming commitments.** Anything in the next 14 days that is multi-day,
involves travel, or is a workshop, conference or training event.

**New contacts.** Attendees who appear in calendar events but have no page in
`wiki/people/`. Flag these for stub page creation.

---

## Stage 5: Write output files

Write to `raw_ingest/calendar/` (create it if missing). Only write a file for a
category if it contains new information not already captured in the wiki.

### Recurring meetings file

Write only if `wiki/topics/meeting-cadence.md` does not exist, OR if the
recurring meeting landscape has changed (new series, discontinued series,
change of cadence or attendees).

Filename: `recurring-<slug>-<YYYYMMDD>.md`

```markdown
---
type: calendar-recurring
source: calendar
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
source: calendar
date_extracted: YYYY-MM-DD
period_start: YYYY-MM-DD
period_end: YYYY-MM-DD
---

# Notable Calendar Events: [date range]

## Recent (Past 7 Days)

| Date | Event | Attendees | Notes |
|------|-------|-----------|-------|
| YYYY-MM-DD | [title] | [names] | [structural note only; no content summary] |

## Upcoming (Next 14 Days)

| Date | Event | Attendees | Notes |
|------|-------|-----------|-------|
| YYYY-MM-DD | [title] | [names] | [structural note] |

## New Contacts

People appearing in calendar events who do not yet have wiki pages:

| Name | Email (if visible) | Context |
|------|--------------------|---------|
| Jane Doe | jdoe@example.edu | [which meeting they appear in] |
```

---

## Stage 6: Update the calendar manifest

After writing each output file, record all event IDs processed in this run in
`.calendar_manifest.json`. Merge with the existing manifest (read it again
right before writing; do not clobber entries added by a concurrent run).

```json
{
  "<event_id>": {
    "processed": "YYYY-MM-DD",
    "output_file": "raw_ingest/calendar/events-notable-YYYYMMDD.md"
  }
}
```

Events filtered out in Stage 3 are also recorded (with `"output_file": null`)
so they are not re-evaluated on the next run.

---

## Stage 7: Report

```
Calendar ingest complete - YYYY-MM-DD
  Events retrieved:     N
  Filtered out:         N
  New events clustered: N
  Output files written:
    raw_ingest/calendar/events-notable-YYYYMMDD.md   (if written)
    raw_ingest/calendar/recurring-<slug>-YYYYMMDD.md (if written)
  New contacts flagged: N
  Manifest entries added: N
```

Note if no output files were written (no new structural information found).

---

## Relationship to other tasks

**Wiki update task** (`WIKI_UPDATE_TASK.md`): picks up files from
`raw_ingest/calendar/` in Stage 2 and synthesises them into wiki pages.
`calendar-recurring` files update `wiki/topics/meeting-cadence.md`.
`calendar-events` files contribute interaction rows to people pages and, if
they involve upcoming multi-day commitments, may update relevant topic pages.

**Gmail ingest task** (`GMAIL_INGEST_TASK.md`): handles meeting *content*. If
a calendar event prompted a substantive email thread (a meeting request that
turned into a real conversation, a post-meeting follow-up), that content is
captured by the email task, not here. Do not duplicate it.

**People pages**: the wiki task adds interaction rows when it processes
calendar output. Those rows record structural facts only:
`| YYYY-MM-DD | [Meeting title] - attended | calendar |`. Richer context
belongs in email-sourced dossier updates, not calendar-sourced rows.
