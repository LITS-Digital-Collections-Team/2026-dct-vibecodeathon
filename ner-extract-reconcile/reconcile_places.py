#!/usr/bin/env python3
"""
reconcile_places.py — Filter, standardise (LCSH or LCNAF), and deduplicate entities_places.csv.

Three main operations, applied in sequence:

1. GEOGRAPHIC VALIDITY FILTER
   spaCy's GPE/LOC tagger is broad: it captures genuine place names but also
   picks up direction words, abstract nouns, Latin phrases, and OCR garbage.
   This step applies a multi-tier test to each entry:

     Tier 1 – LCSH whitelist:  name (normalised) is in the LCSH_TABLE → keep,
              use the standardised LCSH form directly.
     Tier 2 – Structural pass: starts with a capital letter, contains only
              plausible name-like tokens, does not appear in the
              NON_GEOGRAPHIC_TERMS blocklist → keep if it also appears in ≥2
              source files (single-file unknown entries are almost all noise).
     Tier 3 – Drop: all-lowercase, leading article (a/an/the), contains an
              OCR digit, in NON_GEOGRAPHIC_TERMS, or single-file with no LCSH
              match.

   Entries moved here from the people pipeline ("[moved from people — review
   LCSH form]") are treated as campus facilities: the annotation is stripped,
   the entry is kept, and the name is flagged for manual LCSH review.

2. LCSH STANDARDISATION
   Applies the LCSH_TABLE to convert raw place-name variants to the standard
   Library of Congress Subject Headings form:
     US cities  →  "City (State.)"  e.g. "Albany (N.Y.)"
     US states  →  standard state name  e.g. "New York (State)"
     Countries  →  standard country name  e.g. "Soviet Union"
     Regions    →  standard region name  e.g. "New England"

   Entries with no LCSH match are kept in their best-available form (title
   case, leading article stripped) and flagged with lcsh_status="unresolved"
   in the output for manual review.

3. DEDUPLICATION
   OCR produces many spelling variants of the same place name.  This step:
     a) Groups names into phonetic blocks (first_initial + Soundex of the
        first substantive token — same strategy as reconcile_people.py).
     b) Within each block, checks prefix matches (always merge) then applies
        token-sort-ratio fuzzy matching.
     c) Adds a temporal-proximity gate (same as people): pairs scoring between
        TEMPORAL_THRESHOLD and FUZZY_THRESHOLD that also appear in near-adjacent
        date windows are merged, subject to a last-token surname guard.
     d) Selects the canonical form by preferring:
          i.   Entries already in LCSH/LCNAF form
          ii.  Most source files
          iii. Best title-case quality

Outputs:
  entities_places_clean.csv      — all kept entries combined (verified + unverified + campus)
  entities_places_verified.csv   — LCSH/LCNAF heading confirmed; ready for indexing
  entities_places_unverified.csv — passed geographic filter but no LCSH/LCNAF match yet;
                                   review and add to LCSH_TABLE or PRIORITY_OVERRIDES to promote
  entities_places_campus.csv     — Hamilton College campus facilities (moved from people);
                                   needs manual LCSH or local-name authority review
  places_filtered_out.csv        — dropped entries with drop_reason; for audit
  places_reconciliation_report.tsv — every merge decision with reason
  entities_places_lcnaf.csv      — (if --lcnaf-data provided) clean rows + lcnaf_form column

Usage:
  python3 reconcile_places.py \\
      --places  entities_places_augmented.csv \\
      --outdir  /path/to/output/dir

  Optional:
    --min-files N        Drop unknown entries appearing in fewer than N files
                         (default: 2).  Set to 1 to keep all single-file entries.
    --regional-list FILE Load a list of pre-validated place names (one LCNAF/LCSH heading
                         per line; # = comment, blank lines ignored) to use as a regional
                         authority during geographic filtering. Names in this list are treated
                         as verified, rescue single-file entries that would otherwise be
                         dropped, and are preferred over the full LCNAF index when
                         disambiguating. Intended for a geographically bounded place list
                         (e.g. places within 300 miles of the corpus's home institution).
                         (optional)
    --lcnaf-data DIR     Run LCNAF authority lookup after main pipeline. Load or build
                         the geographic index (lcnaf_geo_index.json from this dir, or build
                         from names.skosrdf.jsonld if present). Adds lcnaf_form column to
                         entities_places_lcnaf.csv. (optional)
    --campus-list FILE   Load normalised campus location names (one per line; # = comment,
                         blank lines ignored) and use them to classify places during
                         geographic filtering. (optional)

Requirements: Python 3.8+, rapidfuzz
  pip install rapidfuzz --break-system-packages
"""

import re
import csv
import sys
import json
import time
import argparse
from datetime import date
from pathlib import Path
from collections import defaultdict

from rapidfuzz import fuzz

# ── Tunable parameters ─────────────────────────────────────────────────────────
FUZZY_THRESHOLD     = 88   # minimum token-sort-ratio to merge two place names
OCR_DIGIT_THRESHOLD = 80   # lower threshold when a name contains a digit
TEMPORAL_THRESHOLD  = 78   # lower threshold when date ranges are also close
LCSH_FUZZY_THRESHOLD = 85  # minimum fuzz.ratio to rescue a low-frequency entry
                            # via fuzzy match against LCSH_TABLE keys.
                            # At 85 a single-character OCR error in a 7-char name
                            # scores ≈ 85.7 ("Clintqn" → "clinton").
                            # Lower = more rescues, more risk of wrong mapping.
                            # Known edge cases at this threshold (all single-file):
                            #   "Milton"    → Hamilton (N.Y.)  [could be a place name]
                            #   "Frome"     → Rome (N.Y.)      [Frome is an English town]
                            #   "Birkeland" → Ireland          [Norwegian surname/place]
                            #   "Sprague"   → Prague           [could be a surname]
                            # Raise to 88+ to eliminate these; doing so also loses the
                            # 1-char Clinton variants ("Clintqn" etc.) at exactly 85.7.
DATE_PROXIMITY_DAYS = 365  # ±1 year: how close date ranges must be
MAX_BLOCK_SIZE      = 150  # skip pairwise comparison in very large blocks
MIN_FILES_UNKNOWN   = 2    # entries not in LCSH_TABLE need ≥ this many files

