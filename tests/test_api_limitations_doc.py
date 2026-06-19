"""Drift guard: docs/reference/api-limitations.md tracks api_truth.

The Blackmagic-facing limitations report is generated from the ``submit``-tagged
entries in src/utils/api_truth.py by scripts/gen_api_limitations.py. This test
fails when the committed doc drifts from what the generator would produce now, so
adding or editing a ``submit`` entry forces a regenerate. It also asserts the doc
exists, is marked generated, and that every catalogued submit kind is valid.
"""
import importlib.util
import pathlib
import unittest

from src.utils.api_truth import API_TRUTH, submittable_limitations

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "reference" / "api-limitations.md"
GEN = ROOT / "scripts" / "gen_api_limitations.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_api_limitations", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ApiLimitationsDocTest(unittest.TestCase):
    def test_doc_matches_generator(self):
        gen = _load_generator()
        self.assertTrue(DOC.exists(), "api-limitations.md is missing — run the generator")
        self.assertEqual(
            DOC.read_text(),
            gen.render(),
            "api-limitations.md is stale; run: "
            "venv/bin/python scripts/gen_api_limitations.py",
        )

    def test_doc_is_marked_generated(self):
        self.assertIn("GENERATED FILE", DOC.read_text())

    def test_submit_values_are_valid(self):
        for e in API_TRUTH:
            kind = e.get("submit")
            self.assertIn(
                kind, (None, "missing", "bug"),
                f"entry {e.get('symbol')!r} has invalid submit={kind!r}",
            )

    def test_report_is_non_empty(self):
        groups = submittable_limitations()
        self.assertTrue(groups["missing"], "expected at least one missing-capability entry")
        self.assertTrue(groups["bug"], "expected at least one bug entry")


if __name__ == "__main__":
    unittest.main()
