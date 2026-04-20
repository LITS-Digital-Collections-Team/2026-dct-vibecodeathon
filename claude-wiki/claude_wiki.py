#!/usr/bin/env python3
"""
claude-wiki — AI-powered markdown knowledge base updater

Watches one or more source directories for new files and uses Claude to
analyze their content, then writes targeted updates (new notes, cross-
references, summaries) to a user-defined markdown wiki directory.

Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
SPDX-License-Identifier: GPL-3.0-or-later

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Default configuration values — all overridable in the project config file.
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    # Directory where wiki .md files live (relative to project root).
    "wiki_dir": "wiki",

    # One or more directories to watch for new source files (relative to
    # project root). Files here are never modified by this tool.
    "source_dirs": ["ingest"],

    # Where to persist the set of already-processed file paths.
    # Relative to project root; defaults to inside wiki_dir.
    "processed_log": None,   # resolved at runtime to <wiki_dir>/.processed_files.json

    # Claude model to use. Opus 4.7 is the recommended default for quality.
    "model": "claude-opus-4-7",

    # A short description of the wiki, used to prime the system prompt.
    # Example: "research notes for a digital preservation project"
    "wiki_description": "a personal markdown knowledge base",

    # File extensions to skip outright (in addition to .pdf, which is always
    # skipped because it cannot be read as plain text).
    "skip_extensions": [],

    # Optional extra rules injected verbatim into the system prompt.
    # Useful for project-specific conventions, vocabulary preferences, etc.
    "custom_rules": [],

    # Maximum tokens Claude may generate per response turn.
    "max_tokens": 8096,
}

# ---------------------------------------------------------------------------
# Claude tools exposed to the model.
# The model may only write/patch files inside wiki_dir; all other paths are
# rejected at execution time. The `done` tool ends the update loop.
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "write_file",
        "description": (
            "Create or completely overwrite a wiki file. "
            "Path must be inside the configured wiki directory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "File path relative to the project root, "
                        "e.g. 'wiki/new-note.md'"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Complete file content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "patch_file",
        "description": (
            "Replace a specific string in an existing wiki file. "
            "old_text must match exactly once in the file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the project root.",
                },
                "old_text": {
                    "type": "string",
                    "description": (
                        "Exact text to find and replace. "
                        "Must be unique within the file."
                    ),
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text.",
                },
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "done",
        "description": (
            "Signal that the wiki update for this file is complete. "
            "Call this when all warranted changes have been made, or immediately "
            "if no changes are needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": (
                        "Brief human-readable summary of changes made, "
                        "or 'No changes needed.' if nothing was warranted."
                    ),
                },
            },
            "required": ["summary"],
        },
    },
]


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------

def locate_config(explicit_path: str | None) -> Path | None:
    """Return the config file path to use, or None if not found."""
    if explicit_path:
        p = Path(explicit_path)
        if not p.exists():
            sys.exit(f"ERROR: config file not found: {explicit_path}")
        return p

    # Walk up from cwd looking for claude-wiki.json (similar to how git finds
    # .git, so the tool can be run from any subdirectory of the project).
    here = Path.cwd()
    for directory in [here, *here.parents]:
        candidate = directory / "claude-wiki.json"
        if candidate.exists():
            return candidate

    return None


def load_config(config_path: Path | None) -> dict:
    """
    Merge DEFAULT_CONFIG with values from the JSON config file (if any).
    Config file values take precedence; CLI arguments take precedence over both.
    """
    merged = dict(DEFAULT_CONFIG)
    if config_path:
        try:
            user_config = json.loads(config_path.read_text())
        except json.JSONDecodeError as exc:
            sys.exit(f"ERROR: could not parse config file {config_path}: {exc}")
        merged.update(user_config)
    return merged


def resolve_paths(config: dict, config_path: Path | None) -> tuple[Path, list[Path], Path]:
    """
    Resolve wiki_dir, source_dirs, and processed_log to absolute Paths.
    All relative paths are anchored to the directory containing the config
    file, or to cwd if no config file was found.
    """
    anchor = config_path.parent if config_path else Path.cwd()

    wiki_dir = (anchor / config["wiki_dir"]).resolve()

    source_dirs = []
    for s in config["source_dirs"]:
        resolved = (anchor / s).resolve()
        if not resolved.exists():
            print(f"WARNING: source directory does not exist and will be skipped: {resolved}")
        source_dirs.append(resolved)

    if config.get("processed_log"):
        processed_log = (anchor / config["processed_log"]).resolve()
    else:
        processed_log = wiki_dir / ".processed_files.json"

    return wiki_dir, source_dirs, processed_log


# ---------------------------------------------------------------------------
# Processed-files tracking
# ---------------------------------------------------------------------------

def load_processed(processed_log: Path) -> set:
    """Return the set of file paths (as strings) already handled."""
    if processed_log.exists():
        try:
            return set(json.loads(processed_log.read_text()))
        except (json.JSONDecodeError, OSError):
            # Corrupted log — start fresh rather than crash.
            print(f"WARNING: could not read processed log at {processed_log}; starting fresh.")
    return set()


def save_processed(processed_log: Path, processed: set) -> None:
    """Persist the processed-files set to disk."""
    processed_log.parent.mkdir(parents=True, exist_ok=True)
    processed_log.write_text(json.dumps(sorted(processed), indent=2))


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def get_new_files(
    source_dirs: list[Path],
    processed: set,
    skip_extensions: list[str],
    project_root: Path,
) -> list[Path]:
    """
    Return files in source_dirs whose relative paths are not in `processed`.
    PDFs and explicitly skipped extensions are listed separately so the caller
    can mark them processed without attempting to read them.
    """
    readable = []
    skip_exts = {e.lower().lstrip(".") for e in skip_extensions} | {"pdf"}

    for directory in source_dirs:
        if not directory.exists():
            continue
        for f in sorted(directory.rglob("*")):
            if not f.is_file():
                continue
            rel = str(f.relative_to(project_root))
            if rel in processed:
                continue
            if f.suffix.lower().lstrip(".") in skip_exts:
                print(f"  skipping (unsupported type): {rel}")
                # Mark as processed so we don't re-announce it every run.
                processed.add(rel)
                continue
            readable.append(f)

    return readable


# ---------------------------------------------------------------------------
# Wiki context assembly
# ---------------------------------------------------------------------------

def read_wiki_context(wiki_dir: Path, project_root: Path) -> str:
    """
    Read all .md files in wiki_dir (non-recursive, top-level only by default)
    and return them formatted as a single string for Claude's context window.

    The .processed_files.json log and any files whose names begin with a dot
    are excluded so Claude only sees the actual notes.
    """
    parts = []
    for md_file in sorted(wiki_dir.glob("*.md")):
        rel = md_file.relative_to(project_root)
        try:
            parts.append(f"### {rel}\n\n{md_file.read_text()}")
        except OSError as exc:
            print(f"WARNING: could not read wiki file {md_file}: {exc}")

    if not parts:
        return "(wiki is empty — no notes yet)"

    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# System prompt construction
# ---------------------------------------------------------------------------

def build_system_prompt(config: dict, wiki_dir: Path, source_dirs: list[Path]) -> str:
    """
    Build the Claude system prompt from config values.
    The description and custom rules let project owners tailor Claude's
    behavior without touching the script itself.
    """
    description = config.get("wiki_description", "a personal markdown knowledge base")
    wiki_name = wiki_dir.name
    source_list = ", ".join(f"`{d.name}/`" for d in source_dirs if d.exists())
    custom_rules = config.get("custom_rules", [])

    prompt = f"""You maintain {description}.

