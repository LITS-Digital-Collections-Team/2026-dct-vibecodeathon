#!/usr/bin/env python3
"""
extract_lcnaf_names.py — Extract unique personal name tokens from LCNAF SKOS/RDF.

Reads names.skosrdf.jsonld (the LC Name Authority File in SKOS/RDF JSON-LD,
one JSON object per line) and produces four output files:

  lcnaf_surnames.txt             — unique family/last-name tokens (all)
  lcnaf_given_names.txt          — unique given/first-name tokens (all)
  lcnaf_given_names_common.txt   — given-name tokens appearing ≥ --min-freq
                                   times across all LCNAF records (default 5)

PURPOSE
=======
These lists are intended as a validator for entities_people output.  A
candidate entity is considered a genuine personal name if at least one of its
tokens appears in the LCNAF given-names list.  The "common" file (frequency-
filtered) is preferred for validation: common real given names (robert, james,
mary …) appear in thousands of LCNAF records; one-off contamination tokens
(administrative, alone, workshop …) from corporate-body records that slipped
past the personal-name filter appear only once or twice and are excluded by the
frequency threshold.

IDENTIFICATION STRATEGY
=======================
All LCNAF records in the SKOS serialisation share @type "skos:Concept" —
there is no @type field that distinguishes personal names from corporate
bodies, geographic names, or uniform titles.  Geographic names are identified
by a GAC notation (http://id.loc.gov/datatypes/codes/gac), which is handled by
the places scripts and excluded here.

Personal names in LCNAF follow the inverted authority form:
  "Surname, Given name [birth-death dates and/or qualifiers]"

Examples:
  "Smith, John L. (John Lyle), 1964-"
  "García López, Juan"
  "O'Brien, Patrick, 1952-"
  "Van der Berg, Hans"
  "MacGregor, James, Sir"

This pattern — a comma after the surname with a capitalised letter following —
is the primary discriminator.  Corporate bodies, uniform titles, and geographic
names either have no comma or have commas that do not fit this pattern.

PERFORMANCE
===========
The file is ~18 GB with ~12.3 million lines.  To avoid the overhead of
json.loads() on all 12 million records, the script uses a compiled regex to
extract the skos:prefLabel value directly from the raw line text.

Approximate runtime: 1–3 minutes on a modern CPU.

USAGE
=====
  python3 extract_lcnaf_names.py \\
      --lcnaf  /path/to/names.skosrdf.jsonld \\
      --outdir /path/to/output/dir

  # Raise the frequency threshold for a tighter common-names list:
  python3 extract_lcnaf_names.py --lcnaf names.skosrdf.jsonld --min-freq 10

  # Preview first N lines of each output file:
  head -20 lcnaf_surnames.txt
  head -20 lcnaf_given_names.txt
  head -20 lcnaf_given_names_common.txt

REQUIREMENTS
============
Python 3.8+ (no third-party libraries required)
"""

import re
import sys
import time
import argparse
from collections import Counter
from pathlib import Path

# Decode \uXXXX escapes that appear literally in JSON string values
_UNESCAPE_RE = re.compile(r'\\u([0-9a-fA-F]{4})')

def _unescape_json(s: str) -> str:
    """Replace \\uXXXX sequences with their Unicode characters."""
    return _UNESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), s)


# ── Surname tokeniser ──────────────────────────────────────────────────────────
# Many LCNAF personal names have compound surnames: "Abajo Alcalde, María"
# and "Abajo Antón, Juan" and "Abajo Castrillo, Pedro" each store a different
# compound in the surnames set, inflating the list with near-duplicate entries.
#
# For validation purposes it is more useful to store EACH COMPONENT as its own
# token so that:
#   "abajo alcalde", "abajo antón", "abajo castrillo" → "abajo", "alcalde",
#   "antón", "castrillo"  (vastly more compact and equally useful for lookup)
#
# Particles (prepositions and articles that are never standalone surnames) are
# excluded from the per-component output.
_SURNAME_PARTICLES: frozenset[str] = frozenset({
    # Germanic / Dutch
    'van', 'von', 'vom', 'ver', 'den', 'der', 'ten', 'ter', 'zu', 'zur',
    'zum', 'im', 'am', 'auf',
    # Romance
    'de', 'del', 'della', 'delle', 'degli', 'dei', 'di', 'du', 'des', 'da',
    'das', 'do', 'dos', 'la', 'le', 'les', 'las', 'lo', 'los', 'al', 'el',
    # Arabic / Middle Eastern
    'bin', 'bint', 'ibn', 'abu', 'abd', 'al', 'ul', 'ur',
    # Scandinavian
    'af', 'av', 'og',
    # English
    'of', 'the', 'and',
    # Single-letter particles sometimes appearing in normalised forms
    'a', 'e', 'i', 'o', 'y',
})


