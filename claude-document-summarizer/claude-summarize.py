#!/usr/bin/env python3
# Copyright (C) 2026 Patrick R. Wallace and Hamilton College LITS
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""
claude-summarize.py — Batch-summarize plain-text transcripts using the
Anthropic Claude API (claude-opus-4-6).

Usage:
    python3 claude-summarize.py --input DIR --output DIR [--overwrite] [--dry-run]

--input and --output must be different directories because both contain .txt
files — output summaries would overwrite source transcripts otherwise.

For documents that fit within Claude's 200K-token context window (the vast
majority of transcripts), a single API call produces the summary.  Documents
that exceed MAX_INPUT_TOKENS are automatically split into chunks, each
summarised separately, and then consolidated into one coherent final summary
in a second pass.

Requires ANTHROPIC_API_KEY set in your environment.

Dependencies:
    pip install anthropic
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Tuple

import anthropic

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-6"

# Conservative upper bound on input tokens per single API call.  Claude's
# context window is 200K tokens; keeping below 180K reserves headroom for the
# system prompt, response, and any variance in tokenisation estimates.
MAX_INPUT_TOKENS = 180_000

# Target size (in tokens) for each chunk when a document exceeds
# MAX_INPUT_TOKENS.  Smaller chunks mean more API calls; larger chunks risk
# approaching the context limit.  60K gives a comfortable margin below 180K
# when combined with the prompts.
CHUNK_TARGET_TOKENS = 60_000

# Maximum tokens to request in the model's response.  1,024 is generous for a
# <300-word summary; raise to 2,048 if the prompt is changed to request longer
# output (e.g. extended abstracts or item-level descriptions).
RESPONSE_MAX_TOKENS = 1_024

# Pricing for claude-sonnet-4-6 (USD per million tokens).
COST_PER_M_INPUT = 3.00
COST_PER_M_OUTPUT = 15.00

# Seconds to wait between file-level API calls.  Provides a basic rate-limit
# buffer; override at runtime with --delay.  Set to 0 to disable.
REQUEST_DELAY_SECONDS = 6

# System prompt: instructs Claude as a professional archivist producing neutral
# catalog descriptions.  The constraints (≤300 words, no PII, no value
# judgments) mirror the conventions used in the existing GPT summarizer and
# align with archival description standards.
SYSTEM_PROMPT = (
    "You are a professional archivist creating neutral descriptive summaries of "
    "transcribed documents for use in library catalogs and archival finding aids "
    "at Hamilton College Library, Information & Technology Services. Your role is "
    "description, not interpretation: avoid value judgments, inferences, or "
    "speculation about intent or meaning. Never use racist or sexist language, "
    "even if the source text contains such material — describe it neutrally rather "
    "than reproduce it. Summarise in fewer than 300 words, balancing succinctness, "
    "accuracy, readability, and completeness. Identify and name the main topics, "
    "people, organisations, and locations discussed. Never include email addresses, "
    "phone numbers, or URLs in your output."
)

# User prompt for a document that fits in a single context window.
SINGLE_PASS_PROMPT = (
    "Summarise the following transcript according to your instructions.  "
    "Respond with the summary only — no preamble, headings, or commentary.\n\n"
    "{text}"
)

# User prompt for each chunk of a document that is too long for a single call.
CHUNK_PROMPT = (
    "The following is part {n} of {total} of a long transcript.  "
    "Summarise this section according to your instructions.  "
    "Respond with the partial summary only — no preamble or commentary.\n\n"
    "{text}"
)

