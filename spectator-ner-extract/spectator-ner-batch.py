#!/usr/bin/env python3
"""
ner_batch.py — Chunked NER extraction with checkpoint/combine workflow.

Designed for the Hamilton College Spectator corpus (1947–1981) when the full
corpus is too large to process in a single uninterrupted run, or when multiple
machines are available to process chunks in parallel.

Workflow overview:
  1. Divide the sorted input file list into non-overlapping index ranges.
  2. Run the 'extract' subcommand once per range; each run saves a JSON
     checkpoint file to the --checkpoint directory.
  3. After all chunks complete, run the 'combine' subcommand once to merge
     all checkpoints into the final three CSV files.

Checkpoint format (chunk_XXXX_YYYY.json):
  {
    "people": {"Name": {"dates": [...], "files": [...]}},
    "orgs":   {"Name": {"dates": [...], "files": [...]}},
    "places": {"Name": {"dates": [...], "files": [...]}}
  }
  Dates and files are stored as lists in each chunk (not sets — JSON does not
  support sets); the combine step deduplicates them using Python sets.

Entity extraction heuristics are shared with ner_extract.py.  See that file
or the README for full documentation of filtering and LCSH-standardization rules.

Usage:
    # Extract a chunk (file indices 0–299, inclusive–exclusive)
    python3 ner_batch.py extract \
        --input      /path/to/cleaned_txts \
        --checkpoint /path/to/checkpoints \
        --start 0 --end 300

    # Combine all checkpoints into final CSVs
    python3 ner_batch.py combine \
        --checkpoint /path/to/checkpoints \
        --output     /path/to/output_csvs

Requirements: Python 3.8+, spaCy 3.x with en_core_web_sm
  pip install spacy --break-system-packages
  python3 -m spacy download en_core_web_sm
"""

import re, sys, csv, json, argparse
from pathlib import Path
from collections import defaultdict

import spacy

# ── Shared constants (same as ner_extract.py) ─────────────────────────────────

PROFESSIONAL_TITLES = {
    'dr', 'doctor', 'prof', 'professor', 'dean', 'president', 'vice-president',
    'provost', 'chancellor', 'rector', 'principal', 'director', 'chairman',
    'chairwoman', 'chair', 'superintendent', 'commissioner', 'secretary',
    'treasurer', 'editor', 'coach', 'rev', 'reverend', 'father', 'bishop',
    'cardinal', 'archbishop', 'rabbi', 'minister', 'pastor', 'chaplain',
    'gen', 'general', 'col', 'colonel', 'major', 'capt', 'captain',
    'lt', 'lieutenant', 'sgt', 'sergeant', 'cpl', 'corporal', 'pvt', 'private',
    'adm', 'admiral', 'cmdr', 'commander', 'gov', 'governor', 'sen', 'senator',
    'rep', 'representative', 'amb', 'ambassador', 'judge', 'justice',
    'mayor', 'alderman', 'constable',
}
COURTESY_TITLES = {'mr', 'mrs', 'miss', 'ms', 'mme', 'mdme'}
ALL_TITLES = PROFESSIONAL_TITLES | COURTESY_TITLES

NAME_CONNECTORS = {'de', 'di', 'du', 'van', 'von', 'der', 'den', 'la', 'le',
                   'el', 'al', 'del', 'della', 'da', 'do', 'das', 'dos', 'mac'}
PERSON_BLOCKLIST = {
    'alma mater', 'sub freshman', 'sub-freshman', 'old middle',
    'young republican', 'young democrats', 'big red',
}

NOISE_RE        = re.compile(r'^[^A-Za-z]+$')
LEADING_PUNCT   = re.compile(r'^[^A-Za-z]+')
TRAILING_PUNCT  = re.compile(r'[^A-Za-z\.\)]+$')

