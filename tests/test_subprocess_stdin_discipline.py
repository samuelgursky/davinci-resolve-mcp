"""stdin discipline guard for every child process spawned under src/ (#272).

Over stdio the server's stdin IS the JSON-RPC stream. A child that inherits it
can read protocol bytes meant for the server, and ffmpeg actively does: it
polls stdin for keyboard commands, the "c" in "jsonrpc" opens its interactive
command prompt, and that prompt then blocks waiting for a newline while
consuming the frames it reads. Measured with ffmpeg 9.0.2: a partial frame on
an inherited pipe hung a silencedetect pass indefinitely, while
stdin=DEVNULL finished normally. `capture_output=True` redirects stdout and
stderr only, so it does not protect stdin.

api_truth already said "pass stdin=subprocess.DEVNULL on every subprocess that
can run while serving over stdio"; 29 call sites under src/ did not, including
the runner behind every ffmpeg/ffprobe analysis pass. This guard keeps new
ones out: every subprocess.run/Popen/call/check_call/check_output under src/
must pass `stdin=` (or `input=`, which supplies stdin itself) explicitly.

`src/utils/proc.py` is exempt — it is the safe_run/safe_popen wrapper that
setdefaults stdin=DEVNULL into the **kwargs it forwards.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPAWN_FUNCS = {"Popen", "run", "call", "check_call", "check_output"}
EXEMPT = {Path("src/utils/proc.py")}


def _subprocess_aliases(tree: ast.AST):
    """Names bound to the subprocess module, and bare names bound to its spawn
    functions (`from subprocess import run`)."""
    modules, funcs = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    modules.add(alias.asname or "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name in SPAWN_FUNCS:
                    funcs.add(alias.asname or alias.name)
    return modules, funcs


def unguarded_spawns(source: str, filename: str = "<src>"):
    tree = ast.parse(source, filename=filename)
    modules, funcs = _subprocess_aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_spawn = (
            isinstance(func, ast.Attribute)
            and func.attr in SPAWN_FUNCS
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
        ) or (isinstance(func, ast.Name) and func.id in funcs)
        if not is_spawn:
            continue
        if any(kw.arg in ("stdin", "input") for kw in node.keywords):
            continue
        yield node.lineno


class SubprocessStdinDisciplineTest(unittest.TestCase):
    def test_every_spawn_under_src_sets_stdin(self):
        offenders = []
        for path in sorted((REPO / "src").rglob("*.py")):
            rel = path.relative_to(REPO)
            if rel in EXEMPT:
                continue
            source = path.read_text(encoding="utf-8")
            offenders += [f"{rel.as_posix()}:{line}" for line in unguarded_spawns(source, str(rel))]
        self.assertEqual(
            offenders, [],
            "subprocess call(s) inherit the server's stdin — under stdio that is "
            "the JSON-RPC stream (#272). Pass stdin=subprocess.DEVNULL:\n  "
            + "\n  ".join(offenders),
        )

    def test_guard_detects_the_unguarded_shapes(self):
        # The guard is only worth having if it fires on each spelling.
        sample = (
            "import subprocess\n"
            "import subprocess as sp\n"
            "from subprocess import run as r\n"
            "subprocess.run(['ffmpeg'], capture_output=True)\n"   # 4: flagged
            "sp.Popen(['ffmpeg'], **kw)\n"                       # 5: flagged
            "r(['ffmpeg'])\n"                                    # 6: flagged
            "subprocess.run(['ffmpeg'], stdin=subprocess.DEVNULL)\n"
            "subprocess.run(['cat'], input='x')\n"
        )
        self.assertEqual(list(unguarded_spawns(sample)), [4, 5, 6])


if __name__ == "__main__":
    unittest.main()