# ── LCSH place-name lookup table ───────────────────────────────────────────────
# Keys: lower-case, no punctuation variants of the raw place name.
# Values: canonical LCSH heading.
#
# US city format:   "City (State.)"    where State. is the LCSH state abbrev.
# US state format:  state name, with "(State)" appended only where needed to
#                   disambiguate from a city of the same name (New York, Washington).
# Country format:   standard LCSH country name (no parenthetical qualifier).
# Region format:    standard LCSH region heading.
#
# LCSH state abbreviations used here:
#   Ala. Ariz. Ark. Calif. Colo. Conn. Del. Fla. Ga. Idaho Ill. Ind.
#   Iowa Kans. Ky. La. Me. Md. Mass. Mich. Minn. Miss. Mo. Mont.
#   Neb. Nev. N.H. N.J. N.M. N.Y. N.C. N.D. Ohio Okla. Ore. Pa.
#   R.I. S.C. S.D. Tenn. Tex. Utah Vt. Va. Wash. W.Va. Wis. Wyo.
#   D.C.
#
# Adding entries here is the recommended way to improve LCSH coverage.
LCSH_TABLE: dict[str, str] = {

    # ── Central New York (most frequent in a Hamilton College newspaper) ────────
    'clinton':              'Clinton (N.Y.)',
    'clinton ny':           'Clinton (N.Y.)',
    'utica':                'Utica (N.Y.)',
    'utica ny':             'Utica (N.Y.)',
    'rome':                 'Rome (N.Y.)',
    'rome ny':              'Rome (N.Y.)',
    'rome n y':             'Rome (N.Y.)',
    'new hartford':         'New Hartford (N.Y.)',
    'new hartford ny':      'New Hartford (N.Y.)',
    'oneida':               'Oneida (N.Y.)',
    'oneida county':        'Oneida County (N.Y.)',
    'herkimer':             'Herkimer (N.Y.)',
    'herkimer county':      'Herkimer County (N.Y.)',
    'hamilton':             'Hamilton (N.Y.)',    # NB: disambiguates from Hamilton College
    'hamilton ny':          'Hamilton (N.Y.)',
    'colgate':              'Hamilton (N.Y.)',    # Colgate University is in Hamilton, N.Y.

    # ── Upstate New York ────────────────────────────────────────────────────────
    'albany':               'Albany (N.Y.)',
    'albany ny':            'Albany (N.Y.)',
    'albany n y':           'Albany (N.Y.)',
    'syracuse':             'Syracuse (N.Y.)',
    'syracuse ny':          'Syracuse (N.Y.)',
    'rochester':            'Rochester (N.Y.)',
    'rochester ny':         'Rochester (N.Y.)',
    'buffalo':              'Buffalo (N.Y.)',
    'buffalo ny':           'Buffalo (N.Y.)',
    'ithaca':               'Ithaca (N.Y.)',
    'ithaca ny':            'Ithaca (N.Y.)',
    'binghamton':           'Binghamton (N.Y.)',
    'binghamton ny':        'Binghamton (N.Y.)',
    'schenectady':          'Schenectady (N.Y.)',
    'troy':                 'Troy (N.Y.)',
    'troy ny':              'Troy (N.Y.)',
    'saratoga':             'Saratoga Springs (N.Y.)',
    'saratoga springs':     'Saratoga Springs (N.Y.)',
    'plattsburgh':          'Plattsburgh (N.Y.)',
    'watertown':            'Watertown (N.Y.)',
    'oswego':               'Oswego (N.Y.)',
    'cortland':             'Cortland (N.Y.)',
    'hamilton college':     'Clinton (N.Y.)',   # campus address is Clinton

    # ── New York City / Metro ───────────────────────────────────────────────────
    'new york':             'New York (N.Y.)',
    'new york city':        'New York (N.Y.)',
    'nyc':                  'New York (N.Y.)',
    'new york n y':         'New York (N.Y.)',
    'new york ny':          'New York (N.Y.)',
    'manhattan':            'Manhattan (New York, N.Y.)',
    'brooklyn':             'Brooklyn (New York, N.Y.)',
    'bronx':                'Bronx (New York, N.Y.)',
    'queens':               'Queens (New York, N.Y.)',
    'harlem':               'Harlem (New York, N.Y.)',
    'long island':          'Long Island (N.Y.)',
    'westchester':          'Westchester County (N.Y.)',
    'westchester county':   'Westchester County (N.Y.)',

    # ── New York State ──────────────────────────────────────────────────────────
    'new york state':       'New York (State)',
    'state of new york':    'New York (State)',
    'upstate new york':     'New York (State)',
    'upstate':              'New York (State)',   # in context nearly always upstate NY

    # ── New England colleges and cities ────────────────────────────────────────
    'amherst':              'Amherst (Mass.)',
    'amherst mass':         'Amherst (Mass.)',
    'middlebury':           'Middlebury (Vt.)',
    'middlebury vt':        'Middlebury (Vt.)',
    'hanover':              'Hanover (N.H.)',     # Dartmouth
    'hanover nh':           'Hanover (N.H.)',
    'brunswick':            'Brunswick (Me.)',    # Bowdoin
    'waterville':           'Waterville (Me.)',   # Colby
    'williamstown':         'Williamstown (Mass.)', # Williams
    'northampton':          'Northampton (Mass.)', # Smith
    'south hadley':         'South Hadley (Mass.)', # Mount Holyoke
    'hartford':             'Hartford (Conn.)',
    'hartford conn':        'Hartford (Conn.)',
    'new haven':            'New Haven (Conn.)',
    'new haven conn':       'New Haven (Conn.)',
    'providence':           'Providence (R.I.)',
    'cambridge':            'Cambridge (Mass.)',
    'cambridge mass':       'Cambridge (Mass.)',
    'boston':               'Boston (Mass.)',
    'boston mass':          'Boston (Mass.)',

    # ── Mid-Atlantic ────────────────────────────────────────────────────────────
    'princeton':            'Princeton (N.J.)',
    'princeton nj':         'Princeton (N.J.)',
    'new jersey':           'New Jersey',
    'philadelphia':         'Philadelphia (Pa.)',
    'philadelphia pa':      'Philadelphia (Pa.)',
    'pittsburgh':           'Pittsburgh (Pa.)',
    'pittsburgh pa':        'Pittsburgh (Pa.)',
    'baltimore':            'Baltimore (Md.)',
    'baltimore md':         'Baltimore (Md.)',
    'annapolis':            'Annapolis (Md.)',
    'washington':           'Washington (D.C.)',
    'washington dc':        'Washington (D.C.)',
    'washington d c':       'Washington (D.C.)',
    'washington d.c':       'Washington (D.C.)',
    'district of columbia': 'Washington (D.C.)',

    # ── US States ───────────────────────────────────────────────────────────────
    'alabama':          'Alabama',
    'alaska':           'Alaska',
    'arizona':          'Arizona',
    'arkansas':         'Arkansas',
    'california':       'California',
    'colorado':         'Colorado',
    'connecticut':      'Connecticut',
    'delaware':         'Delaware',
    'florida':          'Florida',
    'georgia':          'Georgia',
    'hawaii':           'Hawaii',
    'idaho':            'Idaho',
    'illinois':         'Illinois',
    'indiana':          'Indiana',
    'iowa':             'Iowa',
    'kansas':           'Kansas',
    'kentucky':         'Kentucky',
    'louisiana':        'Louisiana',
    'maine':            'Maine',
    'maryland':         'Maryland',
    'massachusetts':    'Massachusetts',
    'mass':             'Massachusetts',
    'mass.':            'Massachusetts',
    'michigan':         'Michigan',
    'minnesota':        'Minnesota',
    'mississippi':      'Mississippi',
    'missouri':         'Missouri',
    'montana':          'Montana',
    'nebraska':         'Nebraska',
    'nevada':           'Nevada',
    'new hampshire':    'New Hampshire',
    'new mexico':       'New Mexico',
    'north carolina':   'North Carolina',
    'north dakota':     'North Dakota',
    'ohio':             'Ohio',
    'oklahoma':         'Oklahoma',
    'oregon':           'Oregon',
    'pennsylvania':     'Pennsylvania',
    'rhode island':     'Rhode Island',
    'south carolina':   'South Carolina',
    'south dakota':     'South Dakota',
    'tennessee':        'Tennessee',
    'texas':            'Texas',
    'utah':             'Utah',
    'vermont':          'Vermont',
    'virginia':         'Virginia',
    'west virginia':    'West Virginia',
    'washington state': 'Washington (State)',
    'wisconsin':        'Wisconsin',
    'wyoming':          'Wyoming',

    # ── Other major US cities ───────────────────────────────────────────────────
    'chicago':              'Chicago (Ill.)',
    'chicago ill':          'Chicago (Ill.)',
    'detroit':              'Detroit (Mich.)',
    'cleveland':            'Cleveland (Ohio)',
    'cleveland ohio':       'Cleveland (Ohio)',
    'cincinnati':           'Cincinnati (Ohio)',
    'columbus':             'Columbus (Ohio)',
    'minneapolis':          'Minneapolis (Minn.)',
    'st paul':              'Saint Paul (Minn.)',
    'saint paul':           'Saint Paul (Minn.)',
    'saint louis':          'Saint Louis (Mo.)',
    'st louis':             'Saint Louis (Mo.)',
    'kansas city':          'Kansas City (Mo.)',
    'denver':               'Denver (Colo.)',
    'atlanta':              'Atlanta (Ga.)',
    'miami':                'Miami (Fla.)',
    'new orleans':          'New Orleans (La.)',
    'nashville':            'Nashville (Tenn.)',
    'los angeles':          'Los Angeles (Calif.)',
    'san francisco':        'San Francisco (Calif.)',
    'san francisco calif':  'San Francisco (Calif.)',
    'berkeley':             'Berkeley (Calif.)',
    'palo alto':            'Palo Alto (Calif.)',
    'seattle':              'Seattle (Wash.)',
    'portland':             'Portland (Or.)',

    # ── US regions ──────────────────────────────────────────────────────────────
    # NOTE: bare direction words ('south', 'north', 'east', 'west') are
    # intentionally NOT mapped here.  They appear frequently as ambiguous
    # single-token OCR extractions and their LCSH form depends on context.
    # They are kept with lcsh_status='unresolved' for manual review.
    # Only unambiguous multi-word region names are mapped.
    'new england':          'New England',
    'mid atlantic':         'Middle Atlantic States',
    'middle atlantic':      'Middle Atlantic States',
    'the south':            'Southern States',
    'deep south':           'Southern States',
    'the north':            'Northern States',
    'midwest':              'Middle West (U.S.)',
    'middle west':          'Middle West (U.S.)',
    'the west':             'West (U.S.)',
    'far west':             'West (U.S.)',
    'pacific northwest':    'Northwest, Pacific',
    'appalachia':           'Appalachian Region',
    'appalachian':          'Appalachian Region',

    # ── Canada ──────────────────────────────────────────────────────────────────
    'canada':           'Canada',
    'montreal':         'Montréal (Québec)',
    'toronto':          'Toronto (Ont.)',
    'ottawa':           'Ottawa (Ont.)',
    'ontario':          'Ontario',
    'quebec':           'Québec (Province)',
    'british columbia': 'British Columbia',

    # ── Latin America ───────────────────────────────────────────────────────────
    'mexico':           'Mexico',
    'cuba':             'Cuba',
    'havana':           'Havana (Cuba)',
    'puerto rico':      'Puerto Rico',
    'brazil':           'Brazil',
    'argentina':        'Argentina',
    'chile':            'Chile',
    'colombia':         'Colombia',
    'latin america':    'Latin America',
    'central america':  'Central America',
    'south america':    'South America',

    # ── Western Europe ──────────────────────────────────────────────────────────
    'england':          'England',
    'great britain':    'Great Britain',
    'britain':          'Great Britain',
    'united kingdom':   'Great Britain',
    'uk':               'Great Britain',
    'london':           'London (England)',
    'london england':   'London (England)',
    'oxford':           'Oxford (England)',
    'cambridge england':'Cambridge (England)',
    'ireland':          'Ireland',
    'scotland':         'Scotland',
    'wales':            'Wales',
    'france':           'France',
    'paris':            'Paris (France)',
    'paris france':     'Paris (France)',
    'germany':          'Germany',
    'west germany':     'Germany (West)',
    'east germany':     'Germany (East)',
    'berlin':           'Berlin (Germany)',
    'berlin germany':   'Berlin (Germany)',
    'east berlin':      'Berlin (Germany)',
    'west berlin':      'Berlin (Germany)',
    'bonn':             'Bonn (Germany)',
    'italy':            'Italy',
    'rome italy':       'Rome (Italy)',
    'venice':           'Venice (Italy)',
    'florence':         'Florence (Italy)',
    'milan':            'Milan (Italy)',
    'spain':            'Spain',
    'madrid':           'Madrid (Spain)',
    'barcelona':        'Barcelona (Spain)',
    'portugal':         'Portugal',
    'netherlands':      'Netherlands',
    'holland':          'Netherlands',
    'amsterdam':        'Amsterdam (Netherlands)',
    'belgium':          'Belgium',
    'brussels':         'Brussels (Belgium)',
    'switzerland':      'Switzerland',
    'geneva':           'Geneva (Switzerland)',
    'zurich':           'Zürich (Switzerland)',
    'austria':          'Austria',
    'vienna':           'Vienna (Austria)',
    'sweden':           'Sweden',
    'norway':           'Norway',
    'denmark':          'Denmark',
    'finland':          'Finland',
    'greece':           'Greece',
    'athens':           'Athens (Greece)',
    'turkey':           'Turkey',
    'europe':           'Europe',

    # ── Eastern Europe / Soviet sphere ─────────────────────────────────────────
    'russia':           'Russia (Federation)',
    'soviet union':     'Soviet Union',
    'ussr':             'Soviet Union',
    'u s s r':          'Soviet Union',
    'moscow':           'Moscow (Russia)',
    'leningrad':        'Saint Petersburg (Russia)',
    'czechoslovakia':   'Czechoslovakia',
    'prague':           'Prague (Czech Republic)',
    'hungary':          'Hungary',
    'poland':           'Poland',
    'warsaw':           'Warsaw (Poland)',
    'yugoslavia':       'Yugoslavia',
    'romania':          'Romania',
    'bulgaria':         'Bulgaria',
    'east europe':      'Europe, Eastern',
    'eastern europe':   'Europe, Eastern',

    # ── Middle East / Africa / Asia ─────────────────────────────────────────────
    'israel':           'Israel',
    'jerusalem':        'Jerusalem',
    'tel aviv':         'Tel Aviv-Yafo (Israel)',
    'egypt':            'Egypt',
    'cairo':            'Cairo (Egypt)',
    'iran':             'Iran',
    'iraq':             'Iraq',
    'middle east':      'Middle East',
    'africa':           'Africa',
    'south africa':     'South Africa',
    'nigeria':          'Nigeria',
    'ghana':            'Ghana',
    'kenya':            'Kenya',
    'india':            'India',
    'china':            'China',
    'beijing':          'Beijing (China)',
    'peking':           'Beijing (China)',
    'shanghai':         'Shanghai (China)',
    'japan':            'Japan',
    'tokyo':            'Tokyo (Japan)',
    'korea':            'Korea',
    'north korea':      'Korea (North)',
    'south korea':      'Korea (South)',
    'vietnam':          'Vietnam',
    'north vietnam':    'Vietnam (Democratic Republic)',
    'south vietnam':    'Vietnam (Republic)',
    'saigon':           'Ho Chi Minh City (Vietnam)',
    'hanoi':            'Hanoi (Vietnam)',
    'southeast asia':   'Asia, Southeastern',
    'asia':             'Asia',

    # ── Country-level ───────────────────────────────────────────────────────────
    'united states':    'United States',
    'united states of america': 'United States',
    'america':          'United States',
    'u s':              'United States',
    'u. s':             'United States',
    'u.s':              'United States',
    'the united states':'United States',
    'us':               'United States',
    'australia':        'Australia',
    'new zealand':      'New Zealand',

    # ── Abbreviation forms commonly seen in OCR output ─────────────────────────
    'n y':              'New York (N.Y.)',
    'n.y':              'New York (N.Y.)',
    'n.y.':             'New York (N.Y.)',  # bare state abbrev → city in this corpus
    'd c':              'Washington (D.C.)',
    'd.c':              'Washington (D.C.)',
    'u s a':            'United States',
    'u.s.a':            'United States',
}

