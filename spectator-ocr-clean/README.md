# spectator-ocr-clean

`spectator-ocr-clean.py` — Clean ABBYY OCR text files from scanned newspaper archives.

Description
-----------
A lightweight, dependency-free Python script for cleaning OCR-extracted plain-text
files produced by ABBYY or similar engines on columnar newspapers. Written to improve
readability of OCR output for downstream text analysis, named-entity extraction, and
human review. Designed for the Hamilton College Spectator (1947–1980) but applicable
to any similarly structured newspaper OCR corpus.

Cleaning pipeline
-----------------
The script processes each file in three passes:

**Pass 1 — Strip artifacts and flag noise**
- Removes leading column-gutter characters from each line (underscores, pipes, tildes,
  stray whitespace, and lone leading dashes followed by a space).
- Marks lines as noise (collapses them to blank) if they are too short, contain no
  real words, consist mostly of 1–2 character tokens, or fall below the minimum
  alphanumeric-character ratio.

**Pass 2 — Collapse blank lines**
- Runs of consecutive blank lines (produced by noise removal and original formatting)
  are collapsed to a single blank line, preserving paragraph boundaries without
  introducing extra whitespace.

**Pass 3 — Dehyphenate and join**
- Paragraph blocks are reassembled from their component lines.
- Hyphenated line-breaks are resolved: if a line ends with `word-` and the next line
  begins with a lowercase letter, the hyphen is removed and the two pieces joined
  (e.g. `repor-` + `ted` → `reported`). Uppercase continuations are left intact as
  they are more likely to be legitimate compound usage.
- The remaining lines within each block are joined with single spaces to form natural
  paragraphs.

Requirements
------------
- Python 3.6 or newer
- Standard library only (no pip installs required)

Usage
-----
```
python3 spectator-ocr-clean.py --input INPUT_DIR --output OUTPUT_DIR [--log LOG_FILE]
```

Arguments:

| Flag | Short | Required | Description |
|------|-------|----------|-------------|
| `--input` | `-i` | Yes | Directory containing the original `.txt` OCR files |
| `--output` | `-o` | Yes | Directory to write cleaned `.txt` files into (created if absent) |
| `--log` | `-l` | No | Path for the TSV log file (default: `OUTPUT_DIR/ocr_clean.log.tsv`) |

Examples:

```bash
python3 spectator-ocr-clean.py \
  --input  ~/Code/archives-as-data/spectator/ocr \
  --output ~/Code/archives-as-data/spectator/ocr_cleaned

# Explicit log path
python3 spectator-ocr-clean.py \
  -i ./ocr \
  -o ./ocr_cleaned \
  -l ./ocr_cleaned/ocr_clean.log.tsv
```

Output
------
- Cleaned `.txt` files are written to `--output` with the same filenames as the inputs.
  Original files are never modified.
- A TSV log (`ocr_clean.log.tsv` by default) records per-file statistics:

  | Column | Description |
  |--------|-------------|
  | `filename` | Source filename |
  | `original_lines` | Line count before cleaning |
  | `noise_removed` | Lines removed as OCR noise |
  | `artifacts_stripped` | Lines where leading artifacts were removed |
  | `hyphens_resolved` | Hyphenated line-breaks rejoined |
  | `output_paragraphs` | Paragraph count in cleaned output |
  | `status` | `ok` or `ERROR: <message>` |

- Progress is printed to stdout as each file is processed.

Configuration
-------------
Three constants near the top of the script control noise detection. Adjust them if
your corpus differs significantly from mid-20th century English newspaper text:

| Constant | Default | Effect |
|----------|---------|--------|
| `MIN_WORD_LENGTH` | `3` | Shortest real word allowed; lines with no word this long are noise |
| `LONG_LINE_THRESHOLD` | `30` | Lines at or above this character count are always kept |
| `MIN_ALPHA_RATIO` | `0.40` | Minimum fraction of alphanumeric characters for mid-length lines |

Limitations
-----------
- Column-crossing artifacts (text from two adjacent columns interleaved on the same
  line) cannot be fully corrected without layout analysis; the script will reduce but
  not eliminate them.
- Noise heuristics are tuned for English-language columnar newspaper text. Corpora
  with very different typography or language may need parameter adjustment.

License
-------
Copyright (C) 2026 Patrick R. Wallace and Hamilton College LITS

This program is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details:
https://www.gnu.org/licenses/gpl-3.0.en.html

Disclaimer (AI-assisted composition)
-------------------------------------
This code was written with the assistance of Anthropic Claude Sonnet 4.6 and may not
have been fully reviewed for quality and security by a human reviewer. Use at your own
risk and perform an independent review before deploying in production or running on
sensitive data.

Attribution & contact
---------------------
- Author / maintainer: Patrick R. Wallace (Hamilton College LITS)
- For issues or improvement requests, open a GitHub issue or contact the author.
