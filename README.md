# Archipelago Metadata Generator & Enhancer

A comprehensive Python tool for metadata catalogers to generate, enhance, validate, and export metadata for ingestion into Archipelago digital collections management system.

## Features

- **Template Generation**: Create blank metadata templates in JSON format
- **Format Conversion**: Convert between CSV and JSON formats
- **Metadata Validation**: Validate records against Archipelago schema with detailed error reporting
- **Data Enhancement**: Auto-fill default values, normalize names, and process metadata
- **Statistics Generation**: Analyze metadata completeness and field population
- **Batch Processing**: Process multiple records efficiently
- **CSV Export**: Export to CSV format compliant with Archipelago requirements

## Installation

### Requirements
- Python 3.7+
- pip (Python package manager)

### Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Verify installation:
```bash
python main.py --help
```

## Usage

### Command-Line Interface

The tool provides several commands for different tasks:

#### 1. Generate Templates

Create blank metadata templates to fill in manually:

```bash
python main.py template --count 5 --output ./templates
```

Options:
- `--count, -c`: Number of templates to generate (default: 1)
- `--output, -o`: Output directory (default: ./output)

#### 2. Process Metadata Files

Convert and process metadata files with optional enhancement:

```bash
python main.py process input.csv --format csv --enhance --normalize-names
```

Options:
- `input_file`: Path to CSV or JSON file (required)
- `--format, -f`: Output format (csv, json, both) (default: csv)
- `--enhance`: Apply enhancements to records
- `--normalize-names`: Normalize personal and corporate names
- `--validate`: Validate records before export (default: True)
- `--output, -o`: Output directory (default: ./output)

**Examples:**

Process CSV to CSV with enhancements:
```bash
python main.py process metadata.csv --format csv --enhance --output ./processed
```

Process CSV to both CSV and JSON:
```bash
python main.py process metadata.csv --format both --output ./processed
```

#### 3. Validate Metadata

Validate your metadata records against the schema and generate a detailed report:

```bash
python main.py validate metadata.csv --output ./reports
```

This will:
- Check all required fields
- Validate field values
- Check for common issues
- Generate a JSON report with details

#### 4. View Statistics

Get a summary of metadata completeness:

```bash
python main.py stats metadata.csv
```

Shows:
- Total records and fields
- Field population percentages
- Most and least populated fields
- Number of fully populated records

#### 5. Display Schema

View the complete metadata schema:

```bash
python main.py schema
```

Shows:
- All required fields
- All available fields
- Field categories and organization

## Metadata Schema

### Required Fields

The following fields must be present in every record:

- `local_identifier` - Unique identifier for the resource
- `title` - Primary title of the resource
- `description` - Detailed description
- `type` - Type of object (object, image, sound, text, video, map, etc.)
- `genre` - Genre classification
- `subgenre_*` - Specific subgenre fields
  - `subgenre_audiovisual_materials`
  - `subgenre_ephemera`
  - `subgenre_manuscripts`
  - `subgenre_publications`
  - `subgenre_visual_materials`
- `ismemberof` - Collection membership identifier
- `rights_statements` - Rights and licensing information

### Optional Fields

#### Name Fields

**Personal Name Fields** (role-based):
- personal_name, personal_name_artist, personal_name_author, personal_name_cartographer, personal_name_composer, personal_name_contributor, personal_name_dedicatee, personal_name_editor, personal_name_illustrator, personal_name_interviewee, personal_name_interviewer, personal_name_photographer, personal_name_publisher, personal_name_translator, etc.

**Corporate Name Fields**:
- corporate_name, corporate_name_author, corporate_name_owner, corporate_name_photographer, etc.

**Family Name Fields**:
- family_name

#### Subject Fields

- `subject_personal_name` - Subject heading using personal names
- `subject_corporate_name` - Subject heading using corporate names
- `subject_family_name` - Subject heading using family names
- `subject_geographic` - Geographic subject heading
- `subject_topical` - Topical subject heading
- `subject_cartographic_coordinates` - Coordinates in format "lat, lng"

#### Geographic Fields

- `geographic_location` - JSON object with detailed location data
- `subject_geographic` - Geographic subject heading

#### Descriptive Fields

- `subtitle` - Subtitle of the resource
- `title_alternative` - Alternative title
- `provenance` - Provenance information
- `note` - General notes
- `abstract` - Abstract or summary
- `date_full` - Full date in ISO format
- `date_note` - Notes about dating

#### Publication Fields

- `publisher_name` - Name of publisher
- `place_of_publication` - Where published
- `series_title` - Series name if part of series
- `sort_order` - Sort order within collection

#### Resource Metadata

- `language` - Language code (default: en)
- `extent` - Physical or digital extent
- `table_of_contents` - Table of contents
- `building_name` - Building or location name

