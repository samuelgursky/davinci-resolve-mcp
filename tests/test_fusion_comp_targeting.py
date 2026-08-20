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
        # Names the code under test asked for and the bridge answered with None.
        self.unknown_lookups = []

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

    def __getattr__(self, name):
        # The fusionscript bridge resolves an unknown attribute to None instead
        # of raising AttributeError, which is why the old delete_keyframe
        # implementation died as "'NoneType' object is not callable" rather
        # than at the lookup. Reproduce that so the regression test is honest.
        if name.startswith("__"):
            raise AttributeError(name)
        self.unknown_lookups.append(name)
        return None


class FakeSplineOutput:
    """The Output object an animated Input is connected to."""

    def __init__(self, tool):
        self._tool = tool

    def GetTool(self):
        return self._tool


class FakeSpline:
    """A BezierSpline modifier -- where Fusion keyframes actually live."""

    def __init__(self, inp, supports_delete=True, effective=True, raises=None):
        self._inp = inp
        self._effective = effective
        self._raises = raises
        self.deleted = []
        if not supports_delete:
            # Mirror a build/modifier lacking the method: the bridge hands back
            # None for the name rather than raising on the lookup.
            self.DeleteKeyFrames = None

    def DeleteKeyFrames(self, time):
        if self._raises is not None:
            raise self._raises
        self.deleted.append(time)
        if self._effective:
            self._inp.keyframe_values.pop(time, None)
        return True


def make_animated_input(keyframe_values, **spline_kwargs):
    """An Input wired to a spline, the way add_keyframe leaves one."""
    inp = FakeFusionInput(keyframe_values=keyframe_values)
    spline = FakeSpline(inp, **spline_kwargs)
    inp._connected_output = FakeSplineOutput(spline)
    return inp, spline


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


class FusionDeleteKeyframeTests(unittest.TestCase):
    """issue #155 -- delete_keyframe called RemoveKeyFrame on the Input.

    No such method exists there; keyframes live on the spline connected to the
    input. The bridge answers an unknown attribute with None, so every call
    failed as an opaque `'NoneType' object is not callable`.
    """

    def _run(self, comp, params):
        with patch.object(server, "_resolve_fusion_comp", return_value=(comp, None)):
            return server.fusion_comp("delete_keyframe", params)

    def _params(self, time=75.0):
        return {"tool_name": "Transform1", "input_name": "Size", "time": time}

    def test_deletes_through_the_spline(self):
        inp, spline = make_animated_input({0.0: 1.0, 75.0: 1.4})
        comp = FakeFusionComp({"Transform1": FakeFusionTool({"Size": inp})})

        result = self._run(comp, self._params())

        self.assertNotIn("error", result)
        self.assertTrue(result["success"])
        self.assertEqual(spline.deleted, [75.0])
        self.assertEqual(result["remaining_keyframes"], [0.0])
        self.assertEqual((comp.lock_count, comp.unlock_count), (1, 1))

    def test_never_touches_removekeyframe_on_the_input(self):
        # The exact regression: the handler must not reach for a method the
        # Input does not have. Any such lookup is recorded by the fake.
        inp, _ = make_animated_input({75.0: 1.4})
        comp = FakeFusionComp({"Transform1": FakeFusionTool({"Size": inp})})

        result = self._run(comp, self._params())

        self.assertNotIn("error", result)
        self.assertNotIn("RemoveKeyFrame", inp.unknown_lookups)

    def test_integer_frame_matches_a_float_keyframe(self):
        # Fusion reports keyframe positions as floats; callers pass ints.
        inp, spline = make_animated_input({75.0: 1.4})
        comp = FakeFusionComp({"Transform1": FakeFusionTool({"Size": inp})})

        result = self._run(comp, self._params(time=75))

        self.assertNotIn("error", result)
        self.assertEqual(spline.deleted, [75.0])

    def test_unanimated_input_is_a_structured_error(self):
        inp = FakeFusionInput(connected_output=None, keyframe_values={})
        comp = FakeFusionComp({"Transform1": FakeFusionTool({"Size": inp})})

        result = self._run(comp, self._params())

        self.assertEqual(result["error"]["code"], "FUSION_INPUT_NOT_ANIMATED")
        self.assertEqual(result["error"]["category"], "precondition")
        self.assertEqual((comp.lock_count, comp.unlock_count), (1, 1))

    def test_no_keyframe_at_that_frame_is_a_structured_error(self):
        inp, spline = make_animated_input({0.0: 1.0})
        comp = FakeFusionComp({"Transform1": FakeFusionTool({"Size": inp})})

        result = self._run(comp, self._params(time=75.0))

        self.assertEqual(result["error"]["code"], "FUSION_KEYFRAME_NOT_FOUND")
        self.assertEqual(result["error"]["state"]["keyframes"], [0.0])
        self.assertEqual(spline.deleted, [])

    def test_modifier_without_delete_support_is_reported_as_unsupported(self):
        inp, _ = make_animated_input({75.0: 1.4}, supports_delete=False)
        comp = FakeFusionComp({"Transform1": FakeFusionTool({"Size": inp})})

        result = self._run(comp, self._params())

        self.assertEqual(
            result["error"]["code"], "FUSION_DELETE_KEYFRAMES_UNSUPPORTED"
        )
        self.assertEqual(result["error"]["category"], "unsupported")

    def test_raising_delete_becomes_an_envelope_not_an_exception(self):
        inp, _ = make_animated_input({75.0: 1.4}, raises=RuntimeError("boom"))
        comp = FakeFusionComp({"Transform1": FakeFusionTool({"Size": inp})})

        result = self._run(comp, self._params())

        self.assertEqual(result["error"]["code"], "FUSION_DELETE_KEYFRAME_FAILED")
        self.assertIn("boom", result["error"]["message"])
        self.assertEqual((comp.lock_count, comp.unlock_count), (1, 1))

    def test_silent_noop_is_not_reported_as_success(self):
        # A Fusion call returning without error is not proof it did anything.
        inp, spline = make_animated_input({75.0: 1.4}, effective=False)
        comp = FakeFusionComp({"Transform1": FakeFusionTool({"Size": inp})})

        result = self._run(comp, self._params())

        self.assertEqual(result["error"]["code"], "FUSION_DELETE_KEYFRAME_NOOP")
        self.assertEqual(spline.deleted, [75.0])

    def test_missing_input_returns_error_and_unlocks(self):
        comp = FakeFusionComp({"Transform1": FakeFusionTool({})})

        result = self._run(comp, self._params())

        self.assertEqual(result["error"]["code"], "FUSION_INPUT_NOT_FOUND")
        self.assertEqual((comp.lock_count, comp.unlock_count), (1, 1))

    def test_non_numeric_time_is_rejected(self):
        inp, _ = make_animated_input({75.0: 1.4})
        comp = FakeFusionComp({"Transform1": FakeFusionTool({"Size": inp})})

        result = self._run(comp, self._params(time="soon"))

        self.assertEqual(result["error"]["code"], "INVALID_FRAME")
        self.assertEqual(result["error"]["category"], "invalid_input")

    def test_missing_tool_returns_error(self):
        comp = FakeFusionComp({})

        result = self._run(comp, self._params())

        self.assertIn("error", result)
        self.assertIn("not found", result["error"]["message"])


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
