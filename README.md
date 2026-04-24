# 2026 DCT Vibecodeathon and AI & Tool Dev Sprint
Repository for scripts and other useful (or useful-ish) output from the Digital Collections Team (DCT) 2026 AI & Tool Development Sprint, running from mid-April to early May & concurrent with the LITS' broader AI Evaluation Sprint.

This repository contains scripts, small tools, metadata patches, notebooks, and example outputs produced by DCT staff and/or relevant to our daily work. Items are provided as working prototypes and convenience utilities to accelerate experimentation, reproducibility, and team development.

## Contents

| Folder | Description |
|---|---|
| [`list-places-nearby/`](list-places-nearby/) | A dependency-free CLI utility that produces a plaintext list of GNIS place names within a given radius of a latitude/longitude point, reading directly from the USGS GNIS national text ZIP archive. |
| [`ner-extract-reconcile/`](ner-extract-reconcile/) | A multi-stage toolkit for OCR cleaning, named-entity extraction (people, places, organizations/events), and authority-file reconciliation of digitised historical newspaper archives, developed for the Hamilton College Spectator. Includes spaCy-based NER extraction (single-pass and batched), LCNAF-backed reconciliation for people and places, and bundled authority lists. |
| [`spectator-ocr-clean/`](spectator-ocr-clean/) | A dependency-free Python script (`spectator-ocr-clean.py`) for cleaning ABBYY OCR plain-text output from scanned columnar newspapers. It strips gutter artifacts, removes noise lines, resolves hyphenated line-breaks, and reassembles wrapped paragraphs, writing cleaned files and a per-file TSV log to an output directory. |
| [`spectator-ner-extract/`](spectator-ner-extract/) | A two-script toolkit for extracting named entities (people, organizations/events, and places) from cleaned OCR text of the Hamilton College Spectator and similar student newspapers, using spaCy NER with heuristic filtering and reconciliation rules. Includes a single-pass extractor and a chunked batch extractor with JSON checkpointing, both producing deduplicated CSVs with date ranges. |
| [`batch-ocr-to-pdf/`](batch-ocr-to-pdf/) | This script batches TIFF files, applies OCR, and creates searchable PDF output. It supports two OCR engines: Surya (preferred when available); Tesseract (fallback or explicit option); It also supports grouped output based on filename prefixes and optional debug validation PDFs. |
| [`GPT-extract-place/`](GPT-extract-place/) | Automatically extract geographic place names from a folder of scanned document images (letters, manuscripts, photographs, etc.) using the OpenAI GPT-4o Vision API. Results are written to a CSV with up to three place names per image. Built to address metadata issue with V. Parma Papers. |
| [`claude-transcribe-from-image/`](claude-transcribe-from-image/) | Batch-transcription of scanned handwritten manuscript images and PDFs using the [Anthropic Claude](https://www.anthropic.com/claude) vision API (`claude-sonnet-4-6`). Compatible with institutional Anthropic accounts. Includes token use and cost estimator + logging. |
| [`claude-document-summarizer/`](claude-document-summarizer/) | `claude-summarize.py` reads a single `.txt` transcript file or a directory of such files, generates a neutral descriptive summary of each (suitable for library catalogs and archival finding aids), and writes the result to an output directory. |
| [`mnemotron-wiki/`](mnemotron-wiki/) | Mnemotron Wiki is a Claude-powered system that synthesizes professional documents, email, calendar data, and project notes into a structured, searchable Markdown wiki. You supply the raw material; Claude distills it into dossiers, topic pages, and a running index. Everything lives in plain Markdown files that you own, version with git, and read in any editor. |
| [`combine_name_columns/`](combine_name_columns/) | A Python script that consolidates multiple role-specific personal_name columns in a metadata CSV file into a single pipe-delimited personal_name_combined column. |
| [`metadata-generator-enhancer/`](metadata-generator-enhancer/) | A comprehensive Python tool for metadata catalogers to generate, enhance, validate, and export metadata for ingestion into Archipelago digital collections management system. |

## Who this is for

- DCT staff, developers, and collaborators who want to reproduce, adapt, or extend sprint artifacts.
- People comfortable reading and testing experimental code and data before production use.

## What to expect

- Short, focused scripts and CLI tools (no guarantees of production readiness).
- Small datasets, test inputs, and example outputs.
- Per-folder README and usage notes where available.

## AI-generated content & review disclaimer

Some code, documentation, and other materials in this repository may have been generated or substantially assisted by AI systems. These materials may not have been fully reviewed by a human for quality, correctness, completeness, or security. Use at your own risk: review, test, and audit any item before using it in production or with sensitive data. Please open issues or pull requests to report problems or submit improvements.

## Contribution & license

Check each subfolder for a `README.md` and a `LICENSE` file. If no license appears, ask the maintainers for guidance before reusing code. For questions or contributions, file an issue or contact the DCT maintainers.