"""E2 — session-scoped repeated-failure tracker for the structured error envelope.

See local/design/agentic-flow-improvements-gameplan-2.md §3 task E2.

The model should not be the only line of defense against tight retry loops.
This module tracks per-(scope_key, action_name) failure counts in-process. When
the same scope hits a configurable threshold within a rolling window, the
caller can attach an `escalation` block to the next error response — a signal
to stop auto-retrying and ask the user for guidance.

Design choices:
- In-process only. Session-scoped on purpose: a server restart drops state so
  the agent's previous "grudge" doesn't leak across sessions.
- Successes for the same key clear the counter (transient failures shouldn't
  push the agent into escalation mode if the next attempt fixes things).
- Window-based reset: if no failure for `window_seconds`, the counter resets.
- scope_key is whatever the caller wants — typically a clip_id, a path, or
  the literal "__no_scope__" sentinel when no clip/path context exists.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Tuple

# Tuple of (scope_key, action_name) -> list of failure timestamps (epoch seconds).
_FAILURES: Dict[Tuple[str, str], List[float]] = {}
_LOCK = threading.Lock()

DEFAULT_THRESHOLD = 3
DEFAULT_WINDOW_SECONDS = 600
_NO_SCOPE = "__no_scope__"


def _now() -> float:
    return time.time()


def _prune_outside_window(timestamps: List[float], now: float, window: float) -> List[float]:
    cutoff = now - window
    return [t for t in timestamps if t >= cutoff]


def record_failure(scope_key: Optional[str], action_name: str,
                   *, now: Optional[float] = None,
                   window_seconds: int = DEFAULT_WINDOW_SECONDS) -> int:
    """Record a failure for (scope_key, action_name). Returns the current
    failure count within the rolling window after recording.
    """
    key = (scope_key or _NO_SCOPE, action_name)
    when = now if now is not None else _now()
    with _LOCK:
        timestamps = _prune_outside_window(_FAILURES.get(key, []), when, window_seconds)
        timestamps.append(when)
        _FAILURES[key] = timestamps
        return len(timestamps)


def record_success(scope_key: Optional[str], action_name: str) -> None:
    """A success on the same (scope_key, action_name) clears the failure counter."""
    key = (scope_key or _NO_SCOPE, action_name)
    with _LOCK:
        _FAILURES.pop(key, None)


def get_failure_state(scope_key: Optional[str], action_name: str,
                      *, now: Optional[float] = None,
                      window_seconds: int = DEFAULT_WINDOW_SECONDS) -> Dict[str, object]:
    """Return current failure state for (scope_key, action_name) without mutating."""
    key = (scope_key or _NO_SCOPE, action_name)
    when = now if now is not None else _now()
    with _LOCK:
        timestamps = _prune_outside_window(_FAILURES.get(key, []), when, window_seconds)
        if not timestamps:
            return {"failure_count": 0,
                    "first_failure_at": None,
                    "last_failure_at": None}
        return {"failure_count": len(timestamps),
                "first_failure_at": _iso(timestamps[0]),
                "last_failure_at": _iso(timestamps[-1])}


def build_escalation_block(scope_key: Optional[str], action_name: str,
                           error_category: str,
                           *, threshold: int = DEFAULT_THRESHOLD,
                           window_seconds: int = DEFAULT_WINDOW_SECONDS,
                           now: Optional[float] = None) -> Optional[Dict[str, object]]:
    """If failure count for (scope_key, action_name) is at/above threshold within
    the rolling window, return an `escalation` dict to attach to the response.
    Otherwise return None.

    The dict is what the caller mounts as `response["escalation"] = ...`.
    """
    state = get_failure_state(scope_key, action_name,
                              now=now, window_seconds=window_seconds)
    if state["failure_count"] < threshold:
        return None
    return {
        "recommended": True,
        "reason": "repeated_failure",
        "failure_count": state["failure_count"],
        "first_failure_at": state["first_failure_at"],
        "last_failure_at": state["last_failure_at"],
        "suggested_action": (
            f"Ask the user for guidance; do not auto-retry. "
            f"The last {state['failure_count']} attempts on {action_name!r} "
            f"for scope={scope_key or '(no scope)'} all returned {error_category!r}."
        ),
    }


def reset_all() -> None:
    """Clear all tracked failures. Tests + manual session reset only."""
    with _LOCK:
        _FAILURES.clear()


def _iso(epoch_seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_seconds))
