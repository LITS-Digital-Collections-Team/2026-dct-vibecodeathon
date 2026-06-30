#!/usr/bin/env python3
"""
Step 2: OCR Extraction - Extract text with character-level coordinates.

Extracts text from images using Tesseract (local) or Google Cloud Vision (API).
Saves complete OCR output with character-level bounding boxes and confidence scores.

Usage:
    python 02_ocr_extract.py --input image.jpg --output-dir ./ocr_output
    python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output
    python 02_ocr_extract.py --input image.jpg --output-dir ./ocr_output --engine gcv --dry-run
"""

import argparse
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import json

from utils import (
    ensure_dir, get_output_filename, OCRDataHandler, setup_logging,
    OCROutput, TextBlock, CharBound, validate_image_path
)

logger = logging.getLogger(__name__)


class TesseractOCR:
    """OCR using Tesseract via pytesseract."""

    def __init__(self):
        """Initialize Tesseract OCR."""
        try:
            import pytesseract
            self.pytesseract = pytesseract
            logger.info("Tesseract initialized")
        except ImportError:
            logger.error("pytesseract not installed. Install with: pip install pytesseract")
            raise

    def extract_text(self, image_path: Path) -> OCROutput:
        """Extract text with coordinates from image using Tesseract.

        Args:
            image_path: Path to image file

        Returns:
            OCROutput with extracted text and coordinates
        """
        if not validate_image_path(image_path):
            raise ValueError(f"Invalid image path: {image_path}")

        try:
            from PIL import Image
            img = Image.open(image_path)
            img_width, img_height = img.size
        except Exception as e:
            logger.error(f"Failed to open image: {e}")
            raise

        logger.info(f"Extracting text from {image_path}")

        try:
            # Get detailed data from Tesseract
            data = self.pytesseract.image_to_data(image_path, output_type=self.pytesseract.Output.DICT)

            blocks = []
            text_dict = data

            # Group by block
            block_indices = set(text_dict['block_num'])
            for block_num in sorted(block_indices):
                block_text = ""
                block_chars = []
                block_conf = 0
                block_x, block_y = float('inf'), float('inf')
                block_x2, block_y2 = 0, 0

                for i, block_id in enumerate(text_dict['block_num']):
                    if block_id != block_num:
                        continue

                    text = text_dict['text'][i]
                    if not text.strip():
                        continue

                    conf = int(text_dict['conf'][i])
                    x = int(text_dict['left'][i])
                    y = int(text_dict['top'][i])
                    w = int(text_dict['width'][i])
                    h = int(text_dict['height'][i])

                    block_text += text + " "
                    block_conf = max(block_conf, conf)
                    block_x = min(block_x, x)
                    block_y = min(block_y, y)
                    block_x2 = max(block_x2, x + w)
                    block_y2 = max(block_y2, y + h)

                    # Add individual words as character bounds (approximate)
                    for char in text:
                        char_width = w / len(text) if text else 0
                        block_chars.append(CharBound(
                            char=char,
                            x=x,
                            y=y,
                            width=char_width,
                            height=h,
                            confidence=conf / 100.0
                        ))

                if block_text.strip():
                    block_width = block_x2 - block_x
                    block_height = block_y2 - block_y

                    text_block = TextBlock(
                        text=block_text.strip(),
                        x=float(block_x),
                        y=float(block_y),
                        width=float(block_width),
                        height=float(block_height),
                        chars=block_chars,
                        source="tesseract",
                        confidence=min(100, block_conf) / 100.0
                    )
                    blocks.append(text_block)

            ocr_output = OCROutput(
                image_path=str(image_path),
                dimensions={"width": img_width, "height": img_height},
                blocks=blocks,
                engine="tesseract",
                metadata={
                    "total_blocks": len(blocks),
                    "avg_confidence": sum(b.confidence for b in blocks) / len(blocks) if blocks else 0
                }
            )

            logger.info(f"Extracted {len(blocks)} text blocks")
            return ocr_output

        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            raise


