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


class FakeFusionInput:
    """Minimal stand-in for a Fusion Input object.

    `inp[time] = value` records a keyframe only conceptually; in real Fusion it
    sets a STATIC value unless a spline modifier is attached first.
    """

    def __init__(self, connected_output=None, keyframe_values=None):
        self._connected_output = connected_output
        self.assignments = {}
        # frame_position -> value, modelling existing keyframes on the input.
        self.keyframe_values = dict(keyframe_values or {})

    def __bool__(self):
        return True

    def GetConnectedOutput(self):
        return self._connected_output

    def __setitem__(self, time, value):
        self.assignments[time] = value

    def GetKeyFrames(self):
        # Mirror Fusion: {1-based index: frame_position}, sorted by frame.
        frames = sorted(self.keyframe_values)
        return {i + 1: frame for i, frame in enumerate(frames)} or None


class FakeFusionTool:
    def __init__(self, inputs):
        self._inputs = inputs
        self.modifiers_added = []

    def __getitem__(self, name):
        return self._inputs.get(name)

    def GetInput(self, name, frame):
        inp = self._inputs.get(name)
        return inp.keyframe_values.get(frame) if inp is not None else None

    def AddModifier(self, input_name, modifier_type):
        self.modifiers_added.append((input_name, modifier_type))
        # Mirror Fusion: once a modifier is attached the input is now connected.
        inp = self._inputs.get(input_name)
        if inp is not None:
            inp._connected_output = object()
        return True


class FakeFusionComp:
    def __init__(self, tools):
        self._tools = tools
        self.lock_count = 0
        self.unlock_count = 0

    def FindTool(self, name):
        return self._tools.get(name)

    def Lock(self):
        self.lock_count += 1

    def Unlock(self):
        self.unlock_count += 1


class FusionAddKeyframeTests(unittest.TestCase):
    def _run(self, comp, params):
        with patch.object(server, "_resolve_fusion_comp", return_value=(comp, None)):
            return server.fusion_comp("add_keyframe", params)

    def test_attaches_bezierspline_on_virgin_input(self):
        inp = FakeFusionInput(connected_output=None)
        tool = FakeFusionTool({"Size": inp})
        comp = FakeFusionComp({"Transform1": tool})

        result = self._run(comp, {
            "tool_name": "Transform1", "input_name": "Size", "time": 0, "value": 1.0,
        })

        self.assertTrue(result.get("success"))
        self.assertEqual(tool.modifiers_added, [("Size", "BezierSpline")])
        self.assertEqual(inp.assignments, {0: 1.0})
        self.assertEqual((comp.lock_count, comp.unlock_count), (1, 1))

    def test_skips_modifier_when_already_animated(self):
        inp = FakeFusionInput(connected_output=object())
        tool = FakeFusionTool({"Size": inp})
        comp = FakeFusionComp({"Transform1": tool})

        result = self._run(comp, {
            "tool_name": "Transform1", "input_name": "Size", "time": 75, "value": 1.4,
        })

        self.assertTrue(result.get("success"))
        self.assertEqual(tool.modifiers_added, [])
        self.assertEqual(inp.assignments, {75: 1.4})

    def test_honors_custom_modifier_param(self):
        inp = FakeFusionInput(connected_output=None)
        tool = FakeFusionTool({"Center": inp})
        comp = FakeFusionComp({"Transform1": tool})

        self._run(comp, {
            "tool_name": "Transform1", "input_name": "Center",
            "time": 0, "value": [0.5, 0.5], "modifier": "Path",
        })

        self.assertEqual(tool.modifiers_added, [("Center", "Path")])

    def test_missing_input_returns_error_and_unlocks(self):
        tool = FakeFusionTool({})
        comp = FakeFusionComp({"Transform1": tool})

        result = self._run(comp, {
            "tool_name": "Transform1", "input_name": "Nope", "time": 0, "value": 1.0,
        })

        self.assertIn("error", result)
        self.assertEqual(tool.modifiers_added, [])
        # comp must be unlocked even on the error path.
        self.assertEqual((comp.lock_count, comp.unlock_count), (1, 1))


class FusionGetKeyframesTests(unittest.TestCase):
    def test_returns_frame_positions_and_values(self):
        # GetKeyFrames yields {index: frame}; the handler must report the frame
        # position as `time` and the GetInput(frame) result as `value`.
        inp = FakeFusionInput(
            connected_output=object(),
            keyframe_values={0.0: 1.0, 75.0: 1.4},
        )
        tool = FakeFusionTool({"Size": inp})
        comp = FakeFusionComp({"Transform1": tool})

        with patch.object(server, "_resolve_fusion_comp", return_value=(comp, None)):
            result = server.fusion_comp(
                "get_keyframes", {"tool_name": "Transform1", "input_name": "Size"}
            )

        self.assertEqual(
            result["keyframes"],
            [{"time": 0.0, "value": 1.0}, {"time": 75.0, "value": 1.4}],
        )

    def test_no_keyframes_returns_empty_list(self):
        inp = FakeFusionInput(connected_output=None, keyframe_values={})
        tool = FakeFusionTool({"Size": inp})
        comp = FakeFusionComp({"Transform1": tool})

        with patch.object(server, "_resolve_fusion_comp", return_value=(comp, None)):
            result = server.fusion_comp(
                "get_keyframes", {"tool_name": "Transform1", "input_name": "Size"}
            )

        self.assertEqual(result["keyframes"], [])


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
        self.assertIn("item has 2 comp(s)", (err["error"].get("message","") if isinstance(err["error"], dict) else err["error"]))


if __name__ == "__main__":
    unittest.main()
