"""Where the security audit log and the operation log may live, and how they open.

Both logs append a JSON line that carries caller-supplied params verbatim. If
an MCP caller could point either log at any file, it could append a line such
as ``{"note": "$(cmd)"}`` to a shell startup file, and the next shell would run
``cmd`` (GHSA-3rvw-8897-xq63). So a log path that comes through the MCP surface
or the preferences file must:

- sit under the server's own ``logs/`` directory or the system temp directory;
- end in ``.jsonl`` or ``.log``;
- not be a symlink (the append opens with ``O_NOFOLLOW``).

An operator can still send a log anywhere with an environment variable
(``RESOLVE_MCP_AUDIT_LOG_FILE`` / ``RESOLVE_MCP_OPERATION_LOG_FILE``), because
the environment is set by whoever launches the server, not by the caller.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_SUFFIXES = (".jsonl", ".log")


def server_log_dir() -> str:
    return os.path.realpath(str(_REPO_ROOT / "logs"))


def allowed_log_roots() -> List[str]:
    roots = [server_log_dir(), os.path.realpath(tempfile.gettempdir())]
    for extra in ("/tmp", "/private/tmp"):
        if os.path.isdir(extra):
            roots.append(os.path.realpath(extra))
    seen: List[str] = []
    for root in roots:
        if root not in seen:
            seen.append(root)
    return seen


def normalize(path: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))


def log_path_problem(path: object) -> Optional[str]:
    """Why ``path`` may not be used as a caller-configured log, or None if it may."""
    if not isinstance(path, str) or not path.strip():
        return "log path must be a non-empty string"
    raw = os.path.abspath(os.path.expanduser(path))
    if os.path.islink(raw):
        return "log path must not be a symlink"
    target = normalize(path)
    if not target.lower().endswith(LOG_SUFFIXES):
        return "log path must end in .jsonl or .log"
    if os.path.isdir(target):
        return "log path must be a file, not a directory"
    for root in allowed_log_roots():
        try:
            if os.path.commonpath([target, root]) == root and target != root:
                return None
        except ValueError:
            continue
    return (
        "log path must be under the server's logs directory "
        f"({server_log_dir()}) or the system temp directory"
    )


def append_line(path: str, line: str) -> None:
    """Append one line to a log without following a symlink at the final component.

    New files are created owner-read/write only.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(line)
