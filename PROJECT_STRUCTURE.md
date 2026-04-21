# Project Structure

Archipelago Metadata Generator & Enhancer project organization and file descriptions.

## Directory Layout

```
Metadata Generator:Enhancer/
├── main.py                      # Main CLI entry point
├── generator.py                 # Core metadata generation and enhancement logic
├── validator.py                 # Metadata validation logic
├── config.py                    # Configuration, schema definitions, and constants
├── requirements.txt             # Python package dependencies
├── README.md                    # Comprehensive documentation
├── QUICKSTART.md                # Quick start guide for new users
├── PROJECT_STRUCTURE.md         # This file - project organization
├── .gitignore                   # Git ignore patterns
├── config_example.json          # Example configuration structure
└── examples/                    # Example metadata files
    ├── sample_data.csv          # Sample metadata in CSV format
    └── sample_data.json         # Sample metadata in JSON format

(Optional directories created during runtime)
├── output/                      # Default output directory for generated files
├── templates/                   # User-created templates directory
└── reports/                     # Validation reports and statistics
```

## File Descriptions

### Core Application Files

#### `main.py`
- **Purpose**: Command-line interface entry point
- **Key Components**:
  - CLI commands: `template`, `process`, `validate`, `stats`, `schema`
  - Click framework for user-friendly CLI
  - Integration with Generator and Validator classes
- **Usage**: `python main.py [command] [options]`
- **Lines of Code**: ~400
- **Dependencies**: generator, validator, click

#### `generator.py`
- **Purpose**: Core metadata generation and enhancement logic
- **Key Classes**:
  - `MetadataGenerator`: Main class handling all generation/enhancement operations
- **Key Methods**:
  - `create_blank_template()`: Generate empty template
  - `load_from_csv()`, `load_from_json()`: Load data
  - `enhance_record()`, `enhance_batch()`: Enhance metadata
  - `to_csv()`, `to_json()`: Export functionality
  - `get_statistics()`: Analyze metadata completeness
  - `_normalize_names()`: Name standardization
- **Lines of Code**: ~300
- **Dependencies**: pandas, config, validator

#### `validator.py`
- **Purpose**: Validate metadata against Archipelago schema
- **Key Classes**:
  - `MetadataValidator`: Metadata validation logic
- **Key Methods**:
  - `validate_record()`: Validate single record
  - `validate_batch()`: Validate multiple records
  - `_validate_field_values()`: Check field value validity
  - `_validate_relationships()`: Check field relationships
  - `_validate_geographic()`: Validate geographic data
- **Lines of Code**: ~150
- **Dependencies**: config

#### `config.py`
- **Purpose**: Configuration and schema definitions
- **Key Content**:
  - `METADATA_SCHEMA`: Complete field definitions
  - `DEFAULT_VALUES`: Default field values
  - `VALID_TYPES`, `VALID_LANGUAGES`: Allowlists
  - `GEO_LOCATION_TEMPLATE`: Geographic data structure
  - `NOMINATIM_SETTINGS`: API configuration
  - Output encoding and formatting options
- **Lines of Code**: ~120
- **Dependencies**: None

### Documentation Files

#### `README.md`
- Comprehensive user documentation
- Schema information
- Usage examples and workflows
- Troubleshooting guide
- ~800 lines

#### `QUICKSTART.md`
- Getting started guide
- 5-minute setup instructions
- Command cheat sheet
- Common workflows
- Tips and tricks
- ~150 lines

#### `PROJECT_STRUCTURE.md` (This File)
- Project organization documentation
- File descriptions
- Architecture overview
- Development guidelines
- ~200 lines

### Configuration Files

#### `requirements.txt`
- Python dependencies:
  - pandas: Data manipulation
  - requests: HTTP requests
  - geopy: Geographic operations
  - python-dotenv: Environment variables
  - click: CLI framework
  - pyyaml: YAML parsing

#### `config_example.json`
- Example configuration structure
- Shows available settings
- Field category documentation
- Reference for advanced users

#### `.gitignore`
- Standard Python ignores
- Project-specific patterns
- Output and temporary file patterns

### Example Data Files

#### `examples/sample_data.csv`
- Sample metadata in CSV format
- 3 complete records
- Real-world examples from NYC collections
- Demonstrates all field types

