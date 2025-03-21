#!/usr/bin/env python3
"""
Unit tests for timeline marker functions.
"""

import os
import sys
import unittest
import json
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.timeline_functions.marker_functions import (
    get_all_timeline_markers,
    add_timeline_marker,
    update_marker,
    delete_marker,
    delete_markers_by_color,
    mcp_get_timeline_markers,
    mcp_add_timeline_marker,
    mcp_update_marker,
    mcp_delete_marker,
    mcp_delete_markers_by_color
)

# Mock classes for testing
class MockMarker:
    def __init__(self, frame, color, name="", note="", duration=1, customData=""):
        self.at_frame = frame
        self.color = color
        self.name = name
        self.note = note
        self.duration = duration
        self.customData = customData
        
    def GetMarkerByCustomData(self, data):
        if self.customData == data:
            return self
        return None

class MockTimeline:
    def __init__(self):
        self.markers = {}
        
    def GetMarkers(self):
        return self.markers
    
    def AddMarker(self, frame, color, name="", note="", duration=1, customData=""):
        self.markers[frame] = MockMarker(frame, color, name, note, duration, customData)
        return True
    
    def DeleteMarkerAtFrame(self, frame):
        if frame in self.markers:
            del self.markers[frame]
            return True
        return False
    
    def DeleteMarkersByColor(self, color):
        frames_to_delete = [f for f, m in self.markers.items() if m.color == color]
        for frame in frames_to_delete:
            del self.markers[frame]
        return len(frames_to_delete)
    
    def UpdateMarkerAtFrame(self, frame, color=None, name=None, note=None, duration=None, customData=None):
        if frame not in self.markers:
            return False
        
        marker = self.markers[frame]
        if color:
            marker.color = color
        if name:
            marker.name = name
        if note:
            marker.note = note
        if duration:
            marker.duration = duration
        if customData:
            marker.customData = customData
        
        return True

class MockProject:
    def __init__(self):
        self.current_timeline = MockTimeline()
    
    def GetCurrentTimeline(self):
        return self.current_timeline

class MockResolve:
    def __init__(self):
        self.project_manager = MockProjectManager()
    
    def GetProjectManager(self):
        return self.project_manager

class MockProjectManager:
    def __init__(self):
        self.current_project = MockProject()
    
    def GetCurrentProject(self):
        return self.current_project

