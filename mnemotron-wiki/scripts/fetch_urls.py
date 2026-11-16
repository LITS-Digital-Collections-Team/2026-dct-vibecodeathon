# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
fetch_urls.py — Fetch URL content referenced in raw_ingest/ files.

For each unprocessed file in raw_ingest/, this script extracts URLs, fetches
publicly accessible content, and writes a sidecar .md file that Claude can use
during the ingest run to enrich its analysis.

This script is NOT run automatically. Run it manually before the wiki update
task when you want URL content included:

    python scripts/fetch_urls.py              # fetch from all unprocessed files
    python scripts/fetch_urls.py --dry-run    # show URLs that would be fetched
    python scripts/fetch_urls.py --file PATH  # process one specific file

URLs that are always skipped (not useful or not permissible to fetch):
  - Video conferencing links (Zoom, Google Meet, Teams)
  - Form/app links (Asana, Workday, Google Forms)
  - Authenticated content (Google Docs/Drive/Sheets, SharePoint)
  - Social networks (LinkedIn — ToS prohibits scraping)
  - Non-content assets (images, CSS, JS)

URLs that are fetched:
  - Your institution's pages (config.INSTITUTION_DOMAINS), archives, digital collections
  - GitHub repositories
  - Internet Archive items and collections
  - Other publicly accessible HTML pages
"""

import argparse
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import (
    RAW_INGEST_DIR, FAILED_INGEST_DIR, SUPPORTED_EXTENSIONS, INSTITUTION_DOMAINS, CONTACT_EMAIL, local_today,
)
from scripts.manifest import load_manifest, is_processed

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print(
        "Error: 'requests' and 'beautifulsoup4' are required.\n"
        "Run: pip install -r scripts/requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

# Optional contact address (config.CONTACT_EMAIL) is appended to the User-Agent
# so site operators can reach you; leave it unset to send a generic agent.
HEADERS = {
    "User-Agent": "mnemotron-wiki-fetch/1.0 (personal research tool"
                  + (f"; contact: {CONTACT_EMAIL}" if CONTACT_EMAIL else "") + ")"
}
TIMEOUT = 15

# URLs matching these patterns will be SKIPPED (not useful or not permissible).
SKIP_PATTERNS = [
    r"zoom\.us",
    r"meet\.google\.com",
    r"teams\.microsoft\.com",
    r"form\.asana\.com",
    r"app\.asana\.com",
    r"docs\.google\.com",
    r"drive\.google\.com",
    r"sheets\.google\.com",
    r"slides\.google\.com",
    r"forms\.google\.com",
    r"mail\.google\.com",
    r"calendar\.google\.com",
    r"linkedin\.com",
    r"twitter\.com",
    r"x\.com",
    r"facebook\.com",
    r"instagram\.com",
    r"workday\.com",
    r"myworkday\.com",
    r"sharepoint\.com",
    r"localhost",
    r"127\.0\.0\.1",
    r"mailto:",
    r"tel:",
]

# Non-content file extensions to skip
SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".webp",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".pdf",  # PDFs can be downloaded separately if needed
}

# URLs matching these patterns are fetched with higher priority (listed first).
PRIORITY_PATTERNS = [
    r"archive\.org",
    r"github\.com",
    r"archivesspace\.",
    r"primo\.exlibrisgroup\.com",
]
# Your own institution's domains (config.INSTITUTION_DOMAINS) are also prioritised.
PRIORITY_PATTERNS += [re.escape(d) for d in INSTITUTION_DOMAINS]

URL_RE = re.compile(r'https?://[^\s\)\]\'"<>,]+', re.IGNORECASE)
MAX_CONTENT_CHARS = 3000
POLITE_DELAY = 0.75  # seconds between requests


# ---------------------------------------------------------------------------
# URL utilities
# ---------------------------------------------------------------------------

def extract_urls(filepath: Path) -> list[str]:
    """Extract all http(s) URLs from a file, deduplicated, order-preserved."""
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    seen: set[str] = set()
    urls: list[str] = []
    for url in URL_RE.findall(text):
        url = url.rstrip(".,;:)")  # strip common trailing punctuation
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def classify_url(url: str) -> tuple[str, str]:
    """
    Return (action, reason) where action is 'fetch', 'skip', or 'note'.
    'note' means: include the URL in output but don't fetch content.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "skip", "no scheme or host"

    # Skip by pattern
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            service = pattern.split(r"\.")[0].replace("\\", "")
            return "skip", f"{service} (not fetched)"

    # Skip by file extension
    path_lower = parsed.path.lower()
    for ext in SKIP_EXTENSIONS:
        if path_lower.endswith(ext):
            return "skip", f"{ext} asset"

    return "fetch", ""


def is_priority(url: str) -> bool:
    return any(re.search(p, url, re.IGNORECASE) for p in PRIORITY_PATTERNS)


