# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
classify_ingest.py — Classify unprocessed files and output a parallel-dispatch plan.

Before running Stage 2 of the wiki update task, this script examines every
unprocessed file in raw_ingest/, predicts which wiki page(s) each file targets,
and groups files into *work units* that can be dispatched as parallel subagent
calls.

Two files that target the same wiki page are bundled into a single sequential
unit so that the second write does not clobber the first. All other units are
safe to dispatch in parallel.

Classification uses deterministic heuristics only (no LLM calls unless
--use-llm is given). It builds an index of existing people and topic pages
from their YAML frontmatter, then matches ingest-file names and metadata
against that index.

Personal tuning (words to ignore when matching file names to pages, etc.)
lives in config.py / config.local.json — see FILENAME_STOPWORDS there.

Usage (from wiki root):
    python scripts/classify_ingest.py           # output JSON plan
    python scripts/classify_ingest.py --pretty  # pretty-print JSON
    python scripts/classify_ingest.py --text    # human-readable summary
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.config import (
    WIKI_ROOT, RAW_INGEST_DIR, BRIEFINGS_DIR,
    PEOPLE_DIR, TOPICS_DIR, DAILY_DIR, DOCUMENTS_DIR,
    DOCUMENT_CONVERSION_EXTENSIONS, FILENAME_STOPWORDS,
)
from scripts.check_ingest import get_ingest_files
from scripts.slug import slugify


# ---------------------------------------------------------------------------
# YAML frontmatter parser (minimal — no PyYAML dependency)
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_KV_RE = re.compile(r'^(\w[\w-]*):\s*"?([^"\n]*)"?\s*$', re.MULTILINE)


def _parse_frontmatter(text: str) -> dict:
    m = _FM_RE.match(text)
    if not m:
        return {}
    return dict(_KV_RE.findall(m.group(1)))


def _read_frontmatter(filepath: Path) -> dict:
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
        return _parse_frontmatter(text)
    except OSError:
        return {}


# ---------------------------------------------------------------------------
# Build index of known wiki pages
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    """Lowercase, strip punctuation, collapse spaces → suitable for substring match."""
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()


def build_people_index() -> dict[str, str]:
    """
    Return {name_token → wiki_page_path} for all pages in wiki/people/.

    For "Jane Doe" this produces:
        {"jane": "wiki/people/jane-doe.md",
         "doe": "wiki/people/jane-doe.md",
         "jane doe": "wiki/people/jane-doe.md"}
    """
    index: dict[str, str] = {}
    if not PEOPLE_DIR.exists():
        return index
    for page in PEOPLE_DIR.glob("*.md"):
        fm = _read_frontmatter(page)
        full_name = fm.get("name", "").strip('"').strip()
        if not full_name:
            # Fall back to stem: "jane-doe" → "jane doe"
            full_name = page.stem.replace("-", " ")
        rel = str(page.relative_to(WIKI_ROOT))
        tokens = _slug(full_name).split()
        for t in tokens:
            if len(t) >= 3:  # ignore very short tokens like "de", "van"
                index.setdefault(t, rel)
        if len(tokens) >= 2:
            index.setdefault(_slug(full_name), rel)
    return index


def build_topic_index() -> dict[str, str]:
    """
    Return {keyword → wiki_page_path} for all pages in wiki/topics/.

    Keywords are derived from the filename stem (e.g. "internet-archive-integration"
    → tokens "internet", "archive", "integration", plus the full slug).
    """
    index: dict[str, str] = {}
    if not TOPICS_DIR.exists():
        return index
    for page in TOPICS_DIR.glob("*.md"):
        rel = str(page.relative_to(WIKI_ROOT))
        slug = page.stem  # e.g. "internet-archive-integration"
        index[slug] = rel
        for token in slug.split("-"):
            if len(token) >= 5:
                index.setdefault(token, rel)
    return index


# ---------------------------------------------------------------------------
# Filename heuristics
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_BRIEFING_RE = re.compile(r"morning.brief", re.IGNORECASE)
_ASANA_WEEKLY_RE = re.compile(r"asana.weekly", re.IGNORECASE)
_SUMMARY_SUFFIX_RE = re.compile(r"_summary\.md$", re.IGNORECASE)


def _is_briefing(filepath: Path) -> bool:
    return BRIEFINGS_DIR in filepath.parents or _BRIEFING_RE.search(filepath.name) is not None


def _is_asana_weekly(filepath: Path) -> bool:
    return _ASANA_WEEKLY_RE.search(filepath.name) is not None


def _is_asana_project(filepath: Path) -> bool:
    fm = _read_frontmatter(filepath)
    return fm.get("source", "").strip('"') == "Asana" and bool(fm.get("project_gid"))


def _extract_date(filepath: Path) -> Optional[str]:
    m = _DATE_RE.search(filepath.stem)
    return m.group(0) if m else None


