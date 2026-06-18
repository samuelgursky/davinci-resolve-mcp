"""Tests for CreateSubtitlesFromAudio settings normalization + readback.

Sibling of the issue #70 AutoSyncAudio fix: autoCaptionSettings is keyed by
resolve.SUBTITLE_* enum constants with resolve.AUTO_CAPTION_* enum values, so
human-readable strings must be resolved against the live handle and unknown keys
dropped (not forwarded, which silently fails the whole call).
"""
import unittest
from unittest import mock

import src.server as s


class FakeResolve:
    SUBTITLE_LANGUAGE = "__LANG__"
    SUBTITLE_CAPTION_PRESET = "__PRESET__"
    SUBTITLE_LINE_BREAK = "__LINEBREAK__"
    SUBTITLE_CHARS_PER_LINE = "__CPL__"
    SUBTITLE_GAP = "__GAP__"
    AUTO_CAPTION_KOREAN = "__KOREAN__"
    AUTO_CAPTION_ENGLISH = "__ENGLISH__"
    AUTO_CAPTION_NETFLIX = "__NETFLIX__"
    AUTO_CAPTION_SUBTITLE_DEFAULT = "__DEFAULT__"
    AUTO_CAPTION_LINE_SINGLE = "__SINGLE__"
    AUTO_CAPTION_LINE_DOUBLE = "__DOUBLE__"


class NormalizeTest(unittest.TestCase):
    def test_language_resolves_to_enum(self):
        out, ignored = s._normalize_auto_caption_settings({"language": "korean"}, FakeResolve())
        self.assertEqual(out["__LANG__"], "__KOREAN__")
        self.assertEqual(ignored, [])

    def test_preset_and_line_break_resolve(self):
        out, _ = s._normalize_auto_caption_settings(
            {"preset": "netflix", "line_break": "double"}, FakeResolve()
        )
        self.assertEqual(out["__PRESET__"], "__NETFLIX__")
        self.assertEqual(out["__LINEBREAK__"], "__DOUBLE__")

    def test_chars_per_line_clamped(self):
        hi, _ = s._normalize_auto_caption_settings({"chars_per_line": 999}, FakeResolve())
        lo, _ = s._normalize_auto_caption_settings({"chars_per_line": 0}, FakeResolve())
        self.assertEqual(hi["__CPL__"], 60)
        self.assertEqual(lo["__CPL__"], 1)

    def test_gap_clamped(self):
        out, _ = s._normalize_auto_caption_settings({"gap": 50}, FakeResolve())
        self.assertEqual(out["__GAP__"], 10)

    def test_unknown_language_value_is_reported_not_forwarded(self):
        out, ignored = s._normalize_auto_caption_settings({"language": "klingon"}, FakeResolve())
        self.assertEqual(out, {})
        self.assertEqual(ignored, ["language"])

    def test_unknown_key_is_dropped(self):
        out, ignored = s._normalize_auto_caption_settings(
            {"language": "english", "group_id": "x"}, FakeResolve()
        )
        self.assertEqual(out, {"__LANG__": "__ENGLISH__"})
        self.assertEqual(ignored, ["group_id"])

    def test_no_raw_strings_leak(self):
        out, _ = s._normalize_auto_caption_settings({"language": "korean"}, FakeResolve())
        self.assertNotIn("korean", out.values())
        self.assertNotIn("language", out)


class SafeCreateSubtitlesTest(unittest.TestCase):
    def test_dry_run_returns_resolved_settings_and_ignored(self):
        tl = mock.Mock()
        with mock.patch.object(s, "get_resolve", return_value=FakeResolve()):
            out = s._safe_create_subtitles(
                tl, {"settings": {"language": "korean", "bogus": 1}, "dry_run": True}
            )
        self.assertTrue(out["would_create_subtitles"])
        self.assertEqual(out["settings"]["__LANG__"], "__KOREAN__")
        self.assertEqual(out["ignored_settings"], ["bogus"])
        tl.CreateSubtitlesFromAudio.assert_not_called()

    def test_readback_verifies_track_added(self):
        tl = mock.Mock()
        counts = iter([0, 1])  # before=0, after=1

        tl.GetTrackCount.side_effect = lambda kind: {"subtitle": next(counts)}[kind]
        tl.CreateSubtitlesFromAudio.return_value = True
        with mock.patch.object(s, "get_resolve", return_value=FakeResolve()):
            out = s._safe_create_subtitles(
                tl, {"settings": {"language": "english"}, "dry_run": False}
            )
        # Resolved enum reached the API.
        called_with = tl.CreateSubtitlesFromAudio.call_args[0][0]
        self.assertEqual(called_with["__LANG__"], "__ENGLISH__")
        self.assertTrue(out["success"])
        self.assertTrue(out["verified"])
        self.assertEqual(out["subtitle_tracks_before"], 0)
        self.assertEqual(out["subtitle_tracks_after"], 1)

    def test_readback_catches_lying_boolean(self):
        # API says True but no subtitle track appears -> verified False.
        tl = mock.Mock()
        tl.GetTrackCount.return_value = 2  # unchanged before/after
        tl.CreateSubtitlesFromAudio.return_value = True
        with mock.patch.object(s, "get_resolve", return_value=FakeResolve()):
            out = s._safe_create_subtitles(tl, {"settings": {}, "dry_run": False})
        self.assertTrue(out["success"])
        self.assertFalse(out["verified"])


if __name__ == "__main__":
    unittest.main()
