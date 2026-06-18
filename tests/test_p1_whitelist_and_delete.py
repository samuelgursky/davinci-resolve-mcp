"""Tests for deep-QC P1: settings/options whitelist + DeleteProject routing."""
import unittest
from unittest import mock

import src.server as s


class FilterToKeysTest(unittest.TestCase):
    def test_drops_unknown_keys_and_reports(self):
        filtered, ignored = s._filter_to_keys(
            {"timelineName": "x", "bogus": 1, "importSourceClips": True},
            s._IMPORT_TIMELINE_OPTION_KEYS,
        )
        self.assertEqual(filtered, {"timelineName": "x", "importSourceClips": True})
        self.assertEqual(ignored, ["bogus"])

    def test_non_dict_returns_empty(self):
        self.assertEqual(s._filter_to_keys(None, {"a"}), ({}, []))
        self.assertEqual(s._filter_to_keys("x", {"a"}), ({}, []))

    def test_voice_isolation_keys(self):
        filtered, ignored = s._filter_to_keys(
            {"isEnabled": True, "amount": 50, "typo": 9}, s._VOICE_ISOLATION_STATE_KEYS
        )
        self.assertEqual(filtered, {"isEnabled": True, "amount": 50})
        self.assertEqual(ignored, ["typo"])


class ImportTimelineWhitelistTest(unittest.TestCase):
    def test_import_timeline_filters_options(self):
        captured = {}
        fake_tl = mock.Mock()
        fake_tl.GetName.return_value = "T"
        fake_mp = mock.Mock()
        fake_mp.ImportTimelineFromFile.side_effect = lambda path, opts: captured.update(opts=opts) or fake_tl
        fake_proj = mock.Mock()
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)), \
             mock.patch.object(s, "_get_mp", return_value=(mock.Mock(), fake_proj, fake_mp, None)):
            fake_mp.GetRootFolder.return_value = mock.Mock()
            out = s.media_pool("import_timeline", {"path": "/tmp/x.aaf",
                                                   "options": {"timelineName": "Cut", "junk": 1}})
        self.assertEqual(captured["opts"], {"timelineName": "Cut"})  # junk dropped
        self.assertEqual(out.get("ignored_options"), ["junk"])


class RenderSettingsWhitelistTest(unittest.TestCase):
    def test_set_settings_filters_unknown_keys(self):
        captured = {}
        fake_proj = mock.Mock()
        fake_proj.SetRenderSettings.side_effect = lambda s_: captured.update(s=s_) or True
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)):
            out = s.render("set_settings", {"settings": {"TargetDir": "/tmp", "Nonsense": 9}})
        self.assertEqual(captured["s"], {"TargetDir": "/tmp"})
        self.assertEqual(out.get("ignored_settings"), ["Nonsense"])

    def test_set_settings_requires_dict(self):
        fake_proj = mock.Mock()
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)):
            out = s.render("set_settings", {})
        self.assertIn("error", out)


class DeleteProjectRoutingTest(unittest.TestCase):
    def test_raw_delete_routes_through_safe_helper(self):
        fake_pm = mock.Mock()
        with mock.patch.object(s, "_check", return_value=(fake_pm, mock.Mock(), None)), \
             mock.patch("src.utils.project_cleanup.delete_project_safely",
                        return_value={"success": True, "attempts": 1, "leftover": None, "detail": ""}) as safe:
            out = s.project_manager("delete", {"name": "Disposable"})
        safe.assert_called_once()
        self.assertTrue(out["success"])
        self.assertIn("delete_detail", out)

    def test_raw_delete_requires_name(self):
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), mock.Mock(), None)):
            out = s.project_manager("delete", {})
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
