"""Tests for project_summary (live structural readout) and timeline get_transcript."""
import unittest
from unittest import mock

import src.server as s


class FakeClip:
    def __init__(self, name, ctype, uid):
        self.name = name
        self.ctype = ctype
        self.uid = uid

    def GetName(self):
        return self.name

    def GetClipProperty(self, key):
        return self.ctype if key == "Type" else ""

    def GetUniqueId(self):
        return self.uid


class FakeFolder:
    def __init__(self, clips, subs=None):
        self._clips = clips
        self._subs = subs or []

    def GetClipList(self):
        return list(self._clips)

    def GetSubFolderList(self):
        return list(self._subs)


class FakeMP:
    def __init__(self, root):
        self._root = root

    def GetRootFolder(self):
        return self._root


class FakeTimeline:
    def __init__(self, name):
        self.name = name

    def GetName(self):
        return self.name


class FakeProj:
    def __init__(self, mp, tl_count, cur_tl):
        self._mp = mp
        self._tlc = tl_count
        self._cur = cur_tl

    def GetName(self):
        return "proj"

    def GetMediaPool(self):
        return self._mp

    def GetTimelineCount(self):
        return self._tlc

    def GetCurrentTimeline(self):
        return self._cur


class ProjectSummaryTest(unittest.TestCase):
    def _proj(self):
        root = FakeFolder(
            [FakeClip("a", "Video", "1"), FakeClip("b", "Audio", "2")],
            subs=[FakeFolder([FakeClip("c", "Video", "3")])],
        )
        return FakeProj(FakeMP(root), 2, FakeTimeline("tl1"))

    def test_inventory(self):
        fake_r = mock.Mock()
        fake_r.GetCurrentPage.return_value = "edit"
        with mock.patch.object(s, "get_resolve", return_value=fake_r):
            out = s._project_summary(self._proj(), include_clips=True)
        self.assertEqual(out["project"], "proj")
        self.assertEqual(out["current_page"], "edit")
        self.assertEqual(out["timeline_count"], 2)
        self.assertEqual(out["current_timeline"], "tl1")
        self.assertEqual(out["media_pool"]["clip_count"], 3)
        self.assertEqual(out["media_pool"]["folder_count"], 2)
        self.assertEqual(out["media_pool"]["by_type"], {"Video": 2, "Audio": 1})
        self.assertEqual(len(out["clips"]), 3)

    def test_clip_limit_and_exclude(self):
        with mock.patch.object(s, "get_resolve", return_value=None):
            out = s._project_summary(self._proj(), include_clips=False)
        self.assertIsNone(out["clips"])
        self.assertIsNone(out["current_page"])

    def test_empty_media_pool(self):
        proj = FakeProj(FakeMP(FakeFolder([])), 0, None)
        with mock.patch.object(s, "get_resolve", return_value=None):
            out = s._project_summary(proj)
        self.assertEqual(out["media_pool"]["clip_count"], 0)
        self.assertEqual(out["media_pool"]["folder_count"], 1)  # just root
        self.assertIsNone(out["current_timeline"])


class SubItem:
    def __init__(self, text, start=0, end=0):
        self.text = text
        self.start = start
        self.end = end

    def GetName(self):
        return self.text

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end


class FakeSubTimeline:
    def __init__(self, subs):
        self._subs = subs

    def GetTrackCount(self, tt):
        return 1 if (tt == "subtitle" and self._subs) else 0

    def GetItemListInTrack(self, tt, i):
        return list(self._subs) if tt == "subtitle" else []


class TimelineTranscriptTest(unittest.TestCase):
    def test_reads_cues(self):
        tl = FakeSubTimeline([SubItem("Hello", 0, 24), SubItem("world", 24, 48)])
        out = s._timeline_transcript(tl, with_timecodes=True)
        self.assertEqual(out["text"], "Hello world")
        self.assertEqual(out["cue_count"], 2)
        self.assertTrue(out["has_subtitles"])
        self.assertEqual(out["cues"][0]["start"], 0)
        self.assertEqual(out["cues"][1]["end"], 48)

    def test_no_timecodes_by_default(self):
        tl = FakeSubTimeline([SubItem("a")])
        out = s._timeline_transcript(tl)
        self.assertNotIn("start", out["cues"][0])

    def test_empty(self):
        tl = FakeSubTimeline([])
        out = s._timeline_transcript(tl)
        self.assertEqual(out["text"], "")
        self.assertEqual(out["cue_count"], 0)
        self.assertFalse(out["has_subtitles"])


if __name__ == "__main__":
    unittest.main()
