# GCV OCR to PDF Pipeline - Usage Examples

## Example 1: Basic Batch Processing

**Scenario**: You have 10 TIFF images named `document_001.tif` through `document_010.tif` that you want to convert to a single searchable PDF.

**Setup**:
```bash
mkdir -p input_images output_pdfs
cp document_*.tif input_images/
```

**Command**:
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs \
  --credentials-path ./service-account-key.json
```

**Result**:
- One PDF: `document.pdf` with 10 pages
- Each page is searchable with overlaid OCR text
- File grouping based on `_` prefix (document)

---

## Example 2: Multiple Document Groups

**Scenario**: You have multiple document types that should be split into separate PDFs.

**File structure**:
```
input_images/
 invoice_001.tif
 invoice_002.tif
 invoice_003.tif
 receipt_001.jpg
 receipt_002.jpg
 report_2026_001.tif
```

**Command**:
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs \
  --credentials-path ./service-account-key.json
```

**Result**:
- `invoice.pdf` (3 pages)
- `receipt.pdf` (2 pages)
- `report.pdf` (1 page)

---

## Example 3: Custom Grouping Character

**Scenario**: Your files use hyphens instead of underscores.

**File structure**:
```
input_images/
 scan-001.tif
 scan-002.tif
 memo-001.jpg
 memo-002.jpg
```

**Command**:
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs \
  --split-char '-' \
  --credentials-path ./service-account-key.json
```

**Result**:
- `scan.pdf` (2 pages)
- `memo.pdf` (2 pages)

---

## Example 4: Preview Before Processing (Dry Run)

**Scenario**: You want to see what will be processed before actually running OCR.

**Command**:
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs \
  --dry-run
```

**Output**:
```
Found 10 image files
Grouped into 2 groups
  document: 7 files
  archive: 3 files
```

No files are processed, no API calls made.

---

## Example 5: Debug Mode - Verify Text Placement

**Scenario**: You want to verify that OCR text is being placed accurately.

**Command**:
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs \
  --debug \
  --credentials-path ./service-account-key.json
```

**What happens**:
- Each character gets a red bounding box
- Text labels show detected characters
- Helps verify GCV detection accuracy
- Creates regular searchable PDFs + visual verification

**Use case**: Before processing large batches, test with debug mode to ensure accuracy.

---

## Example 6: Using Environment Variable for Credentials

**Scenario**: You want to avoid passing credentials on command line.

**Setup**:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=./service-account-key.json
```

**Command**:
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs
```

No `--credentials-path` needed - uses environment variable instead.

---

## Example 7: Application Default Credentials

**Scenario**: You're already authenticated with `gcloud`.

**Setup**:
```bash
gcloud auth application-default login
```

**Command**:
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs
```

No credentials file needed - uses default GCP authentication.

---

## Example 8: Large Batch Processing

**Scenario**: You have 500 images to process in multiple groups.

**File structure**:
```
input_images/
 archive_001.tif
 archive_002.tif
 ... (250 archive files)
 legal_001.jpg
 legal_002.jpg
 ... (250 legal files)
```

**Command**:
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs \
  --credentials-path ./service-account-key.json
```

**Expected timing**:
- 500 images  2 seconds each = ~16 minutes
- Mostly network latency (GCV API)
- Memory usage: 100-200MB
- Output: 2 large PDFs

**Optimization tips**:
- Monitor GCP quota in console
- Process during off-peak hours
- Consider splitting into smaller batches if quota issues

---

## Example 9: Mixed Format Images

**Scenario**: You have both TIFF and JPEG images.

**File structure**:
```
input_images/
 scan_001.tif
 scan_002.tif
 scan_003.jpg
 scan_004.jpg
 scan_005.jpg
```

**Command**:
```bash
python main.py \
  --input-dir ./input_images \
  --output-dir ./output_pdfs \
  --credentials-path ./service-account-key.json
```

**Result**:
- `scan.pdf` (5 pages)
- Mixed TIFF/JPEG formats handled automatically
- Pipeline converts all to PNG internally for processing

---

## Example 10: Incremental Processing

**Scenario**: You processed 100 documents yesterday and have 50 new ones today.

**Command for today**:
```bash
python main.py \
  --input-dir ./today_images \
  --output-dir ./today_pdfs \
  --credentials-path ./service-account-key.json
```

**Result**:
- Yesterday's PDFs remain untouched
- New PDFs created in today's output directory
- Can be combined later if needed

---

## Example 11: Different Output Directory

**Scenario**: Organize outputs by date/project.

**Commands**:
```bash
# Monday batch
python main.py \
  --input-dir ./monday_images \
  --output-dir ./output_2026-06-08 \
  --credentials-path ./creds.json

# Tuesday batch
python main.py \
  --input-dir ./tuesday_images \
  --output-dir ./output_2026-06-09 \
  --credentials-path ./creds.json
```

**Result**:
- Organized by date: `output_2026-06-08/`, `output_2026-06-09/`
- Easy to track which PDFs were generated when

---

## Example 12: Testing with Sample Image

**Scenario**: First time setup - test with one image before processing batch.

**Setup**:
```bash
mkdir -p test_input test_output
cp sample_image.tif test_input/
```

**Command**:
```bash
python main.py \
  --input-dir ./test_input \
  --output-dir ./test_output \
  --debug \
  --credentials-path ./service-account-key.json
```

**Result**:
- Verifies credentials work
- Tests OCR accuracy with debug boxes
- Confirms output format
- One small PDF to review

---

## Troubleshooting Examples

### Problem: "Authentication Error"

**Test command**:
```bash
python main.py \
  --input-dir ./test_input \
  --output-dir ./test_output \
  --dry-run
```

This runs without API calls. If it fails, credentials aren't the issue.

### Problem: "No Text Detected"

**Debug command**:
```bash
python main.py \
  --input-dir ./low_quality_images \
  --output-dir ./output \
  --debug \
  --credentials-path ./creds.json
```

The `--debug` flag shows red boxes where text was detected. If no boxes, image quality is issue.

### Problem: "API Quota Exceeded"

**Solution**: Process in smaller batches

```bash
# Create subdirectories by date
python main.py --input-dir ./batch1 --output-dir ./pdf_batch1 ...
# Wait or check quota
python main.py --input-dir ./batch2 --output-dir ./pdf_batch2 ...
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Basic run | `python main.py --input-dir in --output-dir out --credentials-path creds.json` |
| Preview | `python main.py --input-dir in --output-dir out --dry-run` |
| Debug | `python main.py --input-dir in --output-dir out --debug --credentials-path creds.json` |
| Custom split | `python main.py --input-dir in --output-dir out --split-char '-' --credentials-path creds.json` |
| Help | `python main.py --help` |