def _surname_tokens(surname: str) -> list[str]:
    """
    Split a (lowercased) compound surname into individual meaningful tokens,
    filtering out particles/prepositions.  Each returned token is a candidate
    standalone surname for the output list.

    Examples:
      "abajo alcalde"  → ["abajo", "alcalde"]
      "de la cruz"     → ["cruz"]          (de, la filtered)
      "van der berg"   → ["berg"]          (van, der filtered)
      "o'brien"        → ["o'brien"]       (kept as one token)
      "smith"          → ["smith"]
    """
    # Split on spaces; hyphens are kept as part of the token (they connect
    # genuine compound surnames like "lloyd-george").
    parts = re.split(r'\s+', surname)
    tokens = []
    for part in parts:
        tok = part.strip(" .,;:\"'!?*-")
        if not tok:
            continue
        if len(tok) < 2:
            continue
        if tok in _SURNAME_PARTICLES:
            continue
        # Must start with a Unicode letter (rejects OCR noise like "!name", "----r")
        if not tok[0].isalpha():
            continue
        tokens.append(tok)
    return tokens


# ── Regex: extract a simple-string skos:prefLabel from a raw JSON line ─────────
# Matches: ..."skos:prefLabel":"Smith, John, 1920-"...
# Does NOT match list values: ..."skos:prefLabel":["English label", {...}],...
# The (?:...) inner group handles JSON-escaped characters inside the string.
_LABEL_RE = re.compile(
    r'"skos:prefLabel"\s*:\s*"((?:[^"\\]|\\.)*)"'
)

# ── Personal name pattern ───────────────────────────────────────────────────────
# "Surname, Given [optional stuff]"
# Surname: one or more tokens (handles compound surnames)
# After comma: must start with a Unicode letter (not a digit or symbol)
_PERSONAL_RE = re.compile(
    r'^(.+?),\s+([^\d\s(][\w\'\u00C0-\u017E\u0180-\u024F\-\']*)',
    re.UNICODE,
)

# ── Words in the SURNAME POSITION that signal non-personal-name entries ────────
# If any of these appear as a word in the part before the first comma, the
# record is almost certainly a corporate body, conference, or meeting — not
# a person.
_SURNAME_KEYWORDS: frozenset[str] = frozenset({
    'workshop', 'conference', 'symposium', 'seminar', 'colloquium', 'congress',
    'meeting', 'forum', 'summit', 'convention', 'institute', 'association',
    'society', 'university', 'college', 'school', 'academy', 'federation',
    'commission', 'committee', 'council', 'board', 'bureau', 'office',
    'department', 'division', 'agency', 'authority', 'ministry', 'service',
    'company', 'corporation', 'inc', 'ltd', 'llc', 'foundation', 'trust',
    'group', 'organization', 'organisation', 'international', 'national',
    'federal', 'royal', 'imperial', 'expedition', 'survey', 'project',
    'program', 'programme', 'working', 'study', 'studies', 'research',
    'center', 'centre', 'network', 'alliance', 'coalition', 'consortium',
})

