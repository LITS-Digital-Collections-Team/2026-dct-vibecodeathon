"""Batch OCR TIFF files into grouped searchable PDFs.

This script supports two OCR backends:
- Surya OCR via either the new predictor API or legacy Surya model API
- Tesseract OCR via pytesseract

It groups TIFF files by filename prefix, applies OCR per page, writes an image-based PDF page,
and overlays invisible searchable text. When debug mode is enabled, it also creates a
visible validation PDF with red bounding boxes and text for manual inspection.

This script was created with assistance from GitHub Copilot.
"""

import sys
import os
import torch
import io
import argparse
import traceback
from PIL import Image, ImageSequence
from tqdm import tqdm
from collections import defaultdict

# Disable torch.compile for this script to avoid Surya runtime meta-device failures.
if hasattr(torch, 'compile'):
    torch.compile = lambda model, **kwargs: model

# Set cache before importing surya to ensure it uses the right path
os.environ["HUGGINGFACE_HUB_CACHE"] = os.path.join(os.path.expanduser("~"), ".cache", "huggingface")

SURYA_API = None

try:
    import fitz  # PyMuPDF
    from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS, _compute_linear_scaling_rope_parameters

    from surya.common.surya.schema import TaskNames
    from surya.common.surya import SuryaModel
    from surya.common.surya.decoder import config as surya_decoder_config
    from surya.common.surya.encoder import Qwen2_5_VisionRotaryEmbedding
    from surya.detection import DetectionPredictor
    from surya.foundation import FoundationPredictor
    from surya.recognition import RecognitionPredictor
    from surya.foundation.loader import FoundationModelLoader
    from surya.settings import settings

    _orig_qwen_init = Qwen2_5_VisionRotaryEmbedding.__init__
    def _patched_qwen_init(self, dim: int, theta: float = 10000.0, *args, **kwargs):
        _orig_qwen_init(self, dim, theta, *args, **kwargs)
        self._rotary_dim = dim
        self._rotary_theta = theta
    Qwen2_5_VisionRotaryEmbedding.__init__ = _patched_qwen_init

    _orig_qwen_forward = Qwen2_5_VisionRotaryEmbedding.forward
    def _patched_qwen_forward(self, seqlen: int):
        if isinstance(self.inv_freq, torch.Tensor) and getattr(self.inv_freq, 'is_meta', False):
            inv_freq = 1.0 / (
                self._rotary_theta
                ** (
                    torch.arange(0, self._rotary_dim, 2, dtype=torch.float32, device='cpu')
                    / self._rotary_dim
                )
            )
        else:
            inv_freq = self.inv_freq
        seq = torch.arange(seqlen, device='cpu', dtype=inv_freq.dtype)
        return torch.outer(seq, inv_freq)
    Qwen2_5_VisionRotaryEmbedding.forward = _patched_qwen_forward

    # Fix missing tied output embeddings on some Surya checkpoints and clear meta tensors.
    _orig_foundation_model = FoundationModelLoader.model
    def _patch_meta_tensors(module):
        for submodule in module.modules():
            for name, value in list(submodule.__dict__.items()):
                if isinstance(value, torch.Tensor) and value.is_meta:
                    submodule.__dict__[name] = value.to("cpu")
            for name, param in list(submodule._parameters.items()):
                if isinstance(param, torch.Tensor) and param.is_meta:
                    submodule._parameters[name] = param.to("cpu")
            for name, buffer in list(submodule._buffers.items()):
                if isinstance(buffer, torch.Tensor) and buffer.is_meta:
                    submodule._buffers[name] = buffer.to("cpu")

    def _patched_foundation_model(self, device=settings.TORCH_DEVICE_MODEL, dtype=None, attention_implementation=None):
        model = _orig_foundation_model(self, device, dtype, attention_implementation)
        try:
            if hasattr(model, 'tie_weights'):
                model.tie_weights()
        except Exception:
            pass
        try:
            _patch_meta_tensors(model)
        except Exception:
            pass
        return model
    FoundationModelLoader.model = _patched_foundation_model

    if not hasattr(surya_decoder_config.SuryaDecoderConfig, "pad_token_id"):
        surya_decoder_config.SuryaDecoderConfig.pad_token_id = None

    def _surya_all_tied_weights_keys(self):
        tied = getattr(self, "_tied_weights_keys", [])
        if isinstance(tied, dict):
            return tied
        return dict.fromkeys(tied)

    SuryaModel.all_tied_weights_keys = property(_surya_all_tied_weights_keys)

    def _surya_tie_weights(self, missing_keys=None, recompute_mapping=False):
        self._tie_weights()

    SuryaModel.tie_weights = _surya_tie_weights

    def _surya_tie_or_clone_weights(self, output_embeddings, input_embeddings):
        if hasattr(output_embeddings, "weight") and hasattr(input_embeddings, "weight"):
            if output_embeddings.weight.shape == input_embeddings.weight.shape:
                output_embeddings.weight = input_embeddings.weight
        return output_embeddings

    SuryaModel._tie_or_clone_weights = _surya_tie_or_clone_weights

    def _surya_default_rope_init_fn(config, device=None, seq_len=None, layer_type=None):
        try:
            return _compute_linear_scaling_rope_parameters(
                config, device=device, seq_len=seq_len, layer_type=layer_type
            )
        except KeyError as e:
            if e.args and e.args[0] == 'factor':
                if not hasattr(config, 'rope_parameters'):
                    config.rope_parameters = {}
                if layer_type is not None:
                    config.rope_parameters.setdefault(layer_type, {})
                    config.rope_parameters[layer_type].setdefault('factor', 1.0)
                    config.rope_parameters[layer_type].setdefault(
                        'rope_theta', getattr(config, 'rope_theta', 10000.0)
                    )
                else:
                    config.rope_parameters.setdefault('factor', 1.0)
                    config.rope_parameters.setdefault(
                        'rope_theta', getattr(config, 'rope_theta', 10000.0)
                    )
                return _compute_linear_scaling_rope_parameters(
                    config, device=device, seq_len=seq_len, layer_type=layer_type
                )
            raise

    ROPE_INIT_FUNCTIONS['default'] = _surya_default_rope_init_fn

    SURYA_API = "predictor"
    print("Surya predictor API loaded successfully.")

