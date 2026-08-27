#!/usr/bin/env python3
"""
Step 5: PDF Merge - Combine per-page PDFs into one multi-page PDF, in
filename order.

Usage:
    python 05_pdf_merge.py --input-dir ./pdf_output --output ./combined.pdf
"""

import argparse
import logging
import re
from pathlib import Path

import fitz  # pymupdf

from utils import ensure_dir, setup_logging

logger = logging.getLogger(__name__)


def natural_sort_key(path: Path):
    """Split a filename into text/number chunks so embedded page numbers
    sort numerically (e.g. '_9' before '_10') rather than lexicographically.
    """
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r"(\d+)", path.stem)
    ]


def merge_pdfs(input_dir: Path, output_path: Path, pattern: str = "*.pdf") -> int:
    """Merge all PDFs in input_dir into a single PDF, ordered by filename.

    Args:
        input_dir: Directory containing the per-page PDFs
        output_path: Path to write the merged PDF
        pattern: Glob pattern to select input PDFs

    Returns:
        Number of pages written
    """
    pdf_files = sorted(input_dir.glob(pattern), key=natural_sort_key)
    if not pdf_files:
        raise FileNotFoundError(f"No PDF files matching {pattern!r} found in {input_dir}")

    logger.info(f"Merging {len(pdf_files)} PDF(s) in filename order")
    for pdf_file in pdf_files:
        logger.debug(f"  {pdf_file.name}")

    merged = fitz.open()
    page_count = 0
    for pdf_file in pdf_files:
        with fitz.open(pdf_file) as src:
            merged.insert_pdf(src)
            page_count += src.page_count

    ensure_dir(output_path.parent)
    merged.save(str(output_path))
    merged.close()

    logger.info(f"Saved merged PDF ({page_count} pages) to {output_path}")
    return page_count


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Step 5: PDF Merge - Combine per-page PDFs into one PDF, in filename order",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python 05_pdf_merge.py --input-dir ./pdf_output_boa --output ./boa-005-merged.pdf

  # Only merge a subset matching a glob pattern
  python 05_pdf_merge.py --input-dir ./pdf_output_boa --output ./out.pdf --pattern "*005_0*.pdf"
        """,
    )
    parser.add_argument("--input-dir", type=Path, required=True, help="Directory of per-page PDFs to merge")
    parser.add_argument("--output", type=Path, required=True, help="Path for the merged output PDF")
    parser.add_argument(
        "--pattern", default="*.pdf",
        help="Glob pattern for selecting input PDFs within --input-dir (default: *.pdf)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(__name__, log_level)

    if not args.input_dir.exists():
        parser.error(f"Input directory not found: {args.input_dir}")

    try:
        merge_pdfs(args.input_dir, args.output, args.pattern)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        exit(1)


if __name__ == "__main__":
    main()
