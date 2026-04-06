#!/usr/bin/env python3
"""
ner_extract.py — Extract named entities from cleaned OCR newspaper files.

Designed for the Hamilton College Spectator corpus (1947–1980).

Produces three CSV files:
  entities_people.csv       — personal names
  entities_orgs_events.csv  — organizations and named events
  entities_places.csv       — geographic places (LCSH-standardized)

Each CSV has columns:
  name | earliest_date | latest_date | files

Person-name rules:
  KEEP  — First + Last  (e.g., "John Allen")
  KEEP  — Professional/academic title + Last  (e.g., "Dean Tolles", "Dr. Smith")
  KEEP  — Courtesy title + Last  ONLY if a full first+last form of that surname
           appears elsewhere in the same file (within-document reconciliation)
  DROP  — First name only, last name only, all-caps tokens (headline noise)

Place standardization:
  Rule-based LCSH geographic heading format (no external API calls).
  US cities are qualified as "City (State.)" using LCSH abbreviations.
  International cities as "City (Country)".
  Unknown places are left as extracted.

Usage:
  python3 ner_extract.py --input INPUT_DIR --output OUTPUT_DIR

Requirements: Python 3.8+, spaCy 3.x with en_core_web_lg
  pip install spacy --break-system-packages
  python3 -m spacy download en_core_web_lg
"""

import re
import csv
import sys
import argparse
from pathlib import Path
from collections import defaultdict

import spacy

# ── Configuration ──────────────────────────────────────────────────────────────

# Professional / academic / religious / government / military titles.
# A PERSON entity whose first token is one of these + a last name is kept.
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
    'mayor', 'alderman', 'alderperson', 'constable',
}

# Courtesy titles — kept ONLY when reconciled with a full name in the same file.
COURTESY_TITLES = {'mr', 'mrs', 'miss', 'ms', 'mme', 'mdme'}

ALL_TITLES = PROFESSIONAL_TITLES | COURTESY_TITLES

# Noise: short tokens, all-caps (OCR headline junk), purely non-alpha.
NOISE_RE  = re.compile(r'^[^A-Za-z]+$')        # no alphabetic characters at all
ALLCAPS_RE = re.compile(r'^[A-Z][A-Z\s\.\-]+$')  # e.g., "HAMILTON COLLEGE"

# Common connectors allowed inside multi-token names (van, de, etc.)
NAME_CONNECTORS = {'de', 'di', 'du', 'van', 'von', 'der', 'den', 'la', 'le',
                   'el', 'al', 'del', 'della', 'da', 'do', 'das', 'dos', 'mac'}

# Phrases that look like names but are not people.
PERSON_BLOCKLIST = {
    'alma mater', 'sub freshman', 'sub-freshman', 'old middle',
    'young republican', 'young democrats', 'big red',
}

# Leading non-alpha characters to strip from entity text (OCR artefacts)
LEADING_PUNCT_RE = re.compile(r'^[^A-Za-z]+')
# Trailing non-alpha characters to strip
TRAILING_PUNCT_RE = re.compile(r'[^A-Za-z\.\)]+$')

# ── LCSH rule-based place-name lookup ─────────────────────────────────────────
# Format: extracted name (case-insensitive) → LCSH authorized form.
# Drawn from LC authority file patterns for this corpus's likely place names.

