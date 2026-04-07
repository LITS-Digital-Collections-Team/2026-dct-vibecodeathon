#!/usr/bin/env python3
"""
reconcile_people.py — Clean and deduplicate entities_people.csv.

Three main operations, applied in sequence:

1. PLACE KEYWORD FILTER
   Names that contain clear place-type words — "dormitory", "dorm",
   "building", "gallery", "auditorium", "gymnasium" — are not personal
   names.  These rows are removed from the people file and appended to
   entities_places.csv (with LCSH form left as-is for manual review).

2. OCR NAME RECONCILIATION
   OCR mis-reads the same name many ways across 30+ years of scanned
   issues.  This step:
     a) Normalises each name for comparison by lower-casing and
        substituting common OCR digit-for-letter confusions (8→e, 0→o,
        1→l, 5→s, etc.).
     b) Applies comparison normalisation before blocking and matching:
          i.  Leading context-word strip — removes occupational descriptors
              that absorbed into the entity ("Headwaiter Alex Cruden" →
              "Alex Cruden").  Formal titles (Dean, Professor…) are
              intentionally preserved.
          ii. First-name expansion — maps nicknames to canonical long forms
              ("Bob" → "Robert", "Alex" → "Alexander", "Bill" → "William")
              so that nickname variants land in the same block and match at
              the comparison stage.
     c) Groups comparison-normalised names into phonetic blocks using:
          Primary key:    first_initial + Soundex(last_token)
          Secondary key:  first_initial + Soundex(second_token)  [3+ tokens]
          The secondary key catches concatenation artefacts such as
          "Alex Cruden ARTS", "Alex Cruden Rod Baldwin".
     d) Within each block, checks for prefix matches first (always merge),
        then applies token-sort-ratio fuzzy matching.
     d) Uses a Union-Find structure to build connected clusters of
        near-duplicate names.
     e) Selects a canonical form for each cluster by preferring:
          i.  The form with the most distinct source files (most-attested).
          ii. Among ties: the form free of OCR digit artefacts.
          iii. Among remaining ties: standard Title Case.
     f) Merges all variant rows into one canonical row, unioning the file
        lists and expanding the earliest/latest date range.

3. LCNAF NAME VALIDATION  (optional — requires --names-dir)
   After OCR reconciliation, each canonical name is checked against two
   token lists extracted from the LC Name Authority File:
     lcnaf_given_names.txt  — unique given-name tokens
     lcnaf_surnames.txt     — unique surname tokens
   A two-tier check is applied.  Entries attested in 3 or more source files
   are passed through unconditionally — OCR noise is almost always a one-off
   artefact, whereas a genuine person naturally recurs across issues.  For
   single- and double-file entries, the first token of the comparison-
   normalised name must appear in the LCNAF common given-names list (tokens
   appearing ≥ 5 times across all LCNAF records); names that fail are written
   to entities_people_unverified.csv for manual review.  Checking the first
   token specifically targets the given-name position and avoids false passes
   from contamination tokens ("organ", "nassau") that happen to appear ≥ 5
   times in LCNAF surname position.  LEADING_CONTEXT_WORDS stripping in
   comparison_normalise() handles title prefixes ("Librarian Walter …" →
   "walter …").  Nickname expansion ("Bob" → "robert") is also applied.
   lcnaf_given_names_common.txt is preferred; lcnaf_given_names.txt is the
   fallback if the common file has not yet been generated.

Thresholds (adjustable at the top of the file):
  FUZZY_THRESHOLD       — minimum token-sort-ratio for two names to merge
                          (88 works well for 1–2 char OCR errors in a
                          name of 10–15 chars; lower = more aggressive).
  OCR_DIGIT_THRESHOLD   — lower threshold used when one name contains a
                          digit (digit subs inflate edit distance, so we
                          allow more slack).
  TEMPORAL_THRESHOLD    — still-lower threshold used when the fuzzy score
                          falls below FUZZY_THRESHOLD but the two entries
                          appear in overlapping or near-adjacent date ranges
                          (within DATE_PROXIMITY_DAYS of each other).
                          E.g. "Al Braveman" (1 file, Nov 1967) merges into
                          "Al Braverman" (6 files, Oct 1967–Oct 1970).
  DATE_PROXIMITY_DAYS   — how many days apart two entries' date ranges may
                          be and still qualify for the temporal rule (365 =
                          ±1 year).
  MAX_BLOCK_SIZE        — skip pairwise comparison in blocks larger than
                          this (avoids false positives in common-surname
                          Soundex collisions).

Outputs:
  entities_people_clean.csv        — reconciled people (LCNAF-verified if --names-dir given)
  entities_people_unverified.csv   — names that failed LCNAF check (only with --names-dir)
  entities_places_augmented.csv    — original places + moved-from-people
  reconciliation_report.tsv        — audit trail: every merge decision

Usage:
  python3 reconcile_people.py \\
      --people     entities_people.csv \\
      --places     entities_places.csv \\
      --outdir     /path/to/output/dir \\
      --names-dir  /path/to/lcnaf_name_lists/   # optional; enables LCNAF check

Requirements: Python 3.8+, rapidfuzz
  pip install rapidfuzz --break-system-packages
"""

