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


class FakeClip211(FakeClip):
    """A 21.1 clip: the property is still a truncated preview, GetTranscription
    is the whole thing."""

    SEGMENTS = [
        {"start": "01:00:00:00", "end": "01:00:02:00", "text": "First part",
         "speaker": "Speaker 1",
         "words": [{"start": "01:00:00:00", "end": "01:00:01:00", "text": "First"}]},
        {"start": "01:00:02:00", "end": "01:00:04:00", "text": "second part",
         "speaker": "Speaker 1", "words": []},
    ]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.nested_arg = None

    def GetTranscription(self, useNestedClipTranscription=False):
        self.nested_arg = useNestedClipTranscription
        return {"language": "en", "segments": self.SEGMENTS}


class GetTranscription211Test(GetTranscriptionTest):
    def test_prefers_the_method_over_the_truncated_property(self):
        out = self._call(FakeClip211("This goes on and on\u2026"))
        self.assertEqual(out["source"], "get_transcription")
        self.assertEqual(out["text"], "First part second part")
        self.assertFalse(out["truncated"])
        self.assertEqual(out["language"], "en")
        self.assertEqual(len(out["segments"]), 2)

    def test_words_are_dropped_unless_asked_for(self):
        out = self._call(FakeClip211("preview\u2026"))
        self.assertNotIn("words", out["segments"][0])
        self.assertEqual(out["segments"][0]["speaker"], "Speaker 1")

    def test_include_words(self):
        clip = FakeClip211("preview\u2026")
        mp = mock.Mock()
        with mock.patch.object(s, "_get_mp", return_value=(None, None, mp, None)), \
             mock.patch.object(s, "_find_clip", return_value=clip):
            out = s.media_pool_item("get_transcription",
                                    {"clip_id": "x", "include_words": True})
        self.assertEqual(len(out["segments"][0]["words"]), 1)

    def test_falls_back_when_the_method_returns_nothing(self):
        clip = FakeClip211("A preview\u2026")
        clip.GetTranscription = lambda *a, **k: {"segments": []}
        out = self._call(clip)
        self.assertEqual(out["source"], "clip_property")
        self.assertEqual(out["text"], "A preview\u2026")
        self.assertTrue(out["truncated"])

    def test_falls_back_when_the_method_raises(self):
        clip = FakeClip211("A preview\u2026")
        def boom(*a, **k):
            raise RuntimeError("no transcript")
        clip.GetTranscription = boom
        out = self._call(clip)
        self.assertEqual(out["source"], "clip_property")
        self.assertTrue(out["truncated"])

    def test_210_clip_still_reports_the_property_route(self):
        out = self._call(FakeClip("A complete transcript."))
        self.assertEqual(out["source"], "clip_property")
        self.assertIsNone(out["segments"])


if __name__ == "__main__":
    unittest.main()
