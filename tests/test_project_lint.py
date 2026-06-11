"""Unit tests for the project lint health-check (Phase C1)."""
import unittest

from src.utils import project_lint as pl


def _codes(state):
    return {i.code for i in pl.lint_state(state)}


class ProjectLintTest(unittest.TestCase):
    def test_no_project_short_circuits(self):
        issues = pl.lint_state({"project": None})
        self.assertEqual([i.code for i in issues], ["no_project"])
        self.assertEqual(issues[0].severity, "error")

    def test_clean_project_has_no_errors(self):
        state = {
            "project": "Show",
            "current_timeline": "Edit",
            "timelines": [{"name": "Edit", "fps": 24, "item_count": 10}],
            "settings": {"colorScienceMode": "acescct"},
            "render": {"format": "mov"},
        }
        report = pl.lint_report(state)
        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"]["error"], 0)

    def test_no_current_timeline_warning(self):
        self.assertIn("no_current_timeline", _codes({"project": "S", "timelines": []}))

    def test_mixed_fps_info(self):
        state = {
            "project": "S", "current_timeline": "A",
            "timelines": [{"name": "A", "fps": 24, "item_count": 1},
                          {"name": "B", "fps": 30, "item_count": 1}],
        }
        self.assertIn("mixed_fps", _codes(state))

    def test_empty_timeline_warning(self):
        state = {"project": "S", "current_timeline": "A",
                 "timelines": [{"name": "A", "fps": 24, "item_count": 0}]}
        self.assertIn("empty_timeline", _codes(state))

    def test_audio_only_timeline_is_not_empty(self):
        state = {"project": "S", "current_timeline": "Music",
                 "timelines": [{"name": "Music", "fps": 24, "item_count": 0,
                                "video_item_count": 0, "audio_item_count": 1}]}
        self.assertNotIn("empty_timeline", _codes(state))

    def test_color_science_unset_info(self):
        state = {"project": "S", "current_timeline": "A",
                 "timelines": [{"name": "A", "fps": 24, "item_count": 1}],
                 "settings": {"colorScienceMode": "davinciYRGB"}}
        self.assertIn("color_science_unset", _codes(state))

    def test_offline_media_is_error(self):
        state = {"project": "S", "current_timeline": "A",
                 "timelines": [{"name": "A", "fps": 24, "item_count": 1}],
                 "offline_media_count": 3}
        report = pl.lint_report(state)
        self.assertFalse(report["ok"])
        self.assertIn("offline_media", _codes(state))

    def test_unanalyzed_clips_info(self):
        state = {"project": "S", "current_timeline": "A",
                 "timelines": [{"name": "A", "fps": 24, "item_count": 1}],
                 "unanalyzed_clip_count": 5}
        self.assertIn("unanalyzed_clips", _codes(state))

    def test_issues_sorted_error_first(self):
        state = {"project": "S", "timelines": [{"name": "A", "fps": 24, "item_count": 0}],
                 "offline_media_count": 1}
        issues = pl.lint_state(state)
        self.assertEqual(issues[0].severity, "error")


if __name__ == "__main__":
    unittest.main()
