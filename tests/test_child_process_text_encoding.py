"""Two ways a child process lies about a tool that works.

Both come from #153, which was reported as one bug and is two.

**Discovery.** A console script installed into the server's own virtualenv —
`pip install openai-whisper` writes `whisper` into `venv/Scripts` on Windows and
`venv/bin` elsewhere — is on PATH only when that environment has been
*activated*, and nothing activates it: the client launches `venv/python
server.py` directly. `shutil.which("whisper")` then returns None, and
`capabilities` reports the tool absent while it sits next to the interpreter
that is looking for it.

**Decoding.** `subprocess.run(..., text=True)` with no `encoding=` decodes the
child's bytes with the *locale* codec, which on a default Windows install is
cp1252 — a codec with no mapping for most of what a media tool prints. A clip
name in Japanese, a localized WMIC banner, or whisper's own language list is
then a `UnicodeDecodeError` raised inside a probe whose whole job is to answer
a yes/no question. That is why the guard below is a walk over `src/` rather than
a list of the call sites known to have been wrong: the next one to be added
would be wrong the same way, and it would present as "the tool isn't installed".
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Callables that spawn a child and hand back its output.
SPAWNERS = {"run", "Popen", "check_output", "safe_run"}


class InterpreterScriptDirOnPathTests(unittest.TestCase):
    def test_the_venv_this_server_runs_from_is_searched_for_tools(self) -> None:
        from src.utils import media_analysis  # noqa: F401 - import runs the PATH setup

        script_dir = os.path.dirname(os.path.abspath(sys.executable))
        self.assertIn(script_dir, os.environ.get("PATH", "").split(os.pathsep))

    def test_it_is_searched_first(self) -> None:
        """A tool installed deliberately alongside this server should win over an
        older copy sitting in /usr/local/bin."""
        from src.utils import media_analysis

        media_analysis._ensure_path_includes_standard_tool_dirs()
        parts = os.environ.get("PATH", "").split(os.pathsep)
        script_dir = os.path.dirname(os.path.abspath(sys.executable))
        for earlier in parts[: parts.index(script_dir)]:
            self.assertNotIn(earlier, ("/usr/local/bin", "/opt/homebrew/bin"))

    def test_the_setup_is_idempotent(self) -> None:
        """It runs at import and can be called again; a PATH that grows by one
        entry per call would eventually be the bug."""
        from src.utils import media_analysis

        media_analysis._ensure_path_includes_standard_tool_dirs()
        before = os.environ.get("PATH", "")
        media_analysis._ensure_path_includes_standard_tool_dirs()
        self.assertEqual(os.environ.get("PATH", ""), before)


class ChildOutputDecodingTests(unittest.TestCase):
    """Every text-mode child read under `src/` names its codec.

    Static, because the failure needs a non-UTF-8 locale to reproduce and none of
    this suite's machines have one. A missing `encoding=` is visible in the
    source; the exception it raises is only visible in Tokyo.
    """

    def _offenders(self):
        found = []
        for path in sorted((REPO_ROOT / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if ast.unparse(node.func).split(".")[-1] not in SPAWNERS:
                    continue
                keywords = {kw.arg for kw in node.keywords if kw.arg}
                if not ({"text", "universal_newlines"} & keywords):
                    continue
                if "encoding" not in keywords:
                    rel = path.relative_to(REPO_ROOT)
                    found.append(f"{rel}:{node.lineno}")
        return found

    def test_no_text_mode_child_read_relies_on_the_locale_codec(self) -> None:
        offenders = self._offenders()
        self.assertEqual(
            offenders, [],
            "text=True without encoding= decodes with the locale codec — cp1252 on a "
            "default Windows install — and raises UnicodeDecodeError on the first "
            "non-Latin-1 byte the child prints. Add encoding=\"utf-8\", "
            "errors=\"replace\":\n  " + "\n  ".join(offenders),
        )

    def test_the_walk_can_actually_see_an_offender(self) -> None:
        """A guard that silently matches nothing passes forever. This asserts the
        detector fires on the shape it is meant to catch."""
        module = ast.parse('subprocess.run(["x"], capture_output=True, text=True)')
        call = next(n for n in ast.walk(module) if isinstance(n, ast.Call))
        keywords = {kw.arg for kw in call.keywords if kw.arg}
        self.assertIn(ast.unparse(call.func).split(".")[-1], SPAWNERS)
        self.assertTrue({"text", "universal_newlines"} & keywords)
        self.assertNotIn("encoding", keywords)


if __name__ == "__main__":
    unittest.main()
