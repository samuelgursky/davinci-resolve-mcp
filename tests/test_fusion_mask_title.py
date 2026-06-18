"""Tests for the fusion_comp convenience actions added for issue #73:

  - add_fusion_mask  (Rectangle/Ellipse mask + params + optional wiring)
  - set_text_plus / get_text_plus  (Fusion Text+ / title template text)

A fake comp/tool is used so no live Resolve is needed.
"""
import unittest
from unittest import mock

import src.server as s


class FakeTool:
    def __init__(self, name, comp, regid="Background"):
        self.name = name
        self.comp = comp
        self.regid = regid
        self.inputs = {}
        self.connections = {}

    def GetAttrs(self):
        return {"TOOLS_Name": self.name, "TOOLS_RegID": self.regid}

    def SetAttrs(self, d):
        if "TOOLS_Name" in d:
            self.comp._rename(self.name, d["TOOLS_Name"])
            self.name = d["TOOLS_Name"]

    def SetInput(self, input_id, value, *time):
        self.inputs[input_id] = value
        return True

    def GetInput(self, input_id, *time):
        return self.inputs.get(input_id)

    def ConnectInput(self, input_name, source):
        self.connections[input_name] = source
        return True


class FakeComp:
    def __init__(self):
        self.tools = {}
        self.locks = 0
        self._added = 0

    def add(self, name, regid="Background"):
        t = FakeTool(name, self, regid=regid)
        self.tools[name] = t
        return t

    def FindTool(self, name):
        return self.tools.get(name)

    def GetToolList(self, *args):
        return {i + 1: t for i, t in enumerate(self.tools.values())}

    def Lock(self):
        self.locks += 1

    def Unlock(self):
        self.locks -= 1

    def AddTool(self, regid, x=-32768, y=-32768):
        self._added += 1
        name = f"{regid}_{self._added}"
        while name in self.tools:
            self._added += 1
            name = f"{regid}_{self._added}"
        return self.add(name, regid=regid)

    def _rename(self, old, new):
        self.tools[new] = self.tools.pop(old)


def _dispatch(comp, action, params):
    with mock.patch.object(s, "_resolve_fusion_comp", return_value=(comp, None)):
        return s.fusion_comp(action, params)


class AddFusionMaskTest(unittest.TestCase):
    def test_rectangle_mask_sets_friendly_params(self):
        comp = FakeComp()
        out = _dispatch(comp, "add_fusion_mask", {
            "mask_type": "Rectangle",
            "corner_radius": 0.445,
            "width": 0.3,
            "height": 0.964,
            "center_x": 0.5,
            "center_y": 0.5,
        })
        self.assertTrue(out["success"])
        self.assertEqual(out["tool_type"], "RectangleMask")
        tool = comp.tools[out["tool_name"]]
        # Friendly names mapped to Fusion input ids.
        self.assertEqual(tool.inputs["CornerRadius"], 0.445)
        self.assertEqual(tool.inputs["Width"], 0.3)
        self.assertEqual(tool.inputs["Height"], 0.964)
        # center_x/center_y combine into a single Point input.
        self.assertEqual(tool.inputs["Center"], [0.5, 0.5])
        # Every applied input reports success.
        self.assertTrue(all(r["success"] for r in out["inputs_set"]))
        self.assertEqual(comp.locks, 0)  # balanced Lock/Unlock

    def test_ellipse_alias(self):
        comp = FakeComp()
        out = _dispatch(comp, "add_fusion_mask", {"mask_type": "ellipse", "width": 0.2})
        self.assertTrue(out["success"])
        self.assertEqual(out["tool_type"], "EllipseMask")

    def test_defaults_to_rectangle(self):
        comp = FakeComp()
        out = _dispatch(comp, "add_fusion_mask", {})
        self.assertTrue(out["success"])
        self.assertEqual(out["tool_type"], "RectangleMask")

    def test_invalid_mask_type(self):
        out = _dispatch(FakeComp(), "add_fusion_mask", {"mask_type": "Triangle"})
        self.assertIn("error", out)

    def test_center_list_form(self):
        comp = FakeComp()
        out = _dispatch(comp, "add_fusion_mask", {"center": [0.25, 0.75]})
        tool = comp.tools[out["tool_name"]]
        self.assertEqual(tool.inputs["Center"], [0.25, 0.75])

    def test_raw_inputs_passthrough(self):
        comp = FakeComp()
        out = _dispatch(comp, "add_fusion_mask", {"inputs": {"Angle": 45, "CustomKey": 1}})
        tool = comp.tools[out["tool_name"]]
        self.assertEqual(tool.inputs["Angle"], 45)
        self.assertEqual(tool.inputs["CustomKey"], 1)

    def test_optional_connect_wires_into_target(self):
        comp = FakeComp()
        comp.add("MediaOut1", regid="MediaOut")
        out = _dispatch(comp, "add_fusion_mask", {
            "width": 0.5,
            "connect_to": "MediaOut1",
        })
        self.assertTrue(out["success"])
        self.assertEqual(out["connection"]["success"], True)
        self.assertEqual(out["connection"]["input_name"], "EffectMask")
        # The mask tool is wired into the target's EffectMask input.
        target = comp.tools["MediaOut1"]
        self.assertIn("EffectMask", target.connections)
        self.assertIs(target.connections["EffectMask"], comp.tools[out["tool_name"]])

    def test_connect_to_missing_target_reports_error(self):
        comp = FakeComp()
        out = _dispatch(comp, "add_fusion_mask", {"connect_to": "nope"})
        # The mask is still created; only the wiring fails.
        self.assertTrue(out["success"])
        self.assertFalse(out["connection"]["success"])


class TextPlusTest(unittest.TestCase):
    def test_set_text_auto_finds_text_plus(self):
        comp = FakeComp()
        comp.add("Background1", regid="Background")
        comp.add("Title", regid="TextPlus")
        out = _dispatch(comp, "set_text_plus", {"text": "Hello World"})
        self.assertTrue(out["success"])
        self.assertEqual(out["tool_name"], "Title")
        self.assertEqual(comp.tools["Title"].inputs["StyledText"], "Hello World")
        self.assertEqual(out["readback"], "Hello World")
        self.assertEqual(comp.locks, 0)

    def test_set_text_explicit_tool_name(self):
        comp = FakeComp()
        comp.add("T1", regid="TextPlus")
        comp.add("T2", regid="TextPlus")
        out = _dispatch(comp, "set_text_plus", {"text": "Second", "tool_name": "T2"})
        self.assertEqual(out["tool_name"], "T2")
        self.assertEqual(comp.tools["T2"].inputs["StyledText"], "Second")
        self.assertNotIn("StyledText", comp.tools["T1"].inputs)

    def test_get_text(self):
        comp = FakeComp()
        t = comp.add("Title", regid="TextPlus")
        t.inputs["StyledText"] = "Existing"
        out = _dispatch(comp, "get_text_plus", {})
        self.assertEqual(out["text"], "Existing")
        self.assertEqual(out["tool_name"], "Title")

    def test_set_text_requires_string(self):
        comp = FakeComp()
        comp.add("Title", regid="TextPlus")
        out = _dispatch(comp, "set_text_plus", {})
        self.assertIn("error", out)

    def test_no_text_tool_found(self):
        comp = FakeComp()
        comp.add("Background1", regid="Background")
        out = _dispatch(comp, "set_text_plus", {"text": "x"})
        self.assertIn("error", out)

    def test_get_text_missing_named_tool(self):
        out = _dispatch(FakeComp(), "get_text_plus", {"tool_name": "nope"})
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
