"""
extract_places.py
-----------------
Uses the OpenAI GPT-4o Vision API to extract geographic place names from a
folder of scanned document images (JPG/PNG) and write the results to a CSV.

The script is resumable: it reads the output CSV on each run and skips any
image whose filename already appears there, so you can stop and restart freely
or run in batches with --limit.

Usage
-----
    # Process all unprocessed images in ./images/ → places.csv
    python extract_places.py

    # Override default directories / output file
    python extract_places.py --images /path/to/scans --output results.csv

    # Process only the next 10 unprocessed images (useful for spot-checking)
    python extract_places.py --limit 10

    # Preview what would be processed without calling the API
    python extract_places.py --dry-run

Requirements
------------
    pip install openai
    export OPENAI_API_KEY="sk-..."   # or set in your shell profile

Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
License: GNU General Public License v3.0 — see LICENSE or README.md
"""

import argparse
import base64
import csv
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Default paths — override at the command line; see --help
# ---------------------------------------------------------------------------
DEFAULT_IMAGES_DIR = Path(__file__).parent / "images"
DEFAULT_CSV_PATH   = Path(__file__).parent / "places.csv"

# Supported image extensions scanned from the images directory
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# ---------------------------------------------------------------------------
# GPT system prompt
#
# This prompt instructs the model to return LCNAF-style geographic headings.
# Edit the examples in the Rules section to match conventions relevant to
# your collection, but keep the JSON output contract intact so the parser
# in extract_places() continues to work.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a metadata specialist with expertise in Library of Congress Name Authority \
File (LCNAF) authorized geographic headings. You analyze scanned document images \
(letters, manuscripts, photographs, etc.) and extract geographic place names — \
including the location the document was created in and any places mentioned in \
the body text.

Return ONLY a JSON object with this exact structure (no prose, no markdown fences):
{"places": ["Place 1", "Place 2", "Place 3"]}

Rules:
- Include at most 3 places; if fewer are found, include only those.
- Use LCNAF authorized forms wherever possible, for example:
    "Glasgow (Scotland)", "London (England)", "New York (N.Y.)",
    "Boston (Mass.)", "San Francisco (Calif.)"
- Broader geographic terms such as "England", "Scotland", "California" are
  acceptable when no specific city or locality is identifiable.
- If no geographic place name can be identified, return {"places": []}.
- List places in order of prominence: the document's origin location first,
  then other locations mentioned in the text.
"""


# ---------------------------------------------------------------------------
# API key loading
# ---------------------------------------------------------------------------

def load_api_key() -> str:
    """
    Read the OpenAI API key from the OPENAI_API_KEY environment variable.
    Exits with an informative message if the key is not set.
    Never hardcode API keys in source files.
    """
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    sys.exit(
        "Error: OPENAI_API_KEY environment variable is not set.\n"
        "Export it in your shell before running:\n"
        "    export OPENAI_API_KEY=\"sk-...\""
    )


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def load_processed_filenames(csv_path: Path) -> set:
    """
    Return the set of filenames already recorded in the output CSV.
    Used to skip images that have been processed in a previous run.
    If the CSV does not exist yet, return an empty set.
    """
    if not csv_path.exists():
        return set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["filename"] for row in reader}


def ensure_csv_header(csv_path: Path) -> None:
    """
    Write the CSV header row if the file does not exist yet.
    This is called once at the start of a run so the output file is always
    a valid CSV even if no images are actually processed.
    """
    if not csv_path.exists():
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["filename", "place_1", "place_2", "place_3"])


def append_row(csv_path: Path, filename: str, places: list) -> None:
    """
    Append one result row to the CSV.
    places is a list of up to 3 strings; shorter lists are padded with empty
    strings so every row always has exactly 4 columns (filename + 3 places).
    """
    padded = (places + ["", "", ""])[:3]   # ensure exactly 3 place slots
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([filename] + padded)


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def collect_images(images_dir: Path) -> list:
    """
    Return all supported image files in images_dir, sorted alphabetically.
    Alphabetical order works correctly for zero-padded filenames (e.g.
    item_001.jpg, item_002.jpg, …) without needing a numeric comparator.
    """
    files = [
        p for p in images_dir.iterdir()
        if p.suffix.lower() in IMAGE_EXTENSIONS
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


def encode_image_b64(image_path: Path) -> str:
    """
    Read an image file and return its contents as a base64-encoded string
    suitable for embedding in an OpenAI API request.
    """
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def extract_places(client, image_path: Path) -> list:
    """
    Send one image to GPT-4o and return a list of up to 3 place name strings.

    The model is instructed to return a JSON object; we strip any accidental
    markdown code fences before parsing to handle occasional model formatting
    drift.
    """
    # Encode image as base64 data URI so it can be sent inline
    b64 = encode_image_b64(image_path)
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            # System message establishes the model's role and output contract
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    # Attach the image inline using the data URI scheme
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64}",
                            "detail": "high",   # use high-detail mode for dense handwriting
                        },
                    },
                    # Explicit extraction instruction accompanies every image
                    {
                        "type": "text",
                        "text": "Extract all geographic place names from this document image.",
                    },
                ],
            },
        ],
        max_tokens=200,
        temperature=0,  # deterministic output; place extraction is factual
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if the model wraps its JSON in them
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("` \n")

    data = json.loads(raw)
    places = data.get("places", [])

    # Guard against the model returning more than 3 items despite instructions
    return places[:3]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract geographic place names from document images using GPT-4o Vision.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python extract_places.py\n"
            "  python extract_places.py --images scans/ --output results.csv\n"
            "  python extract_places.py --limit 10\n"
            "  python extract_places.py --dry-run"
        ),
    )
    parser.add_argument(
        "--images",
        type=Path,
        default=DEFAULT_IMAGES_DIR,
        metavar="DIR",
        help=f"Directory containing image files to process (default: {DEFAULT_IMAGES_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CSV_PATH,
        metavar="CSV",
        help=f"Path to the output CSV file (default: {DEFAULT_CSV_PATH}). "
             "Existing rows are never overwritten; new results are appended.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N unprocessed images this run (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the images that would be processed without calling the API.",
    )
    args = parser.parse_args()

    # Validate images directory
    if not args.images.is_dir():
        sys.exit(f"Error: images directory not found: {args.images}")

    # Load API key early (even for dry-run) so misconfiguration is caught upfront
    api_key = load_api_key()

    # Determine which images still need processing
    already_done = load_processed_filenames(args.output)
    all_images   = collect_images(args.images)
    pending      = [p for p in all_images if p.name not in already_done]

    # Apply batch limit if requested
    if args.limit:
        pending = pending[: args.limit]

    if not pending:
        print("Nothing to process — output CSV is already up to date.")
        return

    # Report what will be processed
    print(f"Images to process: {len(pending)}")
    for p in pending:
        print(f"  {p.name}")

    if args.dry_run:
        print("(dry-run — no API calls made)")
        return

    # Create the CSV header row if this is a fresh output file
    ensure_csv_header(args.output)

    # Initialise the OpenAI client
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    # Process each pending image
    for image_path in pending:
        print(f"Processing {image_path.name} … ", end="", flush=True)
        try:
            places = extract_places(client, image_path)
            append_row(args.output, image_path.name, places)
            label = " | ".join(places) if places else "(none found)"
            print(f"→ {label}")
        except Exception as e:
            # Log the error and continue so one bad image does not halt a batch
            print(f"ERROR: {e}")
            print("  Skipping this image and continuing.")

    print(f"\nDone. Results written to {args.output}")


if __name__ == "__main__":
    main()