# ── Non-geographic terms blocklist ─────────────────────────────────────────────
# Single words or short phrases that spaCy tags as GPE/LOC but are not
# geographic locations in this corpus.  All lower-case.
NON_GEOGRAPHIC_TERMS: set[str] = {
    # Latin phrases appearing in academic / newspaper copy
    'absentia', 'alma', 'mater', 'alma mater', 'cum laude', 'magna cum laude',
    'summa cum laude', 'in absentia',
    # Common English words mis-tagged as places
    'abroad', 'abroad.', 'home', 'here', 'there', 'elsewhere',
    'abroad', 'local', 'national', 'regional', 'international',
    'absurd', 'abstract', 'abilities', 'ability', 'absence', 'absent',
    'abode', 'abash', 'abyss',
    # Directions without geographic referent (bare compass points)
    # NOTE: "the South", "the Middle East", "Eastern Europe" ARE kept —
    # only bare single-word forms with no geographic specificity are blocked.
    # These are handled by the multi-file minimum threshold instead.
    # Academic / institutional terms
    'campus', 'library', 'chapel',    # "Chapel" alone → too ambiguous; multi-word forms kept
    'commons', 'dormitory', 'dorm',
    'classroom', 'lecture hall', 'auditorium',
    # Miscellaneous OCR / section-label noise
    'arts', 'news', 'sports', 'features', 'editorial', 'opinion',
    'section', 'page', 'column', 'issue',
    'street',  'avenue', 'road', 'lane', 'drive',  # bare street-type words
    'building', 'hall',                              # bare building-type words
    'county',  'state', 'city', 'town', 'village',  # bare geo-type words
    'nation', 'world', 'globe', 'universe',
    # Short noise tokens
    'a', 'an', 'the', 'in', 'at', 'of', 'on', 'to', 'by',
}

# ── OCR digit → letter substitution (same as reconcile_people.py) ──────────────
OCR_SUBS = str.maketrans({
    '0': 'o', '1': 'l', '2': 'z', '3': 'e', '4': 'a',
    '5': 's', '6': 'b', '7': 't', '8': 'e', '9': 'g',
})

HAS_DIGIT_RE   = re.compile(r'[0-9]')
LEADING_ART_RE = re.compile(r'^(a |an |the )', re.IGNORECASE)
MOVED_FROM_RE  = re.compile(r'\s*\[moved from people[^\]]*\]', re.IGNORECASE)
PAREN_QUAL_RE  = re.compile(r'\s*\([^)]+\)')   # strips "(N.Y.)" etc. for normalisation

# ── GAC notation type URI ──────────────────────────────────────────────────────
# This is the datatype that identifies a LCNAF record as a geographic name.
_GAC_TYPE = 'http://id.loc.gov/datatypes/codes/gac'

# ── Soundex (identical implementation to reconcile_people.py) ─────────────────
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
    """Lower-case, strip leading articles, apply digit substitutions."""
    name = LEADING_ART_RE.sub('', name).strip()
    name = name.lower().translate(OCR_SUBS)
    name = re.sub(r"[^a-z0-9\s'\.\-]", ' ', name)
    return re.sub(r'\s+', ' ', name).strip()


def comparison_normalise(name: str) -> str:
    """
    Full normalisation for blocking and fuzzy comparison (never stored).
    Strips leading articles, parenthetical LCNAF qualifiers, applies OCR
    digit substitutions, and lower-cases.
      "Albany (N.Y.)"       →  "albany"
      "the United States"   →  "united states"
      "Clintqn"             →  "clintqn"
    """
    name = PAREN_QUAL_RE.sub('', name)
    return ocr_normalise(name)


def block_key(comp_norm: str) -> str:
    """Blocking key = first_initial + Soundex(first_substantive_token)."""
    tokens = comp_norm.split()
    if not tokens:
        return 'X_0000'
    first_init = tokens[0][0].upper() if tokens[0] else 'X'
    return f'{first_init}_{soundex(tokens[0])}'


def has_ocr_digit(name: str) -> bool:
    return bool(HAS_DIGIT_RE.search(name))


# ── LCSH lookup (base implementation) ──────────────────────────────────────────

def _lcsh_key(name: str) -> str:
    """Normalise a place name to the key format used in LCSH_TABLE."""
    k = LEADING_ART_RE.sub('', name).strip()
    k = PAREN_QUAL_RE.sub('', k)
    k = re.sub(r'[^a-zA-Z0-9\s\.\-]', ' ', k)
    k = re.sub(r'\s+', ' ', k).strip().lower()
    # also try without trailing punctuation
    return k.rstrip('.')


