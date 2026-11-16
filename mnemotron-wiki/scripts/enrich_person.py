# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
enrich_person.py — Fetch public profile information for a wiki person page.

Writes a structured ingest file to raw_ingest/ that the next wiki update run
will synthesise into the person's page (Profile and any relationship-notes
sections your people-page template defines).

Fetches:
  - Institutional directory / profile page (directory URL templates from
    config.py, else a site search on the person's e-mail domain)
  - Google Scholar profile URL + snippet
  - LinkedIn profile URL only (content not fetched; ToS prohibits scraping)

Usage:
    # Use an existing people page as context:
    python scripts/enrich_person.py jane-doe

    # Provide fields explicitly:
    python scripts/enrich_person.py --name "Jane Doe" \\
        --email jdoe@example.edu --title "Digital Curation Librarian"

Options:
    --org TEXT       Organization name (default: taken from the people page)
    --no-scholar     Skip Google Scholar search
    --no-linkedin    Skip LinkedIn URL lookup
    --dry-run        Print what would be fetched without fetching or writing
"""

import argparse
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlparse, unquote, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import (
    WIKI_ROOT, RAW_INGEST_DIR, PEOPLE_DIR, INSTITUTION_DOMAINS, DIRECTORY_URL_TEMPLATES,
    CONTACT_EMAIL, local_today,
)

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

HEADERS = {
    "User-Agent": "mnemotron-wiki-enrich/1.0 (personal research tool"
                  + (f"; contact: {CONTACT_EMAIL}" if CONTACT_EMAIL else "") + ")"
}
TIMEOUT = 15


# ---------------------------------------------------------------------------
# Web utilities
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> Optional["BeautifulSoup"]:
    """Fetch *url* and return a BeautifulSoup, or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as exc:
        print(f"  [!] {url}: {exc}", file=sys.stderr)
        return None


def page_text(soup: BeautifulSoup, max_chars: int = 2500) -> str:
    """Extract clean text from a BeautifulSoup page."""
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    trimmed = text[:max_chars]
    if len(text) > max_chars:
        trimmed += "\n\n*[content truncated]*"
    return trimmed


def ddg_search(query: str, num_results: int = 5) -> list[dict]:
    """
    Search DuckDuckGo HTML interface. Returns list of {title, url, snippet}.
    Uses the POST endpoint which is more stable than the GET interface.
    """
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "us-en"},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"  [!] DuckDuckGo search failed: {exc}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    results = []

    for result in soup.select(".result"):
        link = result.select_one(".result__a")
        snippet_el = result.select_one(".result__snippet")
        if not link:
            continue

        raw_href = link.get("href", "")
        # DDG wraps redirect URLs; unwrap if present
        if "uddg=" in raw_href:
            qs = parse_qs(urlparse(raw_href).query)
            href = unquote(qs.get("uddg", [raw_href])[0])
        else:
            href = raw_href

        results.append({
            "title": link.get_text(strip=True),
            "url": href,
            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
        })

        if len(results) >= num_results:
            break

    return results


# ---------------------------------------------------------------------------
# People page reader
# ---------------------------------------------------------------------------

def read_people_page(slug: str) -> dict:
    """
    Parse YAML frontmatter from wiki/people/<slug>.md.
    Returns dict with keys: name, email, title, department, organization.
    """
    page = PEOPLE_DIR / f"{slug}.md"
    if not page.exists():
        return {}
    content = page.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not fm_match:
        return {}
    fm = fm_match.group(1)
    fields = {}
    for key in ("name", "email", "title", "department", "organization"):
        m = re.search(rf'^{key}:\s*"?([^"\n]+)"?', fm, re.MULTILINE)
        if m:
            fields[key] = m.group(1).strip()
    return fields


# ---------------------------------------------------------------------------
# Source-specific fetchers
# ---------------------------------------------------------------------------

def fetch_institutional_profile(name: str, email: str, org: str) -> str:
    """
    Try to fetch an institutional profile page. Returns formatted text or a
    'not found' note.
    """
    email_domain = email.split("@", 1)[1].lower() if email and "@" in email else ""
    if email_domain and email_domain in INSTITUTION_DOMAINS and DIRECTORY_URL_TEMPLATES:
        username = email.split("@")[0]
        for template in DIRECTORY_URL_TEMPLATES:
            url = template.format(username=username)
            soup = fetch_page(url)
            if soup:
                text = page_text(soup)
                # Confirm the page is actually about this person
                if name.split()[0].lower() in text.lower() and len(text) > 200:
                    return f"**Source:** {url}\n\n{text}"

    # Fall back to site search
    first_name = name.split()[0]
    last_name = name.split()[-1]
    domain = email_domain or (re.sub(r"[^a-z0-9]", "", org.lower()) + ".edu" if org else "")
    if not domain:
        return "*No institutional profile page found (no e-mail domain or organization given).*"
    query = f'"{first_name} {last_name}" site:{domain}'
    results = ddg_search(query, num_results=3)

    for r in results:
        url = r.get("url", "")
        if not url or not urlparse(url).netloc:
            continue
        if last_name.lower() in r.get("title", "").lower() or last_name.lower() in url.lower():
            soup = fetch_page(url)
            if soup:
                text = page_text(soup)
                if first_name.lower() in text.lower():
                    return f"**Source:** {url}\n\n{text}"

    return "*No institutional profile page found via directory URL or site search.*"


