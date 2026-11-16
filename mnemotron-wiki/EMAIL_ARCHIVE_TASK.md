<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
This file is part of Mnemotron Wiki. See LICENSE for terms.

AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude Sonnet 5.5). It may not have been fully reviewed by a human; test it in your own environment before relying on it.
-->

# Email Archive Task — Instructions for Claude

> **Requires:**
> - A **Gmail-capable MCP connector** that can (a) search threads/messages
>   with Gmail query syntax and (b) fetch a full thread with message bodies.
>   A connector with richer body handling (full plain-text bodies, quoted-history
>   handling, attachment listing) is better, but is not required, and tool
>   names vary between connectors — map the generic operations used below
>   ("search threads", "get thread", "list attachments") onto whatever your
>   connector exposes. If it cannot list attachments, record `Attachments: Unknown`.
> - A wiki with the standard folders (`wiki/people/, `wiki/topics/`,
>   `wiki/organizations/`) — the relevance gate needs documented entities to
>   match against.
>
> **Local-file alternative (no connector):** export your mail (Google Takeout
> mbox, or a folder of `.eml` files) and run the same pipeline over the
> exported messages instead of live Gmail. See "Working from a local export"
> immediately below. If you have neither a connector nor an export, skip this
> document.


This file contains the instructions Claude follows when the email archive
task runs. It is invoked on demand only — say "run the email archive task".
It is not scheduled and does not run automatically.

Unlike the Gmail ingest task (`GMAIL_INGEST_TASK.md`), which filters heavily
and writes short synthesized summaries for the wiki update task to absorb
into people/topic pages, this task is a **verbatim archive**: when it
decides to keep something, it preserves headers and body text exactly as
sent, with no summarization, and writes directly to `wiki/email/` — there is
no downstream synthesis step (an optional, separate Synthesis Pass is described
at the end of this file).

**What it keeps is relevance-gated, not everything.** A thread only gets
archived as a full conversation if it connects — even loosely — to something
already documented in the wiki (`wiki/people/`, `wiki/topics/`,
`wiki/organizations/`). An earlier, fully-inclusive design was abandoned
because the volume was dominated by content with no lasting connection to
anything the wiki owner actually tracks (see "Standing Policy Decisions").
The trivial/marketing/digest rules are **not** relevance-gated — a recurring
automated system notification is still a digest regardless of whether it
happens to name a documented person, and any digest sources you have
explicitly marked "keep unconditionally" (for example, professional-community
listserv digests) are exempt from the gate. Relevance-gating only decides
whether real correspondence gets the full verbatim treatment.

**Relationship to the Gmail ingest task:** the two tasks are independent and
may both process the same thread. The Gmail ingest task extracts and
summarizes professionally relevant content into dossier/topic updates, and
is the mechanism by which *new* people/topics/orgs get wiki pages in the
first place. This task preserves the full correspondence record for
*already-documented* entities. They use separate manifests and do not need
to agree on scope, but there is a real dependency: this task's relevance
gate can only find what the Gmail ingest task (or the wiki owner directly)
has already put in the wiki. A thread that fails the relevance gate today may
pass on some future run if its sender or topic gets a wiki page later.

---

## Working from a local export (alternative to a live connector)

If you have no Gmail connector, export the mailbox and substitute these
steps wherever the document says "search threads" / "get thread":

1. **Export.** Use Google Takeout (Mail, mbox format) or any client that
   writes `.eml` files. Unzip into a scratch folder. (`scripts/ingest_takeout.py
   --help` documents the Takeout path for the *Gmail ingest* task; the
   verbatim archive uses the same export but a different output.)
2. **Enumerate messages** with Python's standard `mailbox` module (mbox) or
   `email` module (`.eml`) via a short script run through Bash. Filter by the
   `Date` header to the requested window — this replaces Stage 2's search
   queries.
3. **Group into threads.** Takeout mbox files carry Gmail's `X-GM-THRID`
   header; use it as the thread ID. For plain `.eml` exports, group by the
   `References`/`In-Reply-To` chain and use the Message-ID of the earliest
   message (hashed or sanitized) as the thread ID.
4. **Convert** each thread into the same per-message shape the helper script
   uses (`id`, date, from/to/cc, subject, body text, label list if any),
   then continue at Stage 3. Everything downstream — classification, quote
   stripping (`dequote_message()`), file templates, manifests, digest
   registry — is identical. `Pass 0`, `Pass 1/2` and "Avoiding unnecessary
   Gmail calls" do not apply; instead skip any thread whose manifest entry
   already covers its newest message.
5. **Format adjustments.** Use the same frontmatter but set `source: mbox`
   (or `eml`) instead of `source: gmail`, and fill `thread_id` with whatever
   ID step 3 produced. Attachment filenames come from MIME parts
   (`part.get_filename()`); still do not extract attachment content.

---

## Configuration

| Setting | Value |
|---------|-------|
| Output directory | `wiki/email/` |
| Email archive manifest | `.email_archive_manifest.json` |
| Relevance index cache | `.relevance_index.json` (built/loaded via `scripts/build_relevance_index.py`) |
| Digest source registry cache | `.digest_registry.json` (built/loaded via `scripts/build_digest_registry.py`) |
| Default lookback window | 14 days |
| Mail account | the account your connector is authorized for (or your export) |
| Time zone for timestamps | `config.TIMEZONE` (default `UTC`; set it in `scripts/config.py`) |

The email archive manifest (`.email_archive_manifest.json`) tracks, per
thread, which messages have already been archived and to which output file.
It is distinct from `.gmail_manifest.json` (used by the Gmail ingest task,
read-only here for Stage 2's Pass 0 shortlist — never written by this task)
and `.manifest.json` (used by the wiki update task — not touched by this
task at all). The two cache files above are owned by this task: they are
derived, disposable, and safe to delete and let regenerate at any time if
something ever looks wrong with them.

**Custom windows:** the default lookback is 14 days. For a one-time backfill,
the user may ask for a longer window explicitly — e.g. "run the email
archive task for the last 90 days" or "...since 2026-01-01." Use whatever
window is stated; otherwise use 14 days regardless of whether the manifest is
empty or not (there is no separate first-run window for this task). See
"Fixed historical windows (backfills)" under Stage 2 for the actual search
mechanism — a relative window like `newer_than:Nd` cannot express a fixed
past date range, so backfills use a different query shape than routine runs.

**Large backfills should be chunked, not run as one giant window.** Split
into sub-windows (a month at a time is a reasonable default; use narrower
windows if a given period turns out to be especially high-volume) and run
each sub-window through the full Stage 1–9 pipeline in chronological order
before moving to the next. Digest and marketing-log files are living
documents that simply keep accumulating rows across sub-windows — there is
nothing special to do there. This also bounds how much a single pass has to
hold in context at once. If delegating each sub-window to a separate agent,
run them **sequentially, not in parallel** — two agents touching the
manifest or the same digest/marketing-log file at the same time can clobber
each other's writes, since both append-then-save the whole file.

---

## Personal/relevance index — how you configure it

The relevance gate and the "Related Wiki Pages" links are driven entirely by
your own wiki pages. There is no separate configuration file: you "configure"
the index by writing good frontmatter on the pages in `wiki/people/`,
`wiki/topics/`, and `wiki/organizations/`.

- **People pages:** put every address the person uses in an `email:` field
  (a single address, a comma-separated string, or a YAML block list; all
  are supported by `scripts/build_relevance_index.py`). A person with no
  `email:` still matches by name (page title/`name`), so add known aliases
  and nicknames to the page where the index reads them.
- **Topic pages:** the topic title and every entry in `tags:` become match
  keywords. Add tags for project code names, vendor names, and recurring
  phrases you would want an email subject to match.
- **Organization pages:** the org name (and any tags/aliases) becomes a match
  keyword. Keep org names specific. Broad "home institution" organizations
  (your own employer, department, or domain) should **not** by themselves
  make a thread relevant — see the gate rule in Stage 3.
- **Refreshing:** the index rebuilds automatically when any source page is
  newer than `.relevance_index.json`. Force a rebuild with
  `python scripts/build_relevance_index.py --force`, or inspect it with
  `--print`.

A newly added page does not retroactively pull in previously logged
candidate threads (see Stage 7); it only affects new activity going forward.

## Digest-source registry — how you configure it

The digest registry is derived, not hand-maintained. Every
`wiki/email/digest-*.md` file declares which messages belong to it in its own
frontmatter (`source_name`, `source_pattern`). `build_digest_registry.py`
parses those fields into `.digest_registry.json`.

To register a new recurring source:

1. Create `wiki/email/digest-<source-slug>.md` from the Stage 5 template.
2. Set `source_pattern` to a sender address, a domain, or a stable subject
   prefix (simple literal/wildcard forms work best — it is not a full
   parser), for example `alerts@example.org` or
   `Example Security Bulletin *`.
3. Run `python scripts/build_digest_registry.py --force`, then verify with
   `python scripts/build_digest_registry.py --test 'alerts@example.org' 'Example Security Bulletin 2026-014'`.

To mark a digest source "keep unconditionally" (exempt from the relevance
gate, such as a professional-community mailing list you always want a
one-line-per-issue record of), simply give it a digest file; digests are
never relevance-gated. To stop archiving a source, delete its digest file
and rebuild the registry.

---

## Stage 1: Load Context

1. Read `.email_archive_manifest.json`. If it does not exist, treat it as an
   empty object `{}` and create it after Stage 8.
2. List existing files in `wiki/email/` so you know which conversation,
   digest, marketing-log, and candidate-log files already exist and can
   update them in place instead of duplicating them.
3. **Load the relevance index — don't rebuild it by hand.** This does
   double duty: it feeds the "Related Wiki Pages" section *and* drives
   Stage 2's targeted search and Stage 3's relevance gate. Rather than
   re-parsing the three wiki directories from scratch every run, call:

   ```python
   import sys; sys.path.insert(0, 'scripts')
   from build_relevance_index import load_relevance_index, match_person, match_topics, match_orgs, wiki_link_for_person
   index = load_relevance_index()   # rebuilds only if a wiki/people|topics|organizations file is newer than the cache
   ```

   `load_relevance_index()` caches to `.relevance_index.json` and only
   rebuilds when a source file's mtime is newer than the cache — so the
   first chunk in a chained backfill pays the parse cost once and every
   later chunk just loads the cached JSON. Use `match_person(sender_or_name, index)`,
   `match_topics(text, index)`, and `match_orgs(text, index)` directly for
   Stage 2's keyword search and Stage 3's relevance gate — don't re-derive
   matching logic inline. `wiki_link_for_person(email_or_name, index)`
   returns the exact `../people/<slug>.md` relative link for the "Related
   Wiki Pages" section, so that step is a lookup, not a re-derivation of the
   slug/path each time (`wiki_link_for_topic(slug)` and `wiki_link_for_org(slug)`
   do the same for the other two page types).

   People without an `email:` field still match by name via `match_person`.
   Your home institution is almost certainly broad enough that nearly any
   message from your own domain would nominally match an organization —
   institutional domain membership alone is deliberately **not** treated as
   a hit; see the relevance-gate rule in Stage 3.

4. **Load the digest source registry** the same way — don't re-infer
   "is this sender an established digest source" by scanning
   `wiki/email/digest-*.md` files each time:

   ```python
   from build_digest_registry import load_digest_registry, match_digest_source
   registry = load_digest_registry()   # rebuilds only if a digest-*.md file is newer than the cache
   output_file = match_digest_source(sender_email, subject, registry)  # None if not a known source
   ```

   A `None` result means "not a known recurring source" — apply Stage 3's
   first-sighting heuristic fresh; it does not mean "definitely a one-off"
   (a source whose subject idiom the simple pattern-matcher cannot parse
   will also return `None`; when in doubt, trust the self-describing
   sender/subject heuristics in Stage 3 over a `None`).

**Avoiding unnecessary Gmail calls:** the manifest is authoritative for what
has already been archived. Before fetching any thread, check whether it is
already in the manifest with a `last_message_date` on or after the newest
message the search results show for that thread — if so, skip the fetch
entirely. If a thread has newer messages than what's recorded, you still
need to fetch it (there is no partial-thread fetch), but you only need to
append the messages newer than `last_message_id` to the existing file.

---

## Stage 2: Retrieve Threads

Retrieval is **targeted first, broad fallback second** — the goal is to
avoid ever fetching full thread bodies for threads that have no chance of
passing the Stage 3 relevance gate. Search-result listings are cheap (they
return sender/subject/snippet metadata, not full bodies), so it is fine to
cast a wide net at that level; the expensive step is everything after.

### Pass 0 — shortlist from `.gmail_manifest.json` first (a real pre-filter, not just a cross-check)

Before building any search query, pull a shortlist directly out of the
Gmail ingest task's own manifest — this is cheap (one JSON read, no mail
calls) and, for a backfill month, often the fastest way to a first batch of
almost-certainly-relevant thread IDs. Skip this pass if you have never run
the Gmail ingest task (no `.gmail_manifest.json`).

```python
import sys; sys.path.insert(0, 'scripts')
from email_archive_helpers import gmail_manifest_shortlist
matched, unknown_date = gmail_manifest_shortlist('.gmail_manifest.json', month=3, year=2026)
```

(CLI form: `python scripts/email_archive_helpers.py --gmail-manifest-shortlist .gmail_manifest.json 3`.)

`matched` is every thread with a non-null `output_file` (the Gmail ingest
task judged it professionally relevant enough to write a dossier/topic
update) whose free-text `note` parses to the target month. Fetch these
directly and run them through the Stage 3 relevance gate immediately — skip
constructing a Pass 1/2 search query for them, since you already have the
thread ID. `unknown_date` is the same signal but with no parseable month in
the note; fold these into Pass 2's candidate pool rather than fetching them
blind.

**Still not authoritative.** `.gmail_manifest.json` answers a different
question — "professionally relevant" (the Gmail ingest task's standard) isn't
the same test as "connects to something already in the wiki" (this task's
gate) — and the wiki may have grown since that entry was written. Apply the
Stage 3 relevance gate fresh against the *current* lookup for every thread
this surfaces; a manifest hit is a strong prior, not a bypass. And don't
treat absence from this manifest as evidence of irrelevance — the Gmail
ingest task's filtering is stricter than this task's.

### Pass 1 — targeted queries from the relevance index

Build queries from the relevance index's people lookup (loaded once in
Stage 1 — don't rebuild it here): batch known email addresses into
`from:(a@example.org OR b@example.edu OR ...)` / `to:(...)` groups (roughly
15-20 addresses per query to stay under Gmail's query-length limits), and run
both an inbox and a sent search per batch, restricted to the window (see
"Fixed historical windows" below for backfills). Separately, run a keyword
search using the topics/organizations lookup (topic titles and `tags:`
values) to catch content-side matches whose participants aren't documented
people — e.g. a vendor thread about a tracked project. Skip any
address/keyword already covered by a Pass 0 hit.

This is expected to surface the large majority of relevant threads not
already caught by Pass 0, since most real correspondence has a documented
person as sender or recipient.

**Issue these searches concurrently, not one at a time.** The inbox and
sent searches, and each address-batch and keyword query within Pass 1, are
independent reads with no ordering dependency on each other — batch them as
parallel tool calls in a single turn rather than waiting for each to return
before issuing the next. The same applies to thread fetches once you have a
confirmed list of candidate thread IDs: fetch the batch concurrently. The
only part of this pipeline that needs to happen one at a time is the
*writing* — manifest updates and digest/marketing/candidate log appends —
since those read-modify-write the same file repeatedly and concurrent
writes to it would clobber each other. Reads can overlap freely; writes
cannot.

### Pass 2 — lightweight fallback for the rest of the window

Also run the plain window-wide search (`is:inbox` / `is:sent` for the
period, no participant/keyword restriction), but **only inspect the returned
metadata** (sender address/name, subject) against the relevance index — do
not fetch a thread from this pass unless the metadata itself suggests a
match that Pass 0/1 missed (e.g. an undocumented email alias for a known
person, a topic keyword appearing only in the subject line, or one of Pass
0's `unknown_date` entries turning out to belong to this window). This
catches the remaining gaps without paying full-body-fetch cost on the rest.

Do **not** add `-category:promotions`, `-category:social`, or any other
Gmail category exclusion to either pass — the marketing/digest/trivial
classification in Stage 3 already handles that distinction, and it needs
the content to decide correctly, not a blunt category filter.

Skip a thread only if it is already fully covered per the manifest check in
Stage 1.

### Fixed historical windows (backfills)

`newer_than:Nd` is relative to the moment the search runs — it cannot
express "all of January 2026." For a backfill with an explicit start (and
optionally end) date, use the connector's structured `start_time`/`end_time`
parameters (ISO 8601) if it has them, instead of a raw query string:

1. **Inbox:** `is:inbox` restricted to `[start_time, end_time)` via the
   structured params, plus participant filters as needed — or, if the
   connector's structured date params don't combine cleanly with `is:inbox`,
   fall back to a raw query with Gmail's `after:YYYY/MM/DD before:YYYY/MM/DD`
   syntax (note: `after`/`before` are day-granular, inclusive of `after` and
   exclusive of `before`).
2. **Sent:** same, with `is:sent`.

Compute the boundary timestamps with a real timezone conversion in
`config.TIMEZONE` (DST-aware — `scripts/email_archive_helpers.py` contains
the conversion helper used elsewhere in this task) rather than a hard-coded
UTC offset, since the offset differs by month in zones with daylight saving
time. Getting it wrong only shifts which emails land in which chunk by an
hour at the boundary — low-stakes, but easy to get right.

For each remaining thread ID, retrieve the full thread: subject, all
participant addresses (from/to/cc/bcc where visible), date of each message,
and each message's body.

**Check attachments on every message, not just ones that mention them.**
If your connector can list attachments, do so for every message in a thread
headed for full or digest treatment, even if the body text doesn't say
anything is attached — don't rely on spotting phrases like "attached" or
"[image: ...]" as your trigger; text-based hinting misses attachments on
otherwise-unremarkable messages (for example, a self-addressed email whose
only content is a few draft documents). Do not download or embed attachment
content — filenames only.

---

## Stage 3: Classify

Sort each thread into exactly one of five buckets: trivial, marketing,
digest, full conversation, or candidate (new). Trivial, marketing, and
digest classification are **not** subject to the relevance gate below — a
recurring system notification is still a digest whether or not it happens to
mention a documented person, and digest sources you have registered are kept
unconditionally (they are already condensed to one line per issue and the
cost of keeping them is negligible). The relevance gate applies only to
candidates for full-conversation treatment.

When uncertain between "trivial" and "full conversation," choose full
conversation (subject to the relevance gate). When uncertain between
"digest" and "full conversation," choose full conversation on a source's
first appearance and only reclassify it as digest-eligible once you can see
the repeating pattern. When uncertain between "marketing" and "digest," ask
whether the sender's primary intent is commercial/promotional (marketing) or
operational/institutional (digest) — see the distinction below.

### Trivial — skip entirely, no log

Skip only messages with no lasting reference value:

- New sign-in / new-device-login security alerts
- MFA / 2FA one-time passcodes and verification codes
- Password-reset emails containing only a reset link/code and no other content
- Delivery-status, bounce, or read-receipt notifications with no added
  message content
- Calendar accept/decline auto-notifications with no message body text

Record skipped thread/message IDs in the manifest with `"kind": "skipped"` so
they are not re-evaluated on the next run. Nothing is written to `wiki/email/`
for this bucket, not even a log entry — these are genuinely disposable.

### Marketing — skip archiving, but log for reference

Commercial/promotional email whose primary purpose is to sell, upsell, or
drive engagement with a paid product or service, rather than to convey
information about the wiki owner's actual work or their institution's
operations. Do **not** write a conversation or digest file for these — but
**do** record every instance in the running marketing log (Stage 6) so their
existence is still searchable later.

Marketing indicators:
- Sender is a commercial vendor (not your own institution, not a professional
  association/listserv) and the message is a newsletter, product-tip email,
  "what's new" feature rundown, webinar/event invite, or onboarding nudge.
- The email's call to action is "buy," "register," "upgrade," "don't miss
  out," "here's what you're missing" — engagement/revenue framing, not an
  operational fact about the owner's own accounts, infrastructure, or work.
- A `CATEGORY_PROMOTIONS` label is present (a strong signal, though not
  dispositive on its own — cross-check against the content).

**Not marketing, even from a commercial vendor** — these stay in the digest
bucket instead, because they report on the owner's/institution's own
operational state rather than trying to sell something: automated system
notifications (security bulletins, crawl/build reports, account/system
status), and transactional notifications about work the owner or colleagues
actually did (e.g. a project-tracker comment digest, an HR-system time-off
receipt). The test: does this email tell me something happened in *our*
systems/work, or is it trying to get me to engage more with *their*
product? The former is digest; the latter is marketing.

Examples: an analytics vendor's onboarding reminder and a task-tracker
vendor's monthly "What's new" product newsletter are marketing. The same
tracker's "you have unread notifications" digest and its individual
task-comment notifications are not — they report actual work activity. A
retirement-plan provider's webinar invitations are marketing (event
promotion), even though the provider administers the owner's own plan — this
is commercial event marketing, not an operational fact about the owner's
account.

### Digest-eligible — condense, don't drop

A thread or a recurring sender qualifies for digest treatment when messages
are **template-driven and non-interactive** — no back-and-forth reply
content, just a recurring automated announcement from the same source, and
it is not marketing per the distinction above. Typical examples: vendor
security bulletins (e.g. an open-source project's security advisories),
recurring system/service status notifications, transactional/operational
automated receipts, routine listserv digests with no discussion attached to
them.

This is different from a listserv *discussion* thread (people replying with
actual content) or a one-off broadcast announcement — those get full
conversation treatment (subject to the gate), consistent with the Gmail
ingest task's "reduced scope, not out of scope" handling of broadcast lists.
The distinguishing question is not "is this automated," it's "would
archiving every instance in full add anything beyond the date and headline."

**Check the digest registry first — this is a lookup, not an inference.**
Call `match_digest_source(sender_email, subject, registry)` (registry loaded
once in Stage 1). A hit means append to the returned `output_file` directly;
you're done classifying. Only fall back to judgment when it returns `None`:

- **Recognizing digest-eligible sources on first sighting** (don't wait for
  a second occurrence just because the registry doesn't know this sender
  yet): treat a source as an established series immediately if any of these
  hold —
  - The sender name or body text self-describes as a digest/bulletin system
    (e.g. "automatic digest system," "security-news," "advisory").
  - The subject contains a series/issue identifier that implies an ongoing
    numbered sequence (e.g. `#2026-110`, `SA-2026-069`, a digest date range
    like "29 Jun to 1 Jul").
  - The sender address is a `noreply`/`no-reply`/system-style address tied
    to infrastructure the owner's institution operates or depends on (e.g.
    a repository server, an HR/payroll system, a web-archiving service).
  - A `None` result can also mean the registry's pattern-matcher just
    doesn't parse this particular source's subject idiom — if a
    `digest-*.md` file for this exact sender clearly already exists on disk,
    append to it rather than concluding it's a new source; consider fixing
    that file's `source_pattern` field so the registry picks it up correctly
    next time it's rebuilt.