def lcsh_lookup(name: str) -> str | None:
    """
    Try several normalisation variants of *name* against LCSH_TABLE.
    Returns the LCSH heading string if found, else None.
    """
    key = _lcsh_key(name)
    if key in LCSH_TABLE:
        return LCSH_TABLE[key]
    # Try without internal periods (e.g. "U.S.A" → "usa")
    key_nopunct = re.sub(r'\.', '', key).strip()
    if key_nopunct in LCSH_TABLE:
        return LCSH_TABLE[key_nopunct]
    # Try first token only (catches "Albany, N.Y." → "albany")
    first_tok = key.split()[0] if key.split() else ''
    if first_tok and first_tok in LCSH_TABLE:
        # Only use this if the first token dominates (1-2 token names)
        if len(key.split()) <= 2:
            return LCSH_TABLE[first_tok]
    return None


def lcsh_fuzzy_lookup(name: str,
                      threshold: int = LCSH_FUZZY_THRESHOLD) -> str | None:
    """
    Fuzzy fallback for lcsh_lookup(): when exact key matching fails, compare
    the comparison-normalised form of *name* against every key in LCSH_TABLE
    using character-level fuzz.ratio.  Returns the LCSH heading for the
    best-scoring key if it meets *threshold*, else None.

    Only applied to ≤ 2-token comparison norms: longer strings risk false
    positives because a short known key ("rome", "iran") can score high against
    unrelated multi-word phrases that happen to share characters.

    Performance note: LCSH_TABLE has ~200 keys, so this is O(200) ratio
    comparisons per call — fast enough even when called for every low-frequency
    entry in the corpus.
    """
    comp = comparison_normalise(name)
    if not comp or len(comp.split()) > 2:
        return None

    best_score, best_lcsh = 0, None
    for key, lcsh_form in LCSH_TABLE.items():
        score = fuzz.ratio(comp, key)
        if score > best_score:
            best_score, best_lcsh = score, lcsh_form

    return best_lcsh if best_score >= threshold else None


# ── LCNAF authority lookup (optional) ────────────────────────────────────────

# ── Corpus-specific priority overrides ────────────────────────────────────────
# Serves two distinct purposes:
#
# 1. DISAMBIGUATION: The LCNAF contains many places sharing the same bare name
#    (dozens of "Clinton"s, "Albany"s, "Utica"s, etc.).  For bare single-word
#    OCR tokens, LCNAF alone cannot determine which was meant — that requires
#    corpus context.  This table provides disambiguation for the Hamilton
#    College (Clinton, N.Y.) newspaper context.
#
# 2. LCSH-ONLY HEADINGS: Countries, U.S. states, and major cities are LCSH
#    Subject Headings, not LCNAF named authorities.  They carry no GAC notation
#    and therefore do not appear in the geographic index built from
#    names.skosrdf.jsonld.  Entries in this table for those places ensure they
#    still get a standardised heading rather than falling through to 'unresolved'
#    or — worse — matching an obscure altLabel in the LCNAF index.
#
# PRIORITY_OVERRIDES is consulted first (before any index lookup) and trusted
# unconditionally.  Qualified names like "Clinton (N.Y.)" resolve correctly via
# the full-key index even without an override, but bare names like "clinton" or
# "france" always need this table.
#
# Add entries as needed when reviewing the unresolved output file.
# The full LCSH heading form should be used as the value (e.g. "New York (State)"
# rather than "New York State").
PRIORITY_OVERRIDES: dict[str, str] = {
    # ── Central New York (Hamilton College context) ────────────────────────────
    'clinton':      'Clinton (N.Y.)',
    'utica':        'Utica (N.Y.)',
    'rome':         'Rome (N.Y.)',     # in this corpus, Rome = Rome N.Y. not Rome Italy
    'hamilton':     'Hamilton (N.Y.)',
    'oneida':       'Oneida (N.Y.)',
    'albany':       'Albany (N.Y.)',
    'rochester':    'Rochester (N.Y.)',
    'buffalo':      'Buffalo (N.Y.)',
    'ithaca':       'Ithaca (N.Y.)',
    'syracuse':     'Syracuse (N.Y.)',
    'binghamton':   'Binghamton (N.Y.)',
    'schenectady':  'Schenectady (N.Y.)',
    'troy':         'Troy (N.Y.)',
    # ── Northeast colleges & cities ───────────────────────────────────────────
    'amherst':      'Amherst (Mass.)',
    'middlebury':   'Middlebury (Vt.)',
    'princeton':    'Princeton (N.J.)',
    'cambridge':    'Cambridge (Mass.)',
    'hanover':      'Hanover (N.H.)',
    'boston':       'Boston (Mass.)',
    'philadelphia': 'Philadelphia (Pa.)',
    'chicago':      'Chicago (Ill.)',
    'washington':   'Washington (D.C.)',
    # ── Major world cities ────────────────────────────────────────────────────
    'paris':        'Paris (France)',
    'london':       'London (England)',
    'berlin':       'Berlin (Germany)',
    'moscow':       'Moscow (Russia)',
    'tokyo':        'Tokyo (Japan)',
    'geneva':       'Geneva (Switzerland)',
    # ── U.S. states not in LCNAF geo index ───────────────────────────────────
    # Many state names are LCSH subject headings, not LCNAF named authorities,
    # so they do not appear in the GAC-coded index built from names.skosrdf.jsonld.
    'new york':         'New York (N.Y.)',   # city; 'new york state' for state
    'new york state':   'New York (State)',
    'new jersey':       'New Jersey',
    'pennsylvania':     'Pennsylvania',
    'massachusetts':    'Massachusetts',
    'connecticut':      'Connecticut',
    'vermont':          'Vermont',
    'new hampshire':    'New Hampshire',
    'maine':            'Maine',
    'rhode island':     'Rhode Island',
    'maryland':         'Maryland',
    'virginia':         'Virginia',
    'north carolina':   'North Carolina',
    'south carolina':   'South Carolina',
    'georgia':          'Georgia',
    'florida':          'Florida',
    'ohio':             'Ohio',
    'michigan':         'Michigan',
    'indiana':          'Indiana',
    'illinois':         'Illinois',
    'wisconsin':        'Wisconsin',
    'minnesota':        'Minnesota',
    'iowa':             'Iowa',
    'missouri':         'Missouri',
    'california':       'California',
    'texas':            'Texas',
    # ── Countries not in LCNAF geo index ─────────────────────────────────────
    'england':          'England',
    'france':           'France',
    'germany':          'Germany',
    'united states':    'United States',
    'canada':           'Canada',
    'russia':           'Russia',
    'china':            'China',
    'japan':            'Japan',
    'italy':            'Italy',
    'spain':            'Spain',
    'ireland':          'Ireland',
    'scotland':         'Scotland',
    'wales':            'Wales',
    'australia':        'Australia',
    'india':            'India',
    'mexico':           'Mexico',
    'brazil':           'Brazil',
    'argentina':        'Argentina',
    'south africa':     'South Africa',
}


# ── Regional authority list (optional) ────────────────────────────────────────
# A pre-validated flat list of place names in LCNAF/LCSH heading form, e.g.
# "Clinton (N.Y.)", "Albany (N.Y.)", "Boston (Mass.)".  Loaded via
# --regional-list; intended for geographically bounded lists such as all named
# places within a fixed radius of the corpus's home institution.
#
# The same two-key normalisation strategy used by the LCNAF geo index is
# applied: a full key retains the parenthetical qualifier ("clinton n y") for
# unambiguous lookup; a bare key strips it ("clinton") and is only retained
# when it maps to exactly one authority form in the list.
#
# Priority order in classify_place():
#   LCSH_TABLE → regional_lookup() → lcnaf_lookup() → structural checks
# Regional is consulted before the full LCNAF index because it is smaller,
# geographically bounded, and therefore less likely to return a geographically
# irrelevant result for the same place name.


def load_regional_list(path: Path) -> dict:
    """
    Load a flat LCNAF/LCSH place-name list (one heading per line) and return
    a lookup dict with keys 'full' and 'bare'.

    'full'  maps _lcnaf_key_full(heading) → heading  (always unique)
    'bare'  maps _lcnaf_key_bare(heading) → heading  (only when unambiguous)

    Lines beginning with '#' and blank lines are ignored.
    """
    from collections import defaultdict

    full: dict[str, str]            = {}
    bare_candidates: dict[str, list] = defaultdict(list)

    with path.open(encoding='utf-8') as fh:
        for line in fh:
            heading = line.strip()
            if not heading or heading.startswith('#'):
                continue
            fk = _lcnaf_key_full(heading)
            if fk:
                full[fk] = heading
            bk = _lcnaf_key_bare(heading)
            if bk:
                bare_candidates[bk].append(heading)

    # Only include bare keys that resolve to a single authority form.
    bare: dict[str, str] = {}
    for bk, candidates in bare_candidates.items():
        unique = list(dict.fromkeys(candidates))
        if len(unique) == 1:
            bare[bk] = unique[0]

    print(f'Regional list: {len(full):,} full keys, {len(bare):,} unambiguous bare keys '
          f'from {path.name}.')
    return {'full': full, 'bare': bare}


