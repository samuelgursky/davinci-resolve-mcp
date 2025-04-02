#!/usr/bin/env python3
"""
Clear existing markers and add new alternating color markers at visible timeline positions
"""

import os
import sys

# Set environment variables for DaVinci Resolve scripting
RESOLVE_API_PATH = (
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
)
RESOLVE_LIB_PATH = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
RESOLVE_MODULES_PATH = os.path.join(RESOLVE_API_PATH, "Modules")

os.environ["RESOLVE_SCRIPT_API"] = RESOLVE_API_PATH
os.environ["RESOLVE_SCRIPT_LIB"] = RESOLVE_LIB_PATH
sys.path.append(RESOLVE_MODULES_PATH)

# Import DaVinci Resolve scripting
import DaVinciResolveScript as dvr_script


def main():
    print("\n===== Clearing and Adding New Markers =====\n")

    # Connect to Resolve
    resolve = dvr_script.scriptapp("Resolve")
    if not resolve:
        print("Error: Failed to connect to DaVinci Resolve")
        return

    print(f"Connected to: {resolve.GetProductName()} {resolve.GetVersionString()}")

    # Get project manager
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        print("Error: Failed to get Project Manager")
        return

    # Get current project
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        print("Error: No project currently open")
        return

    print(f"Current project: {current_project.GetName()}")

    # Get current timeline
    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        print("Error: No timeline currently active")
        return

    timeline_name = current_timeline.GetName()
    print(f"Current timeline: {timeline_name}")

    # Get timeline frame rate
    try:
        frame_rate = float(current_timeline.GetSetting("timelineFrameRate"))
        print(f"Timeline frame rate: {frame_rate} fps")
    except Exception as e:
        print(f"Error getting frame rate: {str(e)}")
        frame_rate = 24.0  # Default to 24 fps
        print(f"Using default frame rate: {frame_rate} fps")

    # Get timeline frame range
    start_frame = current_timeline.GetStartFrame()
    end_frame = current_timeline.GetEndFrame()
    print(f"Timeline frame range: {start_frame} to {end_frame}")

    # Clear existing markers
    existing_markers = current_timeline.GetMarkers() or {}
    print(f"Found {len(existing_markers)} existing markers to clear")

    if existing_markers:
        for frame in existing_markers:
            current_timeline.DeleteMarkerAtFrame(frame)
        print("All existing markers cleared")

    # Get clips to ensure we're adding markers on actual clips
    clips = []
    for track_idx in range(1, 5):  # Check first 4 video tracks
        try:
            track_clips = current_timeline.GetItemListInTrack("video", track_idx)
            if track_clips and len(track_clips) > 0:
                clips.extend(track_clips)
        except:
            continue

    if not clips:
        print("Error: No clips found in timeline")
        return

    # Define exact positions visible in the timeline for markers
    # Based on the screenshot where the playhead is at 01:00:00:00
    # We'll add markers at consistent intervals within the visible clips

    print("\n--- Adding Markers at Specific Positions ---")

    # Define the marker positions based on the visible clips
    colors = ["Blue", "Red", "Green", "Yellow", "Purple", "Cyan"]
    marker_positions = []

    # Add positions for the first clip (approximately first half of timeline)
    first_clip_start = 86400  # 01:00:00:00

    # Add markers at specific positions in 10-second intervals
    for i in range(6):  # Add 6 markers in the 60-second span
        frame = first_clip_start + (i * int(frame_rate * 10))  # Every 10 seconds
        color_index = i % len(colors)
        marker_positions.append(
            {
                "frame": frame,
                "color": colors[color_index],
                "note": f"Marker {i+1}: {i*10} seconds",
            }
        )

    # Add a few markers in the other clips visible in the timeline
    second_clip_start = 87351  # Start of DaVinciResolveMCP-01_v04.mov
    third_clip_start = 88446  # Start of DaVinciResolveMCP-01_v02.mov
    fourth_clip_start = 89469  # Start of DaVinciResolveMCP-01_v03.mov

    # Add one marker in each clip
    additional_markers = [
        {"frame": second_clip_start + 240, "color": "Red", "note": "Clip 2 marker"},
        {"frame": third_clip_start + 240, "color": "Green", "note": "Clip 3 marker"},
        {"frame": fourth_clip_start + 240, "color": "Purple", "note": "Clip 4 marker"},
    ]

    marker_positions.extend(additional_markers)

    # Add markers
    markers_added = 0

    for marker in marker_positions:
        frame = marker["frame"]
        color = marker["color"]
        note = marker["note"]

        # Verify the frame is within a clip
        frame_in_clip = False
        for clip in clips:
            if clip.GetStart() <= frame <= clip.GetEnd():
                frame_in_clip = True
                break

        if not frame_in_clip:
            print(f"Skipping frame {frame}: Not within a clip")
            continue

        # Add the marker
        print(f"Adding {color} marker at frame {frame} ({note})")
        result = current_timeline.AddMarker(frame, color, note, note, 1, "")

        if result:
            print(f"✓ Successfully added marker")
            markers_added += 1
        else:
            print(f"✗ Failed to add marker")

    # Get final count of markers
    final_markers = current_timeline.GetMarkers() or {}

    print(f"\nAdded {markers_added} new markers")
    print(f"Timeline now has {len(final_markers)} total markers")
    print("\n===== Completed =====")


if __name__ == "__main__":
    main()
