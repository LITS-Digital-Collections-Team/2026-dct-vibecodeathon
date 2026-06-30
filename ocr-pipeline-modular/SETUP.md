# OCR Pipeline Quick Start Guide

## Installation (5 minutes)

### 1. Prerequisites

Ensure you have Python 3.8+ installed:
```bash
python3 --version
```

### 2. Install System Dependencies

**macOS:**
```bash
brew install tesseract
```

**Ubuntu/Debian:**
```bash
sudo apt-get install tesseract-ocr libtesseract-dev
```

**Windows:**
- Download from: https://github.com/UB-Mannheim/tesseract/wiki

### 3. Install Python Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 4. (Optional) Configure API Keys

For advanced features like Claude corrections:

```bash
# Copy example config
cp .env.example .env

# Edit .env and add your API keys
nano .env
```

## Quick Test

Run the module test to verify installation:

```bash
python3 -c 'from utils import CharBound, TextBlock, OCROutput; print("✓ All modules loaded successfully")'
```

## Basic Usage

### Step 1: Prepare Images

```bash
# Single file
python3 01_image_prep.py --input document.tiff --output-dir ./prep_output

# Multiple files
python3 01_image_prep.py --input-dir ./images --output-dir ./prep_output
```

Output: Optimized JPG images in `./prep_output/`

### Step 2: Extract Text

```bash
# Using Tesseract (recommended, no API key needed)
python3 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output

# Or with Google Cloud Vision
python3 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output --engine gcv
```

Output: OCR JSON files with coordinates in `./ocr_output/`

### Step 3: Correct Text (Optional)

Requires `ANTHROPIC_API_KEY` environment variable:

```bash
# Auto-correct low-confidence blocks
python3 03_text_correct.py --input-dir ./ocr_output --output-dir ./corrected_output --auto

# Interactive review
python3 03_text_correct.py --input-dir ./ocr_output --output-dir ./corrected_output --interactive
```

Output: Corrected OCR JSON in `./corrected_output/`

### Step 4: Create Searchable PDF

```bash
python3 04_pdf_assemble.py \
  --image-dir ./prep_output \
  --ocr-dir ./corrected_output \
  --output-dir ./pdf_output
```

Output: Searchable PDFs in `./pdf_output/`

## Example: Complete Pipeline

```bash
# Prepare images
python3 01_image_prep.py --input-dir ./raw_images --output-dir ./prep_output

# Extract text
python3 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output

# Skip correction if no API key, or correct
python3 03_text_correct.py --input-dir ./ocr_output --output-dir ./corrected_output --auto

# Create PDFs
python3 04_pdf_assemble.py \
  --image-dir ./prep_output \
  --ocr-dir ./corrected_output \
  --output-dir ./pdf_output

# Verify output
ls -lh pdf_output/
```

## Help & Documentation

Each script has built-in help:

```bash
python3 01_image_prep.py --help
python3 02_ocr_extract.py --help
python3 03_text_correct.py --help
python3 04_pdf_assemble.py --help
```

For detailed documentation, see `README.md`

## Troubleshooting

### "pytesseract: Pytesseract is not installed or it is not in your PATH"

Install Tesseract:
- macOS: `brew install tesseract`
- Ubuntu: `sudo apt-get install tesseract-ocr`
- Windows: Download installer from GitHub

### ImportError: No module named 'PIL'

```bash
pip install Pillow
```

### ImportError: No module named 'anthropic'

```bash
pip install anthropic
```

### API Key Errors

Verify environment variable is set:
```bash
# Should print your API key
echo $ANTHROPIC_API_KEY

# Or check .env file exists and is loaded
cat .env
```

## Performance Tips

1. **Batch processing is fastest** - Use `--input-dir` when possible
2. **Skip Step 3 for speed** - Text correction is optional
3. **Tesseract is faster** - Use default engine unless you need better accuracy
4. **Resize large images** - Use `--max-width` in Step 1 to optimize
5. **Use confidence thresholds** - In Step 3, increase `--threshold` to skip easy corrections

## File Organization

Recommended directory structure:

```
project/
├── raw_images/          # Original TIFF files
├── prep_output/         # Step 1: Optimized JPG images
├── ocr_output/          # Step 2: OCR extraction results
├── corrected_output/    # Step 3: Corrected text (optional)
└── pdf_output/          # Step 4: Final searchable PDFs
```

## Architecture Overview

```
TIFF → [Step 1] → JPG → [Step 2] → JSON (with coordinates)
                                         ↓
                                    [Step 3] → JSON (corrected)
                                         ↓
                                    [Step 4] → Searchable PDF
```

Each step:
- Is independent and can be run separately
- Saves intermediate JSON for review/editing
- Has comprehensive error handling
- Supports both single file and batch modes
- Includes detailed logging

## Next Steps

1. Read the full `README.md` for detailed documentation
2. Check individual script help: `python3 XX_*.py --help`
3. Review the `utils.py` file for data structure details
4. Explore the JSON outputs to understand the data flow
