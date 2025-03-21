#!/usr/bin/env python
"""
Test script for DaVinci Resolve Playback and Clip Selection Functions

This script tests the following functions:
- mcp_control_playback
- mcp_get_selected_clips
- mcp_get_playhead_position

These functions handle timeline playback control and clip selection retrieval.
"""

import sys
import os
import time
from typing import Dict, Any, Optional, List

# Add the src directory to the Python path
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.append(src_dir)

# Import the functions to test
try:
    from src.resolve_mcp import (
        resolve,
        mcp_control_playback,
        mcp_get_selected_clips,
        mcp_get_playhead_position,
        get_current_project,
        get_current_timeline,
        get_project_manager,
        get_media_pool
    )
except ImportError:
    try:
        from resolve_mcp import (
            resolve,
            mcp_control_playback,
            mcp_get_selected_clips, 
            mcp_get_playhead_position,
            get_current_project,
            get_current_timeline,
            get_project_manager,
            get_media_pool
        )
    except ImportError as e:
        print(f"Error importing timeline functions: {e}")
        sys.exit(1)

def print_result(function_name: str, result: Dict[str, Any]) -> None:
    """Print the result of a function call in a formatted way"""
    print("\n" + "=" * 70)
    print(f"FUNCTION: {function_name}")
    print("-" * 70)
    
    if "error" in result:
        print(f"ERROR: {result['error']}")
        
        # Print debug info if available
        if "debug_info" in result:
            print("\nDEBUG INFO:")
            for key, value in result["debug_info"].items():
                print(f"  {key}: {value}")
    elif "status" in result and result["status"] == "success":
        print(f"SUCCESS: {result.get('message', 'Operation completed successfully')}")
        
        # Print additional information if available
        if "timecode" in result:
            print(f"\nTimecode: {result['timecode']}")
            print(f"Frame Position: {result['frame_position']}")
        elif "selected_clips" in result:
            print(f"\nSelected Clips ({result.get('count', 0)}):")
            clips = result.get("selected_clips", [])
            if not clips:
                print("  No clips selected")
            else:
                for i, clip in enumerate(clips):
                    print(f"  Clip {i+1}:")
                    for key, value in clip.items():
                        print(f"    {key}: {value}")
    else:
        print("RESULT:")
        for key, value in result.items():
            print(f"  {key}: {value}")
    
    print("=" * 70)

def debug_helper_functions():
    """Print debug information about the helper functions"""
    print("\n" + "=" * 70)
    print("DEBUGGING HELPER FUNCTIONS")
    print("-" * 70)
    
    print(f"resolve: {resolve}")
    print(f"type(resolve): {type(resolve)}")
    
    project_manager = get_project_manager()
    print(f"project_manager: {project_manager}")
    print(f"type(project_manager): {type(project_manager)}")
    
    current_project = get_current_project()
    print(f"current_project: {current_project}")
    print(f"type(current_project): {type(current_project)}")
    
    if current_project:
        print("\nProject Methods Available:")
        for method in dir(current_project):
            if not method.startswith("_"):
                print(f"  - {method}")
    
    current_timeline = get_current_timeline()
    print(f"current_timeline: {current_timeline}")
    print(f"type(current_timeline): {type(current_timeline)}")
    
    if current_timeline:
        print("\nTimeline Methods Available:")
        for method in dir(current_timeline):
            if not method.startswith("_"):
                print(f"  - {method}")
    
    print("=" * 70)

def test_playback_control(command: str) -> None:
    """Test the playback control function with a specific command"""
    print(f"\nTESTING PLAYBACK CONTROL: {command}")
    
    # Execute the command
    result = mcp_control_playback(command)
    print_result(f"mcp_control_playback({command})", result)
    
    # Give some time for the command to take effect
    time.sleep(1)
    
    # Get the current playhead position to verify
    position_result = mcp_get_playhead_position()
    print_result("mcp_get_playhead_position()", position_result)

def test_get_selected_clips() -> None:
    """Test the get selected clips function"""
    print("\nTESTING GET SELECTED CLIPS")
    
    # Get selected clips
    result = mcp_get_selected_clips()
    print_result("mcp_get_selected_clips()", result)
    
    # Provide feedback to the user
    if "selected_clips" in result and not result["selected_clips"]:
        print("\nNOTE: No clips are currently selected. Please select some clips in the timeline and run this test again.")

def run_tests():
    """Run tests for the playback and clip selection functions"""
    # Check if DaVinci Resolve is running
    if not resolve:
        print("ERROR: DaVinci Resolve is not running. Please start DaVinci Resolve and try again.")
        sys.exit(1)
    
    print("DaVinci Resolve is running. Starting tests...\n")
    
    # Debug helper functions first
    debug_helper_functions()
    
    # Test 1: Get playhead position
    print("TEST 1: Get playhead position")
    playhead_result = mcp_get_playhead_position()
    print_result("mcp_get_playhead_position()", playhead_result)
    
    # Test 2: Control playback - play
    test_playback_control("play")
    
    # Test 3: Control playback - pause
    test_playback_control("pause")
    
    # Test 4: Control playback - stop
    test_playback_control("stop")
    
    # Test 5: Control playback - next_frame
    test_playback_control("next_frame")
    
    # Test 6: Control playback - prev_frame
    test_playback_control("prev_frame")
    
    # Test 7: Get selected clips
    test_get_selected_clips()
    
    print("\nAll tests completed. Please manually verify that the playback controls worked as expected.")
    print("\nNOTE: To properly test clip selection, please select some clips in the timeline and run this test again.")

if __name__ == "__main__":
    run_tests() 