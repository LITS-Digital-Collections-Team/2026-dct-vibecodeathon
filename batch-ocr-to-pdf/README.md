# Surya OCR Batch Script

This script batches TIFF files, applies OCR, and creates searchable PDF output.
It supports two OCR engines:

- **Surya** (preferred when available)
- **Tesseract** (fallback or explicit option)

It also supports grouped output based on filename prefixes and optional debug validation PDFs.

> Script and documentation were created with assistance from GitHub Copilot.

## Features

- Group TIFF files by filename prefix and write one PDF per group
- Create searchable PDFs with invisible text overlay
- Optional validation PDFs with visible OCR boxes/text
- Supports Surya predictor API and legacy Surya model API
- Auto fallback from Surya to Tesseract when needed
- Supports `--checkpoint`, `--device`, and `--engine` CLI options

## Requirements

- Python 3.10+ (or compatible with installed packages)
- `torch`
- `Pillow`
- `tqdm`
- `PyMuPDF`
- `surya-ocr` (optional for Surya OCR)
- `pytesseract` and Tesseract executable (if using Tesseract)

## Installation

```powershell
python -m pip install torch pillow tqdm pymupdf
python -m pip install surya-ocr
python -m pip install pytesseract
```

For Tesseract on Windows:

1. Download and install Tesseract from https://github.com/tesseract-ocr/tesseract
2. Add the Tesseract install folder (for example `C:\Program Files\Tesseract-OCR`) to `PATH`
3. Verify with:

```powershell
tesseract --version
```

## Usage

```powershell
python surya_ocr.py <input_dir> [--output <dir>] [--logs <dir>] [--engine <surya|tesseract|auto>] [--checkpoint <path>] [--device <cpu|cuda|mps>] [--debug] [--validation-dir <dir>] [--nodry]
```

### Example

```powershell
python surya_ocr.py "C:\Users\khoffman\Documents\TIFFs" --engine auto --output "C:\Users\khoffman\Documents\PDFs" --debug
```

## CLI Options

- `input` - Directory containing TIFF files
- `--output` - Directory for output PDFs (`./output_pdfs` by default)
- `--logs` - Directory for OCR text logs (`./ocr_logs` by default)
- `--char` - Split character used to group filenames (`_` by default)
- `--device` - Force Surya device: `cpu`, `cuda`, or `mps`
- `--checkpoint` - Override the Surya foundation checkpoint path or S3 URL
- `--engine` - OCR backend: `surya`, `tesseract`, or `auto`
- `--debug` - Produce validation PDFs with visible overlay boxes and text
- `--validation-dir` - Directory for debug validation PDFs (`./validation_pdfs` by default)
- `--nodry` - Skip the confirmation prompt and proceed immediately

## Notes

- By default the script prompts before starting OCR, showing the number of PDFs and pages to process.
- `--nodry` skips that prompt.
- `--engine auto` attempts Surya first, then falls back to Tesseract if Surya is unavailable.
- If using Tesseract, make sure the executable is installed and accessible through `PATH`.

## Troubleshooting

- If Surya fails to load, check that `surya-ocr` is installed and compatible with your environment.
- If Tesseract fails, verify `pytesseract` is installed and `tesseract.exe` is on your PATH.
- If OCR text is missing, enable `--debug` to inspect the validation PDF overlay output.
