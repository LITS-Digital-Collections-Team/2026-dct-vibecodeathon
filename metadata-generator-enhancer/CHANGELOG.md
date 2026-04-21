# Changelog

All notable changes to the Archipelago Metadata Generator & Enhancer project will be documented in this file.

## [1.0.0] - 2026-04-21

### Added

#### Core Features
- **Metadata Generation**: Create blank templates with all 77 Archipelago schema fields
- **Format Support**: Load and export CSV and JSON formats
- **Data Enhancement**: Auto-fill defaults, normalize names, add timestamps
- **Validation**: Comprehensive validation with required/optional field checking
- **Batch Processing**: Process multiple records efficiently with statistics
- **Geographic Support**: Template for structured geographic location data

#### CLI Commands
- `template`: Generate blank metadata templates
- `process`: Convert and enhance metadata files
- `validate`: Validate metadata records against schema
- `stats`: Generate statistics about metadata completeness
- `schema`: Display the complete metadata schema

#### Validation Features
- Required field checking (12 required fields)
- Field value validation (types, languages, genres)
- Relationship validation between fields
- Geographic data consistency checking
- Batch validation with per-record error reporting
- Warning system for non-critical issues

#### Enhancement Features
- Automatic default value filling
- Personal and corporate name normalization (title case with intelligence)
- Timestamp auto-generation option
- Intelligent article/preposition handling in names

#### Schema Support
- 77 total metadata fields organized by category
- 20 Personal name fields (role-based: author, photographer, editor, etc.)
- 5 Corporate name fields
- 6 Subject heading fields
- 2 Geographic fields with Nominatim template
- 5 File resource fields (audios, images, models, videos, documents)
- Complete support for Archipelago ingestion requirements

#### Input/Output
- **Input**: CSV, JSON formats with UTF-8 encoding
- **Output**: CSV (all-fields), JSON (all-fields), validation reports
- **Encoding**: UTF-8 throughout for international character support
- **Export**: Field reordering to match schema, proper quoting, NaN handling

#### Documentation
- Comprehensive README with workflows and troubleshooting
- Quick Start guide for new users
- Project Structure documentation
- Full schema documentation
- Code comments and docstrings
- Example files with real metadata samples

#### Example Data
- `sample_data.csv`: 3 records from NYC historical collections
- `sample_data.json`: Same data in JSON format
- Demonstrates:
  - Historical maps (cartographic)
  - Photographs (visual materials)
  - Manuscripts (primary sources)
  - All required fields properly filled
  - Geographic location structure
  - Various name fields and roles

#### Configuration
- `config.py`: Centralized schema and defaults
- `config_example.json`: Example configuration structure
- Customizable defaults for common fields
- Allowlists for types and languages

#### Development
- `.gitignore`: Python and project-specific patterns
- Modular code structure for easy maintenance
- Type hints for better code documentation
- Clean separation of concerns (Generation, Validation, CLI)

### Technical Details

#### Dependencies
- pandas >= 1.3.0: Data manipulation and CSV/JSON handling
- requests >= 2.26.0: HTTP operations (future geographic lookup)
- geopy >= 2.2.0: Geographic operations (future enhancement)
- python-dotenv >= 0.19.0: Environment configuration
- click >= 8.0.0: CLI framework
- pyyaml >= 5.4.0: Configuration file parsing

#### Code Statistics
- main.py: ~400 lines (CLI interface)
- generator.py: ~300 lines (core logic)
- validator.py: ~150 lines (validation)
- config.py: ~120 lines (configuration)
- Total: ~970 lines of production code

#### Architecture
- Object-oriented design with MetadataGenerator and MetadataValidator classes
- Modular function approach for CLI commands
- Separation of concerns: Generation, Validation, Configuration
- Flexible input/output handling
- Error handling and user-friendly messages

### Usage Examples

```bash
# Generate templates
python main.py template --count 5

# Process and enhance
python main.py process data.csv --enhance --normalize-names

# Validate
python main.py validate data.csv

# Get statistics
python main.py stats data.csv

# View schema
python main.py schema
```

### Known Limitations (v1.0.0)

1. Geographic coordinate lookup (Nominatim) disabled by default
2. No integration with name authority services (LCNAF, VIAF)
3. No support for RDF/Linked Data output
4. No built-in field customization
5. CLI-only interface (no GUI)

### Testing Status

- ✓ CLI command parsing verified
- ✓ CSV loading and export tested
- ✓ JSON loading and export tested
- ✓ Validation logic tested with sample data
- ✓ Enhancement features verified
- ✓ Statistics generation tested
- ✓ Schema display verified
- ✓ Error handling tested

### Future Roadmap

- [ ] Web interface for non-technical users
- [ ] Integration with LCNAF and VIAF authorities
- [ ] RDF/Linked Data export format
- [ ] Batch API for automated processing
- [ ] Database backend for large collections
- [ ] Automated geographic lookup via Nominatim
- [ ] Custom field support per institution
- [ ] Import templates from external sources
- [ ] Multi-language UI support
- [ ] Container (Docker) support for deployment

---

## Versioning

This project follows [Semantic Versioning](https://semver.org/):
- MAJOR version for incompatible schema/API changes
- MINOR version for new features (backwards compatible)
- PATCH version for bug fixes

Current: **1.0.0**

---

**Release Date**: April 21, 2026  
**Python Version**: 3.7+  
**Status**: Stable Release