LCSH_PLACES: dict[str, str] = {
    # ── Central New York / local ──────────────────────────────────────────────
    'clinton':         'Clinton (N.Y.)',
    'hamilton':        'Hamilton (N.Y.)',
    'utica':           'Utica (N.Y.)',
    'rome':            'Rome (N.Y.)',
    'new hartford':    'New Hartford (N.Y.)',
    'whitesboro':      'Whitesboro (N.Y.)',
    'oriskany':        'Oriskany (N.Y.)',
    'oneida':          'Oneida (N.Y.)',
    'cazenovia':       'Cazenovia (N.Y.)',
    'morrisville':     'Morrisville (N.Y.)',
    'cooperstown':     'Cooperstown (N.Y.)',
    'cortland':        'Cortland (N.Y.)',

    # ── New York State ────────────────────────────────────────────────────────
    'new york':        'New York (N.Y.)',
    'new york city':   'New York (N.Y.)',
    'nyc':             'New York (N.Y.)',
    'manhattan':       'Manhattan (New York, N.Y.)',
    'brooklyn':        'Brooklyn (New York, N.Y.)',
    'bronx':           'Bronx (New York, N.Y.)',
    'queens':          'Queens (New York, N.Y.)',
    'staten island':   'Staten Island (New York, N.Y.)',
    'albany':          'Albany (N.Y.)',
    'syracuse':        'Syracuse (N.Y.)',
    'rochester':       'Rochester (N.Y.)',
    'buffalo':         'Buffalo (N.Y.)',
    'ithaca':          'Ithaca (N.Y.)',
    'schenectady':     'Schenectady (N.Y.)',
    'troy':            'Troy (N.Y.)',
    'binghamton':      'Binghamton (N.Y.)',
    'oswego':          'Oswego (N.Y.)',
    'poughkeepsie':    'Poughkeepsie (N.Y.)',
    'yonkers':         'Yonkers (N.Y.)',
    'white plains':    'White Plains (N.Y.)',
    'hempstead':       'Hempstead (N.Y.)',
    'long island':     'Long Island (N.Y.)',
    'new york state':  'New York (State)',
    'state of new york':'New York (State)',
    'westchester':     'Westchester County (N.Y.)',
    'adirondacks':     'Adirondack Mountains (N.Y.)',
    'catskills':       'Catskill Mountains (N.Y.)',

    # ── Northeast / New England ───────────────────────────────────────────────
    'boston':          'Boston (Mass.)',
    'cambridge':       'Cambridge (Mass.)',
    'new haven':       'New Haven (Conn.)',
    'hartford':        'Hartford (Conn.)',
    'new haven':       'New Haven (Conn.)',
    'new london':      'New London (Conn.)',
    'middletown':      'Middletown (Conn.)',
    'middlebury':      'Middlebury (Vt.)',
    'burlington':      'Burlington (Vt.)',
    'hanover':         'Hanover (N.H.)',
    'concord':         'Concord (N.H.)',
    'providence':      'Providence (R.I.)',
    'portland':        'Portland (Me.)',
    'brunswick':       'Brunswick (Me.)',
    'bangor':          'Bangor (Me.)',
    'newport':         'Newport (R.I.)',
    'springfield':     'Springfield (Mass.)',
    'worcester':       'Worcester (Mass.)',
    'lowell':          'Lowell (Mass.)',
    'amherst':         'Amherst (Mass.)',
    'northampton':     'Northampton (Mass.)',
    'williamstown':    'Williamstown (Mass.)',

    # ── Mid-Atlantic ──────────────────────────────────────────────────────────
    'philadelphia':    'Philadelphia (Pa.)',
    'pittsburgh':      'Pittsburgh (Pa.)',
    'harrisburg':      'Harrisburg (Pa.)',
    'allentown':       'Allentown (Pa.)',
    'scranton':        'Scranton (Pa.)',
    'reading':         'Reading (Pa.)',
    'princeton':       'Princeton (N.J.)',
    'newark':          'Newark (N.J.)',
    'jersey city':     'Jersey City (N.J.)',
    'trenton':         'Trenton (N.J.)',
    'new brunswick':   'New Brunswick (N.J.)',
    'hoboken':         'Hoboken (N.J.)',
    'baltimore':       'Baltimore (Md.)',
    'annapolis':       'Annapolis (Md.)',
    'washington':      'Washington (D.C.)',
    'washington d.c.': 'Washington (D.C.)',
    'washington dc':   'Washington (D.C.)',
    'district of columbia': 'Washington (D.C.)',
    'wilmington':      'Wilmington (Del.)',
    'dover':           'Dover (Del.)',

    # ── South ─────────────────────────────────────────────────────────────────
    'richmond':        'Richmond (Va.)',
    'norfolk':         'Norfolk (Va.)',
    'charlottesville': 'Charlottesville (Va.)',
    'raleigh':         'Raleigh (N.C.)',
    'charlotte':       'Charlotte (N.C.)',
    'chapel hill':     'Chapel Hill (N.C.)',
    'durham':          'Durham (N.C.)',
    'charleston':      'Charleston (S.C.)',
    'columbia':        'Columbia (S.C.)',
    'atlanta':         'Atlanta (Ga.)',
    'savannah':        'Savannah (Ga.)',
    'athens':          'Athens (Ga.)',
    'memphis':         'Memphis (Tenn.)',
    'nashville':       'Nashville (Tenn.)',
    'knoxville':       'Knoxville (Tenn.)',
    'new orleans':     'New Orleans (La.)',
    'baton rouge':     'Baton Rouge (La.)',
    'birmingham':      'Birmingham (Ala.)',
    'montgomery':      'Montgomery (Ala.)',
    'jackson':         'Jackson (Miss.)',
    'miami':           'Miami (Fla.)',
    'orlando':         'Orlando (Fla.)',
    'tampa':           'Tampa (Fla.)',
    'jacksonville':    'Jacksonville (Fla.)',
    'tallahassee':     'Tallahassee (Fla.)',

    # ── Midwest ───────────────────────────────────────────────────────────────
    'chicago':         'Chicago (Ill.)',
    'springfield':     'Springfield (Ill.)',
    'detroit':         'Detroit (Mich.)',
    'ann arbor':       'Ann Arbor (Mich.)',
    'grand rapids':    'Grand Rapids (Mich.)',
    'cleveland':       'Cleveland (Ohio)',
    'columbus':        'Columbus (Ohio)',
    'cincinnati':      'Cincinnati (Ohio)',
    'toledo':          'Toledo (Ohio)',
    'akron':           'Akron (Ohio)',
    'dayton':          'Dayton (Ohio)',
    'oberlin':         'Oberlin (Ohio)',
    'indianapolis':    'Indianapolis (Ind.)',
    'south bend':      'South Bend (Ind.)',
    'milwaukee':       'Milwaukee (Wis.)',
    'madison':         'Madison (Wis.)',
    'minneapolis':     'Minneapolis (Minn.)',
    'saint paul':      'Saint Paul (Minn.)',
    'st. paul':        'Saint Paul (Minn.)',
    'st paul':         'Saint Paul (Minn.)',
    'st. louis':       'Saint Louis (Mo.)',
    'saint louis':     'Saint Louis (Mo.)',
    'st louis':        'Saint Louis (Mo.)',
    'kansas city':     'Kansas City (Mo.)',
    'des moines':      'Des Moines (Iowa)',
    'iowa city':       'Iowa City (Iowa)',
    'omaha':           'Omaha (Neb.)',
    'lincoln':         'Lincoln (Neb.)',
    'fargo':           'Fargo (N.D.)',
    'sioux falls':     'Sioux Falls (S.D.)',

    # ── West ──────────────────────────────────────────────────────────────────
    'denver':          'Denver (Colo.)',
    'boulder':         'Boulder (Colo.)',
    'salt lake city':  'Salt Lake City (Utah)',
    'phoenix':         'Phoenix (Ariz.)',
    'tucson':          'Tucson (Ariz.)',
    'los angeles':     'Los Angeles (Calif.)',
    'san francisco':   'San Francisco (Calif.)',
    'berkeley':        'Berkeley (Calif.)',
    'palo alto':       'Palo Alto (Calif.)',
    'pasadena':        'Pasadena (Calif.)',
    'san diego':       'San Diego (Calif.)',
    'sacramento':      'Sacramento (Calif.)',
    'portland':        'Portland (Or.)',
    'seattle':         'Seattle (Wash.)',
    'spokane':         'Spokane (Wash.)',
    'boise':           'Boise (Idaho)',
    'las vegas':       'Las Vegas (Nev.)',
    'reno':            'Reno (Nev.)',
    'albuquerque':     'Albuquerque (N.M.)',
    'santa fe':        'Santa Fe (N.M.)',
    'honolulu':        'Honolulu (Hawaii)',
    'anchorage':       'Anchorage (Alaska)',

    # ── US states (when mentioned as regions) ────────────────────────────────
    'new york state':         'New York (State)',
    'california':             'California',
    'texas':                  'Texas',
    'florida':                'Florida',
    'ohio':                   'Ohio',
    'illinois':               'Illinois',
    'pennsylvania':           'Pennsylvania',
    'massachusetts':          'Massachusetts',
    'new jersey':             'New Jersey',
    'virginia':               'Virginia',
    'michigan':               'Michigan',
    'georgia':                'Georgia',
    'north carolina':         'North Carolina',
    'washington state':       'Washington (State)',
    'new england':            'New England',

    # ── International ─────────────────────────────────────────────────────────
    'london':          'London (England)',
    'oxford':          'Oxford (England)',
    'cambridge':       'Cambridge (England)',
    'edinburgh':       'Edinburgh (Scotland)',
    'dublin':          'Dublin (Ireland)',
    'paris':           'Paris (France)',
    'berlin':          'Berlin (Germany)',
    'munich':          'Munich (Germany)',
    'rome':            'Rome (Italy)',
    'milan':           'Milan (Italy)',
    'florence':        'Florence (Italy)',
    'venice':          'Venice (Italy)',
    'madrid':          'Madrid (Spain)',
    'barcelona':       'Barcelona (Spain)',
    'lisbon':          'Lisbon (Portugal)',
    'amsterdam':       'Amsterdam (Netherlands)',
    'brussels':        'Brussels (Belgium)',
    'vienna':          'Vienna (Austria)',
    'zurich':          'Zürich (Switzerland)',
    'geneva':          'Geneva (Switzerland)',
    'stockholm':       'Stockholm (Sweden)',
    'oslo':            'Oslo (Norway)',
    'copenhagen':      'Copenhagen (Denmark)',
    'helsinki':        'Helsinki (Finland)',
    'warsaw':          'Warsaw (Poland)',
    'prague':          'Prague (Czech Republic)',
    'budapest':        'Budapest (Hungary)',
    'athens':          'Athens (Greece)',
    'istanbul':        'İstanbul (Turkey)',
    'moscow':          'Moscow (Russia)',
    'leningrad':       'Saint Petersburg (Russia)',
    'st. petersburg':  'Saint Petersburg (Russia)',
    'beijing':         'Beijing (China)',
    'peking':          'Beijing (China)',
    'shanghai':        'Shanghai (China)',
    'tokyo':           'Tokyo (Japan)',
    'osaka':           'Osaka (Japan)',
    'seoul':           'Seoul (Korea)',
    'hong kong':       'Hong Kong (China)',
    'delhi':           'Delhi (India)',
    'new delhi':       'New Delhi (India)',
    'bombay':          'Mumbai (India)',
    'mumbai':          'Mumbai (India)',
    'calcutta':        'Kolkata (India)',
    'cairo':           'Cairo (Egypt)',
    'jerusalem':       'Jerusalem',
    'tel aviv':        'Tel Aviv-Yafo (Israel)',
    'beirut':          'Beirut (Lebanon)',
    'baghdad':         'Baghdad (Iraq)',
    'tehran':          'Tehran (Iran)',
    'riyadh':          'Riyadh (Saudi Arabia)',
    'johannesburg':    'Johannesburg (South Africa)',
    'cape town':       'Cape Town (South Africa)',
    'nairobi':         'Nairobi (Kenya)',
    'sydney':          'Sydney (N.S.W.)',
    'melbourne':       'Melbourne (Vic.)',
    'toronto':         'Toronto (Ont.)',
    'montreal':        'Montréal (Québec)',
    'ottawa':          'Ottawa (Ont.)',
    'vancouver':       'Vancouver (B.C.)',
    'mexico city':     'Mexico City (Mexico)',

    # ── Regional / broader geographic terms ───────────────────────────────────
    'europe':          'Europe',
    'asia':            'Asia',
    'africa':          'Africa',
    'middle east':     'Middle East',
    'far east':        'East Asia',
    'soviet union':    'Soviet Union',
    'ussr':            'Soviet Union',
    'united states':   'United States',
    'u.s.':            'United States',
    'us':              'United States',
    'america':         'United States',
    'great britain':   'Great Britain',
    'united kingdom':  'Great Britain',
    'uk':              'Great Britain',
    'france':          'France',
    'germany':         'Germany',
    'west germany':    'Germany (West)',
    'east germany':    'Germany (East)',
    'italy':           'Italy',
    'spain':           'Spain',
    'russia':          'Russia (Federation)',
    'china':           'China',
    'japan':           'Japan',
    'india':           'India',
    'korea':           'Korea',
    'south korea':     'Korea (South)',
    'north korea':     'Korea (North)',
    'vietnam':         'Vietnam',
    'north vietnam':   'Vietnam (North)',
    'south vietnam':   'Vietnam (South)',
    'israel':          'Israel',
    'canada':          'Canada',
    'australia':       'Australia',
    'new zealand':     'New Zealand',
    'mexico':          'Mexico',
    'cuba':            'Cuba',
    'brazil':          'Brazil',
    'argentina':       'Argentina',
}