Otherwise (no such signal, and only one instance seen so far, and no
existing digest file for this sender), archive as a full conversation and
only reclassify to digest on a later run once the repeating pattern is
directly observed.

Group digest-eligible messages by source (sender address or a stable subject
pattern), not by individual thread.

### Full conversation — gated by relevance

Everything that isn't trivial, marketing, or digest-eligible is a
full-conversation *candidate*: real correspondence (1:1 or group), listserv
discussions with actual reply content, one-off notifications with unique
substance, meeting-related threads with added text, forwards containing new
commentary, broadcast announcements. A candidate only actually gets archived
in full if it passes the **relevance gate**:

**Relevance gate — connects, even loosely, to something already in the
wiki.** A thread passes if any of the following hold:
- A participant (sender, or anyone in `To`/`Cc`) matches a `wiki/people/`
  entry, by email address or by name.
- The subject or body clearly concerns a project/topic that has a
  `wiki/topics/` page — match against the topic's title and `tags:`. A loose
  match counts: the thread doesn't need to name the topic page's exact
  title, just be recognizably about that subject.
- The thread concerns a documented `wiki/organizations/` entry as an
  organization (not just "was sent from an address at your own institution's
  domain" — see below).

**What does *not*, by itself, count as relevant:** the sender or recipient
sharing your own institution's email domain. Your home institution and
department are broad enough as organizations that this would make almost
everything pass trivially, defeating the point of the gate. The bar is a
connection to a *specific* documented person, topic, or organization — not
"happens to work here."

**When uncertain, lean toward passing the gate** — "even loosely relevant"
is deliberately generous. If a thread plausibly touches something tracked
but you're not fully sure, archive it; the failure mode to avoid is the
same one that motivated relevance-gating in the first place (drowning
signal in volume), not under-inclusion of borderline-real correspondence.

**If a candidate fails the gate:** do not archive it in full. Log it
instead — see Stage 7 (Candidate Entity Log).

---

## Stage 4: Write Conversation Files

One file per thread, in `wiki/email/`, flat (no subdirectories).

Filename pattern: `<YYYYMMDD>-<subject-slug>-<thread-id>.md`, where
`YYYYMMDD` is the date of the **first** message in the thread (never changes
across later runs, so the filename stays stable), and `<thread-id>` is the
**full** thread ID — not a truncated prefix. Gmail thread IDs are only 16 hex
characters, so a full ID is not an unreasonable filename component, and
truncating invites collisions: threads created close together in time share
leading hex digits. Use the full ID and this problem disappears entirely.
Use `slugify()` from `scripts/email_archive_helpers.py` for the subject slug.

Example: `20260615-example-collection-digitization-19a1b2c3d4e5f607.md`

### Idempotency check — do this before generating any filename

Never decide "this thread needs a new file" based on the current run's
classification alone. A thread can legitimately be encountered more than
once — across chunked backfill sub-windows (a thread active in both January
and March), across separate task invocations, or because a long-running
thread keeps accumulating new messages over many runs. Before writing
anything for a thread ID:

1. **Check the manifest first.** If the thread ID already has an entry in
   `.email_archive_manifest.json`:
   - `kind: "conversation"` → use the `output_file` path exactly as
     recorded. Do not generate a new filename, even if this run's subject-
     line normalization, slug logic, or first-message-date calculation would
     produce something different from what's on record (e.g. because the
     slug rules were refined after the file was created). Read the existing
     file and follow the "Updating an existing conversation file" procedure
     below.
   - `kind: "digest"` or `"marketing"` → append to that exact file.
   - `kind: "candidate"` → leave it logged as-is. Don't re-fetch and
     archive it in full just because the relevance index has grown since
     then — a newly created wiki page doesn't retroactively pull in old
     candidate-logged threads, only new activity going forward (see Stage 7).
   - `kind: "skipped"` → leave it alone; don't reconsider on a later run
     just because the classification rules changed since then, unless the
     user explicitly asks for a re-evaluation pass.
