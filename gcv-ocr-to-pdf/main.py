"""OCR Batch Pipeline using Google Cloud Vision API.

This script processes TIFF and JPEG images to create searchable PDFs with:
- Google Cloud Vision API for OCR processing
- Character-level XY coordinate-based text overlay
- Batch processing for efficient API usage
- Support for multiple image formats

Features:
- Groups images by filename prefix
- Creates per-group PDFs with accurate OCR text placement
- Tracks character positions for precise overlay
- Optional debug mode with visible text bounding boxes

Usage:
    python main.py --input-dir ./images --output-dir ./pdfs \\
                   --project-id YOUR_PROJECT_ID \\
                   --credentials-path path/to/service-account-key.json
"""

import os
import sys
import argparse
import traceback
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO

import fitz  # PyMuPDF
from PIL import Image, ImageSequence
from tqdm import tqdm

try:
    from google.cloud import vision
    from google.oauth2 import service_account
except ImportError:
    print("Error: google-cloud-vision is not installed.")
    print("Install it with: pip install google-cloud-vision")
    sys.exit(1)


@dataclass
class TextBound:
    """Represents a single character or symbol with its bounding box."""
    text: str
    x: float
    y: float
    width: float
    height: float


@dataclass
class TextLine:
    """Represents a line of text with character-level bounds."""
    text: str
    x: float
    y: float
    width: float
    height: float
    bounds: List[TextBound]


class GoogleCloudVisionOCR:
    """Wrapper for Google Cloud Vision OCR API."""

    def __init__(self, credentials_path: Optional[str] = None, project_id: Optional[str] = None):
        """Initialize Google Cloud Vision client.
        
        Args:
            credentials_path: Path to service account JSON key file
            project_id: GCP project ID (used if credentials not from file)
        """
        if credentials_path:
            self.credentials = service_account.Credentials.from_service_account_file(credentials_path)
            self.client = vision.ImageAnnotatorClient(credentials=self.credentials)
        else:
            self.client = vision.ImageAnnotatorClient()
        self.project_id = project_id

    def extract_text_with_bounds(self, image_path: str) -> List[TextLine]:
        """Extract text and character-level bounding boxes from image using GCV.

        Args:
            image_path: Path to image file (TIFF or JPEG)

        Returns:
            List of TextLine objects with character-level bounds
        """
        with open(image_path, 'rb') as image_file:
            content = image_file.read()

        return self.extract_text_with_bounds_from_bytes(content)

    def extract_text_with_bounds_from_bytes(self, content: bytes) -> List[TextLine]:
        """Extract text and character-level bounding boxes from raw image bytes using GCV.

        Used for individual TIFF frames, which must be sent to GCV one at a
        time since document_text_detection only annotates a single page.

        Args:
            content: Encoded image bytes (e.g. PNG)

        Returns:
            List of TextLine objects with character-level bounds
        """
        image = vision.Image(content=content)
        response = self.client.document_text_detection(image=image)

        if response.error.message:
            raise ValueError(f"GCV API error: {response.error.message}")

        return self._parse_text_annotations(response)

    def _parse_text_annotations(self, response) -> List[TextLine]:
        """Parse GCV response into TextLine objects with character bounds.
        
        Args:
            response: Google Cloud Vision API response
            
        Returns:
            List of TextLine objects with character-level bounds
        """
        if not response.full_text_annotation:
            return []

        text_lines = []
        annotation = response.full_text_annotation

        for page in annotation.pages:
            for block in page.blocks:
                for paragraph in block.paragraphs:
                    line_text = ""
                    line_bounds = []
                    line_x, line_y = float('inf'), float('inf')
                    line_x_max, line_y_max = 0, 0

                    for word in paragraph.words:
                        word_text = ""
                        for symbol in word.symbols:
                            char = symbol.text
                            word_text += char
                            
                            bbox = symbol.bounding_box
                            if bbox.vertices:
                                vertices = [(v.x, v.y) for v in bbox.vertices]
                                x_coords = [v[0] for v in vertices]
                                y_coords = [v[1] for v in vertices]
                                
                                char_x = min(x_coords)
                                char_y = min(y_coords)
                                char_width = max(x_coords) - char_x
                                char_height = max(y_coords) - char_y
                                
                                line_x = min(line_x, char_x)
                                line_y = min(line_y, char_y)
                                line_x_max = max(line_x_max, char_x + char_width)
                                line_y_max = max(line_y_max, char_y + char_height)
                                
                                line_bounds.append(TextBound(
                                    text=char,
                                    x=char_x,
                                    y=char_y,
                                    width=char_width,
                                    height=char_height
                                ))

                        line_text += word_text + " "

                    if line_text.strip():
                        text_lines.append(TextLine(
                            text=line_text.strip(),
                            x=line_x,
                            y=line_y,
                            width=line_x_max - line_x,
                            height=line_y_max - line_y,
                            bounds=line_bounds
                        ))

        return text_lines


