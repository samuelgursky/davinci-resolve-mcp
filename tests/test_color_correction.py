#!/usr/bin/env python3
"""
Unit tests for DaVinci Resolve MCP color correction functions.
"""

import os
import sys
import unittest
import json
from unittest.mock import MagicMock, patch

# Add the src directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from color_functions.color_correction import (
    mcp_get_current_node_index, mcp_set_current_node_index,
    mcp_add_serial_node, mcp_add_parallel_node, mcp_add_layer_node,
    mcp_delete_current_node, mcp_reset_current_node, mcp_get_node_list,
    mcp_get_primary_correction, mcp_set_primary_correction,
    mcp_get_node_label, mcp_set_node_label,
    mcp_get_node_color, mcp_set_node_color,
    mcp_import_lut, mcp_apply_lut_to_current_node
)


class MockColorCorrector:
    def __init__(self):
        self.current_node_index = 1
        self.nodes = [
            {"index": 1, "label": "Node 1", "type": "serial", "color": {"red": 0.5, "green": 0.5, "blue": 0.5, "alpha": 1.0}},
            {"index": 2, "label": "Node 2", "type": "serial", "color": {"red": 0.2, "green": 0.7, "blue": 0.3, "alpha": 1.0}}
        ]
        self.primary_settings = {
            "lift": {"red": 0.0, "green": 0.0, "blue": 0.0, "master": 0.0},
            "gamma": {"red": 1.0, "green": 1.0, "blue": 1.0, "master": 1.0},
            "gain": {"red": 1.0, "green": 1.0, "blue": 1.0, "master": 1.0},
            "contrast": 1.0,
            "saturation": 1.0
        }
        self.luts = []
    
    def GetCurrentNodeIndex(self):
        return self.current_node_index
    
    def SetCurrentNodeIndex(self, index):
        if 1 <= index <= len(self.nodes):
            self.current_node_index = index
            return True
        return False
    
    def AddNode(self, node_type="serial"):
        index = len(self.nodes) + 1
        self.nodes.append({"index": index, "label": f"Node {index}", "type": node_type, 
                          "color": {"red": 0.5, "green": 0.5, "blue": 0.5, "alpha": 1.0}})
        return {"index": index}
    
    def DeleteNode(self):
        if len(self.nodes) > 1:
            del self.nodes[self.current_node_index - 1]
            if self.current_node_index > len(self.nodes):
                self.current_node_index = len(self.nodes)
            # Renumber nodes
            for i, node in enumerate(self.nodes):
                node["index"] = i + 1
            return True
        return False
    
    def ResetNode(self):
        return True
    
    def GetNodeList(self):
        return self.nodes
    
    def GetPrimaryCorrection(self):
        return self.primary_settings
    
    def SetPrimaryCorrection(self, settings):
        self.primary_settings.update(settings)
        return True
    
    def GetNodeLabel(self):
        if 1 <= self.current_node_index <= len(self.nodes):
            return self.nodes[self.current_node_index - 1]["label"]
        return ""
    
    def SetNodeLabel(self, label):
        if 1 <= self.current_node_index <= len(self.nodes):
            self.nodes[self.current_node_index - 1]["label"] = label
            return True
        return False
    
    def GetNodeColor(self):
        if 1 <= self.current_node_index <= len(self.nodes):
            return self.nodes[self.current_node_index - 1]["color"]
        return {"red": 0, "green": 0, "blue": 0, "alpha": 0}
    
    def SetNodeColor(self, color):
        if 1 <= self.current_node_index <= len(self.nodes):
            self.nodes[self.current_node_index - 1]["color"] = color
            return True
        return False
    
    def ImportLut(self, path):
        if os.path.exists(path):
            self.luts.append(path)
            return True
        return False
    
    def ApplyLutToNode(self, path):
        if path in self.luts:
            return True
        return False


class MockNode:
    def __init__(self, index=1, label="Node 1"):
        self.index = index
        self.label = label
        self.color = {"red": 0.5, "green": 0.5, "blue": 0.5, "alpha": 1.0}


