#!/usr/bin/env python3
"""PostToolUse check: catch generated-agent-rules drift the moment it happens.

scripts/agent-rules/generate.mjs is the single source for every per-IDE rule
file (.cursor/rules, .windsurf/rules, .clinerules, .roo/rules, .continue/rules,
.github/copilot-instructions.md, and the AGENTS.md domain-routing block).
tests/test_agent_rules_drift.py fails if any of those go stale relative to
their sources without a regeneration — but that is only caught at test time.
The sources are the four files generate.mjs actually reads (docs/SKILL.md,
docs/kernels/README.md, resolve-advanced/README.md) plus the DOMAINS manifest
inlined in generate.mjs itself; AGENTS.md is an output, so an edit there can
also leave it stale. This hook runs
the same `--check` the test does, right after an edit to one of the sources,
so drift surfaces immediately instead of at the next test run.

Informational only: it never blocks the edit. If node is missing, the
generator is missing, or the edited file isn't a generator source, it exits
quietly. Reads the PostToolUse payload on stdin, emits additionalContext on
stdout when there's something to say.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "agent-rules" / "generate.mjs"

# A write to any of these can leave the generated per-IDE files stale.
#
# The first four are what generate.mjs reads: docs/SKILL.md supplies the
# compound and granular tool counts, docs/kernels/README.md the kernel-action
# count, resolve-advanced/README.md the advanced tool count, and generate.mjs
# itself carries the DOMAINS routing manifest inline. AGENTS.md is an *output*
# (the domain-routing block is written into it), so an edit there is drift too.
# If generate.mjs ever grows a new input, add it here or this hook goes silent
# on exactly the edit it exists to catch.
SOURCE_PATHS = (
    REPO_ROOT / "docs" / "SKILL.md",
    REPO_ROOT / "docs" / "kernels" / "README.md",
    REPO_ROOT / "resolve-advanced" / "README.md",
    REPO_ROOT / "scripts" / "agent-rules" / "generate.mjs",
    REPO_ROOT / "AGENTS.md",
)
# Watched defensively rather than because generate.mjs reads them: these dirs
# hold the kernels and guides the generated files point at, and a `--check` run
# is cheap enough that a false watch costs far less than a missed one.
SOURCE_DIRS = (
    REPO_ROOT / "docs" / "kernels",
    REPO_ROOT / "docs" / "guides",
)


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


def is_generator_source(path: str) -> bool:
    if not path:
        return False
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    if resolved in SOURCE_PATHS:
        return True
    return any(
        resolved == d or d in resolved.parents for d in SOURCE_DIRS
    )


def main() -> None:
    path = edited_path()
    if not is_generator_source(path):
        say_nothing()

    node = shutil.which("node")
    if node is None or not GENERATOR.is_file():
        say_nothing()

    try:
        proc = subprocess.run(
            [node, str(GENERATOR), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        say_nothing()
        return

    if proc.returncode == 0:
        say_nothing()

    output = (proc.stdout + proc.stderr).strip()

    # generate.mjs exits 1 for two different reasons: it found drift, or it
    # threw before it could look. Only the first is fixed by regenerating —
    # telling the session to run the generator when the generator is the thing
    # that crashed sends it in a circle. The drift path always prints the "✗ N
    # agent-rule file(s) are stale" line; a throw never does.
    if "agent-rule file(s) are stale" in output:
        additional_context(
            "Generated agent-rule files are stale after this edit — "
            f"`node scripts/agent-rules/generate.mjs` needs to run.\n{output}"
        )

    additional_context(
        "`node scripts/agent-rules/generate.mjs --check` failed to run "
        f"(exit {proc.returncode}) — this is a broken generator, not drift, so "
        "regenerating will not fix it. Most often a canonical count moved out "
        "from under one of the patterns generate.mjs parses.\n"
        f"{output}"
    )


if __name__ == "__main__":
    main()
