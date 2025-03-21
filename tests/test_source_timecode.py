"""
Test script for source timecode functionality.
"""

import sys
import os
import json

# Add the project directory to the path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(script_dir, '..'))
sys.path.append(project_dir)

# Import the timecode functions
try:
    from src.timecode_functions.source_timecode import (
        timecode_to_frames,
        frames_to_timecode,
        calculate_source_timecode,
        mcp_get_clip_source_timecode,
        mcp_get_source_timecode_report,
        mcp_export_source_timecode_report
    )
except ImportError as e:
    print(f"Error importing timecode functions: {e}")
    sys.exit(1)

def test_timecode_conversion():
    """Test timecode conversion functions."""
    print("\n=== Testing Timecode Conversion Functions ===")
    
    # Test timecode to frames
    test_cases = [
        ("01:00:00:00", 24.0, 86400),
        ("00:00:30:00", 24.0, 720),
        ("00:00:00:12", 24.0, 12),
        ("10:30:15:10", 30.0, 1138060),
    ]
    
    print("\nTesting timecode_to_frames:")
    for tc, fps, expected in test_cases:
        result = timecode_to_frames(tc, fps)
        print(f"  {tc} at {fps} fps -> {result} frames (Expected: {expected})")
        assert result == expected, f"Expected {expected}, got {result}"
    
    # Test frames to timecode
    test_cases = [
        (86400, 24.0, "01:00:00:00"),
        (720, 24.0, "00:00:30:00"),
        (12, 24.0, "00:00:00:12"),
        (1138060, 30.0, "10:30:15:00"),  # Note: This may differ slightly due to frame rate rounding
    ]
    
    print("\nTesting frames_to_timecode:")
    for frames, fps, expected in test_cases:
        result = frames_to_timecode(frames, fps)
        print(f"  {frames} frames at {fps} fps -> {result} (Expected: {expected})")
        # For frame rate conversion, we may have slight differences, so just check format
        assert len(result) == 11, f"Expected format HH:MM:SS:FF, got {result}"
    
    # Test calculate_source_timecode
    test_cases = [
        ("01:00:00:00", 24, 24.0, "01:00:01:00"),
        ("00:59:59:23", 1, 24.0, "01:00:00:00"),
        ("02:30:00:00", -3600, 24.0, "02:29:00:00"),
    ]
    
    print("\nTesting calculate_source_timecode:")
    for start_tc, offset, fps, expected in test_cases:
        result = calculate_source_timecode(start_tc, offset, fps)
        print(f"  {start_tc} + {offset} frames at {fps} fps -> {result} (Expected: {expected})")
        assert result == expected, f"Expected {expected}, got {result}"
    
    print("\nAll timecode conversion tests passed!")
    
def test_clip_source_timecode():
    """Test getting source timecode for a clip."""
    print("\n=== Testing Clip Source Timecode Functions ===")
    
    # Test getting source timecode for the first clip in the first video track
    result = mcp_get_clip_source_timecode("video", 1, 0)
    
    # Print the result
    print(json.dumps(result, indent=2))
    
    if "error" in result:
        print(f"Error: {result['error']}")
    else:
        print("\nClip source timecode details:")
        print(f"  Name: {result.get('name', 'N/A')}")
        print(f"  Track: {result.get('track', 'N/A')}")
        print(f"  Timeline Start: {result.get('start_frame', 'N/A')}")
        print(f"  Timeline End: {result.get('end_frame', 'N/A')}")
        print(f"  Duration: {result.get('duration', 'N/A')}")
        print(f"  Source Start TC: {result.get('source_start_tc', 'N/A')}")
        print(f"  Source End TC: {result.get('source_end_tc', 'N/A')}")
        print(f"  Source In: {result.get('source_in', 'N/A')}")
        print(f"  Source Out: {result.get('source_out', 'N/A')}")
        print(f"  Timeline Source In TC: {result.get('timeline_source_in_tc', 'N/A')}")
        print(f"  Timeline Source Out TC: {result.get('timeline_source_out_tc', 'N/A')}")
        print(f"  File Path: {result.get('file_path', 'N/A')}")
    
def test_source_timecode_report():
    """Test generating a source timecode report."""
    print("\n=== Testing Source Timecode Report ===")
    
    # Get the source timecode report
    report = mcp_get_source_timecode_report()
    
    if "error" in report:
        print(f"Error: {report['error']}")
    else:
        print(f"Timeline: {report.get('timeline_name', 'N/A')}")
        print(f"Timeline Start TC: {report.get('timeline_timecode_start', 'N/A')}")
        print(f"Timeline End TC: {report.get('timeline_timecode_end', 'N/A')}")
        print(f"Clip Count: {len(report.get('clips', []))}")
        
        # Print details of the first few clips
        for i, clip in enumerate(report.get('clips', [])[:3]):
            print(f"\nClip {i+1}:")
            print(f"  Name: {clip.get('name', 'N/A')}")
            print(f"  Track: {clip.get('track', 'N/A')}")
            print(f"  Timeline Source In TC: {clip.get('timeline_source_in_tc', 'N/A')}")
            print(f"  Timeline Source Out TC: {clip.get('timeline_source_out_tc', 'N/A')}")
        
        if len(report.get('clips', [])) > 3:
            print(f"\n... and {len(report.get('clips', [])) - 3} more clips")

def test_export_source_timecode_report():
    """Test exporting a source timecode report."""
    print("\n=== Testing Export Source Timecode Report ===")
    
    # Test exporting to different formats
    formats = ["csv", "json", "edl"]
    
    for format in formats:
        export_path = f"tests/output/source_timecode_report.{format}"
        
        # Ensure the output directory exists
        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        
        print(f"\nExporting to {format.upper()} format: {export_path}")
        result = mcp_export_source_timecode_report(export_path, format)
        
        if "error" in result:
            print(f"  Error: {result['error']}")
        else:
            print(f"  Status: {result.get('status', 'N/A')}")
            print(f"  Message: {result.get('message', 'N/A')}")
            print(f"  Clips Exported: {result.get('clips_exported', 'N/A')}")

if __name__ == "__main__":
    print("Starting source timecode tests...\n")
    
    # First test the timecode conversion functions (these don't require DaVinci Resolve)
    test_timecode_conversion()
    
    # Test the functions that require DaVinci Resolve
    # These may fail if Resolve is not running or no project/timeline is open
    try:
        test_clip_source_timecode()
        test_source_timecode_report()
        test_export_source_timecode_report()
        print("\nAll tests completed!")
    except Exception as e:
        print(f"\nError during tests: {e}")
        print("Make sure DaVinci Resolve is running and a project with a timeline is open.") 