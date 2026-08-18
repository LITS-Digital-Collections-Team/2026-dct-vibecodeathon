#!/usr/bin/env python3
"""
Step 2: OCR Extraction - Extract text with character-level coordinates.

Extracts text from images using Tesseract (local), Google Cloud Vision (API),
Claude Vision (full-page transcription via the claude CLI, OAuth), or "auto"
cascade mode (default): try Tesseract first, and only call GCV when
Tesseract's confidence is below threshold. Saves complete OCR output with
character-level bounding boxes and confidence scores (except claude-vision,
which has no per-word coordinates -- see ClaudeVisionOCR).

Usage:
    python 02_ocr_extract.py --input image.jpg --output-dir ./ocr_output
    python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output
    python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output \\
        --engine auto --confidence-threshold 0.8
    python 02_ocr_extract.py --input image.jpg --output-dir ./ocr_output --engine gcv --dry-run
"""

import argparse
import logging
import os
import shutil
import subprocess
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
            # Pass the already-opened PIL Image, not the Path — pytesseract
            # doesn't accept Path objects on this API.
            data = self.pytesseract.image_to_data(img, output_type=self.pytesseract.Output.DICT)

            blocks = []
            text_dict = data

            # Group by block
            block_indices = set(text_dict['block_num'])
            for block_num in sorted(block_indices):
                block_text = ""
                block_chars = []
                block_conf_sum = 0
                block_conf_count = 0
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
                    block_conf_sum += conf
                    block_conf_count += 1
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
                    # Mean (not max) word confidence, so one confident word can't
                    # mask a block that's mostly garbled.
                    block_conf = block_conf_sum / block_conf_count if block_conf_count else 0

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
            # GCV's response hierarchy is Page -> Block -> Paragraph -> Word
            # -> Symbol; Page has no `paragraphs` field of its own.
            if response.full_text_annotation:
                for page in response.full_text_annotation.pages:
                    for block in page.blocks:
                        for paragraph in block.paragraphs:
                            para_text = ""
                            para_chars = []
                            word_confidences = []

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
                                word_confidences.append(word_conf)

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
                                para_conf = (
                                    sum(word_confidences) / len(word_confidences)
                                    if word_confidences else 0.0
                                )
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


class ClaudeVisionOCR:
    """Transcribe an image directly with Claude's vision, via the `claude`
    CLI's non-interactive print mode (OAuth-authenticated Claude
    subscription, no API key needed -- see 03_text_correct.py's
    --backend cli for the same mechanism).

    Unlike Tesseract/GCV, this reads the whole page holistically with a
    language model instead of classifying individual glyphs, which is
    dramatically more accurate on hard material like connected cursive
    handwriting. The tradeoff: Claude doesn't give reliable per-word
    pixel coordinates the way a real OCR engine does, so the full
    transcription is returned as a single TextBlock spanning the whole
    page rather than one block per line/word. The resulting PDF is fully
    text-searchable, just without word-level highlight positioning.

    Confidence is fixed at 1.0 deliberately (not a bug like the old GCV
    default) -- this is the highest-fidelity transcription this pipeline
    can produce, and Step 3's text-only correction can only see the text,
    not the image, so running it on top of a vision-grounded transcription
    could only introduce ungrounded "corrections", never improve it.
    """

    PROMPT_TEMPLATE = (
        "Read the image at {image_path} and transcribe the text exactly as "
        "written, preserving line breaks and paragraph structure. If the "
        "text is handwritten, transcribe your best reading of it.\n\n"
        "Return ONLY the transcription, nothing else -- no preamble, no "
        "commentary, no notes about illegible words."
    )

    def __init__(self, claude_bin: Optional[str] = None):
        self.claude_bin = claude_bin or shutil.which("claude")
        if not self.claude_bin:
            logger.warning("claude CLI not found on PATH; claude-vision extraction will fail")

    def extract_text(self, image_path: Path) -> OCROutput:
        """Extract a full-page transcription using Claude's vision.

        Args:
            image_path: Path to image file

        Returns:
            OCROutput with a single page-spanning TextBlock
        """
        if not validate_image_path(image_path):
            raise ValueError(f"Invalid image path: {image_path}")
        if not self.claude_bin:
            raise RuntimeError("claude CLI not found on PATH")

        from PIL import Image
        img = Image.open(image_path)
        img_width, img_height = img.size

        logger.info(f"Extracting text from {image_path} (Claude Vision)")

        prompt = self.PROMPT_TEMPLATE.format(image_path=image_path)
        cmd = [
            self.claude_bin, "-p", prompt,
            "--output-format", "json",
            "--disallowed-tools", "Bash,Write,Edit,Glob,Grep,WebSearch,WebFetch",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            raise RuntimeError("claude CLI timed out")

        if result.returncode != 0:
            raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr.strip()[:200]}")

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"claude CLI returned invalid JSON: {e}")

        if payload.get("is_error"):
            raise RuntimeError(f"claude CLI reported an error: {payload.get('result')}")

        text = (payload.get("result") or "").strip()

        blocks = []
        if text:
            blocks.append(TextBlock(
                text=text,
                x=0.0,
                y=0.0,
                width=float(img_width),
                height=float(img_height),
                chars=[],
                source="claude-vision",
                confidence=1.0
            ))

        ocr_output = OCROutput(
            image_path=str(image_path),
            dimensions={"width": img_width, "height": img_height},
            blocks=blocks,
            engine="claude-vision",
            metadata={
                "total_blocks": len(blocks),
                "avg_confidence": 1.0 if blocks else 0,
                "note": "Full-page transcription via Claude vision; no per-word "
                        "bounding boxes, text spans the whole page rect."
            }
        )

        logger.info(f"Extracted {len(blocks)} text block(s) via Claude Vision")
        return ocr_output


