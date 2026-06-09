# GCV OCR to PDF Architecture

## Overview

This OCR batch pipeline converts image documents (TIFF/JPEG) into searchable PDFs using Google Cloud Vision API. The key innovation is character-level coordinate-based text overlay, ensuring precise text placement using bounding box data from GCV.

## Components

### 1. GoogleCloudVisionOCR Class
Central wrapper around Google Cloud Vision API.

**Key Methods:**
- `extract_text_with_bounds()`: Sends image to GCV and returns parsed TextLine objects
- `_parse_text_annotations()`: Converts GCV response to internal data structures

**Features:**
- Supports both service account and default credentials
- Character-level bounding box extraction
- Full page annotation parsing

### 2. Data Classes

#### TextBound
Represents a single character with precise positioning:
- `text`: The character string
- `x`, `y`: Top-left coordinate
- `width`, `height`: Character dimensions

#### TextLine
Represents a line of text with collection of character bounds:
- `text`: Full line text
- `x`, `y`, `width`, `height`: Line bounding box
- `bounds`: List of TextBound objects for each character

### 3. Processing Pipeline

```
Input Images
    
 Discover TIFF/JPEG files
    
 Group by filename prefix
    
For each group:
    
    create_pdf_from_images_with_ocr()
        
        For each image:
            
 Load image
            
 Get OCR
            
 Place text in PDF
            
            Add page to document
    
    Save PDF
    
Output PDFs
```

### 4. Text Overlay Rendering

The `render_text_overlay()` function:

1. Iterates through each character in detected text
2. Calculates precise rectangle from GCV bounding box
3. For each character:
   - In debug mode: draws visible red box + text
   - In normal mode: inserts invisible searchable text overlay
4. Uses scale_factor for coordinate adjustment if needed

**Key Points:**
- Text is rendered at opacity=0 (invisible) for searchability
- Each character gets its own positioned rectangle
- PDF text search works across overlaid text
- Debug mode allows visual verification of placement

### 5. File Grouping Strategy

Groups images by filename prefix using a configurable split character:

Example with `_` as split character:
```
 document group
 document group
 document group
 report group
 report group
```

Output:
```
document.pdf (contains 3 pages)
report.pdf (contains 2 pages)
```

## Coordinate Systems

### Image Coordinates (GCV)
- Origin at top-left
- X increases right
- Y increases down
- Measured in pixels

### PDF Coordinates (PyMuPDF)
- Origin at bottom-left
- X increases right
- Y increases up
- Measured in points (72 per inch by default)

The pipeline preserves GCV coordinates as provided since the image is inserted at its native resolution.

## API Rate Limiting

Google Cloud Vision API has rate limits. For batch processing:
- Monitor API quota usage in GCP console
- Consider implementing retry logic for large batches
- Use async processing for very large datasets

## Memory Considerations

- Each image is loaded into memory as PIL Image
- PDF document accumulates in memory during processing
- For large batches (100+ pages), consider processing groups sequentially

## Performance Characteristics

| Operation | Time | Notes |
|-----------|------|-------|
| Image loading | ~10-100ms | Depends on image size |
| GCV API call | 500ms-2s | Network dependent |
| OCR parsing | ~50-200ms | Text complexity dependent |
| PDF rendering | ~100-300ms | Per image |
| Total per image | ~1-3s | With API calls |

## Error Handling

Robust error handling throughout:
- API errors caught and reported
- Missing credentials detected early
- Image loading failures skip to next image
- Partial PDFs saved if some images fail
- Full stack traces in debug output

## Future Enhancements

1. **Async API Calls**: Process multiple images in parallel
2. **Batch Vision API**: Use Vision API batch endpoint for cost savings
3. **Language-Specific Handling**: Support for multiple OCR languages
4. **Layout Preservation**: Maintain document structure in PDF
5. **Confidence Scoring**: Include OCR confidence in metadata
6. **Custom Page Formatting**: User-defined PDF layouts
7. **Incremental Processing**: Resume partially completed batches
