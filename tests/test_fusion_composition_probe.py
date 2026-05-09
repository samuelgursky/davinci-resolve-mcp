import unittest

from src.server import (
    _fusion_boundary_report,
    _fusion_comp_snapshot,
    _fusion_graph_capabilities,
    _probe_fusion_tool,
    _safe_add_fusion_tool,
    _safe_connect_fusion_tools,
    _safe_set_fusion_inputs,
)


class FusionAttrStub:
    def __init__(self, attrs, connected=None):
        self.attrs = attrs
        self.connected = connected

    def GetAttrs(self):
        return dict(self.attrs)

    def GetConnectedOutput(self):
        return self.connected


class FusionOutputStub(FusionAttrStub):
    def GetTool(self):
        return None


class FusionToolStub:
    def __init__(self, name, reg_id):
        self.attrs = {"TOOLS_Name": name, "TOOLS_RegID": reg_id}
        self.inputs = {}
        self.connected = {}

    def GetAttrs(self):
        return dict(self.attrs)

    def SetAttrs(self, attrs):
        self.attrs.update(attrs)
        return True

    def GetInputList(self):
        return {
            1: FusionAttrStub({"INPS_Name": "Blend", "INPS_ID": "Blend", "INPS_DataType": "Number"}),
            2: FusionAttrStub({"INPS_Name": "Styled Text", "INPS_ID": "StyledText", "INPS_DataType": "Text"}),
        }

    def GetOutputList(self):
        return {1: FusionOutputStub({"OUTS_Name": "Output", "OUTS_ID": "Output", "OUTS_DataType": "Image"})}

    def SetInput(self, input_name, value, *args):
        self.inputs[input_name] = value
        return True

    def GetInput(self, input_name, *args):
        return self.inputs.get(input_name)

    def ConnectInput(self, input_name, source):
        self.connected[input_name] = source
        return True


class FusionCompStub:
    def __init__(self):
        self.tools = {
            1: FusionToolStub("MediaIn1", "MediaIn"),
            2: FusionToolStub("MediaOut1", "MediaOut"),
        }
        self.locked = False

    def GetAttrs(self):
        return {"COMPS_Name": "Stub Comp"}

    def GetToolList(self, *args):
        return dict(self.tools)

    def FindTool(self, name):
        for tool in self.tools.values():
            if tool.attrs["TOOLS_Name"] == name:
                return tool
        return None

    def AddTool(self, tool_type, x=-1, y=-1):
        index = len(self.tools) + 1
        tool = FusionToolStub(f"{tool_type}{index}", tool_type)
        self.tools[index] = tool
        return tool

    def Lock(self):
        self.locked = True

    def Unlock(self):
        self.locked = False


class FusionCompositionProbeTest(unittest.TestCase):
    def test_capabilities_report_common_tools(self):
        capabilities = _fusion_graph_capabilities(FusionCompStub())

        self.assertIn("Background", capabilities["common_tools"])
        self.assertEqual(capabilities["comp"]["tool_count"], 2)

    def test_comp_snapshot_includes_tools_and_io(self):
        snapshot = _fusion_comp_snapshot(FusionCompStub(), {"include_io": True})

        self.assertEqual(snapshot["name"], "Stub Comp")
        self.assertEqual(snapshot["tool_count"], 2)
        self.assertIn("inputs", snapshot["tools"][0])

    def test_safe_add_tool_dry_run_does_not_mutate(self):
        comp = FusionCompStub()
        result = _safe_add_fusion_tool(comp, {"tool_type": "Background", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertEqual(len(comp.tools), 2)

    def test_safe_add_tool_sets_name(self):
        comp = FusionCompStub()
        result = _safe_add_fusion_tool(comp, {"tool_type": "TextPlus", "name": "MCP_Text"})

        self.assertTrue(result["success"])
        self.assertEqual(result["tool"]["name"], "MCP_Text")

    def test_probe_fusion_tool_reports_missing_and_found(self):
        comp = FusionCompStub()

        self.assertFalse(_probe_fusion_tool(comp, {"tool_name": "Missing"})["found"])
        self.assertTrue(_probe_fusion_tool(comp, {"tool_name": "MediaIn1"})["found"])

    def test_safe_set_inputs_returns_readback(self):
        comp = FusionCompStub()
        result = _safe_set_fusion_inputs(comp, {"tool_name": "MediaIn1", "inputs": {"Blend": 0.5}})

        self.assertTrue(result["success"])
        self.assertEqual(result["results"]["Blend"]["value"], 0.5)

    def test_safe_connect_tools_validates_names(self):
        comp = FusionCompStub()
        result = _safe_connect_fusion_tools(
            comp,
            {"target_tool": "MediaOut1", "input_name": "Input", "source_tool": "MediaIn1"},
        )

        self.assertTrue(result["success"])

    def test_boundary_report_shape(self):
        report = _fusion_boundary_report(FusionCompStub(), {"include_io": False})

        self.assertIn("capabilities", report)
        self.assertIn("composition", report)


if __name__ == "__main__":
    unittest.main()