import re
import csv
import sys
import argparse
from datetime import date
from pathlib import Path
from collections import defaultdict

from rapidfuzz import fuzz

# ── Tunable parameters ─────────────────────────────────────────────────────────
FUZZY_THRESHOLD     = 88   # minimum token-sort-ratio to merge two names
OCR_DIGIT_THRESHOLD = 80   # lower threshold when a name contains a digit
MAX_BLOCK_SIZE      = 150  # skip pairwise comparison in very large blocks

# Temporal proximity merge: when two names score below FUZZY_THRESHOLD but
# above TEMPORAL_THRESHOLD, AND their date ranges are within DATE_PROXIMITY_DAYS
# of each other, they are still merged.  The intuition: "Al Braveman" appearing
# once in November 1967 is almost certainly an OCR error for "Al Braverman",
# which appears six times between October 1967 and October 1970.  A fuzzy score
# of ~78–87 combined with overlapping or near-adjacent dates is strong evidence
# of a variant rather than a distinct person.
#
# Lower TEMPORAL_THRESHOLD → more aggressive (catches more variants, more risk
# of false merges).  Raise DATE_PROXIMITY_DAYS to allow wider time gaps.
TEMPORAL_THRESHOLD   = 78   # lower fuzzy threshold when date ranges are close
DATE_PROXIMITY_DAYS  = 365  # ±1 year: how close date ranges must be to apply

# ── Place-type keywords ────────────────────────────────────────────────────────
# A PERSON name containing any of these (case-insensitive) is really a place.
PLACE_KEYWORDS = [
    'dormitory', 'dorm', 'gallery', 'auditorium', 'gymnasium',
    'coliseum', 'stadium', 'arena', 'amphitheatre', 'amphitheater',
]
# "building" is only treated as a place indicator when it appears at the
# end of the name (avoids catching surnames like "Building" used poetically).
BUILDING_END_RE = re.compile(r'\bbuilding\s*$', re.IGNORECASE)

# ── Leading context-word strip ─────────────────────────────────────────────────
# Occupational or descriptive words that sometimes appear before a personal name
# in newspaper copy and end up absorbed into the entity by the OCR/NER pipeline.
# E.g. "Headwaiter Alex Cruden", "Photographer Bill Scoones".
# These are stripped ONLY during comparison normalisation, not from the stored name.
#
# NOTE: formal titles handled by PROFESSIONAL_TITLES (Dean, Professor, Coach, etc.)
# are intentionally EXCLUDED here — "Dean Tolles" should not be stripped to "Tolles".
LEADING_CONTEXT_WORDS = {
    # Food-service / hospitality
    'headwaiter', 'waiter', 'waitress', 'busboy', 'hostess',
    'bartender', 'cook', 'chef', 'steward', 'stewardess',
    # Press / publishing
    'photographer', 'cameraman', 'photog',
    'reporter', 'journalist', 'correspondent', 'columnist',
    'writer', 'author', 'poet', 'novelist', 'playwright',
    'illustrator', 'cartoonist', 'designer',
    # Campus / academic (non-title)
    'student', 'freshman', 'sophomore', 'junior', 'senior',
    'alumnus', 'alumna', 'alum', 'graduate', 'grad',
    'scholar', 'researcher', 'fellow', 'intern',
    'instructor', 'teacher', 'lecturer',   # "professor" stays in PROFESSIONAL_TITLES
    # Administrative / civic (non-title)
    'trustee', 'regent', 'member', 'delegate', 'envoy',
    'spokesman', 'spokeswoman', 'spokesperson',
    'volunteer', 'worker', 'employee', 'aide', 'assistant', 'clerk',
    'owner', 'proprietor', 'founder', 'operator',
    # Institutional title modifiers — appear before a formal title or a name;
    # stripping them exposes the following given name for LCNAF lookup.
    # E.g. "Librarian Walter Pilkington" → "Walter Pilkington"
    #      "Visiting Professor Smith"     → "Professor Smith"  (title preserved)
    'librarian', 'archivist', 'curator',
    'coach', 'trainer',
    'director', 'administrator',
    'visiting', 'adjunct', 'acting', 'associate', 'assistant',
    'former', 'emeritus',
    # Arts / performance
    'conductor', 'musician', 'singer', 'performer',
    'artist', 'painter', 'sculptor', 'actor', 'actress',
    # Other trades
    'architect', 'engineer', 'scientist',
    'lawyer', 'attorney', 'solicitor', 'accountant', 'consultant',
    'custodian', 'janitor', 'doorman', 'guard', 'officer',
    # Sports (non-title)
    'athlete', 'player', 'golfer', 'swimmer', 'runner',
    'pitcher', 'catcher', 'quarterback', 'halfback',
}