2. **If the thread ID has no manifest entry** (possible if the manifest was
   lost, edited by hand, or predates this task), don't assume it's new —
   grep existing files in `wiki/email/` for `thread_id: "<id>"` in the
   frontmatter before creating one. If a match turns up, treat it as case 1
   above and backfill the missing manifest entry from what the file already
   records (`last_message_id` is whatever message is last in the file;
   `message_count_archived` is however many `### Message N` blocks it has).
3. Only after both checks come back empty is this genuinely a new thread —
   proceed to generate a filename and write a new file.

### Timestamps

Gmail message timestamps (`internalDate`) are epoch milliseconds in UTC.
Convert to `config.TIMEZONE` using proper timezone-aware conversion (a
library/zoneinfo call, not a fixed UTC offset) so results stay correct
across daylight-saving transitions — a fixed offset will be wrong for part
of the year in any zone that observes DST. For local exports, convert the
`Date` header the same way.

### Handling appended/quoted prior messages

Email clients append the growing quoted history to the bottom of each new
reply, and different clients format that quoted block differently. Do not
re-transcribe quoted history — it is already stored (in full) as its own
message entry earlier in the same file. For each message, store only the
text the sender actually added: scan the message body for the **earliest**
occurrence of any of the following boundary markers, and cut there,
discarding everything from that point to the end of the message:

