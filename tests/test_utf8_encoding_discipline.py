"""UTF-8 encoding discipline guard (companion to PR #174's sweep).

`open()` / `Path.read_text()` / `Path.write_text()` without `encoding=` fall
back to the OS locale encoding. On Windows (cp1252 by default) that crashes
with UnicodeDecodeError the moment the target holds non-ASCII bytes — which
this repo's own sources do (`tests/test_import.py` failed parsing
`src/server.py` at byte 0x90 on a stock Windows Python). PR #174 fixed all
151 call sites in `tests/` and `scripts/`; this guard keeps new ones out.

Exemptions mirror the sweep: binary-mode opens (no text decoding happens) and
`Image.open(...)` (PIL's, takes no encoding argument).
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("tests", "scripts")
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
    value = func.value
    return isinstance(value, ast.Name) and value.id == "Image"


def unencoded_text_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            if not _mode_is_binary(node) and not _has_encoding(node):
                yield node.lineno, "open(...)"
        elif isinstance(func, ast.Attribute) and func.attr in TEXT_METHODS:
            if func.attr == "open" and _is_pil_image_open(func):
                continue
            if not _mode_is_binary(node) and not _has_encoding(node):
                yield node.lineno, f".{func.attr}(...)"


class Utf8Discipline(unittest.TestCase):
    def test_no_unencoded_text_file_calls(self):
        offenders = []
        for d in SCAN_DIRS:
            for py in sorted((REPO / d).rglob("*.py")):
                for lineno, what in unencoded_text_calls(py):
                    offenders.append(f"{py.relative_to(REPO)}:{lineno} {what}")
        self.assertEqual(offenders, [],
                         "text-mode file calls without encoding=\"utf-8\" (crash on Windows cp1252):\n  "
                         + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