# ── First-name expansion table ─────────────────────────────────────────────────
# Maps common shortened/nickname first names (lower-case) to their canonical
# long form, used ONLY during comparison normalisation.
# This allows "Bob Smith" and "Robert Smith" to match even though they start
# with different letters and land in different Soundex blocks.
#
# Canonical form chosen: the full formal name most likely to appear in an
# authoritative record (LCNAF, college roster, etc.).
#
# ⚠ A few entries are ambiguous — see inline notes.  Comment out any that
#   produce false merges in your specific corpus.
FIRST_NAME_EXPANSIONS: dict[str, str] = {
    # A ──────────────────────────────────────────────────────────────────────
    'al':      'alfred',     # ⚠ also Albert, Alan — most common in this era
    'alex':    'alexander',
    'abe':     'abraham',
    'andy':    'andrew',
    'art':     'arthur',
    # B ──────────────────────────────────────────────────────────────────────
    'bart':    'bartholomew',
    'ben':     'benjamin',
    'benny':   'benjamin',
    'bill':    'william',
    'billy':   'william',
    'bob':     'robert',
    'bobby':   'robert',
    'brad':    'bradley',
    # C ──────────────────────────────────────────────────────────────────────
    'charlie': 'charles',
    'chuck':   'charles',
    'chris':   'christopher',
    # D ──────────────────────────────────────────────────────────────────────
    'dan':     'daniel',
    'danny':   'daniel',
    'dave':    'david',
    'davy':    'david',
    'dick':    'richard',
    'don':     'donald',
    'donny':   'donald',
    # E ──────────────────────────────────────────────────────────────────────
    'ed':      'edward',
    'eddie':   'edward',
    'ned':     'edward',
    'ted':     'edward',     # ⚠ also Theodore
    # F ──────────────────────────────────────────────────────────────────────
    'fred':    'frederick',
    'freddy':  'frederick',
    # G ──────────────────────────────────────────────────────────────────────
    'gene':    'eugene',
    'geoff':   'geoffrey',
    'gus':     'augustus',   # ⚠ also Gustave / Gustav
    # H ──────────────────────────────────────────────────────────────────────
    'hal':     'harold',     # ⚠ also Henry
    'hank':    'henry',
    # J ──────────────────────────────────────────────────────────────────────
    'jack':    'john',       # ⚠ also Jakob / Jacques in some traditions
    'jake':    'jacob',
    'jeff':    'jeffrey',
    'jim':     'james',
    'jimmy':   'james',
    'joe':     'joseph',
    'joey':    'joseph',
    'johnny':  'john',
    'jon':     'jonathan',
    # K ──────────────────────────────────────────────────────────────────────
    'ken':     'kenneth',
    'kenny':   'kenneth',
    # L ──────────────────────────────────────────────────────────────────────
    'larry':   'lawrence',
    'len':     'leonard',
    'lenny':   'leonard',
    'lew':     'lewis',
    'louie':   'louis',
    'lou':     'louis',
    # M ──────────────────────────────────────────────────────────────────────
    'matt':    'matthew',
    'mike':    'michael',
    'mickey':  'michael',
    'mitch':   'mitchell',
    # N ──────────────────────────────────────────────────────────────────────
    'nat':     'nathaniel',
    'nate':    'nathaniel',
    'nick':    'nicholas',
    # P ──────────────────────────────────────────────────────────────────────
    'pat':     'patrick',
    'pete':    'peter',
    'phil':    'philip',
    # R ──────────────────────────────────────────────────────────────────────
    'ray':     'raymond',
    'rich':    'richard',
    'rick':    'richard',
    'ricky':   'richard',
    'rob':     'robert',
    'ron':     'ronald',
    'ronny':   'ronald',
    # S ──────────────────────────────────────────────────────────────────────
    'sam':     'samuel',
    'sammy':   'samuel',
    'sandy':   'alexander',  # ⚠ also Sandra — likely male in pre-1978 corpus
    'stan':    'stanley',
    'steve':   'stephen',
    'stevie':  'stephen',
    # T ──────────────────────────────────────────────────────────────────────
    'tim':     'timothy',
    'timmy':   'timothy',
    'tom':     'thomas',
    'tommy':   'thomas',
    'tony':    'anthony',
    # V ──────────────────────────────────────────────────────────────────────
    'vin':     'vincent',
    'vince':   'vincent',
    # W ──────────────────────────────────────────────────────────────────────
    'wally':   'walter',
    'walt':    'walter',
    'will':    'william',
    'willie':  'william',
}

# ── OCR digit → likely letter substitution map ─────────────────────────────────
OCR_SUBS = str.maketrans({
    '0': 'o', '1': 'l', '2': 'z', '3': 'e', '4': 'a',
    '5': 's', '6': 'b', '7': 't', '8': 'e', '9': 'g',
})

