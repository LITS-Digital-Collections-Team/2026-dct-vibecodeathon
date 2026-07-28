# GCV OCR to PDF Pipeline

A batch processing pipeline that converts TIFF and JPEG images into searchable PDFs using Google Cloud Vision API for OCR processing. Text is overlaid on the PDF with accurate XY coordinates at the character level.

## Features

- **Google Cloud Vision OCR**: Uses Google's advanced OCR engine for accurate text recognition
- **Character-Level Positioning**: Places each character precisely using XY coordinates from GCV
- **Batch Processing**: Efficiently processes multiple images in groups
- **Multi-Format Support**: Handles TIFF (multi-frame) and JPEG images
- **Searchable PDFs**: Creates PDFs with invisible searchable text overlay
- **Debug Mode**: Optional visible red bounding boxes for verification
- **File Grouping**: Groups images by filename prefix for organized PDF output

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Set up Google Cloud Authentication:
   - Create a GCP service account with Vision API access
   - Download the service account JSON key file
   - Set environment variable: `export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json`

## Usage

### Basic Usage
```bash
python main.py \
  --input-dir ./images \
  --output-dir ./pdfs \
  --credentials-path ./service-account-key.json
```

### With Project ID
```bash
python main.py \
  --input-dir ./images \
  --output-dir ./pdfs \
  --project-id my-gcp-project
```

### Dry Run (List files without processing)
```bash
python main.py \
  --input-dir ./images \
  --output-dir ./pdfs \
  --dry-run
```

### Debug Mode (Show text bounding boxes)
```bash
python main.py \
  --input-dir ./images \
  --output-dir ./pdfs \
  --debug \
  --credentials-path ./service-account-key.json
```

### Custom Filename Split Character
```bash
python main.py \
  --input-dir ./images \
  --output-dir ./pdfs \
  --split-char '-' \
  --credentials-path ./service-account-key.json
```

## Command-Line Options

| Option | Required | Description |
|--------|----------|-------------|
| `--input-dir` | Yes | Directory containing TIFF/JPEG images |
| `--output-dir` | Yes | Directory where output PDFs will be saved |
| `--credentials-path` | No | Path to GCP service account JSON key file |
| `--project-id` | No | GCP project ID |
| `--split-char` | No | Character to split filename on for grouping (default: `_`) |
| `--debug` | No | Enable debug mode with visible text boxes |
| `--dry-run` | No | List files without processing |

## How It Works

1. **File Discovery**: Scans input directory for TIFF and JPEG images
2. **Grouping**: Splits filenames on the split character (default `_`) and groups files with the same prefix — e.g. `doc_001.tif`, `doc_002.tif`, `doc_003.tif` all become pages in `doc.pdf`
3. **OCR Processing**: For each image page (a multi-frame TIFF's frames are each OCR'd individually, since GCV only annotates one page per request):
   - Sends to Google Cloud Vision API (`document_text_detection`)
   - Extracts text with character-level bounding boxes (x/y, width, height per symbol)
4. **PDF Generation**:
   - Creates one PDF page per image page, sized in points from the image's DPI metadata (default `300` DPI if absent) so pages match their real physical size
   - Overlays invisible (`render_mode=3`), searchable text scaled to the same DPI so it lines up with the visible image
5. **Output**: Saves one PDF per image group

## Code Structure

| Symbol | File:Line | Purpose |
|---|---|---|
| `GoogleCloudVisionOCR` | `main.py:65` | Wraps the GCV client; handles auth and parses symbol-level bounding boxes |
| `TextBound` | `main.py:45` | Dataclass holding per-character coordinate data (x, y, width, height, text) |
| `TextLine` | `main.py:55` | Dataclass holding per-paragraph text and its constituent `TextBound` list |
| `group_image_files()` | `main.py:208` | Groups files by prefix before the split character |
| `load_image_pages()` | `main.py:253` | Loads every frame of a TIFF (or the single page of other formats) as PIL Images |
| `get_image_dpi()` | `main.py:270` | Reads DPI from image metadata, falling back to `DEFAULT_DPI` |
| `render_text_overlay()` | `main.py:294` | Places invisible (or debug-visible) text on a PyMuPDF page at GCV coordinates |
| `create_pdf_from_images_with_ocr()` | `main.py:325` | Orchestrates image loading → per-page OCR → PDF page creation for one group |
| `process_image_groups()` | `main.py:401` | Top-level loop over all groups; supports `--dry-run` |

## Text Overlay Precision

The pipeline captures character-level XY coordinates from Google Cloud Vision and:
- Places each character in the PDF at its detected position
- Calculates width and height based on bounding box vertices
- Uses scale factor for coordinate adjustment
- In debug mode, draws visible red boxes for verification

## Example File Structure

```
input_dir/
 document_001.tif
 document_002.tif
 document_003.tif
 scan_001.jpg
 scan_002.jpg

output_dir/
 document.pdf (contains pages from document_001.tif, document_002.tif, document_003.tif)
 scan.pdf (contains pages from scan_001.jpg, scan_002.jpg)
```

## Performance Notes

- Large batch operations may take time due to API calls
- Each image is processed sequentially through GCV
- Consider API quotas and rate limits for large batches
- Debug mode may increase processing time due to drawing operations

## Troubleshooting

### Authentication Error
- Ensure `GOOGLE_APPLICATION_CREDENTIALS` is set or `--credentials-path` is provided
- Verify service account has Vision API enabled

### No Text Detected
- Check image quality and text legibility
- Enable `--debug` mode to verify image processing
- GCV may have difficulty with very small or low-quality text

### PDF Generation Issues
- Ensure output directory exists and is writable
- Check disk space for large batches
- Verify PIL can handle image format

## License

This script was created with assistance from GitHub Copilot.
