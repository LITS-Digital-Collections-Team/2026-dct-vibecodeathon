#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
check_auth.py — Show which Claude backend the scripts will use and verify it works.

    python scripts/check_auth.py              # report only (no network, no cost)
    python scripts/check_auth.py --call       # also send one tiny test request
    python scripts/check_auth.py --backend api --call    # test a specific backend

Never prints secret values.  See AUTHENTICATION.md for setup instructions.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["cli", "api"], help="test this backend instead of the configured one")
    ap.add_argument("--call", action="store_true", help="make one small real request (uses a few tokens)")
    args = ap.parse_args()
    if args.backend:
        os.environ["MNEMOTRON_BACKEND"] = args.backend

    from scripts import llm
    info = llm.describe()
    print(json.dumps(info, indent=2))
    if info.get("backend") is None:
        print("\nNo usable backend. See AUTHENTICATION.md.", file=sys.stderr)
        return 2
    print(f"\nSelected backend: {info['backend']}")
    if not args.call:
        print("(Run with --call to send a one-word test request.)")
        return 0
    try:
        reply = llm.generate("Reply with exactly one word.", "Say hello.")
    except llm.LLMError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    print(f"OK — model replied: {reply!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