HAS_DIGIT_RE = re.compile(r'[0-9]')


# ── Soundex ────────────────────────────────────────────────────────────────────
_SOUNDEX_MAP = {
    'B': '1', 'F': '1', 'P': '1', 'V': '1',
    'C': '2', 'G': '2', 'J': '2', 'K': '2',
    'Q': '2', 'S': '2', 'X': '2', 'Z': '2',
    'D': '3', 'T': '3',
    'L': '4',
    'M': '5', 'N': '5',
    'R': '6',
}

def soundex(word: str) -> str:
    """Return a 4-char Soundex code for *word* (alphabetic chars only)."""
    word = re.sub(r'[^A-Za-z]', '', word).upper()
    if not word:
        return '0000'
    first = word[0]
    result = first
    prev_code = _SOUNDEX_MAP.get(first, '0')
    for ch in word[1:]:
        code = _SOUNDEX_MAP.get(ch, '0')
        if code != '0' and code != prev_code:
            result += code
        prev_code = code
        if len(result) == 4:
            break
    return (result + '0000')[:4]


# ── Name normalisation ─────────────────────────────────────────────────────────

def ocr_normalise(name: str) -> str:
    """Lower-case, apply digit substitutions, strip non-alpha/space chars."""
    name = name.lower().translate(OCR_SUBS)
    name = re.sub(r"[^a-z\s'\-]", '', name)
    return re.sub(r'\s+', ' ', name).strip()


def comparison_normalise(name: str) -> str:
    """
    Full normalisation used ONLY for blocking and similarity comparison
    (never stored or shown to users).  Chains three operations:

    1. OCR normalisation (lower-case + digit substitutions).
    2. Leading context-word strip: removes occupational/descriptive words
       that sometimes prefix a name in newspaper copy, e.g.:
         "Headwaiter Alex Cruden"  →  "alex cruden"
         "Photographer Bill Scoones"  →  "bill scoones"
       Formal titles (Dean, Professor, Coach…) are intentionally NOT
       stripped — they are part of the recognised name form.
    3. First-name expansion: maps common shortened first names to their
       full canonical forms so that nickname variants land in the same
       comparison block, e.g.:
         "bob"  →  "robert"   (Bob Smith ↔ Robert Smith)
         "alex" →  "alexander" (Alex Cruden ↔ Alexander Cruden)
         "bill" →  "william"  (Bill Scoones ↔ William Scoones)
    """
    tokens = ocr_normalise(name).split()

    # Step 2: strip leading context/occupational words
    # (stop as soon as we hit a non-context word to avoid over-stripping)
    while tokens and tokens[0] in LEADING_CONTEXT_WORDS:
        tokens = tokens[1:]

    # Step 3: expand first name if it's a known nickname
    if tokens and tokens[0] in FIRST_NAME_EXPANSIONS:
        tokens[0] = FIRST_NAME_EXPANSIONS[tokens[0]]

    return ' '.join(tokens)


def block_key(comp_norm: str) -> str:
    """
    Blocking key = first-name-initial + Soundex(last token).
    Accepts a *pre-computed comparison_normalise() string* so that
    context-stripped and first-name-expanded forms are used consistently.
    """
    tokens = comp_norm.split()
    if not tokens:
        return 'X_0000'
    first_init = tokens[0][0].upper() if tokens[0] else 'X'
    last_token = tokens[-1] if len(tokens) > 1 else tokens[0]
    return f'{first_init}_{soundex(last_token)}'


def has_ocr_digit(name: str) -> bool:
    return bool(HAS_DIGIT_RE.search(name))


def dates_are_close(ri: dict, rj: dict,
                    max_days: int = DATE_PROXIMITY_DAYS) -> bool:
    """
    Return True if the publication date ranges of two CSV rows are within
    *max_days* of each other (or overlap).

    Each row has 'earliest_date' and 'latest_date' fields (ISO-8601 strings,
    e.g. "1967-10-06").  The function computes the gap between the two ranges:

      range_i = [earliest_i, latest_i]
      range_j = [earliest_j, latest_j]

    If the ranges overlap the gap is 0 (always close).  Otherwise the gap is
    the minimum of (earliest_j − latest_i) and (earliest_i − latest_j).

    Returns False if either row is missing all date fields (conservative: we
    only apply the temporal rule when we have evidence to work with).
    """
    def parse_row_dates(row: dict) -> list:
        out = []
        for field in ('earliest_date', 'latest_date'):
            val = row.get(field, '').strip()
            if val:
                try:
                    out.append(date.fromisoformat(val))
                except ValueError:
                    pass
        return out

    di = parse_row_dates(ri)
    dj = parse_row_dates(rj)
    if not di or not dj:
        return False   # can't evaluate without dates

    i_min, i_max = min(di), max(di)
    j_min, j_max = min(dj), max(dj)

    # Overlapping ranges → gap = 0 → always within max_days
    if i_min <= j_max and j_min <= i_max:
        return True

    # Non-overlapping: gap is the distance between the nearest endpoints
    gap = min(abs((i_min - j_max).days), abs((j_min - i_max).days))
    return gap <= max_days


