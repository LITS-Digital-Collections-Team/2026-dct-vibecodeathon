#!/usr/bin/env python3
"""
Step 4: PDF Assembly - Create searchable PDF from original image and OCR text.

Combines original TIFF/image with corrected OCR text to create a searchable PDF.
Text is placed at original coordinates and made invisible to create text layer beneath image.

Usage:
    python 04_pdf_assemble.py --image image.jpg --ocr ocr_corrected.json --output output.pdf
    python 04_pdf_assemble.py --image-dir ./images --ocr-dir ./corrected_output --output-dir ./pdfs
    python 04_pdf_assemble.py --image image.jpg --ocr ocr.json --output out.pdf --debug
"""

import argparse
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import json

import fitz  # pymupdf

from utils import (
    ensure_dir, get_output_filename, OCRDataHandler, setup_logging,
    OCROutput, validate_image_path
)

logger = logging.getLogger(__name__)


class PDFAssembler:
    """Create searchable PDF from image and OCR text."""

    def __init__(self, debug: bool = False):
        """Initialize PDF assembler.

        Args:
            debug: If True, show red bounding boxes around text blocks
        """
        self.debug = debug

    def assemble_pdf(
        self,
        image_path: Path,
        ocr_output: OCROutput,
        output_path: Path,
        font_size: Optional[int] = None
    ) -> None:
        """Create searchable PDF from image and OCR text.

        Args:
            image_path: Path to original image file
            ocr_output: OCROutput with text blocks
            output_path: Output PDF file path
            font_size: Font size for text (auto-calculated if None)
        """
        if not validate_image_path(image_path):
            raise ValueError(f"Invalid image path: {image_path}")

        logger.info(f"Creating PDF from {image_path}")

        try:
            # Create PDF with image dimensions
            img_width = ocr_output.dimensions["width"]
            img_height = ocr_output.dimensions["height"]

            # Convert pixels to points (72 dpi)
            pdf_width = img_width * 72 / 96
            pdf_height = img_height * 72 / 96

            # Create document
            doc = fitz.open()
            page = doc.new_page(width=pdf_width, height=pdf_height)

            # Insert image
            try:
                img_rect = fitz.Rect(0, 0, pdf_width, pdf_height)
                pix = fitz.Pixmap(image_path)
                page.insert_image(img_rect, pixmap=pix)
            except Exception as e:
                logger.warning(f"Could not insert image {image_path}: {e}")

            # Add text layer (invisible and searchable)
            for block in ocr_output.blocks:
                text = block.text
                x = block.x * 72 / 96
                y = block.y * 72 / 96
                width = block.width * 72 / 96
                height = block.height * 72 / 96

                # Create text rectangle
                text_rect = fitz.Rect(x, y, x + width, y + height)

                # Calculate adaptive font size if not provided
                if font_size is None:
                    # Estimate based on block height
                    est_font_size = max(8, int(height * 0.7))
                else:
                    est_font_size = font_size

                try:
                    # Insert text as a genuinely invisible (render_mode=3) text
                    # layer. insert_textbox doesn't fit if the requested font
                    # size leaves no room for line height within text_rect
                    # (returns a negative fit code rather than raising), so
                    # shrink the font until it fits or hits a floor.
                    size = est_font_size
                    fitted = False
                    while size >= 4:
                        rc = page.insert_textbox(
                            text_rect,
                            text,
                            fontsize=size,
                            align=fitz.TEXT_ALIGN_LEFT,
                            render_mode=3,
                        )
                        if rc >= 0:
                            fitted = True
                            break
                        size -= 1

                    if not fitted:
                        logger.warning(f"Text did not fit block rect even at minimum font size, skipped: {text[:50]!r}")

                    if self.debug:
                        # Draw red bounding box for debugging
                        page.draw_rect(text_rect, color=fitz.pdfcolor["red"], width=1)
                        page.insert_text(
                            (x, y - 5),
                            f"[{block.confidence:.2f}]",
                            fontsize=6,
                            color=fitz.pdfcolor["red"]
                        )

                except Exception as e:
                    logger.warning(f"Failed to add text to PDF: {e}")
                    continue

            # Save PDF
            ensure_dir(output_path.parent)
            doc.save(output_path)
            doc.close()

            logger.info(f"PDF created: {output_path}")

        except Exception as e:
            logger.error(f"Failed to create PDF: {e}")
            raise

    def process_image_ocr_pair(
        self,
        image_path: Path,
        ocr_json_path: Path,
        output_dir: Path
    ) -> Path:
        """Process image with corresponding OCR file.

        Args:
            image_path: Path to image file
            ocr_json_path: Path to OCR JSON file
            output_dir: Output directory

        Returns:
            Path to created PDF
        """
        logger.info(f"Processing: {image_path} + {ocr_json_path}")

        # Load OCR data
        ocr_output = OCRDataHandler.load_json(ocr_json_path)

        # Create PDF
        output_path = output_dir / f"{image_path.stem}_searchable.pdf"
        self.assemble_pdf(image_path, ocr_output, output_path)

        return output_path

    def process_batch(
        self,
        image_dir: Path,
        ocr_dir: Path,
        output_dir: Path
    ) -> List[Path]:
        """Process all image-OCR pairs in directories.

        Args:
            image_dir: Directory with images
            ocr_dir: Directory with OCR JSON files
            output_dir: Output directory

        Returns:
            List of created PDF paths
        """
        image_dir = Path(image_dir)
        ocr_dir = Path(ocr_dir)
        output_dir = ensure_dir(output_dir)

        if not image_dir.exists():
            raise FileNotFoundError(f"Image directory not found: {image_dir}")
        if not ocr_dir.exists():
            raise FileNotFoundError(f"OCR directory not found: {ocr_dir}")

        # Find image files
        image_files = (
            list(image_dir.glob("*.jpg")) +
            list(image_dir.glob("*.jpeg")) +
            list(image_dir.glob("*.png")) +
            list(image_dir.glob("*.tif")) +
            list(image_dir.glob("*.tiff"))
        )

        if not image_files:
            logger.warning(f"No image files found in {image_dir}")
            return []

        logger.info(f"Found {len(image_files)} image file(s)")

        results = []
        for image_path in sorted(image_files):
            # Find corresponding OCR file
            ocr_json_path = ocr_dir / f"{image_path.stem}_ocr.json"
            if not ocr_json_path.exists():
                # Try corrected version
                ocr_json_path = ocr_dir / f"{image_path.stem}_ocr_corrected.json"

            if not ocr_json_path.exists():
                logger.warning(f"No OCR file found for {image_path}, skipping")
                continue

            try:
                pdf_path = self.process_image_ocr_pair(
                    image_path,
                    ocr_json_path,
                    output_dir
                )
                results.append(pdf_path)
            except Exception as e:
                logger.error(f"Error processing {image_path}: {e}")
                continue

        return results