class GoogleCloudVisionOCR:
    """OCR using Google Cloud Vision API."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Google Cloud Vision OCR.

        Args:
            api_key: Google Cloud API key (or from GOOGLE_CLOUD_API_KEY env var)
        """
        try:
            from google.cloud import vision
            self.vision_client = vision.ImageAnnotatorClient()
            self.api_key = api_key or os.getenv("GOOGLE_CLOUD_API_KEY")
            logger.info("Google Cloud Vision initialized")
        except ImportError:
            logger.error("google-cloud-vision not installed. Install with: pip install google-cloud-vision")
            raise

    def extract_text(self, image_path: Path) -> OCROutput:
        """Extract text with coordinates using Google Cloud Vision.

        Args:
            image_path: Path to image file

        Returns:
            OCROutput with extracted text and coordinates
        """
        if not validate_image_path(image_path):
            raise ValueError(f"Invalid image path: {image_path}")

        try:
            from PIL import Image
            img = Image.open(image_path)
            img_width, img_height = img.size
        except Exception as e:
            logger.error(f"Failed to open image: {e}")
            raise

        logger.info(f"Extracting text from {image_path} (Google Cloud Vision)")

        try:
            from google.cloud import vision
            with open(image_path, 'rb') as f:
                image_content = f.read()

            image = vision.Image(content=image_content)
            response = self.vision_client.document_text_detection(image=image)

            blocks = []

            # Process full text annotation
            if response.full_text_annotation:
                for page in response.full_text_annotation.pages:
                    for paragraph in page.paragraphs:
                        para_text = ""
                        para_chars = []
                        para_conf = 1.0

                        # Get bounding box for paragraph
                        if paragraph.bounding_box.vertices:
                            vertices = paragraph.bounding_box.vertices
                            para_x = min(v.x for v in vertices)
                            para_y = min(v.y for v in vertices)
                            para_x2 = max(v.x for v in vertices)
                            para_y2 = max(v.y for v in vertices)
                        else:
                            continue

                        for word in paragraph.words:
                            word_text = "".join([symbol.text for symbol in word.symbols])
                            para_text += word_text + " "

                            # Get word confidence
                            word_conf = word.confidence

                            if word.bounding_box.vertices:
                                vertices = word.bounding_box.vertices
                                word_x = min(v.x for v in vertices)
                                word_y = min(v.y for v in vertices)
                                word_x2 = max(v.x for v in vertices)
                                word_y2 = max(v.y for v in vertices)
                                word_width = word_x2 - word_x
                                word_height = word_y2 - word_y

                                for char in word_text:
                                    char_width = word_width / len(word_text) if word_text else 0
                                    para_chars.append(CharBound(
                                        char=char,
                                        x=float(word_x),
                                        y=float(word_y),
                                        width=float(char_width),
                                        height=float(word_height),
                                        confidence=float(word_conf)
                                    ))

                        if para_text.strip():
                            text_block = TextBlock(
                                text=para_text.strip(),
                                x=float(para_x),
                                y=float(para_y),
                                width=float(para_x2 - para_x),
                                height=float(para_y2 - para_y),
                                chars=para_chars,
                                source="gcv",
                                confidence=float(para_conf)
                            )
                            blocks.append(text_block)

            ocr_output = OCROutput(
                image_path=str(image_path),
                dimensions={"width": img_width, "height": img_height},
                blocks=blocks,
                engine="gcv",
                metadata={
                    "total_blocks": len(blocks),
                    "avg_confidence": sum(b.confidence for b in blocks) / len(blocks) if blocks else 0
                }
            )

            logger.info(f"Extracted {len(blocks)} text blocks")
            return ocr_output

        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            raise


class OCRExtractor:
    """Unified OCR extraction interface."""

    def __init__(self, engine: str = "tesseract"):
        """Initialize extractor with specified engine.

        Args:
            engine: OCR engine ("tesseract" or "gcv")
        """
        self.engine = engine
        if engine == "tesseract":
            self.ocr = TesseractOCR()
        elif engine == "gcv":
            self.ocr = GoogleCloudVisionOCR()
        else:
            raise ValueError(f"Unknown engine: {engine}")

    def process_image(self, image_path: Path) -> OCROutput:
        """Process single image.

        Args:
            image_path: Path to image file

        Returns:
            OCROutput
        """
        return self.ocr.extract_text(image_path)

    def process_batch(self, input_dir: Path) -> List[OCROutput]:
        """Process all images in directory.

        Args:
            input_dir: Input directory

        Returns:
            List of OCROutput objects
        """
        input_dir = Path(input_dir)
        if not input_dir.exists():
            raise FileNotFoundError(f"Input directory not found: {input_dir}")

        image_files = (
            list(input_dir.glob("*.jpg")) +
            list(input_dir.glob("*.jpeg")) +
            list(input_dir.glob("*.png")) +
            list(input_dir.glob("*.tif")) +
            list(input_dir.glob("*.tiff"))
        )

        if not image_files:
            logger.warning(f"No image files found in {input_dir}")
            return []

        logger.info(f"Processing {len(image_files)} image(s)")

        results = []
        for image_path in sorted(image_files):
            try:
                result = self.process_image(image_path)
                results.append(result)
            except Exception as e:
                logger.error(f"Error processing {image_path}: {e}")
                continue

        return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Step 2: OCR Extraction - Extract text with character-level coordinates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single image with Tesseract (default)
  python 02_ocr_extract.py --input image.jpg --output-dir ./ocr_output

  # Batch processing with Google Cloud Vision
  python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output --engine gcv

  # Dry run to test without saving
  python 02_ocr_extract.py --input image.jpg --output-dir ./ocr_output --dry-run

  # Verbose output
  python 02_ocr_extract.py --input image.jpg --output-dir ./ocr_output --verbose
        """
    )

    parser.add_argument("--input", type=Path, help="Single input image file")
    parser.add_argument("--input-dir", type=Path, help="Input directory with images")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory for OCR JSON")
    parser.add_argument(
        "--engine", choices=["tesseract", "gcv"], default="tesseract",
        help="OCR engine to use (default: tesseract)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Extract without saving files")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(__name__, log_level)

    # Validate arguments
    if not args.input and not args.input_dir:
        parser.error("Must specify either --input or --input-dir")
    if args.input and args.input_dir:
        parser.error("Cannot specify both --input and --input-dir")

    try:
        extractor = OCRExtractor(engine=args.engine)

        if not args.dry_run:
            output_dir = ensure_dir(args.output_dir)

        if args.input:
            # Single file
            result = extractor.process_image(args.input)
            if not args.dry_run:
                output_path = output_dir / f"{args.input.stem}_ocr.json"
                OCRDataHandler.save_json(result, output_path)
            logger.info("OCR extraction complete")

        elif args.input_dir:
            # Batch processing
            results = extractor.process_batch(args.input_dir)
            if not args.dry_run:
                for result in results:
                    output_path = output_dir / f"{Path(result.image_path).stem}_ocr.json"
                    OCRDataHandler.save_json(result, output_path)
            logger.info(f"Batch processing complete: {len(results)} files processed")

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        exit(1)


if __name__ == "__main__":
    main()