The wiki notes are in `{wiki_name}/`. Source documents live in: {source_list or "(source directories configured separately)"}. Never modify or delete source files.

Your job: analyze a newly added source file and make targeted updates to the wiki that improve cross-referencing, add summaries, or create new standalone notes where the content warrants them.

Core rules:
- Preserve the author's voice and personal phrasing in existing notes
- Never write to source directories — only to `{wiki_name}/`
- Use [[wikilinks]] for internal links between wiki notes
- Create a new note only when the content clearly warrants a standalone page
- Prefer updating existing notes over creating redundant new ones
- When all warranted changes are done, call `done` with a brief summary
- If no changes are needed, call `done` immediately with 'No changes needed.'"""

    if custom_rules:
        prompt += "\n\nAdditional project-specific rules:\n"
        prompt += "\n".join(f"- {rule}" for rule in custom_rules)

    return prompt


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def execute_tool(
    name: str,
    inputs: dict,
    project_root: Path,
    wiki_dir: Path,
    source_dirs: list[Path],
) -> str:
    """
    Dispatch a tool call from Claude and return a result string.

    Safety guarantees enforced here (not trusted from the model):
    - write_file and patch_file may only target paths inside wiki_dir.
    - No source directory path may ever be written to.
    """
    if name == "done":
        # done is a signal, not a file operation; return summary to caller.
        return inputs.get("summary", "Done.")

    # Resolve the target path for file operations.
    path_str = inputs.get("path", "")
    target = (project_root / path_str).resolve()
    wiki_dir_resolved = wiki_dir.resolve()

    # --- Security check ---
    if not str(target).startswith(str(wiki_dir_resolved) + os.sep) and target != wiki_dir_resolved:
        return (
            f"ERROR: path '{path_str}' is outside the wiki directory — write rejected. "
            f"Only files under '{wiki_dir.name}/' may be modified."
        )

    # Ensure the path doesn't resolve into a source directory even if it's
    # somehow nested under wiki_dir (shouldn't happen, but belt-and-suspenders).
    for src in source_dirs:
        if str(target).startswith(str(src.resolve())):
            return (
                f"ERROR: path '{path_str}' resolves to a source directory — write rejected."
            )

    if name == "write_file":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(inputs["content"])
        print(f"    wrote: {path_str}")
        return f"OK: wrote {path_str}"

    if name == "patch_file":
        if not target.exists():
            return f"ERROR: file does not exist: {path_str}"
        original = target.read_text()
        old_text = inputs.get("old_text", "")
        if not old_text:
            return "ERROR: old_text must not be empty"
        count = original.count(old_text)
        if count == 0:
            return f"ERROR: old_text not found in {path_str}"
        if count > 1:
            return (
                f"ERROR: old_text matches {count} locations in {path_str} — "
                "provide more surrounding context to make it unique"
            )
        target.write_text(original.replace(old_text, inputs["new_text"], 1))
        print(f"    patched: {path_str}")
        return f"OK: patched {path_str}"

    return f"ERROR: unknown tool '{name}'"


# ---------------------------------------------------------------------------
# Core update loop
# ---------------------------------------------------------------------------

def process_file(
    client: anthropic.Anthropic,
    file_path: Path,
    project_root: Path,
    wiki_dir: Path,
    source_dirs: list[Path],
    system_prompt: str,
    config: dict,
) -> str:
    """
    Run the wiki-update agentic loop for one newly discovered source file.

    Returns the summary string from the `done` tool call, or an error string.

    The loop works as follows:
    1. Read the current wiki context (all .md files in wiki_dir).
    2. Send the wiki context + new file content to Claude in a single user
       message, with cache_control on the wiki context block so that repeated
       calls within the same run (or across runs when the wiki is unchanged)
       benefit from Anthropic's prompt cache.
    3. Execute any tool calls Claude makes (write_file, patch_file).
    4. Continue until Claude calls `done` or the response stops naturally.
    """
    rel = file_path.relative_to(project_root)
    print(f"  reading: {rel}")

    try:
        file_content = file_path.read_text(errors="replace")
    except OSError as exc:
        return f"ERROR: could not read file: {exc}"

    wiki_context = read_wiki_context(wiki_dir, project_root)
    model = config.get("model", DEFAULT_CONFIG["model"])
    max_tokens = config.get("max_tokens", DEFAULT_CONFIG["max_tokens"])

    # The wiki context block is marked for caching: it is stable across all
    # tool-loop turns for this file, and may be stable across multiple files
    # in the same run if the wiki hasn't changed. The new-file content block
    # is NOT cached because it changes with every file.
    messages: list[dict] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "## Current wiki state\n\n"
                        "The following are all current notes in the wiki:\n\n"
                        + wiki_context
                    ),
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": (
                        f"## New source file to process\n\n"
                        f"**Path:** `{rel}`\n\n"
                        f"**Contents:**\n\n{file_content}\n\n"
                        "Analyze this file and make any warranted updates to the wiki. "
                        "Call `done` when finished."
                    ),
                },
            ],
        }
    ]

    # Agentic loop: keep sending tool results back until `done` is called.
    while True:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},  # Claude decides when/how much to reason
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        # Append assistant's response to the conversation history.
        messages.append({"role": "assistant", "content": response.content})

        # If Claude stopped naturally without calling any tools, we're done.
        if response.stop_reason == "end_turn":
            return "Completed (no done tool called — Claude stopped naturally)"

        # Process all tool calls in the response, collecting results.
        tool_results = []
        done_summary = None

        for block in response.content:
            if block.type != "tool_use":
                continue

            result = execute_tool(
                block.name,
                block.input,
                project_root,
                wiki_dir,
                source_dirs,
            )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

            # Capture the done signal but don't break yet — we must send
            # tool results for ALL tool uses in this response before stopping.
            if block.name == "done":
                done_summary = result

        # Send tool results back to Claude.
        messages.append({"role": "user", "content": tool_results})

        if done_summary is not None:
            return done_summary


# ---------------------------------------------------------------------------
# Init subcommand
# ---------------------------------------------------------------------------

def init_project(config_path: Path) -> None:
    """
    Scaffold a new claude-wiki.json config file with annotated defaults.
    Refuses to overwrite an existing config.
    """
    if config_path.exists():
        sys.exit(f"ERROR: config file already exists: {config_path}\nDelete it first to reinitialize.")

    starter = {
        "wiki_dir": "wiki",
        "source_dirs": ["ingest"],
        "model": "claude-opus-4-7",
        "wiki_description": "a personal knowledge base for [your project name here]",
        "skip_extensions": [],
        "custom_rules": [
            "Example rule: always use ISO 8601 dates (YYYY-MM-DD)",
            "Remove this list or replace with your own project conventions"
        ],
        "max_tokens": 8096
    }

    config_path.write_text(json.dumps(starter, indent=2) + "\n")
    print(f"Created config: {config_path}")
    print("Edit it to match your project, then run: python claude_wiki.py")

    # Create the wiki and ingest directories too.
    project_root = config_path.parent
    (project_root / "wiki").mkdir(exist_ok=True)
    (project_root / "ingest").mkdir(exist_ok=True)
    print("Created directories: wiki/  ingest/")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="claude_wiki",
        description=(
            "Scan source directories for new files and use Claude to update "
            "a markdown wiki with cross-references, summaries, and new notes."
        ),
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to claude-wiki.json config file (default: auto-detected)",
    )
    parser.add_argument(
        "--init",
        metavar="DIR",
        nargs="?",
        const=".",
        help="Scaffold a new claude-wiki.json in DIR (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover new files and report what would be processed, but make no changes",
    )
    args = parser.parse_args()

    # --init: scaffold and exit.
    if args.init is not None:
        init_dir = Path(args.init).resolve()
        init_project(init_dir / "claude-wiki.json")
        return

    # Locate and load config.
    config_path = locate_config(args.config)
    config = load_config(config_path)
    wiki_dir, source_dirs, processed_log = resolve_paths(config, config_path)

    # The project root is the directory containing the config file, or cwd.
    project_root = config_path.parent if config_path else Path.cwd()

    # Verify the API key is available before doing any file I/O.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(
            "ERROR: ANTHROPIC_API_KEY environment variable is not set.\n"
            "Set it before running: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    wiki_dir.mkdir(parents=True, exist_ok=True)
    processed = load_processed(processed_log)
    new_files = get_new_files(
        source_dirs, processed, config.get("skip_extensions", []), project_root
    )

    # Save immediately after skip-extension filtering updates the processed set.
    save_processed(processed_log, processed)

    if not new_files:
        print("No new files to process.")
        return

    print(f"Found {len(new_files)} new file(s) to process.")

    if args.dry_run:
        for f in new_files:
            print(f"  would process: {f.relative_to(project_root)}")
        return

    client = anthropic.Anthropic()
    system_prompt = build_system_prompt(config, wiki_dir, source_dirs)

    for file_path in new_files:
        rel = str(file_path.relative_to(project_root))
        print(f"\nProcessing: {rel}")
        try:
            summary = process_file(
                client,
                file_path,
                project_root,
                wiki_dir,
                source_dirs,
                system_prompt,
                config,
            )
            # Only mark processed on success so failures are retried next run.
            processed.add(rel)
            save_processed(processed_log, processed)
            print(f"  done: {summary}")
        except anthropic.APIError as exc:
            print(f"  API ERROR on {rel}: {exc}", file=sys.stderr)
        except OSError as exc:
            print(f"  FILE ERROR on {rel}: {exc}", file=sys.stderr)

    print("\nWiki update complete.")


if __name__ == "__main__":
    main()