def regional_lookup(name: str, regional: dict) -> str | None:
    """
    Look up *name* in the regional authority list.

    Uses the same two-key strategy as lcnaf_lookup():
      1. PRIORITY_OVERRIDES  — corpus-specific disambiguation (trusted unconditionally)
      2. Full key            — retains parenthetical qualifier; unambiguous
      3. Bare key            — strips qualifier; only when unambiguous in the list
    """
    bare = _lcnaf_key_bare(name)
    if bare in PRIORITY_OVERRIDES:
        return PRIORITY_OVERRIDES[bare]

    full_keys = regional.get('full', {})
    bare_keys = regional.get('bare', {})

    fk = _lcnaf_key_full(name)
    if fk in full_keys:
        return full_keys[fk]

    fk_nopunct = re.sub(r'\.', '', fk).strip()
    if fk_nopunct in full_keys:
        return full_keys[fk_nopunct]

    if bare in bare_keys:
        return bare_keys[bare]

    return None


# ── LCNAF geographic index ─────────────────────────────────────────────────────

def _extract_label_string(label_value) -> str | None:
    """
    LCNAF prefLabel / altLabel values are either a plain string or a dict:
      {"@language": "zxx-Latn", "@value": "Clinton, N.Y."}
    Return the string value in either case, or None if unparseable.
    """
    if isinstance(label_value, str):
        return label_value
    if isinstance(label_value, dict):
        return label_value.get('@value')
    return None


def _lcnaf_key_full(label: str) -> str:
    """
    Normalise a LCNAF label to an *unambiguous* lookup key by retaining the
    parenthetical geographic qualifier.  Used as the primary index key so that
    "Clinton (N.Y.)" and "Clinton (Wis.)" produce different keys and do not
    collide.

      "Clinton (N.Y.)"   →  "clinton n y"
      "Clinton (Wis.)"   →  "clinton wis"
      "Paris (France)"   →  "paris france"
    """
    k = LEADING_ART_RE.sub('', label).strip()
    # Normalise parenthetical qualifier: remove brackets but keep letters/digits
    k = re.sub(r'\(([^)]+)\)', lambda m: ' ' + m.group(1), k)
    k = re.sub(r'[^a-zA-Z0-9\s\-]', ' ', k)
    k = re.sub(r'\s+', ' ', k).strip().lower()
    return k.rstrip('.')


def _lcnaf_key_bare(label: str) -> str:
    """
    Normalise a place name by STRIPPING the parenthetical qualifier.  Used
    for bare-name lookups ("Albany", "Boston") and as the query key when the
    raw OCR entity has no qualifier.

      "Albany (N.Y.)"  →  "albany"
      "Albany, N.Y."   →  "albany n y"   (no parens, so comma+abbrev remain)
      "Albany"         →  "albany"
    """
    k = LEADING_ART_RE.sub('', label).strip()
    k = PAREN_QUAL_RE.sub('', k)
    k = re.sub(r'[^a-zA-Z0-9\s\-]', ' ', k)
    k = re.sub(r'\s+', ' ', k).strip().lower()
    return k.rstrip('.')


def build_geo_index(jsonld_path: Path, index_path: Path) -> dict:
    """
    Stream through the LCNAF JSONLD file and extract all geographic entries
    (those with a GAC notation), building a lookup index.

    The file is ~18 GB with one JSON object per line.  Rather than parsing
    every line, we first check for the literal string '"gac"' before calling
    json.loads() — this fast-path cuts processing time by ~99 %.

    The returned (and saved) index has the structure:
      {
        "keys": {
          "<full_key>": "<LCNAF_prefLabel>",   # qualifier retained: "clinton n y"
          ...
        },
        "bare_keys": {
          "<bare_key>": "<LCNAF_prefLabel>",   # only unambiguous bare names
          ...
        },
        "prefix": {
          "<3-char-prefix>": ["<full_key1>", ...],
          ...
        },
        "bare_prefix": {
          "<3-char-prefix>": ["<bare_key1>", ...],
          ...
        }
      }

    "keys" maps every normalised full variant (prefLabel AND altLabels, with
    qualifier letters retained) to the canonical LCNAF prefLabel.  Because
    qualifiers are preserved, "Clinton (N.Y.)" and "Clinton (Wis.)" produce
    different keys and do not collide.

    "bare_keys" maps bare (qualifier-stripped) names to a prefLabel, but ONLY
    for names where the LCNAF has exactly one candidate (unambiguous).  Bare
    names with multiple candidates (e.g. "clinton" → dozens of Clintons) are
    omitted; those are handled by PRIORITY_OVERRIDES in lcnaf_lookup().

    "prefix" and "bare_prefix" group keys by their first three characters so
    that lcnaf_fuzzy_lookup() can quickly find close candidates without
    scanning all keys.
    """
    t0 = time.time()
    keys: dict[str, str] = {}                          # full_key → prefLabel
    bare_candidates: dict[str, list] = defaultdict(list)  # bare_key → [prefLabel, …]
    geo_count = 0
    parsed_count = 0

    print(f'Building LCNAF geographic index from {jsonld_path.name} …')
    print('(This runs once; the result is cached for future runs.)')

    with jsonld_path.open(encoding='utf-8', errors='replace') as f:
        for lineno, line in enumerate(f, 1):
            if lineno % 1_000_000 == 0:
                elapsed = time.time() - t0
                print(f'  {lineno/1e6:.1f}M lines read, '
                      f'{geo_count:,} geographic entries so far '
                      f'({elapsed:.0f}s) …')

            # Fast-path: skip lines that cannot be geographic entries.
            # The GAC datatype is serialised as the full URI
            # "http://id.loc.gov/datatypes/codes/gac" — check for the
            # distinctive path segment to avoid parsing irrelevant lines.
            if 'codes/gac' not in line:
                continue

            parsed_count += 1
            try:
                obj = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            # Each line's @graph is a list; find the main concept node
            for node in obj.get('@graph', []):
                node_id = node.get('@id', '')
                if not node_id.startswith('http://id.loc.gov/authorities/names/'):
                    continue

                # Check for GAC notation (confirms this is a geographic entry)
                notation = node.get('skos:notation', {})
                if not (isinstance(notation, dict)
                        and notation.get('@type') == _GAC_TYPE):
                    continue

                # Extract the preferred label
                pref_raw = node.get('skos:prefLabel')
                pref = _extract_label_string(pref_raw)
                if not pref:
                    continue

                geo_count += 1

                # Index the prefLabel itself (full key = unambiguous)
                pref_key = _lcnaf_key_full(pref)
                if pref_key:
                    keys[pref_key] = pref
                # Track bare key for later ambiguity analysis — PREFABELS ONLY.
                # We deliberately do NOT add bare keys from altLabels here.
                # Adding altLabel bare keys causes harmful collisions: e.g.
                # "Clinton Junction (Wis.)" has an altLabel "New York (Wis.)",
                # whose bare key "new york" would then point to "Clinton (Wis.)"
                # in bare_keys, causing "New York (N.Y.)" to mislabel.
                bare_k = _lcnaf_key_bare(pref)
                if bare_k:
                    bare_candidates[bare_k].append(pref)

                # Index all altLabels as additional FULL-KEY lookup variants
                # (useful when a raw entity already has a qualifier, e.g.
                # "Clinton, N.Y." → altLabel full key → "Clinton (N.Y.)").
                alts = node.get('skos:altLabel', [])
                if isinstance(alts, str):
                    alts = [alts]
                for alt_raw in alts:
                    alt = _extract_label_string(alt_raw)
                    if alt:
                        alt_key = _lcnaf_key_full(alt)
                        if alt_key and alt_key not in keys:
                            keys[alt_key] = pref   # variant → canonical

    elapsed = time.time() - t0
    print(f'Parsed {parsed_count:,} lines with "codes/gac"; '
          f'found {geo_count:,} geographic entries; '
          f'{len(keys):,} full-key index entries in {elapsed:.1f}s.')

    # Build unambiguous bare_keys: only kept when a bare name maps to exactly
    # one prefLabel (so "clinton" → ["Clinton (N.Y.)", "Clinton (Wis.)", …]
    # is dropped; "boston" → ["Boston (Mass.)"] is kept).
    bare_keys: dict[str, str] = {}
    ambiguous_count = 0
    for bare_k, candidates in bare_candidates.items():
        unique = list(dict.fromkeys(candidates))  # deduplicate, preserve order
        if len(unique) == 1:
            bare_keys[bare_k] = unique[0]
        else:
            ambiguous_count += 1
    print(f'{len(bare_keys):,} unambiguous bare keys; '
          f'{ambiguous_count:,} ambiguous bare keys (handled via PRIORITY_OVERRIDES).')

    # Build 3-character prefix indexes for efficient fuzzy lookup
    prefix: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        prefix[k[:3]].append(k)

    bare_prefix: dict[str, list[str]] = defaultdict(list)
    for k in bare_keys:
        bare_prefix[k[:3]].append(k)

    index = {
        'keys':        keys,
        'bare_keys':   bare_keys,
        'prefix':      dict(prefix),
        'bare_prefix': dict(bare_prefix),
    }

    # Save to disk
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8',
    )
    print(f'Index saved to {index_path.name} '
          f'({index_path.stat().st_size / 1e6:.1f} MB).')
    return index


