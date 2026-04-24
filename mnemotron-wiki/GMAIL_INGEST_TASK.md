# Mnemotron Wiki — Gmail Ingest Task

**Optional connector.** Only needed if you want to pull information from Gmail
into your wiki. Requires the Gmail MCP connector configured in Claude.

This task reads recent Gmail threads, identifies professionally relevant
communications, and writes structured markdown files to `raw_ingest/gmail/`
for the wiki update task to process.

---

## Prerequisites

1. Gmail MCP connector enabled in your Claude session (claude.ai integrations
   or Claude Code MCP settings). The connector needs read access to your Gmail.
2. `.gmail_manifest.json` at the wiki root (created automatically on first run).

---

## Configuration

| Setting | Value |
|---------|-------|
| Output directory | `raw_ingest/gmail/` |
| Manifest file | `.gmail_manifest.json` |
| Default lookback window | 7 days |
| First-run lookback window | 30 days |
| Gmail account | *(your institutional email)* |

---

## Stage 1: Load Context

1. Read `.gmail_manifest.json` if it exists; if not, treat as `{}`.
   The manifest maps thread IDs to processing metadata.
2. Determine lookback window: 30 days on first run (empty manifest), else 7 days.
3. Note existing wiki pages (filenames + frontmatter `name`/`title` fields)
   in `wiki/people/`, `wiki/organizations/`, and `wiki/topics/`. You do not
   need to read full file contents — build a lookup table.

---

## Stage 2: Retrieve Threads

Use the Gmail MCP connector to run both searches and collect unique thread IDs:

1. `is:inbox newer_than:Xd -category:promotions -category:social`
2. `is:sent newer_than:Xd`

(Replace X with the lookback window in days.)

For each thread ID not already in `.gmail_manifest.json`: retrieve the full
thread (subject, participant addresses, date, message bodies).

---

## Stage 3: Filter

Discard a thread if it matches any of the following:

- Sender contains: `noreply`, `no-reply`, `mailer-daemon`, `donotreply`,
  `forms-receipts`, `notifications`
- Automated alerts: `[GitHub]`, CI/CD notifications, Jira tickets
- Calendar invites with no substantive message body
- Mailing list digests, newsletters, listserv traffic
- IT/security notifications, password resets, MFA
- HR/payroll system notifications

When uncertain, retain the thread.

---

## Stage 4: Cluster

Group remaining threads by the primary entity they concern. A thread may
appear in more than one cluster.

**Person clusters:** Create when the individual is already in `wiki/people/`,
appears in two or more threads, or has a single thread with substantive
professional content (a decision, project discussion, or meaningful exchange).

**Topic/project clusters:** Create when threads clearly concern a named
initiative, project, or institutional process that has (or should have) a
wiki page.

**Catch-all:** Threads that are professionally relevant but don't map to a
person or topic. Write as a summary file only if it contains at least two threads.

---

## Stage 5: Write Output Files

Write one markdown file per non-empty cluster to `raw_ingest/gmail/`. Summarize
content — do not quote email bodies at length. Omit personal, HR-sensitive, or
medical content entirely.

### Dossier update (person or organization cluster)

Filename: `dossier-<slug>-<YYYYMMDD>.md`

```markdown
---
type: dossier-update
subject_type: person | organization
subject_name: "Full Name or Org Name"
wiki_page: "wiki/people/<slug>.md"   # omit if no page yet
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
| YYYY-MM-DD | [subject] | [One-sentence summary] |

## New Information

[New facts not already in their wiki page: role changes, projects, preferences,
context. 2–5 sentences. Note anything that speaks to communication style,
working habits, or character — this feeds the Personal Overview section.]

## Topics Raised

- [Topic name] — [one-line note; link to wiki page if it exists]
```

### Topic update (project or topic cluster)

Filename: `topic-update-<slug>-<YYYYMMDD>.md`

```markdown
---
type: topic-update
topic: "Topic or Project Name"
wiki_page: "wiki/topics/<slug>.md"   # omit if no page yet
source: gmail
date_extracted: YYYY-MM-DD
threads:
  - id: "<thread_id>"
    date: YYYY-MM-DD
    subject: "Email subject line"
---

# Topic Update: [Topic Name]

## What Changed

[2–4 sentences: new information, decisions, current status.]

## Details

[Specifics: dates, names, action items, decisions, outstanding questions.]

## People Involved

- [Name](../people/<slug>.md) — [role or relevance]
```

### Catch-all summary

Filename: `gmail-summary-<YYYYMMDD>.md` — only write if 2+ catch-all threads.

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

[One paragraph per thread: subject, participants, key content, relevance.]

## Possible New Wiki Entries

- [People, organizations, or topics that don't yet have pages but should]
```

---

## Stage 6: Update Gmail Manifest

Record every thread ID from this run in `.gmail_manifest.json`. Merge with
existing manifest; do not overwrite. Filtered-out threads should also be
recorded (with `"output_file": null`) so they are not re-evaluated.

```json
{
  "<thread_id>": {
    "processed": "YYYY-MM-DD",
    "output_file": "raw_ingest/gmail/dossier-name-YYYYMMDD.md"
  }
}
```

---

## Stage 7: Report

```
Gmail ingest complete — YYYY-MM-DD
  Threads retrieved:    N
  Filtered out:         N
  Clustered:            N
  Output files written:
    raw_ingest/gmail/dossier-name-YYYYMMDD.md
    ...
  Manifest entries added: N
```

Note any threads that seemed ambiguous or may need manual review.

---

## Scope

**In scope:** Project correspondence, meeting context and outcomes, new
relationship information, institutional developments relevant to your work.

**Out of scope:** Personal correspondence, routine administrative overhead
with no informational content, anything that would be uncomfortable to have
summarized in a work document (personnel matters, medical, financial).

**Relationship to the wiki update task:** Files written to `raw_ingest/gmail/`
are picked up by `check_ingest.py` on the next wiki update run. The `wiki_page`
frontmatter field guides the wiki update task to the correct destination.

---

*Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS.
Licensed under the GNU Free Documentation License, Version 1.3 or any later
version; with no Invariant Sections, no Front-Cover Texts, and no Back-Cover
Texts. See README.md for full license terms.*
