"""
Shared utilities and data classes for OCR pipeline.

Provides common data structures and helper functions for all pipeline steps,
ensuring consistency across image preparation, OCR extraction, text correction,
and PDF assembly.
"""

import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class CharBound:
    """Single character with bounding box and confidence."""
    char: str
    x: float
    y: float
    width: float
    height: float
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CharBound':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class TextBlock:
    """Text block with coordinates and character-level bounds."""
    text: str
    x: float
    y: float
    width: float
    height: float
    chars: List[CharBound] = field(default_factory=list)
    source: str = "ocr"  # "ocr" or "corrected"
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data['chars'] = [char.to_dict() for char in self.chars]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TextBlock':
        """Create from dictionary."""
        chars_data = data.pop('chars', [])
        block = cls(**data)
        block.chars = [CharBound.from_dict(char) for char in chars_data]
        return block


@dataclass
class OCROutput:
    """Complete OCR output with all blocks and metadata."""
    image_path: str
    dimensions: Dict[str, int]  # {width, height}
    blocks: List[TextBlock] = field(default_factory=list)
    engine: str = "tesseract"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data['blocks'] = [block.to_dict() for block in self.blocks]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OCROutput':
        """Create from dictionary."""
        blocks_data = data.pop('blocks', [])
        output = cls(**data)
        output.blocks = [TextBlock.from_dict(block) for block in blocks_data]
        return output


class OCRDataHandler:
    """Handle saving and loading OCR data with validation."""

    @staticmethod
    def save_json(data: OCROutput, output_path: Path) -> None:
        """Save OCR output to JSON file."""
        try:
            ensure_dir(output_path.parent)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"Saved OCR data to {output_path}")
        except Exception as e:
            logger.error(f"Failed to save JSON to {output_path}: {e}")
            raise

    @staticmethod
    def load_json(json_path: Path) -> OCROutput:
        """Load OCR output from JSON file."""
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            ocr_output = OCROutput.from_dict(data)
            logger.info(f"Loaded OCR data from {json_path}")
            return ocr_output
        except Exception as e:
            logger.error(f"Failed to load JSON from {json_path}: {e}")
            raise

    @staticmethod
    def save_pretty_json(data: Dict[str, Any], output_path: Path) -> None:
        """Save arbitrary data as pretty JSON."""
        try:
            ensure_dir(output_path.parent)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved data to {output_path}")
        except Exception as e:
            logger.error(f"Failed to save JSON to {output_path}: {e}")
            raise

    @staticmethod
    def load_json_dict(json_path: Path) -> Dict[str, Any]:
        """Load arbitrary JSON file as dictionary."""
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"Loaded data from {json_path}")
            return data
        except Exception as e:
            logger.error(f"Failed to load JSON from {json_path}: {e}")
            raise


def ensure_dir(directory: Path) -> Path:
    """Ensure directory exists, create if needed."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# --- Where things live, in a source checkout and inside a frozen build -----
# PyInstaller unpacks the bundled payload into a temp directory it deletes on
# exit and points sys._MEIPASS at it, so the two directories a script cares
# about stop being the same one and have to be kept apart:
#
#   BUNDLE_DIR: read-only payload shipped inside the build (the step scripts).
#   APP_DIR:    the folder the app was launched from -- writable, visible to
#               the user, and where anything worth keeping has to go.
#
# In a plain source checkout both are just the pipeline directory.
IS_FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DIR = (
    Path(sys.executable).resolve().parent if IS_FROZEN
    else Path(__file__).resolve().parent
)

# APP_DIR, not __file__: inside a frozen build __file__ resolves into the temp
# BUNDLE_DIR, so a usage log written there would be deleted on every exit.
CLAUDE_USAGE_LOG = APP_DIR / "logs" / "claude_usage.jsonl"


# Every `claude -p --output-format json` call in this pipeline goes through
# run_claude_cli() below. It exists because the obvious way to make the call
# is subtly broken on Windows: subprocess's text=True decodes stdout with the
# platform's preferred encoding, which is cp1252 there, so any transcription
# or correction containing a curly quote, em-dash, or accented character blew
# up subprocess's stdout reader thread. That failure is invisible to the
# caller -- CPython's _readerthread appends nothing to its buffer, and
# _communicate then collapses the empty buffer to None -- so instead of a
# real error you got "TypeError: the JSON object must be str, bytes or
# bytearray, not NoneType" out of json.loads. The claude CLI always emits
# UTF-8, so we decode explicitly and never consult the platform encoding.
CLAUDE_CLI_ATTEMPTS = 2
_CLAUDE_CLI_ENCODING = "utf-8"


class ClaudeCLIError(RuntimeError):
    """A `claude -p --output-format json` call failed.

    Subclasses RuntimeError so existing callers that catch RuntimeError (or
    Exception) keep working unchanged.
    """


def _run_claude_cli_once(cmd: List[str], timeout: int) -> Dict[str, Any]:
    """Run the claude CLI a single time and return its parsed JSON payload.

    Raises:
        ClaudeCLIError: on timeout, non-zero exit, non-UTF-8 output, empty
            output, unparseable JSON, or an is_error payload. Every failure
            mode names its actual cause so a caller's log line is useful.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ClaudeCLIError(f"claude CLI timed out after {timeout}s")

    # stderr is diagnostic only, so never let it be the thing that fails.
    stderr = result.stderr.decode(_CLAUDE_CLI_ENCODING, errors="replace").strip()

    try:
        stdout = result.stdout.decode(_CLAUDE_CLI_ENCODING)
    except UnicodeDecodeError as e:
        raise ClaudeCLIError(f"claude CLI output was not valid UTF-8: {e}")

    if result.returncode != 0:
        raise ClaudeCLIError(f"claude CLI exited {result.returncode}: {stderr[:200]}")

    if not stdout.strip():
        detail = f" (stderr: {stderr[:200]})" if stderr else ""
        raise ClaudeCLIError(f"claude CLI exited 0 but produced no output{detail}")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise ClaudeCLIError(f"claude CLI returned invalid JSON: {e}")

    if payload.get("is_error"):
        raise ClaudeCLIError(f"claude CLI reported an error: {payload.get('result')}")

    return payload