class CascadeOCR:
    """Run Tesseract first; only call Google Cloud Vision if Tesseract's
    confidence is too low. Keeps the common case free and local, and only
    pays for the GCV API call when it's actually needed.
    """

    def __init__(self, confidence_threshold: float = 0.75):
        """Initialize cascade OCR.

        Args:
            confidence_threshold: Minimum average Tesseract block confidence
                (0-1) to accept the Tesseract result. Below this, fall back
                to Google Cloud Vision.
        """
        self.confidence_threshold = confidence_threshold
        self.tesseract = TesseractOCR()
        self._gcv = None  # Lazily initialized so GCV credentials aren't required unless needed.

    @property
    def gcv(self) -> "GoogleCloudVisionOCR":
        if self._gcv is None:
            self._gcv = GoogleCloudVisionOCR()
        return self._gcv

    def extract_text(self, image_path: Path) -> OCROutput:
        """Extract text, escalating to GCV only when Tesseract looks unreliable.

        Args:
            image_path: Path to image file

        Returns:
            OCROutput from Tesseract or GCV, whichever was used
        """
        tesseract_result = self.tesseract.extract_text(image_path)
        tesseract_confidence = tesseract_result.metadata.get("avg_confidence", 0)

        if tesseract_confidence >= self.confidence_threshold:
            logger.info(
                f"Tesseract confidence {tesseract_confidence:.2f} >= threshold "
                f"{self.confidence_threshold:.2f}; skipping GCV"
            )
            tesseract_result.metadata["cascade_decision"] = "tesseract_accepted"
            tesseract_result.metadata["tesseract_confidence"] = tesseract_confidence
            return tesseract_result

        logger.info(
            f"Tesseract confidence {tesseract_confidence:.2f} < threshold "
            f"{self.confidence_threshold:.2f}; falling back to Google Cloud Vision"
        )
        try:
            gcv_result = self.gcv.extract_text(image_path)
            gcv_result.metadata["cascade_decision"] = "gcv_fallback"
            gcv_result.metadata["tesseract_confidence"] = tesseract_confidence
            return gcv_result
        except Exception as e:
            logger.error(f"GCV fallback failed ({e}); keeping Tesseract result")
            tesseract_result.metadata["cascade_decision"] = "gcv_fallback_failed"
            tesseract_result.metadata["tesseract_confidence"] = tesseract_confidence
            tesseract_result.metadata["gcv_error"] = str(e)
            return tesseract_result


class OCRExtractor:
    """Unified OCR extraction interface."""

    def __init__(self, engine: str = "auto", confidence_threshold: float = 0.75):
        """Initialize extractor with specified engine.

        Args:
            engine: OCR engine ("auto", "tesseract", "gcv", or
                "claude-vision"). "auto" runs Tesseract first and only
                escalates to GCV on low confidence. "claude-vision" is not
                part of the auto cascade -- it's a deliberate, heavier-cost
                choice for pages that defeat both Tesseract and GCV.
            confidence_threshold: Used by "auto" mode; see CascadeOCR.
        """
        self.engine = engine
        if engine == "tesseract":
            self.ocr = TesseractOCR()
        elif engine == "gcv":
            self.ocr = GoogleCloudVisionOCR()
        elif engine == "claude-vision":
            self.ocr = ClaudeVisionOCR()
        elif engine == "auto":
            self.ocr = CascadeOCR(confidence_threshold=confidence_threshold)
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

        if self.engine == "auto" and results:
            gcv_count = sum(1 for r in results if r.metadata.get("cascade_decision") == "gcv_fallback")
            logger.info(
                f"Cascade summary: {len(results) - gcv_count}/{len(results)} resolved by Tesseract, "
                f"{gcv_count}/{len(results)} escalated to GCV"
            )

        return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Step 2: OCR Extraction - Extract text with character-level coordinates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto cascade (default): Tesseract first, GCV only if confidence is low
  python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output

  # Force Tesseract only (no GCV fallback)
  python 02_ocr_extract.py --input image.jpg --output-dir ./ocr_output --engine tesseract

  # Force Google Cloud Vision for every image
  python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output --engine gcv

  # Full-page transcription via Claude's vision (OAuth, no API key) -- for
  # pages that defeat both Tesseract and GCV, e.g. cursive handwriting.
  # No per-word bounding boxes; slower and heavier than the other engines,
  # so not run automatically by --engine auto.
  python 02_ocr_extract.py --input image.jpg --output-dir ./ocr_output --engine claude-vision

  # Auto cascade with a stricter confidence threshold
  python 02_ocr_extract.py --input-dir ./prep_output --output-dir ./ocr_output \\
    --engine auto --confidence-threshold 0.85

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
        "--engine", choices=["auto", "tesseract", "gcv", "claude-vision"], default="auto",
        help="OCR engine: 'auto' tries Tesseract first and escalates to GCV only on low "
             "confidence (default), or force 'tesseract'/'gcv'/'claude-vision'. "
             "'claude-vision' transcribes the full page via Claude's vision (OAuth, no "
             "API key) -- much better on hard material like cursive handwriting, but no "
             "per-word bounding boxes, and not part of the 'auto' cascade since it's "
             "slower/heavier; pick it explicitly for pages that defeat Tesseract and GCV"
    )
    parser.add_argument(
        "--confidence-threshold", type=float, default=0.75,
        help="Minimum average Tesseract confidence (0-1) to accept its result in 'auto' "
             "mode before falling back to GCV (default: 0.75)"
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
        extractor = OCRExtractor(engine=args.engine, confidence_threshold=args.confidence_threshold)

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
