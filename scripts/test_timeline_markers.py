#!/usr/bin/env python3
"""
Test script for timeline marker functions in DaVinci Resolve MCP.

This script tests the marker functions against a real DaVinci Resolve instance.
It requires DaVinci Resolve to be running and the MCP server to be started.

Usage:
    python test_timeline_markers.py
"""

import os
import sys
import json
import time
import random
from pathlib import Path

# Add the parent directory to sys.path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from src.mcp.client.client import MCPClient
except ImportError as e:
    print(f"Error importing MCPClient: {e}")
    sys.exit(1)

# Available marker colors in DaVinci Resolve
MARKER_COLORS = [
    "Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", 
    "Fuchsia", "Rose", "Lavender", "Sky", "Mint", "Lemon", 
    "Sand", "Cocoa", "Cream"
]

def print_separator(text=""):
    """Print a separator line with optional text"""
    width = 80
    if text:
        text = f" {text} "
        padding = (width - len(text)) // 2
        print("=" * padding + text + "=" * padding)
    else:
        print("=" * width)

def print_markers(markers):
    """Pretty print markers"""
    if not markers or not markers.get("markers"):
        print("No markers found")
        return
    
    print(f"Found {len(markers['markers'])} markers:")
    for marker in markers["markers"]:
        print(f"  Frame: {marker['frame']}, Name: {marker['name']}, Color: {marker['color']}")
        if marker.get('note'):
            print(f"    Note: {marker['note']}")
        if marker.get('duration') and marker['duration'] > 0:
            print(f"    Duration: {marker['duration']} frames")

def test_all_marker_functions(client):
    """Test all marker functions"""
    try:
        # Test 1: Get timeline info
        print_separator("Timeline Info")
        timeline_info = client.execute_command("mcp_get_timeline_info")
        if "error" in timeline_info:
            print(f"Error getting timeline info: {timeline_info['error']}")
            return False
        
        print(f"Current timeline: {timeline_info['name']}")
        print(f"Timeline duration: {timeline_info['duration']} frames")
        print(f"Frame rate: {timeline_info['frame_rate']} fps")
        
        # Test 2: Get all markers (before adding any)
        print_separator("Initial Markers")
        initial_markers = client.execute_command("mcp_get_timeline_markers")
        if "error" in initial_markers:
            print(f"Error getting markers: {initial_markers['error']}")
            return False
        
        print_markers(initial_markers)
        initial_count = len(initial_markers.get("markers", []))
        
        # Test 3: Add markers
        print_separator("Adding Markers")
        timeline_duration = timeline_info["duration"]
        added_markers = []
        
        # Add 5 markers at random positions with random colors
        for i in range(5):
            frame = random.randint(0, timeline_duration)
            color = random.choice(MARKER_COLORS)
            name = f"Test Marker {i+1}"
            note = f"This is test marker {i+1} created by test_timeline_markers.py"
            
            print(f"Adding marker at frame {frame} with color {color}")
            result = client.execute_command("mcp_add_timeline_marker", {
                "frame": frame,
                "color": color,
                "name": name,
                "note": note,
                "duration": 10 if i % 2 == 0 else 0  # Add duration to every other marker
            })
            
            if "error" in result:
                print(f"Error adding marker: {result['error']}")
                continue
                
            print(f"  Added marker: {result['marker']['name']}")
            added_markers.append(result['marker'])
            
            # Small delay to avoid overwhelming Resolve
            time.sleep(0.5)
        
        # Test 4: Get all markers (after adding)
        print_separator("Markers After Addition")
        markers_after_add = client.execute_command("mcp_get_timeline_markers")
        if "error" in markers_after_add:
            print(f"Error getting markers: {markers_after_add['error']}")
            return False
            
        print_markers(markers_after_add)
        
        # Verify correct number of markers were added
        expected_count = initial_count + len(added_markers)
        actual_count = len(markers_after_add.get("markers", []))
        if actual_count != expected_count:
            print(f"WARNING: Expected {expected_count} markers, but found {actual_count}")
        
        # Test 5: Update a marker
        if added_markers:
            print_separator("Updating a Marker")
            marker_to_update = added_markers[0]
            original_frame = marker_to_update["frame"]
            new_color = random.choice([c for c in MARKER_COLORS if c != marker_to_update["color"]])
            new_name = f"{marker_to_update['name']} (Updated)"
            
            print(f"Updating marker at frame {original_frame}")
            print(f"  Original: {marker_to_update['name']} ({marker_to_update['color']})")
            print(f"  New: {new_name} ({new_color})")
            
            result = client.execute_command("mcp_update_marker", {
                "frame": original_frame,
                "color": new_color,
                "name": new_name,
                "note": f"This marker was updated by test_timeline_markers.py at {time.ctime()}"
            })
            
            if "error" in result:
                print(f"Error updating marker: {result['error']}")
            else:
                print(f"  Updated marker: {result['marker']['name']}")
        
        # Test 6: Delete a marker
        if len(added_markers) >= 2:
            print_separator("Deleting a Marker")
            marker_to_delete = added_markers[1]
            frame_to_delete = marker_to_delete["frame"]
            
            print(f"Deleting marker at frame {frame_to_delete}: {marker_to_delete['name']}")
            result = client.execute_command("mcp_delete_marker", {
                "frame": frame_to_delete
            })
            
            if "error" in result:
                print(f"Error deleting marker: {result['error']}")
            else:
                print(f"  Deleted marker successfully: {result['status']}")
        
        # Test 7: Delete markers by color
        if added_markers:
            print_separator("Deleting Markers by Color")
            color_to_delete = added_markers[0]["color"]
            if color_to_delete == new_color:  # If we updated the first marker
                color_to_delete = new_color
                
            print(f"Deleting all markers with color: {color_to_delete}")
            result = client.execute_command("mcp_delete_markers_by_color", {
                "color": color_to_delete
            })
            
            if "error" in result:
                print(f"Error deleting markers by color: {result['error']}")
            else:
                print(f"  Deleted {result['deleted_count']} markers with color {color_to_delete}")
        
        # Test 8: Get final markers
        print_separator("Final Markers")
        final_markers = client.execute_command("mcp_get_timeline_markers")
        if "error" in final_markers:
            print(f"Error getting markers: {final_markers['error']}")
            return False
            
        print_markers(final_markers)
        
        return True
        
    except Exception as e:
        print(f"Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function"""
    print_separator("TIMELINE MARKER FUNCTIONS TEST")
    print("This script tests the timeline marker functions with DaVinci Resolve.")
    print("Make sure DaVinci Resolve is running and has a project with a timeline open.")
    print("Also ensure the MCP server has been started.")
    print()
    
    # Connect to MCP server
    try:
        client = MCPClient()
        connected = client.connect()
        if not connected:
            print("Failed to connect to MCP server. Make sure it's running.")
            return
            
        print("Connected to MCP server successfully.")
        
        # Run tests
        success = test_all_marker_functions(client)
        
        if success:
            print_separator("TEST COMPLETED SUCCESSFULLY")
        else:
            print_separator("TEST COMPLETED WITH ERRORS")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Disconnect from server
        try:
            if 'client' in locals():
                client.disconnect()
                print("Disconnected from MCP server.")
        except:
            pass

if __name__ == "__main__":
    main() 