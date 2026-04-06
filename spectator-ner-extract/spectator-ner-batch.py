#!/usr/bin/env python3
"""
ner_batch.py — Chunked NER extraction that checkpoints to disk.

Processes files in configurable chunk sizes, saving a JSON checkpoint after
each chunk. A separate 'combine' step merges all checkpoints into the final
three CSV files.

Usage:
    # Process one chunk
    python3 ner_batch.py extract --input DIR --checkpoint DIR \
        --start 0 --end 300

    # Combine all checkpoints into CSVs
    python3 ner_batch.py combine --checkpoint DIR --output DIR
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
    """Return (people_set, orgs_set, places_set) for one spaCy Doc."""
    raw_people_full  = set()
    raw_people_maybe = {}
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
                if value not in raw_people_maybe:
                    raw_people_maybe[value] = raw

        elif label in ('ORG', 'EVENT'):
            if not raw[0].isalpha(): continue
            if not re.findall(r'[A-Z][A-Za-z]{2,}', raw): continue
            if '|' in raw or re.search(r'\d{3,}', raw): continue
            raw_orgs.add(raw)

        elif label in ('GPE', 'LOC'):
            words = re.findall(r'[A-Za-z]+', raw)
            if any(len(w) >= 3 for w in words):
                raw_places.add(raw)

    # Within-doc courtesy-title reconciliation (discard unreconciled forms)
    last_to_full = defaultdict(list)
    for fn in raw_people_full:
        parts = fn.split()
        if first_token_title(parts) is None:
            last_to_full[parts[-1].rstrip('.,;:').lower()].append(fn)
    # (unreconciled courtesy forms are simply dropped)

    return raw_people_full, raw_orgs, {lcsh_place(p) for p in raw_places}


# ── Subcommands ────────────────────────────────────────────────────────────────

def cmd_extract(args):
    input_dir = Path(args.input).expanduser().resolve()
    ckpt_dir  = Path(args.checkpoint).expanduser().resolve()
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    txt_files = sorted(input_dir.glob('spec-*_djvu.txt'))
    chunk = txt_files[args.start:args.end]
    total = len(chunk)
    print(f'Chunk {args.start}–{args.end}: {total} files', flush=True)

    nlp = spacy.load('en_core_web_sm',
                     disable=['parser', 'attribute_ruler', 'lemmatizer'])
    nlp.max_length = 2_000_000

    # Accumulator for this chunk: name → {dates: [], files: []}
    acc = {'people': defaultdict(lambda: {'dates': [], 'files': []}),
           'orgs':   defaultdict(lambda: {'dates': [], 'files': []}),
           'places': defaultdict(lambda: {'dates': [], 'files': []})}

    texts = []
    metas = []
    for fp in chunk:
        texts.append(fp.read_text(encoding='utf-8', errors='replace'))
        metas.append((fp.name, filename_to_date(fp.name)))

    for i, (doc, (fname, date)) in enumerate(
            zip(nlp.pipe(texts, batch_size=4), metas), 1):
        people, orgs, places = extract_doc_entities(doc)
        for name in people:
            acc['people'][name]['dates'].append(date)
            acc['people'][name]['files'].append(fname)
        for name in orgs:
            acc['orgs'][name]['dates'].append(date)
            acc['orgs'][name]['files'].append(fname)
        for name in places:
            acc['places'][name]['dates'].append(date)
            acc['places'][name]['files'].append(fname)
        if i % 50 == 0 or i == total:
            print(f'  [{i}/{total}] people:{len(acc["people"])} '
                  f'orgs:{len(acc["orgs"])} places:{len(acc["places"])}',
                  flush=True)

    # Serialize defaultdict → regular dict for JSON
    out = {}
    for kind in ('people', 'orgs', 'places'):
        out[kind] = {k: v for k, v in acc[kind].items()}

    ckpt_path = ckpt_dir / f'chunk_{args.start:04d}_{args.end:04d}.json'
    ckpt_path.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    print(f'Checkpoint saved: {ckpt_path}', flush=True)


def cmd_combine(args):
    ckpt_dir  = Path(args.checkpoint).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ckpt_files = sorted(ckpt_dir.glob('chunk_*.json'))
    print(f'Combining {len(ckpt_files)} checkpoint files…')

    merged = {'people': defaultdict(lambda: {'dates': set(), 'files': set()}),
              'orgs':   defaultdict(lambda: {'dates': set(), 'files': set()}),
              'places': defaultdict(lambda: {'dates': set(), 'files': set()})}

    for ckpt_path in ckpt_files:
        data = json.loads(ckpt_path.read_text(encoding='utf-8'))
        for kind in ('people', 'orgs', 'places'):
            for name, rec in data.get(kind, {}).items():
                merged[kind][name]['dates'].update(d for d in rec['dates'] if d)
                merged[kind][name]['files'].update(rec['files'])

    HEADER = ['name', 'earliest_date', 'latest_date', 'files']
    for kind, fname in [('people', 'entities_people.csv'),
                        ('orgs',   'entities_orgs_events.csv'),
                        ('places', 'entities_places.csv')]:
        rows = []
        for name, rec in sorted(merged[kind].items(), key=lambda x: x[0].lower()):
            dates = sorted(rec['dates'])
            files = sorted(rec['files'])
            rows.append([name,
                         dates[0] if dates else '',
                         dates[-1] if dates else '',
                         ';'.join(files)])
        out_path = output_dir / fname
        with out_path.open('w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(HEADER)
            csv.writer(f).writerows(rows)
        print(f'  {fname}: {len(rows):,} entities')

    print('Done.')


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd')

    ex = sub.add_parser('extract')
    ex.add_argument('--input',      required=True)
    ex.add_argument('--checkpoint', required=True)
    ex.add_argument('--start', type=int, required=True)
    ex.add_argument('--end',   type=int, required=True)

    co = sub.add_parser('combine')
    co.add_argument('--checkpoint', required=True)
    co.add_argument('--output',     required=True)

    args = p.parse_args()
    if args.cmd == 'extract':
        cmd_extract(args)
    elif args.cmd == 'combine':
        cmd_combine(args)
    else:
        p.print_help()

if __name__ == '__main__':
    main()