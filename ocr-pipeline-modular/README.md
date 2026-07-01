# Modular OCR Pipeline

A production-grade, modular OCR pipeline that converts document images to searchable PDFs. The pipeline is divided into 4 independent steps, allowing for review and manual intervention between stages.

## Architecture Overview

```
Step 1: Image Preparation          Step 2: OCR Extraction
TIFF → JPG (optimized)             Image → Text + Coordinates
        ↓                                    ↓
   prep_output/                       ocr_output/
   └─ image_prep.json                 └─ image_ocr.json
   
Step 3: Text Correction             Step 4: PDF Assembly
OCR JSON → Claude Review            Image + OCR → Searchable PDF
        ↓                                    ↓
   corrected_output/                   pdf_output/
   └─ image_ocr_corrected.json        └─ image_searchable.pdf
```

### Data Flow

1. **Image Preparation** - Convert TIFF/RAW images to optimized JPG format
   - Handles multi-frame TIFFs
   - Resizes to max width (preserves aspect ratio)
   - Saves metadata for downstream steps
   - Output: JPG images + JSON metadata

2. **OCR Extraction** - Extract text with character-level coordinates
   - Default "auto" mode runs Tesseract (local, no API key) first and only
     escalates to Google Cloud Vision (API) when Tesseract's confidence is
     below threshold — keeps the common case free and local
   - Can also be forced to always use Tesseract or always use GCV
   - Returns text blocks with exact pixel coordinates
   - Includes confidence scores
   - Output: JSON with full OCR data including character bounds

3. **Text Correction** - Enhance low-confidence text using Claude
   - Identifies blocks below confidence threshold
   - Optionally sends to Claude for automatic correction
   - Supports interactive manual review mode
   - Output: Corrected JSON with source annotations

4. **PDF Assembly** - Create searchable PDF with invisible text layer
   - Overlays corrected text at original coordinates
   - Creates searchable/selectable PDF
   - Optional debug mode with visible bounding boxes
   - Output: Searchable PDF

## Installation

### Prerequisites

- Python 3.8+
- Tesseract OCR (for local OCR engine)
- System libraries for image processing

### System Setup

**macOS:**
```bash
brew install tesseract
brew install tesseract-lang  # For additional languages
```

**Ubuntu/Debian:**
```bash
sudo apt-get install tesseract-ocr
sudo apt-get install libtesseract-dev
```

**Windows:**
- Download installer from: https://github.com/UB-Mannheim/tesseract/wiki
- Add to PATH

### Python Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install required packages
pip install -r requirements.txt
```

### Optional: API Keys

For advanced features, set up API keys:

```bash
# Claude API (for Step 3 text correction)
export ANTHROPIC_API_KEY="sk-ant-..."

# Google Cloud Vision (for alternative OCR in Step 2)
export GOOGLE_CLOUD_API_KEY="your-api-key"

# Or create .env file
cp .env.example .env
# Edit .env with your API keys
```

## Usage

### Quick Start

```bash
# Step 1: Prepare images
python 01_image_prep.py --input-dir ./raw_images --output-dir ./prep_output

# Step 2: Extract text (auto: Tesseract first, GCV only if confidence is low)
python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output

# Step 3: Correct text
python 03_text_correct.py --input-dir ./ocr_output --output-dir ./corrected_output --auto

# Step 4: Create PDFs
python 04_pdf_assemble.py --image-dir ./prep_output --ocr-dir ./corrected_output --output-dir ./pdf_output
```

### Detailed Usage

#### Step 1: Image Preparation

Convert TIFF images to optimized JPG format:

```bash
# Single file
python 01_image_prep.py --input document.tiff --output-dir ./prep_output

# Batch processing
python 01_image_prep.py --input-dir ./raw_images --output-dir ./prep_output

# Custom settings
python 01_image_prep.py --input-dir ./raw_images --output-dir ./prep_output \
  --max-width 1200 --quality 90

