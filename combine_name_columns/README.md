# combine_name_columns

A Python script that consolidates multiple role-specific `personal_name` columns in a metadata CSV file into a single pipe-delimited `personal_name_combined` column.

---

## Background

This script was developed to support digital collections metadata workflows at Hamilton College. Metadata spreadsheets exported from the collections management system often contain many role-specific personal name columns (e.g., `personal_name_author`, `personal_name_editor`, `personal_name_illustrator`). Before ingesting records into the digital repository, these values need to be merged into one column using the `|@|` multi-value delimiter required by the ingest system.

The sample files in this repository come from work on the **V. Valta Parma Papers** collection and contain 19 personal name columns.

---

## Files

| File | Description |
|------|-------------|
| `combine_name_columns.py` | Main Python script |
| `Original Valta Parmer metadata.csv` | Sample input: original metadata spreadsheet with separate personal name columns |
| `Combined_names final file.csv` | Sample output: original metadata plus the new `personal_name_combined` column |

---

## Requirements

- **Python** 3.6 or later
- **pandas** library

Install pandas if you do not already have it:

```bash
pip install pandas
```

---

## Usage

1. **Back up your CSV file.** The script overwrites the input file in place.

2. **Open `combine_name_columns.py`** in a text editor or IDE.

3. **Set the file path.** Find the `csv_path` variable near the top of the script and update it to point to your CSV file:

   ```python
   # macOS / Linux
   csv_path = '/home/username/metadata/my_collection.csv'

   # Windows
   csv_path = r'C:\Users\username\metadata\my_collection.csv'
   ```

4. **Run the script:**

   ```bash
   python combine_name_columns.py
   ```

5. **Check the output.** The script prints the names of all detected `personal_name` columns and a preview of the first 10 combined values so you can verify the results before further processing.

---

## How It Works

1. The script reads the CSV into a pandas DataFrame.
2. It finds every column whose name starts with `personal_name` (including the base `personal_name` column and all role-specific variants).
3. For each row, it collects all non-empty values from those columns, strips leading/trailing whitespace, and joins them with `|@|`.
4. The joined string is written to a new `personal_name_combined` column appended at the end of the DataFrame.
5. The updated DataFrame is saved back to the same CSV file.

### Example

**Input (abbreviated):**

| local_identifier | personal_name_author | personal_name_editor | personal_name_illustrator |
|------------------|----------------------|----------------------|---------------------------|
| item-001 | Smith, Jane | | Doe, John |
| item-002 | | Brown, Alice | |

**Output (new column appended):**

| local_identifier | … | personal_name_combined |
|------------------|---|------------------------|
| item-001 | … | Smith, Jane\|@\|Doe, John |
| item-002 | … | Brown, Alice |

> Duplicate values across columns are preserved; deduplication is not performed.

---

## AI Code Disclaimer

Portions of this script were generated with the assistance of an AI coding tool (GitHub Copilot). All generated code has been reviewed, tested, and verified by the author prior to use.

---

## License

Copyright (C) 2025 Alyssa Willis, Hamilton College LITS Digital Collections Team

This program is free software: you can redistribute it and/or modify it under the terms of the **GNU General Public License** as published by the Free Software Foundation, either **version 3 of the License, or (at your option) any later version**.

This program is distributed in the hope that it will be useful, but **WITHOUT ANY WARRANTY**; without even the implied warranty of **MERCHANTABILITY** or **FITNESS FOR A PARTICULAR PURPOSE**. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

