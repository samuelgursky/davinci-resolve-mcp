"""Regression tests for fusion_comp timeline targeting helpers."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import server


class FakeFusion:
    def __init__(self, comp):
        self._comp = comp

    def GetCurrentComp(self):
        return self._comp


class FakeResolve:
    def __init__(self, comp):
        self._fusion = FakeFusion(comp)

    def Fusion(self):
        return self._fusion


class FakeTimelineItem:
    def __init__(self, unique_id, comp_count=1):
        self._unique_id = unique_id
        self._comp_count = comp_count
        self.requested_comp_index = None

    def GetUniqueId(self):
        return self._unique_id

    def GetFusionCompCount(self):
        return self._comp_count

    def GetFusionCompByIndex(self, comp_index):
        self.requested_comp_index = comp_index
        return {"comp_index": comp_index}

    def GetFusionCompByName(self, comp_name):
        return {"comp_name": comp_name}


class FakeTimeline:
    def __init__(self, tracks):
        self._tracks = tracks

    def GetTrackCount(self, track_type):
        return len(self._tracks.get(track_type, {}))

    def GetItemListInTrack(self, track_type, track_index):
        return self._tracks.get(track_type, {}).get(track_index, [])


class FusionCompTargetingTests(unittest.TestCase):
    def test_active_comp_fallback_does_not_require_timeline(self):
        active_comp = object()

        with patch.object(server, "get_resolve", return_value=FakeResolve(active_comp)), patch.object(
            server,
            "_get_tl",
            side_effect=AssertionError("_get_tl should not be called without timeline scope"),
        ):
            comp, err = server._resolve_fusion_comp({})

        self.assertIs(comp, active_comp)
        self.assertIsNone(err)

    def test_bulk_set_inputs_requires_timeline_scope_per_op(self):
        with patch.object(
            server,
            "_resolve_fusion_comp",
            side_effect=AssertionError("_resolve_fusion_comp should not be called for unscoped bulk ops"),
        ):
            result = server._fusion_comp_bulk_set_inputs(
                {"ops": [{"tool_name": "Text1", "input_name": "StyledText", "value": "Hello"}]}
            )

        self.assertEqual(result["op_count"], 1)
        self.assertIn("timeline scope is required", result["results"][0]["error"])

    def test_find_timeline_item_by_id_scans_timeline_tracks(self):
        wanted = FakeTimelineItem("target")
        timeline = FakeTimeline({
            "video": {1: [FakeTimelineItem("video-1")]},
            "audio": {1: [wanted]},
        })

        self.assertIs(server._find_timeline_item_by_id(timeline, "target"), wanted)

    def test_comp_index_defaults_to_first_comp_and_validates_range(self):
        item = FakeTimelineItem("clip-1", comp_count=2)

        comp, err = server._get_fusion_comp_on_timeline_item(item, {})
        self.assertEqual(comp, {"comp_index": 1})
        self.assertIsNone(err)

        comp, err = server._get_fusion_comp_on_timeline_item(item, {"comp_index": 3})
        self.assertIsNone(comp)
        self.assertIn("item has 2 comp(s)", err["error"])


if __name__ == "__main__":
    unittest.main()
