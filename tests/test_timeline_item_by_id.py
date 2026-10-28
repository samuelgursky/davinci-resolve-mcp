"""Issue #323: timeline_item tools address an item by its stable id.

On 21.1 GetItemListInTrack returns transitions as items, so `item_index` N
is not the Nth clip and shifts whenever a transition is added or removed.
"""

from __future__ import annotations

import unittest
from unittest import mock

import src.server as server
from tests.test_timeline_pinning import _Project, _Timeline


class _Entry:
    def __init__(self, name, uid):
        self.name, self.uid = name, uid

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.uid

    def GetMarkers(self):
        return {0: {"name": f"{self.name} marker"}}


class _TrackedTimeline(_Timeline):
    """Clips C1..C3 with a transition between C1 and C2, as 21.1 lists them."""

    def __init__(self):
        super().__init__("Edit", "uid-tl")
        self.items = [_Entry("C1", "id-c1"), _Entry("Cross Dissolve", "id-x"),
                      _Entry("C2", "id-c2"), _Entry("C3", "id-c3")]

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0


class ItemByIdTest(unittest.TestCase):
    def setUp(self):
        self.tl = _TrackedTimeline()
        proj = _Project([self.tl], current=self.tl)
        patcher = mock.patch.object(server, "_check", return_value=(object(), proj, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_id_names_the_clip_whatever_its_index(self):
        result = server.timeline_item("get_name", {"timeline_item_id": "id-c3"})
        self.assertEqual(result["name"], "C3")
        # The index the caller would have guessed (2 = third clip) is the wrong row.
        self.assertEqual(server.timeline_item("get_name", {"item_index": 2})["name"], "C2")

    def test_an_unknown_id_is_not_found_rather_than_item_zero(self):
        result = server.timeline_item("get_name", {"timeline_item_id": "id-gone"})
        self.assertEqual(result["error"]["code"], "ITEM_NOT_FOUND")

    def test_an_index_passed_alongside_the_id_is_reported_unread(self):
        result = server.timeline_item("get_name", {"timeline_item_id": "id-c1", "item_index": 3})
        self.assertEqual(result["name"], "C1")
        self.assertEqual(result["ignored_params"], ["item_index"])

    def test_the_markers_tool_shares_the_handle(self):
        result = server.timeline_item_markers("get_all", {"timeline_item_id": "id-c2"})
        self.assertEqual(result["markers"], {0: {"name": "C2 marker"}})


if __name__ == "__main__":
    unittest.main()