1. **Gmail-style attribution line:** `On <date/time>, <name> <email> wrote:`
   — match this across a possible line-wrap; the date/name and the word
   "wrote:" are sometimes split onto two lines by the client, so don't
   anchor the pattern to a single line.
2. **Outlook-style header block:** a line starting with `From:` (or
   `*From:*`) followed within the next few lines by `Sent:`, `To:`, and
   `Subject:` lines. The boundary is the start of that `From:` line, not the
   end of the header block.
3. **Classic top-post marker:** a line consisting of `-----Original
   Message-----` (or close variants).
4. **A run of consecutive `>`-quoted lines** (one or more `>` characters) of
   at least two lines, when neither of the above patterns matched first —
   the boundary is the first such line.

If a signature block happens to repeat *after* the cut point (common in
Gmail, which sometimes appends the sender's signature below the quoted
history rather than above it), that's fine to lose — it's a harmless
duplicate of the signature already stored on that person's earlier message
in the thread, and it's not worth complicating the extraction logic to
preserve it.

**If no boundary marker is found**, keep the full message text — do not
guess or truncate. Silently over-including a stray line of quoted text is a
far smaller error than silently deleting real content; when genuinely
unsure where the boundary falls, err toward keeping more, not less.

**Structured relay notifications are a separate case.** Document-comment
emails, project-tracker comment-notification emails, and similar
app-generated relay messages don't use any of the above conventions — they
re-render the *entire* cumulative comment/activity thread inside every
notification email by design. There is no textual "quote boundary" to find.
Instead, diff the current message's rendered list of comments/entries against
the previous message's list (in the same underlying thread) and keep only
the item(s) that are new.