# ── Helper functions ───────────────────────────────────────────────────────────

def filename_to_date(filename: str) -> str | None:
    """Extract ISO date (YYYY-MM-DD) from 'spec-YYYY-MM-DD_djvu.txt'."""
    m = re.search(r'spec-(\d{4}-\d{2}-\d{2})', filename)
    return m.group(1) if m else None


def normalize_entity(text: str) -> str:
    """Collapse internal whitespace, strip outer whitespace and leading/trailing
    punctuation artefacts common in OCR output (e.g. '-John Smith')."""
    text = re.sub(r'\s+', ' ', text).strip()
    text = LEADING_PUNCT_RE.sub('', text)
    text = TRAILING_PUNCT_RE.sub('', text)
    return text.strip()


def is_garbled(text: str) -> bool:
    """
    Return True if the entity text looks like OCR garbage:
      - All-caps (likely a headline token or acronym run-on)
      - Contains no alphabetic characters
      - Very short (1 character)
    """
    t = text.strip()
    if len(t) <= 1:
        return True
    if NOISE_RE.match(t):
        return True
    # Allow short all-caps if they look like genuine acronyms (2–4 chars like "FBI", "SCA")
    # but reject long all-caps runs that are likely headline OCR artifacts
    if re.match(r'^[A-Z\s\.\-]{5,}$', t):
        return True
    return False


