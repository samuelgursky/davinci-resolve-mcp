"""UTF-8 encoding discipline guard (companion to PR #174's sweep).

`open()` / `Path.read_text()` / `Path.write_text()` without `encoding=` fall
back to the OS locale encoding. On Windows (cp1252 by default) that crashes
with UnicodeDecodeError the moment the target holds non-ASCII bytes — which
this repo's own sources do (`tests/test_import.py` failed parsing
`src/server.py` at byte 0x90 on a stock Windows Python). PR #174 fixed all
151 call sites in `tests/` and `scripts/`; this guard keeps new ones out.

Exemptions mirror the sweep: binary-mode opens (no text decoding happens) and
`Image.open(...)` (PIL's, takes no encoding argument).

PRs #175/#176 extended the sweep to `src/` and `install.py`. Those trees host
the exotic `.open()`s that take no encoding at all (`os.open`,
`webbrowser.open`, `aaf2.open`, `zipfile` members, Pillow), so there the
guard checks only bare `open()` and `Path.read_text/write_text` — the calls
where a missing encoding is unambiguously a locale-decoding bug.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# dir → whether attribute-.open(...) calls are also checked there
SCAN_DIRS = {"tests": True, "scripts": True, "src": False}
EXTRA_FILES = ("install.py",)
TEXT_METHODS = {"read_text", "write_text", "open"}


def _mode_is_binary(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and "b" in str(kw.value.value):
            return True
    args = call.args
    if len(args) >= 2 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str):
        return "b" in args[1].value
    return False


def _has_encoding(call: ast.Call) -> bool:
    return any(kw.arg == "encoding" or kw.arg is None for kw in call.keywords)


def _is_pil_image_open(func: ast.Attribute) -> bool:
    # Binary-container `.open` APIs, not text files: PIL's Image.open and
    # pyaaf2's aaf2.open (an AAF is a compound binary document).
    value = func.value
    return isinstance(value, ast.Name) and value.id in ("Image", "aaf2")


def unencoded_text_calls(path: Path, check_attr_open: bool):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            if not _mode_is_binary(node) and not _has_encoding(node):
                yield node.lineno, "open(...)"
        elif isinstance(func, ast.Attribute) and func.attr in TEXT_METHODS:
            if func.attr == "open" and (not check_attr_open or _is_pil_image_open(func)):
                continue
            if not _mode_is_binary(node) and not _has_encoding(node):
                yield node.lineno, f".{func.attr}(...)"


class Utf8Discipline(unittest.TestCase):
    def test_no_unencoded_text_file_calls(self):
        offenders = []
        targets = [(py, attr) for d, attr in SCAN_DIRS.items() for py in sorted((REPO / d).rglob("*.py"))]
        targets += [(REPO / f, False) for f in EXTRA_FILES]
        for py, check_attr_open in targets:
            for lineno, what in unencoded_text_calls(py, check_attr_open):
                offenders.append(f"{py.relative_to(REPO)}:{lineno} {what}")
        self.assertEqual(offenders, [],
                         "text-mode file calls without encoding=\"utf-8\" (crash on Windows cp1252):\n  "
                         + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