def load_geo_index(jsonld_path: Path, index_path: Path,
                   rebuild: bool = False) -> dict:
    """
    Load the LCNAF geographic index from *index_path* if it exists (and
    --rebuild-index was not requested), otherwise build it from *jsonld_path*.
    """
    if not rebuild and index_path.exists():
        print(f'Loading cached LCNAF index from {index_path.name} …', end=' ')
        t0 = time.time()
        index = json.loads(index_path.read_text(encoding='utf-8'))
        # Detect old index format (pre-two-key strategy): rebuild automatically.
        if 'bare_keys' not in index:
            print()
            print('Cached index is in old format (missing bare_keys). '
                  'Rebuilding …')
            return build_geo_index(jsonld_path, index_path)
        print(f'{len(index["keys"]):,} full keys, '
              f'{len(index["bare_keys"]):,} bare keys loaded in '
              f'{time.time()-t0:.1f}s.')
        return index

    if not jsonld_path.exists():
        print(f'ERROR: LCNAF file not found: {jsonld_path}', file=sys.stderr)
        print('Pass --lcnaf-data <path> to specify its location.', file=sys.stderr)
        sys.exit(1)

    return build_geo_index(jsonld_path, index_path)


def lcnaf_lookup(name: str, index: dict) -> str | None:
    """
    Exact lookup of *name* in the LCNAF index.

    Resolution order:
      1. PRIORITY_OVERRIDES — corpus-specific disambiguation for bare names
         (e.g. 'clinton' → 'Clinton (N.Y.)').  Checked by bare key so that
         qualified inputs like 'Clinton (N.Y.)' still pass through cleanly.
      2. Full-key lookup — _lcnaf_key_full() retains parenthetical qualifiers,
         so 'Clinton (N.Y.)' and 'Clinton (Wis.)' resolve to different entries.
      3. Full-key without internal periods — 'N.Y.' → 'NY' variant.
      4. Bare-key lookup — only used when the LCNAF index has exactly one
         prefLabel for that bare name (unambiguous single-candidate keys).
      5. First-token fallback for ≤ 2-token names (catches 'Albany, NY' etc.).
    """
    keys      = index['keys']
    bare_keys = index.get('bare_keys', {})

    # 1. Corpus-specific priority override — trusted unconditionally.
    #    PRIORITY_OVERRIDES provides corpus-specific disambiguation for bare
    #    names that are either ambiguous in LCNAF (many "Clinton"s) or absent
    #    from the LCNAF geographic index entirely (countries, US states, and
    #    major cities are LCSH subject headings, not LCNAF named authorities).
    bare = _lcnaf_key_bare(name)
    if bare in PRIORITY_OVERRIDES:
        return PRIORITY_OVERRIDES[bare]

    # 2. Full-key lookup (qualified, unambiguous)
    full = _lcnaf_key_full(name)
    if full in keys:
        return keys[full]

    # 3. Full-key without internal periods ('Clinton (N.Y.)' → 'clinton n y'
    #    but also handles e.g. 'U.S.' → 'US' in the qualifier portion)
    full_nopunct = re.sub(r'\.', '', full).strip()
    if full_nopunct in keys:
        return keys[full_nopunct]

    # 4. Bare-key lookup — only when unambiguous in the prefLabel-only index.
    #    (altLabel bare keys are excluded from bare_keys to prevent collisions
    #    like altLabel "New York (Wis.)" poisoning bare key "new york".)
    if bare in bare_keys:
        return bare_keys[bare]

    # NOTE: No first-token fallback.  It is too aggressive — bare single words
    # like "st", "old", "winter", "gotham" are all LCNAF place names, so a
    # first-token match would return wrong headings for multi-word phrases like
    # "St. Clinton", "Old Clinton", "Winter Carnival", "Gotham City", etc.

    return None


def lcnaf_fuzzy_lookup(name: str, index: dict,
                       threshold: int = LCSH_FUZZY_THRESHOLD) -> str | None:
    """
    Fuzzy lookup of *name* against the LCNAF index when exact lookup fails.

    Only applied to ≤ 2-token comparison norms (to avoid false positives from
    short known keys matching unrelated multi-word phrases).

    Candidates are drawn from the *bare_keys* index (qualifiers stripped) so
    that character-level similarity between e.g. 'clintqn' and 'clinton' is
    not diluted by the qualifier characters ' n y'.  This keeps the effective
    score for a one-character OCR error at ≈ 85–92 % rather than ≈ 63–70 %.

    After finding the best bare-key match we resolve the prefLabel via:
      1. PRIORITY_OVERRIDES (corpus-specific disambiguation)
      2. bare_keys (only stored when unambiguous)

    Efficiency: candidates are gathered from the bare_prefix 3-char bucket
    plus adjacent first-character OCR substitution buckets, keeping each
    search to typically 50–500 comparisons instead of 200 000+.
    """
    comp = comparison_normalise(name)
    if not comp or len(comp.split()) > 2:
        return None

    bare_keys   = index.get('bare_keys', {})
    bare_prefix = index.get('bare_prefix', {})

    # Gather bare-key candidates from the 3-char prefix bucket
    pfx = comp[:3]
    candidates = list(bare_prefix.get(pfx, []))

    # Also check prefix buckets for the query with its first char substituted
    # by common OCR confusion pairs so that a garbled first letter
    # (e.g. "Glinton" for "Clinton") still finds the right block.
    if len(comp) >= 3:
        for sub in ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'l',
                    'm', 'n', 'o', 'p', 'r', 's', 't', 'u', 'v', 'w'):
            alt_pfx = sub + comp[1:3]
            if alt_pfx != pfx:
                candidates.extend(bare_prefix.get(alt_pfx, []))

    if not candidates:
        return None

    best_score, best_key = 0, None
    for k in candidates:
        s = fuzz.ratio(comp, k)
        if s > best_score:
            best_score, best_key = s, k

    if best_score < threshold or best_key is None:
        return None

    # Resolve the bare key to a prefLabel
    if best_key in PRIORITY_OVERRIDES:
        pref = PRIORITY_OVERRIDES[best_key]
        if _lcnaf_key_full(pref) in index['keys']:
            return pref
    if best_key in bare_keys:
        return bare_keys[best_key]
    return None


# ── Temporal proximity helper ──────────────────────────────────────────────────

def dates_are_close(ri: dict, rj: dict,
                    max_days: int = DATE_PROXIMITY_DAYS) -> bool:
    """Return True if the publication date ranges of two rows are within
    max_days of each other (or overlap)."""
    def parse_row_dates(row):
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
        return False

    i_min, i_max = min(di), max(di)
    j_min, j_max = min(dj), max(dj)
    if i_min <= j_max and j_min <= i_max:
        return True
    gap = min(abs((i_min - j_max).days), abs((j_min - i_max).days))
    return gap <= max_days


# ── Canonical form scoring ─────────────────────────────────────────────────────

def _token_case_score(token: str) -> int:
    """
    Score a single name token by capitalisation quality.
      +2  Title-case (standard or DiName)
      +1  Short token ≤2 chars
       0  Mixed internal caps beyond 2 (OCR noise)
      -1  All-lowercase
      -2  All-uppercase >2 chars (OCR artefact)
    """
    t = re.sub(r"[^A-Za-z]", '', token)
    if not t:
        return 0
    if len(t) <= 2:
        return 1
    if t.isupper():
        return -2
    if t[0].islower():
        return -1
    internal_upper = sum(1 for c in t[1:] if c.isupper())
    return 2 if internal_upper <= 2 else 0


def canonical_score(row: dict) -> tuple:
    """
    Higher score = better canonical candidate.  Priorities:
      1. LCSH-standardised form (lcsh_status == 'matched')
      2. No OCR digit artefacts
      3. Number of source files
      4. Capitalisation quality
    """
    name       = row['name']
    is_lcsh    = 1 if row.get('lcsh_status') == 'matched' else 0
    file_count = len(row['files'].split(';'))
    no_digit   = 0 if has_ocr_digit(name) else 1
    case_score = sum(_token_case_score(t) for t in name.split())
    return (is_lcsh, no_digit, file_count, case_score)


# ── Geographic validity filter ─────────────────────────────────────────────────