class MockCurrentClip:
    def __init__(self):
        self.corrector = MockColorCorrector()
    
    def GetCurrentNode(self):
        return MockNode(
            self.corrector.current_node_index, 
            self.corrector.nodes[self.corrector.current_node_index - 1]["label"]
        )


class MockTimeline:
    def __init__(self):
        self.current_clip = MockCurrentClip()
    
    def GetCurrentClip(self):
        return self.current_clip


class MockProject:
    def __init__(self):
        self.timeline = MockTimeline()
    
    def GetCurrentTimeline(self):
        return self.timeline


class MockResolve:
    def __init__(self):
        self.project = MockProject()
    
    def GetProjectManager(self):
        return MagicMock()
    
    def GetCurrentProject(self):
        return self.project


class TestColorCorrectionFunctions(unittest.TestCase):
    
    def setUp(self):
        self.mock_resolve = MockResolve()
        self.patcher = patch('color_functions.color_correction.get_resolve', return_value=self.mock_resolve)
        self.mock_get_resolve = self.patcher.start()
    
    def tearDown(self):
        self.patcher.stop()

    def test_get_current_node_index(self):
        # Given the mock resolve is set up with a current node index of 1
        
        # When we call the get current node index function
        result = mcp_get_current_node_index(None)
        
        # Then we expect the result to be the current node index
        self.assertEqual(result, {"index": 1})

    def test_set_current_node_index(self):
        # Given the mock resolve is set up with two nodes
        
        # When we set the current node index to 2
        result = mcp_set_current_node_index(None, 2)
        
        # Then we expect the function to return success
        self.assertEqual(result, {"success": True})
        # And the current node index should be updated
        self.assertEqual(self.mock_resolve.project.timeline.current_clip.corrector.current_node_index, 2)

    def test_add_serial_node(self):
        # Given the mock resolve is set up with two nodes
        
        # When we add a serial node
        result = mcp_add_serial_node(None)
        
        # Then we expect the result to contain the new node index
        self.assertEqual(result, {"node_index": 3})
        # And the nodes list should now have 3 nodes
        self.assertEqual(len(self.mock_resolve.project.timeline.current_clip.corrector.nodes), 3)

    def test_add_parallel_node(self):
        # When we add a parallel node
        result = mcp_add_parallel_node(None)
        
        # Then we expect the result to contain the new node index
        self.assertEqual(result, {"node_index": 3})
        # And the new node should be of type parallel
        self.assertEqual(
            self.mock_resolve.project.timeline.current_clip.corrector.nodes[2]["type"],
            "parallel"
        )

    def test_add_layer_node(self):
        # When we add a layer node
        result = mcp_add_layer_node(None)
        
        # Then we expect the result to contain the new node index
        self.assertEqual(result, {"node_index": 3})
        # And the new node should be of type layer
        self.assertEqual(
            self.mock_resolve.project.timeline.current_clip.corrector.nodes[2]["type"],
            "layer"
        )

    def test_delete_current_node(self):
        # Given the mock resolve is set up with the current node index set to 2
        self.mock_resolve.project.timeline.current_clip.corrector.current_node_index = 2
        
        # When we delete the current node
        result = mcp_delete_current_node(None)
        
        # Then we expect the function to return success
        self.assertEqual(result, {"success": True})
        # And the nodes list should now have only 1 node
        self.assertEqual(len(self.mock_resolve.project.timeline.current_clip.corrector.nodes), 1)
        # And the current node index should be adjusted to 1
        self.assertEqual(self.mock_resolve.project.timeline.current_clip.corrector.current_node_index, 1)

    def test_reset_current_node(self):
        # When we reset the current node
        result = mcp_reset_current_node(None)
        
        # Then we expect the function to return success
        self.assertEqual(result, {"success": True})

    def test_get_node_list(self):
        # When we get the node list
        result = mcp_get_node_list(None)
        
        # Then we expect the result to contain the nodes list
        self.assertEqual(len(result["nodes"]), 2)
        self.assertEqual(result["nodes"][0]["index"], 1)
        self.assertEqual(result["nodes"][1]["index"], 2)

    def test_get_primary_correction(self):
        # When we get the primary correction settings
        result = mcp_get_primary_correction(None)
        
        # Then we expect the result to contain the primary settings
        self.assertEqual(result["lift"]["red"], 0.0)
        self.assertEqual(result["gamma"]["green"], 1.0)
        self.assertEqual(result["gain"]["blue"], 1.0)
        self.assertEqual(result["saturation"], 1.0)

    def test_set_primary_correction(self):
        # Given a new set of primary correction values
        settings = {
            "lift": {"red": 0.1, "green": 0.0, "blue": -0.1, "master": 0.0},
            "gamma": {"red": 1.1, "green": 1.0, "blue": 0.9, "master": 1.0},
            "gain": {"red": 1.2, "green": 1.0, "blue": 0.8, "master": 1.0},
            "saturation": 1.2
        }
        
        # When we set the primary correction
        result = mcp_set_primary_correction(None, settings)
        
        # Then we expect the function to return success
        self.assertEqual(result, {"success": True})
        # And the primary settings should be updated
        corrector = self.mock_resolve.project.timeline.current_clip.corrector
        self.assertEqual(corrector.primary_settings["lift"]["red"], 0.1)
        self.assertEqual(corrector.primary_settings["gamma"]["red"], 1.1)
        self.assertEqual(corrector.primary_settings["gain"]["red"], 1.2)
        self.assertEqual(corrector.primary_settings["saturation"], 1.2)

    def test_get_node_label(self):
        # When we get the node label
        result = mcp_get_node_label(None)
        
        # Then we expect the result to contain the label
        self.assertEqual(result, {"label": "Node 1"})

    def test_set_node_label(self):
        # When we set the node label
        result = mcp_set_node_label(None, "Custom Label")
        
        # Then we expect the function to return success
        self.assertEqual(result, {"success": True})
        # And the node label should be updated
        self.assertEqual(
            self.mock_resolve.project.timeline.current_clip.corrector.nodes[0]["label"],
            "Custom Label"
        )

    def test_get_node_color(self):
        # When we get the node color
        result = mcp_get_node_color(None)
        
        # Then we expect the result to contain the color values
        self.assertEqual(result["red"], 0.5)
        self.assertEqual(result["green"], 0.5)
        self.assertEqual(result["blue"], 0.5)
        self.assertEqual(result["alpha"], 1.0)

    def test_set_node_color(self):
        # Given a new set of color values
        color = {"red": 0.8, "green": 0.3, "blue": 0.2, "alpha": 1.0}
        
        # When we set the node color
        result = mcp_set_node_color(None, color)
        
        # Then we expect the function to return success
        self.assertEqual(result, {"success": True})
        # And the node color should be updated
        node_color = self.mock_resolve.project.timeline.current_clip.corrector.nodes[0]["color"]
        self.assertEqual(node_color["red"], 0.8)
        self.assertEqual(node_color["green"], 0.3)
        self.assertEqual(node_color["blue"], 0.2)

    @patch('os.path.exists', return_value=True)
    def test_import_lut(self, mock_exists):
        # Given a LUT path
        lut_path = "/path/to/my_lut.cube"
        
        # When we import the LUT
        result = mcp_import_lut(None, lut_path)
        
        # Then we expect the function to return success
        self.assertEqual(result, {"success": True})
        # And the LUT should be added to the list
        self.assertIn(lut_path, self.mock_resolve.project.timeline.current_clip.corrector.luts)

    @patch('os.path.exists', return_value=True)
    def test_apply_lut_to_current_node(self, mock_exists):
        # Given an imported LUT
        lut_path = "/path/to/my_lut.cube"
        self.mock_resolve.project.timeline.current_clip.corrector.luts.append(lut_path)
        
        # When we apply the LUT to the current node
        result = mcp_apply_lut_to_current_node(None, lut_path)
        
        # Then we expect the function to return success
        self.assertEqual(result, {"success": True})


if __name__ == '__main__':
    unittest.main() 