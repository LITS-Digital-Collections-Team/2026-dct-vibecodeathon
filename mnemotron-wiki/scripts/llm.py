# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
llm.py — One interface for every script that needs to call Claude.

Two interchangeable backends:

  cli   (default) Runs headless Claude Code: `claude -p ...`.  Uses whatever
        login Claude Code already has — subscription, Teams/Enterprise SSO, or a
        long-lived token from `claude setup-token` exported as
        CLAUDE_CODE_OAUTH_TOKEN.  No API key and no SDK required.
  api   Calls the Anthropic Messages API with the `anthropic` Python SDK.
        See AUTHENTICATION.md for every way to supply credentials.

Choosing the backend (first match wins):
  1. MNEMOTRON_BACKEND=cli | api | auto          (environment)
  2. "backend" under "llm" in config.local.json   (optional, untracked)
  3. auto  ->  cli if the `claude` executable is found, otherwise api if any API
     credential is available, otherwise an error that explains both options.
Headless Claude Code is therefore the default whenever it is installed, even if
an API key also happens to be in your environment.  Set MNEMOTRON_BACKEND=api
to use the API deliberately.

Nothing in this file contains credentials.  Never commit keys or tokens.

Settings (environment variable  |  config.local.json "llm" key  |  default)
--------------------------------------------------------------------------
  MNEMOTRON_BACKEND            backend             cli|api|auto  (auto)
  MNEMOTRON_CLAUDE_BIN         claude_bin          path to the claude executable
  MNEMOTRON_CLI_MODEL          cli_model           alias for CLI text calls (haiku)
  MNEMOTRON_CLI_VISION_MODEL   cli_vision_model    alias for CLI image calls (= cli_model)
  MNEMOTRON_CLI_KEEP_API_KEY   cli_keep_api_key    1 = do NOT strip ANTHROPIC_API_KEY /
                               ANTHROPIC_AUTH_TOKEN from the CLI subprocess.  By default
                               they are stripped so the CLI uses its own login instead of
                               billing an API key that may have no credit.
  MNEMOTRON_TIMEOUT_S          timeout_s           CLI timeout seconds (300)
  MNEMOTRON_API_MODEL          api_model           text model ID (claude-haiku-5-5)
  MNEMOTRON_API_VISION_MODEL   api_vision_model    image model ID (claude-sonnet-5-5)
  API credentials, first found wins:
    ANTHROPIC_API_KEY | MNEMOTRON_API_KEY_FILE (path to a file holding only the key) |
    MNEMOTRON_API_KEY_COMMAND (a command, run without a shell, that prints the key —
    e.g. a secret-manager CLI) | whatever the SDK itself resolves
    (ANTHROPIC_AUTH_TOKEN, an `ant auth login` profile, workload identity federation).
    ANTHROPIC_BASE_URL is honored by the SDK (proxies, gateways).

Public functions
----------------
  generate(system_prompt, user_content, *, model=None, max_tokens=16000) -> str
  generate_from_image(system_prompt, image_path, instruction, *, model=None,
                      max_tokens=4096) -> str
  backend_name() -> "cli" | "api"
  describe() -> dict          (diagnostics; never includes secret values)
  api_client() -> (anthropic_module, client)   (for agent loops; same credentials)
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_API_KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
_RETRYABLE_STATUSES = {429, 500, 502, 503, 529}

_local_cache: dict | None = None


def _local_llm_config() -> dict:
    """The optional "llm" object from config.local.json (untracked, per-machine)."""
    global _local_cache
    if _local_cache is None:
        _local_cache = {}
        path = _ROOT / "config.local.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                _local_cache = data.get("llm", {}) if isinstance(data, dict) else {}
            except (OSError, ValueError):
                _local_cache = {}
    return _local_cache


def _opt(env_name: str, key: str, default=None):
    """Resolve a setting: environment first, then config.local.json, then default."""
    val = os.environ.get(env_name)
    if val not in (None, ""):
        return val
    val = _local_llm_config().get(key)
    return default if val in (None, "") else val


class LLMError(RuntimeError):
    """Raised for any backend failure (missing CLI, auth, timeout, API error)."""


# --------------------------------------------------------------------------- #
# Credential discovery (API backend)
# --------------------------------------------------------------------------- #
def _claude_bin() -> str | None:
    explicit = _opt("MNEMOTRON_CLAUDE_BIN", "claude_bin")
    if explicit:
        return explicit if Path(explicit).exists() else shutil.which(explicit)
    return shutil.which("claude")


