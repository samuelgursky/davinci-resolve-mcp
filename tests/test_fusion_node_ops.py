"""Tests for Fusion node layout/copy actions on the fusion_comp tool.

Covers get_position / set_position / copy_tool / auto_arrange and the position
normalizer, using a fake comp so no live Resolve is needed.
"""
import unittest
from unittest import mock

import src.server as s


class FakeFlow:
    def __init__(self):
        self.pos = {}

    def GetPosTable(self, tool):
        if tool.name in self.pos:
            x, y = self.pos[tool.name]
            return {1: x, 2: y}
        return None

    def SetPos(self, tool, x, y):
        self.pos[tool.name] = (x, y)


class _CF:
    def __init__(self, flow):
        self.FlowView = flow


class FakeTool:
    def __init__(self, name, comp, regid="Background"):
        self.name = name
        self.comp = comp
        self.regid = regid
        self.settings_loaded = False

    def GetAttrs(self):
        return {"TOOLS_Name": self.name, "TOOLS_RegID": self.regid}

    def SetAttrs(self, d):
        if "TOOLS_Name" in d:
            self.comp._rename(self.name, d["TOOLS_Name"])
            self.name = d["TOOLS_Name"]

    def SaveSettings(self, path):
        # Real Fusion writes the tool's settings to the file at `path`; the test
        # only needs to confirm the call path, so report success.
        return True

    def LoadSettings(self, path):
        self.settings_loaded = True
        return True


class FakeComp:
    def __init__(self):
        self.tools = {}
        self.flow = FakeFlow()
        self.locks = 0
        self._added = 0

    def add(self, name, regid="Background"):
        t = FakeTool(name, self, regid=regid)
        self.tools[name] = t
        return t

    def FindTool(self, name):
        return self.tools.get(name)

    @property
    def CurrentFrame(self):
        return _CF(self.flow)

    def GetToolList(self):
        return {i + 1: t for i, t in enumerate(self.tools.values())}

    def Lock(self):
        self.locks += 1

    def Unlock(self):
        self.locks -= 1

    def GetAttrs(self):
        return dict(getattr(self, "_attrs", {}))

    def SetAttrs(self, d):
        self._attrs = {**getattr(self, "_attrs", {}), **d}

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


class ParsePosTest(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(s._parse_pos({1: 3, 2: 4}), (3.0, 4.0))
        self.assertEqual(s._parse_pos({"1": 3, "2": 4}), (3.0, 4.0))
        self.assertEqual(s._parse_pos({"x": 5, "y": 6}), (5.0, 6.0))
        self.assertEqual(s._parse_pos([7, 8]), (7.0, 8.0))
        self.assertEqual(s._parse_pos((9, 10, 11)), (9.0, 10.0))
        self.assertIsNone(s._parse_pos(None))
        self.assertIsNone(s._parse_pos({}))
        self.assertIsNone(s._parse_pos([1]))


class GetPositionTest(unittest.TestCase):
    def test_reads_position(self):
        comp = FakeComp()
        comp.add("T1")
        comp.flow.pos["T1"] = (3.0, 4.0)
        out = _dispatch(comp, "get_position", {"tool_name": "T1"})
        self.assertEqual((out["x"], out["y"]), (3.0, 4.0))

    def test_missing_tool(self):
        out = _dispatch(FakeComp(), "get_position", {"tool_name": "nope"})
        self.assertIn("error", out)


class SetPositionTest(unittest.TestCase):
    def test_sets_and_reads_back(self):
        comp = FakeComp()
        comp.add("T1")
        out = _dispatch(comp, "set_position", {"tool_name": "T1", "x": 12, "y": -3})
        self.assertTrue(out["success"])
        self.assertEqual(comp.flow.pos["T1"], (12.0, -3.0))
        self.assertEqual(out["readback"], {"x": 12.0, "y": -3.0})
        self.assertEqual(comp.locks, 0)  # balanced Lock/Unlock

    def test_requires_x_y(self):
        comp = FakeComp()
        comp.add("T1")
        out = _dispatch(comp, "set_position", {"tool_name": "T1", "x": 1})
        self.assertIn("error", out)


class CopyToolTest(unittest.TestCase):
    def test_copies_and_identifies_new_tool(self):
        comp = FakeComp()
        comp.add("T1", regid="Transform")
        out = _dispatch(comp, "copy_tool", {"tool_name": "T1"})
        self.assertTrue(out["success"])
        self.assertTrue(out["new_tool"])
        self.assertNotEqual(out["new_tool"], "T1")
        self.assertIn(out["new_tool"], comp.tools)
        # New node carries the source's settings (LoadSettings was called).
        self.assertTrue(comp.tools[out["new_tool"]].settings_loaded)
        self.assertEqual(comp.locks, 0)  # balanced Lock/Unlock

    def test_copy_with_rename_and_position(self):
        comp = FakeComp()
        comp.add("T1")
        out = _dispatch(comp, "copy_tool", {"tool_name": "T1", "name": "Clone", "x": 5, "y": 6})
        self.assertTrue(out["success"])
        self.assertEqual(out["new_tool"], "Clone")
        self.assertIn("Clone", comp.tools)
        self.assertEqual(comp.flow.pos["Clone"], (5.0, 6.0))

    def test_missing_source(self):
        out = _dispatch(FakeComp(), "copy_tool", {"tool_name": "nope"})
        self.assertIn("error", out)


class AutoArrangeTest(unittest.TestCase):
    def test_horizontal_default(self):
        comp = FakeComp()
        comp.add("A")
        comp.add("B")
        comp.add("C")
        out = _dispatch(comp, "auto_arrange", {"spacing": 2})
        self.assertEqual(out["count"], 3)
        self.assertEqual(comp.flow.pos["A"], (0.0, 0.0))
        self.assertEqual(comp.flow.pos["B"], (2.0, 0.0))
        self.assertEqual(comp.flow.pos["C"], (4.0, 0.0))

    def test_vertical_subset(self):
        comp = FakeComp()
        comp.add("A")
        comp.add("B")
        out = _dispatch(comp, "auto_arrange",
                        {"tool_names": ["B"], "direction": "vertical", "spacing": 3, "x": 1, "y": 1})
        self.assertEqual(out["count"], 1)
        self.assertEqual(comp.flow.pos["B"], (1.0, 1.0))

    def test_empty(self):
        out = _dispatch(FakeComp(), "auto_arrange", {})
        self.assertIn("error", out)


class FrameRangeTest(unittest.TestCase):
    def test_set_then_get_roundtrip(self):
        comp = FakeComp()
        _dispatch(comp, "set_frame_range", {"start": 0, "end": 100})
        out = _dispatch(comp, "get_frame_range", {})
        self.assertEqual(out["start"], 0)
        self.assertEqual(out["end"], 100)


if __name__ == "__main__":
    unittest.main()
