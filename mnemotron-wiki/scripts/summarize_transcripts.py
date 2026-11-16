# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
summarize_transcripts.py — Pre-summarize large transcript files before wiki ingest.

Raw meeting transcripts and coaching-session recordings are often 30–100KB of
verbatim dialogue. Processing them directly in the wiki update task fills the
synthesis context window early and degrades quality for later files.

This script identifies large/transcript-like files, calls Claude to
produce a structured ~1KB summary, writes the summary as *_summary.md in the
same raw_ingest/ subdirectory, records the original in the manifest (so it is
not re-processed), and deletes the original.

The summary file is then picked up by check_ingest.py and processed normally
in Stage 2 — but the synthesis agent now works from a clean, structured
document rather than a 50KB verbatim transcript.

Usage (from wiki root):
    python scripts/summarize_transcripts.py             # process all eligible files
    python scripts/summarize_transcripts.py --dry-run   # show what would change
    python scripts/summarize_transcripts.py file [...]  # target specific files
    python scripts/summarize_transcripts.py --threshold N  # override byte threshold

Eligibility rules (either condition triggers summarization):
    1. Filename contains a TRANSCRIPT_PATTERN substring, OR
    2. File size exceeds TRANSCRIPT_THRESHOLD_BYTES and content contains
       dialogue-like timestamp patterns (HH:MM:SS or Speaker\nHH:MM:SS lines)

Files whose names already contain "_summary" are never re-summarized.
"""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import WIKI_ROOT, RAW_INGEST_DIR, FAILED_INGEST_DIR, SUPPORTED_EXTENSIONS
from scripts.manifest import load_manifest, mark_processed, save_manifest

# ---------------------------------------------------------------------------
# Tunable thresholds
# ---------------------------------------------------------------------------

TRANSCRIPT_THRESHOLD_BYTES = 8_000  # 8 KB — files over this are candidates

# Filename substrings that always flag a file as a transcript regardless of size.
TRANSCRIPT_FILENAME_PATTERNS = [
    "_transcript",
    "Personal Meeting Room",
    "coaching-session-transcript",
    "coaching_session_transcript",
]

# ---------------------------------------------------------------------------
# Summarization prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You extract structured information from raw meeting transcripts and session recordings
for a personal work wiki. Your output is a compact structured markdown file that will
be ingested by a wiki synthesis agent in place of the full transcript.

Write clearly and factually. Do not editorialize or soften observations. Be concise:
the target length is 600–1200 words total. Omit any section that has no real content.
"""

USER_PROMPT_TEMPLATE = """\
Produce a structured summary of the following transcript. Use this exact format:

---
type: {filetype}
participants: [comma-separated list of speaker names]
summarized_from: {filename}
---

# {title}

## Key Outcomes
[3–6 bullets: concrete results, decisions confirmed, milestones reached]

## Decisions Made
[Bulleted list. Each bullet: decision + 1-sentence rationale if stated]

## People & Relationship Observations
[Behavioral observations about specific people that belong in their people-page dossiers.
 Note the source channel as [meeting] for each item. Include candid statements, role
 clarifications, friction, or alignment signals. Omit neutral pleasantries.]

## Topics Covered
[Bulleted list of subjects discussed with 1–2 sentence notes on each]

## Action Items
[Owner: task description. Omit if none.]

## Notable Quotes
[2–4 verbatim or near-verbatim exchanges that are operationally significant or
 reveal character. Format as: Speaker: "quote"]

---

TRANSCRIPT:

{content}
"""

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

_TIMESTAMP_RE = re.compile(r"\b\d{2}:\d{2}:\d{2}\b")
_SPEAKER_LINE_RE = re.compile(r"^[A-Z][a-zA-Z ]{2,40}\n\d{2}:\d{2}:\d{2}", re.MULTILINE)


def _looks_like_transcript(text: str) -> bool:
    """Return True if *text* has a transcript-like timestamp/speaker pattern."""
    return bool(_SPEAKER_LINE_RE.search(text)) or (
        len(_TIMESTAMP_RE.findall(text)) >= 5
    )