**Use the helper script, don't hand-transcribe.** `scripts/email_archive_helpers.py`
implements the boundary rules above (`dequote_message()`), plus a thread
parser (`parse_thread()`) that splits a connector `get_thread` response's
`body_text` into per-message dicts. Run it via Bash rather than manually
scanning quoted text line-by-line — doing it by eye or with ad-hoc regexes
misses edge cases such as the Outlook-style header block. If your connector
returns a different response shape, adapt the parsing step but still pass
each message body through `dequote_message()`.

If a message is a forward that pastes in a conversation which is
**already archived under a different thread**, don't retranscribe that
pasted content either — write the forwarding message's own added text in
full, then add a one-line cross-reference: `Forwards: [wiki/email/<file>.md]`.

### Long or oversized threads

Some threads (many messages, or a few very long ones) will cause the
connector's thread fetch to exceed the tool's inline output size and return
an error naming a saved file path instead of inline JSON. This is not a
failure — the full response was still generated, just written to disk. Do not
attempt to work around it by fetching individual messages one at a time;
instead:

1. Parse the saved file as JSON (it's the same `{"result": {...}}` shape a
   normal response would have) — use
   `python scripts/email_archive_helpers.py --from-file <path>` (or call
   `parse_thread()` directly in a short Python snippet) rather than reading
   the raw dump with a text tool, since the file's lines are too long for
   line-oriented reading and are not meant to be read that way. (`--from-stdin`
   is also supported.)
2. Extract `result.body_text` (already split by the connector into
   `\n\n---\n\n`-separated per-message blocks with headers) and
   `result.messages[]` (for `id`, `internalDate`, `labelIds` per message).
3. Run every block through `dequote_message()` before writing it into the
   conversation file, exactly as with a normally sized thread.

Threads over roughly 8–10 messages, or with any single message over ~20KB,
are the ones likely to trip this — expect it rather than be surprised by it.

### Updating an existing conversation file

If `wiki/email/` already contains a file for this thread ID (check the
manifest — it records the mapping from thread ID to file), read it, find the
newest message already stored, and append only messages newer than that.
Update the frontmatter (`date_last_message`, `message_count`) and refresh the
Conversation Summary to reflect the full thread. Do not rename the file and
do not duplicate already-stored messages.

### Template

```markdown
---
type: email-conversation
thread_id: "<gmail_thread_id>"
subject: "Subject line (most recent, without Re:/Fwd: prefixes noted separately if changed)"
participants:
  - "Jane Doe <jdoe@example.edu>"
  - "John Smith <jsmith@example.org>"
date_started: YYYY-MM-DD
date_last_message: YYYY-MM-DD
message_count: N
has_attachments: true | false
source: gmail
date_archived: YYYY-MM-DD
---

# Email: [Subject]

## Conversation Summary

[2-4 neutral sentences: who is talking, about what, and the current state as
of the most recent message. Regenerate this each time the file is updated.]

## Related Wiki Pages

- [Jane Doe](../people/jane-doe.md) — [why relevant]
- [Example Collection Digitization](../topics/example-collection-digitization.md) — [why relevant]

(Write "None identified" if nothing matches. Generate these links via
`wiki_link_for_person()`/`wiki_link_for_topic()`/`wiki_link_for_org()` from
the Stage 1 relevance index rather than hand-deriving the slug/path from a
display name each time — the index already resolved this once for the
relevance gate; reuse that result instead of redoing the lookup.)

## Messages

### Message 1 — YYYY-MM-DD HH:MM

**From:** Jane Doe <jdoe@example.edu>
**To:** John Smith <jsmith@example.org>, Alex Rivera <arivera@example.edu>
**Cc:** Sam Lee <slee@example.org>
**Subject:** Original subject line
**Attachments:** filename.pdf, filename.docx (or "None")

> [verbatim body text of this message only — no summarizing, no
> paraphrasing. Quoted prior-message text stripped per the rule above.]

---

### Message 2 — YYYY-MM-DD HH:MM

**From:** ...
**To:** ...
**Subject:** ...
**Attachments:** ...

> [verbatim added text only]

---
```

Repeat the `### Message N` block per message, oldest first. Use a plain
blockquote or fenced block for the verbatim text — pick blockquote (`>`)
unless the body contains its own markdown-like syntax that would collide,
in which case use a fenced code block instead.

---

## Stage 5: Write Digest Files

One living file per source, in `wiki/email/`, appended to over time (not
re-dated per run).

Filename pattern: `digest-<source-slug>.md` — e.g. `digest-example-security-advisories.md`.

### Template

```markdown
---
type: email-digest
source_name: "Human-readable source name"
source_pattern: "sender address, domain, or subject prefix used to identify this source"
date_range_start: YYYY-MM-DD
date_range_end: YYYY-MM-DD
entry_count: N
source: gmail
---

# Email Digest: [Source Name]

## About

[1-2 sentences: what this source is and why it's condensed rather than
archived in full.]

## Entries

| Date | Subject | Note |
|------|---------|------|
| YYYY-MM-DD | [subject] | [one-line abbreviated content — e.g. severity, headline, affected item] |
```

The `source_pattern` field is what `build_digest_registry.py` reads (see
"Digest-source registry — how you configure it" above), so keep it accurate.