def lcsh_place(raw: str) -> str:
    """
    Return the LCSH-standardized form of a place name.
    Falls back to the normalized extracted form if not in the lookup table.
    """
    key = normalize_entity(raw).lower()
    return LCSH_PLACES.get(key, normalize_entity(raw))


def first_token_title(tokens: list[str]) -> str | None:
    """
    Return the lower-case title if the first token is a recognized title,
    else None.  Handles trailing periods (e.g., 'Dr.' → 'dr').
    """
    if not tokens:
        return None
    t = tokens[0].rstrip('.').lower()
    if t in ALL_TITLES:
        return t
    return None


def looks_like_name_token(token: str) -> bool:
    """A token looks like a name if it starts with an uppercase letter and
    contains only letters, hyphens, or apostrophes."""
    return bool(re.match(r"^[A-Z][A-Za-z\'\-]+$", token))


def all_tokens_valid_name(tokens: list[str], skip_first_if_title: bool = False) -> bool:
    """
    Return True if every token in *tokens* is either a proper name token,
    a recognized name connector (de, van, von …), or an empty string.
    Set skip_first_if_title=True when the first token has already been
    confirmed as a title and should be skipped.
    """
    start = 1 if skip_first_if_title else 0
    for tok in tokens[start:]:
        t = tok.rstrip('.,;:')
        if not t:
            continue
        if t.lower() in NAME_CONNECTORS:
            continue
        if not looks_like_name_token(t):
            return False
    return True


