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
claude-transcribe-batch.py — Batch-transcribe scanned manuscript images and PDFs
using the Anthropic Claude API (claude-sonnet-4-6).

Usage:
    python3 claude-transcribe-batch.py --input /path/to/images/ --output /path/to/transcriptions/
    python3 claude-transcribe-batch.py --input /path/to/scan.pdf  --output /path/to/transcriptions/

--input may be a directory (all supported files are processed) or a single file.

Supported input formats: .jpg .jpeg .png .tiff .tif .pdf

Requires ANTHROPIC_API_KEY set in your environment.

For PDF support, also install pdf2image and its poppler dependency:
    pip install pdf2image
    brew install poppler          # macOS
    apt install poppler-utils     # Ubuntu/Debian

Dependencies:
    pip install anthropic Pillow
    pip install pdf2image         # optional, for PDF input only
"""

import argparse
import base64
import io
import os
import sys
import time
from pathlib import Path
from typing import Tuple

import anthropic
from PIL import Image

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-6"

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}
SUPPORTED_EXTS = SUPPORTED_IMAGE_EXTS | {".pdf"}

# Maximum pixel dimension (longest side) before base64 encoding.
# Claude bills roughly (width × height) / 750 tokens per image.  At 1,500 px on
# the longest side, a letter-size scan costs ~2,000 tokens — legible for
# 19th-century cursive without excessive API cost.  Raise this value if you find
# that fine detail (e.g. very small handwriting) is being missed.
MAX_SIDE_PX = 1500

# JPEG quality for the re-encoded image sent to the API.  85 is a good balance
# between file size and legibility; lower values save tokens but may introduce
# compression artefacts that degrade OCR accuracy on thin pen strokes.
JPEG_QUALITY = 85

# Resolution used when rasterising PDF pages with pdf2image / poppler.
# 150 DPI gives ~1,240 × 1,600 px for a US letter-size page — enough to read
# period handwriting clearly.  Increase to 200 DPI if small script is missed,
# at the cost of larger intermediate images and more tokens per page.
PDF_DPI = 150

# Pricing for claude-sonnet-4-6 (USD per million tokens).
COST_PER_M_INPUT = 3.00
COST_PER_M_OUTPUT = 15.00

# Estimated text tokens consumed by the system prompt + user prompt per API call.
# System prompt: ~90 words ≈ 120 tokens; user prompt: ~25 words ≈ 32 tokens.
# Used only for the --dry-run cost estimate.
PROMPT_TOKENS_PER_CALL = 150

SYSTEM_PROMPT = (
    "You are an expert transcriptionist specialising in 19th-century English "
    "handwritten documents.  Transcribe the text exactly as written, preserving "
    "original spelling, punctuation, capitalisation, and line breaks as they "
    "appear on the page.  Mark any word you are uncertain about with [?] "
    "placed immediately after that word."
)

USER_PROMPT = (
    "Transcribe all handwritten text visible in this scanned document page.  "
    "Respond with the transcription only — no preamble, headings, or commentary."
)


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def resize_and_encode(img: Image.Image) -> str:
    """Resize to MAX_SIDE_PX on the longest side; return a base64 JPEG string.

    Converts to RGB before saving because JPEG does not support transparency or
    palette modes (RGBA, P) — common in PNG and some TIFF scans.  The conversion
    is lossless for greyscale/colour manuscript scans.
    """
    w, h = img.size
    if max(w, h) > MAX_SIDE_PX:
        scale = MAX_SIDE_PX / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------------
# Token estimation (used by --dry-run)
# ---------------------------------------------------------------------------

def estimate_image_tokens(img: Image.Image) -> int:
    """Estimate input tokens for one image after the resize step.

    Claude bills approximately (width × height) / 750 tokens per image.
    This function applies the same resize logic as resize_and_encode() so the
    estimate reflects the actual dimensions that would be sent to the API.
    Does not include the text-prompt overhead (see PROMPT_TOKENS_PER_CALL).
    """
    w, h = img.size
    if max(w, h) > MAX_SIDE_PX:
        scale = MAX_SIDE_PX / max(w, h)
        w, h = int(w * scale), int(h * scale)
    return max(1, round((w * h) / 750))


def dry_run_file(path: Path) -> int:
    """Return the estimated input-token count for transcribing one file.

    Loads and (for PDFs) rasterises the file exactly as the real run would,
    then sums per-page image-token estimates plus the fixed prompt overhead.
    No API calls are made.
    """
    if path.suffix.lower() == ".pdf":
        try:
            from pdf2image import convert_from_path
        except ImportError:
            print(
                "ERROR: pdf2image is required for PDF support.\n"
                "  pip install pdf2image\n"
                "  brew install poppler        (macOS)\n"
                "  apt install poppler-utils   (Ubuntu/Debian)",
                file=sys.stderr,
            )
            sys.exit(1)
        pages = convert_from_path(str(path), dpi=PDF_DPI)
        tokens = sum(estimate_image_tokens(p) for p in pages)
        tokens += PROMPT_TOKENS_PER_CALL * len(pages)
        return tokens
    else:
        img = Image.open(path)
        return estimate_image_tokens(img) + PROMPT_TOKENS_PER_CALL


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def transcribe_image_b64(client: anthropic.Anthropic, b64: str) -> Tuple[str, int, int]:
    """Send one base64-encoded JPEG to Claude and return the transcription plus token counts.

    Returns:
        (transcription_text, input_tokens, output_tokens)

    The request uses a two-part user message: the image block followed by a text
    instruction.  Claude's vision API requires at least one text block alongside
    the image; placing the instruction after the image mirrors how a human would
    look at the scan first, then receive directions.

    max_tokens=2048 is sufficient for a single densely written manuscript page
    (~500–800 words).  Increase this value if transcriptions are being cut off
    mid-page.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": USER_PROMPT},
                ],
            }
        ],
    )
    text = response.content[0].text.strip()
    return text, response.usage.input_tokens, response.usage.output_tokens


