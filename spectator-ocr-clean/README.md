# spectator-ocr-clean

spectator-ocr-clean.py — Clean ABBYY OCR text files from scanned newspaper archives.

Description
-----------
This repository contains `spectator-ocr-clean.py`, a lightweight, dependency-free
Python script for cleaning OCR-extracted plain-text files produced by
ABBYY or similar OCR engines on columnar newspapers. The script was written to
improve readability of OCR output for downstream text analysis, named-entity
extraction, and human review.

Key transformations performed
- Strip common column-gutter artifacts at the start of lines (underscores,
  pipes, tildes, stray spaces).
- Remove short or low-information lines that are likely OCR noise (rules,
  decorative symbols, mastheads).
- Resolve hyphenated line-breaks (rejoin `repor-\n ted` → `reported`) when the
  next line begins with a lowercase letter.
- Reassemble wrapped column lines into natural paragraphs.
- Write cleaned text files to an output directory and record per-file
  statistics in a TSV log.

Requirements
------------
- Python 3.6 or newer
- Standard library only (no external pip packages required)

Usage
-----
Run the script from the command line. At minimum provide an input directory
containing `.txt` OCR outputs and an output directory to receive cleaned files.

Examples:

```bash
python3 spectator-ocr-clean.py \
  --input ~/Code/archives-as-data/spectator/ocr \
  --output ~/Code/archives-as-data/spectator/ocr_cleaned

# Supply an explicit log location
python3 spectator-ocr-clean.py -i ./ocr -o ./ocr_cleaned -l ./ocr_cleaned/ocr_clean.log.tsv
```

Behavior and output
-------------------
- The `--output` directory is created if it does not exist and will contain the
  cleaned `.txt` files with the same filenames as the inputs.
- A TSV log is written (default: `OUTPUT_DIR/ocr_clean.log.tsv`) with basic
  statistics per file: original lines, noise removed, artifacts stripped,
  hyphens resolved, output paragraph count, and status.
- The script attempts conservative heuristics; always spot-check cleaned
  outputs before using them for irreversible processing.

Configuration
-------------
Tunable constants are defined near the top of the script (e.g. `MIN_WORD_LENGTH`,
`LONG_LINE_THRESHOLD`, `MIN_ALPHA_RATIO`). Modify those values if your OCR
corpus is substantially different from mid-20th century English newspapers.

License
-------
Copyright (C) 2026 Patrick R Wallace and Hamilton College LITS

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details:
https://www.gnu.org/licenses/gpl-3.0.en.html

Disclaimer (AI-assisted composition)
-----------------------------------
This code was written using Anthropic Claude Sonnet 4.6 and may not have been
fully reviewed for quality and security by a human reviewer. Use at your own
risk and please perform an independent review before deploying in production
or running on sensitive data.

Attribution & contact
---------------------
- Author / maintainer: Patrick R. Wallace (Hamilton College LITS)
- If you find issues or want improvements, please open a GitHub issue or
  contact the author.
