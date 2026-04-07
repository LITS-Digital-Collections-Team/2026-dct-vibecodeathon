#!/usr/bin/env python3
"""
ocr-clean.py — Clean OCR text files from scanned newspaper archives.

Designed for ABBYY-generated OCR from columnar newspaper text (e.g., the
Hamilton College Spectator, 1947–1980).

What this script does:
  1. Strips leading OCR artifacts from each line (stray underscores, pipes,
     dashes, etc. that appear when the OCR engine reads column gutters).
  2. Removes noise lines — very short or mostly-symbolic lines that are
     OCR garbage from mastheads, horizontal rules, and column decorations.
  3. Resolves hyphenated line breaks: words split across column lines
     (e.g., "repor-\nted") are rejoined into single words ("reported").
  4. Joins wrapped column lines into natural paragraphs — narrow newspaper
     columns produce many artificial line breaks that this step removes.
  5. Writes cleaned files to a separate output directory (originals untouched).
  6. Writes a tab-separated log file recording what changed in each file.

Limitations:
  - Column-crossing artefacts (text from two adjacent columns interleaved)
    cannot be fully corrected without layout analysis; this script will
    improve but not eliminate them.
  - The noise-detection heuristics are tuned for 20th-century English
    newspaper text. Adjust MIN_WORD_LENGTH / MIN_ALPHA_RATIO below if you
    find too much (or too little) being removed.

Usage:
  python3 ocr_clean.py --input INPUT_DIR --output OUTPUT_DIR [--log LOG_FILE]

  Example:
    python3 ocr_clean.py \\
        --input  ~/Code/archives-as-data/spectator/ocr \\
        --output ~/Code/archives-as-data/spectator/ocr_cleaned

Requirements: Python 3.6+, standard library only (no pip installs needed).
"""

import re
import sys
import csv
import argparse
import logging
from pathlib import Path
from datetime import datetime


# ── Tunable parameters ────────────────────────────────────────────────────────
# Increase MIN_WORD_LENGTH if legitimate short-word lines are being removed.
# Decrease it if you still see too much junk.
MIN_WORD_LENGTH = 3          # Shortest real word allowed in a short line

# Lines at least this long are assumed to be real content regardless of
# word composition (handles headlines, datelines, attribution lines, etc.).
LONG_LINE_THRESHOLD = 30

# Minimum fraction of alphanumeric characters for mid-length lines.
MIN_ALPHA_RATIO = 0.40

# Characters to strip from the *start* of a line (column-gutter artefacts).
# This is applied before noise detection.
LEADING_ARTIFACT_RE = re.compile(r'^[\s_|~]+')

# Pattern: a line ending with a word-character followed by a plain hyphen
# (no space before the hyphen). This marks a word split across column lines.
# Only dehyphenate when the *next* line begins with a lowercase letter.
TRAILING_HYPHEN_RE = re.compile(r'([A-Za-z])-$')


# ── Noise detection ───────────────────────────────────────────────────────────

def _longest_word(text: str) -> int:
    """Return the length of the longest run of consecutive letters."""
    words = re.findall(r'[A-Za-z]+', text)
    return max((len(w) for w in words), default=0)


def _short_word_ratio(text: str) -> float:
    """Fraction of words that are ≤2 characters long."""
    words = re.findall(r'[A-Za-z]+', text)
    if not words:
        return 1.0
    short = sum(1 for w in words if len(w) <= 2)
    return short / len(words)


