<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
This file is part of Mnemotron Wiki. See LICENSE for terms.

AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude Sonnet 5.5). It may not have been fully reviewed by a human; test it in your own environment before relying on it.
-->

# Gmail Ingest Task — Instructions for Claude

> **Requires:**
> - A **Gmail-capable MCP connector** that can search threads (with Gmail
>   query syntax) and fetch a thread with its messages. A connector with
>   richer body and quoted-history handling is better but not required, and
>   tool names vary between connectors — map the generic operations used here
>   ("search threads", "get thread") onto whatever yours exposes.
> - A wiki with the standard folders (`wiki/people/`, `wiki/topics/`,
>   `wiki/organizations/`) and the wiki update task (`WIKI_UPDATE_TASK.md`),
>   which consumes this task's output.
>
> **Local-file alternative (no connector):** export your mail with Google
> Takeout (Mail, mbox format) and run `python scripts/ingest_takeout.py
> <takeout.zip>` (see `--help` for the `--since`, `--days`, and `--list`
> options). It reads the Gmail mbox in the archive and writes the same kinds of
> files this task writes (dossier updates, topic updates, a summary file) into
> `raw_ingest/gmail/`, using a built-in noise filter instead of the Stage 3
> judgment calls below. For `.eml` exports, either convert to mbox first or
> follow Stages 3–7 by hand over the exported messages (group by
> `References`/`In-Reply-To` for threads; use the earliest Message-ID as the
> thread ID). If you have neither a connector nor an export, skip this
> document.