def ensure_dir(path: str) -> None:
    """Ensure directory exists."""
    Path(path).mkdir(parents=True, exist_ok=True)


def list_image_files(input_dir: str) -> List[str]:
    """List all TIFF and JPEG files in directory.
    
    Args:
        input_dir: Directory path to search
        
    Returns:
        Sorted list of image file paths
    """
    extensions = {'.tif', '.tiff', '.jpg', '.jpeg'}
    files = []
    
    for ext in extensions:
        files.extend(Path(input_dir).glob(f'*{ext}'))
        files.extend(Path(input_dir).glob(f'*{ext.upper()}'))
    
    return sorted([str(f) for f in files])


def group_image_files(files: List[str], split_char: str = '_') -> Dict[str, List[str]]:
    """Group image files by prefix before split character.
    
    Args:
        files: List of file paths
        split_char: Character to split on for grouping
        
    Returns:
        Dictionary mapping group name to list of files
    """
    groups = defaultdict(list)
    for f in files:
        basename = Path(f).stem
        group_key = basename.split(split_char)[0]
        groups[group_key].append(f)
    
    for group_files in groups.values():
        group_files.sort()
    
    return dict(groups)


def extract_frames_from_tiff(image_path: str) -> List[Image.Image]:
    """Extract all frames from a TIFF file.
    
    Args:
        image_path: Path to TIFF file
        
    Returns:
        List of PIL Image objects for each frame
    """
    frames = []
    try:
        img = Image.open(image_path)
        for frame in ImageSequence.Iterator(img):
            frame_copy = frame.convert('RGB')
            frames.append(frame_copy)
    except Exception as e:
        print(f"Warning: Could not extract frames from {image_path}: {e}")
        img = Image.open(image_path).convert('RGB')
        frames.append(img)
    
    return frames


def load_image_pages(image_path: str) -> List[Image.Image]:
    """Load every page/frame of an image file as PIL Images.

    Args:
        image_path: Path to image file

    Returns:
        List of PIL Image objects — one per TIFF frame, or a single-item
        list for other formats. Empty if the image could not be loaded.
    """
    try:
        img = Image.open(image_path)
        if img.format == 'TIFF':
            return extract_frames_from_tiff(image_path)
        return [img.convert('RGB')]
    except Exception as e:
        print(f"Error loading image {image_path}: {e}")
        return []


DEFAULT_DPI = 300.0


def get_image_dpi(pil_image: Image.Image) -> float:
    """Get the image's horizontal DPI from its metadata.

    Falls back to DEFAULT_DPI for scans without embedded resolution
    metadata, since pixel dimensions alone don't imply a physical size.

    Args:
        pil_image: PIL Image object

    Returns:
        Horizontal DPI as a float
    """
    dpi = pil_image.info.get('dpi')
    if dpi and dpi[0]:
        return float(dpi[0])
    return DEFAULT_DPI


def render_text_overlay(page, text_lines: List[TextLine], 
                       scale_factor: float = 1.0, debug: bool = False) -> None:
    """Render OCR text as invisible searchable overlay on PDF page.
    
    Args:
        page: PyMuPDF page object
        text_lines: List of TextLine objects with bounds
        scale_factor: Scale factor for coordinate adjustment
        debug: If True, draw visible red boxes around text
    """
    for line in text_lines:
        for bound in line.bounds:
            if not bound.text or bound.text.isspace():
                continue

            x = bound.x * scale_factor
            y = bound.y * scale_factor
            w = bound.width * scale_factor
            h = bound.height * scale_factor

            rect = fitz.Rect(x, y, x + w, y + h)

            if debug:
                page.draw_rect(rect, color=(1, 0, 0), width=0.5)
                page.insert_font(fontname="helv")
                page.insert_text((x, y - 2), bound.text, fontsize=8, color=(1, 0, 0))

            page.insert_text((x, y + h), bound.text, fontsize=max(1, h),
                            fontname="helv", render_mode=3)


