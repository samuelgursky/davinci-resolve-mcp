"""Text modifiers attach through `fusion_comp add_modifier` (issue #250).

`Tool.AddModifier` wants the modifier's REGISTRY ID. Measured on Studio
19.1.3.7 on a TextPlus StyledText input: "Follower" and "TextFollower" return
False and attach nothing; "StyledTextFollower" attaches a `Follower1` tool and
connects it to the input. Before this, `add_keyframe(modifier="Follower")`
failed with FUSION_ADD_MODIFIER_FAILED and there was no way to reach the
modifier tool an agent needs to drive (Delay, per-character transforms).
"""
import unittest
from unittest.mock import patch

from src import server


class _Output:
    def __init__(self, tool):
        self._tool = tool

    def GetTool(self):
        return self._tool


class _ModifierTool:
    def __init__(self, name, reg_id):
        self._attrs = {"TOOLS_Name": name, "TOOLS_RegID": reg_id}

    def GetAttrs(self):
        return dict(self._attrs)


class _Input:
    def __init__(self):
        self._connected = None
        self.writes = {}

    def GetConnectedOutput(self):
        return self._connected

    def __setitem__(self, time, value):
        self.writes[time] = value


class _Tool:
    """Mirrors Fusion: only the registry ID attaches, and it creates a tool."""

    ACCEPTED = {"StyledTextFollower": "Follower1", "BezierSpline": "StyledTextBezierSpline1"}

    def __init__(self, inputs):
        self._inputs = inputs
        self.calls = []

    def __getitem__(self, name):
        return self._inputs.get(name)

    def AddModifier(self, input_name, modifier_id):
        self.calls.append((input_name, modifier_id))
        created = self.ACCEPTED.get(modifier_id)
        if created is None:
            return False
        self._inputs[input_name]._connected = _Output(_ModifierTool(created, modifier_id))
        return True


class _Comp:
    def __init__(self, tools):
        self._tools = tools
        self.undo = []

    def FindTool(self, name):
        return self._tools.get(name)

    def StartUndo(self, name):
        self.undo.append(("start", name))

    def EndUndo(self, keep):
        self.undo.append(("end", keep))


def _run(comp, action, params):
    with patch.object(server, "_resolve_fusion_comp", return_value=(comp, None)):
        return server.fusion_comp(action, params)


class ModifierIdTests(unittest.TestCase):
    def test_follower_maps_to_the_registry_id_case_insensitively(self):
        for name in ("Follower", "follower", "FOLLOWER", "TextFollower", "StyledTextFollower"):
            self.assertEqual(server._fusion_modifier_id(name), "StyledTextFollower", name)

    def test_unknown_names_pass_through_untouched(self):
        self.assertEqual(server._fusion_modifier_id("BezierSpline"), "BezierSpline")
        self.assertEqual(server._fusion_modifier_id("Path"), "Path")


class AddModifierTests(unittest.TestCase):
    def setUp(self):
        self.inp = _Input()
        self.tool = _Tool({"StyledText": self.inp})
        self.comp = _Comp({"Text1": self.tool})

    def test_follower_attaches_and_returns_the_created_tool(self):
        out = _run(self.comp, "add_modifier",
                   {"tool_name": "Text1", "input_name": "StyledText", "modifier": "Follower"})
        self.assertTrue(out.get("success"), out)
        self.assertEqual(self.tool.calls, [("StyledText", "StyledTextFollower")])
        self.assertEqual(out["modifier_tool"], "Follower1")
        self.assertEqual(out["modifier_type"], "StyledTextFollower")
        self.assertEqual(out["requested"], "Follower")
        self.assertEqual(self.comp.undo, [("start", "Add modifier StyledTextFollower to StyledText"), ("end", True)])

    def test_a_modifier_fusion_rejects_is_reported_not_claimed(self):
        out = _run(self.comp, "add_modifier",
                   {"tool_name": "Text1", "input_name": "StyledText", "modifier": "NoSuchModifier"})
        self.assertEqual(out["error"]["code"], "FUSION_ADD_MODIFIER_FAILED")
        self.assertIn("StyledTextFollower", out["error"]["remediation"])
        self.assertIsNone(self.inp.GetConnectedOutput())

    def test_an_already_connected_input_is_refused_with_the_existing_tool_named(self):
        self.inp._connected = _Output(_ModifierTool("Follower1", "StyledTextFollower"))
        out = _run(self.comp, "add_modifier",
                   {"tool_name": "Text1", "input_name": "StyledText", "modifier": "Follower"})
        self.assertEqual(out["error"]["code"], "FUSION_INPUT_ALREADY_CONNECTED")
        self.assertEqual(out["error"]["state"]["modifier_tool"], "Follower1")
        self.assertEqual(self.tool.calls, [])

    def test_missing_params_and_unknown_tool_or_input(self):
        self.assertIn("error", _run(self.comp, "add_modifier", {"tool_name": "Text1", "input_name": "StyledText"}))
        self.assertIn("error", _run(self.comp, "add_modifier", {"tool_name": "Nope", "input_name": "StyledText", "modifier": "Follower"}))
        self.assertIn("error", _run(self.comp, "add_modifier", {"tool_name": "Text1", "input_name": "Nope", "modifier": "Follower"}))

    def test_result_carries_the_measured_fact(self):
        out = _run(self.comp, "add_modifier",
                   {"tool_name": "Text1", "input_name": "StyledText", "modifier": "Follower"})
        symbols = [k.get("symbol") for k in out.get("known_limitation", [])]
        self.assertIn("Tool.AddModifier", symbols)


class AddKeyframeNormalisesTheModifierTests(unittest.TestCase):
    def test_add_keyframe_with_follower_sends_the_registry_id(self):
        inp = _Input()
        tool = _Tool({"StyledText": inp})
        comp = _Comp({"Text1": tool})
        out = _run(comp, "add_keyframe", {"tool_name": "Text1", "input_name": "StyledText",
                                          "time": 0, "value": "Hi", "modifier": "Follower"})
        self.assertTrue(out.get("success"), out)
        self.assertEqual(tool.calls, [("StyledText", "StyledTextFollower")])

    def test_add_keyframe_failure_points_at_add_modifier(self):
        inp = _Input()
        tool = _Tool({"Size": inp})
        comp = _Comp({"T": tool})
        out = _run(comp, "add_keyframe", {"tool_name": "T", "input_name": "Size",
                                          "time": 0, "value": 1.0, "modifier": "Bogus"})
        self.assertEqual(out["error"]["code"], "FUSION_ADD_MODIFIER_FAILED")
        self.assertIn("add_modifier", out["error"]["remediation"])


if __name__ == "__main__":
    unittest.main()
