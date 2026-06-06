"""Tests for clip transcription read-back and the _is_truncated helper."""
import unittest
from unittest import mock

import src.server as s


class IsTruncatedTest(unittest.TestCase):
    def test_ellipsis_unicode(self):
        self.assertTrue(s._is_truncated("hello world…"))

    def test_ellipsis_ascii(self):
        self.assertTrue(s._is_truncated("hello world..."))

    def test_trailing_space_then_ellipsis(self):
        self.assertTrue(s._is_truncated("hello…   "))

    def test_not_truncated(self):
        self.assertFalse(s._is_truncated("a complete sentence."))

    def test_non_string(self):
        self.assertFalse(s._is_truncated(None))
        self.assertFalse(s._is_truncated(42))


class FakeClip:
    def __init__(self, transcription="", status="Transcribed"):
        self._t = transcription
        self._s = status

    def GetClipProperty(self, key):
        if key == "Transcription":
            return self._t
        if key == "Transcription Status":
            return self._s
        return ""


class GetTranscriptionTest(unittest.TestCase):
    def _call(self, clip):
        mp = mock.Mock()
        with mock.patch.object(s, "_get_mp", return_value=(None, None, mp, None)), \
             mock.patch.object(s, "_find_clip", return_value=clip):
            return s.media_pool_item("get_transcription", {"clip_id": "x"})

    def test_full_text(self):
        out = self._call(FakeClip("A complete transcript."))
        self.assertEqual(out["text"], "A complete transcript.")
        self.assertFalse(out["truncated"])
        self.assertTrue(out["has_transcription"])
        self.assertEqual(out["status"], "Transcribed")

    def test_truncated(self):
        out = self._call(FakeClip("This goes on and on…"))
        self.assertTrue(out["truncated"])
        self.assertTrue(out["has_transcription"])

    def test_empty(self):
        out = self._call(FakeClip("", status=""))
        self.assertFalse(out["has_transcription"])
        self.assertFalse(out["truncated"])
        self.assertIsNone(out["status"])

    def test_non_string_property(self):
        # GetClipProperty may return a non-str; handler must not crash.
        clip = FakeClip()
        clip._t = None
        out = self._call(clip)
        self.assertEqual(out["text"], "")
        self.assertFalse(out["has_transcription"])


if __name__ == "__main__":
    unittest.main()
