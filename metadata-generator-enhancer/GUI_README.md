# GUI Interface Documentation

## Running the GUI

You have two options to launch the windowed GUI interface:

### Option 1: Using the Launcher Script
```bash
python gui_launcher.py
```

### Option 2: Using the CLI
```bash
python main.py gui
```

## GUI Features

### 1. **File Upload**
   - Click "Browse CSV/JSON" to select your input metadata file
   - The interface will automatically load and count the records

### 2. **Output Directory**
   - Click "Choose Output Directory" to set where results will be saved
   - Defaults to `./output`

### 3. **Processing Options**

   **Output Format:**
   - CSV - Export to CSV format only
   - JSON - Export to JSON format only
   - Both CSV & JSON - Generate both formats (recommended)

   **Processing Checkboxes:**
   - **Enhance records** - Automatically fill default values and clean up data
   - **Normalize names** - Apply name normalization for people and organizations
   - **Validate records** - Check records against Archipelago schema

### 4. **Template Generation**
   - Specify the number of blank templates to create
   - Click "📋 Generate Template" to create empty JSON metadata templates
   - Perfect for starting new metadata from scratch

### 5. **Action Buttons**

   | Button | Function |
   |--------|----------|
   | **📋 Generate Template** | Create blank metadata templates for manual entry |
   | **⚙️ Process File** | Convert, enhance, and export your metadata file |
   | **✓ Validate File** | Check records against the Archipelago schema |
   | **🗂️ Open Output Folder** | Open the output directory in your file browser |

### 6. **Status & Results**
   - Real-time log of all operations
   - Color-coded messages:
     - 🟢 Green = Success
     - 🔴 Red = Error
     - 🔵 Blue = Information
     - 🟠 Orange = Warning

## Workflow Example

1. **Start**: Click "Browse CSV/JSON" and select your metadata file
2. **Configure**: Choose output format and processing options
3. **Process**: Click "⚙️ Process File" to convert and enhance
4. **View**: Check the log for results and validation summary
5. **Export**: Click "🗂️ Open Output Folder" to find your processed files

## Supported File Formats

### Input
- **CSV** (.csv) - Comma-separated values with headers
- **JSON** (.json) - Array of metadata objects

### Output
- **CSV** (.csv) - Compatible with Archipelago import
- **JSON** (.json) - Full structured metadata

## Tips

- **Validation** helps identify problems before ingestion
- **Enhance records** automatically fills common fields with defaults
- **Normalize names** cleans up inconsistent name formatting
- Generate templates to understand the metadata structure
- Check the status log for detailed feedback on each operation

## Troubleshooting

**Issue: "No file selected" message**
- Click the "Browse CSV/JSON" button and select a valid file

**Issue: Validation shows many errors**
- Review the error details in the log
- Check that all required fields are present in your data

**Issue: GUI doesn't launch**
- Ensure Python 3.7+ is installed
- Run from the same directory as the Python files
- Check that tkinter is available (usually built-in)

## Advanced Usage

For command-line processing without the GUI:
```bash
python main.py process input.csv --enhance --normalize-names
python main.py validate input.json
python main.py template --count 5
```

See `python main.py --help` for all CLI options.
