#!/usr/bin/env python3
"""
Add markers at regular intervals using proper timecode conversion
This script adds markers at specified intervals starting from a given timecode
"""

import os
import sys
import argparse

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


def tc_to_frame(tc_str, fps):
    """Convert timecode string to frame number"""
    if not tc_str:
        return 0

    # Handle timecode format "HH:MM:SS:FF"
    parts = tc_str.split(":")
    if len(parts) != 4:
        return 0

    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    frames = int(parts[3])

    total_frames = int(round((hours * 3600 + minutes * 60 + seconds) * fps + frames))

    return total_frames


def frame_to_tc(frame, fps):
    """Convert frame number to timecode string"""
    total_seconds = frame / fps
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    frames = int((total_seconds - int(total_seconds)) * fps)

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def add_markers(
    start_tc="01:00:00:00", interval_seconds=10, count=7, clear_existing=True
):
    """Add markers at regular intervals"""
    print(
        f"\n===== ADDING {count} MARKERS AT {interval_seconds}-SECOND INTERVALS =====\n"
    )
    print(f"Starting at: {start_tc}")

    # Connect to Resolve
    resolve = dvr_script.scriptapp("Resolve")
    if not resolve:
        print("Error: Failed to connect to DaVinci Resolve")
        return

    print(f"Connected to: {resolve.GetProductName()} {resolve.GetVersionString()}")

    # Get project manager
    project_manager = resolve.GetProjectManager()
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
    print(f"Timeline: {timeline_name}")

    # Get frame rate
    fps = float(current_timeline.GetSetting("timelineFrameRate"))
    print(f"Frame rate: {fps} fps")

    # Get timeline start timecode
    timeline_start_tc = current_timeline.GetStartTimecode()
    if not timeline_start_tc:
        timeline_start_tc = "01:00:00:00"  # Default

    print(f"Timeline start timecode: {timeline_start_tc}")

    # Clear existing markers if requested
    if clear_existing:
        existing_markers = current_timeline.GetMarkers() or {}
        print(f"Clearing {len(existing_markers)} existing markers")

        for frame in existing_markers:
            current_timeline.DeleteMarkerAtFrame(frame)

    # Get clips to check if frames are valid
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

    # Convert start timecode to frame
    start_frame = tc_to_frame(start_tc, fps)
    print(f"Start position: {start_tc} (frame {start_frame})")

    # Define colors
    colors = ["Blue", "Red", "Green", "Yellow", "Purple", "Cyan", "Pink"]

    # Calculate interval in frames
    interval_frames = int(interval_seconds * fps)
    print(f"Interval: {interval_seconds} seconds ({interval_frames} frames)")

    # Add markers
    print("\n--- Adding Markers ---")
    markers_added = 0

    for i in range(count):
        # Calculate frame position
        frame = start_frame + (i * interval_frames)
        target_tc = frame_to_tc(frame, fps)

        # Validate frame is within a clip
        frame_in_clip = False
        clip_name = ""
        for clip in clips:
            if clip.GetStart() <= frame <= clip.GetEnd():
                frame_in_clip = True
                clip_name = clip.GetName()
                break

        if not frame_in_clip:
            print(f"Skipping position {target_tc} (frame {frame}): Not within any clip")
            continue

        # Select color
        color_index = i % len(colors)
        color = colors[color_index]

        # Create marker note
        note = f"Marker {i+1}: {interval_seconds*i} seconds from start"

        print(
            f"Adding {color} marker at {target_tc} (frame {frame}) in clip: {clip_name}"
        )
        result = current_timeline.AddMarker(frame, color, note, note, 1, "")

        if result:
            print(f"✓ Successfully added marker")
            markers_added += 1
        else:
            print(f"✗ Failed to add marker - checking if position already has a marker")

            # Check if a marker already exists
            markers = current_timeline.GetMarkers() or {}
            if frame in markers:
                # Try alternate position
                alt_frame = frame + 1
                alt_tc = frame_to_tc(alt_frame, fps)
                print(f"Trying alternate position: {alt_tc} (frame {alt_frame})")

                alt_result = current_timeline.AddMarker(
                    alt_frame, color, note, note, 1, ""
                )

                if alt_result:
                    print(f"✓ Successfully added marker at alternate position")
                    markers_added += 1

    # Get final count of markers
    final_markers = current_timeline.GetMarkers() or {}

    print(f"\nAdded {markers_added} new markers")
    print(f"Timeline now has {len(final_markers)} total markers")
    print("\n===== COMPLETED =====")


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Add markers at regular intervals")
    parser.add_argument(
        "--start", "-s", default="01:00:00:00", help="Start timecode (HH:MM:SS:FF)"
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=10,
        help="Interval in seconds between markers",
    )
    parser.add_argument(
        "--count", "-c", type=int, default=7, help="Number of markers to add"
    )
    parser.add_argument(
        "--keep", "-k", action="store_true", help="Keep existing markers (don't clear)"
    )

    args = parser.parse_args()

    # Validate timecode format
    if len(args.start.split(":")) != 4:
        print("Error: Invalid start timecode format. Use HH:MM:SS:FF format.")
        return

    # Add the markers
    add_markers(args.start, args.interval, args.count, not args.keep)


if __name__ == "__main__":
    main()
