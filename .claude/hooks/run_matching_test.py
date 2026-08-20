#!/usr/bin/env python3
"""PostToolUse check: run the one test file an edited module maps to.

tests/ follows a src/<module>.py -> tests/test_<module>.py naming convention
for 72 of the 126 modules under src/ — densely in src/utils/, not at all for
src/server.py, src/granular/common.py, or src/control_panel.py, which is where
most edits land. Running the full suite after every edit is too slow for
inline feedback; this hook runs just the matching test file, so a broken change
surfaces before the session moves on. It is a fast partial net, not coverage:
silence here means "no matching test file", not "this edit is fine".

The lookup is by stem, so src/api/foo.py and src/foo.py both resolve to
tests/test_foo.py. Only __init__.py collides today, but a future same-named
module in two packages would run the wrong test file and report it as this
edit's result.

Informational only: it never blocks the edit, and it skips silently when
there is no matching test file or the edited file isn't under src/. Reads the
PostToolUse payload on stdin, emits additionalContext on stdout only when the
matching test fails.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
TESTS_DIR = REPO_ROOT / "tests"


def say_nothing() -> None:
    sys.exit(0)


def additional_context(message: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": message,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    sys.exit(0)


def edited_path() -> str:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return ""
    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}
    return (
        tool_input.get("file_path")
        or tool_response.get("filePath")
        or ""
    )


def matching_test_file(path: str) -> Path | None:
    if not path:
        return None
    try:
        resolved = Path(path).resolve()
    except OSError:
        return None
    if resolved.suffix != ".py" or SRC_DIR not in resolved.parents:
        return None
    test_file = TESTS_DIR / f"test_{resolved.stem}.py"
    return test_file if test_file.is_file() else None


def venv_python() -> str | None:
    """The project's own venv interpreter (install.py creates it at venv/),
    so this runs against the environment that actually has pytest and the
    project's dependencies installed, not whatever `python3` is on PATH."""
    for candidate in (
        REPO_ROOT / "venv" / "bin" / "python",
        REPO_ROOT / "venv" / "Scripts" / "python.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("python3") or shutil.which("python")


def has_pytest(python: str) -> bool:
    try:
        proc = subprocess.run(
            [python, "-c", "import pytest"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def main() -> None:
    test_file = matching_test_file(edited_path())
    if test_file is None:
        say_nothing()

    python = venv_python()
    if python is None or not has_pytest(python):
        say_nothing()

    try:
        proc = subprocess.run(
            [python, "-m", "pytest", str(test_file), "-q"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        say_nothing()
        return

    if proc.returncode == 0:
        say_nothing()

    output = (proc.stdout + proc.stderr).strip()
    additional_context(
        f"{test_file.relative_to(REPO_ROOT)} failed after this edit:\n{output}"
    )


if __name__ == "__main__":
    main()
