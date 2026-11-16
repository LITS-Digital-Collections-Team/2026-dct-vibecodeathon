# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Patrick R. Wallace, Hamilton College LITS
# This file is part of Mnemotron Wiki. See LICENSE for terms.
#
# AI ASSISTANCE NOTICE: Created with assistance from Claude Code (Claude
# Sonnet 5.5). It may not have been fully reviewed by a human; test it in your
# own environment before relying on it.

"""
locking.py — Safe concurrent writes for manifests, logs and wiki pages.

Several agents or scripts may run at once (parallel work units, a scheduled
job overlapping a manual run).  Plain `json.dump(open(path, "w"))` loses
updates and can leave a half-written file.  This module gives every writer:

  file_lock(path)                 advisory inter-process lock (flock; falls back
                                  to an O_EXCL lock file where flock is missing)
  atomic_write_text(path, text)   write to a temp file in the same directory,
                                  fsync, then os.replace  (readers never see a
                                  partial file; a crash never truncates)
  atomic_write_json(path, obj)
  read_json(path, default)
  update_json(path, fn)           locked read-modify-write: fn(current) -> new
  merge_save_json(path, data)     locked "union" save: re-reads the file, merges
                                  `data` over it key by key, writes atomically.
                                  Use for append-style manifests keyed by hash/ID
                                  so concurrent writers never drop each other's
                                  entries.  (Pass delete_keys=[...] to remove.)
  page_lock(page_path)            lock for read-modify-write of one wiki page.

Locks are advisory: they protect code that uses them.  Wiki *pages* are
additionally coordinated by `agent_manifest.py` (page ownership claims) so two
agents do not write the same page at all; page_lock() is a safety net for
scripts that edit pages.

Environment: MNEMOTRON_LOCK_TIMEOUT_S (default 60) — how long to wait for a lock.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from pathlib import Path

try:
    import fcntl  # POSIX
except ImportError:  # Windows
    fcntl = None

LOCK_TIMEOUT_S = float(os.environ.get("MNEMOTRON_LOCK_TIMEOUT_S", "60"))


class LockTimeout(RuntimeError):
    pass


@contextlib.contextmanager
def file_lock(path, timeout: float | None = None):
    """Exclusive lock keyed on *path* (a sibling `<name>.lock` file is used)."""
    path = Path(path)
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = LOCK_TIMEOUT_S if timeout is None else timeout
    deadline = time.monotonic() + timeout
    if fcntl is not None:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise LockTimeout(f"Timed out waiting for lock on {path}")
                    time.sleep(0.05)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
    else:  # portable fallback: create-exclusive lock file
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                try:  # break locks left by a crashed process after 10 minutes
                    if time.time() - lock_path.stat().st_mtime > 600:
                        lock_path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    raise LockTimeout(f"Timed out waiting for lock on {path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            with contextlib.suppress(FileNotFoundError):
                lock_path.unlink()


def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def atomic_write_json(path, obj, **dump_kwargs) -> None:
    dump_kwargs.setdefault("indent", 2)
    dump_kwargs.setdefault("ensure_ascii", False)
    atomic_write_text(path, json.dumps(obj, **dump_kwargs) + "\n")


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return {} if default is None else default
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    return json.loads(text) if text else ({} if default is None else default)


def update_json(path, fn, default=None, **dump_kwargs):
    """Locked read-modify-write.  fn receives the current object and returns the new one."""
    with file_lock(path):
        new = fn(read_json(path, default))
        atomic_write_json(path, new, **dump_kwargs)
        return new


def merge_save_json(path, data: dict, delete_keys=(), **dump_kwargs) -> dict:
    """Locked union save for manifests keyed by hash/ID (see module docstring)."""
    def _merge(current):
        current = dict(current or {})
        current.update(data)
        for k in delete_keys:
            current.pop(k, None)
        return current
    return update_json(path, _merge, default={}, **dump_kwargs)


@contextlib.contextmanager
def page_lock(page_path, timeout: float | None = None):
    """Lock a single wiki page for a read-modify-write."""
    with file_lock(page_path, timeout):
        yield