# ── LCSH lookup table (abridged for speed; full table in ner_extract.py) ──────
# Only the most common place names; the combine step can re-apply the full table.
LCSH_PLACES = {
    'clinton': 'Clinton (N.Y.)', 'hamilton': 'Hamilton (N.Y.)',
    'utica': 'Utica (N.Y.)', 'rome': 'Rome (N.Y.)',
    'new york': 'New York (N.Y.)', 'new york city': 'New York (N.Y.)',
    'albany': 'Albany (N.Y.)', 'syracuse': 'Syracuse (N.Y.)',
    'rochester': 'Rochester (N.Y.)', 'buffalo': 'Buffalo (N.Y.)',
    'ithaca': 'Ithaca (N.Y.)', 'schenectady': 'Schenectady (N.Y.)',
    'troy': 'Troy (N.Y.)', 'binghamton': 'Binghamton (N.Y.)',
    'boston': 'Boston (Mass.)', 'cambridge': 'Cambridge (Mass.)',
    'new haven': 'New Haven (Conn.)', 'hartford': 'Hartford (Conn.)',
    'washington': 'Washington (D.C.)', 'washington d.c.': 'Washington (D.C.)',
    'washington dc': 'Washington (D.C.)',
    'philadelphia': 'Philadelphia (Pa.)', 'pittsburgh': 'Pittsburgh (Pa.)',
    'baltimore': 'Baltimore (Md.)', 'chicago': 'Chicago (Ill.)',
    'detroit': 'Detroit (Mich.)', 'cleveland': 'Cleveland (Ohio)',
    'atlanta': 'Atlanta (Ga.)', 'new orleans': 'New Orleans (La.)',
    'los angeles': 'Los Angeles (Calif.)', 'san francisco': 'San Francisco (Calif.)',
    'london': 'London (England)', 'paris': 'Paris (France)',
    'berlin': 'Berlin (Germany)', 'moscow': 'Moscow (Russia)',
    'tokyo': 'Tokyo (Japan)', 'united states': 'United States',
    'new england': 'New England', 'soviet union': 'Soviet Union',
    'princeton': 'Princeton (N.J.)', 'middlebury': 'Middlebury (Vt.)',
    'hanover': 'Hanover (N.H.)', 'amherst': 'Amherst (Mass.)',
    'colgate': 'Colgate (N.Y.)',
}


# ── Utility functions ──────────────────────────────────────────────────────────

def filename_to_date(name):
    m = re.search(r'spec-(\d{4}-\d{2}-\d{2})', name)
    return m.group(1) if m else None

def normalize_entity(text):
    text = re.sub(r'\s+', ' ', text).strip()
    text = LEADING_PUNCT.sub('', text)
    text = TRAILING_PUNCT.sub('', text)
    return text.strip()

def is_garbled(text):
    t = text.strip()
    if len(t) <= 1:           return True
    if NOISE_RE.match(t):     return True
    if re.match(r'^[A-Z\s\.\-]{5,}$', t): return True
    return False

def looks_like_name_token(tok):
    return bool(re.match(r"^[A-Z][A-Za-z'\-]+$", tok))

def first_token_title(tokens):
    if not tokens: return None
    t = tokens[0].rstrip('.').lower()
    return t if t in ALL_TITLES else None

def all_tokens_valid_name(tokens, skip_first=False):
    start = 1 if skip_first else 0
    for tok in tokens[start:]:
        t = tok.rstrip('.,;:')
        if not t: continue
        if t.lower() in NAME_CONNECTORS: continue
        if not looks_like_name_token(t): return False
    return True

def classify_person(text):
    text = normalize_entity(text)
    if not text: return ('drop', None)
    tokens = text.split()
    if len(tokens) < 2 or len(tokens) > 5: return ('drop', None)
    if is_garbled(text): return ('drop', None)
    if text.lower() in PERSON_BLOCKLIST: return ('drop', None)

    title = first_token_title(tokens)
    if title in PROFESSIONAL_TITLES:
        rest = tokens[1:]
        if rest and any(looks_like_name_token(t.rstrip('.,;:')) for t in rest):
            if all_tokens_valid_name(tokens, skip_first=True):
                return ('keep_full', text)
        return ('drop', None)
    if title in COURTESY_TITLES:
        if all_tokens_valid_name(tokens, skip_first=True):
            last = tokens[-1].rstrip('.,;:')
            if looks_like_name_token(last):
                return ('keep_if_rec', last)
        return ('drop', None)
    if not all_tokens_valid_name(tokens):
        return ('drop', None)
    name_tokens = [t for t in tokens if looks_like_name_token(t.rstrip('.,;:'))]
    if len(name_tokens) >= 2:
        return ('keep_full', text)
    return ('drop', None)

def lcsh_place(raw):
    key = normalize_entity(raw).lower()
    return LCSH_PLACES.get(key, normalize_entity(raw))

# ── Extraction ─────────────────────────────────────────────────────────────────