def classify_place(name: str, file_count: int,
                   min_files: int = MIN_FILES_UNKNOWN,
                   lcnaf_index: dict | None = None,
                   campus_list: frozenset[str] | None = None,
                   regional: dict | None = None) -> tuple[str, str, str]:
    """
    Classify a raw place-name entry.

    Returns:
        (decision, lcsh_form, lcsh_status)

        decision:    'keep' | 'drop' | 'campus'
        lcsh_form:   LCSH/LCNAF heading if found, else best cleaned form
        lcsh_status: 'matched' | 'unresolved' | 'campus'
    """
    # ── Handle moved-from-people (campus facilities) ──────────────────────────
    if MOVED_FROM_RE.search(name):
        clean = MOVED_FROM_RE.sub('', name).strip()
        return ('campus', clean, 'campus')

    # ── Check against campus list (if provided) ───────────────────────────────
    if campus_list:
        normed_name = name.lower().strip()
        # Remove punctuation for comparison
        normed_name = re.sub(r'[^a-z0-9\s]', '', normed_name)
        if normed_name in campus_list:
            return ('campus', name, 'campus')

    # ── Basic structural filters ──────────────────────────────────────────────
    stripped = LEADING_ART_RE.sub('', name).strip()

    # Entirely lowercase and no LCSH match → almost certainly noise
    if stripped == stripped.lower() and not stripped[0].isdigit():
        # Check LCSH before dropping — "mass." etc. are lowercase but valid
        lcsh = lcsh_lookup(stripped)
        if lcsh:
            return ('keep', lcsh, 'matched')
        return ('drop', stripped, 'noise_lowercase')

    # Blocklist check (case-insensitive)
    if stripped.lower() in NON_GEOGRAPHIC_TERMS:
        return ('drop', stripped, 'noise_blocklist')

    # ── LCSH whitelist (Tier 1) ───────────────────────────────────────────────
    lcsh = lcsh_lookup(name)
    if lcsh:
        return ('keep', lcsh, 'matched')

    # ── Regional authority list (Tier 2) ─────────────────────────────────────
    # Checked before the full LCNAF index because it is geographically bounded
    # to the likely region of the corpus, making its matches more precise.
    # A hit here also rescues single-file entries that would otherwise fall to
    # noise_low_freq, because a name confirmed by the regional list is very
    # unlikely to be OCR noise.
    if regional:
        reg = regional_lookup(name, regional)
        if reg:
            return ('keep', reg, 'matched')

    # ── Try LCNAF lookup if index provided (Tier 3) ────────────────────────────
    if lcnaf_index:
        lcnaf = lcnaf_lookup(name, lcnaf_index)
        if lcnaf:
            return ('keep', lcnaf, 'matched')

    # ── Structural checks for unknown entries (Tier 4) ────────────────────────
    # Must start with a capital letter
    if not stripped[0].isupper():
        return ('drop', stripped, 'noise_no_capital')

    # Must not be purely OCR digit garbage
    if has_ocr_digit(stripped) and file_count < min_files:
        # Still try fuzzy LCSH before dropping
        lcsh = lcsh_fuzzy_lookup(stripped)
        if lcsh:
            return ('keep', lcsh, 'matched')
        # Try fuzzy regional before dropping
        if regional:
            reg = regional_lookup(stripped, regional)
            if reg:
                return ('keep', reg, 'matched')
        # Try fuzzy LCNAF if index provided
        if lcnaf_index:
            lcnaf = lcnaf_fuzzy_lookup(stripped, lcnaf_index)
            if lcnaf:
                return ('keep', lcnaf, 'matched')
        return ('drop', stripped, 'noise_ocr_digit')

    # Single-token all-caps (e.g. "ARTS", "NEWS") → section labels
    tokens = stripped.split()
    if len(tokens) == 1 and stripped.isupper() and len(stripped) > 2:
        return ('drop', stripped, 'noise_allcaps')

    # Unknown entries must appear in ≥ min_files files.
    # Exception: if a fuzzy LCSH or regional match exists, rescue even
    # single-file entries — they are almost certainly OCR variants of a known
    # place name.
    if file_count < min_files:
        lcsh = lcsh_fuzzy_lookup(stripped)
        if lcsh:
            return ('keep', lcsh, 'matched')
        if regional:
            reg = regional_lookup(stripped, regional)
            if reg:
                return ('keep', reg, 'matched')
        if lcnaf_index:
            lcnaf = lcnaf_fuzzy_lookup(stripped, lcnaf_index)
            if lcnaf:
                return ('keep', lcnaf, 'matched')
        return ('drop', stripped, 'noise_low_freq')

    # Passed all filters: keep with unresolved LCSH status
    best_form = stripped
    return ('keep', best_form, 'unresolved')


# ── Union-Find ────────────────────────────────────────────────────────────────

class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank   = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
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
        for field in ('earliest_date', 'latest_date'):
            if r.get(field):
                all_dates.append(r[field])
    all_dates = [d for d in all_dates if d]
    return {
        'name':          canonical_row['name'],
        'lcsh_status':   canonical_row.get('lcsh_status', 'unresolved'),
        'earliest_date': min(all_dates) if all_dates else '',
        'latest_date':   max(all_dates) if all_dates else '',
        'files':         ';'.join(sorted(all_files)),
    }


# ── Main pipeline ──────────────────────────────────────────────────────────────

