<!--
SPDX-License-Identifier: GFDL-1.3-or-later
Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
Permission is granted to copy, distribute and/or modify this document under the terms of the GNU Free Documentation License, Version 1.3 or any later version published by the Free Software Foundation; with no Invariant Sections, no Front-Cover Texts, and no Back-Cover Texts.

AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude Sonnet 5.5). It may not have been fully reviewed by a human; test it in your own environment before relying on it.
-->

# Authentication: connecting Mnemotron Wiki to Claude

> Created with assistance from Claude Code (Claude Sonnet 5.5); may not have been fully reviewed by a human.

Every script that calls Claude goes through `scripts/llm.py`. It has two backends.
**The default is headless Claude Code.** The API is the alternative.

| | `cli` — headless Claude Code (default) | `api` — Anthropic API |
|---|---|---|
| What runs | `claude -p ...` as a subprocess | the `anthropic` Python SDK |
| Credentials | Claude Code's own login (subscription, Team/Enterprise SSO) or a long-lived token | An API key (or other SDK-supported credential) |
| Billing | Your Claude plan | Pay-as-you-go API credit |
| Needs installed | Claude Code | `pip install anthropic` |
| Best for | Personal use, workplace seats, unattended jobs on your own machine | Servers/CI without Claude Code, per-token billing, proxies/gateways |

The task documents (`*_TASK.md`) are instructions for an *agent*. `scripts/run_task.py` runs them
on **either** backend: headless Claude Code (`cli`), or a built-in API agent loop (`api`) that
needs only an API key and no Claude Code installation. You lose no functionality by choosing
either method. Nothing here requires an API key unless you choose `api`.

## 1. How the backend is chosen

First match wins:

1. Environment variable `MNEMOTRON_BACKEND=cli|api|auto`
2. `"llm": {"backend": "..."}` in `config.local.json` (untracked, per machine)
3. `auto` (the default): **`cli` if the `claude` executable is found**, otherwise `api` if any API
   credential is available, otherwise an error.

An `ANTHROPIC_API_KEY` in your environment does **not** switch you to the API while Claude Code
is installed. To use the API on purpose, set `MNEMOTRON_BACKEND=api`.

Check what will happen, without spending anything:

```bash
python scripts/check_auth.py            # report
python scripts/check_auth.py --call     # also send one tiny test request
python scripts/check_auth.py --backend api --call
```

## 2. Option A — headless Claude Code (default)

1. Install Claude Code (see Anthropic's documentation) so that `claude` is on your `PATH`.
2. Log in once. Run `claude` interactively and follow the prompts (consumer subscription, or your
   organization's Team/Enterprise single sign-on).
3. Verify: `python scripts/check_auth.py --call`.

**Unattended runs (cron, launchd, CI on your own machine).** Interactive logins can expire or need
a browser. For jobs without a person present, create a long-lived token once, on a machine where
you are logged in:

```bash
claude setup-token        # prints a token; copy it into your secret store, not into the repo
```

Then expose it to the job as `CLAUDE_CODE_OAUTH_TOKEN` in the job's environment (for example from
your scheduler's secret store). Use a dedicated, least-privilege account where your organization
allows it, and check that unattended automated use is within your plan's terms.

**Why API keys are stripped.** If `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) is set, the
`claude` CLI prefers it over your login, even when that key has no credit, which produces confusing
billing errors. So the `cli` backend removes those variables from the subprocess environment and the
CLI falls back to its own login. To keep them (you *want* the CLI to bill an API key), set
`MNEMOTRON_CLI_KEEP_API_KEY=1`.

Other settings: `MNEMOTRON_CLAUDE_BIN` (path to `claude`), `MNEMOTRON_CLI_MODEL` (alias, default
`haiku`), `MNEMOTRON_CLI_VISION_MODEL`, `MNEMOTRON_TIMEOUT_S` (default 300).

## 3. Option B — the Anthropic API

1. `pip install anthropic`
2. Provide credentials by **any one** of the following (checked in this order):

| Method | How | Notes |
|---|---|---|
| Environment variable | `export ANTHROPIC_API_KEY="<your key>"` | Simple. Put it in your shell profile or the job's secret store, never in a committed file. |
| Key file | `export MNEMOTRON_API_KEY_FILE=~/.config/mnemotron/anthropic.key` | File contains only the key. `chmod 600` it. Keeps the key out of your environment and shell history. |
| Key command | `export MNEMOTRON_API_KEY_COMMAND='security find-generic-password -s anthropic -w'` | Any command that prints the key, run without a shell. Works with a secret manager, e.g. `pass show anthropic`, `op read op://Private/Anthropic/credential`, a cloud secrets CLI. Fetched on use, never stored. |
| SDK-native sources | `ANTHROPIC_AUTH_TOKEN`, an `ant auth login` profile, workload identity federation | Resolved by the SDK itself when none of the above is set. |

3. Select the backend: `export MNEMOTRON_BACKEND=api`
4. Verify: `python scripts/check_auth.py --backend api --call`

Proxy or gateway: set `ANTHROPIC_BASE_URL` (honored by the SDK).

Models (override as needed; check current availability and prices before large runs):
`MNEMOTRON_API_MODEL` (default `claude-haiku-5-5`, used for text) and
`MNEMOTRON_API_VISION_MODEL` (default `claude-sonnet-5-5`, used for image transcription).

### Per-machine settings file

Instead of environment variables you can create `config.local.json` in the wiki root. It is
git-ignored. Never put a key itself in it, only a pointer to one.

```json
{
  "llm": {
    "backend": "api",
    "api_key_file": "~/.config/mnemotron/anthropic.key",
    "api_model": "claude-haiku-5-5",
    "api_vision_model": "claude-sonnet-5-5"
  }
}
```

Keys: `backend`, `claude_bin`, `cli_model`, `cli_vision_model`, `cli_keep_api_key`, `timeout_s`,
`api_key_file`, `api_key_command`, `api_model`, `api_vision_model`. Environment variables win over
this file.

Amazon Bedrock, Google Vertex AI and Microsoft Foundry are not wired into `llm.py`. If you need one
of them, the supported route is Claude Code configured for that provider (Option A).

## 4. Troubleshooting

| Message | Cause and fix |
|---|---|
| `No Claude backend available` | Neither `claude` nor an API credential was found. Install Claude Code and log in, or follow Option B. |
| `claude CLI error: ... login` | Not logged in. Run `claude` interactively once, or provide `CLAUDE_CODE_OAUTH_TOKEN`. |
| CLI mentions credit or billing though you have a subscription | An API key is being used. Leave `MNEMOTRON_CLI_KEEP_API_KEY` unset (the default). |
| `No Anthropic API credentials found` | `api` backend selected but no key was found. See the table in section 3. |
| `Anthropic API authentication failed` | Key is wrong, revoked or from another workspace. |
| `Your credit balance is too low` | The API key's account has no credit. Add credit, or use `cli`. |
| `claude CLI timed out` | Raise `MNEMOTRON_TIMEOUT_S` for large inputs. |
| `MNEMOTRON_API_KEY_COMMAND returned no key` | Run the command by hand; it must print only the key and exit 0. |

## 5. Security checklist

* Never commit keys or tokens. `.gitignore` already excludes `.env`, `config.local.json`, `*.key` and `*.pem`.
* Prefer a key file, key command or secret manager over a plain environment variable on shared machines.
* Content you ingest is sent to Anthropic by either backend. Do not ingest material you are not permitted to share.
* Concurrent runs are safe for the manifests and page claims (see `scripts/locking.py` and
  `scripts/agent_manifest.py`), but each parallel run makes its own Claude calls and uses your quota.