When updating an existing digest file, append new rows to the bottom of the
table (chronological order) and update `date_range_end` and `entry_count` in
the frontmatter. Do not rewrite or reorder existing rows.

---

## Stage 6: Write the Marketing Log

One single living file for the whole task: `wiki/email/marketing-log.md`.
Unlike digest files, this is not split per source — every marketing email
from every vendor goes in the same table, since the point is just a
searchable record that these arrived, not a per-vendor content summary.

Append new rows to the bottom (chronological order). No body content, no
"About" section, no per-source summarization — just enough to identify what
arrived, in case it's ever relevant to look back at.

### Template (create if it doesn't exist yet)

```markdown
---
type: email-marketing-log
source: gmail
date_range_start: YYYY-MM-DD
date_range_end: YYYY-MM-DD
entry_count: N
---

# Marketing Email Log

Commercial/promotional email is not archived in full (see
`EMAIL_ARCHIVE_TASK.md` Stage 3) — this is a running log of what arrived, for
reference only.

| Date | Sender | Subject |
|------|--------|---------|
| YYYY-MM-DD | Example Vendor <news@example.com> | Subject line |
```

When updating, append rows and update `date_range_end`/`entry_count` in the
frontmatter, same as a digest file.

---

## Stage 7: Write the Candidate Entity Log

One single living file: `wiki/email/candidate-entities-log.md`. This is
where full-conversation candidates land when they fail the Stage 3
relevance gate — a real correspondence thread that doesn't (yet) connect to
anything documented in the wiki. Modeled on the Gmail ingest task's
"Possible New Wiki Entries" idea, but lighter weight: **do not archive the
conversation content** — the whole point of failing the gate is that this
task doesn't do the fetch/transcribe work for it. Log just enough to let
the wiki owner (or the Gmail ingest task) decide whether it's worth a wiki
page.

Append new rows to the bottom (chronological order). No body content, no
quote-stripping, no per-message breakdown — one row per thread.

### Template (create if it doesn't exist yet)

```markdown
---
type: email-candidate-log
source: gmail
date_range_start: YYYY-MM-DD
date_range_end: YYYY-MM-DD
entry_count: N
---

# Candidate Entity Log

Threads that looked like real correspondence but didn't connect to an
existing wiki page, so weren't archived in full (see `EMAIL_ARCHIVE_TASK.md`
Stage 3). Logged here as candidates for a future `wiki/people/`,
`wiki/topics/`, or `wiki/organizations/` page — the Gmail ingest task, or
the wiki owner directly, decides whether to create one. If a page is created
later, re-running this task will pick up new activity on the same
sender/topic going forward (it won't retroactively re-fetch what's logged
here).

| Date | Sender | Subject | Note |
|------|--------|---------|------|
| YYYY-MM-DD | Name <email@example.org> | Subject line | [why it looked real but undocumented — e.g. "external collaborator, 3 threads this window"] |
```

When updating, append rows and update `date_range_end`/`entry_count` in the
frontmatter, same as a digest file. Record every logged thread ID in the
manifest with `"kind": "candidate"` so it isn't re-logged on a later run —
but note this means it also won't be automatically re-considered for full
archiving if the entity later gets a wiki page; that requires a fresh,
deliberate look (e.g. the user asking to backfill everything for a
newly documented person).

---

## Stage 8: Update the Email Archive Manifest

After writing or updating each file, record every processed thread/message
ID in `.email_archive_manifest.json`. Merge with the existing manifest; do
not overwrite it. Perform manifest writes one at a time (see the concurrency
notes above) — a single writer, never parallel agents.

```json
{
  "<thread_id>": {
    "kind": "conversation",
    "output_file": "wiki/email/20260615-example-collection-digitization-19a1b2c3d4e5f607.md",
    "last_message_id": "<message_id>",
    "last_message_date": "YYYY-MM-DD",
    "message_count_archived": N,
    "processed": "YYYY-MM-DD"
  },
  "<other_thread_id>": {
    "kind": "digest",
    "output_file": "wiki/email/digest-example-security-advisories.md",
    "last_message_date": "YYYY-MM-DD",
    "processed": "YYYY-MM-DD"
  },
  "<marketing_thread_id>": {
    "kind": "marketing",
    "output_file": "wiki/email/marketing-log.md",
    "last_message_date": "YYYY-MM-DD",
    "processed": "YYYY-MM-DD"
  },
  "<candidate_thread_id>": {
    "kind": "candidate",
    "output_file": "wiki/email/candidate-entities-log.md",
    "last_message_date": "YYYY-MM-DD",
    "processed": "YYYY-MM-DD"
  },
  "<skipped_thread_id>": {
    "kind": "skipped",
    "output_file": null,
    "processed": "YYYY-MM-DD"
  }
}
```

---

## Stage 9: Report

Print a brief plain-text summary:

```
Email archive complete — YYYY-MM-DD
  Window:                 last N days (or: YYYY-MM-DD to YYYY-MM-DD)
  Threads retrieved:      N
  Skipped (trivial):      N
  Marketing (logged only): N
  Digest entries added:   N (across M source files)
  Candidates logged (failed relevance gate): N
  Conversation files:
    new:     N
    updated: N
  Files written:
    wiki/email/20260615-example-collection-digitization-19a1b2c3d4e5f607.md (new)
    wiki/email/digest-example-security-advisories.md (updated, +3 entries)
    wiki/email/marketing-log.md (updated, +2 entries)
    wiki/email/candidate-entities-log.md (updated, +5 entries)
    ...
  Manifest entries added: N
```

Note any threads that were ambiguous between digest and full-conversation
treatment, any cross-thread forward references you created, and any
candidates that felt like a close call on the relevance gate.

### Error handling

- **Connector error or timeout on a search/fetch:** retry once. If it still
  fails, leave that thread out of the manifest (so the next run retries it)
  and list it in the report under "Not processed."
- **Oversized response saved to a file:** not an error — see "Long or
  oversized threads."
- **Helper script failure** (parse error, missing cache): delete
  `.relevance_index.json` / `.digest_registry.json` and re-run the script
  with `--force`; if a thread's body still can't be parsed, archive nothing
  for it, do not record it in the manifest, and report it.
- **Corrupt or missing manifest:** do not guess. Recover per Stage 4's
  "no manifest entry" rule (grep `wiki/email/` for `thread_id:`), rebuild the
  entries from the files on disk, then continue.
- **Partial runs:** write the manifest after each file (not only at the
  end), so an interruption leaves a consistent record and the rerun resumes
  without duplicating anything.

---

## Notes on Scope and Judgment

**This task filters for wiki relevance, not professional relevance.** Those
are different things: the Gmail ingest task's "professional relevance"
filter judges content on its merits (is this substantive, is it
work-related); this task's relevance gate judges connection (does it touch
something already documented), and applies only to the full-conversation
bucket — trivial/marketing/digest classification is unaffected. Within a
thread that passes the gate, there is no further filtering: personal or
social content sent from institutional accounts is still archived in full;
this is a complete record of documented relationships and topics, not a
curated one. Genuinely personal correspondence is in scope too, as long as
it clears the relevance gate; use ordinary discretion if something feels
clearly out of place (e.g. sensitive medical or financial content) but
default to archiving rather than omitting, unless your own policy (see
"Standing Policy Decisions") says otherwise. **Because the archive is a
verbatim record, decide deliberately what mail you are willing to put in it,
and who can read your wiki directory, before running this task.**