def run_claude_cli(
    cmd: List[str],
    timeout: int = 120,
    attempts: int = CLAUDE_CLI_ATTEMPTS,
    context: str = "",
) -> Dict[str, Any]:
    """Run a `claude -p --output-format json` command, retrying once on failure.

    Args:
        cmd: Fully built claude CLI argv
        timeout: Per-attempt timeout in seconds. Note that the worst case is
            timeout * attempts before this returns.
        attempts: Total tries, including the first. One retry absorbs the
            transient failures (a network blip, a dropped OAuth refresh)
            without turning a genuine error into a long stall.
        context: Short identifier for what is being processed (an image path,
            a text snippet), used only in the retry log line.

    Returns:
        The decoded JSON payload

    Raises:
        ClaudeCLIError: if every attempt failed, naming the last cause
    """
    label = f" for {context}" if context else ""
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            return _run_claude_cli_once(cmd, timeout)
        except ClaudeCLIError as e:
            last_error = e
            if attempt < attempts:
                logger.warning(
                    f"claude CLI attempt {attempt}/{attempts} failed{label} "
                    f"({e}); retrying"
                )

    raise ClaudeCLIError(f"claude CLI failed after {attempts} attempts: {last_error}")


def log_claude_usage(operation: str, payload: Dict[str, Any], context: str = "") -> None:
    """Record token/cost usage from a `claude -p --output-format json` payload.

    Appends one JSON line per call to CLAUDE_USAGE_LOG (a persistent record
    across runs) and emits a one-line summary via the logger, which shows up
    in whichever console/GUI log is already capturing this script's output.

    Args:
        operation: Which pipeline step/engine made the call, e.g.
            "text_correct" or "claude_vision_ocr"
        payload: The parsed JSON payload from a `claude -p --output-format
            json` call (has "usage" and "total_cost_usd" keys)
        context: Short human-readable identifier for what was processed
            (e.g. an image path or a text snippet), for the log line
    """
    usage = payload.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    cost = payload.get("total_cost_usd", 0.0)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "operation": operation,
        "context": context,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
        "total_cost_usd": cost,
    }

    try:
        ensure_dir(CLAUDE_USAGE_LOG.parent)
        with open(CLAUDE_USAGE_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning(f"Could not write to Claude usage log: {e}")

    logger.info(
        f"Claude usage [{operation}] {context}: {input_tokens} in / {output_tokens} out tokens "
        f"(cache: {cache_read} read, {cache_creation} created), ${cost:.4f}"
    )


def get_output_filename(input_path: Path, output_dir: Path, suffix: str, extension: str = "") -> Path:
    """Generate output filename based on input filename and suffix."""
    stem = input_path.stem
    if extension and not extension.startswith('.'):
        extension = f".{extension}"
    filename = f"{stem}_{suffix}{extension}" if suffix else f"{stem}{extension}"
    return output_dir / filename


def setup_logging(name: str, log_level: int = logging.INFO) -> None:
    """Setup logging configuration."""
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
        ]
    )


def validate_image_path(image_path: Path) -> bool:
    """Validate that image file exists and is readable."""
    image_path = Path(image_path)
    if not image_path.exists():
        logger.error(f"Image file not found: {image_path}")
        return False
    if not image_path.is_file():
        logger.error(f"Not a file: {image_path}")
        return False
    return True
