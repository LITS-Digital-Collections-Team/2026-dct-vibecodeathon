# spectator-ner-extract

A small toolkit for extracting named entities from cleaned OCR text of the
Hamilton College Spectator (1947–1981) and similar student newspapers.

This folder contains two scripts:

- `spectator-ner-extract.py` — single-pass extractor that reads cleaned `.txt`
  files, runs spaCy NER, applies heuristic filtering and reconciliation rules,
  and writes three CSVs: `entities_people.csv`,
  `entities_orgs_events.csv`, and `entities_places.csv`.

- `spectator-ner-batch.py` — chunked extractor that processes files in
  configurable chunks and writes JSON checkpoints. A separate `combine`
  subcommand merges checkpoints into the same three CSV outputs (useful for
  large corpora and long-running jobs).

There is a `test-data/` directory with a small sample of cleaned OCR files for
quick local testing.

Requirements
------------
- Python 3.8 or newer
- spaCy 3.x
- A spaCy model (recommended: `en_core_web_sm` for speed; use `en_core_web_lg`
  for better results if compute permits)

Install spaCy and a model:

```bash
python3 -m pip install "spacy>=3.0" \
  --break-system-packages
python3 -m spacy download en_core_web_sm
```

Usage — single-file extractor
-----------------------------
Run the single-pass extractor to process a directory of cleaned `.txt` files and
produce CSVs in an output directory:

```bash
python3 spectator-ner-extract.py --input /path/to/cleaned_txts --output /path/to/output_csvs
```

Usage — chunked batch extractor
------------------------------
For very large corpora, use the chunked workflow to checkpoint progress and
avoid long uninterrupted runs.

1. Extract (single chunk):

```bash
python3 spectator-ner-batch.py extract --input /path/to/cleaned_txts \
    --checkpoint /path/to/checkpoints --start 0 --end 300
```

Run the `extract` step multiple times with different `--start`/`--end` ranges
(or script orchestration) to create many `chunk_XXXX_YYYY.json` checkpoint
files.

2. Combine checkpoints into final CSVs:

```bash
python3 spectator-ner-batch.py combine --checkpoint /path/to/checkpoints --output /path/to/output_csvs
```

Files produced
--------------
Each combine step writes the following CSV files to the `--output` directory:
- `entities_people.csv`
- `entities_orgs_events.csv`
- `entities_places.csv`

CSV columns: `name, earliest_date, latest_date, files` (files listed as
semicolon-separated `spec-YYYY-MM-DD_djvu.txt` names).

Behavior and heuristics
-----------------------
- PERSON entities are filtered by heuristic rules: professional titles are
  retained; courtesy titles (Mr/Ms) are retained only if a matching full
  name appears elsewhere in the same document; single-token names are dropped.
- ORG and EVENT entities require an alphabetic leading character and at least
  one mixed-case word to reduce headline/OCR noise.
- LOC/GPE entities are filtered to require one or more alphabetic tokens of
  length ≥3. Place names are mapped to rule-based LCSH forms for local and
  common international names (no external API calls).

Configuration
-------------
Abridged LCSH place tables are embedded in the scripts; the full tables used
by `spectator-ner-extract.py` are conservative and tuned for the corpus.
Adjust title lists (PROFESSIONAL_TITLES, COURTESY_TITLES) and NAME_CONNECTORS
as needed for other collections.

License
-------
Copyright (C) 2026 Patrick R. Wallace and Hamilton College LITS

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details:
https://www.gnu.org/licenses/gpl-3.0.en.html

AI-assisted composition disclaimer
---------------------------------
Parts of this code and accompanying documentation were written with assistance
from Anthropic Claude Sonnet 4.6. The code may not have been fully reviewed
for quality, correctness, or security by a human reviewer. Use at your own
risk and perform your own review before deploying or running on sensitive
data.

Attribution & contact
---------------------
- Author / maintainer: Patrick R. Wallace (Hamilton College LITS)
- Suggestions, bug reports, and pull requests are welcome.