**No attachment content.** Never fetch, embed, or transcribe attachment
contents. List filenames only, in the `Attachments` field.

**Verbatim means verbatim.** Do not summarize or paraphrase message bodies
in the `Messages` section — that's what the Conversation Summary field is
for. The only text you're permitted to remove from a message body is a
trailing quoted-reply chain that duplicates content already stored
elsewhere in the same file (see Stage 4).

**Deduplication:** the email archive manifest is the primary mechanism.
Conversation filenames are stable (based on first-message date and full
thread ID), so re-runs update files in place rather than creating
duplicates.

---

## Standing Policy Decisions

This section records judgment calls so they are applied directly on future
runs rather than re-asked. The entries below are the design decisions that
shaped this task; **add your own dated entries** as you make calls about your
own mail (for instance, how to treat HR-related threads or deeply personal
messages), and apply them consistently. If a genuinely new category of
sensitive content shows up that no entry covers, pause and ask the user —
then record the decision here.

- **Marketing email:** excluded from archiving entirely (log only, Stage 6).
  Established after an early test archived an onboarding email and a product
  newsletter in full.
- **Deeply personal or high-stakes content written by the wiki owner**
  (e.g. a candid reflection on workplace conflict, a self-addressed email
  with draft documents): archive per the default inclusion policy — the
  archive's purpose is the owner's own record of their own working life. Edit
  this entry if you want a different default.
- **HR / candidate-feedback threads:** archived per default inclusion, no
  censorship, as the process is intended as an archive, not a curated or
  redacted record. Edit this entry (and add filtering) if your situation
  requires it.
- **Relevance-gating:** after a test backfill showed the volume was dominated
  by content with no lasting connection to anything tracked in the wiki, the
  design changed from "archive everything except trivial/marketing" to the
  relevance-gated design in Stage 3. Three decisions came with it:
  - Existing over-inclusive data was **pruned**, not grandfathered — files
    that failed the new gate were deleted and their manifest entries
    converted to `candidate` entries.
  - Registered digest sources (such as professional-community listservs) are
    **kept unconditionally**, exempt from the gate.
  - Full-conversation candidates failing the gate are **logged, not silently
    dropped** — see Stage 7.
- **Efficiency pass:** added (1) `scripts/build_relevance_index.py`, caching
  the people/topics/orgs lookup to `.relevance_index.json`; (2)
  `scripts/build_digest_registry.py`, deriving a sender/subject → digest-file
  lookup from existing digest files' `source_pattern` frontmatter; (3)
  `.gmail_manifest.json` as a real Pass 0 pre-filter
  (`email_archive_helpers.gmail_manifest_shortlist()`); (4) explicit guidance
  to issue searches and thread fetches concurrently, since only the write
  steps need to be serialized. None of this changes what gets archived — it
  only changes how cheaply the pipeline gets there.
- **Synthesis Pass added** as a separate, optional, on-demand extension: see
  "Optional: Synthesis Pass" below. It reads the verbatim archive and feeds
  the wiki's topic/people/organization pages, without altering the archive
  files themselves.
- **Synthesis Pass manifest writes centralized.** The first real run of the
  Synthesis Pass dispatched 14 parallel page-agents, several of which
  independently read-modified-saved `.email_synthesis_manifest.json` as they
  finished. Because each agent's in-memory copy predated the others'
  concurrent writes, the last save won and silently dropped the rest — 53 of
  117 expected entries were lost until manually reconciled. Fixed by making
  manifest writes the orchestrator's job alone
  (`scripts/record_email_synthesis.py`, a single load-once/save-once script),
  never the page-agents'. See "Concurrency and processing order."

---

## Optional: Synthesis Pass

Everything above (Stages 1-9) only archives — it deliberately does not
synthesize anything into `wiki/topics/`, `wiki/people/`, or
`wiki/organizations/`. This section documents a **separate, on-demand**
pass that does that synthesis, reading from the archive already sitting in
`wiki/email/` rather than fetching anything new from mail. It is not part
of the standard Stage 1-9 pipeline and does not run automatically as part
of it — invoke it explicitly (e.g., "synthesize the email archive for the
last 60 days") whenever the accumulated verbatim record has grown enough
to be worth folding into the wiki's reference pages. It needs no mail
connector at all, only the already-archived files.

**Relationship to the other two email tasks.** There are three
independent email-related tasks, each answering a different question and
each with its own manifest:

| Task | Source | Output | Manifest |
|------|--------|--------|----------|
| Gmail Ingest Task (`GMAIL_INGEST_TASK.md`) | Live Gmail (or export) | Synthesized dossier/topic updates | `.gmail_manifest.json` |
| Email Archive Task (Stages 1-9 above) | Live Gmail (or export) | Verbatim conversation/digest files in `wiki/email/` | `.email_archive_manifest.json` |
| **Synthesis Pass (this section)** | **Already-archived `wiki/email/` files** | Synthesized topic/people/org updates | `.email_synthesis_manifest.json` |

The Synthesis Pass is downstream of the Email Archive Task, not a
replacement for the Gmail Ingest Task: it only ever sees threads that
already passed the archive task's relevance gate (a documented person,
topic, or org match), so it will never surface a brand-new entity the way
the Gmail Ingest Task's "Possible New Wiki Entries" mechanism can. Treat
it as a way to mine the verbatim archive for detail that has accumulated
since the linked pages were last updated, not as a discovery mechanism.

### The one hard rule: the archive is read-only

Every other ingest pipeline in this wiki deletes (or moves) its source
file once it has been processed into a wiki page — see the file-disposal
step in `WIKI_UPDATE_TASK.md`'s Stage 2. **The Synthesis Pass never does
this.** Files in `wiki/email/` are treated as a permanent, append-only
verbatim record; this pass only ever reads them. Never delete, move,
rename, or edit a `wiki/email/*.md` file as part of this process, even
after its content has been fully folded into a topic or person page. The
only files this pass writes to are: pages under `wiki/topics/`,
`wiki/people/`, `wiki/organizations/`, and `.email_synthesis_manifest.json`.

### Token efficiency: summaries first, verbatim only when needed

The whole point of archiving verbatim is that the full text is there if
you ever need it — but re-reading it on every synthesis pass defeats the
purpose of having a `## Conversation Summary` at all. Default to reading
only:

- The frontmatter (`participants`, `subject`, `date_last_message`,
  `message_count`, `thread_id`).
- The `## Conversation Summary` section.
- The `## Related Wiki Pages` section — this is a direct reuse of the
  relevance-index lookup the archive task already did at archive time;
  do not re-derive relevance here.

Only open the `## Messages` section and read the verbatim body when the
summary is genuinely insufficient to write a good wiki update — e.g. a
specific decision's exact wording matters, a quote is worth preserving,
or the summary is ambiguous about who committed to what. This should be
the exception, not the default, for the large majority of files.

### Scope