#### `examples/sample_data.json`
- Same data as CSV but in JSON format
- Properly formatted geographic_location objects
- Useful for JSON workflow testing

## Architecture Overview

### Data Flow

```
Input Files (CSV/JSON)
    ↓
Generator.load_from_* ← Load records
    ↓
Generator.enhance_record ← Optional enhancement
    ├─ apply defaults
    ├─ normalize names
    └─ add timestamps
    ↓
Validator.validate_record ← Validate against schema
    ├─ check required fields
    ├─ validate field values
    └─ check relationships
    ↓
Generator.to_csv/json ← Export
    ↓
Output Files (CSV/JSON)
```

### Class Relationships

```
MetadataGenerator
├─ uses MetadataValidator
├─ uses config (METADATA_SCHEMA, DEFAULT_VALUES)
└─ processes Dict objects (metadata records)

MetadataValidator
├─ uses config (METADATA_SCHEMA, VALID_TYPES, VALID_LANGUAGES)
└─ processes Dict objects

CLI (main.py)
├─ uses MetadataGenerator
├─ uses MetadataValidator
├─ uses config
└─ provides command interface
```

## Module Dependencies

```
main.py
├── generator.py
│   ├── config.py
│   ├── validator.py
│   └── pandas (external)
├── validator.py
│   └── config.py
└── config.py
```

## Field Organization

The metadata schema organizes 77 fields into categories:

### By Type (77 fields)
- **Personal Name Fields** (20): Role-specific personal names
- **Corporate Name Fields** (5): Organization/entity names
- **Subject Fields** (6): Subject headings and geography
- **Geographic Fields** (2): Geographic information
- **File Resource Fields** (5): Associated digital files
- **Name Fields** (6): General naming
- **Descriptive Fields** (15): Content descriptions
- **Access & Rights** (4): Access and licensing
- **Publication Fields** (4): Publisher information
- **Type & Genre** (5): Resource classification
- **Location Fields** (3): Physical/location information
- **Relationships** (3): Resource relationships

### By Requirement
- **Required** (12): Must be present
- **Recommended** (15): Should be present
- **Optional** (50): May be present

## Development Guidelines

### Adding New Features

1. **New Validation Rules**: Edit `validator.py`
   - Add method to `MetadataValidator` class
   - Call from `validate_record()` or `validate_batch()`

2. **New Enhancement Methods**: Edit `generator.py`
   - Add method to `MetadataGenerator` class
   - Call from `enhance_record()` or `enhance_batch()`

3. **New CLI Commands**: Edit `main.py`
   - Create new `@cli.command()` function
   - Use `click` decorators for arguments/options
   - Call appropriate `MetadataGenerator` methods

4. **Schema Changes**: Edit `config.py`
   - Update `METADATA_SCHEMA` dictionary
   - Update `VALID_TYPES` or other allowlists
   - Update default values if needed

### Code Style

- Follow PEP 8 guidelines
- Use type hints where practical
- Document public methods with docstrings
- Use descriptive variable names
- Keep functions focused and modular

### Testing Recommendations

- Test with sample_data.csv and sample_data.json
- Verify all CLI commands work
- Test with various input formats
- Check validation messages are helpful
- Verify output files are properly formatted

## Configuration Customization

Users can customize behavior by:

1. Modifying `config.py` directly (for local changes)
2. Using `config_example.json` as reference
3. Setting environment variables (future enhancement)
4. Passing command-line options (implemented via Click)

## Performance Considerations

- **Current**: Handles CSV/JSON files with 1000+ records efficiently
- **Memory**: Uses pandas DataFrame for efficient data handling
- **Validation**: O(n) complexity for batch validation
- **I/O**: Streaming-friendly for larger datasets in future versions

## Known Limitations

1. Geographic coordinates require Nominatim service (optional)
2. Validation doesn't check against external authority files
3. No built-in name authority control (LCNAF, VIAF)
4. No support for RDF output (future enhancement)
5. Geographic lookup currently disabled in code (set nominatim_enabled: false in config)

## Future Enhancements

- Integration with name authority services (LCNAF, VIAF)
- RDF/Linked Data output format
- Batch API for processing
- Web interface
- Database integration
- Automated geographic coordinate lookup
- Custom field support
- Template system for institutions

---

**Last Updated**: April 21, 2026  
**Version**: 1.0.0  
**Maintainer**: Archipelago Community
