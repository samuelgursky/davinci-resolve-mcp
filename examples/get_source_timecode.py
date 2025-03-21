#!/usr/bin/env python3
"""
Example script to get source timecode information from the first three clips in the timeline.
"""

import sys
import os
import json

# Add the project directory to the sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
sys.path.append(project_dir)

try:
    # Import the timecode functions
    from src.timecode_functions.source_timecode import (
        get_resolve_instance,
        get_current_timeline,
        get_clip_source_timecode,
        mcp_get_clip_source_timecode
    )
except ImportError as e:
    print(f"Error importing timecode functions: {e}")
    sys.exit(1)

def main():
    """Main function that retrieves source timecode for first 3 clips"""
    print("DaVinci Resolve Source Timecode Example")
    print("---------------------------------------")
    
    # Check if DaVinci Resolve is running
    resolve = get_resolve_instance()
    if not resolve:
        print("Error: DaVinci Resolve is not running.")
        return
    
    # Check if a timeline is open
    timeline = get_current_timeline()
    if not timeline:
        print("Error: No timeline is currently open in DaVinci Resolve.")
        return
    
    print(f"Current timeline: {timeline.GetName()}")
    print()
    
    # Get the first three clips from the first video track
    print("First three clips in video track 1:")
    print()
    
    for i in range(3):
        print(f"Clip {i+1}:")
        try:
            result = mcp_get_clip_source_timecode("video", 1, i)
            print(json.dumps(result, indent=2))
        except Exception as e:
            print(f"  Error getting clip {i}: {str(e)}")
        print()

if __name__ == "__main__":
    main() 