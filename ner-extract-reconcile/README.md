# ner-extract-reconcile

A toolkit for OCR cleaning, named-entity extraction, and authority-file reconciliation of digitised historical newspaper archives. Developed for the *Hamilton College Spectator* digitisation project; adaptable to any newspaper corpus with similar OCR characteristics.

---

## Contents

```
ner-extract-reconcile/
├── README.md                        ← this file
│
├── ocr-clean.py                     ← Stage 1: clean raw ABBYY OCR text
├── ner-extract.py                   ← Stage 2: extract named entities (single run)
├── ner-batch.py                     ← Stage 2 alt: chunked/distributed NER extraction
│
├── reconcile_people.py              ← Stage 3a: reconcile people entities
├── reconcile_places.py              ← Stage 3b: reconcile places entities
├── extract_lcnaf_names.py           ← Utility: extract name tokens from LCNAF
│
└── authority-lists/
    ├── lcnaf_geo_index.json         ← LCNAF geographic authority index (23 MB, pre-built)
    ├── lcnaf_given_names_common.txt ← Frequent LCNAF given-name tokens (≥5 records, 382 KB)
    ├── lcnaf_given_names.txt        ← All LCNAF given-name tokens (2.7 MB)
    ├── lcnaf_surnames.txt           ← All LCNAF surname tokens (12 MB)
    ├── hamilton-places.txt          ← Campus location whitelist
    └── campus-table.txt             ← Hamilton College building reference table
```

**Dependencies (all scripts):** Python 3.8+
**Additional dependencies:** `rapidfuzz` (reconcile scripts), `spaCy` with `en_core_web_sm` (NER scripts)

```bash
pip install rapidfuzz --break-system-packages
pip install spacy --break-system-packages
python3 -m spacy download en_core_web_sm
```

---

## Workflow overview

```
Raw OCR .txt files
       │
       ▼
ocr-clean.py          →  Cleaned .txt files
       │
       ▼
ner-extract.py        →  entities_people.csv
   (or ner-batch.py)               entities_places.csv
                                   entities_orgs_events.csv
       │
       ├──────────────────────────────────────────────────────┐
       ▼                                                      ▼
reconcile_people.py              →  entities_people_clean.csv
  (reads people + places)           entities_people_unverified.csv
                                    entities_places_augmented.csv  ──┐
                                    reconciliation_report.tsv        │
                                                                      │
                                                                      ▼
reconcile_places.py              →  entities_places_clean.csv
  (reads augmented places)          entities_places_verified.csv
                                    entities_places_unverified.csv
                                    entities_places_campus.csv
                                    places_filtered_out.csv
                                    places_reconciliation_report.tsv
                                    entities_places_lcnaf.csv  (with --lcnaf-data)
```

---

## Stage 1 — OCR cleaning: `ocr-clean.py`

Cleans ABBYY-generated OCR output from scanned columnar newspapers. Handles column-gutter artefacts, noise lines, hyphenated line breaks, and ragged paragraph wrapping.

### Usage

```bash
python3 ocr-clean.py \
    --input  /path/to/raw-ocr/ \
    --output /path/to/cleaned-ocr/ \
    --log    /path/to/ocr_clean.log.tsv   # optional
```

### Arguments

| Flag | Required | Description |
|------|----------|-------------|
| `--input`, `-i` | yes | Directory of raw `.txt` OCR files |
| `--output`, `-o` | yes | Directory to write cleaned `.txt` files |
| `--log`, `-l` | no | Path for TSV log (default: `OUTPUT/ocr_clean.log.tsv`) |

### What it does

1. Strips column-gutter characters (`_`, `|`, `~`, leading dashes)
2. Removes noise lines (too short, no real words, low alphanumeric ratio)
3. Collapses runs of blank lines to a single blank
4. Resolves hyphenated line breaks (joins split words)
5. Rejoins wrapped lines into natural paragraphs

### Output

- One cleaned `.txt` per input file, same filename, written to `--output`
- `ocr_clean.log.tsv` — per-file statistics: lines removed, artefacts stripped, hyphens resolved

---

## Stage 2 — Named entity extraction: `ner-extract.py`

