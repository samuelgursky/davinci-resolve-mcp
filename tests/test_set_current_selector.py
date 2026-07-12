"""set_current accepts a stable id/name selector, not only a 1-based index."""
import unittest
from unittest import mock

import src.server as s
from src.server import _find_timeline_by_id


class TimelineStub:
    def __init__(self, unique_id, name):
        self._id = unique_id
        self._name = name

    def GetUniqueId(self):
        return self._id

    def GetName(self):
        return self._name


class ProjectStub:
    def __init__(self, timelines):
        self._timelines = timelines
        self.set_to = None

    def GetTimelineCount(self):
        return len(self._timelines)

    def GetTimelineByIndex(self, index):
        return self._timelines[index - 1] if 1 <= index <= len(self._timelines) else None

    def SetCurrentTimeline(self, tl):
        self.set_to = tl
        return True


def _dispatch(proj, params):
    with mock.patch.object(s, "_check", return_value=(mock.Mock(), proj, None)):
        return s.timeline("set_current", params)


class FindTimelineByIdTest(unittest.TestCase):
    def setUp(self):
        self.proj = ProjectStub([TimelineStub("tl-a", "Act 1"), TimelineStub("tl-b", "Act 2")])

    def test_returns_timeline_and_index_for_matching_id(self):
        tl, index = _find_timeline_by_id(self.proj, "tl-b")
        self.assertEqual((tl.GetName(), index), ("Act 2", 2))

    def test_returns_none_for_unknown_id(self):
        self.assertEqual(_find_timeline_by_id(self.proj, "tl-missing"), (None, None))


class SetCurrentSelectorTest(unittest.TestCase):
    def setUp(self):
        self.proj = ProjectStub([TimelineStub("tl-a", "Act 1"), TimelineStub("tl-b", "Act 2")])

    def test_selects_by_id(self):
        out = _dispatch(self.proj, {"id": "tl-b"})
        self.assertTrue(out.get("success"))
        self.assertEqual(self.proj.set_to.GetName(), "Act 2")

    def test_selects_by_name(self):
        out = _dispatch(self.proj, {"name": "Act 1"})
        self.assertTrue(out.get("success"))
        self.assertEqual(self.proj.set_to.GetName(), "Act 1")

    def test_falls_back_to_name_when_id_misses(self):
        out = _dispatch(self.proj, {"id": "nope", "name": "Act 2"})
        self.assertTrue(out.get("success"))
        self.assertEqual(self.proj.set_to.GetName(), "Act 2")

    def test_errors_when_selector_matches_nothing(self):
        out = _dispatch(self.proj, {"id": "nope"})
        self.assertIn("error", out)
        self.assertIsNone(self.proj.set_to)

    def test_index_still_supported(self):
        out = _dispatch(self.proj, {"index": 1})
        self.assertTrue(out.get("success"))
        self.assertEqual(self.proj.set_to.GetName(), "Act 1")


if __name__ == "__main__":
    unittest.main()
