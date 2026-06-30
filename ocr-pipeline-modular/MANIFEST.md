# OCR Pipeline - Project Manifest

## Overview
Production-grade modular OCR pipeline with 4 independent steps for converting document images to searchable PDFs.

## Project Structure

### Core Modules

1. **utils.py** (180 lines, 8KB)
   - Shared data classes and utilities
   - Classes: CharBound, TextBlock, OCROutput, OCRDataHandler
   - Functions: ensure_dir, get_output_filename, validate_image_path, setup_logging
   - Handles JSON serialization/deserialization of OCR data

2. **01_image_prep.py** (226 lines, 8KB)
   - Image preparation and optimization
   - Converts TIFF to optimized JPG
   - Resizes to max width while preserving aspect ratio
   - Batch processing support
   - Saves preparation metadata

3. **02_ocr_extract.py** (414 lines, 16KB)
   - Text extraction with coordinates
   - Supports Tesseract (local) and Google Cloud Vision (API)
   - Character-level bounding boxes
   - Confidence scores
   - Batch processing with dry-run mode

4. **03_text_correct.py** (339 lines, 12KB)
   - Text correction using Claude API
   - Automatic correction of low-confidence blocks
   - Interactive manual review mode
   - Confidence threshold filtering
   - Batch processing pipeline

5. **04_pdf_assemble.py** (368 lines, 16KB)
   - Searchable PDF creation
   - Overlays corrected text at original coordinates
   - Debug mode with visible bounding boxes
   - PDF merging support
   - Batch processing

### Configuration & Documentation

- **requirements.txt** (4KB)
  - All Python dependencies with version constraints
  - Optional dependencies for API features

- **README.md** (406 lines, 12KB)
  - Complete architecture documentation
  - Installation and setup instructions
  - Detailed usage examples for each step
  - Troubleshooting guide
  - Module reference

- **SETUP.md** (5KB)
  - Quick start guide (5 minutes)
  - Practical examples
  - Common troubleshooting
  - Performance tips

- **.env.example** (4KB)
  - Configuration template
  - API key placeholders
  - Tesseract path configuration

- **MANIFEST.md** (this file)
  - Project overview
  - File structure
  - Statistics

### Testing

- **test_imports.py** (48 lines, 4KB)
  - Module import verification
  - Data class instantiation tests
  - Serialization/deserialization tests

## Statistics

- **Total Lines**: 1,981 (Python code only, excluding tests)
- **Total Size**: 84 KB (all files including documentation)
- **Python Files**: 5 + 1 test
- **Documentation Files**: 3
- **Configuration Files**: 2

## Features

### Step 1: Image Preparation
 Single file and batch processing- 
 Multi-frame TIFF support- 
 Configurable resize dimensions- 
 JPEG quality control- 
 Metadata saving- 
 Error handling and logging- 

### Step 2: OCR Extraction
 Tesseract OCR (default, no API needed)- 
 Google Cloud Vision (optional, API-based)- 
 Character-level coordinate extraction- 
 Confidence scoring- 
 Batch processing- 
 Dry-run mode for testing- 

### Step 3: Text Correction
 Claude API integration- 
 Automatic correction mode- 
 Interactive review mode- 
 Confidence-based filtering- 
 Batch processing- 
 Correction history tracking- 

### Step 4: PDF Assembly
 Searchable PDF creation- 
 Invisible text layer- 
 Original image preservation- 
 Coordinate-based text placement- 
 Debug bounding boxes- 
 PDF merging- 
 Batch processing- 

## Data Flow

```
Input: TIFF/Image File
         
    [Step 1]
         
    JPG + Metadata
         
    [Step 2]
         
    JSON (OCR with coordinates)
         
    [Step 3] (optional)
         
    JSON (corrected)
         
    [Step 4]
         
Output: Searchable PDF
```

## Command-Line Interface

All scripts use argparse with:
- Comprehensive --help documentation
- Single file and batch modes
- Verbose logging support
- Error handling and validation
- Configuration options

## Data Structures

### CharBound
- char: str
- x, y, width, height: float
- confidence: float (0-1)

### TextBlock
- text: str
- x, y, width, height: float
- chars: List[CharBound]
- source: str ("ocr" or "corrected")
- confidence: float (0-1)

### OCROutput
- image_path: str
- dimensions: Dict[width, height]
- blocks: List[TextBlock]
- engine: str ("tesseract" or "gcv")
- metadata: Dict[str, Any]

## Dependencies

### Required
- Pillow (image processing)
- pymupdf (PDF creation)
- pytesseract (Tesseract interface)

### Optional
- google-cloud-vision (GCV engine)
- anthropic (Claude corrections)
- python-dotenv (configuration)

## Production Features

 Comprehensive error handling- 
 Structured logging- 
 Input validation- 
 Type hints- 
 Documentation strings- 
 Graceful degradation- 
 Intermediate JSON outputs- 
 Batch processing- 
 Manual review capabilities- 
 Debug modes- 

## API Requirements

### Tesseract (Step 2, default)
- No API key required
- Requires system installation
- Faster but less accurate

### Google Cloud Vision (Step 2, optional)
- Requires `GOOGLE_CLOUD_API_KEY`
- API-based (network required)
- More accurate, slower

### Claude (Step 3, optional)
- Requires `ANTHROPIC_API_KEY`
- API-based (network required)
- Automatic text correction

## Scalability

- Handles single images and batch directories
- Intermediate JSON outputs allow resumption
- Memory efficient (processes one image at a time)
- Supports dry-run mode for testing

## Future Enhancements

Possible extensions:
- Character-level correction
- Multiple OCR engines in parallel
- Incremental processing with caching
- Web UI for interactive review
- Multi-page PDF support
- Language-specific customization
- Performance optimization for high-volume

## License & Attribution

Part of LITS-Digital-Collections-Team 2026-dct-vibecodeathon project.

## Support

For detailed help, use built-in documentation:
```bash
python3 01_image_prep.py --help
python3 02_ocr_extract.py --help
python3 03_text_correct.py --help
python3 04_pdf_assemble.py --help
```

See README.md for comprehensive documentation.