class PDFMerger:
    """Merge multiple PDFs into single document."""

    @staticmethod
    def merge_pdfs(pdf_paths: List[Path], output_path: Path) -> None:
        """Merge multiple PDFs.

        Args:
            pdf_paths: List of PDF file paths
            output_path: Output merged PDF path
        """
        if not pdf_paths:
            logger.warning("No PDFs to merge")
            return

        logger.info(f"Merging {len(pdf_paths)} PDF(s)")

        try:
            output_doc = fitz.open()

            for pdf_path in sorted(pdf_paths):
                try:
                    pdf = fitz.open(pdf_path)
                    output_doc.insert_pdf(pdf)
                    pdf.close()
                except Exception as e:
                    logger.error(f"Error merging {pdf_path}: {e}")
                    continue

            ensure_dir(output_path.parent)
            output_doc.save(output_path)
            output_doc.close()

            logger.info(f"Merged PDF saved: {output_path}")

        except Exception as e:
            logger.error(f"Failed to merge PDFs: {e}")
            raise


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Step 4: PDF Assembly - Create searchable PDF from image and OCR text",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single image + OCR file
  python 04_pdf_assemble.py --image image.jpg --ocr ocr.json --output output.pdf

  # Batch processing
  python 04_pdf_assemble.py --image-dir ./images --ocr-dir ./corrected_output \\
    --output-dir ./pdfs

  # Debug mode with visible text boxes
  python 04_pdf_assemble.py --image image.jpg --ocr ocr.json --output output.pdf --debug

  # Merge all PDFs into single document
  python 04_pdf_assemble.py --image-dir ./images --ocr-dir ./corrected_output \\
    --output-dir ./pdfs --merge-output combined.pdf
        """
    )

    parser.add_argument("--image", type=Path, help="Single image file")
    parser.add_argument("--ocr", type=Path, help="OCR JSON file (required with --image)")
    parser.add_argument("--output", type=Path, help="Output PDF file (required with --image)")

    parser.add_argument("--image-dir", type=Path, help="Directory with images")
    parser.add_argument("--ocr-dir", type=Path, help="Directory with OCR JSON files")
    parser.add_argument("--output-dir", type=Path, help="Output directory for PDFs")

    parser.add_argument("--debug", action="store_true", help="Show red bounding boxes around text")
    parser.add_argument(
        "--merge-output", type=Path,
        help="Merge all output PDFs into single file"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(__name__, log_level)

    # Validate arguments
    single_mode = args.image or args.ocr or args.output
    batch_mode = args.image_dir or args.ocr_dir or args.output_dir

    if single_mode and batch_mode:
        parser.error("Cannot use both single mode (--image/--ocr/--output) and batch mode (--image-dir/--ocr-dir/--output-dir)")

    if not single_mode and not batch_mode:
        parser.error("Must specify either single mode or batch mode")

    try:
        assembler = PDFAssembler(debug=args.debug)

        if single_mode:
            # Single image + OCR file
            if not args.image or not args.ocr or not args.output:
                parser.error("Single mode requires --image, --ocr, and --output")

            assembler.assemble_pdf(
                args.image,
                OCRDataHandler.load_json(args.ocr),
                args.output
            )
            logger.info("PDF assembly complete")

        elif batch_mode:
            # Batch processing
            if not args.image_dir or not args.ocr_dir or not args.output_dir:
                parser.error("Batch mode requires --image-dir, --ocr-dir, and --output-dir")

            pdfs = assembler.process_batch(
                args.image_dir,
                args.ocr_dir,
                args.output_dir
            )

            logger.info(f"Batch processing complete: {len(pdfs)} PDF(s) created")

            if args.merge_output:
                PDFMerger.merge_pdfs(pdfs, args.merge_output)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        exit(1)


if __name__ == "__main__":
    main()
