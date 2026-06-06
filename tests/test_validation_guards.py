"""Tests for input-validation guards on project/clip/timeline actions.

- export_frame_as_still: reject empty path / nonexistent target directory.
- set_mark_in_out (clip + timeline): reject mark_in > mark_out.
"""
import unittest
from unittest import mock

import src.server as s


class FakeProj:
    def __init__(self):
        self.exported = None

    def ExportCurrentFrameAsStill(self, path):
        self.exported = path
        return True


class FakeClip:
    def __init__(self):
        self.mark = None

    def SetMarkInOut(self, a, b, t):
        self.mark = (a, b, t)
        return True


class FakeTL:
    def __init__(self):
        self.mark = None

    def SetMarkInOut(self, a, b, t):
        self.mark = (a, b, t)
        return True


class ExportStillGuardTest(unittest.TestCase):
    def _call(self, params):
        proj = FakeProj()
        with mock.patch.object(s, "_check", return_value=(None, proj, None)):
            return s.project_settings("export_frame_as_still", params), proj

    def test_empty_path_rejected(self):
        out, proj = self._call({"path": ""})
        self.assertIn("error", out)
        self.assertIsNone(proj.exported)

    def test_missing_path_rejected(self):
        out, _ = self._call({})
        self.assertIn("error", out)

    def test_nonexistent_dir_rejected(self):
        out, proj = self._call({"path": "/no/such/dir/frame.png"})
        self.assertIn("error", out)
        self.assertIsNone(proj.exported)

    def test_valid_path_exports(self):
        out, proj = self._call({"path": "/tmp/frame.png"})
        self.assertTrue(out.get("success"))
        self.assertEqual(proj.exported, "/tmp/frame.png")


class ClipMarkGuardTest(unittest.TestCase):
    def _call(self, params):
        mp = mock.Mock()
        clip = FakeClip()
        with mock.patch.object(s, "_get_mp", return_value=(None, None, mp, None)), \
             mock.patch.object(s, "_find_clip", return_value=clip):
            return s.media_pool_item("set_mark_in_out", params), clip

    def test_inverted_rejected(self):
        out, clip = self._call({"clip_id": "x", "mark_in": 100, "mark_out": 50})
        self.assertIn("error", out)
        self.assertIsNone(clip.mark)

    def test_valid_sets_mark(self):
        out, clip = self._call({"clip_id": "x", "mark_in": 10, "mark_out": 50})
        self.assertTrue(out.get("success"))
        self.assertEqual(clip.mark, (10, 50, "all"))

    def test_equal_allowed(self):
        out, clip = self._call({"clip_id": "x", "mark_in": 25, "mark_out": 25})
        self.assertTrue(out.get("success"))


class TimelineMarkGuardTest(unittest.TestCase):
    def _call(self, params):
        tl = FakeTL()
        proj = mock.Mock()
        proj.GetCurrentTimeline.return_value = tl
        with mock.patch.object(s, "_check", return_value=(None, proj, None)):
            return s.timeline("set_mark_in_out", params), tl

    def test_inverted_rejected(self):
        out, tl = self._call({"mark_in": 100, "mark_out": 50})
        self.assertIn("error", out)
        self.assertIsNone(tl.mark)

    def test_valid_sets_mark(self):
        out, tl = self._call({"mark_in": 10, "mark_out": 50})
        self.assertTrue(out.get("success"))
        self.assertEqual(tl.mark, (10, 50, "all"))


if __name__ == "__main__":
    unittest.main()