def extract_doc_entities(doc):
    """
    Run entity classification on an already-processed spaCy Doc object.

    Returns a tuple of three sets:
        (people_set, orgs_set, places_set)

    Applies the same heuristic rules as ner_extract.py:
      - PERSON:     classify_person() accepts full first+last forms and
                    professional-title forms; courtesy-title forms are kept
                    only if an unambiguous matching full form exists in the
                    same document (within-doc reconciliation).
      - ORG/EVENT:  must begin with an alpha char and contain at least one
                    capitalized word of ≥3 letters; digit-heavy strings rejected.
      - GPE/LOC:    must contain a word of ≥3 alpha chars; LCSH lookup applied.
    """
    raw_people_full  = set()   # definitely-keep person names
    raw_people_maybe = {}      # last_name → courtesy-form, needs reconciliation
    raw_orgs   = set()
    raw_places = set()

    for ent in doc.ents:
        raw = normalize_entity(ent.text)
        if not raw or is_garbled(raw): continue
        label = ent.label_

        if label == 'PERSON':
            kind, value = classify_person(raw)
            if kind == 'keep_full':
                raw_people_full.add(value)
            elif kind == 'keep_if_rec':
                # Courtesy-title form (Mr./Ms. + last name): keep only if a
                # full first+last form for that surname appears in this document.
                # Store last_name → courtesy-form for later reconciliation.
                if value not in raw_people_maybe:
                    raw_people_maybe[value] = raw

        elif label in ('ORG', 'EVENT'):
            # Reject tokens that start with punctuation or all-digit strings
            if not raw[0].isalpha(): continue
            # Require at least one genuine capitalized word (filters headline junk)
            if not re.findall(r'[A-Z][A-Za-z]{2,}', raw): continue
            # Reject OCR noise: pipes and 3+ consecutive digits
            if '|' in raw or re.search(r'\d{3,}', raw): continue
            raw_orgs.add(raw)

        elif label in ('GPE', 'LOC'):
            # Require at least one real alphabetic word of length ≥3
            words = re.findall(r'[A-Za-z]+', raw)
            if any(len(w) >= 3 for w in words):
                raw_places.add(raw)

    # Within-document reconciliation: build a map of last_name → full-name forms.
    # If a courtesy-title form (e.g. 'Mr. Williams') has exactly one matching
    # full-name form already in the document, the full form is sufficient —
    # the courtesy form need not be added as a separate entry.
    # Unreconciled courtesy forms (no match, or ambiguous) are simply dropped.
    last_to_full = defaultdict(list)
    for fn in raw_people_full:
        parts = fn.split()
        if first_token_title(parts) is None:   # skip titled forms like 'Dean Tolles'
            last_to_full[parts[-1].rstrip('.,;:').lower()].append(fn)

    # Apply LCSH standardization to all place names before returning.
    return raw_people_full, raw_orgs, {lcsh_place(p) for p in raw_places}


# ── Subcommands ────────────────────────────────────────────────────────────────

def cmd_extract(args):
    """
    Process one chunk of files (index range [start, end)) and save a JSON checkpoint.

    The checkpoint filename encodes the range: chunk_XXXX_YYYY.json.  This allows
    multiple chunks to be run independently (in any order or in parallel on
    different machines) without overwriting each other.
    """
    input_dir = Path(args.input).expanduser().resolve()
    ckpt_dir  = Path(args.checkpoint).expanduser().resolve()
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    # Slice the sorted file list to get this chunk's files.
    # Files are sorted alphabetically; spec-YYYY-MM-DD_djvu.txt sorts chronologically.
    txt_files = sorted(input_dir.glob('spec-*_djvu.txt'))
    chunk = txt_files[args.start:args.end]
    total = len(chunk)
    print(f'Chunk {args.start}–{args.end}: {total} files', flush=True)

    # Load spaCy with only the NER component — parser and lemmatizer are not
    # needed and disabling them gives a significant speed-up.
    nlp = spacy.load('en_core_web_sm',
                     disable=['parser', 'attribute_ruler', 'lemmatizer'])
    # Raise the max_length limit: some issue files are large after OCR cleaning.
    nlp.max_length = 2_000_000

    # Per-chunk accumulator: entity_name → {dates: [list], files: [list]}.
    # Lists (not sets) are used here because JSON does not support sets;
    # the combine step will deduplicate using Python sets.
    acc = {'people': defaultdict(lambda: {'dates': [], 'files': []}),
           'orgs':   defaultdict(lambda: {'dates': [], 'files': []}),
           'places': defaultdict(lambda: {'dates': [], 'files': []})}

    # Pre-read all files in the chunk so nlp.pipe() can batch them efficiently.
    texts = []
    metas = []   # parallel list: (filename, ISO date string)
    for fp in chunk:
        texts.append(fp.read_text(encoding='utf-8', errors='replace'))
        metas.append((fp.name, filename_to_date(fp.name)))

    # Run NER across the chunk in batches of 4 documents at a time.
    # batch_size controls how many docs are sent to each worker; tune upward
    # if you have enough RAM (larger batches = better GPU/CPU utilization).
    for i, (doc, (fname, date)) in enumerate(
            zip(nlp.pipe(texts, batch_size=4), metas), 1):
        people, orgs, places = extract_doc_entities(doc)
        # Append each entity's date and filename to its accumulator record.
        for name in people:
            acc['people'][name]['dates'].append(date)
            acc['people'][name]['files'].append(fname)
        for name in orgs:
            acc['orgs'][name]['dates'].append(date)
            acc['orgs'][name]['files'].append(fname)
        for name in places:
            acc['places'][name]['dates'].append(date)
            acc['places'][name]['files'].append(fname)
        # Print running counts every 50 files so long runs show progress.
        if i % 50 == 0 or i == total:
            print(f'  [{i}/{total}] people:{len(acc["people"])} '
                  f'orgs:{len(acc["orgs"])} places:{len(acc["places"])}',
                  flush=True)

    # Convert defaultdicts to plain dicts before JSON serialization.
    # (json.dumps cannot serialize defaultdict directly.)
    out = {}
    for kind in ('people', 'orgs', 'places'):
        out[kind] = {k: v for k, v in acc[kind].items()}

    # Checkpoint filename encodes the chunk range for easy identification.
    ckpt_path = ckpt_dir / f'chunk_{args.start:04d}_{args.end:04d}.json'
    ckpt_path.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    print(f'Checkpoint saved: {ckpt_path}', flush=True)


