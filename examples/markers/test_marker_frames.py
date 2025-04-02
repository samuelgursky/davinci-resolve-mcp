#!/usr/bin/env python3
"""
Test Marker Frame Placement Script

This script demonstrates and tests the enhanced marker functionality in DaVinci Resolve.
It adds markers at different frame positions, including automatic frame selection,
to validate the marker functionality works correctly with various inputs.

Example Usage:
    python test_marker_frames.py

The script will:
1. Connect to DaVinci Resolve
2. Test adding markers at different frame positions
3. Include automatic frame selection when no frame is specified
4. Output the results of each marker operation
"""

import os
import sys
import time

# Add the project root to the Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "../.."))
sys.path.append(project_root)

# Set environment variables for DaVinci Resolve scripting
RESOLVE_API_PATH = (
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
)
RESOLVE_LIB_PATH = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
RESOLVE_MODULES_PATH = os.path.join(RESOLVE_API_PATH, "Modules")

os.environ["RESOLVE_SCRIPT_API"] = RESOLVE_API_PATH
os.environ["RESOLVE_SCRIPT_LIB"] = RESOLVE_LIB_PATH
sys.path.append(RESOLVE_MODULES_PATH)

# Import the timeline_operations module from the project
from src.api.timeline_operations import add_marker

# Import DaVinci Resolve scripting
import DaVinciResolveScript as dvr_script


def main():
    """Main function to test marker placement at different frames."""
    # Connect to Resolve
    resolve = dvr_script.scriptapp("Resolve")
    if not resolve:
        print("Error: Could not connect to DaVinci Resolve")
        sys.exit(1)

    print(f"Connected to {resolve.GetProductName()} {resolve.GetVersionString()}")
    print("Testing marker placement at different frames...")

    # Display current timeline information
    project_manager = resolve.GetProjectManager()
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        print("Error: No project is currently open")
        sys.exit(1)

    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        print("Error: No timeline is currently open")
        sys.exit(1)

    print(f"Current timeline: {current_timeline.GetName()}")
    print(f"Timeline duration: {current_timeline.GetEndFrame()} frames")

    # Test with different frames
    # None = auto-selected frame, others are specific frame positions
    test_frames = [None, 86450, 87000, 88000, 89000, 90000]

    for frame in test_frames:
        note = f"Test marker at {'auto-selected' if frame is None else frame}"
        color = "Green" if frame is None else "Blue"

        print(
            f"\nAttempting to add {color} marker at frame={frame or 'auto'} with note: '{note}'"
        )
        result = add_marker(resolve, frame, color, note)
        print(f"Result: {result}")

        # Small delay between operations
        time.sleep(0.5)

    print("\nMarker testing completed successfully!")


if __name__ == "__main__":
    main()
