"""Shared host-protocol helpers for repository agent hooks."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


def host() -> str:
    return os.environ.get("DAVINCI_AGENT_HOST", "claude").strip().lower()


def load_event() -> Dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(payload: Dict[str, Any]) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def pretool_decision(decision: str, reason: str) -> None:
    if decision == "ask" and host() == "codex":
        # Codex PreToolUse currently supports allow/deny but not ask. The MCP
        # actions covered by this branch issue their own confirmation tokens,
        # so preserve that server gate and surface the warning as context.
        _write(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": reason,
                }
            }
        )
    else:
        _write(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": reason,
                }
            }
        )
    raise SystemExit(0)


def posttool_context(message: str) -> None:
    _write(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": message,
            }
        }
    )
    raise SystemExit(0)


def _candidate_strings(event: Dict[str, Any]) -> Iterable[str]:
    tool_input = event.get("tool_input") or {}
    tool_response = event.get("tool_response") or {}
    if isinstance(tool_input, dict):
        for key in ("file_path", "path"):
            value = tool_input.get(key)
            if isinstance(value, str):
                yield value
        command = tool_input.get("command")
        if isinstance(command, str):
            for match in re.finditer(
                r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", command, re.MULTILINE
            ):
                yield match.group(1).strip()
            for match in re.finditer(r"^\+\+\+ b/(.+)$", command, re.MULTILINE):
                yield match.group(1).strip()
    if isinstance(tool_response, dict):
        for key in ("filePath", "file_path", "path"):
            value = tool_response.get(key)
            if isinstance(value, str):
                yield value


def edited_paths(event: Dict[str, Any]) -> List[str]:
    base = Path(str(event.get("cwd") or os.getcwd()))
    paths: List[str] = []
    for raw in _candidate_strings(event):
        candidate = Path(os.path.expandvars(os.path.expanduser(raw)))
        if not candidate.is_absolute():
            candidate = base / candidate
        try:
            resolved = str(candidate.resolve())
        except OSError:
            continue
        if resolved not in paths:
            paths.append(resolved)
    return paths
