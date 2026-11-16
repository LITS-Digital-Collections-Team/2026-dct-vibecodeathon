# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
extract_text.py — Extract plain text from native (non-scanned) document types.

Supported formats and their backends
--------------------------------------
  .pdf          pdfminer.six   Scanned PDFs (no text layer) are detected and
                               flagged for re-routing to ocr.py.
  .docx, .odt   python-docx    Paragraph text; core properties as metadata.
  .html, .htm   BeautifulSoup  Script/style stripped; visible text only.
  .csv          stdlib csv     Rendered as pipe-separated plain text.
  .txt, .md     built-in       Direct UTF-8 read.
  .doc          textutil / docx2txt   Legacy Word (macOS textutil, else docx2txt).
  .eml          email (stdlib) Headers as metadata; plain-text body preferred.
  .json/.jsonl  json (stdlib)  Pretty-printed JSON / one object per line.
  .xml          ElementTree    Tag-labelled outline (MODS, EAD, Dublin Core...).
  images        scripts/llm    Quick vision extraction of screenshots.  Archival
                               scans/handwriting belong in ocr.py.

Return value
------------
All functions return a dict with these keys:

    text      str        Extracted plain text (stripped of leading/trailing
                         whitespace).
    type      str        File type derived from extension (e.g. "pdf").
    source    Path       Original file path.
    metadata  dict       Any available metadata (title, author, etc.).
    error     str|None   Error message if extraction failed; None on success.
    is_scan   bool       True if the file appears to be a scanned PDF with no
                         usable text layer.  Only ever True for .pdf files.

The function never raises — errors are captured in result["error"] so callers
can decide how to handle failures (log and continue, quarantine, etc.).

CLI exit codes
--------------
    0  Success — text printed to stdout.
    1  Extraction error — message on stderr.
    2  Scanned PDF detected — message on stderr; caller should use ocr.py.

Usage (CLI)
-----------
    python scripts/extract_text.py path/to/document.pdf

Usage (import)
--------------
    from scripts.extract_text import extract_text
    result = extract_text(Path("paper.pdf"))
    if result["is_scan"]:
        # re-route to ocr.py
    elif result["error"]:
        # handle failure
    else:
        text = result["text"]