#### Access and Rights

- `shelf_location` - Shelf location (if physical)
- `physical_location` - Physical location details
- `restrictions_on_access` - Access restrictions (default provided)
- `audios` - Audio files associated
- `images` - Image files associated
- `models` - 3D model files
- `videos` - Video files associated
- `documents` - Document files associated

#### Relationship Fields

- `ispartof` - Parent resource identifier
- `sequence_id` - Sequence in a series
- `sort_order` - Sorting order

## Data Format Guidelines

### CSV Format

When providing data in CSV format:
- First row should contain field headers matching the schema
- Each subsequent row is a metadata record
- String values containing commas should be quoted
- Use UTF-8 encoding

Example:
```csv
local_identifier,title,description,type,genre,ismemberof,rights_statements
item_001,Sample Document,A description,text,document,collection_1,CC0
```

### JSON Format

When providing data in JSON format:
- Root level should be an array of objects
- Each object is a metadata record
- Use UTF-8 encoding

Example:
```json
[
  {
    "local_identifier": "item_001",
    "title": "Sample Document",
    "description": "A description",
    "type": "text",
    "genre": "document",
    "ismemberof": "collection_1",
    "rights_statements": "CC0"
  }
]
```

## Enhancement Features

### Default Value Filling

When enhancement is enabled, the tool automatically fills in commonly used default values:

- `language`: "en" (English)
- `type`: "object"
- `restrictions_on_access`: "There are no restrictions on access to this resource."

### Name Normalization

When `--normalize-names` flag is used:
- Personal names formatted in title case with special handling for articles (of, and, the, van, von, de, la, le)
- Corporate names formatted in title case
- Consistent formatting across records

## Output

### CSV Output

When exporting to CSV, the tool:
- Includes all fields from the schema in the correct order
- Fills empty cells with empty strings
- Uses UTF-8 encoding
- Quoted fields as needed

### JSON Output

When exporting to JSON, the tool:
- Creates a properly formatted JSON array
- Includes all fields from records
- Uses UTF-8 encoding with readable formatting

### Validation Report

When validation is run, a JSON report is generated containing:
- Total, valid, and invalid record counts
- Detailed error messages for invalid records
- Warning messages for records with issues
- By-record error tracking

## Examples and Workflows

### Workflow 1: Create and Process Metadata

1. Generate templates:
```bash
python main.py template --count 10
```

2. Fill in the templates manually (JSON files in `./output`)

3. Convert to CSV:
```bash
python main.py process metadata_template_1.json --format csv
```

4. Validate:
```bash
python main.py validate metadata_template_1_output.csv
```

5. View statistics:
```bash
python main.py stats metadata_template_1_output.csv
```

### Workflow 2: Batch Process Existing Data

1. Start with raw CSV data:
```bash
python main.py process raw_data.csv --enhance --normalize-names --format both
```

2. Validate the output:
```bash
python main.py validate raw_data_output.csv
```

3. Fix any validation issues, then re-process if needed

### Workflow 3: Prepare for Archipelago Ingestion

1. Process your source data:
```bash
python main.py process source_data.csv --enhance --format csv --output ./archipelago_ready
```

2. Validate final output:
```bash
python main.py validate archipelago_ready/source_data_output.csv
```

3. Export CSV is ready for Archipelago ingestion

## Troubleshooting

### "Required field 'X' is missing or empty"

**Issue**: The validator found empty required fields.

**Solution**: 
- Use `python main.py schema` to see which fields are required
- Fill in all required fields in your data
- Re-run validation to confirm

### "File must be .csv or .json"

**Issue**: You provided a file in an unsupported format.

**Solution**: Convert your file to either CSV or JSON format first.

### Character Encoding Issues

**Issue**: Special characters appear as garbled text.

**Solution**: Ensure your source file uses UTF-8 encoding:
- In Excel: Save As → CSV UTF-8 (Comma delimited)
- In other editors: Select UTF-8 encoding when saving

### Large File Processing

For very large files (10,000+ records):
- Processing may take longer
- Consider splitting into batches
- Use `--validate false` flag to speed up processing if validation isn't needed

## Contributing and Development

### Project Structure

```
.
├── main.py              # CLI entry point
├── generator.py         # Core metadata generation logic
├── validator.py         # Validation logic
├── config.py            # Schema and configuration
├── requirements.txt     # Dependencies
├── README.md            # This file
└── output/              # Default output directory
```

### Adding New Features

1. Validation logic: Modify `validator.py`
2. Enhancement logic: Modify `generator.py` methods
3. CLI commands: Add new command to `main.py`
4. Schema updates: Modify `config.py`

## License

[Your License Here]

## Support

For issues, questions, or feature requests, please contact the development team.

## Version

Archipelago Metadata Generator & Enhancer v1.0.0
Python 3.7+
