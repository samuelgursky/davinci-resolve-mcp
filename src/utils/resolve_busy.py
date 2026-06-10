"""Cross-process visibility for long synchronous DaVinci Resolve operations.

The Resolve scripting bridge executes one call at a time. Most calls return in
milliseconds, but a handful block for seconds-to-minutes (timeline export and
import, scene-cut detection, subtitle generation, audio transcription). A
second tool call issued during one of those — from another thread of this
server, or from the other instance when stdio and networked servers share one
Resolve — simply hangs inside fusionscript with no feedback.

This module gives those long operations a name and a presence that every
instance can see, so the Resolve preflight can wait briefly and then return a
structured "busy" answer instead of hanging:

    with long_resolve_op("timeline.export"):
        tl.Export(...)

    op = wait_until_free(timeout_seconds=5.0)   # None when free
    if op:
        ... return a RESOLVE_BUSY error naming op["label"] ...

Registration is advisory and best-effort: a sidecar JSON file in the temp dir
(same approach as page_lock) carries {label, pid, thread, started_at}. Records
are ignored when their pid is dead or they exceed MAX_OP_AGE_SECONDS, so a
crashed operation can never wedge the server. The registering thread is exempt
from its own gate — long operations call Resolve helpers internally.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

_SIDECAR = os.path.join(tempfile.gettempdir(), "davinci_resolve_mcp_busy.json")
# A long op that has run this long is presumed crashed/leaked and ignored.
MAX_OP_AGE_SECONDS = 2 * 60 * 60
# Default time a preflight will wait for the bridge to free up before
# returning a busy error.
DEFAULT_WAIT_SECONDS = 5.0
_POLL_SECONDS = 0.25

_lock = threading.Lock()
_local_owner: Optional[int] = None  # thread ident of the in-process registrant


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _read_record() -> Optional[Dict[str, Any]]:
    try:
        with open(_SIDECAR, "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict) or not record.get("label"):
        return None
    started_at = record.get("started_at")
    if not isinstance(started_at, (int, float)):
        return None
    if time.time() - started_at > MAX_OP_AGE_SECONDS:
        return None
    pid = record.get("pid")
    if not isinstance(pid, int) or not _pid_alive(pid):
        return None
    return record


def _write_record(record: Dict[str, Any]) -> None:
    tmp_path = f"{_SIDECAR}.tmp-{os.getpid()}-{threading.get_ident()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        os.replace(tmp_path, _SIDECAR)
    except OSError:
        pass
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _clear_record() -> None:
    record = None
    try:
        with open(_SIDECAR, "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, json.JSONDecodeError):
        pass
    # Only the owning process removes the sidecar; never clobber another
    # instance's registration.
    if isinstance(record, dict) and record.get("pid") == os.getpid():
        try:
            os.remove(_SIDECAR)
        except OSError:
            pass


def current_long_op() -> Optional[Dict[str, Any]]:
    """The active long operation visible across instances, or None."""
    record = _read_record()
    if record is None:
        return None
    return {
        "label": record.get("label"),
        "pid": record.get("pid"),
        "same_process": record.get("pid") == os.getpid(),
        "started_at": record.get("started_at"),
        "age_seconds": round(max(0.0, time.time() - float(record.get("started_at", 0.0))), 1),
    }


@contextmanager
def long_resolve_op(label: str):
    """Register a long synchronous Resolve call for its duration."""
    global _local_owner
    ident = threading.get_ident()
    with _lock:
        nested = _local_owner is not None
        if not nested:
            _local_owner = ident
    if not nested:
        _write_record({
            "label": str(label),
            "pid": os.getpid(),
            "thread": ident,
            "started_at": time.time(),
        })
    try:
        yield
    finally:
        if not nested:
            with _lock:
                _local_owner = None
            _clear_record()


def wait_until_free(timeout_seconds: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Wait briefly for any long op to finish.

    Returns None when the bridge is free (or becomes free within the timeout),
    otherwise the still-running operation's info. The thread that registered
    the current in-process op is never gated by it. timeout_seconds defaults
    to DEFAULT_WAIT_SECONDS, read at call time so callers/tests can tune it.
    """
    if timeout_seconds is None:
        timeout_seconds = DEFAULT_WAIT_SECONDS
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        op = current_long_op()
        if op is None:
            return None
        if op["same_process"]:
            record = _read_record() or {}
            if record.get("thread") == threading.get_ident():
                return None
        if time.monotonic() >= deadline:
            return op
        time.sleep(_POLL_SECONDS)