def _token_case_score(token: str) -> int:
    """
    Score a single name token by how well-formed its capitalisation is.
      +2  Proper title-case  ("Hawkes", "DiMiceli" with ≤2 internal caps)
      +1  Short token ≤2 chars — assume OK
       0  Mixed-internal-caps beyond 2 ("SpRoaT") — likely OCR noise
      -1  All-lowercase        — clearly mis-cased
      -2  All-uppercase >2 chars ("ALFRED", "HAWKES") — OCR artefact
    """
    t = re.sub(r"[^A-Za-z]", '', token)
    if not t:
        return 0
    if len(t) <= 2:
        return 1
    if t.isupper():
        return -2   # ALL CAPS — bad
    if t[0].islower():
        return -1   # lowercase start — bad
    # Count uppercase letters in positions 1+
    internal_upper = sum(1 for c in t[1:] if c.isupper())
    if internal_upper <= 2:
        return 2    # title-case or standard mixed (DiMiceli, MacDonald)
    return 0        # too many internal caps — OCR noise


def canonical_score(row: dict) -> tuple:
    """
    Higher score = better canonical candidate.
    Priority (most to least important):
      1. No OCR digit artefacts in the name
      2. Number of source files (most-attested = most likely correct)
      3. Capitalisation quality (title-case tokens beat all-caps beats mixed-caps)
    """
    name = row['name']
    file_count = len(row['files'].split(';'))
    no_digit   = 0 if has_ocr_digit(name) else 1
    case_score = sum(_token_case_score(t) for t in name.split())
    return (no_digit, file_count, case_score)


# ── Place keyword filter ───────────────────────────────────────────────────────

def is_place_name(name: str) -> bool:
    nl = name.lower()
    if any(kw in nl for kw in PLACE_KEYWORDS):
        return True
    if BUILDING_END_RE.search(name):
        return True
    return False


# ── LCNAF name validator ───────────────────────────────────────────────────────

# ── Tokens that are known non-name words despite appearing ≥ 5 times in ────────
# LCNAF given-name position (contamination from corporate/geographic records).
# These are excluded from the given-name check to prevent false passes.
_NOT_GIVEN_NAMES: frozenset[str] = frozenset({
    'american', 'building', 'central', 'eastern', 'general', 'great',
    'international', 'lower', 'national', 'new', 'northern', 'old',
    'royal', 'southern', 'upper', 'western',
})


def load_name_lists(names_dir: Path) -> tuple:
    """
    Load the LCNAF given-name list from *names_dir*.

    Prefers lcnaf_given_names_common.txt (frequency-filtered, tokens appearing
    ≥ 5 times across LCNAF records) over lcnaf_given_names.txt.  The common
    file is produced by extract_lcnaf_names.py --min-freq 5; the full file is
    used as a fallback if the common file does not yet exist.

    Returns (given_names,) as a 1-tuple containing a frozenset of lowercase
    strings.  The surnames list is not used for validation — it contains too
    many common English words to be a reliable discriminator.
    """
    common_path = names_dir / 'lcnaf_given_names_common.txt'
    full_path   = names_dir / 'lcnaf_given_names.txt'

    if common_path.exists():
        src = common_path
        label = 'common (frequency-filtered)'
    else:
        src = full_path
        label = 'full (frequency-filtering not available — run extract_lcnaf_names.py)'

    given_names = frozenset(
        line.strip() for line in src.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ) - _NOT_GIVEN_NAMES

    print(f'LCNAF validator: {len(given_names):,} given-name tokens loaded '
          f'from {src.name}  [{label}].')
    return (given_names,)


def name_has_lcnaf_support(name: str,
                           given_names: frozenset,
                           file_count: int = 1) -> bool:
    """
    Return True if *name* looks like a genuine personal name based on the
    LCNAF common given-names list.

    Two-tier check:

    Tier 1 — multi-file bypass (file_count >= 3):
      Entries attested in 3 or more distinct source files are almost certainly
      real people: OCR noise and section headers are typically one-off
      artefacts that appear in a single issue.  These are passed through
      without a name-list check.

    Tier 2 — LCNAF first-token check (file_count < 3):
      The first token of the comparison-normalised name must appear in the
      LCNAF common given-names list.  LEADING_CONTEXT_WORDS stripping is
      already applied by comparison_normalise(), so occupational or
      institutional title prefixes ("Librarian", "Coach", "Visiting") are
      removed before the lookup.

      Checking the first token only (not any token) is deliberate:
        - Personal names are written "Given Surname".
        - Non-personal entries ("Academic Dean", "Administrative Organ",
          "American Writing") start with adjectives, nouns, or abbreviations
          that do not appear in the given-names list.
        - Checking any token would allow contamination tokens ("organ",
          "nassau") that appear ≥ 5 times in LCNAF to rescue non-name entries.

      Nickname expansion via comparison_normalise() means that "Bob Smith" →
      "robert smith" → first token "robert" → found in given names.

    Single-token names always return False — a bare word with no surname is
    almost certainly a fragment rather than a full personal name.
    """
    comp   = comparison_normalise(name)
    tokens = comp.split()
    if len(tokens) < 2:
        return False
    # Tier 1: trust multi-file entries — genuine people recur across issues
    if file_count >= 3:
        return True
    # Tier 2: strict given-name check for single- and double-file entries
    return tokens[0] in given_names