except ImportError:
    try:
        import fitz  # PyMuPDF

        from surya.model.detection.model import load_model as load_det_model, load_processor as load_det_processor
        from surya.model.recognition.model import load_model as load_rec_model
        from surya.model.recognition.processor import load_rec_processor
        from surya.detection import batch_detection
        from surya.recognition import batch_recognition
        from surya.ocr import run_ocr

        SURYA_API = "legacy"
        print("Legacy surya.model API loaded successfully.")

    except ImportError as e:
        print(f"CRITICAL ERROR: {e}")
        print("\nAttempting to find where 'surya' is installed...")
        os.system(f'"{sys.executable}" -m pip show surya-ocr')
        sys.exit(1)

def get_default_surya_device():
    """Return the preferred Surya device: CUDA, MPS, or CPU."""
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def get_safe_surya_dtype(device):
    """Choose a safe Surya dtype based on the selected device."""
    if device == "cpu":
        return torch.float32
    if device == "cuda":
        return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    return torch.float32


def tesseract_ocr_page(img_rgb):
    """Run OCR with Tesseract and return a list of text lines and bounding boxes.

    Each returned item is a dictionary with keys:
    - text: recognized text string
    - bbox: (left, top, right, bottom)
    """
    try:
        import pytesseract
        from pytesseract import Output
    except ImportError:
        raise RuntimeError(
            "Tesseract OCR requires pytesseract. Install it with 'python -m pip install pytesseract' "
            "and ensure the Tesseract executable is available on PATH."
        )

    data = pytesseract.image_to_data(img_rgb, output_type=Output.DICT)
    lines = []

    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        lines.append(
            {
                "text": text,
                "bbox": (
                    data["left"][i],
                    data["top"][i],
                    data["left"][i] + data["width"][i],
                    data["top"][i] + data["height"][i],
                ),
            }
        )

    if not lines:
        full_text = pytesseract.image_to_string(img_rgb).strip()
        if full_text:
            lines.append(
                {"text": full_text, "bbox": (0, 0, img_rgb.width, img_rgb.height)}
            )

    return lines


def ensure_dir(path):
    """Create a directory if it does not already exist."""
    if path and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def list_tiff_files(input_dir):
    """Return a sorted list of TIFF files from the input directory."""
    return sorted(
        f for f in os.listdir(input_dir) if f.lower().endswith((".tif", ".tiff"))
    )


def group_tiff_files(files, split_char):
    """Group TIFF files by filename prefix, using split_char as the separator."""
    groups = defaultdict(list)
    for filename in files:
        group_key = filename.split(split_char)[0] if split_char in filename else os.path.splitext(filename)[0]
        groups[group_key].append(filename)
    return groups


