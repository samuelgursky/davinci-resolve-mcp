"""Per-user private state files (tokens, pidfiles) — never in a shared tempdir.

Two callers keep secrets on disk: the control-panel launcher (its bearer token
+ pid) and the networked MCP transport (its bearer token + URL). Both used to
land in world-readable locations (``~/Documents/...`` and ``tempfile.gettempdir()``).
This module gives them one home under the user's HOME with 0700/0600 modes.

``DAVINCI_RESOLVE_MCP_STATE_DIR`` overrides the directory (tests, sandboxes).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict


def private_state_dir() -> str:
    override = os.environ.get("DAVINCI_RESOLVE_MCP_STATE_DIR")
    path = override or os.path.join(os.path.expanduser("~"), ".davinci-resolve-mcp")
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        if sys.platform != "win32":
            os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _restrict_windows_acl(path: str) -> None:
    """Best-effort: strip inherited ACEs and grant only the current user."""
    user = os.environ.get("USERNAME")
    if not user:
        return
    try:
        subprocess.run(
            ["icacls", path, "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def write_private_file(path: str, text: str) -> None:
    """Write ``text`` to ``path`` readable only by the current user (0600).

    Replaces any existing file so a previously wider mode never survives.
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        os.remove(path)
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    if sys.platform == "win32":
        _restrict_windows_acl(path)
    else:
        os.chmod(path, 0o600)


def write_private_json(path: str, payload: Dict[str, Any]) -> None:
    write_private_file(path, json.dumps(payload, indent=2))
