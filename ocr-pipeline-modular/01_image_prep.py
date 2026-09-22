#!/usr/bin/env python3
"""
Step 1: Image Preparation - Convert TIFF to optimized JPG/PNG.

Converts TIFF images to optimized JPG format, resizing to max width while
preserving aspect ratio. Saves preparation metadata for downstream processing.

Usage:
    python 01_image_prep.py --input-dir ./input --output-dir ./prep_output
    python 01_image_prep.py --input /path/to/file.tiff --output-dir ./prep_output
"""

import argparse
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image
import json

from utils import ensure_dir, get_output_filename, OCRDataHandler, setup_logging

logger = logging.getLogger(__name__)


class ImagePreparator:
    """Prepare images for OCR processing."""

    def __init__(self, max_width: int = 1000, jpg_quality: int = 85):
        """Initialize image preparator.

        Args:
            max_width: Maximum width for output images (pixels)
            jpg_quality: JPEG quality (1-95)
        """
        self.max_width = max_width
        self.jpg_quality = jpg_quality

    def prepare_image(self, input_path: Path, output_dir: Path) -> Dict[str, Any]:
        """Process single TIFF image.

        Args:
            input_path: Path to TIFF file
            output_dir: Output directory for processed images

        Returns:
            Dictionary with preparation metadata
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        logger.info(f"Processing: {input_path}")

        # Open image
        try:
            img = Image.open(input_path)
        except Exception as e:
            logger.error(f"Failed to open image {input_path}: {e}")
            raise

        original_width, original_height = img.size
        frame_count = 1

        # Handle multi-frame TIFF (return first frame)
        try:
            frame_count = img.n_frames
            if frame_count > 1:
                logger.warning(f"Multi-frame TIFF detected ({frame_count} frames), using first frame")
                img.seek(0)
        except AttributeError:
            pass

        # Calculate scaling factor
        if original_width > self.max_width:
            scale_factor = self.max_width / original_width
            new_width = self.max_width
            new_height = int(original_height * scale_factor)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            logger.info(f"Resized: {original_width}x{original_height} → {new_width}x{new_height}")
        else:
            scale_factor = 1.0
            new_width, new_height = original_width, original_height
            logger.info(f"Image already within max width ({original_width}px), no resize needed")

        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Save as JPG
        output_path = output_dir / get_output_filename(input_path, output_dir, "prep", "jpg").name
        try:
            img.save(output_path, "JPEG", quality=self.jpg_quality, optimize=True)
            logger.info(f"Saved: {output_path}")
        except Exception as e:
            logger.error(f"Failed to save image {output_path}: {e}")
            raise

        # Prepare metadata
        metadata = {
            "original_path": str(input_path),
            "output_path": str(output_path),
            "original_dimensions": {
                "width": original_width,
                "height": original_height
            },
            "output_dimensions": {
                "width": new_width,
                "height": new_height
            },
            "scale_factor": scale_factor,
            "jpg_quality": self.jpg_quality,
            "frames": frame_count,
            "format": img.format
        }

        return metadata

    def process_batch(
        self, input_dir: Path, output_dir: Path, recursive: bool = False, workers: int = 1
    ) -> Dict[str, Any]:
        """Process all TIFF files in directory.

        Args:
            input_dir: Input directory
            output_dir: Output directory
            recursive: If True, also scan subdirectories of input_dir, and
                mirror each file's subfolder path under output_dir (so a
                later --merge-per-folder in Step 4 can group pages back up
                by their original folder).
            workers: Number of images to resize/encode concurrently, using
                separate processes (this step is CPU-bound, unlike Steps
                2-3's network calls, so a process pool actually parallelizes
                it instead of just overlapping I/O wait).

        Returns:
            Dictionary with batch metadata
        """
        input_dir = Path(input_dir)
        output_dir = ensure_dir(output_dir)

        if not input_dir.exists():
            raise FileNotFoundError(f"Input directory not found: {input_dir}")

        # Find TIFF files
        if recursive:
            tiff_files = list(input_dir.rglob("*.tif")) + list(input_dir.rglob("*.tiff"))
        else:
            tiff_files = list(input_dir.glob("*.tif")) + list(input_dir.glob("*.tiff"))
        if not tiff_files:
            logger.warning(f"No TIFF files found in {input_dir}")
            return {"files_processed": 0, "files": []}

        sorted_files = sorted(tiff_files)
        logger.info(f"Found {len(sorted_files)} TIFF file(s), {workers} worker(s)")

        batch_metadata = {
            "input_directory": str(input_dir),
            "output_directory": str(output_dir),
            "recursive": recursive,
            "files_processed": 0,
            "files": [],
            "total_original_size": 0,
            "total_output_size": 0
        }

        def _target_dir(tiff_path: Path) -> Path:
            relative_dir = tiff_path.parent.relative_to(input_dir)
            return ensure_dir(output_dir / relative_dir) if str(relative_dir) != "." else output_dir

        results_by_path: Dict[Path, Dict[str, Any]] = {}
        if workers > 1:
            # Target directories are created up front since ensure_dir()'s
            # mkdir isn't safe to run concurrently from worker processes.
            target_dirs = {p: _target_dir(p) for p in sorted_files}
            with ProcessPoolExecutor(max_workers=workers) as executor:
                future_to_path = {
                    executor.submit(self.prepare_image, p, target_dirs[p]): p for p in sorted_files
                }
                for future in as_completed(future_to_path):
                    tiff_path = future_to_path[future]
                    try:
                        results_by_path[tiff_path] = future.result()
                    except Exception as e:
                        logger.error(f"Error processing {tiff_path}: {e}")
        else:
            for tiff_path in sorted_files:
                try:
                    results_by_path[tiff_path] = self.prepare_image(tiff_path, _target_dir(tiff_path))
                except Exception as e:
                    logger.error(f"Error processing {tiff_path}: {e}")
                    continue

        for tiff_path in sorted_files:
            if tiff_path in results_by_path:
                batch_metadata["files"].append(results_by_path[tiff_path])
                batch_metadata["files_processed"] += 1

        return batch_metadata


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Step 1: Image Preparation - Convert TIFF to optimized JPG/PNG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single file
  python 01_image_prep.py --input sample.tiff --output-dir ./prep_output

  # Batch processing directory
  python 01_image_prep.py --input-dir ./images --output-dir ./prep_output

  # With custom settings
  python 01_image_prep.py --input-dir ./images --output-dir ./prep_output \\
    --max-width 1200 --quality 90

  # Recurse into subfolders, mirroring their structure under --output-dir
  # (each subfolder's pages can later be merged into one PDF in Step 4)
  python 01_image_prep.py --input-dir ./scans --output-dir ./prep_output --recursive
        """
    )

    parser.add_argument("--input", type=Path, help="Single input TIFF file")
    parser.add_argument("--input-dir", type=Path, help="Input directory with TIFF files")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory for processed images")
    parser.add_argument("--max-width", type=int, default=1000, help="Maximum image width (default: 1000)")
    parser.add_argument("--quality", type=int, default=85, help="JPEG quality 1-95 (default: 85)")
    parser.add_argument(
        "--recursive", action="store_true",
        help="With --input-dir, also scan subfolders and mirror their structure "
             "under --output-dir"
    )
    parser.add_argument(
        "--workers", type=int, default=4,
        help="With --input-dir, number of images to resize/encode concurrently, "
             "using separate processes (default: 4). Set to 1 to disable."
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

    try:
        preparator = ImagePreparator(max_width=args.max_width, jpg_quality=args.quality)
        output_dir = ensure_dir(args.output_dir)

        if args.input:
            # Single file
            metadata = preparator.prepare_image(args.input, output_dir)
            OCRDataHandler.save_pretty_json(metadata, output_dir / f"{args.input.stem}_metadata.json")
            logger.info("Image preparation complete")

        elif args.input_dir:
            # Batch processing
            batch_metadata = preparator.process_batch(
                args.input_dir, output_dir, recursive=args.recursive, workers=args.workers
            )
            OCRDataHandler.save_pretty_json(
                batch_metadata,
                output_dir / "batch_metadata.json"
            )
            logger.info(f"Batch processing complete: {batch_metadata['files_processed']} files processed")

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        exit(1)


if __name__ == "__main__":
    # Required for --workers > 1's ProcessPoolExecutor: when this script is
    # frozen (PyInstaller), a spawned worker process re-executes this same
    # frozen binary, and freeze_support() is what lets it recognize that
    # re-invocation as a multiprocessing worker instead of parsing sys.argv
    # as this script's own CLI args. A no-op on non-frozen/non-Windows runs.
    multiprocessing.freeze_support()
    main()
