"""Batches independent `claude -p` calls into shared Claude Code sessions.

Why this module exists: every `claude -p ...` subprocess call starts a
distinct Claude Code session, tracked and billed as one, regardless of how
trivial the request. The original ocr-pipeline-modular project called
`claude -p` once per page (OCR transcription) and once per low-confidence
text block (correction) -- a single 116-page batch run alone produced well
over a hundred sessions, and across a real workload this added up to
thousands of sessions in Anthropic's usage analytics for what is
conceptually one job.

This module keeps the same OAuth/CLI mechanism (no ANTHROPIC_API_KEY, reuses
whatever `claude /login` session is already active) but chains up to
`session_batch_size` independent calls into ONE continuing Claude Code
session via `--session-id` (first call) / `--resume` (later calls), instead
of starting a fresh session per call. Each item is still sent as its own
turn -- this never combines multiple images or text blocks into a single
prompt, which would risk the model conflating content across them. What
changes is only which session each turn's `claude -p` invocation belongs to.

Because turns in the same session still share conversation history (earlier
images/text are still technically in context, even sent as separate turns),
every prompt built on top of this module should explicitly tell Claude to
treat each turn as independent and ignore earlier turns' content -- see
02_ocr_extract.py and 03_text_correct.py's prompt templates.
"""

import json
import logging
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, TypeVar

logger = logging.getLogger(__name__)

DEFAULT_SESSION_BATCH_SIZE = 15


@dataclass
class ClaudeCallResult:
    """Outcome of one turn sent through a ClaudeSession."""
    ok: bool
    result_text: str = ""
    payload: dict = field(default_factory=dict)
    error: Optional[str] = None


class ClaudeSession:
    """One continuing `claude -p` session, reused across up to `batch_size`
    calls before rolling over to a fresh session id.

    Not thread-safe for concurrent calls on the *same* instance by design --
    `--resume` depends on the previous turn having already completed, so
    calls on one ClaudeSession must be made sequentially. Run multiple
    ClaudeSession instances in parallel (one per group of items) instead;
    see run_in_batched_sessions().
    """

    def __init__(
        self,
        claude_bin: str,
        batch_size: int = DEFAULT_SESSION_BATCH_SIZE,
        disallowed_tools: str = "",
        timeout: int = 180,
    ):
        self.claude_bin = claude_bin
        self.batch_size = max(1, batch_size)
        self.disallowed_tools = disallowed_tools
        self.timeout = timeout
        self._session_id: Optional[str] = None
        self._calls_in_session = 0

    def call(self, prompt: str) -> ClaudeCallResult:
        """Send one turn. Starts a fresh session on the first call, after
        `batch_size` calls, or after any failure (so one broken session
        can't poison every remaining item in the group)."""
        fresh = self._session_id is None or self._calls_in_session >= self.batch_size
        if fresh:
            self._session_id = str(uuid.uuid4())
            self._calls_in_session = 0
            session_args = ["--session-id", self._session_id]
        else:
            session_args = ["--resume", self._session_id]

        cmd = [self.claude_bin, "-p", prompt, "--output-format", "json", *session_args]
        if self.disallowed_tools:
            cmd += ["--disallowed-tools", self.disallowed_tools]

        try:
            # stdin=DEVNULL: inherited stdin stalls for several seconds per
            # call under a GUI whose own stdin is a pipe that never closes.
            proc = subprocess.run(
                cmd, capture_output=True, encoding="utf-8", timeout=self.timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            self._session_id = None
            return ClaudeCallResult(ok=False, error="claude CLI timed out")

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None

        # Substantive failures (expired OAuth, quota, API errors) come back
        # as JSON on stdout; stderr generally carries only warnings.
        if proc.returncode != 0 or (payload or {}).get("is_error"):
            self._session_id = None
            detail = (payload or {}).get("result") or stderr.strip() or "(no detail)"
            return ClaudeCallResult(
                ok=False, payload=payload or {},
                error=f"claude CLI failed (exit {proc.returncode}): {str(detail)[:300]}",
            )

        if payload is None:
            self._session_id = None
            if not stdout.strip():
                error = f"claude CLI produced no readable output (stderr: {stderr.strip()[:200] or '<empty>'})"
            else:
                error = f"claude CLI returned invalid JSON: {stdout[:200]}"
            return ClaudeCallResult(ok=False, error=error)

        self._calls_in_session += 1
        return ClaudeCallResult(ok=True, result_text=(payload.get("result") or "").strip(), payload=payload)


T = TypeVar("T")
R = TypeVar("R")


def run_in_batched_sessions(
    items: List[T],
    call_fn: Callable[[ClaudeSession, T], R],
    claude_bin: str,
    session_batch_size: int = DEFAULT_SESSION_BATCH_SIZE,
    workers: int = 1,
    disallowed_tools: str = "",
    timeout: int = 180,
) -> List[R]:
    """Process `items` through `call_fn(session, item)`, grouping consecutive
    items into chunks of `session_batch_size` that share one ClaudeSession
    (one continuing `claude` session per chunk), and running up to `workers`
    chunks concurrently -- so session count still drops by ~session_batch_size
    even when `workers` > 1 restores per-chunk parallelism.

    call_fn is responsible for building its own prompt from `item` and
    interpreting the returned ClaudeCallResult; on ok=False it should decide
    what to return (e.g. the original, uncorrected value) rather than raise,
    so one bad item doesn't abort the rest of its chunk.

    Returns results in the same order as `items`.
    """
    if not items:
        return []

    chunks = [items[i:i + session_batch_size] for i in range(0, len(items), session_batch_size)]
    results: List[Any] = [None] * len(items)

    def process_chunk(chunk_index: int, chunk_items: List[T]) -> None:
        session = ClaudeSession(
            claude_bin, batch_size=session_batch_size,
            disallowed_tools=disallowed_tools, timeout=timeout,
        )
        offset = chunk_index * session_batch_size
        for i, item in enumerate(chunk_items):
            results[offset + i] = call_fn(session, item)

    logger.info(
        f"Processing {len(items)} item(s) in {len(chunks)} session(s) of up to "
        f"{session_batch_size}, {workers} concurrently"
    )

    if workers > 1 and len(chunks) > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process_chunk, idx, chunk) for idx, chunk in enumerate(chunks)]
            for future in futures:
                future.result()
    else:
        for idx, chunk in enumerate(chunks):
            process_chunk(idx, chunk)

    return results
