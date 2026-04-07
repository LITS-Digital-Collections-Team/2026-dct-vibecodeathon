#!/usr/bin/env python3
"""
list-places-nearby.py

Generate a plaintext list of GNIS feature names within a radius of a given
latitude/longitude. This script is intentionally self-contained and uses
paths relative to the containing directory so it can be dropped into a folder
that also contains a `gnis/` directory with the zipped GNIS national text.

Design notes:
- Default center is Clinton, NY (keeps previous behavior).
- Defaults mirror the earlier script but can be overridden via CLI.
- Default GNIS ZIP path is `gnis/DomesticNames_National_Text.zip` next to
  this script; the script will error if that ZIP is not present.

Typical usage (from the package directory):

  python3 list-places-nearby.py --lat 43.048852 --lon -75.380250 --radius 300

To specify a different GNIS zip file or output file:

  python3 list-places-nearby.py --zip gnis/DomesticNames_National_Text.zip --out results.txt

"""

from __future__ import annotations
import argparse
import csv
import math
import zipfile
from pathlib import Path
from typing import Iterable, Set

# --- Default center (Clinton, NY) and radius ---
DEFAULT_LAT = 43.048852
DEFAULT_LON = -75.380250
DEFAULT_RADIUS_MILES = 300.0

# Working directory is the directory containing this script. All paths are
# computed relative to this directory so users can move the folder around.
WORKDIR = Path(__file__).resolve().parent

# Default locations (relative to WORKDIR)
DEFAULT_GNIS_ZIP = WORKDIR / "gnis" / "DomesticNames_National_Text.zip"
DEFAULT_TXT_PATH_INSIDE = "Text/DomesticNames_National.txt"

# Conservative whitelist of GNIS feature classes to include (same as before).
WHITELIST: Set[str] = {
    "Populated Place",
    "Stream",
    "Lake",
    "Summit",
    "Valley",
    "Spring",
    "Island",
    "Cape",
    "Ridge",
    "Bay",
    "Flat",
    "Gap",
    "Swamp",
    "Bar",
    "Cliff",
    "Basin",
    "Channel",
    "Bend",
    "Falls",
    "Range",
    "Beach",
    "Area",
    "Pillar",
    "Rapids",
    "Glacier",
    "Bench",
    "Arch",
    "Woods",
    "Slope",
    "Plain",
    "Crater",
    "Arroyo",
    "Lava",
    "Isthmus",
    "Sea",
}

# State name -> USPS postal code mapping (used to create simple LC-like
# parenthetical forms such as "Name (N.Y.)").
STATE_TO_USPS = {
    'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA',
    'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE', 'Florida': 'FL', 'Georgia': 'GA',
    'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA',
    'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
    'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS', 'Missouri': 'MO',
    'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ',
    'New Mexico': 'NM', 'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH',
    'Oklahoma': 'OK', 'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
    'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT',
    'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY',
    'District of Columbia': 'DC', 'Puerto Rico': 'PR', 'Guam': 'GU', 'American Samoa': 'AS',
    'Northern Mariana Islands': 'MP', 'Virgin Islands': 'VI'
}


def postal_to_lc(postal: str) -> str:
    """Convert a 2-letter postal code to dotted style like 'N.Y.'"""
    if not postal or len(postal) != 2:
        return postal
    return f"{postal[0]}.{postal[1]}."


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in miles between two decimal-degree points."""
    R = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def normalize_name(name: str) -> str:
    """Minimal normalization: collapse whitespace and strip."""
    return " ".join(name.split()).strip()


def process_gnis(zip_path: Path, txt_inside: str, center_lat: float, center_lon: float,
                 radius_miles: float, whitelist: Set[str]) -> Iterable[str]:
    """Stream the GNIS text inside `zip_path` and yield normalized names.

    Deduplication is case-insensitive on the already-normalized output form.
    """
    seen = set()
    out_names = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        with zf.open(txt_inside) as fh:
            reader = csv.reader((line.decode('utf-8', errors='replace') for line in fh), delimiter='|')
            header = next(reader, None)
            if not header:
                return []
            # find indices for required fields; this will raise if header changes
            idx_name = header.index('feature_name')
            idx_class = header.index('feature_class')
            idx_state = header.index('state_name')
            idx_lat = header.index('prim_lat_dec')
            idx_lon = header.index('prim_long_dec')

            for row in reader:
                try:
                    fclass = row[idx_class].strip()
                except Exception:
                    continue
                if fclass not in whitelist:
                    continue
                name = normalize_name(row[idx_name])
                state = row[idx_state].strip()
                lat_s = row[idx_lat].strip()
                lon_s = row[idx_lon].strip()
                if not lat_s or not lon_s:
                    continue
                try:
                    lat = float(lat_s)
                    lon = float(lon_s)
                except ValueError:
                    continue
                dist = haversine_miles(center_lat, center_lon, lat, lon)
                if dist <= radius_miles:
                    postal = STATE_TO_USPS.get(state, '')
                    if postal:
                        name_out = f"{name} ({postal_to_lc(postal)})"
                    else:
                        name_out = f"{name} ({state})" if state else name
                    key = name_out.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    out_names.append(name_out)
    return out_names


def main(argv: list[str] | None = None) -> int:
    """Parse CLI args and run the GNIS filtering. Returns 0 on success."""
    parser = argparse.ArgumentParser(description="List GNIS place names near a coordinate")
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT,
                        help="Center latitude (default: Clinton, NY)")
    parser.add_argument("--lon", type=float, default=DEFAULT_LON,
                        help="Center longitude (default: Clinton, NY)")
    parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS_MILES,
                        help="Radius in miles (default: 300)")
    parser.add_argument("--zip", type=Path, default=DEFAULT_GNIS_ZIP,
                        help="Path to GNIS zip file (relative to script directory by default)")
    parser.add_argument("--out", type=Path, default=None, help="Output file path")
    parser.add_argument("--classes", type=str, default=None,
                        help="Comma-separated GNIS feature classes to include (default: conservative whitelist)")
    args = parser.parse_args(argv)

    # Compute a sensible default output filename if none provided. The
    # default now embeds the center coordinates and radius for clarity.
    if args.out is None:
        lat_str = f"{args.lat:.5f}"
        lon_str = f"{args.lon:.5f}"
        out_name = f"places_{lat_str}_{lon_str}_{int(args.radius)}mi.txt"
        args.out = WORKDIR / out_name

    # Build the feature-class set from `--classes` if provided, otherwise
    # fall back to the conservative WHITELIST above.
    if args.classes:
        classes_set = set([c.strip() for c in args.classes.split(',') if c.strip()])
    else:
        classes_set = WHITELIST

    if not args.zip.exists():
        print(f"GNIS zip not found at {args.zip}. Please download it or point --zip to the file.")
        return 2

    print(f"Processing GNIS file around ({args.lat}, {args.lon}) within {args.radius} miles...")
    names = list(process_gnis(args.zip, DEFAULT_TXT_PATH_INSIDE, args.lat, args.lon, args.radius, classes_set))
    names_sorted = sorted(names, key=lambda s: s.lower())
    args.out.write_text("\n".join(names_sorted) + "\n", encoding='utf-8')
    print(f"Wrote {len(names_sorted)} unique names to {args.out}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