# ── Union-Find ─────────────────────────────────────────────────────────────────

class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank   = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, x: int, y: int):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


# ── Merging helpers ────────────────────────────────────────────────────────────

def merge_rows(rows: list[dict]) -> dict:
    """Collapse a cluster of variant rows into one canonical row."""
    canonical_row = max(rows, key=canonical_score)
    all_files = set()
    all_dates = []
    for r in rows:
        all_files.update(r['files'].split(';'))
        if r['earliest_date']:
            all_dates.append(r['earliest_date'])
        if r['latest_date']:
            all_dates.append(r['latest_date'])
    all_dates = [d for d in all_dates if d]
    return {
        'name':          canonical_row['name'],
        'earliest_date': min(all_dates) if all_dates else '',
        'latest_date':   max(all_dates) if all_dates else '',
        'files':         ';'.join(sorted(all_files)),
    }


# ── Main pipeline ──────────────────────────────────────────────────────────────

def reconcile(people_path: Path, places_path: Path, outdir: Path,
              name_lists: tuple | None = None):
    outdir.mkdir(parents=True, exist_ok=True)

    # ── 1. Load input CSVs ────────────────────────────────────────────────────
    people_rows = list(csv.DictReader(people_path.open(encoding='utf-8')))
    places_rows = list(csv.DictReader(places_path.open(encoding='utf-8')))
    print(f'Loaded {len(people_rows):,} people rows, {len(places_rows):,} places rows.')

    # ── 2. Place keyword filter ───────────────────────────────────────────────
    keep_rows   = []
    moved_rows  = []   # will be appended to places
    for row in people_rows:
        if is_place_name(row['name']):
            moved_rows.append(row)
        else:
            keep_rows.append(row)

    print(f'Place-keyword filter: moved {len(moved_rows)} rows to places, '
          f'{len(keep_rows)} remain in people.')

    # ── 3. Pre-compute comparison norms (used for both blocking and matching) ──
    # comparison_normalise() applies OCR normalisation, leading context-word
    # stripping, and first-name expansion.  We compute it once per row and
    # reuse it throughout steps 3 and 4 for consistency and speed.
    comp_norms: list[str] = [
        comparison_normalise(row['name']) for row in keep_rows
    ]

    # ── 4. Build blocks ───────────────────────────────────────────────────────
    # Each name is assigned to one or more blocks so that true variants land
    # in the same block even when trailing tokens differ.
    #
    # Primary key:   first_initial + Soundex(last_token)  [on comparison norm]
    #   → catches spelling variants AND nickname expansions:
    #     "Bob Smith" expands to "robert smith" → same block as "Robert Smith"
    #     "Headwaiter Alex Cruden" strips to "alex cruden" → same block as
    #     "Alex Cruden" after expansion to "alexander cruden"
    #
    # Secondary key: first_initial + Soundex(second_token)  [3+ token names only]
    #   → catches concatenation artefacts where extra tokens were appended
    #     after the real last name, e.g. "Alex Cruden ARTS", "Alex Cruden NEWS",
    #     "Alex Cruden Rod Baldwin" — all share second_token "Cruden" → same block
    #     as the canonical "Alex Cruden".
    blocks: dict[str, list[int]] = defaultdict(list)
    for idx, comp_norm in enumerate(comp_norms):
        tokens = comp_norm.split()
        # Primary block (uses comparison norm, so context-stripped + expanded)
        pkey = block_key(comp_norm)
        blocks[pkey].append(idx)
        # Secondary block: for 3+ token comp-norm, key on second token
        if len(tokens) >= 3:
            first_init = tokens[0][0].upper() if tokens[0] else 'X'
            sec_key = f'{first_init}_{soundex(tokens[1])}'
            if sec_key != pkey:   # avoid double-adding to same block
                blocks[sec_key].append(idx)

    # ── 5. Within-block fuzzy matching → merge pairs ─────────────────────────
    uf = UnionFind(len(keep_rows))
    merge_log: list[dict] = []   # for the reconciliation report

    total_pairs_checked = 0
    for bkey, indices in blocks.items():
        if len(indices) < 2:
            continue
        if len(indices) > MAX_BLOCK_SIZE:
            # Block too large: high risk of false positives, skip
            continue

        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                total_pairs_checked += 1
                # Use comparison norms (context-stripped, first-name-expanded)
                # for both prefix and fuzzy matching.
                ni = comp_norms[indices[i]]
                nj = comp_norms[indices[j]]
                ri, rj = keep_rows[indices[i]], keep_rows[indices[j]]

                # ── Prefix match rule ────────────────────────────────────────
                # If the shorter normalised name is an exact prefix of the
                # longer one (token-boundary aligned), this is a concatenation
                # artefact: the OCR engine attached a section label or an
                # adjacent name.  Examples:
                #   "Alex Cruden"  →  "Alex Cruden ARTS"
                #   "Alex Cruden"  →  "Alex Cruden NEWS SULORS"
                #   "Alex Cruden"  →  "Alex Cruden Rod Baldwin"
                # We treat prefix matches as score = 100, bypassing the fuzzy
                # threshold, and always merge them.
                shorter, longer = (ni, nj) if len(ni) <= len(nj) else (nj, ni)
                is_prefix = (
                    longer.startswith(shorter)
                    and (len(longer) == len(shorter)          # identical
                         or longer[len(shorter)] == ' ')      # token boundary
                )
                if is_prefix:
                    score = 100.0
                    reason = 'prefix'
                else:
                    # ── Fuzzy match rule ─────────────────────────────────────
                    # Lower threshold when a name contains an OCR digit artefact.
                    threshold = (OCR_DIGIT_THRESHOLD
                                 if has_ocr_digit(ri['name']) or has_ocr_digit(rj['name'])
                                 else FUZZY_THRESHOLD)
                    score = fuzz.token_sort_ratio(ni, nj)
                    if score >= threshold:
                        reason = 'fuzzy'
                    elif score >= TEMPORAL_THRESHOLD and dates_are_close(ri, rj):
                        # ── Temporal proximity rule ──────────────────────────
                        # Score is below the normal threshold but above the
                        # temporal threshold, AND the two entries appear in
                        # overlapping or near-adjacent publication windows (≤1 yr
                        # apart by default).  This catches one-off OCR variants
                        # like "Al Braveman" (1 file, Nov 1967) which should merge
                        # into "Al Braverman" (6 files, Oct 1967 – Oct 1970).
                        # The canonical_score() already prefers the more-attested
                        # form, so the right name is kept automatically.
                        #
                        # Surname guard — required for temporal merges only:
                        # A shared multi-word title ("Associate Dean", "Assistant
                        # Professor") can push token_sort_ratio above
                        # TEMPORAL_THRESHOLD even when the surnames are completely
                        # different (e.g. "Associate Dean DePuy" vs "Associate Dean
                        # Hadley").  We require that the last tokens of the two
                        # comparison-normalised names are themselves sufficiently
                        # similar before allowing a temporal merge.  Character-level
                        # fuzz.ratio is used (not token_sort_ratio) so that a bare
                        # surname like "braveman" / "braverman" scores correctly.
                        last_i = ni.split()[-1] if ni.split() else ''
                        last_j = nj.split()[-1] if nj.split() else ''
                        if fuzz.ratio(last_i, last_j) < TEMPORAL_THRESHOLD:
                            continue  # surnames too different; title is inflating score
                        reason = 'temporal_proximity'
                    else:
                        continue   # no merge

                uf.union(indices[i], indices[j])
                merge_log.append({
                    'name_a':   ri['name'],
                    'files_a':  len(ri['files'].split(';')),
                    'name_b':   rj['name'],
                    'files_b':  len(rj['files'].split(';')),
                    'score':    score,
                    'block':    bkey,
                    'reason':   reason,
                })

    print(f'Checked {total_pairs_checked:,} within-block name pairs.')

    # ── 5. Build clusters from Union-Find ─────────────────────────────────────
    clusters: dict[int, list[dict]] = defaultdict(list)
    for idx, row in enumerate(keep_rows):
        clusters[uf.find(idx)].append(row)

    merged_count   = sum(1 for c in clusters.values() if len(c) > 1)
    variant_count  = sum(len(c) - 1 for c in clusters.values() if len(c) > 1)
    singleton_count = sum(1 for c in clusters.values() if len(c) == 1)
    print(f'Clusters: {merged_count} merged groups '
          f'({variant_count} variants collapsed), '
          f'{singleton_count} singletons unchanged.')

    # ── 6. Produce final rows ─────────────────────────────────────────────────
    clean_rows = []
    for cluster_rows in clusters.values():
        clean_rows.append(merge_rows(cluster_rows))

    # Sort by name, case-insensitive
    clean_rows.sort(key=lambda r: r['name'].lower())

    # ── 6b. LCNAF name validation (optional) ──────────────────────────────────
    # When --names-dir is supplied, each canonical name is checked against
    # the LCNAF given-name and surname token lists.  Names that do not have
    # at least one token in each list are written to a separate
    # entities_people_unverified.csv for manual review.  This catches
    # non-personal entities (place names, organisation abbreviations, OCR
    # garbage) that survived the earlier filters.
    unverified_rows: list[dict] = []
    if name_lists is not None:
        (given_names,) = name_lists
        verified: list[dict] = []
        for row in clean_rows:
            n_files = len(row['files'].split(';'))
            if name_has_lcnaf_support(row['name'], given_names, n_files):
                verified.append(row)
            else:
                unverified_rows.append(row)
        print(f'LCNAF name check: {len(verified):,} verified, '
              f'{len(unverified_rows):,} unverified '
              f'(→ entities_people_unverified.csv).')
        clean_rows = verified

    # ── 7. Augmented places ───────────────────────────────────────────────────
    # Moved rows arrive without LCSH standardisation — flag them for review.
    augmented_places = list(places_rows)
    for row in moved_rows:
        augmented_places.append({
            'name':          row['name'] + '  [moved from people — review LCSH form]',
            'earliest_date': row['earliest_date'],
            'latest_date':   row['latest_date'],
            'files':         row['files'],
        })
    augmented_places.sort(key=lambda r: r['name'].lower())

    # ── 8. Write outputs ──────────────────────────────────────────────────────
    PEOPLE_HEADER = ['name', 'earliest_date', 'latest_date', 'files']
    PLACES_HEADER = ['name', 'earliest_date', 'latest_date', 'files']
    REPORT_HEADER = ['name_a', 'files_a', 'name_b', 'files_b',
                     'similarity_score', 'canonical_chosen', 'block_key',
                     'merge_reason']

    people_out = outdir / 'entities_people_clean.csv'
    with people_out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=PEOPLE_HEADER)
        w.writeheader()
        w.writerows(clean_rows)
    print(f'  → {people_out.name}: {len(clean_rows):,} entities')

    if unverified_rows:
        unverified_out = outdir / 'entities_people_unverified.csv'
        with unverified_out.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=PEOPLE_HEADER)
            w.writeheader()
            w.writerows(unverified_rows)
        print(f'  → {unverified_out.name}: {len(unverified_rows):,} entities '
              f'(failed LCNAF name check — review manually)')

    places_out = outdir / 'entities_places_augmented.csv'
    with places_out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=PLACES_HEADER)
        w.writeheader()
        w.writerows(augmented_places)
    print(f'  → {places_out.name}: {len(augmented_places):,} entities '
          f'({len(moved_rows)} added from people)')

    # Reconciliation report: annotate with which name was chosen canonical
    # Build a quick lookup: if name_a and name_b are in the same cluster,
    # the canonical is whichever block_name was selected by merge_rows.
    # For the report we annotate each merge pair.
    report_out = outdir / 'reconciliation_report.tsv'
    # Build name→canonical lookup
    name_to_canonical: dict[str, str] = {}
    for cluster_rows in clusters.values():
        canon = merge_rows(cluster_rows)['name']
        for r in cluster_rows:
            name_to_canonical[r['name']] = canon

    with report_out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=REPORT_HEADER, delimiter='\t')
        w.writeheader()
        for entry in sorted(merge_log, key=lambda e: -e['score']):
            w.writerow({
                'name_a':           entry['name_a'],
                'files_a':          entry['files_a'],
                'name_b':           entry['name_b'],
                'files_b':          entry['files_b'],
                'similarity_score': entry['score'],
                'canonical_chosen': name_to_canonical.get(entry['name_a'],
                                    entry['name_a']),
                'block_key':        entry['block'],
                'merge_reason':     entry.get('reason', 'fuzzy'),
            })
    print(f'  → {report_out.name}: {len(merge_log):,} merge decisions logged')

    print('\nDone.')
    return clean_rows, unverified_rows, augmented_places, merge_log


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description='Reconcile OCR name variants in entities_people.csv.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--people',    '-p', required=True,
                   help='Path to entities_people.csv')
    p.add_argument('--places',    '-l', required=True,
                   help='Path to entities_places.csv (for augmentation)')
    p.add_argument('--outdir',    '-o', required=True,
                   help='Directory for output files')
    p.add_argument('--names-dir', '-n', default=None,
                   help='Directory containing lcnaf_given_names.txt and '
                        'lcnaf_surnames.txt (enables LCNAF name validation). '
                        'Omit to skip validation.')
    args = p.parse_args()

    name_lists = None
    if args.names_dir:
        names_dir  = Path(args.names_dir).expanduser().resolve()
        name_lists = load_name_lists(names_dir)

    reconcile(
        people_path = Path(args.people).expanduser().resolve(),
        places_path = Path(args.places).expanduser().resolve(),
        outdir      = Path(args.outdir).expanduser().resolve(),
        name_lists  = name_lists,
    )


if __name__ == '__main__':
    main()
