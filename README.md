# 2026 DCT Vibecodeathon and AI & Tool Dev Sprint
Repository for scripts and other useful (or useful-ish) output from the Digital Collections Team (DCT) 2026 AI & Tool Development Sprint.

This repository contains scripts, small tools, metadata patches, notebooks, and example outputs produced by DCT staff and/or relevant to our daily work. Items are provided as working prototypes and convenience utilities to accelerate experimentation, reproducibility, and team development.

## Contents

| Folder | Description |
|---|---|
| [`spectator-ocr-clean/`](spectator-ocr-clean/) | A dependency-free Python script (`spectator-ocr-clean.py`) for cleaning ABBYY OCR plain-text output from scanned columnar newspapers. It strips gutter artifacts, removes noise lines, resolves hyphenated line-breaks, and reassembles wrapped paragraphs, writing cleaned files and a per-file TSV log to an output directory. |
| [`spectator-ner-extract/`](spectator-ner-extract/) | A two-script toolkit for extracting named entities (people, organizations/events, and places) from cleaned OCR text of the Hamilton College Spectator and similar student newspapers, using spaCy NER with heuristic filtering and reconciliation rules. Includes a single-pass extractor and a chunked batch extractor with JSON checkpointing, both producing deduplicated CSVs with date ranges. A sample of cleaned OCR files for testing is in `test-data/`. |

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
