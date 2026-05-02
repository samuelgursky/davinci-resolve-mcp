"""Unit tests for v2.3.2 helpers — overload builders and subtitle settings.

All tests use stubs in place of live Resolve handles, so they can run in CI
without DaVinci Resolve installed.
"""

import unittest

from src.granular.common import (
    _build_create_clip_info_dict,
    _build_subtitle_settings,
)
from src.server import (
    _build_create_clip_info_dict as compound_build_create_clip_info_dict,
)


class MediaPoolItemStub:
    def __init__(self, unique_id="clip-1", name="clip-1.mp4"):
        self.unique_id = unique_id
        self.name = name

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name


class FolderStub:
    """Stub of a media pool folder/root supporting recursive _find_clip lookup."""

    def __init__(self, clips=None, sub_folders=None):
        self._clips = clips or []
        self._sub_folders = sub_folders or []

    def GetClipList(self):
        return self._clips

    def GetSubFolderList(self):
        return self._sub_folders


class ResolveStub:
    """Stub of the Resolve object exposing only the AUTO_CAPTION_* constants."""

    SUBTITLE_LANGUAGE = "key:lang"
    SUBTITLE_CAPTION_PRESET = "key:preset"
    SUBTITLE_CHARS_PER_LINE = "key:chars"
    SUBTITLE_LINE_BREAK = "key:lb"
    SUBTITLE_GAP = "key:gap"

    AUTO_CAPTION_AUTO = "lang:auto"
    AUTO_CAPTION_KOREAN = "lang:korean"
    AUTO_CAPTION_ENGLISH = "lang:english"
    AUTO_CAPTION_MANDARIN_SIMPLIFIED = "lang:mand_simp"

    AUTO_CAPTION_SUBTITLE_DEFAULT = "preset:default"
    AUTO_CAPTION_TELETEXT = "preset:teletext"
    AUTO_CAPTION_NETFLIX = "preset:netflix"

    AUTO_CAPTION_LINE_SINGLE = "lb:single"
    AUTO_CAPTION_LINE_DOUBLE = "lb:double"


# ────────────────────────────────────────────────────────────────────────────
# CreateTimelineFromClips clipInfo builder (granular common.py)
# ────────────────────────────────────────────────────────────────────────────


class GranularCreateClipInfoBuilderTest(unittest.TestCase):
    def setUp(self):
        self.clip = MediaPoolItemStub(unique_id="abc", name="abc.mp4")
        self.root = FolderStub(clips=[self.clip])

    def test_full_dict_camelcase(self):
        out, err = _build_create_clip_info_dict(
            self.root,
            {"clip_id": "abc", "startFrame": 10, "endFrame": 50, "recordFrame": 100},
            0,
        )
        self.assertIsNone(err)
        self.assertEqual(out, {
            "mediaPoolItem": self.clip,
            "startFrame": 10,
            "endFrame": 50,
            "recordFrame": 100,
        })

    def test_full_dict_snakecase(self):
        out, err = _build_create_clip_info_dict(
            self.root,
            {"media_pool_item_id": "abc", "start_frame": 0, "end_frame": 24, "record_frame": 0},
            1,
        )
        self.assertIsNone(err)
        self.assertEqual(out["startFrame"], 0)
        self.assertEqual(out["endFrame"], 24)
        self.assertEqual(out["recordFrame"], 0)

    def test_does_not_pass_track_index_or_media_type(self):
        out, err = _build_create_clip_info_dict(
            self.root,
            {
                "clip_id": "abc",
                "startFrame": 0, "endFrame": 24, "recordFrame": 0,
                "trackIndex": 2, "mediaType": 1,
            },
            0,
        )
        self.assertIsNone(err)
        self.assertNotIn("trackIndex", out)
        self.assertNotIn("mediaType", out)
        self.assertEqual(set(out.keys()), {"mediaPoolItem", "startFrame", "endFrame", "recordFrame"})

    def test_missing_clip_id(self):
        _, err = _build_create_clip_info_dict(self.root, {"startFrame": 0, "endFrame": 1, "recordFrame": 0}, 0)
        self.assertEqual(err, {"error": "clip_infos[0] requires clip_id or media_pool_item_id"})

    def test_clip_not_found(self):
        _, err = _build_create_clip_info_dict(self.root, {"clip_id": "missing", "startFrame": 0, "endFrame": 1, "recordFrame": 0}, 3)
        self.assertEqual(err, {"error": "clip_infos[3]: media pool clip not found: missing"})

    def test_missing_record_frame(self):
        _, err = _build_create_clip_info_dict(self.root, {"clip_id": "abc", "startFrame": 0, "endFrame": 1}, 0)
        self.assertEqual(err, {"error": "clip_infos[0] requires record_frame/recordFrame"})

    def test_non_dict(self):
        _, err = _build_create_clip_info_dict(self.root, ["not", "a", "dict"], 0)
        self.assertEqual(err, {"error": "clip_infos[0] must be an object"})


