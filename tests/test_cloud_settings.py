"""Tests for CloudProject {cloudSettings} normalization.

Sibling of the issue #70 AutoSyncAudio fix: the ProjectManager CloudProject
family keys its settings dict by resolve.CLOUD_SETTING_* constants with
resolve.CLOUD_SYNC_* sync-mode values, so human-readable strings must be
resolved against the live handle and unknown keys dropped.
"""
import unittest

import src.server as s


class FakeResolve:
    CLOUD_SETTING_PROJECT_NAME = "__NAME__"
    CLOUD_SETTING_PROJECT_MEDIA_PATH = "__MEDIA__"
    CLOUD_SETTING_IS_COLLAB = "__COLLAB__"
    CLOUD_SETTING_SYNC_MODE = "__SYNCMODE__"
    CLOUD_SETTING_IS_CAMERA_ACCESS = "__CAM__"
    CLOUD_SYNC_NONE = "__SYNC_NONE__"
    CLOUD_SYNC_PROXY_ONLY = "__SYNC_PROXY__"
    CLOUD_SYNC_PROXY_AND_ORIG = "__SYNC_BOTH__"


class CloudSettingsNormalizeTest(unittest.TestCase):
    def test_string_fields_keyed_to_enum_constants(self):
        out, ignored = s._normalize_cloud_settings(
            {"project_name": "My Project", "media_path": "/Vol/Media"}, FakeResolve()
        )
        self.assertEqual(out["__NAME__"], "My Project")
        self.assertEqual(out["__MEDIA__"], "/Vol/Media")
        self.assertEqual(ignored, [])

    def test_sync_mode_resolves_to_enum_value(self):
        out, _ = s._normalize_cloud_settings({"sync_mode": "proxy_only"}, FakeResolve())
        self.assertEqual(out["__SYNCMODE__"], "__SYNC_PROXY__")

    def test_sync_mode_aliases(self):
        out, _ = s._normalize_cloud_settings({"sync_mode": "proxy_and_original"}, FakeResolve())
        self.assertEqual(out["__SYNCMODE__"], "__SYNC_BOTH__")

    def test_bool_fields_coerced(self):
        out, _ = s._normalize_cloud_settings(
            {"is_collab": 1, "is_camera_access": 0}, FakeResolve()
        )
        self.assertIs(out["__COLLAB__"], True)
        self.assertIs(out["__CAM__"], False)

    def test_unknown_sync_mode_reported(self):
        out, ignored = s._normalize_cloud_settings({"sync_mode": "warpspeed"}, FakeResolve())
        self.assertEqual(out, {})
        self.assertEqual(ignored, ["sync_mode"])

    def test_unknown_key_dropped(self):
        out, ignored = s._normalize_cloud_settings(
            {"project_name": "X", "frobnicate": True}, FakeResolve()
        )
        self.assertEqual(out, {"__NAME__": "X"})
        self.assertEqual(ignored, ["frobnicate"])


if __name__ == "__main__":
    unittest.main()