# Help
python 01_image_prep.py --help
```

**Output:**
- `image_prep.jpg` - Optimized image
- `image_metadata.json` - Preparation metadata (dimensions, scale factor)
- `batch_metadata.json` - Batch processing summary

#### Step 2: OCR Extraction

Extract text with coordinates using Tesseract, Google Cloud Vision, or an
auto cascade of both:

```bash
# Auto cascade (default): try Tesseract first, escalate to GCV only if
# Tesseract's average confidence is below --confidence-threshold (0.75)
python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output

# Auto cascade with a stricter threshold (escalates to GCV more often)
python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output \
  --engine auto --confidence-threshold 0.85

# Force Tesseract only, never call GCV
python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output --engine tesseract

# Force Google Cloud Vision for every image
python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output --engine gcv

# Dry run (extract without saving)
python 02_ocr_extract.py --input image.jpg --output-dir ./ocr_output --dry-run

# Verbose output
python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output --verbose

# Help
python 02_ocr_extract.py --help
```

**How auto cascade works:**
1. Run Tesseract locally (free, no network call)
2. Compute the average confidence across detected text blocks (word-level
   confidences averaged per block, then averaged across blocks)
3. If confidence ≥ `--confidence-threshold` (default `0.75`), keep the
   Tesseract result
4. Otherwise, call Google Cloud Vision and use its result instead
5. If GCV is unavailable (no credentials/library) when escalation is
   needed, the Tesseract result is kept and the failure is logged rather
   than aborting the batch

Each output JSON's `metadata` includes `cascade_decision`
(`tesseract_accepted`, `gcv_fallback`, or `gcv_fallback_failed`) and
`tesseract_confidence`, so you can audit which engine actually produced
each file. A per-run summary (`Cascade summary: N/M resolved by Tesseract, ...`)
is logged after batch processing.

**Output:**
- `image_ocr.json` - Full OCR data with character-level coordinates

**JSON Structure:**
```json
{
  "image_path": "image.jpg",
  "dimensions": {"width": 1000, "height": 1200},
  "engine": "tesseract",
  "blocks": [
    {
      "text": "Sample text",
      "x": 100,
      "y": 50,
      "width": 300,
      "height": 20,
      "confidence": 0.95,
      "chars": [
        {"char": "S", "x": 100, "y": 50, "width": 12, "height": 20, "confidence": 0.98}
      ]
    }
  ]
}
```

#### Step 3: Text Correction

Enhance low-confidence OCR text using Claude API:

```bash
# Automatic correction (uses Claude)
python 03_text_correct.py --input-dir ./ocr_output --output-dir ./corrected_output --auto

# Interactive mode (review each correction)
python 03_text_correct.py --input-dir ./ocr_output --output-dir ./corrected_output --interactive

# Custom confidence threshold
python 03_text_correct.py --input-dir ./ocr_output --output-dir ./corrected_output \
  --threshold 0.7 --auto

# Single file
python 03_text_correct.py --input image_ocr.json --output-dir ./corrected_output --auto

# Help
python 03_text_correct.py --help
```

**Options:**
- `--threshold` (0-1): Only correct blocks below this confidence (default: 0.8)
- `--auto`: Automatically apply Claude corrections
- `--interactive`: Manually review each correction

**Required:**
- `ANTHROPIC_API_KEY` environment variable set

#### Step 4: PDF Assembly

Create searchable PDF from original image and corrected OCR text:

```bash
# Single image + OCR file
python 04_pdf_assemble.py --image image.jpg --ocr image_ocr.json --output output.pdf

# Batch processing
python 04_pdf_assemble.py --image-dir ./images --ocr-dir ./corrected_output \
  --output-dir ./pdf_output

# Debug mode (show text bounding boxes)
python 04_pdf_assemble.py --image-dir ./images --ocr-dir ./corrected_output \
  --output-dir ./pdf_output --debug

# Merge all PDFs into single document
python 04_pdf_assemble.py --image-dir ./images --ocr-dir ./corrected_output \
  --output-dir ./pdf_output --merge-output combined.pdf

# Help
python 04_pdf_assemble.py --help
```

## Configuration

### .env File

Create `.env` file in the pipeline directory:

```env
# Claude API for text correction
ANTHROPIC_API_KEY=sk-ant-...

