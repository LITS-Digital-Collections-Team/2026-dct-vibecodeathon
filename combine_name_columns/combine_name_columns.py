"""
combine_name_columns.py
-----------------------
Combines multiple 'personal_name' columns in a metadata CSV into a single
pipe-delimited 'personal_name_combined' column.

This script was written to support metadata workflows where names are spread
across multiple role-specific columns (e.g., personal_name_author,
personal_name_editor, personal_name_illustrator). It collects all non-empty
values from every column whose name starts with 'personal_name' and joins
them into one column using the '|@|' delimiter, which is the multi-value
separator used by the Hamilton College digital collections ingest system.

USAGE
-----
1. Set the `csv_path` variable below to the full path of your input CSV file.
2. Run the script:
       python combine_name_columns.py
3. The script overwrites the input file, adding a new 'personal_name_combined'
   column at the end. Back up your file before running if needed.

REQUIREMENTS
------------
  - Python 3.6+
  - pandas  (install with: pip install pandas)

EXAMPLE INPUT (two rows, abbreviated columns)
----------------------------------------------
  local_identifier | personal_name_author | personal_name_editor | personal_name_illustrator
  item-001         | Smith, Jane          |                      | Doe, John
  item-002         |                      | Brown, Alice         | Brown, Alice

EXAMPLE OUTPUT (new combined column appended)
---------------------------------------------
  local_identifier | ... | personal_name_combined
  item-001         | ... | Smith, Jane|@|Doe, John
  item-002         | ... | Brown, Alice|@|Brown, Alice

NOTE: Duplicate values are preserved as-is; deduplication is not performed.

Copyright (C) 2025  Alyssa Willis, Hamilton College LITS Digital Collections Team
License: GNU General Public License v3.0 or later — see LICENSE or
         <https://www.gnu.org/licenses/gpl-3.0.html>

DISCLAIMER: Portions of this script were generated with the assistance of an
AI coding tool (GitHub Copilot). All code has been reviewed and tested by the
author before use.
"""

import pandas as pd


# ---------------------------------------------------------------------------
# CONFIGURATION — update csv_path to point to your input file
# ---------------------------------------------------------------------------
# Example (macOS/Linux):  '/home/username/metadata/my_collection.csv'
# Example (Windows):      r'C:\Users\username\metadata\my_collection.csv'
csv_path = '/home/awillis/Test folder/Copy of AMI V. Valta Parma Papers- Binder 2 - Binder 2.csv'


# ---------------------------------------------------------------------------
# STEP 1: Load the CSV into a pandas DataFrame
# ---------------------------------------------------------------------------
df = pd.read_csv(csv_path)


# ---------------------------------------------------------------------------
# STEP 2: Identify all columns whose names start with 'personal_name'
#         This picks up the base 'personal_name' column as well as all
#         role-specific variants (personal_name_author, personal_name_editor,
#         personal_name_illustrator, etc.)
# ---------------------------------------------------------------------------
personal_name_cols = [col for col in df.columns if col.startswith('personal_name')]

print(f"Found {len(personal_name_cols)} personal_name columns:")
print(personal_name_cols)


# ---------------------------------------------------------------------------
# STEP 3: Define a row-level function that collects all non-empty values
#         from the identified columns and joins them with the '|@|' separator
# ---------------------------------------------------------------------------
def combine_personal_names(row):
    """
    Given a DataFrame row, return a '|@|'-joined string of all non-empty
    values found across the personal_name columns.

    Parameters
    ----------
    row : pandas.Series
        A single row from the DataFrame.

    Returns
    -------
    str
        Combined name string, e.g. 'Smith, Jane|@|Doe, John', or an empty
        string if no personal_name values are present in the row.
    """
    values = []
    for col in personal_name_cols:
        val = row[col]
        # Skip NaN values and whitespace-only strings; include everything else
        if pd.notna(val) and str(val).strip():
            values.append(str(val).strip())
    # Join with the multi-value delimiter used by the ingest system
    return '|@|'.join(values) if values else ''


# ---------------------------------------------------------------------------
# STEP 4: Apply the function across every row to create the combined column
# ---------------------------------------------------------------------------
df['personal_name_combined'] = df.apply(combine_personal_names, axis=1)


# ---------------------------------------------------------------------------
# STEP 5: Write the updated DataFrame back to the same CSV file.
#         index=False prevents pandas from adding a row-number column.
# ---------------------------------------------------------------------------
df.to_csv(csv_path, index=False)

print(f"\nSuccessfully added 'personal_name_combined' column to:\n  {csv_path}")


# ---------------------------------------------------------------------------
# STEP 6: Print a preview of the new column for the first 10 rows so you can
#         quickly verify the output looks correct before further processing
# ---------------------------------------------------------------------------
print(f"\nFirst 10 rows of the new column:")
for idx, row in df[['local_identifier', 'personal_name_combined']].head(10).iterrows():
    print(f"  {row['local_identifier']}: {row['personal_name_combined']}")