def count_group_pages(input_dir, files):
    """Count total image frames/pages in a group of TIFF files."""
    pages = 0
    for filename in files:
        try:
            with Image.open(os.path.join(input_dir, filename)) as img:
                pages += getattr(img, "n_frames", 1)
        except Exception:
            pass
    return pages


def confirm_proceed(dry_run):
    """Prompt the user to confirm whether OCR should proceed in dry-run mode."""
    if not dry_run:
        return True
    response = input("\nProceed with OCR? (y/n): ").strip().lower()
    return response == "y"


def init_surya_predictors(device, checkpoint, requested_engine):
    """Initialize Surya OCR predictors or fallback to Tesseract.

    This helper supports both the new Surya predictor API and the legacy model API.
    If Surya is unavailable and the engine is set to auto, it returns a context that
    triggers Tesseract fallback.
    """
    if SURYA_API is None:
        if requested_engine == "auto":
            return {"type": "tesseract"}
        raise RuntimeError(
            "Surya is not available in this environment. "
            "Install surya-ocr or use --engine tesseract."
        )

    if SURYA_API == "predictor":
        surya_device = device or get_default_surya_device()
        if surya_device == "cuda" and not torch.cuda.is_available():
            print("WARNING: CUDA requested but not available. Falling back to CPU.")
            surya_device = "cpu"
        if surya_device == "mps" and not hasattr(torch.backends, "mps"):
            print("WARNING: MPS requested but not available. Falling back to CPU.")
            surya_device = "cpu"

        surya_dtype = get_safe_surya_dtype(surya_device)
        det_dtype = torch.float32 if surya_device in {"cpu", "mps"} else torch.float16

        print(
            f"Using Surya checkpoint={checkpoint or 'default'} device={surya_device}, dtype={surya_dtype}"
        )

        try:
            foundation_predictor = FoundationPredictor(
                checkpoint=checkpoint,
                device=surya_device,
                dtype=surya_dtype,
            )
            det_predictor = DetectionPredictor(
                device=surya_device,
                dtype=det_dtype,
            )
            rec_predictor = RecognitionPredictor(foundation_predictor)

            if not hasattr(foundation_predictor.model, "lm_head") or not hasattr(
                foundation_predictor.model.lm_head, "weight"
            ) or foundation_predictor.model.lm_head.weight.numel() == 0:
                raise RuntimeError(
                    "Surya foundation model is missing lm_head.weight or has an empty output head. "
                    "This often means the checkpoint is incomplete or incompatible. "
                    "Use --checkpoint to override the default Surya model."
                )

            return {
                "type": "predictor",
                "det_predictor": det_predictor,
                "rec_predictor": rec_predictor,
            }
        except Exception:
            if requested_engine == "auto":
                print("WARNING: Surya initialization failed. Falling back to Tesseract.")
                traceback.print_exc()
                return {"type": "tesseract"}
            print("WARNING: Surya predictor initialization failed. Retrying with CPU float32.")
            traceback.print_exc()
            surya_device = "cpu"
            surya_dtype = torch.float32
            det_dtype = torch.float32
            foundation_predictor = FoundationPredictor(
                checkpoint=checkpoint,
                device=surya_device,
                dtype=surya_dtype,
            )
            det_predictor = DetectionPredictor(
                device=surya_device,
                dtype=det_dtype,
            )
            rec_predictor = RecognitionPredictor(foundation_predictor)
            return {
                "type": "predictor",
                "det_predictor": det_predictor,
                "rec_predictor": rec_predictor,
            }

    effective_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    if effective_device == "cuda" and not torch.cuda.is_available():
        print("WARNING: CUDA requested but not available. Falling back to CPU.")
        effective_device = "cpu"

    det_model, det_processor = load_det_model(), load_det_processor()
    rec_model, rec_processor = load_rec_model(), load_rec_processor()
    det_model.to(effective_device)
    rec_model.to(effective_device)
    return {
        "type": "legacy",
        "det_model": det_model,
        "det_processor": det_processor,
        "rec_model": rec_model,
        "rec_processor": rec_processor,
    }


