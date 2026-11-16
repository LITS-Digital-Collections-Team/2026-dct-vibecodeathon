# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
ingest_takeout.py — Process a Google Takeout .zip archive into ingest files.

Detects content inside the zip (Gmail mbox, Google Chat JSON) and produces
wiki-compatible ingest files for the wiki update task to process.

Gmail mbox → raw_ingest/gmail/  (dossier-update / topic-update / gmail-summary files)
Google Chat JSON → raw_ingest/  (extracted with descriptive names, handled by extract_text.py)

The zip itself is recorded in the wiki manifest once processing is complete so
that check_ingest.py does not re-surface it on future runs (zip is not a
supported extension for the general pipeline, but the manifest entry acts as
a processed-file record all the same).

Usage:
    python scripts/ingest_takeout.py <takeout.zip>
    python scripts/ingest_takeout.py <takeout.zip> --since 2026-05-01
    python scripts/ingest_takeout.py <takeout.zip> --days 30
    python scripts/ingest_takeout.py <takeout.zip> --list   # preview contents only
"""

from __future__ import annotations

import argparse
import email as emaillib
import email.policy
import email.utils
import mailbox
import re
import sys
import tempfile
import zipfile
import yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import RAW_INGEST_DIR, WIKI_DIR, PEOPLE_DIR, OWNER_EMAILS, TOPIC_KEYWORDS, local_today
from scripts.manifest import load_manifest, mark_processed, save_manifest


# ---------------------------------------------------------------------------
# Noise-filter: skip messages that are clearly auto-generated
# ---------------------------------------------------------------------------

_NOISE_SENDER_PATTERNS = re.compile(
    r"noreply|no-reply|donotreply|mailer-daemon|notifications?@|"
    r"forms-receipts|postmaster|bounce|support@|alerts?@|digest@",
    re.IGNORECASE,
)
_NOISE_SUBJECT_PATTERNS = re.compile(
    r"\[jira\]|\[github\]|ci/cd|build (passed|failed)|"
    r"password reset|verification code|mfa |two-factor|"
    r"benefits enrollment|pay stub|your receipt|order confirmation|"
    r"unsubscribe|mailing list|listserv digest|"
    r"automatic reply|out of office|delivery (status|failure)|"
    r"calendar invite accepted|calendar invite declined",
    re.IGNORECASE,
)


def is_noise(msg) -> bool:
    sender = str(msg.get("from", ""))
    subject = str(msg.get("subject", ""))
    if _NOISE_SENDER_PATTERNS.search(sender):
        return True
    if _NOISE_SUBJECT_PATTERNS.search(subject):
        return True
    return False


# ---------------------------------------------------------------------------
# Email body extraction
# ---------------------------------------------------------------------------

def get_plain_body(msg, max_chars: int = 1500) -> str:
    """Return plain text from the message, truncated to max_chars."""
    plain_parts = []
    html_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            if str(part.get("Content-Disposition", "")).lower().startswith("attachment"):
                continue
            ct = part.get_content_type()
            try:
                if ct == "text/plain":
                    plain_parts.append(part.get_content())
                elif ct == "text/html":
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(part.get_content(), "lxml")
                    for tag in soup(["script", "style"]):
                        tag.decompose()
                    html_parts.append(soup.get_text(separator=" "))
            except Exception:
                pass
    else:
        ct = msg.get_content_type()
        try:
            body = msg.get_content()
            if ct == "text/plain":
                plain_parts.append(body)
            elif ct == "text/html":
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(body, "lxml")
                for tag in soup(["script", "style"]):
                    tag.decompose()
                html_parts.append(soup.get_text(separator=" "))
        except Exception:
            pass

    parts = plain_parts if plain_parts else html_parts
    text = " ".join(p.strip() for p in parts if p and p.strip())
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


# ---------------------------------------------------------------------------
# People-index: email → wiki slug
# ---------------------------------------------------------------------------

def build_people_index() -> dict[str, dict]:
    """Return {email_lower: {slug, name}} from wiki/people/ frontmatter."""
    index = {}
    if not PEOPLE_DIR.exists():
        return index
    for fpath in PEOPLE_DIR.glob("*.md"):
        content = fpath.read_text(encoding="utf-8", errors="replace")
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            continue
        try:
            data = yaml.safe_load(match.group(1))
        except Exception:
            continue
        if not data or "email" not in data or not data["email"]:
            continue
        email = data["email"].strip().lower()
        index[email] = {"slug": fpath.stem, "name": data.get("name", fpath.stem)}
    return index


# ---------------------------------------------------------------------------
# Gmail mbox processing
# ---------------------------------------------------------------------------

def parse_mbox_from_zip(zf: zipfile.ZipFile, entry_name: str,
                         since: datetime) -> list[dict]:
    """Extract and parse an mbox entry from the zip, filtering by date."""
    with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with zf.open(entry_name) as src:
            tmp_path.write_bytes(src.read())

        mbox = mailbox.mbox(str(tmp_path))
        messages = []
        for raw_msg in mbox:
            try:
                msg = emaillib.message_from_string(
                    raw_msg.as_string(),
                    policy=emaillib.policy.default,
                )
                date_str = msg.get("date", "")
                if not date_str:
                    continue
                try:
                    msg_date = emaillib.utils.parsedate_to_datetime(date_str)
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                if msg_date < since:
                    continue
                if is_noise(msg):
                    continue

                messages.append({
                    "date": msg_date,
                    "date_str": msg_date.strftime("%Y-%m-%d"),
                    "subject": str(msg.get("subject", "(no subject)")).strip(),
                    "from": str(msg.get("from", "")).strip(),
                    "to": str(msg.get("to", "")).strip(),
                    "cc": str(msg.get("cc", "")).strip(),
                    "body": get_plain_body(msg),
                    "mbox_entry": entry_name,
                })
            except Exception:
                continue
    finally:
        tmp_path.unlink(missing_ok=True)

    return messages


def extract_email_address(field: str) -> str:
    """Pull the bare email address from a header value like 'Name <addr>'."""
    parsed = emaillib.utils.parseaddr(field)
    return parsed[1].lower().strip() if parsed[1] else ""


def all_participants(msg: dict) -> list[str]:
    """Return all email addresses (from/to/cc) for a message."""
    addrs = []
    for field in ("from", "to", "cc"):
        value = msg.get(field, "")
        if not value:
            continue
        # Multiple addresses separated by commas
        for part in value.split(","):
            addr = extract_email_address(part.strip())
            if addr:
                addrs.append(addr)
    return list(set(addrs))


def cluster_by_person(messages: list[dict], people_index: dict,
                       self_addresses: set[str] | None = None) -> dict[str, list[dict]]:
    """Map wiki slug → list of messages involving that person.

    self_addresses: email addresses belonging to the account owner. Messages
    match all participants, so without this filter the owner's own slug would
    collect every single message (useless for a dossier update).
    """
    clusters: dict[str, list[dict]] = {}
    skip = self_addresses or set()
    for msg in messages:
        for addr in all_participants(msg):
            if addr in skip:
                continue
            if addr in people_index:
                slug = people_index[addr]["slug"]
                clusters.setdefault(slug, []).append(msg)
    return clusters


def write_dossier_update(slug: str, name: str, msgs: list[dict],
                         date_str: str, output_dir: Path) -> Path:
    wiki_page = f"wiki/people/{slug}.md"
    fname = output_dir / f"dossier-{slug}-{date_str}.md"

    # Build interactions table
    rows = []
    for m in sorted(msgs, key=lambda x: x["date"]):
        summary = m["body"][:200].replace("|", "\\|").replace("\n", " ")
        if not summary:
            summary = "(no body)"
        subject = m["subject"][:80].replace("|", "\\|")
        rows.append(f'| {m["date_str"]} | {subject} | {summary}… |')

    # Collect unique topics mentioned
    body_blob = " ".join(m["body"] for m in msgs)
    topics = _infer_topics(body_blob)

    lines = [
        "---",
        f'type: dossier-update',
        f'subject_type: person',
        f'subject_name: "{name}"',
        f'wiki_page: "{wiki_page}"',
        f'source: takeout-gmail',
        f'date_extracted: {date_str}',
        f'threads:',
    ]
    for m in msgs[:10]:
        lines.append(f'  - date: {m["date_str"]}')
        lines.append(f'    subject: "{m["subject"][:80]}"')
    lines += [
        "---",
        "",
        f"# Dossier Update: {name}",
        "",
        "## New Interactions",
        "",
        "| Date | Subject | Summary |",
        "|------|---------|---------|",
    ] + rows + [""]

    if topics:
        lines += ["## Topics Raised", ""]
        for t in topics:
            lines.append(f"- {t}")
        lines.append("")

    fname.write_text("\n".join(lines), encoding="utf-8")
    return fname


def write_gmail_summary(msgs: list[dict], date_str: str, output_dir: Path,
                        period_start: str, period_end: str) -> Path:
    """Write a catch-all summary for messages not clustered by person."""
    fname = output_dir / f"gmail-summary-takeout-{date_str}.md"

    lines = [
        "---",
        "type: gmail-summary",
        "source: takeout-gmail",
        f"date_extracted: {date_str}",
        f"period_start: {period_start}",
        f"period_end: {period_end}",
        "---",
        "",
        f"# Gmail Sent Mail Summary: {period_start} to {period_end}",
        "",
        "## Threads",
        "",
    ]

    for m in sorted(msgs, key=lambda x: x["date"]):
        subject = m["subject"][:100]
        to_addr = m["to"][:80]
        snippet = m["body"][:300].replace("\n", " ")
        lines.append(f"**{m['date_str']} — {subject}**  ")
        lines.append(f"To: {to_addr}  ")
        lines.append(snippet)
        lines.append("")

    fname.write_text("\n".join(lines), encoding="utf-8")
    return fname


# Simple topic-keyword detector for tagging dossier updates
# Topic keywords come from config.py (TOPIC_KEYWORDS; override in config.local.json).
_TOPIC_KEYWORDS = TOPIC_KEYWORDS


def _infer_topics(text: str) -> list[str]:
    text = text.lower()
    found = []
    for pattern, label in _TOPIC_KEYWORDS.items():
        if re.search(pattern, text):
            found.append(label)
    return found


# ---------------------------------------------------------------------------
# Google Chat JSON extraction
# ---------------------------------------------------------------------------

def extract_chat_json(zf: zipfile.ZipFile, entry_name: str) -> Path:
    """Write a chat JSON from the zip to raw_ingest/ with a descriptive name."""
    # Derive a readable name from path like Google Chat/Groups/Name/messages.json
    parts = Path(entry_name).parts
    if len(parts) >= 3:
        # e.g. "Takeout/Google Chat/Groups/Project Team/messages.json"
        kind = "group" if any("group" in p.lower() for p in parts) else "dm"
        # The folder name containing messages.json is the conversation name
        conv_name = parts[-2] if len(parts) >= 2 else "conversation"
        conv_slug = re.sub(r"[^a-z0-9]+", "-", conv_name.lower()).strip("-")
        filename_part = "messages" if "messages" in Path(entry_name).name else Path(entry_name).stem
        out_name = f"google-chat-{kind}-{conv_slug}-{filename_part}.json"
    else:
        out_name = Path(entry_name).name

    dest = RAW_INGEST_DIR / out_name
    with zf.open(entry_name) as src:
        dest.write_bytes(src.read())
    return dest


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Process a Google Takeout .zip into wiki ingest files."
    )
    parser.add_argument("zip_path", help="Path to the Takeout .zip file")
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="Only process messages on or after this date (default: 30 days ago)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        metavar="N",
        help="Process messages from the last N days (default: 30; ignored if --since is set)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List zip contents and exit without processing",
    )
    parser.add_argument(
        "--self",
        metavar="EMAIL",
        dest="self_emails",
        action="append",
        default=[],
        help="Email address(es) belonging to the account owner — suppressed from person "
             "clustering so the owner's slug does not collect every sent message. "
             "Default: owner_emails from config.py / config.local.json.",
    )
    args = parser.parse_args()

    zip_path = Path(args.zip_path).resolve()
    if not zip_path.exists():
        print(f"Error: file not found: {zip_path}")
        sys.exit(1)

    if not zipfile.is_zipfile(zip_path):
        print(f"Error: not a valid zip file: {zip_path}")
        sys.exit(1)

    today = datetime.now(tz=timezone.utc)
    today_str = local_today().isoformat()

    if args.since:
        since_dt = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    else:
        since_dt = today - timedelta(days=args.days)

    print(f"Takeout: {zip_path.name}")
    print(f"Date filter: on or after {since_dt.date()}")

    with zipfile.ZipFile(zip_path) as zf:
        all_names = zf.namelist()

        if args.list:
            print(f"\nContents ({len(all_names)} files):")
            for n in all_names:
                print(f"  {n}")
            return

        # Categorise entries
        mbox_entries = [n for n in all_names if n.lower().endswith(".mbox")]
        chat_message_entries = [
            n for n in all_names
            if "google chat" in n.lower() and n.lower().endswith("messages.json")
        ]
        chat_info_entries = [
            n for n in all_names
            if "google chat" in n.lower() and n.lower().endswith("group_info.json")
        ]

        print(f"\nDetected: {len(mbox_entries)} mbox, "
              f"{len(chat_message_entries)} chat conversation(s)")

        people_index = build_people_index()
        self_addresses = set(e.lower() for e in (args.self_emails or OWNER_EMAILS))
        print(f"People index: {len(people_index)} known email addresses\n")

        output_files = []
        gmail_dir = RAW_INGEST_DIR / "gmail"
        gmail_dir.mkdir(parents=True, exist_ok=True)

        # ---- Gmail mbox files ----
        for entry in mbox_entries:
            label = Path(entry).stem  # e.g. "Sent", "Inbox"
            print(f"Parsing {entry}…", end=" ", flush=True)
            msgs = parse_mbox_from_zip(zf, entry, since_dt)
            print(f"{len(msgs)} messages in window")

            if not msgs:
                continue

            # Cluster by known person (skip owner's own address)
            person_clusters = cluster_by_person(msgs, people_index, self_addresses)

            # Collect messages not covered by any person cluster
            covered_ids = {id(m) for cluster in person_clusters.values() for m in cluster}
            unclustered = [m for m in msgs if id(m) not in covered_ids]

            period_start = min(m["date_str"] for m in msgs)
            period_end = max(m["date_str"] for m in msgs)

            for slug, cluster_msgs in person_clusters.items():
                name = people_index.get(
                    next((a for a in people_index if people_index[a]["slug"] == slug), ""),
                    {},
                ).get("name", slug)
                # Resolve name from slug
                for addr, info in people_index.items():
                    if info["slug"] == slug:
                        name = info["name"]
                        break
                fpath = write_dossier_update(slug, name, cluster_msgs, today_str, gmail_dir)
                output_files.append(fpath)
                print(f"  → {fpath.name} ({len(cluster_msgs)} messages)")

            if len(unclustered) >= 2:
                fpath = write_gmail_summary(
                    unclustered, today_str, gmail_dir, period_start, period_end
                )
                output_files.append(fpath)
                print(f"  → {fpath.name} ({len(unclustered)} unclustered messages)")

        # ---- Google Chat JSON ----
        for entry in chat_message_entries + chat_info_entries:
            print(f"Extracting {entry}…", end=" ", flush=True)
            fpath = extract_chat_json(zf, entry)
            output_files.append(fpath)
            print(f"→ {fpath.name}")

    # ---- Record zip in manifest ----
    manifest = load_manifest()
    # Use a synthetic wiki_page target representing the digest collection
    summary_target = Path(f"raw_ingest/gmail/gmail-summary-takeout-{today_str}.md")
    manifest = mark_processed(zip_path, summary_target, manifest)
    save_manifest(manifest)
    print(f"\nMarked in manifest: {zip_path.name}")

    print(f"\nDone. {len(output_files)} output file(s) written to raw_ingest/:")
    for f in output_files:
        rel = f.relative_to(RAW_INGEST_DIR)
        print(f"  raw_ingest/{rel}")


if __name__ == "__main__":
    main()