class TestMarkerFunctions(unittest.TestCase):
    
    @patch('src.timeline_functions.marker_functions.resolve', MockResolve())
    def setUp(self):
        # Create a mock resolver and timeline with markers
        self.resolve = MockResolve()
        self.project_manager = self.resolve.GetProjectManager()
        self.current_project = self.project_manager.GetCurrentProject()
        self.timeline = self.current_project.GetCurrentTimeline()
        
        # Add some test markers
        self.timeline.AddMarker(100, "Blue", "Marker 1", "Test note 1", 10, "custom1")
        self.timeline.AddMarker(200, "Red", "Marker 2", "Test note 2", 15, "custom2")
        self.timeline.AddMarker(300, "Green", "Marker 3", "Test note 3", 20, "custom3")
        self.timeline.AddMarker(400, "Red", "Marker 4", "Test note 4", 25, "custom4")
    
    def test_get_all_timeline_markers(self):
        # Test getting all markers
        with patch('src.timeline_functions.marker_functions.resolve', self.resolve):
            markers = get_all_timeline_markers()
        
        # Verify we got all markers
        self.assertEqual(len(markers), 4)
        
        # Verify marker details
        self.assertEqual(markers[0]["frame"], 100)
        self.assertEqual(markers[0]["color"], "Blue")
        self.assertEqual(markers[1]["frame"], 200)
        self.assertEqual(markers[1]["color"], "Red")
    
    def test_add_timeline_marker(self):
        # Test adding a new marker
        with patch('src.timeline_functions.marker_functions.resolve', self.resolve):
            result = add_timeline_marker(500, "Yellow", "New Marker", "New note", 30, "custom5")
        
        # Verify the marker was added
        self.assertTrue(result)
        markers = self.timeline.GetMarkers()
        self.assertIn(500, markers)
        self.assertEqual(markers[500].color, "Yellow")
        self.assertEqual(markers[500].name, "New Marker")
    
    def test_update_marker(self):
        # Test updating an existing marker
        with patch('src.timeline_functions.marker_functions.resolve', self.resolve):
            result = update_marker(200, "Purple", "Updated Marker", "Updated note", 40, "updated")
        
        # Verify the marker was updated
        self.assertTrue(result)
        markers = self.timeline.GetMarkers()
        self.assertEqual(markers[200].color, "Purple")
        self.assertEqual(markers[200].name, "Updated Marker")
        self.assertEqual(markers[200].note, "Updated note")
        self.assertEqual(markers[200].duration, 40)
        self.assertEqual(markers[200].customData, "updated")
    
    def test_delete_marker(self):
        # Test deleting a marker
        with patch('src.timeline_functions.marker_functions.resolve', self.resolve):
            result = delete_marker(300)
        
        # Verify the marker was deleted
        self.assertTrue(result)
        markers = self.timeline.GetMarkers()
        self.assertNotIn(300, markers)
        self.assertEqual(len(markers), 3)
    
    def test_delete_markers_by_color(self):
        # Test deleting markers by color
        with patch('src.timeline_functions.marker_functions.resolve', self.resolve):
            count = delete_markers_by_color("Red")
        
        # Verify the markers were deleted
        self.assertEqual(count, 2)
        markers = self.timeline.GetMarkers()
        self.assertEqual(len(markers), 2)
        
        # Verify only Red markers were deleted
        for _, marker in markers.items():
            self.assertNotEqual(marker.color, "Red")
    
    # Test MCP interface functions
    
    @patch('src.timeline_functions.marker_functions.resolve', MockResolve())
    def test_mcp_get_timeline_markers(self):
        result = mcp_get_timeline_markers({})
        data = json.loads(result)
        
        # Verify we got all markers
        self.assertEqual(len(data), 4)
    
    @patch('src.timeline_functions.marker_functions.resolve', MockResolve())
    def test_mcp_add_timeline_marker(self):
        args = {
            "frame": 600,
            "color": "Cyan",
            "name": "MCP Marker",
            "note": "MCP Note",
            "duration": 50,
            "custom_data": "mcp-custom"
        }
        
        result = mcp_add_timeline_marker(args)
        self.assertTrue(json.loads(result))
        
        # Verify the marker was added
        timeline = MockResolve().GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        markers = timeline.GetMarkers()
        self.assertIn(600, markers)
        self.assertEqual(markers[600].color, "Cyan")
    
    @patch('src.timeline_functions.marker_functions.resolve', MockResolve())
    def test_mcp_update_marker(self):
        args = {
            "frame": 100,
            "color": "Lavender",
            "name": "Updated MCP",
            "note": "Updated via MCP",
            "duration": 60,
            "custom_data": "updated-mcp"
        }
        
        result = mcp_update_marker(args)
        self.assertTrue(json.loads(result))
        
        # Verify the marker was updated
        timeline = MockResolve().GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        markers = timeline.GetMarkers()
        self.assertEqual(markers[100].color, "Lavender")
        self.assertEqual(markers[100].name, "Updated MCP")
    
    @patch('src.timeline_functions.marker_functions.resolve', MockResolve())
    def test_mcp_delete_marker(self):
        args = {"frame": 200}
        
        result = mcp_delete_marker(args)
        self.assertTrue(json.loads(result))
        
        # Verify the marker was deleted
        timeline = MockResolve().GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        markers = timeline.GetMarkers()
        self.assertNotIn(200, markers)
    
    @patch('src.timeline_functions.marker_functions.resolve', MockResolve())
    def test_mcp_delete_markers_by_color(self):
        args = {"color": "Green"}
        
        result = mcp_delete_markers_by_color(args)
        data = json.loads(result)
        
        # Verify the markers were deleted
        self.assertEqual(data, 1)
        
        # Verify only Green markers were deleted
        timeline = MockResolve().GetProjectManager().GetCurrentProject().GetCurrentTimeline()
        markers = timeline.GetMarkers()
        for _, marker in markers.items():
            self.assertNotEqual(marker.color, "Green")

if __name__ == '__main__':
    unittest.main() 