# list-places-nearby

A small utility to produce a plaintext list of GNIS place names within a
given radius of a latitude/longitude point. The script and data are intended
to live together in the same folder so paths are simple and portable.

Contents
- `list-places-nearby.py` — the main script (CLI)
- `gnis/` — expected to contain `DomesticNames_National_Text.zip` with
  the GNIS national text archive inside (the script looks for
  `Text/DomesticNames_National.txt` inside the ZIP).

Quick start

1. Ensure the folder contains `gnis/DomesticNames_National_Text.zip`.
   If you don't already have it, download the GNIS national text ZIP from
   the USGS (or use the copy included in this package, if present).

2. Run the script from the package directory. Examples:

```bash
# default (Clinton, NY, 300 miles)
python3 list-places-nearby.py

# explicit coordinate + radius
python3 list-places-nearby.py --lat 43.048852 --lon -75.380250 --radius 300

# specify the GNIS ZIP explicitly and an output file
python3 list-places-nearby.py --zip gnis/DomesticNames_National_Text.zip --out places_near_clinton.txt
```

Output
- By default the script writes a filename that embeds the query center and
  radius into the name, e.g. `places_43.04885_-75.38025_300mi.txt` into the
  package directory (where coordinates are the center point and `300` is the
  integer radius in miles).
- Each line is a single place name, formatted like `Name (S.T.)` where
  `S.T.` is a dotted postal-code abbreviation (e.g. `Clinton (N.Y.)`).

Additional options

- `--classes` — pass a comma-separated list of GNIS feature classes to
  include. Example: `--classes "Populated Place,Stream,Lake"`. If not
  provided the script uses a conservative default whitelist of populated
  places and selected natural features.

Notes & troubleshooting
- The script streams the GNIS text inside the ZIP and may take a minute to
  run for large radii. It filters to a conservative whitelist of feature
  classes (populated places and selected natural features).
- If header fields change in the GNIS text file the script may raise an
  exception when locating fields—report that issue and include a sample
  of the GNIS header line so it can be repaired.

License / attribution
- This script is a small utility added to help produce place-name lists
  for authority reconciliation workflows. The GNIS data used is public
  domain (U.S. Geological Survey / USGS); please follow GNIS terms when
  redistributing derivatives.
