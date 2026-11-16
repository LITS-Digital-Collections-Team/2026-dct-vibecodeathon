# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
email_archive_helpers.py — Support functions for EMAIL_ARCHIVE_TASK.md.

Handles the two mechanical problems that turned out to be error-prone when
done by hand:

1. Stripping quoted prior-message text from a Gmail thread's concatenated
   body_text without losing real content (dequote_message / parse_thread).
2. Reading a get_thread response that was too large to return inline and
   was saved to a file instead (parse_thread_file).

Usage as a library (preferred, from within a Claude-run Bash snippet):

    python3 -c "
    import sys; sys.path.insert(0, 'scripts')
    from email_archive_helpers import parse_thread_file
    import json
    msgs = parse_thread_file('/path/to/saved-tool-result.txt')
    print(json.dumps(msgs, indent=2))
    "

Usage as a CLI:

    python3 scripts/email_archive_helpers.py --from-file <path>
    python3 scripts/email_archive_helpers.py --from-stdin < thread.json
"""

import json
import re
import sys
from datetime import datetime, timezone

import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from scripts.config import TIMEZONE, get_timezone
except ImportError:  # pragma: no cover - run from an unusual location
    TIMEZONE = "UTC"

    def get_timezone():
        return timezone.utc

LOCAL_TZ = get_timezone()

# ---------------------------------------------------------------------------
# Quote-boundary detection
# ---------------------------------------------------------------------------

# 1. Gmail-style attribution line. DOTALL-agnostic: allow the date/name and
#    "wrote:" to be split across a soft line-wrap, so match across newlines.
_GMAIL_ATTRIBUTION_RE = re.compile(
    r"\r?\nOn\s.{0,120}?\swrote:\s*\r?\n",
    re.DOTALL,
)

# 2. Outlook-style header block: "From:" (optionally wrapped in *asterisks*)
#    followed within a few lines by "Sent:"/"To:"/"Subject:".
_OUTLOOK_HEADER_RE = re.compile(
    r"\r?\n\*?From:\*?[^\n]*\r?\n"
    r"(?:[^\n]*\r?\n){0,4}?"
    r"\*?(?:Sent|Date):\*?[^\n]*\r?\n",
    re.IGNORECASE,
)

# 3. Classic top-post marker.
_ORIGINAL_MESSAGE_RE = re.compile(r"\r?\n-{3,}\s*Original Message\s*-{3,}\r?\n", re.IGNORECASE)

# 4. A run of two or more consecutive lines starting with one or more '>'.
_BLOCKQUOTE_RUN_RE = re.compile(r"(?:\r?\n>{1,}[^\n]*){2,}")


def dequote_message(text):
    """Return only the text a sender actually added, stripping quoted history.

    Scans for the earliest of several known quote-boundary conventions and
    cuts there. If nothing matches, returns the text unchanged — silently
    over-including a stray quote is a smaller error than silently deleting
    real content, so this never guesses a cut point it isn't confident about.
    """
    candidates = []
    for pattern in (_GMAIL_ATTRIBUTION_RE, _OUTLOOK_HEADER_RE, _ORIGINAL_MESSAGE_RE, _BLOCKQUOTE_RUN_RE):
        m = pattern.search(text)
        if m:
            candidates.append(m.start())
    if not candidates:
        return text.strip()
    return text[: min(candidates)].strip()


# ---------------------------------------------------------------------------
# Header parsing (From/To/Cc/Subject) out of a raw message block
# ---------------------------------------------------------------------------

_HEADER_LINE_RE = re.compile(r"^(From|To|Cc|Bcc|Date|Subject):\s*(.*)$", re.MULTILINE)


def split_header_and_body(block):
    """Split a raw per-message block into (headers dict, body text).

    Assumes a Gmail-connector style body_text convention: each block
    starts with From/To/Cc/Date/Subject lines, a blank line, then the body.
    """
    lines = block.splitlines()
    headers = {}
    body_start = 0
    for i, line in enumerate(lines):
        m = _HEADER_LINE_RE.match(line)
        if m:
            headers[m.group(1)] = m.group(2).strip()
            body_start = i + 1
        elif line.strip() == "" and headers:
            body_start = i + 1
            break
        elif not headers:
            continue
        else:
            break
    body = "\n".join(lines[body_start:])
    return headers, body


# ---------------------------------------------------------------------------
# Timestamp conversion
# ---------------------------------------------------------------------------

def epoch_ms_to_local(internal_date_ms):
    """Convert a Gmail internalDate (epoch ms, UTC) to a datetime in the
    configured time zone (config.TIMEZONE, default UTC), correct across
    daylight-saving transitions."""
    dt_utc = datetime.fromtimestamp(int(internal_date_ms) / 1000, tz=timezone.utc)
    return dt_utc.astimezone(LOCAL_TZ)


# Backward-compatible alias for the older function name.
epoch_ms_to_eastern = epoch_ms_to_local


# ---------------------------------------------------------------------------
# Thread parsing
# ---------------------------------------------------------------------------

def parse_thread(result):
    """Parse a get_thread `result` object into a list of per-message dicts.

    Each dict: {id, date (YYYY-MM-DD HH:MM, local time zone), from, to, cc, subject,
    body_added (quote-stripped), body_raw}.
    """
    body_text = result.get("body_text", "")
    blocks = re.split(r"\n\n---\n\n", body_text)
    messages_meta = result.get("messages", [])

    parsed = []
    for i, block in enumerate(blocks):
        headers, body = split_header_and_body(block)
        meta = messages_meta[i] if i < len(messages_meta) else {}
        date_str = None
        if meta.get("internalDate"):
            dt = epoch_ms_to_local(meta["internalDate"])
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        parsed.append({
            "id": meta.get("id"),
            "date": date_str,
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "cc": headers.get("Cc", ""),
            "subject": headers.get("Subject", ""),
            "body_added": dequote_message(body),
            "body_raw": body.strip(),
        })
    return parsed


def parse_thread_file(path):
    """Load a get_thread response saved to disk (oversized-output fallback)
    and parse it the same way as an inline response."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = data["result"] if "result" in data else data
    return parse_thread(result)


