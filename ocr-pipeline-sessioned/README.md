# OCR Pipeline (session-batched)

Same modular pipeline as `ocr-pipeline-modular` (image prep → OCR extraction
→ text correction → searchable PDF assembly → PDF merge), rebuilt to fix a
specific problem: every `claude -p ...` subprocess call the pipeline made
started a brand-new Claude Code session, and there was one such call per
page (Step 2's `claude-vision` OCR engine) or per low-confidence text block
(Step 3's `--backend cli` correction). A single 116-page batch run alone
produced well over a hundred sessions this way; across real usage this added
up to thousands of sessions in Anthropic's usage analytics for what is
conceptually one job.

## What changed

`claude_session.py` is the new piece. It keeps the exact same mechanism --
the `claude` CLI's non-interactive print mode, reusing whatever `claude
/login` OAuth session is already active, no `ANTHROPIC_API_KEY` needed --
but chains up to `--session-batch-size` (default 15) independent calls into
**one continuing Claude Code session**, via `--session-id` on the first
call and `--resume <that id>` on every call after it, instead of starting a
fresh session every time.

This is *not* the same thing as batching multiple pages/blocks into one
prompt. Each page and each text block is still sent as its own,
independent turn -- combining several images or blocks into a single
request would risk the model conflating content across them, which is a
real failure mode for this kind of transcription/correction work. What
changes is only which session a given turn's `claude -p` call belongs to.
Since turns in the same session do still share conversation history, every
prompt template built on this (see `02_ocr_extract.py`'s and
`03_text_correct.py`'s prompts) explicitly tells Claude to treat each turn
as independent and ignore earlier turns' content -- and both were tested
end-to-end (see below) confirming pages/blocks that shared a session came
back correct and independent, with no cross-contamination.

Both call sites that used to spin one session per call now go through
`claude_session.run_in_batched_sessions()`:

- **`02_ocr_extract.py`**, `--engine claude-vision`: one session per
  `--session-batch-size` pages, instead of one per page.
- **`03_text_correct.py`**, `--auto --backend cli`: every low-confidence
  block *across the whole batch* (not just one file) is flattened into one
  list and chained `--session-batch-size` at a time, instead of one session
  per block. (`--backend api` is unaffected -- the Anthropic SDK never used
  Claude Code sessions in the first place, so it isn't part of this
  problem; `--interactive` mode is also unaffected, since it's human-paced
  and low-volume by nature.)

`--workers` still exists and still means "how many of these run
concurrently" -- it now means concurrent *sessions* for these two paths
(each running its own chain of resumed calls sequentially inside it), so
you keep both the session-count reduction and the wall-clock benefit of
parallelism at the same time. See each script's `--help` for the exact
flags (`--session-batch-size`, `--workers`).

## Everything else

`01_image_prep.py`, `05_pdf_merge.py`, and `utils.py` are carried over
unchanged from `ocr-pipeline-modular` -- none of them call Claude directly,
so none of them contributed to the session count problem.

`04_pdf_assemble.py` and `gui.py` are likewise carried over from
`ocr-pipeline-modular` for the same reason, but have since gained one
addition unrelated to the session-batching fix: `--merge-per-basename`
(and the matching GUI checkbox on the "Step 4: PDF Assembly" tab). It's for
a flat folder holding pages from multiple documents, each named
`<document>_<page_number>.<ext>` (e.g. `SmithLetter_001.tif`,
`SmithLetter_002.tif`, `JonesReport_001.tif`) -- it groups the resulting
per-page PDFs by document, sorts each group's pages numerically, and
merges each into its own `<document>.pdf` under `--output-dir`. This is an
alternative to the existing `--recursive`/`--merge-per-folder` combination,
for when documents live side by side in one folder instead of in separate
subfolders. See `python 04_pdf_assemble.py --help` for usage.

This project does not (yet) carry over `ocr-pipeline-modular/packaging/`
(the frozen Mac/Windows app build). That can be ported over on request; it
wasn't needed to validate the session-batching fix itself.

## Verified

Both new call sites were run end-to-end against the real `claude` CLI
(not mocked):

- `03_text_correct.py --auto --backend cli --session-batch-size 2 --workers 2`
  against 3 low-confidence blocks across 3 files correctly produced 2
  sessions (not 3), and corrected all three blocks correctly.
- `02_ocr_extract.py --engine claude-vision --session-batch-size 2 --workers 2`
  against 3 synthetic one-line-of-text images correctly produced 2 sessions,
  and each page's transcription came back correct and independent -- no
  bleed-through despite two pages sharing one session's conversation
  history.