def classify_person_entity(text: str):
    """
    Classify a raw PERSON entity string.

    Returns:
        ('keep_full',   normalized_name)  — first+last or professional title+last
        ('keep_if_rec', last_name)         — courtesy title+last, needs reconciliation
        ('drop',        None)
    """
    text = normalize_entity(text)
    if not text:
        return ('drop', None)
    tokens = text.split()

    if len(tokens) < 2:
        return ('drop', None)
    # Hard cap: names longer than 5 tokens are usually sentence fragments
    if len(tokens) > 5:
        return ('drop', None)
    if is_garbled(text):
        return ('drop', None)
    # Blocklist check (case-insensitive)
    if text.lower() in PERSON_BLOCKLIST:
        return ('drop', None)

    title = first_token_title(tokens)

    if title in PROFESSIONAL_TITLES:
        # Professional title + at least a last name → keep as-is
        rest = tokens[1:]
        if rest and any(looks_like_name_token(t.rstrip('.,;:')) for t in rest):
            # All remaining tokens must also look like name tokens
            if all_tokens_valid_name(tokens, skip_first_if_title=True):
                return ('keep_full', text)
        return ('drop', None)

    if title in COURTESY_TITLES:
        # Courtesy title — need within-document reconciliation
        rest = tokens[1:]
        if rest and all_tokens_valid_name(tokens, skip_first_if_title=True):
            last = rest[-1].rstrip('.,;:')
            if looks_like_name_token(last):
                return ('keep_if_rec', last)
        return ('drop', None)

    # No title prefix — ALL tokens must look like proper name tokens
    # (this catches "Alpha Delt crushed Squires" since "crushed" fails)
    if not all_tokens_valid_name(tokens):
        return ('drop', None)
    # Require at least 2 proper name tokens
    name_tokens = [t for t in tokens if looks_like_name_token(t.rstrip('.,;:'))]
    if len(name_tokens) >= 2:
        return ('keep_full', text)

    return ('drop', None)