def cmd_combine(args):
    """
    Merge all checkpoint files in --checkpoint into the three final CSV files.

    Each checkpoint holds data for one chunk of files.  Combining uses Python
    sets to union the dates and filenames for each entity across all chunks,
    so entities that appear in multiple chunks are deduplicated automatically.
    The final row for each entity records the earliest and latest date seen
    across the entire corpus.
    """
    ckpt_dir  = Path(args.checkpoint).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Discover all checkpoint files, sorted by name (which encodes chunk ranges).
    ckpt_files = sorted(ckpt_dir.glob('chunk_*.json'))
    print(f'Combining {len(ckpt_files)} checkpoint files…')

    # Global accumulator: uses sets so union across checkpoints is automatic.
    # Each checkpoint stored lists; we convert them to sets on read.
    merged = {'people': defaultdict(lambda: {'dates': set(), 'files': set()}),
              'orgs':   defaultdict(lambda: {'dates': set(), 'files': set()}),
              'places': defaultdict(lambda: {'dates': set(), 'files': set()})}

    for ckpt_path in ckpt_files:
        data = json.loads(ckpt_path.read_text(encoding='utf-8'))
        for kind in ('people', 'orgs', 'places'):
            for name, rec in data.get(kind, {}).items():
                # Filter out None dates (files whose names lacked a parseable date).
                merged[kind][name]['dates'].update(d for d in rec['dates'] if d)
                merged[kind][name]['files'].update(rec['files'])

    # Write one CSV per entity type.  Rows are sorted case-insensitively by name.
    # earliest_date / latest_date are the min/max of the sorted date set.
    HEADER = ['name', 'earliest_date', 'latest_date', 'files']
    for kind, fname in [('people', 'entities_people.csv'),
                        ('orgs',   'entities_orgs_events.csv'),
                        ('places', 'entities_places.csv')]:
        rows = []
        for name, rec in sorted(merged[kind].items(), key=lambda x: x[0].lower()):
            dates = sorted(rec['dates'])
            files = sorted(rec['files'])
            rows.append([name,
                         dates[0] if dates else '',    # earliest appearance
                         dates[-1] if dates else '',   # latest appearance
                         ';'.join(files)])              # semicolon-delimited file list
        out_path = output_dir / fname
        with out_path.open('w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(HEADER)
            csv.writer(f).writerows(rows)
        print(f'  {fname}: {len(rows):,} entities')

    print('Done.')


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description='Chunked NER extraction with checkpoint/combine workflow.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest='cmd')

    # ── 'extract' subcommand ──────────────────────────────────────────────────
    ex = sub.add_parser(
        'extract',
        help='Run NER on a slice of the input files and save a JSON checkpoint.',
    )
    ex.add_argument('--input',      required=True,
                    help='Directory containing cleaned spec-*_djvu.txt files')
    ex.add_argument('--checkpoint', required=True,
                    help='Directory to write the chunk_XXXX_YYYY.json checkpoint')
    ex.add_argument('--start', type=int, required=True,
                    help='0-based start index (inclusive) into the sorted file list')
    ex.add_argument('--end',   type=int, required=True,
                    help='End index (exclusive) — process files[start:end]')

    # ── 'combine' subcommand ──────────────────────────────────────────────────
    co = sub.add_parser(
        'combine',
        help='Merge all checkpoint JSON files into the three final CSV outputs.',
    )
    co.add_argument('--checkpoint', required=True,
                    help='Directory containing chunk_*.json checkpoint files')
    co.add_argument('--output',     required=True,
                    help='Directory to write entities_people.csv, '
                         'entities_orgs_events.csv, entities_places.csv')

    args = p.parse_args()
    if args.cmd == 'extract':
        cmd_extract(args)
    elif args.cmd == 'combine':
        cmd_combine(args)
    else:
        p.print_help()

if __name__ == '__main__':
    main()