"""

import csv
import sys
from io import StringIO
from pathlib import Path


# ---------------------------------------------------------------------------
# Per-format extractors
# ---------------------------------------------------------------------------

def _extract_pdf(filepath: Path) -> tuple[str, dict, bool]:
    """Extract text from a PDF that has a native text layer.

    Returns (text, metadata, is_scan).

    is_scan is set to True when the extracted text is suspiciously short —
    fewer than 100 non-whitespace characters across the entire document.
    This is a reliable heuristic for scanned PDFs where the PDF container
    holds page images but no embedded text.  The threshold is deliberately
    conservative: a real single-page document will almost always exceed 100
    non-whitespace characters.
    """
    from pdfminer.high_level import extract_text as pdfminer_extract
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser

    text = pdfminer_extract(str(filepath))

    # Attempt to read standard PDF metadata from the document info dictionary.
    # This is best-effort: malformed or encrypted PDFs may not expose metadata,
    # and we must not let a metadata failure abort the text extraction.
    metadata = {}
    try:
        with open(filepath, "rb") as f:
            parser = PDFParser(f)
            doc = PDFDocument(parser)
            if doc.info:
                raw = doc.info[0]
                for key in ("Title", "Author", "Subject", "Keywords"):
                    value = raw.get(key)
                    if value:
                        # PDF metadata values are bytes in older documents.
                        if isinstance(value, bytes):
                            value = value.decode("utf-8", errors="replace")
                        metadata[key.lower()] = value.strip()
    except Exception:
        pass

    # Count non-whitespace characters to detect scanned (image-only) PDFs.
    non_ws_count = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
    is_scan = non_ws_count < 100

    return text, metadata, is_scan


def _extract_docx(filepath: Path) -> tuple[str, dict]:
    """Extract text from a .docx or .odt file using python-docx.

    Paragraphs are joined with blank lines between them to preserve the
    visual structure of the document.  Empty paragraphs (section breaks,
    spacing) are filtered out.
    """
    from docx import Document
    doc = Document(str(filepath))

    # Filter out truly empty paragraphs; preserve intentional blank lines
    # between content paragraphs by using double newline as the separator.
    text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

    metadata = {}
    props = doc.core_properties
    if props.title:
        metadata["title"] = props.title
    if props.author:
        metadata["author"] = props.author

    return text, metadata


def _extract_html(filepath: Path) -> tuple[str, dict]:
    """Extract visible text from an HTML file using BeautifulSoup.

    Removes script, style, and head elements — their text content is not
    meaningful for research purposes.  Uses the lxml parser for speed and
    robust handling of malformed HTML.
    """
    from bs4 import BeautifulSoup

    raw = filepath.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "lxml")

    # Remove non-content elements before extracting text.
    for tag in soup(["script", "style", "head"]):
        tag.decompose()

    # get_text with a newline separator, then strip blank lines.
    lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
    text = "\n".join(line for line in lines if line)

    # The <title> element is the most reliable source of a document title.
    metadata = {}
    title_tag = soup.find("title")
    if title_tag:
        metadata["title"] = title_tag.get_text(strip=True)

    return text, metadata


def _extract_csv(filepath: Path) -> tuple[str, dict]:
    """Render a CSV file as pipe-separated plain text.

    Pipe separation is chosen over the original delimiter because it is
    human-readable, survives whitespace normalisation, and is easy for Claude
    to parse into a markdown table.  The first row is treated as a header.
    """
    raw = filepath.read_text(encoding="utf-8", errors="replace")
    reader = csv.reader(StringIO(raw))
    rows = list(reader)

    lines = [" | ".join(cell.strip() for cell in row) for row in rows if any(row)]

    metadata = {}
    if rows:
        metadata["columns"] = rows[0]
        metadata["row_count"] = str(len(rows) - 1)

    return "\n".join(lines), metadata


def _extract_plaintext(filepath: Path) -> tuple[str, dict]:
    """Read a plain text or markdown file directly.

    Uses UTF-8 decoding with error replacement so malformed bytes do not
    abort extraction.
    """
    return filepath.read_text(encoding="utf-8", errors="replace"), {}


def _extract_json(filepath: Path) -> tuple[str, dict]:
    """
    Extract readable text from a JSON file.

    Pretty-prints the parsed structure.  Raises on invalid JSON (the caller
    records the error).
    """
    import json

    data = json.loads(filepath.read_text(encoding="utf-8", errors="replace"))

    # Generic fallback: pretty-print
    text = json.dumps(data, indent=2, ensure_ascii=False)
    return text, {}


def _extract_jsonl(filepath: Path) -> tuple[str, dict]:
    """
    Extract text from a newline-delimited JSON file.

    Each non-empty line is parsed as a JSON object and pretty-printed.
    Unparseable lines are included as-is.
    """
    import json

    out_lines = []
    for raw_line in filepath.read_text(encoding="utf-8", errors="replace").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
            out_lines.append(json.dumps(obj, ensure_ascii=False))
        except json.JSONDecodeError:
            out_lines.append(raw_line)
    return "\n".join(out_lines), {"row_count": str(len(out_lines))}


def _extract_image(filepath: Path) -> tuple[str, dict]:
    """
    Extract text from an image file using Claude's vision API.

    Builds a context-aware prompt based on filename patterns (e.g. LinkedIn
    screenshots get sidebar-ignore instructions).  Falls back to a generic
    OCR-style extraction for unrecognised image types.

    Uses scripts/llm.py, so it works with either the headless Claude Code CLI
    or the Anthropic API backend.  For archival scans and handwriting, use
    ocr.py instead (Tesseract first, Claude vision as fallback).
    """
    try:
        from scripts.llm import generate_from_image
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from llm import generate_from_image

    name_lower = filepath.name.lower()
    if "linkedin" in name_lower and "connections" in name_lower:
        prompt = (
            "This is a screenshot of a LinkedIn Connections page. "
            "The right side of the screen contains a recurring sidebar panel "
            "(ads, 'People You May Know', or similar LinkedIn widgets) — "
            "ignore it entirely. "
            "Extract only the connections list from the left/centre of the page. "
            "For each person output one line in the format:\n"
            "  Name | Title | Organization | Connected on: [date if visible]\n"
            "Omit navigation bars, search boxes, buttons, and all other UI chrome."
        )
    elif "linkedin" in name_lower:
        prompt = (
            "This is a LinkedIn profile screenshot. "
            "Extract the person's name, headline, current title, organization, "
            "location, and any employment history or education that is visible. "
            "Omit navigation bars, buttons, and UI chrome."
        )
    else:
        prompt = (
            "Extract all meaningful text content visible in this screenshot. "
            "Preserve logical structure (headings, list items, table rows). "
            "Omit navigation bars, toolbars, buttons, icons, and repeated UI "
            "chrome unless they provide essential context. "
            "Output plain text only — no markdown formatting, no commentary."
        )

    text = generate_from_image("", filepath, prompt).strip()
    return text, {"extracted_via": "claude-vision"}


def _extract_doc(filepath: Path) -> tuple[str, dict]:
    """
    Extract text from a legacy .doc file using macOS textutil.

    textutil is a macOS built-in that handles Word 97-2004 (.doc) files
    reliably without requiring LibreOffice or antiword.  Falls back to
    python-docx2txt if textutil is not available (non-macOS environments).
    """
    import subprocess

    # macOS path — textutil is always present on macOS 10.4+
    try:
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(filepath)],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout, {}
    except FileNotFoundError:
        pass  # textutil not available; try docx2txt below
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"textutil failed: {exc.stderr.strip()}") from exc

    # Non-macOS fallback: docx2txt (pip install docx2txt)
    try:
        import docx2txt
        text = docx2txt.process(str(filepath))
        return text or "", {}
    except ImportError:
        raise RuntimeError(
            "Cannot extract .doc: textutil is not available and docx2txt is not installed. "
            "On macOS this should not happen. On Linux, run: pip install docx2txt"
        )


def _extract_xml(filepath: Path) -> tuple[str, dict]:
    """
    Extract text content from an XML file using ElementTree.

    Preserves element tag names as inline labels so Claude can interpret
    field semantics (e.g. MODS, Dublin Core, EAD).  Namespace URIs are
    stripped, leaving only the local tag name.
    """
    import xml.etree.ElementTree as ET

    raw = filepath.read_text(encoding="utf-8", errors="replace")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return raw, {}

    def local(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    def render(elem: ET.Element, depth: int = 0) -> list[str]:
        indent = "  " * depth
        tag = local(elem.tag)
        attribs = " ".join(f'{local(k)}="{v}"' for k, v in elem.attrib.items())
        label = f"{tag}{'[' + attribs + ']' if attribs else ''}"
        parts = []
        text = (elem.text or "").strip()
        if text:
            parts.append(f"{indent}{label}: {text}")
        else:
            parts.append(f"{indent}{label}:")
        for child in elem:
            parts.extend(render(child, depth + 1))
        tail = (elem.tail or "").strip()
        if tail:
            parts.append(f"{indent}{tail}")
        return parts

    lines = render(root)
    return "\n".join(lines), {"root_tag": local(root.tag)}


def _extract_eml(filepath: Path) -> tuple[str, dict]:
    """Extract text and headers from an .eml email file."""
    import email
    from email import policy as email_policy

    msg = email.message_from_bytes(
        filepath.read_bytes(), policy=email_policy.default
    )

    metadata = {}
    for header in ("subject", "from", "to", "date"):
        value = msg.get(header)
        if value:
            metadata[header] = str(value).strip()

    # Collect text parts; prefer text/plain over text/html because plain
    # text is more compact and avoids re-parsing HTML artefacts.  Only
    # fall back to HTML if the message has no plain-text part at all
    # (common in heavily formatted marketing emails, rare in work mail).
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in msg.walk():
        if str(part.get("Content-Disposition", "")).lower().startswith("attachment"):
            continue
        ct = part.get_content_type()
        if ct == "text/plain":
            plain_parts.append(part.get_content())
        elif ct == "text/html":
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(part.get_content(), "lxml")
            for tag in soup(["script", "style"]):
                tag.decompose()
            html_parts.append(soup.get_text(separator="\n"))

    parts = plain_parts if plain_parts else html_parts
    text = "\n\n".join(p.strip() for p in parts if p.strip())
    return text, metadata


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

# Maps each supported extension to the function that handles it.
# .odt reuses the .docx extractor because python-docx handles both formats
# via the same OOXML-based API.
_EXTRACTORS = {
    ".pdf":  _extract_pdf,      # returns 3-tuple (text, metadata, is_scan)
    ".docx": _extract_docx,
    ".odt":  _extract_docx,
    ".html": _extract_html,
    ".htm":  _extract_html,
    ".csv":  _extract_csv,
    ".txt":  _extract_plaintext,
    ".md":   _extract_plaintext,
    ".doc":   _extract_doc,
    ".eml":   _extract_eml,
    ".json":  _extract_json,
    ".jsonl": _extract_jsonl,
    ".xml":   _extract_xml,
    # Images: a quick vision-based text extraction (screenshots etc.).  For
    # archival scans and handwriting use ocr.py instead.
    ".png":   _extract_image,
    ".jpg":   _extract_image,
    ".jpeg":  _extract_image,
    ".webp":  _extract_image,
    ".gif":   _extract_image,
}


def extract_text(filepath: Path) -> dict:
    """Extract plain text from *filepath*.

    Returns a result dict as described in the module docstring.
    Never raises — all errors are captured in result["error"].
    """
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    result = {
        "text":     "",
        "type":     ext.lstrip("."),
        "source":   filepath,
        "metadata": {},
        "error":    None,
        "is_scan":  False,
    }

    extractor = _EXTRACTORS.get(ext)
    if extractor is None:
        result["error"] = f"Unsupported file type: {ext!r}"
        return result

    try:
        if ext == ".pdf":
            # PDF extractor returns a 3-tuple; others return a 2-tuple.
            text, metadata, is_scan = extractor(filepath)
            result["is_scan"] = is_scan
        else:
            text, metadata = extractor(filepath)

        result["text"]     = text.strip()
        result["metadata"] = metadata
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/extract_text.py <filepath>")
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"Error: file not found: {target}", file=sys.stderr)
        sys.exit(1)

    res = extract_text(target)

    if res["error"]:
        print(f"Extraction error: {res['error']}", file=sys.stderr)
        sys.exit(1)

    if res["is_scan"]:
        print(
            f"[SCAN] {target.name} appears to be a scanned PDF with no text layer. "
            "Re-route to ocr.py.",
            file=sys.stderr,
        )
        sys.exit(2)

    if res["metadata"]:
        print("--- metadata ---", file=sys.stderr)
        for k, v in res["metadata"].items():
            print(f"  {k}: {v}", file=sys.stderr)

    print(res["text"])
