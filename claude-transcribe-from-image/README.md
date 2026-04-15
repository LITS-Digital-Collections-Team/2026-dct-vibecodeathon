# claude-transcribe-from-image

Batch-transcription of scanned handwritten manuscript images and PDFs using
the [Anthropic Claude](https://www.anthropic.com/claude) vision API
(`claude-sonnet-4-6`).  Developed for the digitisation programme at Hamilton
College Library, Information & Technology Services (LITS).

---

## AI-generated content disclaimer

This tool uses a large language model (Anthropic Claude) to generate
transcriptions.  Output should be treated as a **draft** and reviewed by a
qualified person before use in finding aids, publications, or any context
requiring accuracy.  The model may misread individual words, confuse similar
letterforms, silently omit illegible passages, or produce plausible-looking but
incorrect text.  Uncertain words are flagged with `[?]` but not all errors will
be flagged.

---

## Description

`claude-transcribe-batch.py` processes a single file or a directory of scanned
images or PDFs and writes one plain-text transcription file per input document.
It is designed for archival workflows where a large number of manuscript pages
need to be converted to searchable text quickly, with human review to follow.

### How it works

1. Each input file is discovered by extension (`.jpg`, `.jpeg`, `.png`,
   `.tiff`, `.tif`, `.pdf`).
2. Images are resized so that the longest side is at most 1,500 px and
   re-encoded as JPEG before sending to the API.  This controls token cost
   without sacrificing the resolution needed for period handwriting.
3. PDFs are rasterised page by page at 150 DPI using `pdf2image` / poppler,
   then processed identically to images.
4. Each page is sent to `claude-sonnet-4-6` with a system prompt that primes
   the model as a specialist in 19th-century English handwritten documents.
   The model is instructed to transcribe text exactly as written and to mark
   uncertain words with `[?]`.
5. Output is written to `<stem>.txt` alongside (or in a separate directory
   from) the source file.
6. The script is **resumable**: files whose `.txt` output already exists are
   skipped automatically on subsequent runs.  Use `--overwrite` to force
   re-transcription.

### Multi-page PDFs

All pages of a multi-page PDF are transcribed and concatenated into a single
`.txt` file, separated by `--- Page N ---` markers.

---

## Requirements

| Package | Purpose | Install |
|---------|---------|---------|
| Python 3.9+ | — | — |
| `anthropic` | Anthropic API client | `pip install anthropic` |
| `Pillow` | Image resizing and re-encoding | `pip install Pillow` |
| `pdf2image` | PDF → image conversion *(PDF input only)* | `pip install pdf2image` |
| poppler | Back-end for pdf2image *(PDF input only)* | see below |

**Installing poppler:**

```bash
# macOS
brew install poppler

# Ubuntu / Debian
apt install poppler-utils
```

Install all Python packages at once:

```bash
pip install anthropic Pillow pdf2image
```

---

## Configuration

The script reads your Anthropic API key from the environment variable
`ANTHROPIC_API_KEY`.  Set it before running:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

To make this permanent, add the line to your shell profile (`~/.zprofile`,
`~/.bashrc`, etc.).

The following constants at the top of the script can be adjusted without
changing any logic:

| Constant | Default | Effect |
|----------|---------|--------|
| `MAX_SIDE_PX` | `1500` | Maximum image dimension before encoding. Raise if fine detail is missed; lower to reduce token cost. |
| `JPEG_QUALITY` | `85` | Re-encoding quality. Values below ~75 may introduce artefacts on thin pen strokes. |
| `PDF_DPI` | `150` | Rasterisation resolution for PDF pages. Raise to `200` for very small script. |

---

## Usage

```
python3 claude-transcribe-batch.py --input PATH --output DIR [--overwrite] [--dry-run]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--input`, `-i` | yes | A single `.jpg`, `.jpeg`, `.png`, `.tiff`, `.tif`, or `.pdf` file, **or** a directory of such files |
| `--output`, `-o` | yes | Directory to write `.txt` transcription files (created if it does not exist) |
| `--overwrite` | no | Re-transcribe files that already have a `.txt` output; default is to skip them |
| `--dry-run` | no | Estimate input token count and cost without calling the API or writing any files |

`--input` and `--output` may point to the same directory.  The `.txt` files
are ignored during input discovery (only image/PDF extensions are matched), so
there is no risk of re-processing your own output.

---

## Examples

**Transcribe a directory of JPEGs into a separate output folder:**

```bash
python3 claude-transcribe-batch.py \
    --input  ~/scans/letters/ \
    --output ~/transcriptions/letters/
```

**Transcribe PDFs in-place (output files alongside the PDFs):**

```bash
python3 claude-transcribe-batch.py \
    --input  ~/projects/yhm-com-bnl-mss_PDFs/ \
    --output ~/projects/yhm-com-bnl-mss_PDFs/
```

**Re-run on a collection where some files have already been transcribed:**

The script will skip files that already have a corresponding `.txt`.  To
re-transcribe everything:

```bash
python3 claude-transcribe-batch.py \
    --input  ~/scans/letters/ \
    --output ~/transcriptions/letters/ \
    --overwrite
```

**Estimate token usage and cost before running (no API calls made):**

```bash
python3 claude-transcribe-batch.py \
    --input  ~/projects/yhm-com-bnl-mss_PDFs/ \
    --output ~/projects/yhm-com-bnl-mss_PDFs/ \
    --dry-run
```

```
DRY RUN — 110 file(s) found. Estimating input tokens (output tokens are not predictable in advance)...
  yhm-com-bnl-mss-0001.pdf: ~2,618 input tokens
  yhm-com-bnl-mss-0002.pdf: ~7,568 input tokens
  ...

Estimated total input tokens : ~285,400
Estimated input-only cost    : ~$0.8562 USD
(Output token cost excluded — varies by transcription length.)
```

Note: the estimate uses Claude's documented formula `(width × height) / 750` per image and may run slightly high.  Output token cost (billed at a higher rate) is not included.

**Sample progress output:**

```
Found 110 file(s). Starting transcription...
[1/110] yhm-com-bnl-mss-0001.pdf
[2/110] yhm-com-bnl-mss-0002.pdf
    page 1/3
    page 2/3
    page 3/3
[3/110] yhm-com-bnl-mss-0003.pdf
...
Done. Processed: 110  Skipped (already transcribed): 0  Errors: 0

Metrics:
  Runtime       : 843.2s
  Input tokens  : 198,450
  Output tokens : 42,310
  Est. cost     : $1.2303 USD
```

**Sample output file (`yhm-com-bnl-mss-0001.txt`):**

```
Fountain Grove
Santa Rosa
Apr 18, 1876.

Dear Sir  As Mr. Harris is not through that transitional state into which he
has entered, you will not be surprised that he has to leave to other hands the
task of replying to correspondents who make inquiries at this time concerning
the life.  We have delayed replying to yours hoping he might possibly be able
to do so himself, which would have been so much more satisfactory to you.  But
as he cannot, I will try and answer your questions as well as I can.
```

---

## Output format

- One `.txt` file per input document, named `<source_stem>.txt`.
- Plain UTF-8 text; line breaks are preserved as they appear on the page.
- Uncertain words are followed by `[?]` (e.g. `envigorating [?]`).
- Multi-page PDFs are separated by `--- Page N ---` markers.

---

## Limitations and known issues

- **Accuracy varies by hand.**  Clear, regular scripts transcribe well.  Very
  cramped, faded, or idiosyncratic hands may produce more `[?]` markers or
  silent errors.
- **No confidence scores.**  The `[?]` convention relies on the model's
  self-assessment; some errors will not be flagged.
- **Token limits.**  At `max_tokens=2048` the model can handle approximately
  500–800 words per page.  If a page is cut off mid-transcription, increase
  `max_tokens` in `transcribe_image_b64()`.
- **Rate limits.**  The Anthropic API enforces per-minute token limits.  For
  very large collections (500+ documents), consider adding a short sleep between
  requests or using the Batches API.
- **Internet connection required.**  All processing is done via the Anthropic
  cloud API; nothing runs locally beyond image preparation.

---

## License

Copyright © 2026 Patrick R. Wallace and Hamilton College LITS.

This program is free software: you can redistribute it and/or modify it under
the terms of the **GNU General Public License version 3** as published by the
Free Software Foundation.

This program is distributed in the hope that it will be useful, but **WITHOUT
ANY WARRANTY**; without even the implied warranty of **MERCHANTABILITY** or
**FITNESS FOR A PARTICULAR PURPOSE**.  See the GNU General Public License for
more details.

A full copy of the GNU General Public License is available at
<https://www.gnu.org/licenses/gpl-3.0.html>.