def _api_key() -> tuple[str | None, str]:
    """Return (key or None, source description).  None => let the SDK resolve."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"], "ANTHROPIC_API_KEY"
    key_file = _opt("MNEMOTRON_API_KEY_FILE", "api_key_file")
    if key_file:
        try:
            key = Path(os.path.expanduser(str(key_file))).read_text(encoding="utf-8").strip()
        except OSError as e:
            raise LLMError(f"Could not read MNEMOTRON_API_KEY_FILE ({key_file}): {e}") from e
        if key:
            return key, "MNEMOTRON_API_KEY_FILE"
    cmd = _opt("MNEMOTRON_API_KEY_COMMAND", "api_key_command")
    if cmd:
        try:
            out = subprocess.run(shlex.split(str(cmd)), capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise LLMError(f"MNEMOTRON_API_KEY_COMMAND failed to run: {e}") from e
        if out.returncode != 0 or not out.stdout.strip():
            raise LLMError("MNEMOTRON_API_KEY_COMMAND returned no key (exit "
                           f"{out.returncode}). Run it by hand to debug.")
        return out.stdout.strip(), "MNEMOTRON_API_KEY_COMMAND"
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return None, "ANTHROPIC_AUTH_TOKEN (resolved by the SDK)"
    return None, "SDK default resolution (e.g. an `ant auth login` profile)"


def _have_api_credentials() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return bool(_opt("MNEMOTRON_API_KEY_FILE", "api_key_file") or
                _opt("MNEMOTRON_API_KEY_COMMAND", "api_key_command"))


# --------------------------------------------------------------------------- #
# Backend selection
# --------------------------------------------------------------------------- #
def backend_name() -> str:
    choice = str(_opt("MNEMOTRON_BACKEND", "backend", "auto")).strip().lower()
    if choice in ("cli", "api"):
        return choice
    if choice != "auto":
        raise LLMError(f"MNEMOTRON_BACKEND must be cli, api or auto (got {choice!r}).")
    if _claude_bin():
        return "cli"
    if _have_api_credentials():
        return "api"
    raise LLMError(
        "No Claude backend available. Default: install Claude Code and log in "
        "(headless `claude -p`). Alternative: `pip install anthropic` and provide an "
        "API key (see AUTHENTICATION.md), then set MNEMOTRON_BACKEND=api."
    )


def describe() -> dict:
    """Facts for diagnostics (check_auth.py).  Never returns secret values."""
    info = {"configured_backend": str(_opt("MNEMOTRON_BACKEND", "backend", "auto")),
            "claude_executable": _claude_bin()}
    try:
        info["backend"] = backend_name()
    except LLMError as e:
        info["backend"], info["error"] = None, str(e)
    try:
        _, src = _api_key()
        info["api_credential_source"] = src
    except LLMError as e:
        info["api_credential_source"] = f"error: {e}"
    info["claude_code_oauth_token_set"] = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
    info["cli_strips_api_keys"] = _opt("MNEMOTRON_CLI_KEEP_API_KEY", "cli_keep_api_key") != "1" \
        if str(_opt("MNEMOTRON_CLI_KEEP_API_KEY", "cli_keep_api_key", "0")) != "1" else False
    try:
        import anthropic  # noqa: F401
        info["anthropic_sdk"] = getattr(anthropic, "__version__", "installed")
    except ImportError:
        info["anthropic_sdk"] = None
    return info


# --------------------------------------------------------------------------- #
# CLI backend
# --------------------------------------------------------------------------- #
def _cli_env() -> dict:
    env = dict(os.environ)
    if str(_opt("MNEMOTRON_CLI_KEEP_API_KEY", "cli_keep_api_key", "0")) != "1":
        for var in _API_KEY_ENV_VARS:
            env.pop(var, None)
    return env


def _cli_run(args: list[str], input_text: str | None = None, max_retries: int = 3) -> str:
    claude_path = _claude_bin()
    if not claude_path:
        raise LLMError("The 'claude' CLI was not found (install Claude Code, set "
                       "MNEMOTRON_CLAUDE_BIN, or use MNEMOTRON_BACKEND=api).")
    timeout = int(_opt("MNEMOTRON_TIMEOUT_S", "timeout_s", 300))
    last_err = None
    for attempt in range(max_retries):
        try:
            proc = subprocess.run(
                [claude_path, *args], input=input_text, capture_output=True,
                text=True, env=_cli_env(), timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude CLI timed out after {timeout}s") from e
        stdout = proc.stdout.strip()
        if not stdout:
            raise LLMError(f"claude CLI produced no output (exit {proc.returncode}): {proc.stderr.strip()}")
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"Couldn't parse claude CLI output as JSON: {stdout[:500]}") from e
        if payload.get("is_error") or proc.returncode != 0:
            status = payload.get("api_error_status")
            message = payload.get("result") or proc.stderr.strip()
            if status in _RETRYABLE_STATUSES and attempt < max_retries - 1:
                last_err = message
                time.sleep(2 ** (attempt + 1))
                continue
            hint = ""
            if "login" in str(message).lower() or "auth" in str(message).lower():
                hint = " (Not logged in? Run `claude` once interactively, or see AUTHENTICATION.md.)"
            raise LLMError(f"claude CLI error: {message}{hint}")
        result = payload.get("result")
        if not result:
            raise LLMError(f"claude CLI returned an empty result: {payload}")
        return result.strip()
    raise LLMError(f"claude CLI failed after {max_retries} retries: {last_err}")


def _cli_model(vision: bool) -> str:
    text_model = str(_opt("MNEMOTRON_CLI_MODEL", "cli_model", "haiku"))
    return str(_opt("MNEMOTRON_CLI_VISION_MODEL", "cli_vision_model", text_model)) if vision else text_model


def _cli_generate(system_prompt, user_content, model):
    args = ["-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
            "--model", model or _cli_model(False)]
    if system_prompt:
        args += ["--system-prompt", system_prompt]
    return _cli_run(args, input_text=user_content)


def _cli_image(system_prompt, image_path, instruction, model):
    image_path = Path(image_path).resolve()
    args = ["-p", "--tools", "Read", "--allowedTools", "Read",
            "--output-format", "json", "--no-session-persistence",
            "--model", model or _cli_model(True)]
    if system_prompt:
        args += ["--system-prompt", system_prompt]
    args.append(f"{instruction}\n\nImage path: {image_path}")
    return _cli_run(args)


# --------------------------------------------------------------------------- #
# API backend
# --------------------------------------------------------------------------- #
def _api_client():
    try:
        import anthropic
    except ImportError as e:
        raise LLMError("The API backend needs the SDK: pip install anthropic") from e
    key, _src = _api_key()
    try:
        return anthropic, (anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic())
    except TypeError as e:
        raise LLMError("No Anthropic API credentials found. See AUTHENTICATION.md.") from e


def api_client():
    """Public: (anthropic module, configured client) using the same credential
    discovery as every other call (used by run_task.py's API agent loop)."""
    return _api_client()


def _api_call(messages, system_prompt, model, max_tokens):
    anthropic, client = _api_client()
    kwargs = dict(model=model, max_tokens=max_tokens, messages=messages)
    if system_prompt:
        kwargs["system"] = system_prompt
    try:
        resp = client.messages.create(**kwargs)
    except TypeError as e:  # SDK found no credential at request time
        raise LLMError("No Anthropic API credentials found. See AUTHENTICATION.md.") from e
    except anthropic.AuthenticationError as e:
        raise LLMError("Anthropic API authentication failed. Check your key (AUTHENTICATION.md).") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError(f"Network error talking to the Anthropic API: {e}") from e
    if resp.stop_reason == "refusal":
        raise LLMError("The model declined this request (stop_reason=refusal).")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise LLMError("The API returned no text content.")
    return text


def _api_generate(system_prompt, user_content, model, max_tokens):
    return _api_call([{"role": "user", "content": user_content}], system_prompt,
                     model or str(_opt("MNEMOTRON_API_MODEL", "api_model", "claude-haiku-5-5")), max_tokens)


def _api_image(system_prompt, image_path, instruction, model, max_tokens):
    path = Path(image_path)
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
        {"type": "text", "text": instruction},
    ]
    return _api_call([{"role": "user", "content": content}], system_prompt,
                     model or str(_opt("MNEMOTRON_API_VISION_MODEL", "api_vision_model", "claude-sonnet-5-5")),
                     max_tokens)


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #
def generate(system_prompt: str, user_content: str, *, model: str | None = None,
             max_tokens: int = 16000) -> str:
    """Plain text-in / text-out call with no tool access."""
    if backend_name() == "cli":
        return _cli_generate(system_prompt, user_content, model)
    return _api_generate(system_prompt, user_content, model, max_tokens)


def generate_from_image(system_prompt: str, image_path: str | Path, instruction: str,
                        *, model: str | None = None, max_tokens: int = 4096) -> str:
    """Vision call: describe or transcribe a local image file."""
    if backend_name() == "cli":
        return _cli_image(system_prompt, image_path, instruction, model)
    return _api_image(system_prompt, image_path, instruction, model, max_tokens)


if __name__ == "__main__":  # quick self-check:  python scripts/llm.py
    print("backend:", backend_name())
    print(generate("Reply with one word.", "Say hello."))