Runs spaCy NER over all cleaned `.txt` files, classifies and validates extracted entities, standardises place names to LCSH headings, and writes three entity CSVs.

### Usage

```bash
python3 ner-extract.py \
    --input  /path/to/cleaned-ocr/ \
    --output /path/to/entities/
```

### Arguments

| Flag | Required | Description |
|------|----------|-------------|
| `--input`, `-i` | yes | Directory of cleaned `.txt` files |
| `--output`, `-o` | yes | Directory to write entity CSVs |

### Output files

All output CSVs share the same schema:

| Column | Description |
|--------|-------------|
| `name` | Entity string (title-cased; LCSH form for places) |
| `earliest_date` | ISO-8601 date of earliest appearance |
| `latest_date` | ISO-8601 date of latest appearance |
| `files` | Semicolon-delimited list of source filenames |

| File | Contents |
|------|----------|
| `entities_people.csv` | Personal names |
| `entities_orgs_events.csv` | Organisations and named events |
| `entities_places.csv` | Geographic places (LCSH-standardised) |

### Person classification rules

- **Keep:** Two or more proper name tokens (First Last, First M. Last)
- **Keep:** Professional/academic title + last name (Dean, Professor, Dr, etc.)
- **Keep if recurring:** Courtesy title + last name (`Mr. Williams`) only if the full form (`John Williams`) also appears in the same file
- **Drop:** Single tokens, all-caps strings, >5 tokens, blocklisted phrases

### Notes

- Uses `en_core_web_sm` with parser and lemmatizer disabled for speed
- Parallelises with `nlp.pipe()` using up to 4 processes
- Dates are parsed from filenames in `spec-YYYY-MM-DD_djvu.txt` format

---

## Stage 2 (alternative) — Distributed NER: `ner-batch.py`

Chunked/distributed version of the NER extraction step. Processes files in configurable index ranges, saving JSON checkpoints after each chunk. A separate `combine` step merges checkpoints into final CSVs. Use this for very large corpora or when you need fault-tolerant restartable processing.

### Usage

**Step 1 — extract a chunk** (run multiple instances in parallel or sequence):

```bash
python3 ner-batch.py extract \
    --input      /path/to/cleaned-ocr/ \
    --checkpoint /path/to/checkpoints/ \
    --start      0 \
    --end        200
```

**Step 2 — combine all checkpoints into final CSVs:**

```bash
python3 ner-batch.py combine \
    --checkpoint /path/to/checkpoints/ \
    --output     /path/to/entities/
```

### Arguments

| Subcommand | Flag | Required | Description |
|------------|------|----------|-------------|
| `extract` | `--input` | yes | Directory of cleaned `.txt` files |
| `extract` | `--checkpoint` | yes | Directory to write chunk JSON files |
| `extract` | `--start` | yes | First file index (0-based) for this chunk |
| `extract` | `--end` | yes | Last file index (exclusive) for this chunk |
| `combine` | `--checkpoint` | yes | Directory containing `chunk_*.json` files |
| `combine` | `--output` | yes | Directory for final CSV output |

### Parallel chunk processing example

```bash
# Assuming 800 files total; run 4 chunks in parallel
for start in 0 200 400 600; do
    end=$((start + 200))
    python3 ner-batch.py extract \
        --input /cleaned/ --checkpoint /ckpts/ \
        --start $start --end $end &
done
wait

python3 ner-batch.py combine \
    --checkpoint /ckpts/ --output /entities/
```

---

## Stage 3a — People reconciliation: `reconcile_people.py`

Cleans and deduplicates the people entity CSV. Filters out place-type names absorbed into the people list, then reconciles OCR name variants using phonetic blocking and fuzzy matching. Optionally validates final names against the LC Name Authority File.

### Usage

```bash
# Minimal (no LCNAF validation):
python3 reconcile_people.py \
    --people  entities_people.csv \
    --places  entities_places.csv \
    --outdir  output/

# With LCNAF name validation:
python3 reconcile_people.py \
    --people     entities_people.csv \
    --places     entities_places.csv \
    --outdir     output/ \
    --names-dir  authority-lists/
```

### Arguments

