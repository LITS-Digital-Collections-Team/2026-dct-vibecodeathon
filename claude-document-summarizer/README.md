# claude-document-summarizer

Batch-summarization of plain-text transcripts using the
[Anthropic Claude](https://www.anthropic.com/claude) API (`claude-sonnet-4-6`).
Developed for the digitisation programme at Hamilton College Library,
Information & Technology Services (LITS).

---

## AI-generated content disclaimer

This tool uses a large language model (Anthropic Claude) to generate
descriptive summaries.  Output should be treated as a **draft** and reviewed
by a qualified archivist before use in finding aids, catalogs, or any context
requiring accuracy.  The model may mischaracterise content, conflate names or
topics, or omit significant passages.

---

## Description

`claude-summarize.py` reads a single `.txt` transcript file or a directory of
such files, generates a neutral descriptive summary of each (suitable for
library catalogs and archival finding aids), and writes the result to an output
directory.  It is designed for archival workflows at Hamilton College LITS.

### How it works

1. Each input `.txt` file is read and its token length estimated.  `--input`
   may be a single file or a directory.
2. **Single-pass** (most documents): if the transcript fits within Claude's
   200K-token context window, it is sent in one API call.  This eliminates
   the chunking overhead required by earlier GPT-based tools.
3. **Chunked** (very long documents): if the transcript exceeds the single-pass
   limit, it is split on paragraph boundaries into ~60K-token chunks.  Each
   chunk is summarised separately, and the partial summaries are consolidated
   into one coherent result in a second pass.
4. All API calls use streaming, so long responses do not time out.
5. The script is **resumable**: files whose output already exists in the output
   directory are skipped automatically.  Use `--overwrite` to force
   re-summarisation.
6. At the end of a run, runtime, token counts, and estimated cost are logged.

### Output

- One `.txt` file per input document, with the same filename, written to the
  output directory.
- Plain UTF-8 text, fewer than 300 words by default.
- Neutral, descriptive language; no PII (email addresses, phone numbers, URLs).

---

## Requirements

| Package | Purpose | Install |
|---------|---------|---------|
| Python 3.9+ | — | — |
| `anthropic` | Anthropic API client | `pip install anthropic` |

```bash
pip install anthropic
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

The following constants at the top of the script can be adjusted:

| Constant | Default | Effect |
|----------|---------|--------|
| `MODEL` | `claude-sonnet-4-6` | Model used for summarisation. |
| `MAX_INPUT_TOKENS` | `180000` | Documents larger than this are chunked. |
| `CHUNK_TARGET_TOKENS` | `60000` | Target size per chunk for long documents. |
| `RESPONSE_MAX_TOKENS` | `1024` | Maximum length of each model response. Raise to `2048` for longer summaries. |
| `REQUEST_DELAY_SECONDS` | `6` | Default pause between requests. Override at runtime with `--delay`. |
| `SYSTEM_PROMPT` | *(see script)* | The archivist instruction given to the model. Edit to change domain, institution, or output style. |

---

## Usage

```
python3 claude-summarize.py --input PATH --output DIR [--overwrite] [--dry-run] [--delay SECONDS]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--input`, `-i` | yes | A single `.txt` file, or a directory of `.txt` transcript files |
| `--output`, `-o` | yes | Directory to write `.txt` summary files (created if it does not exist) |
| `--overwrite` | no | Re-summarise files that already have output; default is to skip them |
| `--dry-run` | no | Count input tokens and estimate cost without summarising (uses the token-counting API; no inference charges) |
| `--delay SECONDS` | no | Seconds to wait between requests (default: `6`; set to `0` to disable) |

When `--input` is a directory, it **must differ from `--output`** — both
contain `.txt` files, so using the same path would overwrite source
transcripts with their summaries.  When `--input` is a single file this
restriction does not apply.

---

## Examples

**Summarise a directory of transcripts:**

```bash
python3 claude-summarize.py \
    --input  ~/transcripts/hamilton-lectures/ \
    --output ~/summaries/hamilton-lectures/
```

**Estimate token usage and cost before running:**

```bash
python3 claude-summarize.py \
    --input  ~/transcripts/hamilton-lectures/ \
    --output ~/summaries/hamilton-lectures/ \
    --dry-run
```

```
DRY RUN — 42 file(s) found. Counting tokens via API...
  hamilton-lecture-1974-03-12.txt: 4,821 input tokens
  hamilton-lecture-1974-03-19.txt: 6,103 input tokens
  ...

Estimated total input tokens : 218,450
Estimated input-only cost    : ~$1.0923 USD
(Output token cost excluded — varies by summary length.)
```

The `--dry-run` token counts are exact (via the Anthropic token-counting
endpoint); output token cost is not included as it depends on the generated
summary length.

**Re-run on a collection where some files have already been summarised:**

```bash
python3 claude-summarize.py \
    --input  ~/transcripts/hamilton-lectures/ \
    --output ~/summaries/hamilton-lectures/ \
    --overwrite
```

**Sample progress output:**

```
Found 42 file(s). Starting summarisation...
[1/42] hamilton-lecture-1974-03-12.txt
    single pass (~4,821 estimated tokens)
[2/42] hamilton-lecture-1974-03-19.txt
    single pass (~6,103 estimated tokens)
...
Done. Processed: 42  Skipped (already summarised): 0  Errors: 0

Metrics:
  Runtime       : 187.4s
  Input tokens  : 198,320
  Output tokens : 14,210
  Est. cost     : $1.3470 USD
```

**Sample output file (`hamilton-lecture-1974-03-12.txt`):**

```
Lecture delivered at Hamilton College, March 1974, on the history of
labor organization in the Mohawk Valley. The speaker surveys archival
evidence from county industrial records, 1918–1945, identifying key
figures including organizer Ruth Ellsworth and county labor commissioner
Thomas Vane. Locations discussed include Clinton, Utica, and Oneida
County. The lecture references primary sources held at the New York
State Archives and the Burke Library Special Collections, Hamilton
College. No contact information included.
```

---

## Limitations and known issues

- **Accuracy varies by source quality.**  Clean, verbatim transcripts
  summarise well.  Heavily edited, fragmented, or noisy transcripts may
  produce less accurate summaries.
- **300-word cap is enforced by instruction, not mechanically.**  The model
  generally complies, but may occasionally exceed the limit on complex
  documents.  Adjust `SYSTEM_PROMPT` if stricter control is needed.
- **Chunked documents may lose cross-section references.**  If a speaker
  returns to a topic across distant sections of a very long transcript, the
  consolidation pass may not fully reconstruct that thread.
- **Internet connection required.**  All processing is done via the Anthropic
  cloud API.
- **Rate limits.**  A 6-second inter-request delay is applied by default.
  Increase it with `--delay` for very large collections or lower API tiers,
  or set `--delay 0` to disable it entirely.  For very high-volume workloads
  (500+ documents), the Anthropic Batches API offers higher throughput and a
  50% cost discount.

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