def is_eligible(filepath: Path, threshold: int = TRANSCRIPT_THRESHOLD_BYTES) -> bool:
    """
    Return True if *filepath* should be summarized.

    A file is eligible if:
    - It is not already a summary (name contains "_summary")
    - It is not in the failed/ quarantine
    - Its extension is supported
    - Either its name matches a TRANSCRIPT_FILENAME_PATTERN, or it is large
      enough and its content looks like a dialogue transcript
    """
    if "_summary" in filepath.name.lower():
        return False
    if FAILED_INGEST_DIR in filepath.parents:
        return False
    if filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False

    name_lower = filepath.name.lower()
    if any(p.lower() in name_lower for p in TRANSCRIPT_FILENAME_PATTERNS):
        return True

    if filepath.stat().st_size >= threshold:
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return _looks_like_transcript(text)

    return False


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------

def _infer_filetype(filepath: Path) -> str:
    name = filepath.name.lower()
    if "coaching" in name:
        return "coaching-session"
    if "1on1" in name or "1-on-1" in name:
        return "1:1-meeting"
    if "transcript" in name or "meeting room" in name.lower():
        return "meeting-transcript"
    return "meeting-notes"


def summarize_file(filepath: Path) -> str:
    """Call Claude and return the structured summary as a string."""
    try:
        from scripts.llm import generate
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from llm import generate

    content = filepath.read_text(encoding="utf-8", errors="replace")
    # Truncate to keep input reasonable. 40_000 chars ≈ ~10K tokens; generous
    # enough for full context, small enough to keep a single call fast.
    if len(content) > 40_000:
        content = content[:40_000] + "\n\n[... truncated at 40,000 characters ...]"

    title = filepath.stem.replace("_", " ").replace("-", " ").title()
    filetype = _infer_filetype(filepath)

    prompt = USER_PROMPT_TEMPLATE.format(
        filetype=filetype,
        filename=filepath.name,
        title=title,
        content=content,
    )

    # llm.generate() already retries transient/rate-limit failures
    # internally; a raised LLMError here means it exhausted those.
    return generate(SYSTEM_PROMPT, prompt)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _collect_candidates(paths: list[str], threshold: int) -> list[Path]:
    """Resolve explicit paths or scan raw_ingest/ for eligible files."""
    if paths:
        return [Path(p) for p in paths if is_eligible(Path(p), threshold)]

    candidates = []
    for filepath in sorted(RAW_INGEST_DIR.rglob("*")):
        if filepath.is_file() and not filepath.name.startswith("."):
            if is_eligible(filepath, threshold):
                manifest = load_manifest()
                from scripts.manifest import is_processed
                if not is_processed(filepath, manifest):
                    candidates.append(filepath)
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-summarize large transcript files before wiki ingest."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show which files would be summarized without doing anything.",
    )
    parser.add_argument(
        "--threshold", type=int, default=TRANSCRIPT_THRESHOLD_BYTES,
        help=f"Byte threshold for large-file detection (default: {TRANSCRIPT_THRESHOLD_BYTES}).",
    )
    parser.add_argument(
        "files", nargs="*",
        help="Specific files to summarize. If omitted, scans all of raw_ingest/.",
    )
    args = parser.parse_args()

    os.chdir(WIKI_ROOT)
    eligible = _collect_candidates(args.files, args.threshold)

    if not eligible:
        print("No files eligible for summarization.")
        return

    print(f"{'Would summarize' if args.dry_run else 'Summarizing'} "
          f"{len(eligible)} file(s):\n")
    for f in eligible:
        size_kb = f.stat().st_size / 1024
        print(f"  {f.relative_to(WIKI_ROOT)}  ({size_kb:.1f} KB)")

    if args.dry_run:
        return

    print()
    manifest = load_manifest()

    for filepath in eligible:
        rel = filepath.relative_to(WIKI_ROOT)
        print(f"Summarizing: {rel} ...", end=" ", flush=True)

        summary = summarize_file(filepath)

        summary_path = filepath.with_name(filepath.stem + "_summary.md")
        summary_path.write_text(summary, encoding="utf-8")

        # Record the original in the manifest so it is never re-processed.
        # The "wiki_page" field points to the summary, which is where its
        # content ends up (the summary itself will then be processed into the
        # actual wiki page during Stage 2).
        manifest = mark_processed(
            filepath,
            summary_path.relative_to(WIKI_ROOT),
            manifest,
        )
        save_manifest(manifest)

        filepath.unlink()
        print(f"→ {summary_path.name}")

    print(f"\nDone. {len(eligible)} file(s) summarized.")


if __name__ == "__main__":
    main()