def is_noise(line: str) -> bool:
    """
    Return True if *line* looks like OCR garbage rather than real text.

    Heuristics (applied in order):
      - Blank lines are never noise (they delimit paragraphs).
      - Lines shorter than MIN_WORD_LENGTH are always noise.
      - Long lines (≥ LONG_LINE_THRESHOLD) are never noise.
      - Lines whose longest word is < MIN_WORD_LENGTH are noise.
      - Lines where most words are ≤2 chars and the line is short are noise
        (catches things like "ul ae", "Ee ee", "es aa a Ble").
      - Lines with a low ratio of alphanumeric characters are noise.
    """
    s = line.strip()

    # Blank lines are paragraph separators — not noise.
    if not s:
        return False

    # Absolutely too short to be content.
    if len(s) < MIN_WORD_LENGTH:
        return True

    # Long enough that we trust it regardless of composition.
    if len(s) >= LONG_LINE_THRESHOLD:
        return False

    # Short line: require at least one real word.
    if _longest_word(s) < MIN_WORD_LENGTH:
        return True

    # Short line where nearly all "words" are 1–2 chars: separator noise.
    # (e.g., "Wate Se ager a NN NL", "ee", "Ra")
    if len(s) < LONG_LINE_THRESHOLD and _short_word_ratio(s) > 0.60:
        return True

    # Alphanumeric ratio check for mid-length lines.
    alpha = sum(1 for c in s if c.isalnum())
    if alpha / len(s) < MIN_ALPHA_RATIO:
        return True

    return False


# ── Line-level cleaning ───────────────────────────────────────────────────────

def strip_leading_artifacts(line: str) -> str:
    """
    Remove leading column-gutter characters: underscores, pipes, tildes,
    and leading whitespace beyond a single space.
    A leading dash followed by a space is also stripped (OCR column-rule),
    but a dash followed by a letter is left alone (legitimate em-dash usage).
    """
    line = LEADING_ARTIFACT_RE.sub('', line)
    # Strip a lone leading dash+space (column rule), but not "— word"
    line = re.sub(r'^- (?=[A-Za-z])', '', line)
    return line


# ── Paragraph-block processing ────────────────────────────────────────────────

def split_into_blocks(lines: list) -> list:
    """
    Split a list of strings into paragraph blocks, where blocks are separated
    by one or more empty/blank lines.  Returns a list of lists.
    """
    blocks, current = [], []
    for line in lines:
        if line.strip() == '':
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def dehyphenate_and_join(lines: list) -> str:
    """
    Given the lines of one paragraph block, return a single string with:
      - Hyphenated line breaks resolved (word split across column → whole word).
      - All remaining lines joined with single spaces.

    Dehyphenation rule: if a line ends with `letter-` AND the next line's
    first character is a lowercase letter, remove the hyphen and join directly.
    Uppercase continuations are left with the hyphen in place (they are more
    likely to be legitimate compound words like "sub-\nFreshman Weekend").
    """
    if not lines:
        return ''

    result_tokens = []
    i = 0
    while i < len(lines):
        current = lines[i].rstrip()
        m = TRAILING_HYPHEN_RE.search(current)

        if m and i + 1 < len(lines):
            next_stripped = lines[i + 1].lstrip()
            if next_stripped and next_stripped[0].islower():
                # True word-break hyphen: join without hyphen.
                result_tokens.append(current[:-1] + next_stripped)
                i += 2
                continue

        result_tokens.append(current)
        i += 1

    return ' '.join(result_tokens)


# ── File-level cleaning ───────────────────────────────────────────────────────

def clean_text(raw: str) -> tuple:
    """
    Apply the full cleaning pipeline to *raw* text.

    Returns:
        (cleaned_text: str, stats: dict)

    Stats keys:
        original_lines, noise_removed, artifacts_stripped,
        hyphens_resolved, output_paragraphs
    """
    original_lines = raw.split('\n')
    stats = {
        'original_lines': len(original_lines),
        'noise_removed': 0,
        'artifacts_stripped': 0,
        'hyphens_resolved': 0,
        'output_paragraphs': 0,
    }

    # Pass 1: strip leading artifacts, flag noise lines as blank.
    processed = []
    for line in original_lines:
        if line.strip() == '':
            processed.append('')
            continue

        cleaned = strip_leading_artifacts(line)
        if cleaned != line:
            stats['artifacts_stripped'] += 1

        if is_noise(cleaned):
            stats['noise_removed'] += 1
            processed.append('')        # collapse to blank (paragraph separator)
        else:
            processed.append(cleaned)

    # Pass 2: collapse runs of blank lines to a single blank line.
    collapsed = []
    prev_blank = False
    for line in processed:
        if line.strip() == '':
            if not prev_blank:
                collapsed.append('')
            prev_blank = True
        else:
            collapsed.append(line)
            prev_blank = False

    # Pass 3: split into paragraph blocks, dehyphenate, and join.
    blocks = split_into_blocks(collapsed)
    output_blocks = []
    for block in blocks:
        # Count trailing hyphens before joining.
        hyphens = sum(1 for ln in block if TRAILING_HYPHEN_RE.search(ln.rstrip()))
        stats['hyphens_resolved'] += hyphens

        joined = dehyphenate_and_join(block)
        if joined.strip():
            output_blocks.append(joined)

    stats['output_paragraphs'] = len(output_blocks)
    return '\n\n'.join(output_blocks), stats


