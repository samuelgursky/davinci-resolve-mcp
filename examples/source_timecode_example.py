#!/usr/bin/env python3
"""
Source Timecode Functions Example Script

This script demonstrates how to use the source timecode functions
in the DaVinci Resolve MCP.

Requirements:
- DaVinci Resolve must be running
- A project must be open with a timeline containing clips
"""

import os
import sys
import json
import time
from datetime import datetime

# Add the project directory to the path to allow importing the modules
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
sys.path.append(project_dir)

try:
    # Import the timecode functions
    from src.timecode_functions.source_timecode import (
        mcp_get_clip_source_timecode,
        mcp_get_source_timecode_report,
        mcp_export_source_timecode_report,
        get_current_timeline,
        timecode_to_frames,
        frames_to_timecode,
        calculate_source_timecode
    )
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

def print_separator(title=None):
    """Print a separator line with an optional title."""
    width = 80
    if title:
        print(f"\n{'-' * 5} {title} {'-' * (width - 7 - len(title))}")
    else:
        print("\n" + "-" * width)

def pretty_print_json(data):
    """Print JSON data in a pretty format."""
    print(json.dumps(data, indent=2))

def example_timecode_conversions():
    """Demonstrate timecode conversion utilities."""
    print_separator("TIMECODE CONVERSION EXAMPLES")
    
    # Example 1: Convert timecode to frames
    timecode = "01:00:30:15"
    fps = 24.0
    frames = timecode_to_frames(timecode, fps)
    print(f"Timecode {timecode} at {fps} fps = {frames} frames")
    
    # Example 2: Convert frames to timecode
    frame_count = 86415
    fps = 24.0
    tc = frames_to_timecode(frame_count, fps)
    print(f"{frame_count} frames at {fps} fps = {tc}")
    
    # Example 3: Calculate new timecode by adding frames
    start_tc = "00:30:00:00"
    offset_frames = 1200
    fps = 24.0
    new_tc = calculate_source_timecode(start_tc, offset_frames, fps)
    print(f"{start_tc} + {offset_frames} frames at {fps} fps = {new_tc}")

def example_get_clip_source_timecode():
    """Demonstrate getting source timecode for a specific clip."""
    print_separator("GET CLIP SOURCE TIMECODE EXAMPLE")
    
    # Check if a timeline is open
    timeline = get_current_timeline()
    if not timeline:
        print("No timeline is open. Please open a timeline with clips.")
        return
    
    print(f"Current timeline: {timeline.GetName()}")
    
    # Get source timecode for a clip - try video track 1, first clip (index 0)
    track_type = "video"
    track_index = 1
    clip_index = 0
    
    # Get the source timecode data
    result = mcp_get_clip_source_timecode(track_type, track_index, clip_index)
    
    if "error" in result:
        print(f"Error: {result['error']}")
        return
    
    print(f"Source timecode for {track_type.capitalize()} Track {track_index}, Clip {clip_index + 1} ({result.get('name', 'Unknown')}):")
    pretty_print_json(result)

def example_get_source_timecode_report():
    """Demonstrate generating a source timecode report for all clips."""
    print_separator("GET SOURCE TIMECODE REPORT EXAMPLE")
    
    # Get source timecode report for all clips in the timeline
    report = mcp_get_source_timecode_report()
    
    if "error" in report:
        print(f"Error: {report['error']}")
        return
    
    print(f"Timeline: {report['timeline_name']}")
    print(f"Total clips: {len(report['clips'])}")
    
    # Show the first 3 clips only to avoid overwhelming output
    print(f"First 3 clips:")
    for i, clip in enumerate(report['clips'][:3]):
        print(f"\nClip {i+1}:")
        pretty_print_json(clip)
    
    if len(report['clips']) > 3:
        print(f"\n... and {len(report['clips']) - 3} more clips")

def example_export_source_timecode_report():
    """Demonstrate exporting a source timecode report to different formats."""
    print_separator("EXPORT SOURCE TIMECODE REPORT EXAMPLES")
    
    # Create a directory for the exports if it doesn't exist
    exports_dir = os.path.join(script_dir, "exports")
    os.makedirs(exports_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Example 1: Export as CSV
    csv_path = os.path.join(exports_dir, f"source_timecode_report_{timestamp}.csv")
    csv_result = mcp_export_source_timecode_report(csv_path, "csv", False)
    
    if "error" in csv_result:
        print(f"CSV Export Error: {csv_result['error']}")
    else:
        print(f"CSV Export successful: {csv_path}")
    
    # Example 2: Export as JSON
    json_path = os.path.join(exports_dir, f"source_timecode_report_{timestamp}.json")
    json_result = mcp_export_source_timecode_report(json_path, "json", False)
    
    if "error" in json_result:
        print(f"JSON Export Error: {json_result['error']}")
    else:
        print(f"JSON Export successful: {json_path}")
    
    # Example 3: Export as EDL
    edl_path = os.path.join(exports_dir, f"source_timecode_report_{timestamp}.edl")
    edl_result = mcp_export_source_timecode_report(edl_path, "edl", True)  # Video tracks only for EDL
    
    if "error" in edl_result:
        print(f"EDL Export Error: {edl_result['error']}")
    else:
        print(f"EDL Export successful: {edl_path}")

def main():
    print("DaVinci Resolve Source Timecode Functions Example")
    print("================================================")
    
    # Example 1: Timecode conversion utilities
    example_timecode_conversions()
    
    # Wait a bit before trying to interact with Resolve
    print("\nConnecting to DaVinci Resolve...\n")
    time.sleep(1)
    
    # Check if we can access DaVinci Resolve
    timeline = get_current_timeline()
    if not timeline:
        print("Could not access DaVinci Resolve timeline.")
        print("Make sure DaVinci Resolve is running and a project with a timeline is open.")
        return
    
    # Example 2: Get source timecode for a specific clip
    example_get_clip_source_timecode()
    
    # Example 3: Generate source timecode report
    example_get_source_timecode_report()
    
    # Example 4: Export source timecode report
    example_export_source_timecode_report()

if __name__ == "__main__":
    main() 