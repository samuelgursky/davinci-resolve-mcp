"""Unit tests for B1 — grade_evidence_base composite read.

See local/design/agentic-flow-improvements-gameplan.md §3 task B1.
"""
import re
import unittest

from src.server import _grade_evidence_line


class GradeEvidenceLineTest(unittest.TestCase):
    def test_full_line_matches_required_tokens(self):
        line = _grade_evidence_line(
            item_name="Hero_2A",
            version_label="2",
            num_nodes=4,
            has_lut=True,
            group_name="Scene_03_Day",
            coverage_summary={"clips_total": 12, "clips_analyzed": 10, "clips_reuse_blocked": 1, "clips_superseded_by_relink": 1},
            coverage_warnings_count=0,
        )
        # Contract: required tokens
        self.assertTrue(line.startswith("evidence base:"), line)
        self.assertIn("Hero_2A", line)
        self.assertIn("Version 2", line)
        self.assertIn("4 nodes", line)
        self.assertIn("LUT", line)
        self.assertIn("group=Scene_03_Day", line)
        self.assertIn("10 of 12 target shots", line)
        # 2 = 1 reuse_blocked + 1 superseded
        self.assertIn("2 superseded_by_relink", line)

    def test_default_graph_phrasing_when_nothing_set(self):
        line = _grade_evidence_line(
            item_name=None,
            version_label=None,
            num_nodes=None,
            has_lut=False,
            group_name=None,
            coverage_summary=None,
            coverage_warnings_count=0,
        )
        self.assertIn("current item", line)
        self.assertIn("default graph", line)
        # No coverage clause when no summary
        self.assertNotIn("target shots", line)

    def test_regex_extracts_required_fields(self):
        """Downstream parsers may regex out version + node count. Lock that contract."""
        line = _grade_evidence_line(
            item_name="X", version_label="3", num_nodes=2, has_lut=False, group_name=None,
            coverage_summary={"clips_total": 5, "clips_analyzed": 5},
            coverage_warnings_count=0,
        )
        m = re.search(r"Version (\d+).*?(\d+) nodes.*?(\d+) of (\d+) target shots", line)
        self.assertIsNotNone(m, line)
        self.assertEqual(m.group(1), "3")
        self.assertEqual(m.group(2), "2")
        self.assertEqual(m.group(3), "5")
        self.assertEqual(m.group(4), "5")

    def test_warnings_appended_when_nonzero(self):
        line = _grade_evidence_line(
            item_name="X", version_label="1", num_nodes=1, has_lut=False, group_name=None,
            coverage_summary={"clips_total": 1, "clips_analyzed": 1},
            coverage_warnings_count=3,
        )
        self.assertIn("3 warnings", line)


class GradeEvidenceBaseActionWiringTest(unittest.TestCase):
    def test_action_registered_in_kernel_list(self):
        from src.server import _COLOR_GRADE_KERNEL_ACTIONS
        self.assertIn("grade_evidence_base", _COLOR_GRADE_KERNEL_ACTIONS)

    def test_docstring_advertises_action(self):
        from src.server import timeline_item_color
        self.assertIn("grade_evidence_base", timeline_item_color.__doc__)


class GradeEvidenceBaseVersionExtractionTest(unittest.TestCase):
    """F2 — composite must extract the version label whichever key the
    Resolve API uses ('versionName' camelCase observed live; PascalCase
    'VersionName' assumed by earlier code).
    """

    def _build(self, current_version):
        from src.server import _grade_evidence_base

        class _Item:
            def GetColorGroup(self):
                return None

            def GetName(self):
                return "Hero"

        original_snap = None
        original_probe = None
        try:
            import src.server as compound

            original_snap = compound._grade_version_snapshot
            original_probe = compound._probe_color_node_graph
            compound._grade_version_snapshot = lambda item, p: {"current": current_version}
            compound._probe_color_node_graph = lambda proj, item, p: {
                "available": True, "num_nodes": 1, "nodes": []
            }
            return _grade_evidence_base(object(), _Item(), {"include_coverage": False})
        finally:
            if original_snap is not None:
                compound._grade_version_snapshot = original_snap
            if original_probe is not None:
                compound._probe_color_node_graph = original_probe

    def test_camelcase_versionname_extracted(self):
        out = self._build({"versionName": "Version 3", "versionType": 0})
        self.assertIn("Version 3", out["evidence_base"])

    def test_pascalcase_versionname_extracted(self):
        out = self._build({"VersionName": "2", "versionType": 0})
        self.assertIn("Version 2", out["evidence_base"])

    def test_version_prefix_not_duplicated(self):
        # Input already contains "Version 1"; output must say "Version 1" once.
        out = self._build({"versionName": "Version 1"})
        line = out["evidence_base"]
        self.assertEqual(line.count("Version 1"), 1, line)
        self.assertNotIn("Version Version", line)


if __name__ == "__main__":
    unittest.main()
