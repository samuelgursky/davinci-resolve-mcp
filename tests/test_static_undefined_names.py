"""Static guard: no undefined names anywhere under src/.

An undefined name inside a guard or try/except doesn't crash — it silently
falls back to a default. Three shipped bugs were this class: the
confirm-token gate calling a misspelled preference reader (v2.37.0), the
update-channel resource reporting "stable" unconditionally, and the
auto-run idle-timeout preference being ignored (both fixed after a
pyflakes audit). This test keeps the class extinct.

Skips when pyflakes is not installed (it is a dev dependency, not a
runtime one): `pip install pyflakes`.
"""
from __future__ import annotations

import io
import pathlib
import unittest

try:
    from pyflakes.api import checkPath
    from pyflakes.reporter import Reporter
    HAVE_PYFLAKES = True
except ImportError:
    HAVE_PYFLAKES = False

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"


@unittest.skipUnless(HAVE_PYFLAKES, "pyflakes not installed")
class UndefinedNamesTest(unittest.TestCase):
    def test_no_undefined_names_in_src(self):
        out = io.StringIO()
        reporter = Reporter(out, out)
        for path in sorted(SRC.rglob("*.py")):
            checkPath(str(path), reporter)
        undefined = [
            line
            for line in out.getvalue().splitlines()
            if "undefined name" in line and "unable to detect undefined names" not in line
        ]
        self.assertEqual(undefined, [], "undefined names found:\n" + "\n".join(undefined))


if __name__ == "__main__":
    unittest.main()