| Flag | Required | Description |
|------|----------|-------------|
| `--people`, `-p` | yes | Path to `entities_people.csv` |
| `--places`, `-l` | yes | Path to `entities_places.csv` |
| `--outdir`, `-o` | yes | Directory for output files |
| `--names-dir`, `-n` | no | Directory containing LCNAF name lists (enables name validation) |

### Output files

| File | Contents |
|------|----------|
| `entities_people_clean.csv` | Reconciled people (LCNAF-verified if `--names-dir` given) |
| `entities_people_unverified.csv` | Names that failed LCNAF check — review manually (only with `--names-dir`) |
| `entities_places_augmented.csv` | Original places + place-type names moved from people |
| `reconciliation_report.tsv` | Every merge decision: names, similarity scores, merge reason |

### Processing stages

1. **Place keyword filter** — removes names containing place-type words (`dormitory`, `building`, `auditorium`, etc.); moves them to `entities_places_augmented.csv`
2. **OCR normalisation** — applies digit-for-letter substitutions (8→e, 1→l, 0→o, etc.)
3. **Comparison normalisation** — strips occupational prefixes (`Headwaiter`, `Librarian`, `Coach`, etc.); expands nicknames to canonical forms (`Bob`→`Robert`, `Bill`→`William`, etc.)
4. **Phonetic blocking** — groups names by first-initial + Soundex(last token) to limit pairwise comparisons
5. **Fuzzy matching** — token-sort-ratio ≥ 88; lower threshold (80) when OCR digits present; temporal-proximity rule for borderline scores
6. **LCNAF name validation** *(with `--names-dir`)* — two-tier check:
   - Entries in ≥3 source files pass unconditionally (noise is single-issue; real people recur)
   - Single/double-file entries: first token of normalised name must appear in `lcnaf_given_names_common.txt`

### Tunable parameters (top of script)

| Constant | Default | Effect |
|----------|---------|--------|
| `FUZZY_THRESHOLD` | 88 | Minimum token-sort-ratio for a merge |
| `OCR_DIGIT_THRESHOLD` | 80 | Lower threshold when a digit is present |
| `TEMPORAL_THRESHOLD` | 78 | Floor for temporal-proximity merges |
| `DATE_PROXIMITY_DAYS` | 365 | Max days between date ranges for temporal rule |
| `MAX_BLOCK_SIZE` | 150 | Skip pairwise comparison in blocks larger than this |

### Authority lists used

| File | Purpose |
|------|---------|
| `lcnaf_given_names_common.txt` | Primary validation list (≥5 occurrences in LCNAF) |
| `lcnaf_given_names.txt` | Fallback if common list not present |

---

## Stage 3b — Places reconciliation: `reconcile_places.py`

Filters, deduplicates, and optionally reconciles place entities to LC authority headings. Validates geographic status using an internal LCSH whitelist and structural heuristics, deduplicates OCR variants by phonetic blocking and fuzzy matching, separates campus locations from geographic places, and optionally enriches verified places with LCNAF preferred forms.

### Usage

```bash
# Minimal (LCSH validation and deduplication only):
python3 reconcile_places.py \
    --places  entities_places_augmented.csv \
    --outdir  output/

# With campus whitelist:
python3 reconcile_places.py \
    --places       entities_places_augmented.csv \
    --outdir       output/ \
    --campus-list  authority-lists/hamilton-places.txt

# With campus whitelist + regional authority list:
python3 reconcile_places.py \
    --places         entities_places_augmented.csv \
    --outdir         output/ \
    --campus-list    authority-lists/hamilton-places.txt \
    --regional-list  authority-lists/places_within_300_miles_clinton.txt

# Full pipeline (LCSH + campus whitelist + regional list + LCNAF authority enrichment):
python3 reconcile_places.py \
    --places         entities_places_augmented.csv \
    --outdir         output/ \
    --campus-list    authority-lists/hamilton-places.txt \
    --regional-list  authority-lists/places_within_300_miles_clinton.txt \
    --lcnaf-data     authority-lists/
```

### Arguments