def create_pdf_from_images_with_ocr(image_paths: List[str], 
                                    output_pdf: str,
                                    ocr_client: GoogleCloudVisionOCR,
                                    debug: bool = False) -> bool:
    """Create searchable PDF from images using OCR.
    
    Args:
        image_paths: List of image file paths in order
        output_pdf: Output PDF file path
        ocr_client: GoogleCloudVisionOCR instance
        debug: If True, create visible debug boxes
        
    Returns:
        True if successful, False otherwise
    """
    doc = fitz.open()

    for image_path in image_paths:
        try:
            pil_pages = load_image_pages(image_path)
            if not pil_pages:
                print(f"Skipping {image_path}: could not load")
                continue

            print(f"Extracting OCR from {Path(image_path).name}...")
            multi_page = len(pil_pages) > 1

            for page_index, pil_image in enumerate(pil_pages):
                image_bytes = BytesIO()
                pil_image.save(image_bytes, format='PNG')
                image_bytes.seek(0)
                img_data = image_bytes.read()

                pixmap = fitz.Pixmap(img_data)

                # GCV coordinates are in source pixels; PDF page dimensions
                # are in points (1/72"), so both must be scaled by the
                # image's DPI to produce a correctly sized, aligned page.
                scale_factor = 72.0 / get_image_dpi(pil_image)
                page_width = pixmap.width * scale_factor
                page_height = pixmap.height * scale_factor
                page_rect = fitz.Rect(0, 0, page_width, page_height)

                page = doc.new_page(width=page_width, height=page_height)
                page.insert_image(page_rect, pixmap=pixmap)

                # document_text_detection only annotates a single page, so
                # multi-frame TIFFs need OCR run per-frame on that frame's
                # own bytes; single-page images can reuse the source file.
                if multi_page:
                    text_lines = ocr_client.extract_text_with_bounds_from_bytes(img_data)
                else:
                    text_lines = ocr_client.extract_text_with_bounds(image_path)

                label = f"{Path(image_path).name} (frame {page_index + 1}/{len(pil_pages)})" if multi_page else Path(image_path).name
                if text_lines:
                    render_text_overlay(page, text_lines, scale_factor=scale_factor, debug=debug)
                    print(f"  {label}: found {len(text_lines)} text lines")
                else:
                    print(f"  {label}: no text detected")

        except Exception as e:
            print(f"Error processing {image_path}: {e}")
            traceback.print_exc()
            continue

    if len(doc) > 0:
        doc.save(output_pdf)
        doc.close()
        print(f"Saved PDF: {output_pdf}")
        return True
    else:
        print(f"Warning: No pages were added to PDF")
        return False


def process_image_groups(input_dir: str, 
                        output_dir: str,
                        ocr_client: GoogleCloudVisionOCR,
                        split_char: str = '_',
                        debug: bool = False,
                        dry_run: bool = False) -> None:
    """Process grouped images and create PDFs.
    
    Args:
        input_dir: Directory containing images
        output_dir: Directory for output PDFs
        ocr_client: GoogleCloudVisionOCR instance
        split_char: Character to split filename on for grouping
        debug: If True, create debug PDFs with visible boxes
        dry_run: If True, only list files without processing
    """
    files = list_image_files(input_dir)
    
    if not files:
        print(f"No image files found in {input_dir}")
        return

    print(f"Found {len(files)} image files")

    groups = group_image_files(files, split_char)
    print(f"Grouped into {len(groups)} groups")

    if dry_run:
        for group_name, group_files in sorted(groups.items()):
            print(f"  {group_name}: {len(group_files)} files")
        return

    ensure_dir(output_dir)

    for group_name, group_files in tqdm(sorted(groups.items()), desc="Processing groups"):
        output_pdf = os.path.join(output_dir, f"{group_name}.pdf")
        
        try:
            create_pdf_from_images_with_ocr(
                group_files, 
                output_pdf, 
                ocr_client,
                debug=debug
            )
        except Exception as e:
            print(f"Error processing group {group_name}: {e}")
            traceback.print_exc()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="OCR batch pipeline using Google Cloud Vision API"
    )
    parser.add_argument(
        '--input-dir', 
        required=True,
        help='Directory containing TIFF/JPEG images'
    )
    parser.add_argument(
        '--output-dir',
        required=True,
        help='Directory for output PDFs'
    )
    parser.add_argument(
        '--credentials-path',
        help='Path to GCP service account JSON key file'
    )
    parser.add_argument(
        '--project-id',
        help='GCP project ID'
    )
    parser.add_argument(
        '--split-char',
        default='_',
        help='Character to split filename on for grouping (default: _)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode with visible text boxes'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='List files without processing'
    )

    args = parser.parse_args()

    if not os.path.isdir(args.input_dir):
        print(f"Error: Input directory does not exist: {args.input_dir}")
        sys.exit(1)

    try:
        print("Initializing Google Cloud Vision client...")
        ocr_client = GoogleCloudVisionOCR(
            credentials_path=args.credentials_path,
            project_id=args.project_id
        )
        print("✓ GCV client initialized")

        process_image_groups(
            args.input_dir,
            args.output_dir,
            ocr_client,
            split_char=args.split_char,
            debug=args.debug,
            dry_run=args.dry_run
        )

        print("\nProcessing complete!")

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
