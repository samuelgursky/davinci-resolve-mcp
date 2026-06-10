"""Instance-level actor identity for ledger and destructive-op records.

Design decision (2026-06-09): the supported concurrency target is a single
editor running multiple clients — a stdio server, a networked server, the
control panel, and the batch CLI may all drive one Resolve. Records therefore
identify the INSTANCE that performed an op, not a per-request client; finer
per-client fingerprints can layer on in a multi-user future without changing
this surface.

Each entry point declares itself once at startup via set_instance():

    stdio          — the default MCP server over stdio
    network-sse    — the networked server (SSE transport)
    network-http   — the networked server (streamable-http transport)
    control-panel  — the analysis dashboard process
    batch-cli      — the headless batch runner

actor_string() is the compact form persisted in DB columns: "<instance>:<pid>".
"""
from __future__ import annotations

import os
from typing import Any, Dict

_instance = "stdio"

KNOWN_INSTANCES = ("stdio", "network-sse", "network-http", "control-panel", "batch-cli")


def set_instance(kind: str) -> None:
    """Declare what kind of process this is. Unknown kinds are kept verbatim."""
    global _instance
    kind = str(kind or "").strip() or "stdio"
    _instance = kind


def get_instance() -> str:
    return _instance


def current_actor() -> Dict[str, Any]:
    return {"instance": _instance, "pid": os.getpid()}


def actor_string() -> str:
    return f"{_instance}:{os.getpid()}"