# ---------------------------------------------------------------------------
# Per-file processors
# ---------------------------------------------------------------------------

def process_image_file(client: anthropic.Anthropic, path: Path) -> Tuple[str, int, int]:
    """Transcribe a single image file.  Returns (text, input_tokens, output_tokens)."""
    img = Image.open(path)
    b64 = resize_and_encode(img)
    return transcribe_image_b64(client, b64)


def process_pdf_file(client: anthropic.Anthropic, path: Path) -> Tuple[str, int, int]:
    """Convert each PDF page to a JPEG at PDF_DPI and transcribe page by page.

    Returns (combined_text, total_input_tokens, total_output_tokens).

    pdf2image is imported lazily here so that the script remains usable for
    image-only workflows even if pdf2image/poppler are not installed — the
    ImportError is only raised when a PDF file is actually encountered.
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        print(
            "ERROR: pdf2image is required for PDF support.\n"
            "  pip install pdf2image\n"
            "  brew install poppler        (macOS)\n"
            "  apt install poppler-utils   (Ubuntu/Debian)",
            file=sys.stderr,
        )
        sys.exit(1)

    pages = convert_from_path(str(path), dpi=PDF_DPI)
    transcriptions: list[str] = []
    total_in = total_out = 0

    for i, page_img in enumerate(pages, start=1):
        if len(pages) > 1:
            print(f"    page {i}/{len(pages)}", file=sys.stderr, flush=True)
        b64 = resize_and_encode(page_img)
        text, in_tok, out_tok = transcribe_image_b64(client, b64)
        transcriptions.append(text)
        total_in += in_tok
        total_out += out_tok

    if len(transcriptions) == 1:
        return transcriptions[0], total_in, total_out

    # Multi-page PDFs: join pages with a separator so the output file is one
    # coherent document rather than one file per page.
    combined = "\n\n".join(
        f"--- Page {i} ---\n{t}" for i, t in enumerate(transcriptions, start=1)
    )
    return combined, total_in, total_out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-transcribe manuscript images and PDFs using Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Supported input formats: .jpg .jpeg .png .tiff .tif .pdf\n\n"
            "--input may be a single file or a directory.\n\n"
            "Set ANTHROPIC_API_KEY in your environment before running.\n"
            "PDF support requires: pip install pdf2image\n"
            "  and poppler:        brew install poppler (macOS)\n"
            "                      apt install poppler-utils (Ubuntu/Debian)"
        ),
    )
    parser.add_argument(
        "--input", "-i", required=True, metavar="PATH",
        help="File or directory of image/PDF files to transcribe",
    )
    parser.add_argument(
        "--output", "-o", required=True, metavar="DIR",
        help="Directory to write .txt transcription files (created if absent)",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Re-transcribe files that already have a .txt output (default: skip)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Estimate input tokens and cost without calling the API or writing files",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)

    # Accept either a single file or a directory as --input.
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_EXTS:
            print(
                f"ERROR: unsupported file type '{input_path.suffix}'.  "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTS))}",
                file=sys.stderr,
            )
            sys.exit(1)
        files = [input_path]
    elif input_path.is_dir():
        files = sorted(
            p for p in input_path.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        )
    else:
        print(f"ERROR: input path not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if not files:
        print(f"No supported files found in {input_path}", file=sys.stderr)
        sys.exit(0)

    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY environment variable is not set.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    total = len(files)

    # --dry-run: estimate token usage and cost without touching the API.
    if args.dry_run:
        print(
            f"DRY RUN — {total} file(s) found. "
            "Estimating input tokens (output tokens are not predictable in advance)...",
            file=sys.stderr,
        )
        grand_total = 0
        for path in files:
            try:
                est = dry_run_file(path)
                grand_total += est
                print(f"  {path.name}: ~{est:,} input tokens", file=sys.stderr)
            except Exception as exc:
                print(f"  {path.name}: ERROR — {exc}", file=sys.stderr)
        cost_est = grand_total / 1_000_000 * COST_PER_M_INPUT
        print(
            f"\nEstimated total input tokens : ~{grand_total:,}\n"
            f"Estimated input-only cost    : ~${cost_est:.4f} USD\n"
            f"(Output token cost excluded — varies by transcription length.)",
            file=sys.stderr,
        )
        return

    print(f"Found {total} file(s). Starting transcription...", file=sys.stderr)

    processed = skipped = errors = 0
    total_input_tokens = total_output_tokens = 0
    wall_start = time.time()

    for idx, path in enumerate(files, start=1):
        out_path = output_dir / (path.stem + ".txt")

        if out_path.exists() and not args.overwrite:
            skipped += 1
            continue

        print(f"[{idx}/{total}] {path.name}", file=sys.stderr, flush=True)

        try:
            if path.suffix.lower() == ".pdf":
                result, in_tok, out_tok = process_pdf_file(client, path)
            else:
                result, in_tok, out_tok = process_image_file(client, path)

            out_path.write_text(result, encoding="utf-8")
            processed += 1
            total_input_tokens += in_tok
            total_output_tokens += out_tok

        except anthropic.APIError as exc:
            print(f"    API error: {exc}", file=sys.stderr)
            errors += 1
        except Exception as exc:
            print(f"    ERROR: {exc}", file=sys.stderr)
            errors += 1

    elapsed = time.time() - wall_start
    cost = (total_input_tokens / 1_000_000 * COST_PER_M_INPUT
            + total_output_tokens / 1_000_000 * COST_PER_M_OUTPUT)

    print(
        f"\nDone. "
        f"Processed: {processed}  "
        f"Skipped (already transcribed): {skipped}  "
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
