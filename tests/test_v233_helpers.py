"""Unit tests for v2.3.3 helpers — cloud settings, audio sync settings,
AppendToTimeline clipInfo builder. All tests use stubs in place of live
Resolve handles, so they run in CI without DaVinci Resolve installed.
"""

import unittest

from src.granular.common import (
    _build_append_clip_info_dict,
    _build_audio_sync_settings,
)
from src.utils.cloud_operations import _build_cloud_settings


class MediaPoolItemStub:
    def __init__(self, unique_id="clip-1", name="clip-1.mp4"):
        self.unique_id = unique_id
        self.name = name

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name


class FolderStub:
    def __init__(self, clips=None, sub_folders=None):
        self._clips = clips or []
        self._sub_folders = sub_folders or []

    def GetClipList(self):
        return self._clips

    def GetSubFolderList(self):
        return self._sub_folders


class ResolveCloudStub:
    """Stub of the Resolve object exposing only the CLOUD_SETTING_* / CLOUD_SYNC_* constants."""

    CLOUD_SETTING_PROJECT_NAME = "key:name"
    CLOUD_SETTING_PROJECT_MEDIA_PATH = "key:media_path"
    CLOUD_SETTING_IS_COLLAB = "key:collab"
    CLOUD_SETTING_SYNC_MODE = "key:sync_mode"
    CLOUD_SETTING_IS_CAMERA_ACCESS = "key:cam_access"

    CLOUD_SYNC_NONE = "sync:none"
    CLOUD_SYNC_PROXY_ONLY = "sync:proxy_only"
    CLOUD_SYNC_PROXY_AND_ORIG = "sync:proxy_and_orig"


class ResolveAudioSyncStub:
    """Stub of the Resolve object exposing only the AUDIO_SYNC_* constants."""

    AUDIO_SYNC_MODE = "key:mode"
    AUDIO_SYNC_CHANNEL_NUMBER = "key:channel"
    AUDIO_SYNC_RETAIN_EMBEDDED_AUDIO = "key:retain_audio"
    AUDIO_SYNC_RETAIN_VIDEO_METADATA = "key:retain_meta"

    AUDIO_SYNC_WAVEFORM = "mode:waveform"
    AUDIO_SYNC_TIMECODE = "mode:timecode"
    AUDIO_SYNC_CHANNEL_AUTOMATIC = -1
    AUDIO_SYNC_CHANNEL_MIX = -2


# ────────────────────────────────────────────────────────────────────────────
# Cloud settings builder
# ────────────────────────────────────────────────────────────────────────────


class CloudSettingsBuilderTest(unittest.TestCase):
    def setUp(self):
        self.r = ResolveCloudStub()

    def test_empty_input_returns_empty_dict(self):
        settings, err = _build_cloud_settings(self.r)
        self.assertIsNone(err)
        self.assertEqual(settings, {})

    def test_full_create_settings(self):
        settings, err = _build_cloud_settings(
            self.r,
            project_name="MyCloud",
            project_media_path="/Volumes/cloud",
            is_collab=True,
            sync_mode="proxy_and_orig",
            is_camera_access=False,
        )
        self.assertIsNone(err)
        self.assertEqual(settings, {
            "key:name": "MyCloud",
            "key:media_path": "/Volumes/cloud",
            "key:collab": True,
            "key:sync_mode": "sync:proxy_and_orig",
            "key:cam_access": False,
        })

    def test_sync_mode_aliases(self):
        for alias, expected in [
            ("none", "sync:none"),
            ("proxy_only", "sync:proxy_only"),
            ("proxy-only", "sync:proxy_only"),
            ("PROXY_AND_ORIG", "sync:proxy_and_orig"),
        ]:
            settings, err = _build_cloud_settings(self.r, sync_mode=alias)
            self.assertIsNone(err, msg=f"alias {alias} failed: {err}")
            self.assertEqual(settings["key:sync_mode"], expected)

    def test_unknown_sync_mode_returns_error(self):
        _, err = _build_cloud_settings(self.r, sync_mode="bidirectional")
        self.assertIsNotNone(err)
        self.assertIn("Unknown sync_mode 'bidirectional'", err["error"])

    def test_load_only_3_keys_via_omission(self):
        # LoadCloudProject only honours name, media_path, sync_mode — caller omits the others
        settings, err = _build_cloud_settings(
            self.r, project_name="N", project_media_path="/p", sync_mode="none",
        )
        self.assertIsNone(err)
        self.assertEqual(set(settings.keys()), {"key:name", "key:media_path", "key:sync_mode"})

    def test_is_collab_coerces_to_bool(self):
        settings, _ = _build_cloud_settings(self.r, is_collab=1)
        self.assertIs(settings["key:collab"], True)
        settings, _ = _build_cloud_settings(self.r, is_collab=0)
        self.assertIs(settings["key:collab"], False)


# ────────────────────────────────────────────────────────────────────────────
# Audio sync settings builder
# ────────────────────────────────────────────────────────────────────────────


