"""A Fusion nest control is refused with its members named (issue #253).

Measured on Studio 19.1.3.7: inputs whose INPID_InputControl is "NestControl"
are fold-down group headers, not values. AddModifier returns False for them on
every modifier type, so add_keyframe used to answer a generic
FUSION_ADD_MODIFIER_FAILED for `Softness1` or the Follower's `TransformSize`.
The controls a header folds are the next INPI_LabelControl_NumInputs inputs in
GetInputList() order, and those take a spline normally.
"""
import unittest
from unittest.mock import patch

from src import server


class _Input:
    def __init__(self, input_id, control="SliderControl", nest_count=0):
        self.id = input_id
        self._attrs = {"INPS_ID": input_id, "INPID_InputControl": control}
        if control == "NestControl":
            self._attrs["INPB_Passive"] = True
            self._attrs["INPI_LabelControl_NumInputs"] = nest_count
        self._connected = None
        self.writes = {}

    def GetAttrs(self):
        return dict(self._attrs)

    def GetConnectedOutput(self):
        return self._connected

    def __setitem__(self, time, value):
        self.writes[time] = value


class _Tool:
    def __init__(self, ordered_inputs):
        self._ordered = ordered_inputs
        self._by_id = {i.id: i for i in ordered_inputs}
        self.calls = []

    def __getitem__(self, name):
        return self._by_id.get(name)

    def GetInputList(self):
        # Fusion keys the list 1-based; hand the keys back unsorted on purpose.
        items = list(enumerate(self._ordered, start=1))
        return {k: v for k, v in reversed(items)}

    def AddModifier(self, input_name, modifier_id):
        self.calls.append((input_name, modifier_id))
        inp = self._by_id[input_name]
        if inp._attrs.get("INPID_InputControl") == "NestControl":
            return False  # what Fusion does
        inp._connected = object()
        return True


class _Comp:
    def __init__(self, tool):
        self._tool = tool

    def FindTool(self, name):
        return self._tool if name == "Follower1" else None

    def StartUndo(self, name):
        pass

    def EndUndo(self, keep):
        pass


def _follower():
    return _Tool([
        _Input("Delay"),
        _Input("TransformSize", "NestControl", 6),
        _Input("LineSizeX"), _Input("LineSizeY"), _Input("WordSizeX"), _Input("WordSizeY"),
        _Input("CharacterSizeX"), _Input("CharacterSizeY"),
        _Input("Opacity1"),
        _Input("Softness1", "NestControl", 5),
        _Input("SoftnessX1"), _Input("SoftnessY1"), _Input("SoftnessOnFillColorToo1"),
        _Input("SoftnessGlow1"), _Input("SoftnessBlend1"),
        _Input("Size1", "NestControl", 2),
        _Input("SizeX1"), _Input("SizeY1"),
    ])


def _run(tool, action, params):
    with patch.object(server, "_resolve_fusion_comp", return_value=(_Comp(tool), None)):
        return server.fusion_comp(action, {"tool_name": "Follower1", **params})


class NestMembersTests(unittest.TestCase):
    def test_members_follow_the_header_in_list_order(self):
        tool = _follower()
        self.assertEqual(server._fusion_nest_members(tool, "TransformSize"),
                         (True, ["LineSizeX", "LineSizeY", "WordSizeX", "WordSizeY",
                                 "CharacterSizeX", "CharacterSizeY"]))
        self.assertEqual(server._fusion_nest_members(tool, "Softness1"),
                         (True, ["SoftnessX1", "SoftnessY1", "SoftnessOnFillColorToo1",
                                 "SoftnessGlow1", "SoftnessBlend1"]))
        self.assertEqual(server._fusion_nest_members(tool, "Size1"), (True, ["SizeX1", "SizeY1"]))

    def test_a_real_input_is_not_a_nest(self):
        self.assertEqual(server._fusion_nest_members(_follower(), "Delay"), (False, []))


class AddKeyframeOnNestControlTests(unittest.TestCase):
    def test_nest_control_is_refused_with_members_and_no_add_modifier_call(self):
        tool = _follower()
        out = _run(tool, "add_keyframe", {"input_name": "Softness1", "time": 0, "value": 0.5})
        self.assertEqual(out["error"]["code"], "FUSION_INPUT_IS_NEST_CONTROL")
        self.assertEqual(out["error"]["state"]["nest_members"][:2], ["SoftnessX1", "SoftnessY1"])
        self.assertIn("SoftnessX1", out["error"]["remediation"])
        self.assertEqual(tool.calls, [])
        self.assertEqual(tool["Softness1"].writes, {})

    def test_the_folded_control_still_keyframes(self):
        tool = _follower()
        out = _run(tool, "add_keyframe", {"input_name": "SoftnessX1", "time": 0, "value": 0.5})
        self.assertTrue(out.get("success"), out)
        self.assertEqual(tool.calls, [("SoftnessX1", "BezierSpline")])
        self.assertEqual(tool["SoftnessX1"].writes, {0: 0.5})

    def test_result_carries_the_measured_fact(self):
        out = _run(_follower(), "add_keyframe", {"input_name": "Delay", "time": 0, "value": 5})
        symbols = [k.get("symbol") for k in out.get("known_limitation", [])]
        self.assertIn("Tool.AddModifier (NestControl inputs)", symbols)


class AddModifierOnNestControlTests(unittest.TestCase):
    def test_nest_control_is_refused_before_add_modifier(self):
        tool = _follower()
        out = _run(tool, "add_modifier", {"input_name": "TransformSize", "modifier": "BezierSpline"})
        self.assertEqual(out["error"]["code"], "FUSION_INPUT_IS_NEST_CONTROL")
        self.assertEqual(len(out["error"]["state"]["nest_members"]), 6)
        self.assertEqual(tool.calls, [])


if __name__ == "__main__":
    unittest.main()
