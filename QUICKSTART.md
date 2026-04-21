# Quick Start Guide

Get up and running with the Archipelago Metadata Generator & Enhancer in 5 minutes!

## Step 1: Install

```bash
pip install -r requirements.txt
```

## Step 2: View Available Commands

```bash
python main.py --help
```

## Step 3: Choose Your Workflow

### If Starting From Scratch

1. **Generate a blank template:**
   ```bash
   python main.py template --output ./my_metadata
   ```
   This creates a JSON file with all available fields.

2. **Edit the Template:**
   Open the generated JSON file in your text editor and fill in your metadata values.

3. **Convert to CSV:**
   ```bash
   python main.py process my_metadata/metadata_template.json --format csv --output ./ready_for_archipelago
   ```

### If You Have Existing Data

1. **Check Your Data Format:**
   Ensure you have a CSV or JSON file with your metadata.

2. **Process and Enhance:**
   ```bash
   python main.py process your_data.csv --enhance --normalize-names --format csv
   ```
   
   This will:
   - Fill in default values
   - Normalize names
   - Export to CSV format

3. **Validate:**
   ```bash
   python main.py validate your_data_output.csv
   ```

4. **View Statistics:**
   ```bash
   python main.py stats your_data_output.csv
   ```

## Common Commands Cheat Sheet

| Task | Command |
|------|---------|
| Create template | `python main.py template` |
| Convert CSV to JSON | `python main.py process data.csv --format json` |
| Convert JSON to CSV | `python main.py process data.json --format csv` |
| Validate data | `python main.py validate data.csv` |
| View statistics | `python main.py stats data.csv` |
| View schema | `python main.py schema` |
| Process with all features | `python main.py process data.csv --enhance --normalize-names` |

## Required Fields (Must Fill)

At minimum, your data must include:
- `local_identifier` - Unique ID
- `title` - Main title
- `description` - Description
- `type` - Object type
- `genre` - Genre
- `ismemberof` - Collection membership
- `rights_statements` - Rights info

Plus at least one of:
- `subgenre_audiovisual_materials`
- `subgenre_ephemera`
- `subgenre_manuscripts`
- `subgenre_publications`
- `subgenre_visual_materials`

## Example Workflow

```bash
# 1. Create template
python main.py template --count 5 --output templates

# 2. (Edit the JSON files manually)

# 3. Convert templates to CSV format with enhancements
python main.py process templates/metadata_template_1.json --enhance --format csv

# 4. Validate the output
python main.py validate metadata_template_1_output.csv

# 5. View a summary
python main.py stats metadata_template_1_output.csv

# 6. Ready! The CSV file is ready for Archipelago ingestion
```

## Tips & Tricks

### Batch Processing Multiple Files

```bash
# Create helper script: process_all.sh
for file in data/*.csv; do
  python main.py process "$file" --enhance --format both
done
chmod +x process_all.sh
./process_all.sh
```

### Generate Reports

```bash
# Create validation report in JSON format
python main.py validate your_data.csv --output reports
```

### Review Your Data Quality

```bash
# Check completeness of your dataset
python main.py stats your_data.csv
```

### Using Different Output Directories

```bash
# Process multiple files into different directories
python main.py process data1.csv --output output/batch1
python main.py process data2.csv --output output/batch2
```

## Troubleshooting

**"File not found" error:**
- Check that you're in the correct directory
- Use absolute paths if relative paths don't work

**"Required field missing" warnings:**
- Run `python main.py schema` to see required fields
- Add the missing fields to your data

**Character encoding problems:**
- Ensure CSV files are saved as UTF-8
- In Excel: File → Save As → CSV UTF-8 (Comma delimited)

**Processing is slow:**
- For very large files, validation may take time
- Use valid IDs from Windows Nominatim if you have geographic data

## Next Steps

1. Read the full **README.md** for comprehensive documentation
2. Check **examples/** folder for sample data
3. Review **config.py** to understand the schema
4. Use `--help` with any command for more options

Happy cataloging! 📚