# ── Per-file NER processing ────────────────────────────────────────────────────

def process_file(filepath: Path, nlp) -> dict:
    """
    Run NER on a single file.  Returns a dict with keys:
        'people'  → set of accepted person name strings
        'orgs'    → set of org/event name strings
        'places'  → set of place name strings (pre-LCSH)
    """
    text = filepath.read_text(encoding='utf-8', errors='replace')
    doc  = nlp(text)

    # Collect raw entities by type
    raw_people_full  = set()   # definitely keep
    raw_people_maybe = {}      # last_name → courtesy-title form, need reconciliation
    raw_orgs         = set()
    raw_places       = set()

    for ent in doc.ents:
        raw = normalize_entity(ent.text)
        if not raw or is_garbled(raw):
            continue

        label = ent.label_

        # ── People ───────────────────────────────────────────────────────────
        if label == 'PERSON':
            kind, value = classify_person_entity(raw)
            if kind == 'keep_full':
                raw_people_full.add(value)
            elif kind == 'keep_if_rec':
                # Store last_name → courtesy form (e.g., 'Williams' → 'Mr. Williams')
                # We'll resolve against full names after scanning the whole document
                if value not in raw_people_maybe:
                    raw_people_maybe[value] = raw   # raw = "Mr. Williams" etc.

        # ── Organizations & events ───────────────────────────────────────────
        elif label in ('ORG', 'EVENT'):
            # Must start with an alphabetic character (filters "& Company", "'61 News")
            if not raw or not raw[0].isalpha():
                continue
            # Must contain at least one word of ≥3 letters starting with uppercase
            words_upper = re.findall(r'[A-Z][A-Za-z]{2,}', raw)
            if not words_upper:
                continue
            # Reject pure OCR noise: no digit-heavy strings, no pipe characters
            if '|' in raw or re.search(r'\d{3,}', raw):
                continue
            raw_orgs.add(raw)

        # ── Places ───────────────────────────────────────────────────────────
        elif label in ('GPE', 'LOC'):
            words = re.findall(r'[A-Za-z]+', raw)
            if any(len(w) >= 3 for w in words):
                raw_places.add(raw)

    # Within-document reconciliation for courtesy titles.
    # Build a map: last_name (lower) → canonical full name from raw_people_full
    last_to_full: dict[str, list[str]] = defaultdict(list)
    for full_name in raw_people_full:
        parts = full_name.split()
        # Skip if first token is a title (e.g., "Dean Tolles")
        if first_token_title(parts) is None:
            last = parts[-1].rstrip('.,;:').lower()
            last_to_full[last].append(full_name)

    # Reconcile: if a single unambiguous full name matches the last name,
    # use the full name form (don't add a separate "Mr. Williams" entry).
    for last_name_lower, courtesy_form in raw_people_maybe.items():
        matches = last_to_full.get(last_name_lower, [])
        if len(matches) == 1:
            # Unambiguous — the full name is already in raw_people_full, done.
            # (We intentionally do NOT add the courtesy form as a separate entry.)
            pass
        elif len(matches) == 0:
            # Not found elsewhere in file → drop per user rules.
            pass
        # len > 1: ambiguous → drop.

    return {
        'people': raw_people_full,
        'orgs':   raw_orgs,
        'places': raw_places,
    }


