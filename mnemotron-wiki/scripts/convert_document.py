# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
convert_document.py — Convert PDF/DOC/DOCX/HTML source files to structured
Markdown for the wiki/documents/ pipeline (see scripts/ingest_document.py).

Unlike extract_text.py (which produces a flat text blob for general-purpose
synthesis), this module preserves document structure — headings, lists,
tables — as Markdown, and drops everything that isn't text content: images,
embedded objects, styling, navigation chrome.

Usage (import):
    from scripts.convert_document import convert_to_markdown
    result = convert_to_markdown(Path("report.pdf"))
    print(result["text"])       # Markdown body
    print(result["metadata"])   # {"title": ..., "author": ...} best-effort

Usage (CLI):
    python scripts/convert_document.py path/to/document.pdf
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import PDF_MIN_WORDS_PER_PAGE


# ---------------------------------------------------------------------------
# PDF -> Markdown (heading detection via font size, OCR fallback for scans)
# ---------------------------------------------------------------------------

def _pdf_metadata(filepath: Path) -> dict:
    """Best-effort PDF info-dict metadata (title/author/subject/keywords)."""
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser

    metadata = {}
    try:
        with open(filepath, "rb") as f:
            doc = PDFDocument(PDFParser(f))
            if doc.info:
                raw = doc.info[0]
                for key in ("Title", "Author", "Subject", "Keywords"):
                    value = raw.get(key)
                    if value:
                        if isinstance(value, bytes):
                            value = value.decode("utf-8", errors="replace")
                        metadata[key.lower()] = value.strip()
    except Exception:
        pass  # metadata is best-effort
    return metadata