def _name_tokens(filepath: Path) -> list[str]:
    """Extract lowercase word tokens from the filename stem."""
    stem = filepath.stem.lower()
    # Strip date, summary suffix, common non-name words
    stem = _DATE_RE.sub("", stem)
    stem = re.sub(r"_summary$", "", stem)
    stem = re.sub(r"[_\-]", " ", stem)
    # Extra words to ignore come from config (FILENAME_STOPWORDS).
    stopwords = FILENAME_STOPWORDS | {"1", "on"}
    return [t for t in stem.split() if t and t not in stopwords and len(t) >= 3]


# ---------------------------------------------------------------------------
# Classify one file
# ---------------------------------------------------------------------------

def classify(
    filepath: Path,
    people_idx: dict[str, str],
    topic_idx: dict[str, str],
) -> dict:
    """
    Return a classification dict:
        {
            "file": str,          # relative path
            "type": str,          # "briefing" | "asana-weekly" | "asana-project"
                                  # | "document-conversion" | "summary" | "document"
            "targets": [str],     # predicted wiki page(s) to update
            "confidence": str,    # "high" | "medium" | "low"
            "label": str,         # human-readable description
        }
    """
    rel = str(filepath.relative_to(WIKI_ROOT))

    if _is_briefing(filepath):
        date = _extract_date(filepath)
        target = f"wiki/daily/{date}.md" if date else "wiki/daily/"
        return dict(file=rel, type="briefing", targets=[target],
                    confidence="high", label=f"morning briefing → {target}")

    if _is_asana_weekly(filepath):
        date = _extract_date(filepath)
        target = f"wiki/daily/{date}.md" if date else "wiki/daily/"
        return dict(file=rel, type="asana-weekly", targets=[target],
                    confidence="high", label=f"Asana weekly → {target}")

    if _is_asana_project(filepath):
        return dict(file=rel, type="asana-project", targets=[],
                    confidence="high", label="Asana project file (use ingest_asana_project.py)")

    if filepath.suffix.lower() in DOCUMENT_CONVERSION_EXTENSIONS:
        target = f"wiki/documents/{slugify(filepath.stem)}.md"
        return dict(file=rel, type="document-conversion", targets=[target],
                    confidence="high",
                    label=f"{filepath.name} → {target} (use ingest_document.py)")

    is_summary = bool(_SUMMARY_SUFFIX_RE.search(filepath.name))
    ftype = "summary" if is_summary else "document"

    targets: list[str] = []
    tokens = _name_tokens(filepath)

    # Match tokens against people index
    for token in tokens:
        if token in people_idx:
            page = people_idx[token]
            if page not in targets:
                targets.append(page)

    # Also check full two-word combos for people (e.g. "jane doe")
    for i in range(len(tokens) - 1):
        combo = f"{tokens[i]} {tokens[i+1]}"
        if combo in people_idx:
            page = people_idx[combo]
            if page not in targets:
                targets.append(page)

    # Match tokens against topic index
    for token in tokens:
        if token in topic_idx:
            page = topic_idx[token]
            if page not in targets:
                targets.append(page)

    if targets:
        confidence = "high" if len(targets) == 1 else "medium"
    else:
        ftype = "document"
        confidence = "low"

    label_parts = [Path(t).stem for t in targets] if targets else ["(unknown)"]
    label = f"{filepath.stem} → {', '.join(label_parts)}"

    return dict(file=rel, type=ftype, targets=targets,
                confidence=confidence, label=label)


# ---------------------------------------------------------------------------
# LLM fallback for low-confidence files
# ---------------------------------------------------------------------------

_LLM_CLASSIFY_SYSTEM = """\
You classify ingest files for a wiki. Given the beginning of a
file, identify which wiki pages it most likely updates. Return JSON only.
"""