# ── Entity accumulator ────────────────────────────────────────────────────────

class EntityStore:
    """
    Accumulates entity occurrences across the whole corpus.
    For each entity, tracks the earliest date, latest date, and set of filenames.
    """

    def __init__(self):
        # name → {'earliest': str, 'latest': str, 'files': set}
        self.people: dict[str, dict] = {}
        self.orgs:   dict[str, dict] = {}
        self.places: dict[str, dict] = {}

    def _add(self, store: dict, name: str, date: str, filename: str):
        if name not in store:
            store[name] = {'earliest': date, 'latest': date, 'files': set()}
        rec = store[name]
        if date and (rec['earliest'] is None or date < rec['earliest']):
            rec['earliest'] = date
        if date and (rec['latest'] is None or date > rec['latest']):
            rec['latest'] = date
        rec['files'].add(filename)

    def add_person(self, name, date, filename):
        self._add(self.people, name, date, filename)

    def add_org(self, name, date, filename):
        self._add(self.orgs, name, date, filename)

    def add_place(self, raw_name, date, filename):
        # Standardize to LCSH before storing
        std = lcsh_place(raw_name)
        self._add(self.places, std, date, filename)

    def to_rows(self, store: dict) -> list[list]:
        """Convert a store dict to sorted CSV rows."""
        rows = []
        for name, rec in sorted(store.items(), key=lambda x: x[0].lower()):
            files_sorted = sorted(rec['files'])
            rows.append([
                name,
                rec['earliest'] or '',
                rec['latest'] or '',
                ';'.join(files_sorted),
            ])
        return rows