class AudioSyncSettingsBuilderTest(unittest.TestCase):
    def setUp(self):
        self.r = ResolveAudioSyncStub()

    def test_empty_input_returns_empty(self):
        settings, err = _build_audio_sync_settings(self.r)
        self.assertIsNone(err)
        self.assertEqual(settings, {})

    def test_full_dict(self):
        settings, err = _build_audio_sync_settings(
            self.r, sync_mode="waveform", channel_number=2,
            retain_embedded_audio=True, retain_video_metadata=False,
        )
        self.assertIsNone(err)
        self.assertEqual(settings, {
            "key:mode": "mode:waveform",
            "key:channel": 2,
            "key:retain_audio": True,
            "key:retain_meta": False,
        })

    def test_sync_mode_case_insensitive(self):
        for alias in ["TIMECODE", "Timecode", "timecode"]:
            settings, err = _build_audio_sync_settings(self.r, sync_mode=alias)
            self.assertIsNone(err, msg=f"alias {alias} failed: {err}")
            self.assertEqual(settings["key:mode"], "mode:timecode")

    def test_unknown_sync_mode(self):
        _, err = _build_audio_sync_settings(self.r, sync_mode="zerocross")
        self.assertIsNotNone(err)
        self.assertIn("Unknown sync_mode 'zerocross'", err["error"])

    def test_channel_number_special_strings(self):
        for alias, expected in [("automatic", -1), ("auto", -1), ("MIX", -2), ("mix", -2)]:
            settings, err = _build_audio_sync_settings(self.r, channel_number=alias)
            self.assertIsNone(err, msg=f"alias {alias} failed: {err}")
            self.assertEqual(settings["key:channel"], expected)

    def test_channel_number_int(self):
        settings, err = _build_audio_sync_settings(self.r, channel_number=4)
        self.assertIsNone(err)
        self.assertEqual(settings["key:channel"], 4)

    def test_unknown_channel_string(self):
        _, err = _build_audio_sync_settings(self.r, channel_number="left")
        self.assertIsNotNone(err)
        self.assertIn("Unknown channel_number 'left'", err["error"])

    def test_invalid_channel_type(self):
        _, err = _build_audio_sync_settings(self.r, channel_number=1.5)
        self.assertIsNotNone(err)
        self.assertIn("channel_number must be int", err["error"])


# ────────────────────────────────────────────────────────────────────────────
# AppendToTimeline clipInfo builder (granular)
# ────────────────────────────────────────────────────────────────────────────


class GranularAppendClipInfoBuilderTest(unittest.TestCase):
    def setUp(self):
        self.clip = MediaPoolItemStub(unique_id="abc", name="abc.mp4")
        self.root = FolderStub(clips=[self.clip])

    def test_full_dict_camelcase(self):
        out, err = _build_append_clip_info_dict(
            self.root,
            {"clip_id": "abc", "startFrame": 10, "endFrame": 50,
             "recordFrame": 100, "trackIndex": 2, "mediaType": 1},
            0,
        )
        self.assertIsNone(err)
        self.assertEqual(out, {
            "mediaPoolItem": self.clip,
            "startFrame": 10,
            "endFrame": 50,
            "recordFrame": 100,
            "trackIndex": 2,
            "mediaType": 1,
        })

    def test_full_dict_snakecase(self):
        out, err = _build_append_clip_info_dict(
            self.root,
            {"media_pool_item_id": "abc", "start_frame": 0, "end_frame": 24,
             "record_frame": 0, "track_index": 1},
            1,
        )
        self.assertIsNone(err)
        self.assertEqual(out["startFrame"], 0)
        self.assertEqual(out["trackIndex"], 1)
        self.assertNotIn("mediaType", out)

    def test_missing_track_index(self):
        _, err = _build_append_clip_info_dict(
            self.root,
            {"clip_id": "abc", "start_frame": 0, "end_frame": 1, "record_frame": 0},
            0,
        )
        self.assertEqual(err, {"error": "clip_infos[0] requires track_index/trackIndex"})

    def test_missing_record_frame(self):
        _, err = _build_append_clip_info_dict(
            self.root,
            {"clip_id": "abc", "start_frame": 0, "end_frame": 1, "track_index": 1},
            0,
        )
        self.assertEqual(err, {"error": "clip_infos[0] requires record_frame/recordFrame"})

    def test_clip_not_found(self):
        _, err = _build_append_clip_info_dict(
            self.root,
            {"clip_id": "missing", "start_frame": 0, "end_frame": 1,
             "record_frame": 0, "track_index": 1},
            3,
        )
        self.assertEqual(err, {"error": "clip_infos[3]: media pool clip not found: missing"})

    def test_non_dict(self):
        _, err = _build_append_clip_info_dict(self.root, "string-not-dict", 0)
        self.assertEqual(err, {"error": "clip_infos[0] must be an object"})


if __name__ == "__main__":
    unittest.main()