def find_scholar_profile(name: str, org: str) -> Optional[dict]:
    """Search for a Google Scholar profile. Returns {title, url, snippet} or None."""
    for query in [
        f'"{name}" "{org}" site:scholar.google.com',
        f'"{name}" site:scholar.google.com/citations',
    ]:
        for r in ddg_search(query, num_results=5):
            if "scholar.google.com/citations" in r.get("url", ""):
                return r
        time.sleep(0.5)
    return None


def find_linkedin_url(name: str, title: str, org: str) -> Optional[str]:
    """
    Search for a LinkedIn profile URL. Returns the URL string only.
    LinkedIn content is NOT fetched — their Terms of Service prohibit scraping.
    """
    for query in [
        f'"{name}" "{org}" site:linkedin.com/in',
        f'"{name}" {title} site:linkedin.com/in',
    ]:
        for r in ddg_search(query, num_results=5):
            url = r.get("url", "")
            if "linkedin.com/in/" in url:
                return url
        time.sleep(0.5)
    return None


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------

_SYNTHESIZE_SYSTEM = """\
You update the Profile section of a personal work wiki people page.
Given public web data about a person, rewrite the Profile section
(1–2 sentences) and update the YAML frontmatter fields if better values
are available. Return ONLY the complete updated file — no commentary.
"""


def synthesize_to_page(
    slug: str,
    name: str,
    email: str,
    title: str,
    org: str,
    institutional: str,
    scholar: Optional[dict],
    linkedin_url: Optional[str],
) -> None:
    """
    Call the LLM to write an updated Profile section + frontmatter directly into
    wiki/people/<slug>.md.  Skips if the page does not exist.
    """
    try:
        from scripts.llm import generate
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from llm import generate

    page_path = PEOPLE_DIR / f"{slug}.md"
    if not page_path.exists():
        print(f"  [!] No people page found at {page_path} — skipping synthesis.", file=sys.stderr)
        print("      Create the page first, then re-run with --synthesize.")
        return

    current = page_path.read_text(encoding="utf-8")

    web_summary = f"**Institutional profile:**\n{institutional[:1500]}"
    if scholar:
        web_summary += f"\n\n**Google Scholar:** {scholar.get('url','')} — {scholar.get('snippet','')}"
    if linkedin_url:
        web_summary += f"\n\n**LinkedIn URL:** {linkedin_url}"

    prompt = (
        f"CURRENT PAGE (wiki/people/{slug}.md):\n{current}\n\n"
        f"FETCHED WEB DATA FOR {name}:\n{web_summary}\n\n"
        "Using the web data, update:\n"
        "1. The YAML frontmatter: correct title, department, organization if the web data "
        "provides better values than what is currently there.\n"
        "2. The ## Profile section: rewrite it (1–2 sentences) to accurately describe "
        "who this person is and their relevance to the wiki owner's work.\n"
        "Do not change any other section. Return the complete updated file."
    )

    updated = generate(_SYNTHESIZE_SYSTEM, prompt).strip()
    # Strip accidental markdown code fence wrapping
    updated = re.sub(r"^```[a-z]*\n?", "", updated).rstrip("`").strip()

    page_path.write_text(updated + "\n", encoding="utf-8")
    print(f"  → Updated {page_path.relative_to(WIKI_ROOT)} (Profile + frontmatter)")


