#!/usr/bin/env python3
"""
Add alternating color markers every 10 seconds for 60 seconds in the current timeline
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
    print("\n===== Adding Alternating Color Markers =====\n")

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

    # Get existing markers to avoid conflicts
    existing_markers = current_timeline.GetMarkers() or {}
    print(f"Found {len(existing_markers)} existing markers")

    # Calculate frame positions for markers (every 10 seconds for 60 seconds)
    markers_to_add = []

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

    # Find a reference clip to use as starting point
    reference_clip = clips[0]
    reference_start = reference_clip.GetStart()
    print(f"Reference clip start: {reference_start}")

    # Calculate one hour in frames
    one_hour_in_frames = int(frame_rate * 60 * 60)

    # Calculate start frame at 01:00:00:00 (subtract one hour from current 02:00:00:00)
    start_frame_position = reference_start - one_hour_in_frames
    print(f"New start position (01:00:00:00): {start_frame_position}")

    # Calculate frame positions (every 10 seconds)
    frames_per_10_sec = int(frame_rate * 10)
    colors = ["Blue", "Red", "Green", "Yellow", "Purple", "Cyan"]

    # Prepare markers at 0, 10, 20, 30, 40, 50, 60 seconds (7 markers total)
    for i in range(7):
        offset_frames = i * frames_per_10_sec
        frame_position = start_frame_position + offset_frames
        color_index = i % len(colors)
        markers_to_add.append(
            {
                "frame": frame_position,
                "color": colors[color_index],
                "note": f"{i*10} seconds marker (01:00:00:00 + {i*10}s)",
            }
        )

    # Add markers
    print("\n--- Adding Markers ---")
    markers_added = 0

    for marker in markers_to_add:
        frame = marker["frame"]
        color = marker["color"]
        note = marker["note"]

        # Skip if marker already exists at this frame
        if frame in existing_markers:
            print(f"Skipping frame {frame}: Marker already exists")
            continue

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
            print("✓ Successfully added marker")
            markers_added += 1
        else:
            print("✗ Failed to add marker")

    # Get final count of markers
    final_markers = current_timeline.GetMarkers() or {}

    print(f"\nAdded {markers_added} new markers")
    print(f"Timeline now has {len(final_markers)} total markers")
    print("\n===== Completed =====")


if __name__ == "__main__":
    main()
