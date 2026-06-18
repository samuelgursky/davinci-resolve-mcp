"""Tests for deep-QC P1 1b: required-param validation returns structured errors
instead of crashing with KeyError on omitted params."""
import unittest
from unittest import mock

import src.server as s


class TimelineParamValidationTest(unittest.TestCase):
    def test_set_current_missing_index_errors(self):
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), mock.Mock(), None)):
            out = s.timeline("set_current", {})
        self.assertIn("error", out)
        self.assertNotIn("success", out)  # did not crash / did not proceed

    def test_set_current_valid_index_proceeds(self):
        fake_proj = mock.Mock()
        fake_tl = mock.Mock()
        fake_proj.GetTimelineByIndex.return_value = fake_tl
        fake_proj.SetCurrentTimeline.return_value = True
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)):
            out = s.timeline("set_current", {"index": 2})
        self.assertTrue(out.get("success"))
        fake_proj.GetTimelineByIndex.assert_called_once_with(2)

    def test_add_track_missing_track_type_errors(self):
        fake_proj = mock.Mock()
        fake_proj.GetCurrentTimeline.return_value = mock.Mock()
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)):
            out = s.timeline("add_track", {})
        self.assertIn("error", out)


class ProjectManagerParamValidationTest(unittest.TestCase):
    def _fake_resolve(self):
        r = mock.Mock()
        r.GetProjectManager.return_value = mock.Mock()
        return r

    def test_create_missing_name_errors(self):
        with mock.patch.object(s, "get_resolve", return_value=self._fake_resolve()):
            out = s.project_manager("create", {})
        self.assertIn("error", out)

    def test_export_project_missing_path_errors(self):
        with mock.patch.object(s, "get_resolve", return_value=self._fake_resolve()):
            out = s.project_manager("export_project", {"name": "X"})
        self.assertIn("error", out)

    def test_archive_missing_both_errors(self):
        with mock.patch.object(s, "get_resolve", return_value=self._fake_resolve()):
            out = s.project_manager("archive", {})
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