| Flag | Required | Description |
|------|----------|-------------|
| `--places`, `-p` | yes | Path to `entities_places_augmented.csv` |
| `--outdir`, `-o` | yes | Directory for output files |
| `--min-files`, `-m` | no | Min source files for unknown entries (default: 2) |
| `--campus-list` | no | Campus locations whitelist file (one name per line; `#` comments OK) |
| `--regional-list` | no | Regional place-name authority list (one LCNAF/LCSH heading per line; `#` comments OK). Names in this list are treated as verified, take priority over the full LCNAF index, and rescue single-file entries that would otherwise be dropped as low-frequency noise. See [Regional authority list](#regional-authority-list) below. |
| `--lcnaf-data` | no | Directory containing `lcnaf_geo_index.json` (enables LCNAF enrichment). If the index file is absent, it is built from `names.skosrdf.jsonld` in the same directory. |

### Output files

| File | Contents |
|------|----------|
| `entities_places_clean.csv` | All kept entries (verified + unverified + campus combined) |
| `entities_places_verified.csv` | LCSH heading confirmed — ready for indexing or export |
| `entities_places_unverified.csv` | Geographic but no LCSH match — review manually |
| `entities_places_campus.csv` | Hamilton campus facilities (moved from people or matched via whitelist) |
| `places_filtered_out.csv` | Dropped entries with `drop_reason` audit column |
| `places_reconciliation_report.tsv` | Every merge decision with similarity scores |
| `entities_places_lcnaf.csv` | Clean entries + `lcnaf_form` column *(only with `--lcnaf-data`)* |

### Processing stages

1. **Geographic validity check** — four-tier filter applied in order:
   - *Tier 1: LCSH whitelist* — known geographic heading in the built-in `LCSH_TABLE` → keep (verified)
   - *Tier 2: Regional authority list* *(with `--regional-list`)* — name matches the regional list → keep (verified). Also rescues single-file entries that would otherwise fail the frequency gate.
   - *Tier 3: Full LCNAF index* *(with `--lcnaf-data`)* — name matches the LCNAF geographic authority → keep (verified)
   - *Tier 4: Structural pass / drop* — looks like a place (proper capitalisation, no blocklist words, appears in ≥ `--min-files` source files) → keep (unverified); otherwise → `places_filtered_out.csv`
2. **Campus detection** — entries moved from people with `[moved from people]` annotations, or matching `--campus-list`, go to `entities_places_campus.csv`
3. **OCR deduplication** — same phonetic blocking and fuzzy matching as people reconciliation
4. **LCNAF enrichment** *(with `--lcnaf-data`)* — looks up each verified/clean entry in the LCNAF geographic authority index using a two-key strategy:
   - *Full key* — retains qualifier: `Clinton (N.Y.)` → `clinton n y`
   - *Bare key* — strips qualifier: `Clinton (N.Y.)` → `clinton` (used only when unambiguous)
   - Corpus-specific `PRIORITY_OVERRIDES` (Central New York places, US states, major countries) are applied unconditionally before any index lookup

### Tunable parameters (top of script)

Same set as `reconcile_people.py` plus:

| Constant | Default | Effect |
|----------|---------|--------|
| `LCSH_FUZZY_THRESHOLD` | 85 | Minimum score for fuzzy LCSH rescue of low-frequency entries |
| `MIN_FILES_UNKNOWN` | 2 | Entries with no LCSH match must appear in ≥ this many files to be kept |

### LCNAF geo index

`authority-lists/lcnaf_geo_index.json` is a pre-built cache (23 MB) covering ~243,000 full keys and ~107,000 bare keys. If you need to rebuild it from scratch (e.g. after an LCNAF update):

```bash
# Requires names.skosrdf.jsonld in the target directory
python3 reconcile_places.py \
    --places   entities_places_augmented.csv \
    --outdir   output/ \
    --lcnaf-data /path/to/dir/containing/names.skosrdf.jsonld/
```

The index is automatically saved as `lcnaf_geo_index.json` in the `--lcnaf-data` directory and reused on subsequent runs.

### Regional authority list

`authority-lists/places_within_300_miles_clinton.txt` contains ~80,700 LCNAF place headings for every named place within approximately 300 miles of Clinton, NY (Hamilton College's home community). Pass it via `--regional-list` to:

- **Promote precision** — matches from a geographically bounded list are far more likely to be correct for a Central New York corpus than a match from the full 243,000-entry LCNAF geo index.
- **Rescue single-file entries** — by default, place names appearing in only one source file are treated as probable noise and dropped. A name confirmed by the regional list is almost certainly real, so the frequency gate is bypassed.
- **Standardise form** — entries are returned in their LCNAF heading form (e.g. `Clinton (N.Y.)`, `Utica (N.Y.)`), consistent with LCSH-matched entries.

The file format is one LCNAF heading per line. Lines beginning with `#` and blank lines are ignored. You can create similar lists for other institutions by running a SPARQL query against id.loc.gov or extracting from the LCNAF SKOS/RDF dump filtered by a bounding box.

---

## Utility — LCNAF name extraction: `extract_lcnaf_names.py`

Streams the LC Name Authority File (`names.skosrdf.jsonld`, ~18 GB) and extracts unique personal name tokens into flat text lists for use by `reconcile_people.py`. You only need to run this if you want to update the pre-built lists in `authority-lists/`.

### Usage

```bash
python3 extract_lcnaf_names.py \
    --lcnaf    /path/to/names.skosrdf.jsonld \
    --outdir   authority-lists/ \
    --min-freq 5
```

### Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--lcnaf` | `names.skosrdf.jsonld` | Path to the LCNAF SKOS/RDF JSON-LD file |
| `--outdir` | `.` | Directory to write output files |
| `--min-freq` | 5 | Minimum LCNAF record count for a token to appear in `lcnaf_given_names_common.txt`. Raise to tighten (fewer but more reliable tokens); lower to keep rarer names. |

### Output files

| File | Contents |
|------|----------|
| `lcnaf_surnames.txt` | All unique surname tokens (1.2 M, 12 MB) |
| `lcnaf_given_names.txt` | All unique given-name tokens (325 K, 2.7 MB) |
| `lcnaf_given_names_common.txt` | Given-name tokens appearing ≥ `--min-freq` times (51 K at default, 382 KB) — **used by `reconcile_people.py`** |

### Notes

- Runtime: ~60 seconds on a modern laptop (12 M lines, regex fast-path, no `json.loads`)
- Geographic records (identified by GAC notation) are automatically skipped
- Personal names are identified by the LCNAF inverted-form pattern: `Surname, Given [dates]`
- Compound surnames (`Abajo Alcalde`) are tokenised into individual components (`abajo`, `alcalde`) to reduce near-duplicate inflation; surname particles (`de`, `van`, `von`, etc.) are excluded

---

## Complete workflow example

This example assumes cleaned OCR files are already in `cleaned/` and uses the full pipeline with all optional features enabled.

```bash
# Working directories
CLEANED="cleaned/"          # cleaned OCR .txt files
ENTITIES="entities/"        # raw NER output
OUTPUT="output/"            # reconciled output
AUTH="authority-lists/"     # this directory

mkdir -p "$ENTITIES" "$OUTPUT"

# ── Stage 2: NER extraction ────────────────────────────────────────────────────
python3 ner-extract.py \
    --input  "$CLEANED" \
    --output "$ENTITIES"

# Outputs:
#   entities/entities_people.csv
#   entities/entities_places.csv
#   entities/entities_orgs_events.csv

# ── Stage 3a: People reconciliation ───────────────────────────────────────────
python3 reconcile_people.py \
    --people     "$ENTITIES/entities_people.csv" \
    --places     "$ENTITIES/entities_places.csv" \
    --outdir     "$OUTPUT" \
    --names-dir  "$AUTH"

# Outputs:
#   output/entities_people_clean.csv          ← main deliverable
#   output/entities_people_unverified.csv     ← review manually
#   output/entities_places_augmented.csv      ← feed into places reconciliation
#   output/reconciliation_report.tsv          ← audit trail

# ── Stage 3b: Places reconciliation ───────────────────────────────────────────
python3 reconcile_places.py \
    --places         "$OUTPUT/entities_places_augmented.csv" \
    --outdir         "$OUTPUT" \
    --campus-list    "$AUTH/hamilton-places.txt" \
    --regional-list  "$AUTH/places_within_300_miles_clinton.txt" \
    --lcnaf-data     "$AUTH"

# Outputs:
#   output/entities_places_verified.csv       ← main deliverable (LCSH confirmed)
#   output/entities_places_lcnaf.csv          ← with LCNAF preferred forms
#   output/entities_places_unverified.csv     ← review manually
#   output/entities_places_campus.csv         ← campus locations
#   output/places_filtered_out.csv            ← dropped entries
#   output/places_reconciliation_report.tsv   ← audit trail
```

---

## Running from scratch (including OCR cleaning)

```bash
RAW="raw-ocr/"
CLEANED="cleaned/"
ENTITIES="entities/"
OUTPUT="output/"
AUTH="authority-lists/"

mkdir -p "$CLEANED" "$ENTITIES" "$OUTPUT"

# Stage 1: clean OCR
python3 ocr-clean.py \
    --input  "$RAW" \
    --output "$CLEANED"

# Stage 2: extract entities
python3 ner-extract.py \
    --input  "$CLEANED" \
    --output "$ENTITIES"

# Stage 3a: people
python3 reconcile_people.py \
    --people     "$ENTITIES/entities_people.csv" \
    --places     "$ENTITIES/entities_places.csv" \
    --outdir     "$OUTPUT" \
    --names-dir  "$AUTH"

# Stage 3b: places
python3 reconcile_places.py \
    --places         "$OUTPUT/entities_places_augmented.csv" \
    --outdir         "$OUTPUT" \
    --campus-list    "$AUTH/hamilton-places.txt" \
    --regional-list  "$AUTH/places_within_300_miles_clinton.txt" \
    --lcnaf-data     "$AUTH"
```

---

## Authority lists — notes for maintainers

### Updating the LCNAF name lists

The name lists in `authority-lists/` were generated from the LC Name Authority File (`names.skosrdf.jsonld`) downloaded from <https://id.loc.gov/download/>. To regenerate after an LCNAF update:

```bash
python3 extract_lcnaf_names.py \
    --lcnaf    /path/to/names.skosrdf.jsonld \
    --outdir   authority-lists/ \
    --min-freq 5
```

The `--min-freq 5` threshold retains tokens appearing in ≥5 LCNAF records. This filters out one-off contamination (common English words that appear once as a "given name" in a misidentified corporate-body record) while keeping genuine but rare given names. Adjust as needed:

| Threshold | Tokens | Notes |
|-----------|--------|-------|
| ≥2 | ~123,000 | Catches more rare names; more noise |
| ≥5 | ~51,000 | Default — good balance |
| ≥10 | ~30,000 | Tighter; may miss some unusual names |
| ≥20 | ~18,000 | Only common names |

### Updating the geo index

Run any `reconcile_places.py` invocation with `--lcnaf-data` pointing to a directory containing `names.skosrdf.jsonld`. The script will build and cache `lcnaf_geo_index.json` automatically. Building takes ~5–10 minutes on the full 18 GB file.

### hamilton-places.txt

One campus location name per line. Blank lines and lines beginning with `#` are ignored. Names are matched case-insensitively and punctuation-insensitively against place entities. Add new buildings or facilities as needed.

---

## Troubleshooting

**spaCy model not found**
```bash
python3 -m spacy download en_core_web_sm
```

**`rapidfuzz` not installed**
```bash
pip install rapidfuzz --break-system-packages
```

**Geo index missing or stale** — Pass `--lcnaf-data` pointing to a directory that contains either `lcnaf_geo_index.json` (pre-built) or `names.skosrdf.jsonld` (will build and cache automatically).

**LCNAF name lists missing** — Run `extract_lcnaf_names.py` as described above, pointing `--outdir` to `authority-lists/`.

**Very large corpora** — Use `ner-batch.py` instead of `ner-extract.py` for chunked, fault-tolerant processing.

**Too many names in unverified** — Review `entities_people_unverified.csv`. The two-tier LCNAF check passes all entries with ≥3 source files unconditionally; only single/double-file entries are subject to the given-name check. If legitimate names are appearing there, check whether the first-name token is in `lcnaf_given_names_common.txt`; if not, it may be too rare or have been filtered from the LCNAF extraction as a title.

**Too many places dropped** — Adjust `--min-files` (default 2). Setting it to 1 retains all geographically-valid single-file entries.