def build_ingest_md(
    slug: str,
    name: str,
    email: str,
    title: str,
    org: str,
    institutional: str,
    scholar: Optional[dict],
    linkedin_url: Optional[str],
    include_scholar: bool,
    include_linkedin: bool,
) -> str:
    today = local_today().isoformat()
    lines = [
        f"# Profile Enrichment: {name}",
        f"",
        f"*Generated by `enrich_person.py` on {today}.*",
        f"*Ingest target: `wiki/people/{slug}.md`*",
        f"",
        f"---",
        f"",
        f"**Name:** {name}",
        f"**Email:** {email or '(unknown)'}",
        f"**Title:** {title or '(unknown)'}",
        f"**Organization:** {org}",
        f"",
        f"---",
        f"",
        f"## Institutional Profile",
        f"",
        institutional,
        f"",
    ]

    if include_scholar:
        lines += ["## Google Scholar", ""]
        if scholar:
            lines += [
                f"**Profile URL:** {scholar['url']}",
                f"**Search snippet:** {scholar.get('snippet', '(none)')}",
            ]
        else:
            lines.append("*No Google Scholar profile found.*")
        lines.append("")

    if include_linkedin:
        lines += ["## LinkedIn", ""]
        if linkedin_url:
            lines += [
                f"**Profile URL:** {linkedin_url}",
                "*(URL only — LinkedIn content is not fetched; see profile manually.)*",
            ]
        else:
            lines.append("*No LinkedIn profile URL found via search.*")
        lines.append("")

    lines += [
        "---",
        "",
        "*This file was auto-generated. Review before the wiki update run.*",
        "*Delete this file if the content is not useful or inaccurate.*",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch public profile info and write an enrichment ingest file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("slug", nargs="?", help="Slug matching wiki/people/<slug>.md")
    parser.add_argument("--name", help="Full name")
    parser.add_argument("--email", help="Email address")
    parser.add_argument("--title", help="Job title")
    parser.add_argument("--org", default="", help="Organization name (default: from the people page)")
    parser.add_argument("--no-scholar", action="store_true", help="Skip Google Scholar")
    parser.add_argument("--no-linkedin", action="store_true", help="Skip LinkedIn lookup")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without fetching")
    parser.add_argument(
        "--synthesize", action="store_true",
        help=(
            "After fetching, call the LLM to update the Profile section and frontmatter "
            "of wiki/people/<slug>.md directly. No ingest file is written. "
            "Requires an existing people page."
        ),
    )
    args = parser.parse_args()

    # Resolve identity from slug or flags
    if args.slug:
        page_data = read_people_page(args.slug)
        if not page_data and not args.name:
            print(f"Error: no people page found for '{args.slug}' and no --name given.", file=sys.stderr)
            sys.exit(1)
        slug  = args.slug
        name  = args.name  or page_data.get("name", "")
        email = args.email or page_data.get("email", "")
        title = args.title or page_data.get("title", "")
        org   = args.org or page_data.get("organization", "")
    else:
        if not args.name:
            parser.print_help()
            print("\nError: provide a slug or --name.", file=sys.stderr)
            sys.exit(1)
        name  = args.name
        email = args.email or ""
        title = args.title or ""
        org   = args.org
        slug  = re.sub(r"\s+", "-", name.lower().strip())

    print(f"Enriching: {name}")
    print(f"  Title:  {title or '(unknown)'}")
    print(f"  Email:  {email or '(unknown)'}")
    print(f"  Org:    {org}")

    if args.dry_run:
        print("\nDry run — would fetch:")
        print(f"  Institutional profile: {name} ({email or 'no email'})")
        if not args.no_scholar:
            print(f"  Google Scholar: \"{name}\" + \"{org}\"")
        if not args.no_linkedin:
            print(f"  LinkedIn URL: \"{name}\" + \"{org}\"")
        out = RAW_INGEST_DIR / f"enrichment-{slug}-{local_today().isoformat()}.md"
        print(f"  Output: {out}")
        return

    # Fetch
    print("\nFetching institutional profile...")
    institutional = fetch_institutional_profile(name, email, org)
    time.sleep(1)

    scholar = None
    if not args.no_scholar:
        print("Searching Google Scholar...")
        scholar = find_scholar_profile(name, org)
        time.sleep(1)

    linkedin_url = None
    if not args.no_linkedin:
        print("Searching for LinkedIn URL...")
        linkedin_url = find_linkedin_url(name, title, org)
        time.sleep(1)

    if args.synthesize:
        print("\nSynthesizing directly into people page via the LLM...")
        synthesize_to_page(
            slug=slug, name=name, email=email, title=title, org=org,
            institutional=institutional, scholar=scholar, linkedin_url=linkedin_url,
        )
    else:
        content = build_ingest_md(
            slug=slug, name=name, email=email, title=title, org=org,
            institutional=institutional, scholar=scholar, linkedin_url=linkedin_url,
            include_scholar=not args.no_scholar, include_linkedin=not args.no_linkedin,
        )
        out_path = RAW_INGEST_DIR / f"enrichment-{slug}-{local_today().isoformat()}.md"
        out_path.write_text(content, encoding="utf-8")
        print(f"\nWrote: {out_path.name}")
        print("Run the wiki update task to incorporate this into the people page.")


if __name__ == "__main__":
    main()