def _pdf_blocks(filepath: Path) -> tuple[list[tuple[str, float]], int]:
    """Return ([(text, max_font_size), ...], page_count) via pdfminer layout mode."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTChar, LTTextContainer

    blocks: list[tuple[str, float]] = []
    page_count = 0
    for page in extract_pages(str(filepath)):
        page_count += 1
        for element in page:
            if not isinstance(element, LTTextContainer):
                continue
            text = element.get_text().strip()
            if not text:
                continue
            sizes = [
                char.size
                for line in element
                for char in line
                if isinstance(char, LTChar)
            ]
            size = max(sizes) if sizes else 0.0
            blocks.append((text, size))
    return blocks, page_count


def _blocks_to_markdown(blocks: list[tuple[str, float]]) -> str:
    """Convert (text, font_size) blocks to Markdown, treating oversized short
    lines as headings. Body size is taken as the modal (most common) size."""
    if not blocks:
        return ""

    sizes = [round(size, 1) for _, size in blocks if size]
    body_size = max(set(sizes), key=sizes.count) if sizes else 0.0

    # Distinct sizes larger than body text, biggest first, capped at 4 levels.
    heading_sizes = sorted({s for s in sizes if s > body_size * 1.15}, reverse=True)[:4]

    # Reflow: pdfminer splits one logical paragraph into multiple text boxes
    # wherever a line wraps across a column/box boundary. Merge consecutive
    # plain-text blocks back into one paragraph unless the previous one ends
    # at a sentence boundary or either side looks like a list item.
    paragraphs: list[str] = []
    for text, size in blocks:
        text = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
        if not text:
            continue
        is_heading = (
            round(size, 1) in heading_sizes
            and len(text) < 120
            and not text.endswith((".", ",", ";", ":"))
        )
        if is_heading:
            level = heading_sizes.index(round(size, 1)) + 1
            paragraphs.append(f"{'#' * level} {text}")
            continue

        is_list_item = bool(re.match(r"^([-*•]|\d+[.)])\s", text))
        prev = paragraphs[-1] if paragraphs else ""
        prev_is_heading = prev.startswith("#")
        can_merge = (
            paragraphs and not prev_is_heading and not is_list_item
            and not prev.endswith((".", "!", "?", ":", '"', "”"))
        )
        if can_merge:
            paragraphs[-1] = f"{prev} {text}"
        else:
            paragraphs.append(text)

    return "\n\n".join(paragraphs).strip()


def convert_pdf(filepath: Path) -> tuple[str, dict]:
    """Convert a PDF to Markdown, falling back to OCR if it appears scanned."""
    metadata = _pdf_metadata(filepath)
    blocks, page_count = _pdf_blocks(filepath)
    word_count = sum(len(text.split()) for text, _ in blocks)

    if page_count == 0 or word_count < PDF_MIN_WORDS_PER_PAGE * max(page_count, 1):
        from scripts.ocr import ocr_pdf
        print(f"  {filepath.name}: sparse text layer ({word_count} words over "
              f"{page_count} page(s)) — falling back to OCR.", file=sys.stderr)
        ocr_result = ocr_pdf(filepath)
        if ocr_result["error"]:
            raise RuntimeError(f"OCR fallback failed: {ocr_result['error']}")
        metadata["extracted_via"] = f"ocr:{ocr_result['method']}"
        return _plaintext_heading_heuristic(ocr_result["text"]), metadata

    return _blocks_to_markdown(blocks), metadata


def _plaintext_heading_heuristic(text: str) -> str:
    """Light heading detection for OCR output, which carries no font-size
    information: short, standalone, title-cased or ALL-CAPS lines flanked by
    blank lines are promoted to a level-2 heading."""
    lines = text.splitlines()
    out = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            out.append("")
            continue
        prev_blank = i == 0 or not lines[i - 1].strip()
        next_blank = i + 1 >= len(lines) or not lines[i + 1].strip()
        looks_like_heading = (
            prev_blank and next_blank and len(line) < 80
            and not line.endswith((".", ",", ";"))
            and (line.isupper() or line.istitle())
        )
        out.append(f"## {line}" if looks_like_heading else line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


# ---------------------------------------------------------------------------
# DOCX -> Markdown
# ---------------------------------------------------------------------------

def _append_list_item(blocks: list[str], marker: str, text: str) -> None:
    """Append a list line, merging into the previous block if it's the same
    kind of list (so consecutive items render as one tight Markdown list)."""
    line = f"{marker} {text}"
    if blocks:
        last_line = blocks[-1].split("\n")[-1]
        if last_line.startswith(f"{marker} "):
            blocks[-1] += f"\n{line}"
            return
    blocks.append(line)


def convert_docx(filepath: Path) -> tuple[str, dict]:
    from docx import Document

    doc = Document(str(filepath))

    metadata = {}
    props = doc.core_properties
    if props.title:
        metadata["title"] = props.title
    if props.author:
        metadata["author"] = props.author
    if props.subject:
        metadata["subject"] = props.subject

    blocks: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "").lower()
        m = re.match(r"heading (\d)", style)
        if m:
            level = min(int(m.group(1)), 6)
            blocks.append(f"{'#' * level} {text}")
        elif "list bullet" in style or "list paragraph" in style:
            _append_list_item(blocks, "-", text)
        elif "list number" in style:
            _append_list_item(blocks, "1.", text)
        else:
            blocks.append(text)

    for table in doc.tables:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if not rows:
            continue
        md_table = ["| " + " | ".join(rows[0]) + " |",
                    "| " + " | ".join("---" for _ in rows[0]) + " |"]
        md_table += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        blocks.append("\n".join(md_table))

    return "\n\n".join(blocks), metadata


def convert_doc(filepath: Path) -> tuple[str, dict]:
    """Legacy .doc: convert to .docx via macOS textutil, then reuse convert_docx."""
    with tempfile.TemporaryDirectory(prefix="workwiki_doc_") as tmp:
        tmp_docx = Path(tmp) / (filepath.stem + ".docx")
        try:
            subprocess.run(
                ["textutil", "-convert", "docx", "-output", str(tmp_docx), str(filepath)],
                capture_output=True, text=True, check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Cannot convert .doc: textutil is not available (macOS only)."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"textutil failed: {exc.stderr.strip()}") from exc
        return convert_docx(tmp_docx)


# ---------------------------------------------------------------------------
# HTML -> Markdown
# ---------------------------------------------------------------------------

_HTML_HEADING_RE = re.compile(r"^h([1-6])$")


def _html_block_to_markdown(el) -> list[str]:
    """Recursively render a BeautifulSoup element's block-level children."""
    from bs4.element import NavigableString

    out: list[str] = []
    for child in el.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                out.append(text)
            continue

        name = (child.name or "").lower()
        m = _HTML_HEADING_RE.match(name)
        if m:
            text = child.get_text(" ", strip=True)
            if text:
                out.append(f"{'#' * int(m.group(1))} {text}")
        elif name in ("ul", "ol"):
            items = []
            for i, li in enumerate(child.find_all("li", recursive=False), start=1):
                text = li.get_text(" ", strip=True)
                if text:
                    marker = "-" if name == "ul" else f"{i}."
                    items.append(f"{marker} {text}")
            if items:
                out.append("\n".join(items))
        elif name == "table":
            rows = [
                [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                for tr in child.find_all("tr")
            ]
            rows = [r for r in rows if r]
            if rows:
                md = ["| " + " | ".join(rows[0]) + " |",
                      "| " + " | ".join("---" for _ in rows[0]) + " |"]
                md += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                out.append("\n".join(md))
        elif name == "blockquote":
            text = child.get_text(" ", strip=True)
            if text:
                out.append(f"> {text}")
        elif name in ("pre", "code"):
            text = child.get_text()
            if text.strip():
                out.append(f"```\n{text.strip()}\n```")
        elif name in ("p", "div", "section", "article", "li"):
            text = child.get_text(" ", strip=True)
            if text:
                out.append(text)
        else:
            # Inline or unrecognised container: recurse into it.
            out.extend(_html_block_to_markdown(child))
    return out


def convert_html(filepath: Path) -> tuple[str, dict]:
    from bs4 import BeautifulSoup

    raw = filepath.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "lxml")

    metadata = {}
    title_tag = soup.find("title")
    if title_tag:
        metadata["title"] = title_tag.get_text(strip=True)

    for tag in soup(["script", "style", "head", "nav", "footer", "img", "svg", "noscript"]):
        tag.decompose()

    body = soup.body or soup
    blocks = _html_block_to_markdown(body)
    # Drop consecutive duplicate blocks (common when text is nested in
    # multiple wrapper divs that all resolve to the same get_text()).
    deduped = []
    for b in blocks:
        if not deduped or deduped[-1] != b:
            deduped.append(b)
    return "\n\n".join(deduped), metadata


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_CONVERTERS = {
    ".pdf": convert_pdf,
    ".doc": convert_doc,
    ".docx": convert_docx,
    ".odt": convert_docx,
    ".html": convert_html,
    ".htm": convert_html,
}


def convert_to_markdown(filepath: Path) -> dict:
    """Convert *filepath* to Markdown. Never raises — errors land in result["error"]."""
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    result = {"text": "", "type": ext.lstrip("."), "source": filepath, "metadata": {}, "error": None}

    converter = _CONVERTERS.get(ext)
    if converter is None:
        result["error"] = f"Unsupported document type: {ext}"
        return result

    try:
        text, metadata = converter(filepath)
        result["text"] = text.strip()
        result["metadata"] = metadata
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/convert_document.py <filepath>")
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"Error: file not found: {target}")
        sys.exit(1)

    res = convert_to_markdown(target)
    if res["error"]:
        print(f"Conversion error: {res['error']}")
        sys.exit(1)

    if res["metadata"]:
        print("--- metadata ---", file=sys.stderr)
        for k, v in res["metadata"].items():
            print(f"  {k}: {v}", file=sys.stderr)

    print(res["text"])
