#!/usr/bin/env python3
"""
Step 3: Text Correction - Enhance difficult text using Claude/Gemini.

Identifies low-confidence OCR text blocks and sends them to Claude API for correction.
Supports both automatic batch mode and interactive manual correction mode.

Usage:
    python 03_text_correct.py --input ocr_output.json --output-dir ./corrected_output
    python 03_text_correct.py --input-dir ./ocr_output --output-dir ./corrected_output --threshold 0.8
    python 03_text_correct.py --input ocr_output.json --output-dir ./corrected_output --interactive
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
import os

from utils import (
    ensure_dir, OCRDataHandler, setup_logging,
    OCROutput, TextBlock, CharBound
)

logger = logging.getLogger(__name__)


class TextCorrector:
    """Correct OCR text using Claude API."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Claude client.

        Args:
            api_key: Anthropic API key (or from ANTHROPIC_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            logger.warning("No Anthropic API key found. Set ANTHROPIC_API_KEY environment variable.")
            self.client = None
        else:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
                logger.info("Claude API client initialized")
            except ImportError:
                logger.error("anthropic not installed. Install with: pip install anthropic")
                self.client = None

    def correct_text(self, text: str) -> str:
        """Correct text using Claude API.

        Args:
            text: OCR text to correct

        Returns:
            Corrected text
        """
        if not self.client:
            logger.warning("Claude client not available, returning original text")
            return text

        try:
            message = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": f"""You are an OCR correction specialist. The following text was extracted from an image using OCR and may contain errors. 
Please correct any obvious OCR errors (e.g., 'l' mistaken for '1', 'O' for '0', etc.) while preserving the original meaning and structure.
Only correct clear mistakes. If text is ambiguous, keep it as-is.
Return ONLY the corrected text, nothing else.

Original OCR text:
{text}"""
                    }
                ]
            )
            corrected = message.content[0].text.strip()
            logger.debug(f"Corrected: '{text}' → '{corrected}'")
            return corrected
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return text

    def process_ocr_output(
        self,
        ocr_output: OCROutput,
        confidence_threshold: float = 0.8,
        auto_correct: bool = False
    ) -> OCROutput:
        """Process OCR output, correcting low-confidence blocks.

        Args:
            ocr_output: OCR output to correct
            confidence_threshold: Only correct blocks below this confidence (0-1)
            auto_correct: Automatically correct, or ask for confirmation

        Returns:
            Corrected OCR output
        """
        corrected_blocks = []
        blocks_corrected = 0

        for block in ocr_output.blocks:
            if block.confidence < confidence_threshold:
                logger.info(f"Block below threshold ({block.confidence:.2f}): {block.text[:50]}")

                if auto_correct:
                    corrected_text = self.correct_text(block.text)
                    if corrected_text != block.text:
                        blocks_corrected += 1
                        block.text = corrected_text
                        block.source = "corrected"
                else:
                    # Interactive mode
                    print(f"\nLow confidence block (confidence: {block.confidence:.2f}):")
                    print(f"Current text: {block.text}")
                    print("Options:")
                    print("  1) Use Claude correction")
                    print("  2) Keep original")
                    print("  3) Manual edit")

                    choice = input("Choose (1-3): ").strip()

                    if choice == "1":
                        corrected_text = self.correct_text(block.text)
                        print(f"Claude suggestion: {corrected_text}")
                        use_correction = input("Use this correction? (y/n): ").strip().lower() == 'y'
                        if use_correction:
                            block.text = corrected_text
                            block.source = "corrected"
                            blocks_corrected += 1

                    elif choice == "3":
                        manual_text = input("Enter corrected text: ").strip()
                        if manual_text:
                            block.text = manual_text
                            block.source = "corrected"
                            blocks_corrected += 1

            corrected_blocks.append(block)

        ocr_output.blocks = corrected_blocks
        logger.info(f"Corrected {blocks_corrected} block(s)")

        return ocr_output


class TextCorrectionPipeline:
    """Pipeline for batch text correction."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize pipeline.

        Args:
            api_key: Anthropic API key
        """
        self.corrector = TextCorrector(api_key)

    def process_file(
        self,
        json_path: Path,
        output_dir: Path,
        confidence_threshold: float = 0.8,
        auto_correct: bool = False
    ) -> Path:
        """Process single OCR JSON file.

        Args:
            json_path: Path to OCR JSON file
            output_dir: Output directory
            confidence_threshold: Confidence threshold for correction
            auto_correct: Auto-correct or interactive

        Returns:
            Path to corrected JSON file
        """
        logger.info(f"Processing: {json_path}")

        ocr_output = OCRDataHandler.load_json(json_path)
        corrected_output = self.corrector.process_ocr_output(
            ocr_output,
            confidence_threshold=confidence_threshold,
            auto_correct=auto_correct
        )

        # Add correction metadata
        corrected_output.metadata["correction_threshold"] = confidence_threshold
        corrected_output.metadata["auto_corrected"] = auto_correct

        output_path = output_dir / f"{json_path.stem}_corrected.json"
        OCRDataHandler.save_json(corrected_output, output_path)

        return output_path

    def process_batch(
        self,
        input_dir: Path,
        output_dir: Path,
        confidence_threshold: float = 0.8,
        auto_correct: bool = False
    ) -> List[Path]:
        """Process all OCR JSON files in directory.

        Args:
            input_dir: Input directory with OCR JSON files
            output_dir: Output directory
            confidence_threshold: Confidence threshold for correction
            auto_correct: Auto-correct or interactive

        Returns:
            List of corrected file paths
        """
        input_dir = Path(input_dir)
        output_dir = ensure_dir(output_dir)

        if not input_dir.exists():
            raise FileNotFoundError(f"Input directory not found: {input_dir}")

        # Find OCR JSON files
        json_files = list(input_dir.glob("*_ocr.json"))
        if not json_files:
            logger.warning(f"No OCR JSON files found in {input_dir}")
            return []

        logger.info(f"Found {len(json_files)} OCR JSON file(s)")

        results = []
        for json_path in sorted(json_files):
            try:
                output_path = self.process_file(
                    json_path,
                    output_dir,
                    confidence_threshold=confidence_threshold,
                    auto_correct=auto_correct
                )
                results.append(output_path)
            except Exception as e:
                logger.error(f"Error processing {json_path}: {e}")
                continue

        return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Step 3: Text Correction - Enhance difficult OCR text using Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single file with automatic Claude correction
  python 03_text_correct.py --input ocr_output.json --output-dir ./corrected_output

  # Batch processing with custom threshold
  python 03_text_correct.py --input-dir ./ocr_output --output-dir ./corrected_output \\
    --threshold 0.75

  # Interactive mode for manual review
  python 03_text_correct.py --input ocr_output.json --output-dir ./corrected_output \\
    --interactive

  # Batch with aggressive correction (very low confidence only)
  python 03_text_correct.py --input-dir ./ocr_output --output-dir ./corrected_output \\
    --threshold 0.5 --auto

Note: Requires ANTHROPIC_API_KEY environment variable for Claude corrections.
Set ANTHROPIC_API_KEY in your .env file or system environment.
        """
    )

    parser.add_argument("--input", type=Path, help="Single OCR JSON file")
    parser.add_argument("--input-dir", type=Path, help="Input directory with OCR JSON files")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory for corrected JSON")
    parser.add_argument(
        "--threshold", type=float, default=0.8,
        help="Confidence threshold (0-1). Blocks below this are corrected (default: 0.8)"
    )
    parser.add_argument(
        "--interactive", "-i", action="store_true",
        help="Interactive mode - review each correction"
    )
    parser.add_argument(
        "--auto", "-a", action="store_true",
        help="Auto-correct mode - apply Claude corrections automatically"
    )
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
    if args.interactive and args.auto:
        parser.error("Cannot use both --interactive and --auto")

    # Default to auto mode if neither specified
    auto_correct = args.auto or (not args.interactive)

    try:
        pipeline = TextCorrectionPipeline()
        output_dir = ensure_dir(args.output_dir)

        if args.input:
            # Single file
            pipeline.process_file(
                args.input,
                output_dir,
                confidence_threshold=args.threshold,
                auto_correct=auto_correct
            )
            logger.info("Text correction complete")

        elif args.input_dir:
            # Batch processing
            results = pipeline.process_batch(
                args.input_dir,
                output_dir,
                confidence_threshold=args.threshold,
                auto_correct=auto_correct
            )
            logger.info(f"Batch processing complete: {len(results)} files processed")

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        exit(1)


if __name__ == "__main__":
    main()