By default, this pass only considers files with `type: email-conversation`
frontmatter. Digest files (`type: email-digest`), the marketing log, and
the candidate entity log are excluded by default — they are condensed logs
of recurring/non-substantive/undocumented content respectively, not
correspondence with synthesis-worthy narrative content (`--include-logs`
on the checker script includes them). Pull in a specific digest file by
hand only if you have a concrete reason (e.g., a run of crawl-report
entries that actually signals something worth a topic-page note); there is
no batch mode for it.

### Process

1. **Find what's due**, grouped by target wiki page:

   ```bash
   python scripts/check_email_synthesis.py --days 60
   # or a fixed window:
   python scripts/check_email_synthesis.py --since 2026-06-01
   # optional: --pretty, --include-logs
   ```

   This scans `wiki/email/*.md` for conversation files whose
   `date_last_message` (or `date_started`) falls in the window, checks
   `.email_synthesis_manifest.json` to skip anything already synthesized
   at its current message count, and groups the rest by target page
   (parsed from each file's own `## Related Wiki Pages` links). A file
   that links to more than one page appears once per page it's grouped
   under. Files with no related pages come back separately as `orphans` —
   there's nothing to synthesize them against; mark them processed
   (Step 4) without writing anything.

   There is no fixed default lookback the way the main archive task has
   14 days — state whatever window is useful each time you invoke this.
   Because the manifest tracks synthesis state per thread independently
   of the window you choose, an overly generous window costs nothing
   extra: already-synthesized files are skipped regardless of overlap.

2. **Dispatch by target page, not by file.** Each target page should be
   updated by exactly one agent (or one pass of your own context) so
   there's never a write conflict — this mirrors the "each unit targets a
   distinct wiki page" design of `WIKI_UPDATE_TASK.md`'s Stage 2. With
   dozens of target pages in a typical run, don't spawn one agent per
   page — bucket pages into a manageable number of dispatches (roughly
   10-15), grouping several small (1-2 file) pages into a single agent's
   batch and giving only the largest pages (a dozen+ files) their own
   dedicated agent. If you have no sub-agent facility, simply work through
   the pages yourself, one at a time. Give each agent:
   - The target page path(s) and their current content.
   - For each due file assigned to that page, **in the order
     `check_email_synthesis.py` gave them (oldest first)** — its subject,
     participants, dates, and `## Conversation Summary` text (not the
     full file, unless the agent determines it needs to open one for
     verbatim detail per the rule above). Tell the agent explicitly to
     work through the list in that order, not to reorder or batch by
     convenience — see "Concurrency and processing order" below for why.
   - The relevant page template and people/organization rules from
     `WIKI_UPDATE_TASK.md` (topic, people, and organization page templates
     and conventions) — reuse those verbatim, don't restate them per agent.
   - An explicit reminder not to touch the source `wiki/email/` file.
   - **An explicit instruction NOT to write to
     `.email_synthesis_manifest.json` themselves** — see below. They
     report resolution status in their final message only.

3. **Update pages** using the same templates, tone, and people/org rules as
   the main wiki update task. Treat each due email like an ingest document
   for the purposes of "what does this add that isn't already on the page"
   — but never touch the file itself, and never re-run the relevance gate
   (that decision was already made when the file was archived).

### Concurrency and processing order

**Page claims.** Before dispatching page-agents, run
`python scripts/agent_manifest.py prune --hours 4` and then
`python scripts/agent_manifest.py check <page> ...` for the pages in your
plan. Each agent claims its pages with
`python scripts/agent_manifest.py claim AGENT_ID "email synthesis" <pages>`,
writes only those pages, and releases them with
`python scripts/agent_manifest.py release AGENT_ID`. Two agents never edit the
same page; group all due files for one page into one agent. The claim itself is
atomic (taken under a file lock, `scripts/locking.py`), and the shared
manifests and logs are written through the same locking helpers, so a rare
overlap cannot corrupt them. They are still best written by the orchestrator
alone, as described next.

**Only the orchestrating context writes `.email_synthesis_manifest.json`
— page-agents never do, even though they have the tool access to.**
In the original run, several dispatched agents each independently loaded,
modified, and saved the manifest as soon as they finished their own page.
Because each agent's in-memory copy of the manifest was loaded before
seeing the others' concurrent additions, whichever agent saved last
silently overwrote everyone else's new entries — a classic
read-modify-write race. 117 files should have ended up recorded; only 64
survived until the run was manually reconciled by re-deriving the full
due-list and re-running the marks in a single pass. The fix isn't "write
more carefully," it's structural: with exactly one writer, the race is
impossible regardless of how many page-agents run concurrently.

So: when you brief each page-agent (Step 2), tell it plainly not to call
anything in `scripts/email_synthesis_manifest.py` (the module that loads,
marks, and saves the synthesis manifest) — its job ends with reporting,
per file, whether it was fully incorporated. Collect every agent's report,
then do the actual recording yourself (or via a single non-concurrent
script invocation) in Step 4.

**Process oldest-to-newest, not just for the manifest.** `check_email_synthesis.py`
already returns each page's file list sorted oldest-first by
`date_last_message` (falling back to `date_started`); pass that order
through to agents unchanged and have them work through it in sequence.
Two reasons, not just one:
- It's what makes centralizing the manifest write (above) easy to get
  right — the final recording pass naturally processes in chronological
  order, so the manifest's on-disk key order reads as a timeline instead
  of an arbitrary jumble, the same way the digest/marketing/candidate
  log tables already append oldest-at-the-bottom.
- Within a single page, a later email often only makes sense in light of
  an earlier one on the same page (a question and its resolution, an
  initial estimate and its correction) — synthesizing in chronological
  order means the agent has already internalized the earlier context
  before it needs to reconcile the later one, rather than writing the
  resolution first and then having to retrofit the setup around it.

4. **Record what was synthesized**, once all of a given run's page-agents
   have reported back. Build one JSON file mapping each file that was
   fully incorporated into *every* page it was grouped under (not just
   one, if it was grouped under several) to the list of those pages, then
   run the single recording script — never the synthesis-manifest module's
   functions directly, and never more than once concurrently:

   ```bash
   python scripts/record_email_synthesis.py resolutions.json
   # preview first, if you want:
   python scripts/record_email_synthesis.py resolutions.json --dry-run
   ```

   Where `resolutions.json` looks like:

   ```json
   {
     "wiki/email/<file>.md": ["wiki/topics/<slug>.md", "wiki/people/<slug>.md"],
     "wiki/email/<other>.md": ["wiki/topics/<slug>.md"]
   }
   ```

   The script sorts entries oldest-to-newest itself before writing, so
   you don't need to pre-sort the JSON. If an email is still only
   partially incorporated (e.g., one target page's agent failed or was
   skipped this run), omit it entirely so it's picked up again on the
   next run — don't include it with a partial page list.

5. **Index and commit**, same as the main wiki update task: run
   `python scripts/build_index.py`, then commit `wiki/` and
   `.email_synthesis_manifest.json` (if you keep the wiki under version
   control). `wiki/email/` itself should show no changes in the diff — if it
   does, something in this pass touched the archive and that's a bug in how
   it was run, not expected output.

---

*Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS. Licensed under GPL-3.0-or-later; see LICENSE.*
