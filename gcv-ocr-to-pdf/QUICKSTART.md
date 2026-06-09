# Quick Start Guide

## 1. Setup

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Configure Google Cloud Vision

#### Option A: Service Account File
```bash
# Download JSON key from GCP Console
 Create new key

export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
```

#### Option B: Application Default Credentials (ADC)
```bash
# If already authenticated locally
gcloud auth application-default login
```

## 2. Prepare Images

Organize your images by grouping:
```
input_images/
 document_001.tif
 document_002.tif
 document_003.tif
 report_001.jpg
 report_002.jpg
```

With `_` as split character (default):
 becomes `document.pdf` (3 pages)
 becomes `report.pdf` (2 pages)

## 3. Run the Pipeline

### Basic Processing
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs \
  --credentials-path ./service-account-key.json
```

### With Custom Split Character
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs \
  --split-char '-' \
  --credentials-path ./service-account-key.json
```

### Preview Without Processing (Dry Run)
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs \
  --dry-run
```

### Debug Mode (Show Text Boxes)
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs \
  --debug \
  --credentials-path ./service-account-key.json
```

## 4. Output

Searchable PDFs will be created in `output_pdfs/`:
```
output_pdfs/
 document.pdf
 report.pdf
```

Each PDF:
- Contains all grouped images as pages
- Has invisible searchable text overlay
- Allows text selection and copying
- Shows accurate OCR placement via GCV coordinates

## 5. Verify Results

### Test Text Search
1. Open PDF in your PDF reader
2. Use Ctrl+F (or Cmd+F) to search
3. Text should be found and highlighted

### Check Accuracy (Debug Mode)
1. Run with `--debug` flag
2. Open debug PDF
3. Red boxes show detected text bounds
4. Compare against original image

## 6. Troubleshooting

### "No text detected"
- Check image quality
- Ensure text is legible (OCR works on printed text)
- Try with higher resolution images

### Authentication errors
- Verify credentials file path
- Check GCP project has Vision API enabled
- Ensure service account has appropriate roles

### API quota exceeded
- Check GCP Console for quotas
- Wait for quota reset
- Consider batch processing smaller groups

## 7. Performance Tips

- **Large batches**: Process in smaller groups to manage memory
- **API costs**: Monitor usage in GCP Console
- **Speed**: Each image takes ~1-3 seconds (mostly API latency)
- **Output size**: PDFs scale with number of pages and image resolution

## 8. Advanced Usage

See `ARCHITECTURE.md` for:
- Component details
- Coordinate system information
- Performance characteristics
- Future enhancement ideas
