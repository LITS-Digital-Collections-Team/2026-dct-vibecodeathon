#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
run_task.py — Run a task document (*_TASK.md) with whichever Claude backend you use.

The task documents are instructions for an agent that can read and write files and run
the helper scripts.  This launcher provides that agent on EITHER backend, so no
functionality depends on how you authenticate:

  cli   Headless Claude Code (`claude -p`) does the agent work itself, with scoped
        permissions (file edits, the wiki's own scripts, read-only git plus add/commit).
        Claude Code's own subagents and any MCP connectors you have configured in
        Claude Code are available.
  api   A built-in, sandboxed tool-use loop over the Anthropic Messages API (file tools,
        allowlisted commands, `run_subtask` workers with exclusive page ownership, and
        optional remote MCP servers via --mcp).  Needs only an API key (see
        AUTHENTICATION.md); Claude Code is not required.

The backend is chosen exactly as for the scripts (scripts/llm.py): default headless
Claude Code, or set MNEMOTRON_BACKEND=api, or pass --backend.

Usage
-----
    python scripts/run_task.py RESEARCH_WIKI_TASK.md
    python scripts/run_task.py WIKI_UPDATE_TASK.md --prompt "Process only today's files."
    python scripts/run_task.py EMAIL_ARCHIVE_TASK.md --backend api \
        --mcp mail=https://mcp.example.com/mail --prompt "last 14 days"
    python scripts/run_task.py TASK.md --dry-run      # show what would run; no Claude call

Options
-------
  task                 task document path (relative to the wiki root)
  --prompt TEXT        extra instruction appended to the kickoff message
  --backend cli|api    override the configured backend for this run
  --model ID           cli: alias (default $MNEMOTRON_AGENT_MODEL or "sonnet");
                       api: model ID (default $MNEMOTRON_AGENT_MODEL or claude-sonnet-5-5)
  --max-turns N        api only: API round trips before stopping (default 400)
  --max-budget-usd N   cli only: stop when this much has been spent
  --allow-tool PATTERN cli only: extra Claude Code permission rule (repeatable), e.g.
                       "mcp__myserver__*" to let the agent use an MCP connector
  --mcp NAME=URL       api only: attach a remote MCP server (repeatable); a bearer token,
                       if needed, is read from MNEMOTRON_MCP_<NAME>_TOKEN (never on the CLI)
  --no-commit          forbid `git commit` for this run
  --dry-run            print the plan, make no Claude call
  --force              run even if another run_task.py for this wiki appears active

Safety
------
* One run at a time per wiki: a lock (scripts/.cache/run_task.lock) refuses overlapping
  runs unless --force.  Overlapping scripts are separately protected by scripts/locking.py.
* api sandbox: file tools only reach inside the wiki root; `.git/`, `.env*`, `LICENSE*`
  and this file are not writable; `delete_file` works only inside raw_ingest/;
  `run_command` never uses a shell (python3 scripts in this wiki, git
  status/log/diff/add/commit/show/rev-parse, ls, wc, head, tail, grep, find without
  -exec/-delete, mkdir).  Workers claim their pages exclusively and cannot commit.
* cli permissions are the explicit allowlist built below, with edit prompts auto-accepted
  and everything else denied (nobody is there to answer prompts).
* Each api run writes a JSONL transcript to scripts/.cache/agent-runs/.
Content you process is sent to Anthropic by either backend.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import llm  # noqa: E402
from scripts.locking import LockTimeout, file_lock  # noqa: E402

RUN_DIR = ROOT / "scripts" / ".cache" / "agent-runs"
MAX_RESULT_CHARS = 30_000

READ_ONLY_NAMES = {"LICENSE", "NOTICE.md", "run_task.py"}
HIDDEN_PREFIXES = (".git/", ".env")
GIT_ALLOWED = {"status", "log", "diff", "add", "commit", "show", "rev-parse"}
PROGRAMS_ALLOWED = {"python3", "python", "git", "ls", "wc", "head", "tail", "grep", "find", "mkdir"}
DEFAULT_API_MODEL = os.environ.get("MNEMOTRON_AGENT_MODEL", "claude-sonnet-5-5")
DEFAULT_CLI_MODEL = os.environ.get("MNEMOTRON_AGENT_MODEL", "sonnet")


# --------------------------------------------------------------------------- #
# Sandbox helpers
# --------------------------------------------------------------------------- #
class SandboxError(Exception):
    pass


def _resolve(path: str, *, write: bool = False, owned: list[str] | None = None) -> Path:
    p = (ROOT / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
    try:
        rel = p.relative_to(ROOT).as_posix()
    except ValueError:
        raise SandboxError(f"Path is outside the wiki root: {path}")
    if rel.startswith(HIDDEN_PREFIXES) or rel == ".git":
        raise SandboxError(f"Path is not accessible: {rel}")
    if write:
        if p.name in READ_ONLY_NAMES or rel.startswith("LICENSES/"):
            raise SandboxError(f"Path is read-only: {rel}")
        if owned is not None and not any(rel == o or rel.startswith(o.rstrip("/") + "/") for o in owned):
            raise SandboxError(f"This worker only owns: {owned}. Cannot write {rel}.")
    return p


def _clip(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + f"\n...[truncated {len(text) - MAX_RESULT_CHARS} chars; read in parts with offset/limit]"


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #
def t_read_file(path, offset=0, limit=2000, **_):
    p = _resolve(path)
    if not p.is_file():
        return f"Not a file: {path}"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    chunk = lines[offset: offset + limit]
    out = "\n".join(f"{i + offset + 1}\t{l}" for i, l in enumerate(chunk))
    if offset + limit < len(lines):
        out += f"\n...[{len(lines) - offset - limit} more lines; pass offset={offset + limit}]"
    return out


def t_write_file(path, content, owned=None, **_):
    p = _resolve(path, write=True, owned=owned)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {p.relative_to(ROOT)}"


def t_edit_file(path, old_string, new_string, owned=None, **_):
    p = _resolve(path, write=True, owned=owned)
    text = p.read_text(encoding="utf-8")
    n = text.count(old_string)
    if n != 1:
        return f"old_string must occur exactly once (found {n}). No change made."
    p.write_text(text.replace(old_string, new_string), encoding="utf-8")
    return f"Edited {p.relative_to(ROOT)}"


def t_list_dir(path=".", **_):
    p = _resolve(path)
    if not p.is_dir():
        return f"Not a directory: {path}"
    rows = []
    for c in sorted(p.iterdir()):
        rel = c.relative_to(ROOT).as_posix()
        if rel.startswith(HIDDEN_PREFIXES) or rel == ".git":
            continue
        rows.append(rel + ("/" if c.is_dir() else ""))
    return "\n".join(rows[:1000]) or "(empty)"


def t_delete_file(path, **_):
    p = _resolve(path, write=True)
    rel = p.relative_to(ROOT).as_posix()
    if not rel.startswith("raw_ingest/"):
        return "delete_file is limited to files inside raw_ingest/."
    if not p.is_file():
        return f"Not a file: {rel}"
    p.unlink()
    return f"Deleted {rel}"


def t_run_command(command, no_commit=False, **_):
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return f"Could not parse command: {e}"
    if not argv:
        return "Empty command."
    prog = argv[0]
    if prog not in PROGRAMS_ALLOWED:
        return f"Program not allowed: {prog}. Allowed: {sorted(PROGRAMS_ALLOWED)}"
    if prog.startswith("python"):
        if len(argv) < 2 or argv[1].startswith("-"):
            return "python3 must be given a script path (no -c / -m)."
        script = _resolve(argv[1])
        if script.suffix != ".py" or script.name == "run_task.py":
            return "Only the wiki's own .py scripts may be run."
        argv = [sys.executable, str(script), *argv[2:]]
    elif prog == "git":
        sub = argv[1] if len(argv) > 1 else ""
        if sub not in GIT_ALLOWED or (sub == "commit" and no_commit):
            return f"git {sub!r} is not allowed here."
    elif prog == "find" and any(a in ("-exec", "-execdir", "-delete", "-ok") for a in argv):
        return "find with -exec/-delete is not allowed."
    for a in argv[1:]:  # keep path arguments inside the sandbox
        if not a.startswith("-") and (a.startswith("/") or ".." in Path(a).parts):
            try:
                _resolve(a)
            except SandboxError as e:
                return str(e)
    try:
        proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return "Command timed out after 900s."
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr.strip() else "")
    return _clip(f"[exit {proc.returncode}]\n{out}")


TOOL_FUNCS = {
    "read_file": t_read_file, "write_file": t_write_file, "edit_file": t_edit_file,
    "list_dir": t_list_dir, "delete_file": t_delete_file, "run_command": t_run_command,
}

TOOL_DEFS = [
    {"name": "read_file", "description": "Read a text file inside the wiki root (line-numbered). Use offset/limit for big files.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Create or overwrite a text file inside the wiki root.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace one exact, unique occurrence of old_string with new_string in a file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["path", "old_string", "new_string"]}},
    {"name": "list_dir", "description": "List a directory inside the wiki root.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}},
    {"name": "delete_file", "description": "Delete a file inside raw_ingest/ (only after it has been processed and recorded in the manifest, as the task says).",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "run_command", "description": "Run one allowed command without a shell, e.g. `python3 scripts/check_ingest.py`, `git status`, `grep -rn term wiki/topics`, `ls wiki`, `wc -l file`. No pipes, redirects or chaining.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
]

SUBTASK_DEF = {
    "name": "run_subtask",
    "description": ("Delegate a self-contained work unit to a worker that exclusively owns the listed pages "
                    "(it can write only those paths). Use for the task document's parallel work units. "
                    "Returns the worker's final summary. Do not give two workers the same page."),
    "input_schema": {"type": "object", "properties": {
        "prompt": {"type": "string", "description": "Complete instructions; the worker sees nothing else."},
        "owned_paths": {"type": "array", "items": {"type": "string"}, "description": "Files or directories the worker may write."}},
        "required": ["prompt", "owned_paths"]},
}


# --------------------------------------------------------------------------- #
# Agent loop
# --------------------------------------------------------------------------- #
class Runner:
    def __init__(self, model, max_turns, mcp, no_commit, log):
        anthropic, client = llm.api_client()   # same credential discovery as every other call
        self.anthropic, self.client = anthropic, client
        self.model, self.max_turns, self.mcp, self.no_commit, self.log = model, max_turns, mcp, no_commit, log

    def _tools(self, subtasks_ok):
        return list(TOOL_DEFS) + ([SUBTASK_DEF] if subtasks_ok else [])

    def _call(self, system, messages, tools):
        kwargs = dict(model=self.model, max_tokens=16000, system=system, messages=messages,
                      tools=list(tools), cache_control={"type": "ephemeral"})
        if self.mcp:
            kwargs["mcp_servers"] = [m["server"] for m in self.mcp]
            kwargs["tools"] += [{"type": "mcp_toolset", "mcp_server_name": m["server"]["name"]} for m in self.mcp]
            kwargs["betas"] = ["mcp-client-2025-11-20"]
            fn = self.client.beta.messages.create
        else:
            fn = self.client.messages.create
        for attempt in range(5):
            try:
                return fn(**kwargs)
            except (self.anthropic.RateLimitError, self.anthropic.APIConnectionError):
                time.sleep(min(2 ** attempt * 5, 60))
            except self.anthropic.APIStatusError as e:
                if e.status_code >= 500 and attempt < 4:
                    time.sleep(min(2 ** attempt * 5, 60))
                    continue
                raise
        raise RuntimeError("API retries exhausted")

    def run(self, system, kickoff, *, owned=None, depth=0, label="main"):
        messages = [{"role": "user", "content": kickoff}]
        tools = self._tools(subtasks_ok=(depth == 0))
        final_text = ""
        for turn in range(self.max_turns):
            resp = self._call(system, messages, tools)
            self.log({"label": label, "turn": turn, "stop": resp.stop_reason,
                      "usage": {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens,
                                "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0)}})
            if resp.stop_reason == "refusal":
                return final_text + "\n[stopped: the model declined to continue]"
            messages.append({"role": "assistant", "content": resp.content})
            texts = [b.text for b in resp.content if b.type == "text"]
            if texts:
                final_text = "\n".join(texts)
                if depth == 0:
                    print(final_text, flush=True)
            uses = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason == "tool_use" and uses:
                results = []
                for u in uses:
                    out = self._dispatch(u, owned, depth)
                    self.log({"label": label, "tool": u.name, "input": u.input, "result": out[:2000]})
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": out})
                messages.append({"role": "user", "content": results})
                continue
            if resp.stop_reason == "pause_turn":
                continue
            if resp.stop_reason == "max_tokens":
                messages.append({"role": "user", "content": "Continue from where you stopped."})
                continue
            return final_text  # end_turn
        return final_text + f"\n[stopped: reached --max-turns={self.max_turns}]"

    def _dispatch(self, use, owned, depth):
        try:
            if use.name == "run_subtask":
                sub_system = SYSTEM_BASE + ("\nYou are a worker. Do only the assigned work unit, write only to the pages you own, "
                                            "never write manifests or shared logs, and finish with a brief summary.")
                return self.run(sub_system, use.input["prompt"], owned=list(use.input["owned_paths"]),
                                depth=depth + 1, label=f"worker:{','.join(use.input['owned_paths'])[:60]}")
            fn = TOOL_FUNCS.get(use.name)
            if fn is None:
                return f"Unknown tool: {use.name}"
            kwargs = dict(use.input)
            if use.name in ("write_file", "edit_file"):
                kwargs["owned"] = owned
            if use.name == "run_command":
                kwargs["no_commit"] = self.no_commit or owned is not None  # workers never commit
            if use.name == "delete_file" and owned is not None:
                return "Workers cannot delete files."
            return _clip(fn(**kwargs))
        except SandboxError as e:
            return f"Sandbox: {e}"
        except Exception as e:  # report to the model so it can adapt
            return f"Error: {type(e).__name__}: {e}"


SYSTEM_BASE = (
    "You are running a Mnemotron Wiki task inside a sandboxed API agent. You have file tools, a restricted "
    "`run_command`, and (for the main agent) `run_subtask`. All paths are relative to the wiki root. "
    "Follow the task document exactly. Where it says to dispatch subagents, use run_subtask with exclusive page "
    "ownership. Only the main agent writes manifests and shared logs. If something the task needs is unavailable "
    "(for example an MCP connector that is not attached), say so, skip that stage, and continue with the rest. "
    "Never invent source content. Report what you did and anything skipped at the end."
)



# --------------------------------------------------------------------------- #
# CLI backend: headless Claude Code does the agent work
# --------------------------------------------------------------------------- #
CLI_ALLOWED_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep",
    "Bash(python3 scripts/*)", "Bash(python scripts/*)",
    "Bash(git status*)", "Bash(git log*)", "Bash(git diff*)", "Bash(git show*)",
    "Bash(git add*)", "Bash(git commit*)",
    "Bash(ls*)", "Bash(wc*)", "Bash(head*)", "Bash(tail*)", "Bash(grep*)", "Bash(find*)", "Bash(mkdir*)",
]


CLI_SYSTEM = (
    "You are running a Mnemotron Wiki task headlessly: no human can answer questions, so make "
    "reasonable choices and report them. Read the task document first, then follow it exactly. "
    "Use the wiki's helper scripts (python3 scripts/... or python3 <tool>.py in the wiki root). "
    "Run each git command as its own simple Bash call (git add ...; then git commit -m ...) — "
    "never chain commands with && or ;, which the permission rules do not match. For parallel work, give each worker "
    "exclusive pages and coordinate with scripts/agent_manifest.py (check, claim, release); only "
    "the orchestrating agent writes manifests and shared logs. If a stage needs something that is "
    "unavailable (for example an MCP connector), skip that stage and say so. Never invent source "
    "content. End with a short report of what you did and what you skipped."
)


def build_cli_command(task, kickoff, model, extra_allowed, no_commit, budget):
    claude = llm._claude_bin()
    if not claude:
        raise llm.LLMError("The 'claude' CLI was not found. Install Claude Code, or use --backend api.")
    allowed = [t for t in CLI_ALLOWED_TOOLS if not (no_commit and t == "Bash(git commit*)")]
    for script in sorted(ROOT.glob("*.py")):  # root-level tools (batch_ingest.py, wiki_export.py, ...)
        allowed += [f"Bash(python3 {script.name}*)", f"Bash(python {script.name}*)"]
    allowed += list(extra_allowed)
    cmd = [claude, "-p", kickoff, "--output-format", "text",
           "--permission-mode", "acceptEdits", "--no-session-persistence",
           "--model", model, "--allowedTools", *allowed]
    if budget:
        cmd += ["--max-budget-usd", str(budget)]
    cmd += ["--append-system-prompt", CLI_SYSTEM]
    return cmd


def run_cli(task, kickoff, model, extra_allowed, no_commit, budget) -> int:
    cmd = build_cli_command(task, kickoff, model, extra_allowed, no_commit, budget)
    return subprocess.run(cmd, cwd=ROOT, env=llm._cli_env()).returncode



def main():
    ap = argparse.ArgumentParser(description="Run a Mnemotron task document with headless Claude Code or the Claude API.")
    ap.add_argument("task")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--backend", choices=["cli", "api"])
    ap.add_argument("--model")
    ap.add_argument("--max-turns", type=int, default=400)
    ap.add_argument("--max-budget-usd", type=float)
    ap.add_argument("--allow-tool", action="append", default=[], metavar="PATTERN")
    ap.add_argument("--mcp", action="append", default=[], metavar="NAME=URL")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.backend:
        os.environ["MNEMOTRON_BACKEND"] = a.backend

    task_path = _resolve(a.task)
    if not task_path.is_file():
        sys.exit(f"Task document not found: {a.task}")
    try:
        backend = llm.backend_name()
    except llm.LLMError as e:
        sys.exit(str(e))
    rel_task = task_path.relative_to(ROOT).as_posix()
    kickoff = (f"Run the task described in {rel_task}. Today is {datetime.now().strftime('%Y-%m-%d')}."
               + (f"\nAdditional instructions: {a.prompt}" if a.prompt else ""))

    mcp = []
    for spec in a.mcp:
        name, _, url = spec.partition("=")
        if not name or not url.startswith("https://"):
            sys.exit(f"--mcp expects NAME=https://URL (got {spec!r})")
        server = {"type": "url", "url": url, "name": name}
        tok = os.environ.get("MNEMOTRON_MCP_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper() + "_TOKEN")
        if tok:
            server["authorization_token"] = tok
        mcp.append({"server": server})
    if mcp and backend == "cli":
        print("note: --mcp applies to the api backend; with the cli backend use the MCP servers "
              "configured in Claude Code and pass --allow-tool 'mcp__<server>__*'.", file=sys.stderr)

    model = a.model or (DEFAULT_CLI_MODEL if backend == "cli" else DEFAULT_API_MODEL)

    if a.dry_run:
        print(f"backend: {backend}\nmodel: {model}\ntask: {rel_task}\nkickoff: {kickoff}")
        if backend == "cli":
            print("command:", " ".join(shlex.quote(c) for c in build_cli_command(
                rel_task, kickoff, model, a.allow_tool, a.no_commit, a.max_budget_usd)))
        else:
            print("tools:", [t["name"] for t in TOOL_DEFS] + ["run_subtask"],
                  "\nmcp servers:", [m["server"]["name"] for m in mcp] or "none")
        return

    lock_target = ROOT / "scripts" / ".cache" / "run_task"
    try:
        guard = file_lock(lock_target, timeout=0 if not a.force else 1)
        guard.__enter__()
    except LockTimeout:
        sys.exit("Another run_task.py appears to be active for this wiki (use --force to override).")

    try:
        if backend == "cli":
            sys.exit(run_cli(rel_task, kickoff, model, a.allow_tool, a.no_commit, a.max_budget_usd))
        system = SYSTEM_BASE + "\n\n=== TASK DOCUMENT: " + rel_task + " ===\n" + task_path.read_text(encoding="utf-8")
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        log_path = RUN_DIR / (datetime.now().strftime("%Y%m%dT%H%M%S") + ".jsonl")
        logf = open(log_path, "a", encoding="utf-8")

        def log(rec):
            logf.write(json.dumps(rec, default=str) + "\n")
            logf.flush()

        Runner(model, a.max_turns, mcp, a.no_commit, log).run(system, kickoff)
        print(f"\n[transcript: {log_path.relative_to(ROOT)}]")
    finally:
        guard.__exit__(None, None, None)


if __name__ == "__main__":
    main()