# ── Main batch loop ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Extract named entities from cleaned OCR newspaper files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--input',  '-i', required=True,
                        help='Directory of cleaned .txt files')
    parser.add_argument('--output', '-o', required=True,
                        help='Directory to write CSV output files')
    args = parser.parse_args()

    input_dir  = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    txt_files = sorted(input_dir.glob('*.txt'))
    # Exclude the log file if it snuck in
    txt_files = [f for f in txt_files if '_djvu.txt' in f.name or f.name.startswith('spec-')]
    total = len(txt_files)
    if total == 0:
        print(f'No .txt files found in {input_dir}', file=sys.stderr)
        sys.exit(1)

    print(f'Loading spaCy model…', flush=True)
    # Use the small model for speed; disable unneeded pipeline components.
    # en_core_web_sm is ~3x faster than lg with comparable NER on news text.
    nlp = spacy.load('en_core_web_sm', disable=['parser', 'attribute_ruler', 'lemmatizer'])
    nlp.max_length = 2_000_000

    store = EntityStore()

    print(f'Processing {total} files with nlp.pipe()…', flush=True)

    # Read all texts up-front so nlp.pipe() can batch efficiently
    file_texts  = []
    file_metas  = []    # (filename, date)
    for fp in txt_files:
        try:
            text = fp.read_text(encoding='utf-8', errors='replace')
            file_texts.append(text)
            file_metas.append((fp.name, filename_to_date(fp.name)))
        except Exception as exc:
            print(f'  ERROR reading {fp.name}: {exc}', file=sys.stderr)
            file_texts.append('')
            file_metas.append((fp.name, None))

    # Process in a single pass with nlp.pipe(), using all available CPU cores.
    # n_process=-1 uses os.cpu_count(); batch_size controls chunk size per worker.
    import os
    n_proc = min(4, os.cpu_count() or 1)
    for i, (doc, (filename, date)) in enumerate(
            zip(nlp.pipe(file_texts, batch_size=6, n_process=n_proc), file_metas), 1):

        # Re-use entity extraction logic inline (avoid re-reading the file)
        raw_people_full  = set()
        raw_people_maybe = {}
        raw_orgs         = set()
        raw_places       = set()

        for ent in doc.ents:
            raw = normalize_entity(ent.text)
            if not raw or is_garbled(raw):
                continue
            label = ent.label_

            if label == 'PERSON':
                kind, value = classify_person_entity(raw)
                if kind == 'keep_full':
                    raw_people_full.add(value)
                elif kind == 'keep_if_rec':
                    if value not in raw_people_maybe:
                        raw_people_maybe[value] = raw

            elif label in ('ORG', 'EVENT'):
                if not raw or not raw[0].isalpha():
                    continue
                words_upper = re.findall(r'[A-Z][A-Za-z]{2,}', raw)
                if not words_upper:
                    continue
                if '|' in raw or re.search(r'\d{3,}', raw):
                    continue
                raw_orgs.add(raw)

            elif label in ('GPE', 'LOC'):
                words = re.findall(r'[A-Za-z]+', raw)
                if any(len(w) >= 3 for w in words):
                    raw_places.add(raw)

        # Within-doc reconciliation for courtesy titles
        last_to_full: dict[str, list] = defaultdict(list)
        for full_name in raw_people_full:
            parts = full_name.split()
            if first_token_title(parts) is None:
                last = parts[-1].rstrip('.,;:').lower()
                last_to_full[last].append(full_name)
        # (Courtesy-title forms are intentionally not added as separate entries)

        for name in raw_people_full:
            store.add_person(name, date, filename)
        for name in raw_orgs:
            store.add_org(name, date, filename)
        for name in raw_places:
            store.add_place(name, date, filename)

        if i % 100 == 0 or i == total:
            print(f'  [{i:4d}/{total}]  '
                  f'people:{len(store.people):,}  '
                  f'orgs:{len(store.orgs):,}  '
                  f'places:{len(store.places):,}',
                  flush=True)

    # ── Write CSV files ───────────────────────────────────────────────────────
    HEADER = ['name', 'earliest_date', 'latest_date', 'files']

    for label, store_dict, filename in [
        ('people',      store.people, 'entities_people.csv'),
        ('orgs_events', store.orgs,   'entities_orgs_events.csv'),
        ('places',      store.places, 'entities_places.csv'),
    ]:
        out_path = output_dir / filename
        rows = store.to_rows(store_dict)
        with out_path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(HEADER)
            writer.writerows(rows)
        print(f'  → {out_path.name}  ({len(rows):,} entities)')

    print('Done.')


if __name__ == '__main__':
    main()