# User prompt for the consolidation pass: merges chunk summaries into one.
CONSOLIDATE_PROMPT = (
    "The following are partial summaries of consecutive sections of a single "
    "document.  Consolidate them into one coherent summary of the entire document "
    "according to your instructions.  Respond with the final summary only.\n\n"
    "{text}"
)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Estimate the token count for a block of text without calling the API.

    Uses the rule of thumb that English prose averages ~4 characters per token.
    This is a conservative approximation; the true count may be 10–20 % lower
    for typical transcripts.  Used only to decide whether chunking is needed —
    not for cost reporting (which uses actual usage from API responses).
    """
    return len(text) // 4


def count_tokens_api(client: anthropic.Anthropic, user_text: str) -> int:
    """Return the exact input-token count for a call via the token-counting endpoint.

    This makes a lightweight API call (no inference) and returns the precise
    token count that the corresponding messages.create() call would consume.
    Used by --dry-run to give accurate per-file estimates.
    """
    response = client.messages.count_tokens(
        model=MODEL,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}],
    )
    return response.input_tokens


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def call_claude(client: anthropic.Anthropic, user_text: str) -> Tuple[str, int, int]:
    """Send one request to Claude and return (response_text, input_tokens, output_tokens).

    Streaming is used so that long responses do not time out.
    get_final_message() blocks until the stream is complete and returns the
    full message object, including accurate usage counts.
    """
    with client.messages.stream(
        model=MODEL,
        max_tokens=RESPONSE_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}],
    ) as stream:
        final = stream.get_final_message()

    return (
        final.content[0].text.strip(),
        final.usage.input_tokens,
        final.usage.output_tokens,
    )


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def split_into_chunks(text: str, target_chars: int) -> list[str]:
    """Split text into chunks of approximately target_chars characters.

    Splits on double-newline (paragraph) boundaries where possible so that
    sentences are not cut mid-way.  If a single paragraph is longer than
    target_chars it is included as its own chunk unchanged.
    target_chars should be derived as CHUNK_TARGET_TOKENS × 4.
    """
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len > target_chars and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len + 2  # +2 for the re-inserted "\n\n" separator

    if current:
        chunks.append("\n\n".join(current))

    return chunks if chunks else [text]


# ---------------------------------------------------------------------------
# Per-file processor
# ---------------------------------------------------------------------------

def summarize_file(client: anthropic.Anthropic, path: Path) -> Tuple[str, int, int]:
    """Summarise one .txt file.  Returns (summary, total_input_tokens, total_output_tokens).

    Strategy:
    1. Estimate the token count from character length (no API call).
    2. If the estimate comfortably fits within MAX_INPUT_TOKENS, send a single
       request — this handles the vast majority of transcript files.
    3. If the estimate exceeds the threshold, split the document into
       CHUNK_TARGET_TOKENS-sized chunks, summarise each in turn, then
       consolidate the partial summaries in a second pass.
    """
    text = path.read_text(encoding="utf-8", errors="replace")

    single_prompt = SINGLE_PASS_PROMPT.format(text=text)
    estimated_tokens = estimate_tokens(single_prompt)

    if estimated_tokens <= MAX_INPUT_TOKENS:
        print(f"    single pass (~{estimated_tokens:,} estimated tokens)", file=sys.stderr, flush=True)
        return call_claude(client, single_prompt)

    # Document is too long for a single call — split into chunks.
    target_chars = CHUNK_TARGET_TOKENS * 4
    chunks = split_into_chunks(text, target_chars)
    print(
        f"    chunked: {len(chunks)} parts (~{estimated_tokens:,} estimated tokens total)",
        file=sys.stderr, flush=True,
    )

    partial_summaries: list[str] = []
    total_in = total_out = 0

    for i, chunk in enumerate(chunks, start=1):
        print(f"      chunk {i}/{len(chunks)}", file=sys.stderr, flush=True)
        prompt = CHUNK_PROMPT.format(n=i, total=len(chunks), text=chunk)
        summary, in_tok, out_tok = call_claude(client, prompt)
        partial_summaries.append(summary)
        total_in += in_tok
        total_out += out_tok

    # Consolidation pass: merge chunk summaries into a single coherent summary.
    combined = "\n\n".join(
        f"[Part {i}]\n{s}" for i, s in enumerate(partial_summaries, start=1)
    )
    consolidate_prompt = CONSOLIDATE_PROMPT.format(text=combined)
    final_summary, in_tok, out_tok = call_claude(client, consolidate_prompt)
    total_in += in_tok
    total_out += out_tok

    return final_summary, total_in, total_out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-summarize plain-text transcripts using Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Input files must be UTF-8 plain text (.txt).\n"
            "Set ANTHROPIC_API_KEY in your environment before running.\n\n"
            "--input and --output must be different directories."
        ),
    )
    parser.add_argument(
        "--input", "-i", required=True, metavar="DIR",
        help="Directory containing .txt transcript files",
    )
    parser.add_argument(
        "--output", "-o", required=True, metavar="DIR",
        help="Directory to write .txt summary files (created if it does not exist)",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Re-summarise files that already have output; default is to skip them",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help=(
            "Count input tokens and estimate cost without summarising. "
            "Uses the token-counting API (no inference charges)."
        ),
    )
    parser.add_argument(
        "--delay", type=float, metavar="SECONDS", default=REQUEST_DELAY_SECONDS,
        help=f"Seconds to wait between requests (default: {REQUEST_DELAY_SECONDS}; set to 0 to disable)",
    )
    args = parser.parse_args()

    input_dir = Path(args.input).resolve()
    output_dir = Path(args.output).resolve()

    if not input_dir.is_dir():
        print(f"ERROR: input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    if input_dir == output_dir:
        print(
            "ERROR: --input and --output must be different directories.\n"
            "Both contain .txt files; using the same directory would overwrite "
            "source transcripts with their summaries.",
            file=sys.stderr,
        )
        sys.exit(1)

    files = sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".txt"
    )

    if not files:
        print(f"No .txt files found in {input_dir}", file=sys.stderr)
        sys.exit(0)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    total = len(files)

    # --dry-run: use the token-counting API to get accurate per-file estimates
    # without running any inference.
    if args.dry_run:
        print(
            f"DRY RUN — {total} file(s) found. Counting tokens via API...",
            file=sys.stderr,
        )
        grand_total = 0
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                prompt = SINGLE_PASS_PROMPT.format(text=text)
                n = count_tokens_api(client, prompt)
                grand_total += n
                note = " (will chunk)" if n > MAX_INPUT_TOKENS else ""
                print(f"  {path.name}: {n:,} input tokens{note}", file=sys.stderr)
            except Exception as exc:
                print(f"  {path.name}: ERROR — {exc}", file=sys.stderr)
        cost_est = grand_total / 1_000_000 * COST_PER_M_INPUT
        print(
            f"\nEstimated total input tokens : {grand_total:,}\n"
            f"Estimated input-only cost    : ~${cost_est:.4f} USD\n"
            f"(Output token cost excluded — varies by summary length.)",
            file=sys.stderr,
        )
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Found {total} file(s). Starting summarisation...", file=sys.stderr)

    processed = skipped = errors = 0
    total_input_tokens = total_output_tokens = 0
    wall_start = time.time()

    for idx, path in enumerate(files, start=1):
        out_path = output_dir / path.name

        if out_path.exists() and not args.overwrite:
            skipped += 1
            continue

        print(f"[{idx}/{total}] {path.name}", file=sys.stderr, flush=True)

        try:
            summary, in_tok, out_tok = summarize_file(client, path)
            out_path.write_text(summary, encoding="utf-8")
            processed += 1
            total_input_tokens += in_tok
            total_output_tokens += out_tok

        except anthropic.APIError as exc:
            print(f"    API error: {exc}", file=sys.stderr)
            errors += 1
        except Exception as exc:
            print(f"    ERROR: {exc}", file=sys.stderr)
            errors += 1

        if args.delay > 0 and idx < total:
            time.sleep(args.delay)

    elapsed = time.time() - wall_start
    cost = (total_input_tokens / 1_000_000 * COST_PER_M_INPUT
            + total_output_tokens / 1_000_000 * COST_PER_M_OUTPUT)

    print(
        f"\nDone. "
        f"Processed: {processed}  "
        f"Skipped (already summarised): {skipped}  "
        f"Errors: {errors}",
        file=sys.stderr,
    )
    if processed > 0:
        print(
            f"\nMetrics:\n"
            f"  Runtime       : {elapsed:.1f}s\n"
            f"  Input tokens  : {total_input_tokens:,}\n"
            f"  Output tokens : {total_output_tokens:,}\n"
            f"  Est. cost     : ${cost:.4f} USD",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