# ── Tokens after comma that signal non-personal-name entries ───────────────────
# Corporate bodies, jurisdictions, family names, uniform titles, etc.
_SKIP_TOKENS: frozenset[str] = frozenset({
    # English organisational / corporate keywords
    'and', 'or', 'the', 'inc', 'corp', 'ltd', 'llc', 'co', 'plc',
    'company', 'companies', 'associates', 'brothers', 'sons', 'daughters',
    'publications', 'publishing', 'press', 'bureau', 'books', 'films',
    # Institutional keywords
    'university', 'college', 'institute', 'school', 'academy', 'seminary',
    'department', 'committee', 'office', 'bureau', 'division',
    'board', 'agency', 'authority', 'commission', 'council', 'ministry',
    'society', 'association', 'federation', 'organization', 'organisation',
    'foundation', 'trust', 'fund', 'group',
    # Geographical / political keywords
    'international', 'national', 'federal', 'state', 'regional', 'local',
    'united', 'royal', 'imperial',
    # Temporal qualifiers used in corporate/title authority headings
    'active', 'approximately', 'ca', 'fl', 'flourished', 'b', 'd',
    # Family names ("Smith family" → label = "Smith, family" in some records)
    'family', 'families',
    # Title / uniform title indicators
    'complete', 'selected', 'collected', 'works', 'selections',
    # Conjunctions and articles used in corporate names
    'von', 'van', 'de', 'del', 'di', 'du', 'der', 'das', 'die', 'les',
})

# ── Tokens that follow the comma but are honorifics/titles, not given names ───
_TITLE_TOKENS: frozenset[str] = frozenset({
    'sir', 'dame', 'lord', 'lady', 'baron', 'baroness', 'earl', 'count',
    'countess', 'duke', 'duchess', 'marquess', 'viscount', 'prince',
    'princess', 'king', 'queen', 'emperor', 'empress', 'tsar', 'tsarina',
    'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'rev', 'hon', 'capt', 'maj',
    'col', 'gen', 'adm', 'lt', 'sgt',
    # Religious titles
    'pope', 'bishop', 'archbishop', 'cardinal', 'abbot', 'abbess',
    'father', 'brother', 'sister', 'saint',
})


def _clean_token(raw: str) -> str:
    """
    Strip trailing punctuation that commonly appears in LCNAF labels
    but is not part of the name:
      "John,"   → "John"
      "María."  → "María"
      "O'Brien" → kept as-is
    """
    return raw.strip(" .,;:()-'\"")


def _is_initial(token: str) -> bool:
    """Return True for single-letter initials like 'A.' or 'B'."""
    t = token.rstrip('.')
    return len(t) == 1 and t.isalpha()


def parse_personal_name(label: str) -> tuple[str, str] | None:
    """
    Try to parse *label* as an LCNAF personal name in inverted form.

    Returns (surname_lower, given_lower) on success, or None if the label
    does not match the personal-name pattern.

    Extraction rules:
    - Surname  = everything before the first comma, stripped
    - Given    = first name-like token after the comma, stripped of
                 trailing punctuation.  Single initials (A., B.) are
                 accepted as evidence that a given name exists but are
                 NOT themselves added to the given-names list.

    The function returns None for:
    - Labels with no comma
    - Labels where the token after the comma is in _SKIP_TOKENS or
      _TITLE_TOKENS
    - Labels where the token after the comma starts with a digit
      (dates: "1920-2010")
    - Surplus noise entries (empty tokens after cleaning)
    """
    label = label.strip()
    m = _PERSONAL_RE.match(label)
    if not m:
        return None

    surname_raw = m.group(1).strip()
    first_token_raw = m.group(2).strip()

    # Skip if first token after comma is a date, skip word, or title
    first_lower = _clean_token(first_token_raw).lower()
    if not first_lower:
        return None
    if first_lower[0].isdigit():
        return None
    if first_lower in _SKIP_TOKENS:
        return None
    if first_lower in _TITLE_TOKENS:
        return None

    # Clean surname
    surname = _clean_token(surname_raw)
    if not surname:
        return None

    # Reject if the surname portion contains corporate/conference keywords.
    # E.g. "Workshop on Plate Tectonics, Tokyo, 1995" looks like an inverted
    # personal name but isn't.  Checking individual words in the surname
    # catches these without over-filtering legitimate multi-word surnames.
    surname_words = {w.lower() for w in re.split(r'[\s\-]+', surname) if w}
    if surname_words & _SURNAME_KEYWORDS:
        return None

    # Personal names in LCNAF have ≤ ~5 tokens before the comma.
    # Very long "surnames" (> 6 space-separated tokens) are almost certainly
    # corporate/conference names that slipped through the keyword filter.
    if len(surname.split()) > 6:
        return None

    # Reject if the "surname" contains a parenthesis — this is the hallmark
    # of conference/meeting authority headings: "Workshop (2010 : City, ..."
    if '(' in surname:
        return None

    # Reject if the "surname" starts with a digit — these are date-prefixed
    # conference / serial titles like "1956 a néphagyományban (2006 : Debrecen"
    if surname[0].isdigit():
        return None

    # Given name: the first token after the comma.  Accept even single initials
    # as evidence that the record is a person (they won't be added to the output
    # list, but they confirm the record is personal).
    given = _clean_token(first_token_raw)

    return surname.lower(), given.lower() if not _is_initial(given) else None