# ---------------------------------------------------------------------------
# Filename slug helper
# ---------------------------------------------------------------------------

def slugify(subject, max_words=8):
    """Turn a subject line into a filename-safe slug (lowercase, hyphenated)."""
    subject = re.sub(r"^(re|fwd?):\s*", "", subject, flags=re.IGNORECASE)
    words = re.findall(r"[A-Za-z0-9]+", subject.lower())
    return "-".join(words[:max_words]) or "no-subject"


# ---------------------------------------------------------------------------
# Gmail-manifest shortlist (Stage 2 Pass 0)
# ---------------------------------------------------------------------------

_MONTH_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.IGNORECASE,
)
_MONTH_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _note_month(note):
    """Best-effort month extraction from a free-text gmail-ingest note like
    '90-day goals..., Feb 25' or 'DC usage for April 2026'. Returns 1-12 or
    None if no month name is found. Deliberately loose — this only feeds a
    non-authoritative shortlist, never a decision to skip fetching."""
    m = _MONTH_RE.search(note or "")
    if not m:
        return None
    return _MONTH_NUM[m.group(1)[:3].lower()]


def gmail_manifest_shortlist(manifest_path, month, year=None):
    """Pull a shortlist of likely-relevant thread IDs for `month`/`year` out
    of the Gmail ingest task's `.gmail_manifest.json`, to check directly
    (via get_thread) before running Stage 2's Pass 1/Pass 2 searches.

    Only considers entries with a non-null `output_file` — those are ones
    the Gmail ingest task judged professionally relevant enough to write a
    dossier/topic update for, which is a strong (but not certain — that
    task's relevance test differs from this one's) prior that the thread
    will also pass this task's Stage 3 relevance gate.

    Returns (matched, unknown_date):
      matched       — thread_ids whose note text parses to this month.
      unknown_date  — relevant-per-gmail-ingest thread_ids whose note had no
                      parseable month; still worth checking, just lower
                      confidence about *when*. Don't drop these — surface
                      them so the caller can decide (e.g. fold into Pass 2).

    IMPORTANT: this is a lead, not a verdict. Every thread returned here
    still needs Stage 3's relevance gate applied fresh against the current
    wiki lookups — do not archive solely because it appears here, and do
    not assume a thread is irrelevant just because it's absent (the Gmail
    ingest task's filtering is stricter than this task's).
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        gmail_manifest = json.load(f)

    matched, unknown_date = [], []
    for thread_id, entry in gmail_manifest.items():
        if not entry.get("output_file"):
            continue
        note_month = _note_month(entry.get("note", ""))
        record = {"thread_id": thread_id, "note": entry.get("note", ""), "output_file": entry["output_file"]}
        if note_month == month:
            matched.append(record)
        elif note_month is None:
            unknown_date.append(record)
    return matched, unknown_date


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-file", help="Path to a saved get_thread JSON response")
    parser.add_argument("--from-stdin", action="store_true", help="Read JSON from stdin")
    parser.add_argument("--gmail-manifest-shortlist", nargs=2, metavar=("MANIFEST_PATH", "MONTH"),
                         help="Print the Pass 0 shortlist for a given month number (1-12)")
    args = parser.parse_args()

    if args.gmail_manifest_shortlist:
        path, month = args.gmail_manifest_shortlist
        matched, unknown_date = gmail_manifest_shortlist(path, int(month))
        print(json.dumps({"matched": matched, "unknown_date": unknown_date}, indent=2, ensure_ascii=False))
        return

    if args.from_file:
        messages = parse_thread_file(args.from_file)
    elif args.from_stdin:
        data = json.load(sys.stdin)
        result = data["result"] if "result" in data else data
        messages = parse_thread(result)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(messages, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
