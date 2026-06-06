"""Subprocess helpers that are safe to call while the MCP stdio server is live.

The server owns the JSON-RPC stdin/stdout while serving over stdio. A child
process that inherits stdin can race-read bytes off the protocol stream and
corrupt it; ``capture_output`` only redirects stdout/stderr. These wrappers
default ``stdin`` to ``DEVNULL`` so subprocess hygiene is centralized rather
than re-applied at every call site.
"""
import subprocess
from typing import Any


def safe_run(*args: Any, **kwargs: Any) -> "subprocess.CompletedProcess":
    """subprocess.run with stdin defaulted to DEVNULL (override by passing stdin).

    If ``input`` is given, stdin is left alone — subprocess forbids passing both.
    """
    if "input" not in kwargs:
        kwargs.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.run(*args, **kwargs)


def safe_popen(*args: Any, **kwargs: Any) -> "subprocess.Popen":
    """subprocess.Popen with stdin defaulted to DEVNULL (override by passing stdin)."""
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.Popen(*args, **kwargs)