def extract_text_lines(
    img_rgb,
    ocr_engine,
    engine_context,
    requested_engine,
    languages,
):
    """Extract OCR text lines from a single image page.

    This helper delegates to Surya when available or falls back to Tesseract.
    It returns a tuple of (lines, effective_engine) so auto-fallback can switch engines.
    """
    if ocr_engine != "surya":
        return tesseract_ocr_page(img_rgb), ocr_engine

    if engine_context["type"] == "tesseract":
        return tesseract_ocr_page(img_rgb), "tesseract"

    if engine_context["type"] == "predictor":
        try:
            predictions = engine_context["rec_predictor"](
                [img_rgb],
                task_names=[TaskNames.ocr_with_boxes],
                det_predictor=engine_context["det_predictor"],
                highres_images=None,
                math_mode=False,
            )
            ocr_result = predictions[0]
            return (
                [{"text": line.text, "bbox": line.bbox} for line in ocr_result.text_lines],
                ocr_engine,
            )
        except Exception:
            if requested_engine == "auto":
                print("WARNING: Surya page failed. Falling back to Tesseract for this page.")
                traceback.print_exc()
                return tesseract_ocr_page(img_rgb), "tesseract"
            raise

    predictions = run_ocr(
        [img_rgb],
        [languages],
        engine_context["det_model"],
        engine_context["det_processor"],
        engine_context["rec_model"],
        engine_context["rec_processor"],
    )
    ocr_result = predictions[0]
    return ([{"text": line.text, "bbox": line.bbox} for line in ocr_result.text_lines], ocr_engine)


def render_text_lines(page, lines, debug_page=None):
    """Overlay invisible OCR text onto the PDF page and optional debug markup."""
    for line in lines:
        bbox = line["bbox"]
        line_height = bbox[3] - bbox[1]
        fontsize = max(1, line_height * 0.75)
        rect = fitz.Rect(bbox[0], bbox[1], bbox[2], bbox[3])

        page.insert_textbox(
            rect,
            line["text"],
            fontsize=fontsize,
            fontname="helv",
            render_mode=3,
            align=0,
        )

        if debug_page is not None:
            debug_page.draw_rect(rect, color=(1, 0, 0), width=1)
            debug_page.insert_text(
                rect.tl,
                line["text"],
                fontsize=max(6, min(fontsize, 24)),
                fontname="helv",
                color=(1, 0, 0),
            )


def create_grouped_ocr_pdfs(
    input_dir,
    output_dir,
    log_dir="ocr_logs",
    split_char="_",
    languages=["en"],
    dry_run=True,
    device=None,
    checkpoint=None,
    ocr_engine="auto",
    debug=False,
    validation_dir="validation_pdfs",
):
    """Run OCR across grouped TIFF files and write searchable PDFs.

    Groups are formed by splitting filenames on `split_char`. Each group becomes one
    output PDF file and one text log. If debug mode is enabled, a second validation
    PDF is written with visible bounding boxes and text.
    """
    if not os.path.isdir(input_dir):
        print(f"Error: The input directory '{input_dir}' does not exist.")
        return

    if device is not None and device not in {"cpu", "cuda", "mps"}:
        print(f"Warning: Unsupported device '{device}' specified. Falling back to auto-select.")
        device = None

    if ocr_engine not in {"surya", "tesseract", "auto"}:
        raise ValueError("Unsupported OCR engine. Choose 'surya', 'tesseract', or 'auto'.")

    requested_engine = ocr_engine
    engine_context = None
    if requested_engine == "auto" and SURYA_API is None:
        print("Surya is not available, falling back to Tesseract.")
        ocr_engine = "tesseract"
        engine_context = {"type": "tesseract"}

    ensure_dir(output_dir)
    ensure_dir(log_dir)
    if debug:
        ensure_dir(validation_dir)

    all_files = list_tiff_files(input_dir)
    if not all_files:
        print(f"No TIFF files found in {input_dir}")
        return

    groups = group_tiff_files(all_files, split_char)
    group_stats = [
        (group_name, files, count_group_pages(input_dir, files))
        for group_name, files in groups.items()
    ]

    total_pages = sum(page_count for _, _, page_count in group_stats)
    print("--- Grouping Summary ---")
    for group_name, files, page_count in group_stats:
        print(f"Group: {group_name} | Files: {len(files)} | Pages: {page_count}")

    print(f"\nTOTAL: {len(group_stats)} PDF(s) to create | {total_pages} Total Pages")
    if not confirm_proceed(dry_run):
        print("OCR canceled by user.")
        return

    engine_context = None
    if ocr_engine == "surya":
        engine_context = init_surya_predictors(device, checkpoint, requested_engine)
        if engine_context["type"] == "tesseract":
            ocr_engine = "tesseract"

    if ocr_engine == "tesseract":
        print("Using Tesseract OCR engine. Ensure Tesseract is installed and pytesseract is available.")

    with tqdm(total=total_pages, desc="Overall Progress", unit="page") as pbar:
        for group_name, files, _ in group_stats:
            pdf_doc = fitz.open()
            debug_doc = fitz.open() if debug else None
            log_path = os.path.join(log_dir, f"{group_name}.txt")

            with open(log_path, "w", encoding="utf-8") as log_file:
                log_file.write(f"OCR LOG FOR GROUP: {group_name}\n{'='*40}\n")

                for filename in files:
                    img_path = os.path.join(input_dir, filename)
                    try:
                        with Image.open(img_path) as container:
                            for page_index, frame in enumerate(ImageSequence.Iterator(container)):
                                try:
                                    img_rgb = frame.convert("RGB")
                                    page = pdf_doc.new_page(width=img_rgb.width, height=img_rgb.height)
                                    img_buffer = io.BytesIO()
                                    img_rgb.save(img_buffer, format="JPEG", quality=80)
                                    page.insert_image(page.rect, stream=img_buffer.getvalue())

                                    debug_page = None
                                    if debug:
                                        debug_page = debug_doc.new_page(
                                            width=img_rgb.width, height=img_rgb.height
                                        )
                                        debug_page.insert_image(debug_page.rect, stream=img_buffer.getvalue())

                                    lines, ocr_engine = extract_text_lines(
                                        img_rgb,
                                        ocr_engine,
                                        engine_context,
                                        requested_engine,
                                        languages,
                                    )

                                    log_file.write(f"\n[Source: {filename} | Page: {page_index + 1}]\n")
                                    for line in lines:
                                        log_file.write(line["text"] + "\n")

                                    render_text_lines(page, lines, debug_page=debug_page)

                                except Exception as e:
                                    log_file.write(f"\nERROR on {filename} page {page_index + 1}: {e}\n")
                                    pdf_doc.new_page(width=612, height=792).insert_text((50, 50), "OCR Failed.")
                                finally:
                                    pbar.update(1)
                    except Exception as e:
                        print(f"Could not open {filename}: {e}")

            if len(pdf_doc) > 0:
                pdf_doc.save(os.path.join(output_dir, f"{group_name}.pdf"))
            if debug and debug_doc is not None and len(debug_doc) > 0:
                debug_doc.save(os.path.join(validation_dir, f"{group_name}_validation.pdf"))
            if debug_doc is not None:
                debug_doc.close()
            pdf_doc.close()

    print(f"\nProcessing Complete. Outputs in '{output_dir}' and '{log_dir}'.")