# ---------------------------------------------------------------------------
# Content fetcher
# ---------------------------------------------------------------------------

def fetch_url_content(url: str) -> str:
    """Fetch *url* and return clean text, or an error/status message."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return "*Fetch timed out.*"
    except requests.exceptions.HTTPError as exc:
        return f"*HTTP {exc.response.status_code}.*"
    except Exception as exc:
        return f"*Fetch failed: {exc}*"

    content_type = resp.headers.get("content-type", "")

    if "text/html" in content_type:
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        body = soup.get_text(separator="\n", strip=True)
        body = re.sub(r"\n{3,}", "\n\n", body)
        result = f"**Page title:** {title}\n\n{body[:MAX_CONTENT_CHARS]}"
        if len(body) > MAX_CONTENT_CHARS:
            result += "\n\n*[truncated]*"
        return result

    elif "text/" in content_type:
        text = resp.text[:MAX_CONTENT_CHARS]
        if len(resp.text) > MAX_CONTENT_CHARS:
            text += "\n\n*[truncated]*"
        return text

    else:
        return f"*Non-text content ({content_type.split(';')[0].strip()}) — not fetched.*"


# ---------------------------------------------------------------------------
# File processor
# ---------------------------------------------------------------------------

def process_file(filepath: Path, dry_run: bool = False) -> Optional[str]:
    """
    Process one file: classify its URLs, fetch fetchable ones, return sidecar
    markdown. Returns None if there is nothing worth writing.
    """
    urls = extract_urls(filepath)
    if not urls:
        return None

    classified = [(u, *classify_url(u)) for u in urls]
    to_fetch = [(u, r) for u, action, r in classified if action == "fetch"]
    skipped = [(u, r) for u, action, r in classified if action == "skip"]

    if not to_fetch:
        return None

    # Sort: priority URLs first
    to_fetch.sort(key=lambda x: (0 if is_priority(x[0]) else 1, x[0]))

    if dry_run:
        print(f"\n  {filepath.name} ({len(to_fetch)} fetchable, {len(skipped)} skipped):")
        for url, _ in to_fetch:
            flag = " [priority]" if is_priority(url) else ""
            print(f"    FETCH  {url[:90]}{flag}")
        for url, reason in skipped[:5]:
            print(f"    SKIP   {url[:70]}...  ({reason})")
        if len(skipped) > 5:
            print(f"           ... and {len(skipped) - 5} more skipped")
        return None

    lines = [
        f"# Fetched URL Content",
        f"",
        f"*Generated by `fetch_urls.py` from `{filepath.name}`.*",
        f"",
        f"---",
        f"",
    ]

    for url, _ in to_fetch:
        print(f"    {url[:80]}...")
        content = fetch_url_content(url)
        lines += [
            f"## {url}",
            f"",
            content,
            f"",
            f"---",
            f"",
        ]
        time.sleep(POLITE_DELAY)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def get_unprocessed_files() -> list[Path]:
    """Return unprocessed ingest files, excluding already-generated sidecars."""
    manifest = load_manifest()
    files = []
    for filepath in sorted(RAW_INGEST_DIR.rglob("*")):
        if not filepath.is_file():
            continue
        if FAILED_INGEST_DIR in filepath.parents:
            continue
        if filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if filepath.name.startswith("."):
            continue
        if "-fetched-urls-" in filepath.stem:  # skip our own sidecar files
            continue
        if not is_processed(filepath, manifest):
            files.append(filepath)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch URL content from raw_ingest/ files and write sidecar .md files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show which URLs would be fetched without fetching",
    )
    parser.add_argument(
        "--file", metavar="PATH",
        help="Process a specific file instead of all unprocessed files",
    )
    args = parser.parse_args()

    if args.file:
        files = [Path(args.file)]
        if not files[0].exists():
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
    else:
        files = get_unprocessed_files()

    if not files:
        print("No unprocessed files found in raw_ingest/.")
        return

    if args.dry_run:
        print(f"Dry run — classifying URLs in {len(files)} file(s):")
    else:
        print(f"Processing {len(files)} file(s)...")

    today = local_today().isoformat()
    wrote = 0

    for filepath in files:
        if not args.dry_run:
            print(f"  {filepath.name}")
        result = process_file(filepath, dry_run=args.dry_run)
        if result and not args.dry_run:
            sidecar_name = filepath.stem + f"-fetched-urls-{today}.md"
            sidecar_path = RAW_INGEST_DIR / sidecar_name
            sidecar_path.write_text(result, encoding="utf-8")
            print(f"    → wrote {sidecar_path.name}")
            wrote += 1

    if not args.dry_run:
        if wrote:
            print(f"\nWrote {wrote} sidecar file(s). Run the wiki update task to ingest.")
        else:
            print("No fetchable URLs found in unprocessed files.")


if __name__ == "__main__":
    main()