def _llm_classify(filepath: Path, people_idx: dict, topic_idx: dict) -> list:
    """
    Call the LLM with the first 600 bytes of *filepath* to predict target pages.
    Returns a list of wiki page path strings (may be empty).
    """
    import json as _json
    try:
        from scripts.llm import generate
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from llm import generate

    snippet = filepath.read_bytes()[:600].decode("utf-8", errors="replace")
    page_list = sorted(set(list(people_idx.values()) + list(topic_idx.values())))
    pages_str = "\n".join(f"  {p}" for p in page_list[:80])  # cap at 80

    prompt = (
        f"FILE: {filepath.name}\n\nFIRST 600 BYTES:\n{snippet}\n\n"
        f"KNOWN WIKI PAGES (partial list):\n{pages_str}\n\n"
        "Return JSON: {\"targets\": [\"wiki/people/...\", ...]}\n"
        "Include only pages this file clearly updates. Empty list if uncertain."
    )
    try:
        raw = generate(_LLM_CLASSIFY_SYSTEM, prompt)
        # Strip markdown code fences if present
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        data = _json.loads(raw)
        return [t for t in data.get("targets", []) if isinstance(t, str)]
    except Exception as exc:
        print(f"  [llm-classify] {filepath.name}: {exc}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Build the dispatch plan
# ---------------------------------------------------------------------------

def build_plan(files: list[Path], use_api: bool = False) -> dict:
    """
    Classify all *files* and group them into a parallel-dispatch plan.

    Returns:
        {
            "briefings":        [...],  # handled by Stage 1, not parallelised
            "parallel_units":   [...],  # safe to dispatch concurrently
            "sequential_units": [...],  # files share a target; one agent handles them all
            "unclassified":     [...],  # low-confidence; fall back to sequential
        }
    """
    people_idx = build_people_index()
    topic_idx = build_topic_index()

    briefings: list[dict] = []
    stage2_items: list[dict] = []

    for f in files:
        c = classify(f, people_idx, topic_idx)
        if c["type"] in {"briefing", "asana-weekly"}:
            briefings.append(c)
        else:
            # Upgrade low-confidence classifications via the LLM if requested
            if use_api and c["confidence"] == "low":
                api_targets = _llm_classify(f, people_idx, topic_idx)
                if api_targets:
                    c["targets"] = api_targets
                    c["confidence"] = "medium"
                    label_parts = [Path(t).stem for t in api_targets]
                    c["label"] = f"{f.stem} → {', '.join(label_parts)} [llm]"
            stage2_items.append(c)

    # Group stage2 items by their target set.  Files whose targets overlap
    # must be processed together (same agent) to avoid write conflicts.
    # We do this with a simple union-find over target pages.

    # Step 1: assign each item an index and build target → item_index mapping
    target_to_items: dict[str, list[int]] = defaultdict(list)
    for idx, item in enumerate(stage2_items):
        if not item["targets"]:
            item["_group"] = idx  # isolated: no targets → own group
        for t in item["targets"]:
            target_to_items[t].append(idx)

    # Step 2: union indices that share any target
    parent = list(range(len(stage2_items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for indices in target_to_items.values():
        for i in range(1, len(indices)):
            union(indices[0], indices[i])

    # Step 3: collect groups
    groups: dict[int, list[dict]] = defaultdict(list)
    for idx, item in enumerate(stage2_items):
        groups[find(idx)].append(item)

    parallel_units: list[dict] = []
    sequential_units: list[dict] = []
    unclassified: list[dict] = []

    for members in groups.values():
        # Merge members into a single unit
        all_files = [m["file"] for m in members]
        all_targets = list({t for m in members for t in m["targets"]})
        confidences = [m["confidence"] for m in members]
        overall_confidence = (
            "high" if all(c == "high" for c in confidences) else
            "medium" if any(c != "low" for c in confidences) else
            "low"
        )
        label = " + ".join(Path(m["file"]).stem for m in members)
        if all_targets:
            label += f" → {', '.join(Path(t).stem for t in all_targets)}"

        unit = dict(
            files=all_files,
            targets=all_targets,
            confidence=overall_confidence,
            label=label,
        )

        if overall_confidence == "low":
            unclassified.append(unit)
        elif len(members) == 1:
            parallel_units.append(unit)
        else:
            sequential_units.append(unit)

    return dict(
        briefings=[c["file"] for c in briefings],
        parallel_units=parallel_units,
        sequential_units=sequential_units,
        unclassified=unclassified,
    )


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Classify ingest files and output a parallel-dispatch plan."
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument("--text", action="store_true", help="Human-readable summary instead of JSON.")
    parser.add_argument("--use-api", "--use-llm", dest="use_api", action="store_true",
                        help="Call the LLM to classify low-confidence files (uses scripts/llm.py; needs the claude CLI or an API key).")
    args = parser.parse_args()

    import os
    os.chdir(WIKI_ROOT)
    files = get_ingest_files()

    if not files:
        plan = dict(briefings=[], parallel_units=[], sequential_units=[], unclassified=[])
    else:
        plan = build_plan(files, use_api=args.use_api)

    if args.text:
        total = (len(plan["parallel_units"])
                 + len(plan["sequential_units"])
                 + len(plan["unclassified"]))
        print(f"Briefings (Stage 1):   {len(plan['briefings'])}")
        print(f"Stage 2 work units:    {total}")
        print(f"  Parallel-safe:       {len(plan['parallel_units'])}")
        print(f"  Sequential (shared): {len(plan['sequential_units'])}")
        print(f"  Low-confidence:      {len(plan['unclassified'])}")
        print()
        if plan["briefings"]:
            print("BRIEFINGS:")
            for f in plan["briefings"]:
                print(f"  {f}")
            print()
        if plan["parallel_units"]:
            print("PARALLEL UNITS:")
            for u in plan["parallel_units"]:
                print(f"  [{u['confidence']}] {u['label']}")
                for f in u["files"]:
                    print(f"      file: {f}")
            print()
        if plan["sequential_units"]:
            print("SEQUENTIAL UNITS (shared targets):")
            for u in plan["sequential_units"]:
                print(f"  [{u['confidence']}] {u['label']}")
                for f in u["files"]:
                    print(f"      file: {f}")
            print()
        if plan["unclassified"]:
            print("UNCLASSIFIED (low confidence — treat as sequential):")
            for u in plan["unclassified"]:
                for f in u["files"]:
                    print(f"  {f}")
    else:
        indent = 2 if args.pretty else None
        print(json.dumps(plan, indent=indent))


if __name__ == "__main__":
    main()