This file contains the instructions Claude follows when the Gmail ingest task
runs, whether on a schedule you set up yourself or on demand ("Run the Gmail
ingest task").

The task reads recent Gmail threads, identifies professionally relevant
communications, and writes structured markdown files to `raw_ingest/gmail/`
for the wiki update task to process. Its goal is to keep people, organization,
and topic pages current with information that arrives via email but is not
captured by other sources (meeting notes, task-tracker exports, briefings).

---

## Configuration

| Setting | Value |
|---------|-------|
| Output directory | `raw_ingest/gmail/` |
| Gmail manifest | `.gmail_manifest.json` |
| Default lookback window | 7 days |
| True first-run lookback window | 90 days |
| Ambiguous-history lookback window | 30 days |
| Mail account | the account your connector is authorized for |
| Time zone | `config.TIMEZONE` (default `UTC`) |

The Gmail manifest (`.gmail_manifest.json`) tracks processed thread IDs so
that no thread is summarized twice across runs. It is distinct from the wiki's
content-hash `.manifest.json`, and from `.email_archive_manifest.json` (used by
the verbatim email archive task, `EMAIL_ARCHIVE_TASK.md`).

---

## Stage 1: Load Context

1. Read `.gmail_manifest.json` if it exists. If it does not exist, treat it as
   an empty object `{}`. The manifest maps thread IDs to processing metadata.
2. Determine the lookback window (a window stated explicitly by the user
   always wins):
   - **True first run — manifest is empty and the wiki shows no prior sign of
     Gmail ingest** (no `raw_ingest/gmail/` output on record, no people/topic
     pages carrying gmail-sourced interactions): use 90 days. This is a
     genuinely new setup, so pull a wider history to seed the wiki.
   - **Ambiguous history — manifest is missing or empty, but the wiki already
     contains content clearly derived from earlier Gmail ingest** (existing
     dossier updates, gmail-summary files, or people/topic pages with
     email-sourced interactions): the manifest was lost, reset, or edited by
     hand, so the actual gap since the last real run can't be determined.
     Use 30 days as a conservative default rather than assuming either a
     fresh start or a short gap.
   - **Otherwise** (manifest has entries): use 7 days.
3. Read the list of existing wiki pages to understand current coverage:
   - `wiki/people/` — one file per person; note names and slugs.
   - `wiki/organizations/` — one file per org; note names and slugs.
   - `wiki/topics/` — one file per topic; note slugs and summaries.

   You do not need to read each file in full — filenames and frontmatter
   `name`/`title` fields are enough to build a lookup table. (The shared
   helper `scripts/build_relevance_index.py` builds exactly this lookup —
   `load_relevance_index()`, `match_person()`, `match_topics()`,
   `match_orgs()` — and you may use it instead of listing the directories by
   hand.)

---

## Stage 2: Retrieve Threads

Use the Gmail MCP connector to retrieve recent threads.

Run both of these searches and collect unique thread IDs:

1. **Inbox:** `is:inbox newer_than:Xd -category:promotions -category:social`
2. **Sent:** `is:sent newer_than:Xd`

(Replace `X` with the lookback window in days. For a fixed historical window,
use `after:YYYY/MM/DD before:YYYY/MM/DD` — day-granular, inclusive of `after`,
exclusive of `before` — or the connector's structured start/end time
parameters if it has them. Issue the inbox and sent searches concurrently; they
are independent reads.)

For each thread ID:
- **Skip** if it already appears in `.gmail_manifest.json`.
- Otherwise, retrieve the full thread. Collect: subject line, all participant
  addresses (from/to/cc), date of the most recent message, and message bodies.
  Fetches may be issued concurrently; manifest writes may not (see Stage 6).

---

## Stage 3: Filter

Discard threads that are clearly out of scope before clustering. Skip a thread
if it matches any of the following:

- Sender domain or display name contains: `noreply`, `no-reply`,
  `mailer-daemon`, `donotreply`, `forms-receipts`, `notifications`
- Subject matches patterns like: `[Jira]`, `[GitHub]`, automated CI/CD alerts
- Calendar invite with no substantive message body (just
  accept/decline/forward with no added text)
- Mailing list digests, newsletters, or listserv traffic
- IT security alerts, password reset confirmations, MFA notifications
- HR or payroll system notifications (benefits enrollment, pay stubs)

You may extend this list with patterns specific to your own mailbox (for
example, the addresses of a ticketing system or a building-alerts service);
keep the additions in this section so they persist.

If uncertain, retain the thread — it is better to over-include than to miss
substantive content.

### Reduced-scope threads

Some threads are professionally relevant but should receive lighter treatment.
Do not discard these; instead, handle them as described below rather than
creating full cluster files.

**Broadcast-list messages** (an all-staff, all-faculty, or similar
distribution list — identifiable by the recipient address or a
distribution-list display name): treat as background institutional context
rather than direct work content. The wiki owner receives these to stay aware
of announcements aimed at an audience they are not directly part of. Apply
the following rules:

- Do **not** create a person dossier update based solely on a broadcast-list
  thread, even for the sender. The sender's name, role, and topic may still
  be noted if they connect to the owner's work in another cluster that exists
  for independent reasons.
- Do **extract** people, events, dates, and topics mentioned and incorporate
  them into existing clusters where relevant (e.g., a named event or deadline
  that has bearing on your team's operations or on calendar tracking).
- If the message contains something actionable or contextually useful for
  the owner's work — an event affecting your services, an outreach
  opportunity, an item of archival or research significance, or relevant
  calendar information — include a brief note in a topic update or the
  catch-all.
- Example: a "Fall Final Exam Schedule" announcement from Jane Doe to an
  all-faculty list does not warrant a Jane Doe dossier entry, but the exam
  dates may be worth noting in a topic update for academic-calendar or
  collections planning if relevant.

---

## Stage 4: Cluster

Group the remaining threads by the primary entity they concern. A thread may
appear in more than one cluster.

### Person clusters

Create a person cluster for an individual if:
- They are already documented in `wiki/people/`, OR
- They appear as a participant in two or more threads, OR
- A single thread with them contains substantive professional content (a
  project discussion, decision, or meaningful exchange — not a one-line
  acknowledgment).

Use the email address to identify the person. Cross-reference against existing
people pages where possible.

### Topic / project clusters

Create a topic cluster if:
- The thread(s) are clearly about a specific ongoing project or topic that has
  (or should have) a wiki page — e.g., a digitization project, a software
  evaluation, a named working group, a specific project in your task tracker.
- The subject line or body references a named initiative, project, or
  institutional process.

### Catch-all

Threads that are professionally relevant but do not map cleanly to a person or
topic go into a single catch-all cluster. This cluster is written as a
summary file only if it contains at least two threads.

---

## Stage 5: Write Output Files

Write one markdown file per non-empty cluster to `raw_ingest/gmail/`. Do not
include full email bodies in output files — summarize content; do not quote at
length. Omit personal, HR-sensitive, or medical content entirely. (For a
verbatim record, use the email archive task instead.)

### Dossier update file

For person or organization clusters.

Filename pattern: `dossier-<slug>-<YYYYMMDD>.md`
Examples: `dossier-jane-doe-20260424.md`, `dossier-example-consortium-20260424.md`

```markdown
---
type: dossier-update
subject_type: person | organization
subject_name: "Full Name or Org Name"
wiki_page: "wiki/people/<slug>.md"   # omit if no page exists yet
source: gmail
date_extracted: YYYY-MM-DD
threads:
  - id: "<thread_id>"
    date: YYYY-MM-DD
    subject: "Email subject line"
---

# Dossier Update: [Name]

## New Interactions

| Date | Subject | Summary |
|------|---------|---------|
| YYYY-MM-DD | [subject] | [One-sentence summary of what was discussed or decided] |

## New Information

[Any new facts about this person/org not already in their wiki page: role
changes, new projects, inferred preferences, relevant context. 2–5 sentences.
Omit anything already documented. Note anything that speaks to their
communication style, working habits, or character — this feeds the personal
overview section maintained in their wiki dossier page.]

## Topics Raised

- [Project or topic name] — [one-line note; link to wiki page if it exists]
```

### Topic update file

For project or topic clusters.

Filename pattern: `topic-update-<slug>-<YYYYMMDD>.md`
Example: `topic-update-example-collection-digitization-20260424.md`

```markdown
---
type: topic-update
topic: "Topic or Project Name"
wiki_page: "wiki/topics/<slug>.md"   # omit if no page exists yet
source: gmail
date_extracted: YYYY-MM-DD
threads:
  - id: "<thread_id>"
    date: YYYY-MM-DD
    subject: "Email subject line"
---

# Topic Update: [Topic Name]

## What Changed

[2–4 sentences: what new information arrived, what was decided, what the
current status is as of the most recent thread.]

## Details

[Prose or short bullets covering specifics: dates, names, action items,
decisions, outstanding questions. 3–8 items.]

## People Involved

- [Jane Doe](../people/jane-doe.md) — [role or relevance in this context]
```

### Catch-all summary file

Only write this file if the catch-all cluster contains at least two threads.
Omit it otherwise.

Filename pattern: `gmail-summary-<YYYYMMDD>.md`

```markdown
---
type: gmail-summary
source: gmail
date_extracted: YYYY-MM-DD
period_start: YYYY-MM-DD
period_end: YYYY-MM-DD
---

# Gmail Summary: [date range]

## Threads

[One paragraph per thread: subject, participants, key content, and why it is
professionally relevant. Note any people or topics that don't yet have wiki
pages.]

## Possible New Wiki Entries

[Bullets: people, organizations, or topics encountered in this batch that
appear substantive enough to warrant a wiki page but do not yet have one.]
```

---

## Stage 6: Update the Gmail Manifest

After writing each output file, record every thread ID in that cluster in
`.gmail_manifest.json`. Merge with the existing manifest; do not overwrite it.
Write the manifest from a single context only — if you delegate clusters to
parallel agents (each writing only its own output files; if any agent
will touch a wiki page, it must claim it first with
`python scripts/agent_manifest.py claim ...`), have them report back and let one writer save the file once,
otherwise concurrent read-modify-write saves silently drop each other's
entries.

```json
{
  "<thread_id>": {
    "processed": "YYYY-MM-DD",
    "output_file": "raw_ingest/gmail/dossier-jane-doe-20260424.md",
    "note": "March 2026 — digitization scope discussion"
  }
}
```

The free-text `note` field is optional but useful: the email archive task's
Pass 0 shortlist (`email_archive_helpers.gmail_manifest_shortlist()`) parses
a month name out of it to pre-filter likely-relevant threads for a backfill
month. Include the month and a few words of context when you can.

Threads that were filtered out in Stage 3 should also be recorded (with
`"output_file": null`) so they are not re-evaluated on the next run.

---

## Stage 7: Report

Print a brief plain-text summary:

```
Gmail ingest complete — YYYY-MM-DD
  Threads retrieved:   N
  Filtered out:        N
  Clustered:           N
  Output files written:
    raw_ingest/gmail/dossier-name-YYYYMMDD.md
    raw_ingest/gmail/topic-update-slug-YYYYMMDD.md
    ...
  Manifest entries added: N
```

Note any threads that seemed ambiguous or might need manual review.

### Error handling

- **Connector error or timeout on a search or fetch:** retry once. If it
  still fails, do not record the thread in the manifest (so the next run
  retries it) and list it in the report as not processed.
- **Oversized thread response saved to a file by the connector:** not a
  failure. Read it with a short Python/JSON snippet via Bash rather than a
  line-oriented viewer; `scripts/email_archive_helpers.py --from-file <path>`
  parses the common response shape.
- **Slug mismatch / missing wiki page:** if a `wiki_page` path does not exist
  on disk, omit the field instead of guessing, and mention the person/topic
  under "Possible New Wiki Entries."
- **Partial run:** write the manifest after each output file, so an
  interruption leaves a consistent record and a rerun resumes cleanly.

---

## Notes on Scope and Judgment

**What is in scope:**
- Professional project correspondence — digitization requests, vendor
  communications, peer-institution exchanges
- Any exchange where both sender and recipient are writing from institutional
  addresses (for example `.edu` or your employer's domain) — treat as
  professional correspondence regardless of tone or subject matter
- Meeting context and outcomes — scheduling, follow-ups, decisions made, open
  questions
- New relationship information — role changes, introductions, new contacts
- Institutional developments — workgroups, policy, events, deadlines,
  announcements relevant to the owner's work

**What is out of scope:**
- Personal or social messages where at least one party is writing from a
  non-institutional (personal) address
- Routine administrative overhead with no informational content
- Anything that would be uncomfortable to have summarized in a work document
  (personnel matters, medical, financial)

Adjust these rules to your own situation — for instance, if your institution
does not use `.edu` addresses, substitute whatever distinguishes your work
correspondence from personal mail.

**Broadcast-list messages (reduced scope, not out of scope):** these are
announcements aimed at a different audience; the owner receives them primarily
to stay aware of campus or organizational activity, not because they concern
their work directly. They are a lightweight source of context (calendar,
events, occasionally outreach opportunities or items of archival interest)
but should not drive dossier updates or topic pages on their own. Extract
entities and dates that are relevant to existing wiki coverage; otherwise let
them pass without generating output. See Stage 3 for detail.

**Deduplication:** The Gmail manifest is the primary deduplication mechanism.
Cluster and output filenames include the date of extraction, not the date of
the emails, so multiple runs do not conflict.

**Relationship to the wiki update task:** Output files written to
`raw_ingest/gmail/` will be picked up by `scripts/check_ingest.py` on the next run
of the wiki update task. Their `type` and `wiki_page` frontmatter fields guide
the wiki update task to the correct destination page. The wiki update task
handles final synthesis; this task only produces ingest material.

**Existing wiki pages:** When a `wiki_page` path is present in an output
file's frontmatter, the wiki update task will update that page in place rather
than creating a new one. Accuracy here matters — double-check slugs against
the actual files in `wiki/people/` and `wiki/topics/` before writing.

---

*Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS. Licensed under GPL-3.0-or-later; see LICENSE.*