# ── Batch processing ──────────────────────────────────────────────────────────

def process_directory(input_dir: Path, output_dir: Path, log_path: Path):
    """
    Process every .txt file in *input_dir*, write results to *output_dir*,
    and write a TSV log to *log_path*.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Console progress logger.
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger(__name__)

    txt_files = sorted(input_dir.glob('*.txt'))
    total = len(txt_files)

    if total == 0:
        log.error(f"No .txt files found in {input_dir}")
        sys.exit(1)

    log.info(f"OCR cleanup started  —  {datetime.now():%Y-%m-%d %H:%M}")
    log.info(f"Input : {input_dir}  ({total} files)")
    log.info(f"Output: {output_dir}")
    log.info(f"Log   : {log_path}")
    log.info("─" * 72)

    # Open TSV log.
    with log_path.open('w', newline='', encoding='utf-8') as logfile:
        writer = csv.writer(logfile, delimiter='\t')
        writer.writerow([
            'filename', 'original_lines', 'noise_removed',
            'artifacts_stripped', 'hyphens_resolved', 'output_paragraphs',
            'status',
        ])

        for i, filepath in enumerate(txt_files, 1):
            try:
                raw = filepath.read_text(encoding='utf-8', errors='replace')
                cleaned, stats = clean_text(raw)
                out_path = output_dir / filepath.name
                out_path.write_text(cleaned, encoding='utf-8')

                writer.writerow([
                    filepath.name,
                    stats['original_lines'],
                    stats['noise_removed'],
                    stats['artifacts_stripped'],
                    stats['hyphens_resolved'],
                    stats['output_paragraphs'],
                    'ok',
                ])

                log.info(
                    f"[{i:4d}/{total}] {filepath.name}  "
                    f"lines:{stats['original_lines']:5d}→{stats['output_paragraphs']:4d}para  "
                    f"noise:{stats['noise_removed']:4d}  "
                    f"hyphens:{stats['hyphens_resolved']:3d}"
                )

            except Exception as exc:
                writer.writerow([filepath.name, '', '', '', '', '', f'ERROR: {exc}'])
                log.error(f"[{i:4d}/{total}] ERROR  {filepath.name}: {exc}")

    log.info("─" * 72)
    log.info(f"Done.  Cleaned files written to: {output_dir}")
    log.info(f"       Change log written to:     {log_path}")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Clean ABBYY OCR text files from scanned newspaper archives.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python3 ocr_clean.py \\\n"
            "      --input  ~/Code/archives-as-data/spectator/ocr \\\n"
            "      --output ~/Code/archives-as-data/spectator/ocr_cleaned\n"
        ),
    )
    parser.add_argument('--input',  '-i', required=True,
                        help='Directory containing the original OCR .txt files')
    parser.add_argument('--output', '-o', required=True,
                        help='Directory to write cleaned .txt files into')
    parser.add_argument('--log',    '-l', default=None,
                        help='Path for the TSV log file '
                             '(default: OUTPUT_DIR/ocr_clean.log.tsv)')
    args = parser.parse_args()

    input_dir  = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    log_path   = (Path(args.log).expanduser().resolve()
                  if args.log
                  else output_dir / 'ocr_clean.log.tsv')

    if not input_dir.is_dir():
        print(f"Error: input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    process_directory(input_dir, output_dir, log_path)


if __name__ == '__main__':
    main()