def _given_tokens(given: str) -> list[str]:
    """
    Split a given-name string into individual tokens.
    Unlike surnames, particles are generally NOT filtered from given names
    (e.g. "le" in "Le Van Thanh" is part of the name, but "Van" is not a
    given name).  We keep each space-separated token that is ≥ 2 characters
    and not a recognised particle.

    Hyphens are treated as name connectors: "jean-baptiste" stays whole.
    """
    parts = re.split(r'\s+', given)
    tokens = []
    for part in parts:
        tok = part.strip(" .,;:\"'!?*-")
        if not tok or len(tok) < 2:
            continue
        # Must start with a Unicode letter
        if not tok[0].isalpha():
            continue
        # Only filter the very common particles that are never standalone
        # given names (van, von, de, etc. can precede a given name in some
        # cultures; keep them unless they are clear prepositions).
        if tok in _SURNAME_PARTICLES:
            continue
        tokens.append(tok)
    return tokens


def extract_names(lcnaf_path: Path) -> tuple[Counter, Counter]:
    """
    Stream through *lcnaf_path* and count how many LCNAF records contribute
    each surname token and given-name token.

    Returns (surname_counts: Counter, given_counts: Counter) where each value
    is the number of distinct LCNAF personal-name records in which that token
    appeared.  A high count means the token is genuinely used as a name across
    many records; a count of 1–2 typically indicates contamination from a
    corporate-body or conference record that slipped past the personal-name
    filter.
    """
    surname_counts: Counter = Counter()
    given_counts:  Counter = Counter()

    t0 = time.time()
    total_lines = 0
    matched_lines = 0
    personal_count = 0

    print(f'Scanning {lcnaf_path.name} for personal name records …')
    print('(Geographic lines are skipped; personal names identified by label pattern.)')

    with lcnaf_path.open(encoding='utf-8', errors='replace') as fh:
        for lineno, line in enumerate(fh, 1):
            total_lines += 1

            if lineno % 1_000_000 == 0:
                elapsed = time.time() - t0
                print(f'  {lineno / 1e6:.1f}M lines  |  '
                      f'{personal_count:,} personal names  |  '
                      f'{len(surname_counts):,} surnames  |  '
                      f'{len(given_counts):,} given names  |  '
                      f'{elapsed:.0f}s')

            # Fast-path 1: skip geographic name records (have GAC notation)
            if 'codes/gac' in line:
                continue

            # Fast-path 2: skip lines whose prefLabel is a multi-value list
            # (multi-language records like United Nations have
            #  "skos:prefLabel": ["English", {...}, ...] not a plain string).
            # Personal names are almost always single-string labels.
            if '"skos:prefLabel": "' not in line:
                continue

            # Fast-path 3: prefLabel value must contain a comma
            # (personal names in LCNAF inverted form: "Surname, Given ...")
            pfl_idx = line.index('"skos:prefLabel": "')
            if ',' not in line[pfl_idx : pfl_idx + 120]:
                continue

            # Extract the prefLabel string via regex (avoids json.loads overhead)
            m = _LABEL_RE.search(line, pfl_idx)
            if not m:
                continue

            matched_lines += 1
            # Decode any \uXXXX JSON escape sequences so that accented
            # characters (e.g. \u00e4 → ä) are stored in their proper form.
            label = _unescape_json(m.group(1))

            result = parse_personal_name(label)
            if result is None:
                continue

            personal_count += 1
            surname, given = result
            # Split compound surnames into individual tokens so that e.g.
            # "abajo alcalde" and "abajo antón" both contribute "abajo"
            # (once, per record) plus "alcalde" and "antón" separately,
            # rather than two identical-prefix compound strings.
            for tok in _surname_tokens(surname):
                surname_counts[tok] += 1
            if given:                    # None for single-letter initials
                for tok in _given_tokens(given):
                    given_counts[tok] += 1

    elapsed = time.time() - t0
    print(f'\nDone.  Scanned {total_lines:,} lines in {elapsed:.1f}s.')
    print(f'Lines with simple-string prefLabel + comma: {matched_lines:,}')
    print(f'Personal name records identified: {personal_count:,}')
    print(f'Unique surname tokens:     {len(surname_counts):,}')
    print(f'Unique given-name tokens:  {len(given_counts):,}')

    return surname_counts, given_counts