# ────────────────────────────────────────────────────────────────────────────
# CreateTimelineFromClips clipInfo builder (compound src/server.py)
# ────────────────────────────────────────────────────────────────────────────


class CompoundCreateClipInfoBuilderTest(unittest.TestCase):
    """Mirrors the granular tests against the compound-server helper."""

    def setUp(self):
        self.clip = MediaPoolItemStub(unique_id="abc", name="abc.mp4")
        self.root = FolderStub(clips=[self.clip])

    def test_returns_only_four_keys(self):
        out, err = compound_build_create_clip_info_dict(
            self.root,
            {"clip_id": "abc", "start_frame": 0, "end_frame": 24, "record_frame": 0},
            0,
        )
        self.assertIsNone(err)
        self.assertEqual(set(out.keys()), {"mediaPoolItem", "startFrame", "endFrame", "recordFrame"})

    def test_missing_record_frame_uses_err_helper(self):
        _, err = compound_build_create_clip_info_dict(
            self.root, {"clip_id": "abc", "start_frame": 0, "end_frame": 1}, 2,
        )
        self.assertEqual(err, {"error": "clip_infos[2] requires record_frame/recordFrame (timeline record frame)"})


# ────────────────────────────────────────────────────────────────────────────
# CreateSubtitlesFromAudio settings builder
# ────────────────────────────────────────────────────────────────────────────


class SubtitleSettingsBuilderTest(unittest.TestCase):
    def setUp(self):
        self.r = ResolveStub()

    def test_empty_input_returns_empty_settings(self):
        settings, err = _build_subtitle_settings(self.r)
        self.assertIsNone(err)
        self.assertEqual(settings, {})

    def test_language_mapping_case_insensitive(self):
        settings, err = _build_subtitle_settings(self.r, language="Korean")
        self.assertIsNone(err)
        self.assertEqual(settings, {"key:lang": "lang:korean"})

    def test_language_mandarin_simplified_aliases(self):
        for alias in ["mandarin_simplified", "Mandarin-Simplified"]:
            settings, err = _build_subtitle_settings(self.r, language=alias)
            self.assertIsNone(err, msg=f"alias {alias} failed: {err}")
            self.assertEqual(settings["key:lang"], "lang:mand_simp")

    def test_unknown_language_returns_error(self):
        _, err = _build_subtitle_settings(self.r, language="klingon")
        self.assertIsNotNone(err)
        self.assertIn("Unknown language 'klingon'", err["error"])

    def test_full_dict_korean_netflix(self):
        settings, err = _build_subtitle_settings(
            self.r, language="korean", preset="netflix",
            chars_per_line=16, line_break="double", gap=2,
        )
        self.assertIsNone(err)
        self.assertEqual(settings, {
            "key:lang": "lang:korean",
            "key:preset": "preset:netflix",
            "key:chars": 16,
            "key:lb": "lb:double",
            "key:gap": 2,
        })

    def test_chars_per_line_out_of_range(self):
        for invalid in [0, 61, -1, "42"]:
            _, err = _build_subtitle_settings(self.r, chars_per_line=invalid)
            self.assertIsNotNone(err, msg=f"value {invalid!r} should fail")
            self.assertIn("chars_per_line", err["error"])

    def test_gap_out_of_range(self):
        for invalid in [-1, 11, "5"]:
            _, err = _build_subtitle_settings(self.r, gap=invalid)
            self.assertIsNotNone(err, msg=f"value {invalid!r} should fail")
            self.assertIn("gap", err["error"])

    def test_unknown_preset_returns_error(self):
        _, err = _build_subtitle_settings(self.r, preset="amazon")
        self.assertIsNotNone(err)
        self.assertIn("Unknown preset 'amazon'", err["error"])


if __name__ == "__main__":
    unittest.main()
