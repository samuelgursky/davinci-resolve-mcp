"""The coverage summaries must be derivable from the reference tables.

`docs/reference/api-coverage.md` states its method counts in four places: Key
Stats, the phase table Total, the "Untested Methods (N of M)" heading, and the
per-class reference tables themselves. Those drifted apart, and the cause was
structural rather than clerical — the Resolve 21 methods were never added to the
reference tables at all, so the denominator described a surface the server had
supported for four minor versions.

Numbers agreeing by hand-editing is what produced the drift. This derives every
figure from the tables and fails if a summary disagrees, so the tables stay the
single source and the summaries stay downstream of them.
"""
import pathlib
import re
import unittest

DOC = pathlib.Path(__file__).resolve().parent.parent / "docs/reference/api-coverage.md"

ROW = re.compile(r"^\| *(\d+) *\| *(`[^`]+`) *\| *(✅|⚠️|☁️|🔬) *\|")
CLASS_HEADING = re.compile(r"^### (\w+)$")


def _reference_section(text):
    return text[text.index("## Complete API Reference"):]


def _rows(text):
    """(class, number, signature, status) for every reference-table row."""
    found, cls = [], None
    for line in _reference_section(text).split("\n"):
        heading = CLASS_HEADING.match(line)
        if heading:
            cls = heading.group(1)
            continue
        row = ROW.match(line)
        if row:
            found.append((cls, int(row.group(1)), row.group(2), row.group(3)))
    return found


class ApiCoverageArithmeticTest(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")
        self.rows = _rows(self.text)

    def test_rows_are_found_at_all(self):
        # A format change that stops the parser matching would make every
        # assertion below vacuously true.
        self.assertGreater(len(self.rows), 300, "reference-table rows stopped parsing")

    def test_row_numbering_is_contiguous_within_each_class(self):
        expected, breaks = {}, []
        for cls, number, signature, _ in self.rows:
            want = expected.get(cls, 0) + 1
            if number != want:
                breaks.append(f"{cls}: expected {want}, found {number} at {signature}")
            expected[cls] = number
        self.assertEqual(breaks, [], "row numbering is not contiguous")

    def test_covered_total_matches_the_row_count(self):
        total = len(self.rows)
        self.assertIn(f"| API Methods Covered | **{total}/{total}** (100%) |", self.text)

    def test_live_tested_is_the_tested_marks_and_untested_is_the_rest(self):
        tested = sum(1 for *_, status in self.rows if status in ("✅", "⚠️"))
        untested = sum(1 for *_, status in self.rows if status in ("☁️", "🔬"))
        total = len(self.rows)
        self.assertEqual(tested + untested, total, "a row carries no recognised status")

        pct = f"{tested / total * 100:.1f}"
        self.assertIn(f"| Methods Live Tested | **{tested}/{total}** ({pct}%) |", self.text)
        self.assertIn(f"| Live Test Pass Rate | **{tested}/{tested}** (100%) |", self.text)
        self.assertIn(f"### Untested Methods ({untested} of {total})", self.text)

    def test_the_phase_table_total_equals_methods_live_tested(self):
        # The phase table counts methods, not assertions — that is what makes
        # its Total comparable to Methods Live Tested at all, and the confusion
        # between the two is what let the figures drift.
        tested = sum(1 for *_, status in self.rows if status in ("✅", "⚠️"))
        self.assertIn(f"| **Total** | **{tested}/{tested}** | **100%** |", self.text)

    def test_every_untested_row_is_listed_in_the_untested_section(self):
        section = self.text[self.text.index("### Untested Methods"):]
        section = section[:section.index("## Complete API Reference")]
        listed = section.count("| Yes |") + section.count("| No |")
        untested = sum(1 for *_, status in self.rows if status in ("☁️", "🔬"))
        self.assertEqual(listed, untested,
                         "the untested table must list every ☁️/🔬 row, not just a count")

    def test_resolve_21_methods_are_present_in_the_reference_tables(self):
        # The original defect: these were wrapped, released and live-tested
        # while absent from the tables the denominator counts.
        signatures = " ".join(sig for _, _, sig, _ in self.rows)
        for method in ("PerformAudioClassification", "ClearAudioClassification",
                       "AnalyzeForIntellisearch", "AnalyzeForSlate",
                       "RemoveMotionBlur", "GenerateSpeech",
                       "ResetIntellisearchAnalysis",
                       "DisableBackgroundTasksForCurrentResolveSession"):
            self.assertIn(method, signatures, f"{method} missing from the reference tables")


if __name__ == "__main__":
    unittest.main()