if __name__ == "__main__":
    # Example usage:
    #   python batch_ocr_to_pdf.py C:\path\to\tiffs --engine auto --output C:\path\to\pdfs --debug
    # This will group TIFF files, run OCR with Surya if available, fall back to Tesseract,
    # create searchable PDFs, and write debug validation PDFs with visible overlays.
    parser = argparse.ArgumentParser(description="Batch OCR TIFF files into grouped PDFs.")
    parser.add_argument("input", nargs="?", help="Directory containing the .tif files")
    parser.add_argument("--output", default="./output_pdfs", help="Directory for output PDFs")
    parser.add_argument("--logs", default="./ocr_logs", help="Directory for OCR text logs")
    parser.add_argument("--char", default="_", help="Character to split filenames")
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"], default=None, help="Force Surya device. Defaults to auto-select.")
    parser.add_argument("--checkpoint", default=None, help="Override Surya foundation checkpoint path or s3 URL.")
    parser.add_argument("--engine", choices=["surya", "tesseract", "auto"], default="auto", help="Choose OCR backend: surya, tesseract, or auto (Try Surya then fallback to Tesseract).")
    parser.add_argument("--debug", action="store_true", help="Produce a validation PDF with visible OCR overlay in addition to the searchable output.")
    parser.add_argument("--validation-dir", default="./validation_pdfs", help="Directory for debug validation PDFs when --debug is enabled.")
    parser.add_argument("--nodry", action="store_false", dest="dry_run", help="Skip the dry-run confirmation")

    args = parser.parse_args()

    if not args.input:
        args.input = input("Please enter the path to the TIFF files directory: ").strip()

    args.input = args.input.replace('"', '').replace("'", "")

    if args.input:
        create_grouped_ocr_pdfs(
            input_dir=args.input,
            output_dir=args.output,
            log_dir=args.logs,
            split_char=args.char,
            dry_run=args.dry_run,
            device=args.device,
            checkpoint=args.checkpoint,
            ocr_engine=args.engine,
            debug=args.debug,
            validation_dir=args.validation_dir,
        )