def reconcile(places_path: Path, outdir: Path, min_files: int = MIN_FILES_UNKNOWN,
              lcnaf_data_dir: Path | None = None,
              campus_list: frozenset[str] | None = None,
              regional: dict | None = None):
    outdir.mkdir(parents=True, exist_ok=True)

    # ── Load LCNAF index if requested ──────────────────────────────────────────
    lcnaf_index = None
    if lcnaf_data_dir:
        lcnaf_data_dir = lcnaf_data_dir.expanduser().resolve()
        index_path = lcnaf_data_dir / 'lcnaf_geo_index.json'
        jsonld_path = lcnaf_data_dir / 'names.skosrdf.jsonld'
        lcnaf_index = load_geo_index(jsonld_path, index_path, rebuild=False)

    # ── 1. Load ───────────────────────────────────────────────────────────────
    raw_rows = list(csv.DictReader(places_path.open(encoding='utf-8')))
    print(f'Loaded {len(raw_rows):,} place rows.')

    # ── 2. Geographic validity filter + LCSH normalisation ───────────────────
    keep_rows:    list[dict] = []
    campus_rows:  list[dict] = []
    dropped_rows: list[dict] = []

    for row in raw_rows:
        fc = len(row['files'].split(';'))
        decision, lcsh_form, lcsh_status = classify_place(
            row['name'], fc, min_files,
            lcnaf_index=lcnaf_index,
            campus_list=campus_list,
            regional=regional,
        )

        normed = {
            'name':          lcsh_form,
            'lcsh_status':   lcsh_status,
            'earliest_date': row.get('earliest_date', ''),
            'latest_date':   row.get('latest_date', ''),
            'files':         row['files'],
        }

        if decision == 'keep':
            keep_rows.append(normed)
        elif decision == 'campus':
            campus_rows.append(normed)
        else:
            dropped_rows.append({**normed, 'drop_reason': lcsh_status,
                                  'original_name': row['name']})

    print(f'Geographic filter: {len(keep_rows):,} kept, '
          f'{len(campus_rows):,} campus facilities, '
          f'{len(dropped_rows):,} dropped.')

    lcsh_matched   = sum(1 for r in keep_rows if r['lcsh_status'] == 'matched')
    lcsh_unresolved = sum(1 for r in keep_rows if r['lcsh_status'] == 'unresolved')
    print(f'  LCSH: {lcsh_matched:,} standardised, '
          f'{lcsh_unresolved:,} unresolved (flagged for review).')

    # ── 3. Pre-compute comparison norms ───────────────────────────────────────
    all_rows = keep_rows + campus_rows
    comp_norms: list[str] = [comparison_normalise(r['name']) for r in all_rows]

    # ── 4. Build phonetic blocks ───────────────────────────────────────────────
    # Primary key:   first_initial + Soundex(first_substantive_token)
    # Secondary key: first_initial + Soundex(second_token)  [3+ token names]
    #
    # For place names, the first token is usually the most distinctive
    # (e.g. "Albany", "New", "Washington") — using it as the Soundex base
    # groups OCR variants of the same name better than using the last token.
    blocks: dict[str, list[int]] = defaultdict(list)
    for idx, comp_norm in enumerate(comp_norms):
        tokens = comp_norm.split()
        pkey = block_key(comp_norm)
        blocks[pkey].append(idx)
        if len(tokens) >= 3:
            first_init = tokens[0][0].upper() if tokens[0] else 'X'
            sec_key = f'{first_init}_{soundex(tokens[1])}'
            if sec_key != pkey:
                blocks[sec_key].append(idx)

    # ── 5. Within-block fuzzy matching → merge pairs ──────────────────────────
    uf = UnionFind(len(all_rows))
    merge_log: list[dict] = []
    total_pairs = 0

    for bkey, indices in blocks.items():
        if len(indices) < 2:
            continue
        if len(indices) > MAX_BLOCK_SIZE:
            continue

        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                total_pairs += 1
                ni = comp_norms[indices[i]]
                nj = comp_norms[indices[j]]
                ri = all_rows[indices[i]]
                rj = all_rows[indices[j]]

                # ── Prefix match (concatenation artefact) ────────────────────
                # For place names, the prefix rule requires the shorter form
                # to have ≥ 2 tokens.  A single bare word ("North", "West",
                # "New") must not absorb every compound name that starts with
                # it ("North Carolina", "West Virginia", "New York").  Two-token
                # prefixes are fine: "New York" → "New York State" is a genuine
                # variant; "College Hill" → "College Hill Road" is another.
                shorter, longer = (ni, nj) if len(ni) <= len(nj) else (nj, ni)
                is_prefix = (
                    len(shorter.split()) >= 2          # ← guard: ≥ 2 tokens
                    and longer.startswith(shorter)
                    and (len(longer) == len(shorter)
                         or longer[len(shorter)] == ' ')
                )
                if is_prefix:
                    score  = 100.0
                    reason = 'prefix'
                else:
                    threshold = (OCR_DIGIT_THRESHOLD
                                 if has_ocr_digit(ri['name']) or has_ocr_digit(rj['name'])
                                 else FUZZY_THRESHOLD)
                    score = fuzz.token_sort_ratio(ni, nj)
                    if score >= threshold:
                        reason = 'fuzzy'
                    elif score >= TEMPORAL_THRESHOLD and dates_are_close(ri, rj):
                        # Temporal proximity: close spelling + nearby dates.
                        #
                        # Guard 1 — LCSH conflict: if both entries are already
                        # LCSH-standardised to *different* headings, they are
                        # definitively different places ("Australia" vs "Austria",
                        # "Hamburg" vs "Bamberg").  Never merge two confirmed-
                        # different LCSH forms.
                        if (ri.get('lcsh_status') == 'matched'
                                and rj.get('lcsh_status') == 'matched'
                                and ri['name'] != rj['name']):
                            continue
                        #
                        # Guard 2 — first-token similarity: the first tokens of
                        # the comparison-normalised forms must themselves be
                        # similar (prevents a shared "St." or "New" from
                        # inflating the score for unrelated places).
                        first_i = ni.split()[0] if ni.split() else ''
                        first_j = nj.split()[0] if nj.split() else ''
                        if fuzz.ratio(first_i, first_j) < TEMPORAL_THRESHOLD:
                            continue
                        reason = 'temporal_proximity'
                    else:
                        continue

                uf.union(indices[i], indices[j])
                merge_log.append({
                    'name_a':  ri['name'],
                    'files_a': len(ri['files'].split(';')),
                    'name_b':  rj['name'],
                    'files_b': len(rj['files'].split(';')),
                    'score':   score,
                    'block':   bkey,
                    'reason':  reason,
                })

    print(f'Checked {total_pairs:,} within-block pairs.')

    # ── 6. Build clusters and produce canonical rows ───────────────────────────
    clusters: dict[int, list[dict]] = defaultdict(list)
    for idx, row in enumerate(all_rows):
        clusters[uf.find(idx)].append(row)

    merged_count    = sum(1 for c in clusters.values() if len(c) > 1)
    variant_count   = sum(len(c) - 1 for c in clusters.values() if len(c) > 1)
    singleton_count = sum(1 for c in clusters.values() if len(c) == 1)
    print(f'Clusters: {merged_count} merged groups '
          f'({variant_count} variants collapsed), '
          f'{singleton_count} singletons unchanged.')

    clean_rows = [merge_rows(cluster) for cluster in clusters.values()]
    clean_rows.sort(key=lambda r: r['name'].lower())

    # ── 7. Write outputs ───────────────────────────────────────────────────────
    CLEAN_HEADER  = ['name', 'lcsh_status', 'earliest_date', 'latest_date', 'files']
    FILTER_HEADER = ['original_name', 'name', 'drop_reason',
                     'earliest_date', 'latest_date', 'files']
    REPORT_HEADER = ['name_a', 'files_a', 'name_b', 'files_b',
                     'similarity_score', 'canonical_chosen', 'block_key', 'merge_reason']

    # Split clean_rows into the three named subsets for downstream use.
    # The combined entities_places_clean.csv is also retained so that other
    # scripts can read a single file without caring about status.
    verified_rows   = [r for r in clean_rows if r['lcsh_status'] == 'matched']
    unverified_rows = [r for r in clean_rows if r['lcsh_status'] == 'unresolved']
    campus_rows_out = [r for r in clean_rows if r['lcsh_status'] == 'campus']

    # Combined file (all three groups)
    clean_out = outdir / 'entities_places_clean.csv'
    with clean_out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CLEAN_HEADER)
        w.writeheader()
        w.writerows(clean_rows)
    print(f'  → {clean_out.name}: {len(clean_rows):,} total')

    # entities_places_verified.csv — LCSH heading confirmed
    verified_out = outdir / 'entities_places_verified.csv'
    with verified_out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CLEAN_HEADER)
        w.writeheader()
        w.writerows(verified_rows)
    print(f'  → {verified_out.name}: {len(verified_rows):,} LCSH-standardised entries')

    # entities_places_unverified.csv — geographic but no LCSH match yet
    unverified_out = outdir / 'entities_places_unverified.csv'
    with unverified_out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CLEAN_HEADER)
        w.writeheader()
        w.writerows(unverified_rows)
    print(f'  → {unverified_out.name}: {len(unverified_rows):,} entries (flagged for LCSH review)')

    # entities_places_campus.csv — Hamilton campus facilities (moved from people)
    campus_out = outdir / 'entities_places_campus.csv'
    with campus_out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CLEAN_HEADER)
        w.writeheader()
        w.writerows(campus_rows_out)
    print(f'  → {campus_out.name}: {len(campus_rows_out):,} campus facilities')

    filter_out = outdir / 'places_filtered_out.csv'
    dropped_rows.sort(key=lambda r: r.get('original_name', '').lower())
    with filter_out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FILTER_HEADER, extrasaction='ignore')
        w.writeheader()
        w.writerows(dropped_rows)
    print(f'  → {filter_out.name}: {len(dropped_rows):,} dropped entries')

    # Build name→canonical lookup for report
    name_to_canonical: dict[str, str] = {}
    for cluster in clusters.values():
        canon = merge_rows(cluster)['name']
        for r in cluster:
            name_to_canonical[r['name']] = canon

    report_out = outdir / 'places_reconciliation_report.tsv'
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
                'merge_reason':     entry['reason'],
            })
    print(f'  → {report_out.name}: {len(merge_log):,} merge decisions logged')

    # ── 8. LCNAF authority lookup (optional) ────────────────────────────────────
    if lcnaf_index:
        print()
        print('LCNAF authority lookup:')
        lcnaf_out_rows = []
        for row in clean_rows:
            lcnaf_form = lcnaf_lookup(row['name'], lcnaf_index)
            if not lcnaf_form:
                lcnaf_form = lcnaf_fuzzy_lookup(row['name'], lcnaf_index)
            lcnaf_out_rows.append({**row, 'lcnaf_form': lcnaf_form or ''})

        lcnaf_out = outdir / 'entities_places_lcnaf.csv'
        lcnaf_header = CLEAN_HEADER + ['lcnaf_form']
        with lcnaf_out.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=lcnaf_header)
            w.writeheader()
            w.writerows(lcnaf_out_rows)
        print(f'  → {lcnaf_out.name}: {len(lcnaf_out_rows):,} rows with lcnaf_form')

    print('\nDone.')
    return clean_rows, dropped_rows, merge_log


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description='Filter, standardise (LCSH/LCNAF), and deduplicate entities_places.csv.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--places',        '-p', required=True,
                   help='Path to entities_places_augmented.csv')
    p.add_argument('--outdir',        '-o', required=True,
                   help='Directory for output files')
    p.add_argument('--min-files',     '-m', type=int, default=MIN_FILES_UNKNOWN,
                   help=f'Min source files for unknown entries (default: {MIN_FILES_UNKNOWN})')
    p.add_argument('--lcnaf-data',    type=Path, default=None,
                   help='Directory containing LCNAF data (loads or builds lcnaf_geo_index.json, '
                        'or reads names.skosrdf.jsonld to build index). Optional.')
    p.add_argument('--campus-list',   type=Path, default=None,
                   help='Path to campus location list file (one per line, # = comment, '
                        'blank lines ignored). Optional.')
    p.add_argument('--regional-list', type=Path, default=None,
                   help='Path to a regional place-name authority list (one LCNAF/LCSH heading '
                        'per line; # = comment, blank lines ignored). Names in this list are '
                        'treated as verified and take priority over the full LCNAF index. '
                        'Single-file entries that match are rescued from the noise_low_freq '
                        'filter. Optional.')
    args = p.parse_args()

    # Load campus list if provided
    campus_list = None
    if args.campus_list:
        campus_set = set()
        with args.campus_list.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Normalise: lowercase and remove punctuation
                    normed = line.lower()
                    normed = re.sub(r'[^a-z0-9\s]', '', normed)
                    if normed:
                        campus_set.add(normed)
        campus_list = frozenset(campus_set)
        print(f'Loaded {len(campus_list)} campus locations from {args.campus_list.name}')

    # Load regional authority list if provided
    regional = None
    if args.regional_list:
        regional_path = Path(args.regional_list).expanduser().resolve()
        regional = load_regional_list(regional_path)

    reconcile(
        places_path     = Path(args.places).expanduser().resolve(),
        outdir          = Path(args.outdir).expanduser().resolve(),
        min_files       = args.min_files,
        lcnaf_data_dir  = args.lcnaf_data,
        campus_list     = campus_list,
        regional        = regional,
    )


if __name__ == '__main__':
    main()