# Google Cloud Vision API
GOOGLE_CLOUD_API_KEY=your-api-key

# Tesseract path (if not in PATH)
TESSERACT_CMD=/usr/bin/tesseract
```

## Module Reference

### utils.py

Shared utilities and data classes:

- **CharBound** - Single character with bounding box
- **TextBlock** - Text block with coordinates and character bounds
- **OCROutput** - Complete OCR output with metadata
- **OCRDataHandler** - Save/load OCR data as JSON
- **Helper functions** - ensure_dir, get_output_filename, validate_image_path, setup_logging

### 01_image_prep.py

Image preparation and optimization:

- **ImagePreparator** - Process TIFF/image files
  - `prepare_image()` - Process single image
  - `process_batch()` - Process directory

### 02_ocr_extract.py

Text extraction with coordinates:

- **TesseractOCR** - Local Tesseract engine
- **GoogleCloudVisionOCR** - Google Cloud Vision API
- **OCRExtractor** - Unified interface

### 03_text_correct.py

Text correction and enhancement:

- **TextCorrector** - Claude-based text correction
- **TextCorrectionPipeline** - Batch processing pipeline

### 04_pdf_assemble.py

Searchable PDF creation:

- **PDFAssembler** - Create searchable PDF
- **PDFMerger** - Merge multiple PDFs

## Advanced Usage

### Custom OCR Pipeline

```python
from utils import OCRDataHandler, ensure_dir
from pathlib import Path

# Load OCR output from Step 2
ocr_output = OCRDataHandler.load_json(Path("ocr_output.json"))

# Modify blocks
for block in ocr_output.blocks:
    block.text = block.text.upper()

# Save modified output
OCRDataHandler.save_json(ocr_output, Path("modified_ocr.json"))
```

### Integrate with Existing Workflow

Each step is independent and can be integrated into existing workflows:

```python
from pathlib import Path
from image_prep import ImagePreparator

# Prepare single image
preparator = ImagePreparator()
metadata = preparator.prepare_image(
    Path("input.tiff"),
    Path("./output")
)
print(f"Prepared image: {metadata['output_path']}")
```

## Troubleshooting

### Tesseract Not Found

```bash
# Install Tesseract
brew install tesseract  # macOS
sudo apt-get install tesseract-ocr  # Ubuntu

# Or set TESSERACT_CMD environment variable
export TESSERACT_CMD=/path/to/tesseract
```

### Low OCR Confidence

- Check image quality and resolution
- Try resizing to higher dimensions in Step 1
- Use `--debug` in Step 4 to visualize bounding boxes
- Manually review with `--interactive` in Step 3

### Claude API Errors

```bash
# Verify API key is set
echo $ANTHROPIC_API_KEY

# Test API access
curl https://api.anthropic.com/v1/messages \
  -H "api-key: $ANTHROPIC_API_KEY" \
  -H "content-type: application/json"
```

### PDF Generation Issues

- Ensure image file exists and is readable
- Check OCR JSON format matches expected schema
- Use `--debug` flag to visualize text placement
- Check file permissions in output directory

## Performance Tips

1. **Parallel Processing** - Process multiple images in parallel using external tools
2. **Batch Operations** - Use batch mode for efficiency over single-file mode
3. **Confidence Thresholds** - Adjust threshold in Step 3 to skip unnecessary corrections
4. **Image Resolution** - Balance between quality and processing time in Step 1
5. **Tesseract vs GCV** - Tesseract is faster but less accurate; GCV is slower but more reliable

## Limitations

- Multi-page PDF support requires separate images per page
- Character-level corrections not currently supported (block-level only)
- PDF text layer uses approximate positioning (±5 pixels)
- Large images (>5000px) may require preprocessing

## License

This OCR pipeline is part of the LITS-Digital-Collections-Team 2026-dct-vibecodeathon project.

## Support

For issues or questions, please check the detailed help for each script:

```bash
python 01_image_prep.py --help
python 02_ocr_extract.py --help
python 03_text_correct.py --help
python 04_pdf_assemble.py --help
```
