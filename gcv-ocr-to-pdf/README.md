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
 `document`)
3. **OCR Processing**: For each image:
   - Sends to Google Cloud Vision API
   - Extracts text with character-level bounding boxes
4. **PDF Generation**: 
   - Creates PDF with image as background
   - Overlays invisible searchable text at character positions
   - Ensures text placement matches detected coordinates
5. **Output**: Saves one PDF per image group

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
