# GPT Extract Place

Automatically extract geographic place names from a folder of scanned document images (letters, manuscripts, photographs, etc.) using the OpenAI GPT-4o Vision API. Results are written to a CSV with up to three place names per image, formatted as [Library of Congress Name Authority File (LCNAF)](https://id.loc.gov/authorities/names.html) authorized headings.

The script is **resumable**: it reads the output CSV before each run and skips any image already recorded there. You can stop and restart at any time, or use `--limit` to process in small batches for spot-checking.

---

## Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Setup](#setup)
- [Usage](#usage)
- [Output format](#output-format)
- [Configuration](#configuration)
- [Customizing the system prompt](#customizing-the-system-prompt)
- [Cost and rate limits](#cost-and-rate-limits)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Overview

For each unprocessed image, the script:

1. Encodes the image as a base64 data URI
2. Sends it to GPT-4o with a system prompt instructing the model to return a JSON object containing up to three LCNAF geographic headings
3. Parses the response and appends a row to the output CSV

Supported image formats: `.jpg` / `.jpeg` / `.png`

---

## Requirements

- Python 3.9 or higher
- An [OpenAI API key](https://platform.openai.com/api-keys) with access to `gpt-4o`

---

## Setup

```bash
# 1. Clone or copy this directory to your machine

# 2. Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate       # macOS / Linux
venv\Scripts\activate          # Windows

# 3. Install dependencies
pip install openai

# 4. Set your OpenAI API key as an environment variable
export OPENAI_API_KEY="sk-..."
# Add this line to your shell profile (~/.zshrc, ~/.bashrc, etc.) to persist it
```

> **Security note:** Never paste your API key directly into the script or commit it to version control.

---

## Usage

Place your image files in a folder (default: `images/` next to the script), then run:

```bash
# Process all images in ./images/ and write to ./places.csv
python extract_places.py

# Specify a different images directory and output file
python extract_places.py --images /path/to/scans --output my_results.csv

# Process only the next 10 unprocessed images (useful for reviewing output before a full run)
python extract_places.py --limit 10

# Preview what would be processed without making any API calls
python extract_places.py --dry-run

# Full help
python extract_places.py --help
```

### Arguments

| Argument | Description | Default |
|---|---|---|
| `--images DIR` | Directory containing images to process | `./images/` |
| `--output CSV` | Path to the output CSV file | `./places.csv` |
| `--limit N` | Process at most N unprocessed images this run | (all) |
| `--dry-run` | List pending images without calling the API | — |

---

## Output format

The script creates (or appends to) a CSV with four columns:

```
filename,place_1,place_2,place_3
scan_001.jpg,Glasgow (Scotland),London (England),
scan_002.jpg,New York (N.Y.),,
scan_003.jpg,,,
```

- `filename` — the image filename (no path)
- `place_1` through `place_3` — LCNAF-style geographic headings, most prominent first; empty if fewer than three places were identified

Images where no place names were found are still recorded, with all three place columns left blank. This ensures that re-running the script does not reprocess them.

---

## Configuration

Default paths are set near the top of `extract_places.py` and can also be overridden with the CLI arguments above:

```python
DEFAULT_IMAGES_DIR = Path(__file__).parent / "images"
DEFAULT_CSV_PATH   = Path(__file__).parent / "places.csv"
```

The set of accepted image extensions is also configurable:

```python
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
```

---

## Customizing the system prompt

The `SYSTEM_PROMPT` constant in `extract_places.py` controls what the model looks for and how it formats place names. The default prompt targets LCNAF authorized headings and is written for handwritten correspondence, but it can be edited for other document types or controlled vocabularies.

**Critical:** Keep the output contract line intact so the JSON parser continues to work:

```
Return ONLY a JSON object with this exact structure (no prose, no markdown fences):
{"places": ["Place 1", "Place 2", "Place 3"]}
```

---

## Cost and rate limits

Each image is sent as a high-detail Vision request. Approximate cost guidance (check [OpenAI pricing](https://openai.com/api/pricing/) for current rates):

- High-detail images are tiled; a typical 1000×1000 px scan uses roughly 1–3 image tiles
- At current GPT-4o pricing (~$0.01–0.02 per image) a batch of 100 images costs approximately $1–2

If you hit rate limits, the `--limit` flag can be used to spread processing across multiple sessions.

---

## Troubleshooting

**`OPENAI_API_KEY environment variable is not set`**
Export the variable in your current shell: `export OPENAI_API_KEY="sk-..."`. To make it permanent, add that line to `~/.zshrc` or `~/.bashrc`.

**`Error: images directory not found`**
Create an `images/` folder next to the script and place your image files there, or point to your folder with `--images /path/to/folder`.

**The model returns inconsistent place name formats**
Edit the examples in `SYSTEM_PROMPT` to include authorized headings from your specific collection. More examples in the prompt consistently improve adherence.

**A batch stops partway through**
Any successfully processed images are already saved to the CSV. Re-run the script with the same arguments — it will resume from where it left off.

---

## License

Copyright (C) 2026 Patrick R. Wallace and Hamilton College Library & Information Technology Services (LITS)

This program is free software: you can redistribute it and/or modify it under the terms of the **GNU General Public License** as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.
