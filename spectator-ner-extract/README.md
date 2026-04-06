# spectator-ner-extract

A three-script toolkit for extracting and cleaning named entities from cleaned OCR
text of the Hamilton College Spectator (1947–1981) and similar newspaper corpora.

## Scripts in this folder

| Script | Role in pipeline |
|--------|-----------------|
| `spectator-ner-extract.py` | **Step 1 (single-pass)** — reads all cleaned `.txt` files, runs spaCy NER, applies heuristic filters, and writes three entity CSVs in one pass. Best for corpora ≤ ~2,000 files. |
| `spectator-ner-batch.py` | **Step 1 (batch)** — same extraction logic but processes files in configurable index slices, saving a JSON checkpoint per slice. A separate `combine` subcommand merges all checkpoints into the three CSVs. Use for large corpora or when runs may be interrupted. |
| `spectator-reconcile-people.py` | **Step 2** — post-processes `entities_people.csv`: removes mis-classified place names, then deduplicates OCR name variants across 30+ years of scanned text using phonetic blocking, first-name expansion, and fuzzy matching. |

There is a `test-data/` directory containing a small sample of cleaned OCR files for quick local testing.

---

## Recommended workflows

### Small corpora (≤ ~2,000 files)

```
spectator-ocr-clean.py  →  spectator-ner-extract.py  →  spectator-reconcile-people.py
```

### Large or interruptible corpora

```
spectator-ocr-clean.py  →  spectator-ner-batch.py extract  (repeated for each chunk)
                         →  spectator-ner-batch.py combine
                         →  spectator-reconcile-people.py
```

---

## Requirements

| Dependency | Used by | Install |
|-----------|---------|---------|
| Python 3.8+ | all scripts | — |
| spaCy 3.x | `ner-extract`, `ner-batch` | `pip install spacy --break-system-packages` |
| spaCy model (`en_core_web_sm` recommended) | `ner-extract`, `ner-batch` | `python3 -m spacy download en_core_web_sm` |
| rapidfuzz | `reconcile-people` | `pip install rapidfuzz --break-system-packages` |

Using `en_core_web_sm` is ~3× faster than `en_core_web_lg` with comparable NER
quality on news text. Switch to `lg` if you need higher recall on uncommon names.

---

## Usage

### 1. spectator-ner-extract.py — single-pass extraction

Processes all `.txt` files in `--input` in one run using `nlp.pipe()` with
parallel workers (up to 4, auto-detected from CPU count).

```bash
python3 spectator-ner-extract.py \
    --input  /path/to/cleaned_txts \
    --output /path/to/output_csvs
```

| Flag | Short | Required | Description |
|------|-------|----------|-------------|
| `--input` | `-i` | Yes | Directory of cleaned `.txt` files |
| `--output` | `-o` | Yes | Directory to write CSV output files (created if absent) |

---

### 2. spectator-ner-batch.py — chunked extraction with checkpointing

**Step 2a — extract one chunk:**

```bash
python3 spectator-ner-batch.py extract \
    --input      /path/to/cleaned_txts \
    --checkpoint /path/to/checkpoints \
    --start 0 --end 300
```

Run the `extract` subcommand multiple times with non-overlapping `--start`/`--end`
index ranges to generate a set of `chunk_XXXX_YYYY.json` checkpoint files. Each
chunk can be run at a different time or on a different machine.

| Flag | Required | Description |
|------|----------|-------------|
| `--input` | Yes | Directory containing the `.txt` files (sorted alphabetically) |
| `--checkpoint` | Yes | Directory to write/read checkpoint `.json` files |
| `--start` | Yes | 0-based start index (inclusive) into the sorted file list |
| `--end` | Yes | End index (exclusive) |

**Step 2b — combine checkpoints into CSVs:**

```bash
python3 spectator-ner-batch.py combine \
    --checkpoint /path/to/checkpoints \
    --output     /path/to/output_csvs
```

| Flag | Required | Description |
|------|----------|-------------|
| `--checkpoint` | Yes | Directory containing the `chunk_*.json` files |
| `--output` | Yes | Directory to write the merged CSV files |

---

### 3. spectator-reconcile-people.py — people deduplication

Run after extraction on the resulting `entities_people.csv` and
`entities_places.csv`:

```bash
python3 spectator-reconcile-people.py \
    --people entities_people.csv \
    --places entities_places.csv \
    --outdir /path/to/reconciled_output
```

| Flag | Short | Required | Description |
|------|-------|----------|-------------|
| `--people` | `-p` | Yes | Path to `entities_people.csv` from the extraction step |
| `--places` | `-l` | Yes | Path to `entities_places.csv` from the extraction step |
| `--outdir` | `-o` | Yes | Directory for reconciled output files |

---

## Output files

### After extraction (ner-extract or ner-batch combine)

| File | Contents |
|------|----------|
| `entities_people.csv` | Personal names: one row per unique extracted form |
| `entities_orgs_events.csv` | Organizations and named events |
| `entities_places.csv` | Geographic places, LCSH-standardized where possible |

All three files share the same column schema:

| Column | Description |
|--------|-------------|
| `name` | Entity text as extracted (normalized) |
| `earliest_date` | ISO date of first appearance (`YYYY-MM-DD`) |
| `latest_date` | ISO date of most recent appearance |
| `files` | Semicolon-separated list of source filenames |

### After reconciliation (reconcile-people)

| File | Contents |
|------|----------|
| `entities_people_clean.csv` | Deduplicated people: OCR variants collapsed to a single canonical row, date range and file list merged |
| `entities_places_augmented.csv` | Original places plus names moved from the people file; moved rows are flagged for manual LCSH review |
| `reconciliation_report.tsv` | Audit trail: every merge decision with similarity score, block key, and chosen canonical form |

---

## Behavior and heuristics

### Entity extraction (ner-extract and ner-batch)

**People (`PERSON`):**
- Full first+last forms are kept.
- Professional/academic titles (Dean, Professor, Coach, Rev., Gen., etc.) + last name are kept.
- Courtesy titles (Mr./Mrs./Ms.) + last name are kept *only* if a matching first+last form appears elsewhere in the same file (within-document reconciliation).
- Single-token names, all-caps tokens (OCR headline noise), and names on the blocklist are dropped.
- Names longer than 5 tokens are rejected as sentence fragments.

**Organizations and events (`ORG`, `EVENT`):**
- Must begin with an alphabetic character.
- Must contain at least one capitalized word of three or more letters.
- Strings with pipe characters or runs of three or more digits are rejected as OCR garbage.

**Places (`GPE`, `LOC`):**
- Must contain at least one alphabetic word of three or more characters.
- Extracted forms are mapped to LCSH-standardized headings using a rule-based lookup table of ~200 entries. Unknown places are stored as extracted.

**Multiprocessing:** both extraction scripts use `nlp.pipe()` with `n_process` set to `min(4, cpu_count)` for parallel processing.

### People reconciliation (reconcile-people)

Runs in a two-stage pipeline:

**Stage 1 — Place keyword filter:** names containing words like `dormitory`,
`auditorium`, or ending in `building` are removed from the people file and
appended to `entities_places_augmented.csv` for manual LCSH review.

**Stage 2 — OCR name deduplication:**
1. Names are *comparison-normalised* (used for matching only, not stored):
   lowercased, OCR digit-for-letter substitutions applied (`8→e`, `0→o`, etc.),
   leading occupational words stripped (`Headwaiter Alex Cruden` → `alex cruden`),
   and common nicknames expanded to canonical forms (`bob` → `robert`).
2. Names are blocked into phonetic groups using `first_initial + Soundex(last_token)`.
   A secondary key on `Soundex(second_token)` catches concatenation artefacts.
3. Within each block, prefix matches are always merged; other pairs are merged if
   their `token_sort_ratio` (rapidfuzz) meets the configured threshold.
4. A Union-Find structure builds clusters; each cluster is collapsed to the
   most-attested, best-capitalised, digit-free canonical form.
5. An audit trail is written to `reconciliation_report.tsv`.

---

## Configuration

### Extraction scripts

| Constant | Default | Effect |
|----------|---------|--------|
| `PROFESSIONAL_TITLES` | (set, ~40 entries) | Title + last name forms that are unconditionally kept |
| `COURTESY_TITLES` | `mr, mrs, miss, ms, mme, mdme` | Title + last forms kept only when reconciled within the document |
| `NAME_CONNECTORS` | `de, van, von, …` | Lowercase tokens permitted inside multi-part names |
| `PERSON_BLOCKLIST` | (set) | Phrases that look like names but are not people |
| `LCSH_PLACES` | (dict, ~200 entries) | Rule-based LCSH authorized-form lookup table |

### Reconciliation script

| Constant | Default | Effect |
|----------|---------|--------|
| `FUZZY_THRESHOLD` | `88` | Minimum `token_sort_ratio` score to merge two names |
| `OCR_DIGIT_THRESHOLD` | `80` | Lower threshold when a name contains an OCR digit artefact |
| `MAX_BLOCK_SIZE` | `150` | Skip pairwise comparison in phonetic blocks larger than this |
| `PLACE_KEYWORDS` | (list) | Words that indicate a "person" name is really a place |
| `LEADING_CONTEXT_WORDS` | (set) | Occupational/descriptive words stripped before comparison |
| `FIRST_NAME_EXPANSIONS` | (dict, ~60 entries) | Nickname → canonical long-form name mapping |

---

## License

Copyright (C) 2026 Patrick R. Wallace and Hamilton College LITS

This program is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details:
https://www.gnu.org/licenses/gpl-3.0.en.html

## AI-assisted composition disclaimer

Parts of this code and accompanying documentation were written with assistance from
Anthropic Claude Sonnet 4.6. The code may not have been fully reviewed for quality,
correctness, or security by a human reviewer. Use at your own risk and perform your
own review before deploying or running on sensitive data.

## Attribution & contact

- Author / maintainer: Patrick R. Wallace (Hamilton College LITS)
- Suggestions, bug reports, and pull requests are welcome.