def main():
    ap = argparse.ArgumentParser(
        description='Extract personal name tokens from LCNAF SKOS/RDF JSON-LD.')
    ap.add_argument('--lcnaf',     default='names.skosrdf.jsonld',
                    help='Path to names.skosrdf.jsonld (default: ./names.skosrdf.jsonld)')
    ap.add_argument('--outdir',    default='.',
                    help='Directory for output files (default: current directory)')
    ap.add_argument('--min-freq',  type=int, default=5,
                    help='Minimum record count for a token to appear in the '
                         '"common" frequency-filtered output file '
                         '(default: 5).  Raise to tighten the list; lower to '
                         'keep rarer names.  The full unfiltered lists are '
                         'always written regardless of this setting.')
    args = ap.parse_args()

    lcnaf_path = Path(args.lcnaf)
    outdir     = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not lcnaf_path.exists():
        print(f'ERROR: LCNAF file not found: {lcnaf_path}', file=sys.stderr)
        sys.exit(1)

    surname_counts, given_counts = extract_names(lcnaf_path)

    # ── Full lists (all unique tokens, backward-compatible) ────────────────────
    surnames_path    = outdir / 'lcnaf_surnames.txt'
    given_names_path = outdir / 'lcnaf_given_names.txt'

    surnames_path.write_text(
        '\n'.join(sorted(surname_counts)) + '\n', encoding='utf-8')
    given_names_path.write_text(
        '\n'.join(sorted(given_counts)) + '\n', encoding='utf-8')

    # ── Frequency-filtered given-names list ────────────────────────────────────
    # Tokens that appear in ≥ min_freq records are genuinely used as given names
    # across multiple LCNAF entries.  One-off contamination tokens (common
    # English words like "administrative" that appear exactly once in a
    # corporate-body record that slipped past the personal-name filter) are
    # excluded.  This filtered list is what reconcile_people.py uses for
    # validation.
    min_freq = args.min_freq
    common_given = sorted(tok for tok, cnt in given_counts.items() if cnt >= min_freq)
    common_path  = outdir / 'lcnaf_given_names_common.txt'
    common_path.write_text('\n'.join(common_given) + '\n', encoding='utf-8')

    print(f'\nFrequency threshold: --min-freq {min_freq}')
    print(f'  Given-name tokens with count >= {min_freq}: '
          f'{len(common_given):,}  (of {len(given_counts):,} total)')

    # Show how many tokens fall at a few reference thresholds for tuning:
    for thresh in (2, 5, 10, 20, 50):
        n = sum(1 for cnt in given_counts.values() if cnt >= thresh)
        print(f'    >= {thresh:>3}: {n:>8,} given-name tokens')

    print(f'\nOutput written to:')
    print(f'  {surnames_path}  ({surnames_path.stat().st_size / 1e6:.1f} MB)')
    print(f'  {given_names_path}  ({given_names_path.stat().st_size / 1e6:.1f} MB)')
    print(f'  {common_path}  ({common_path.stat().st_size / 1e6:.1f} MB)  '
          f'← use this for validation')


if __name__ == '__main__':
    main()
