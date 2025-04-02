#!/usr/bin/env python3
"""
CLI utility to add a marker at a specific timecode position
Usage: ./add_timecode_marker.py <timecode> [color] [note]
Example: ./add_timecode_marker.py 01:00:15:00 Red "My marker note"
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


def add_marker(timecode, color="Blue", note=""):
    """Add a marker at the specified timecode"""
    print(f"Attempting to add {color} marker at {timecode} with note: {note}")

    # Connect to Resolve
    resolve = dvr_script.scriptapp("Resolve")
    if not resolve:
        print("Error: Failed to connect to DaVinci Resolve")
        return False

    print(f"Connected to: {resolve.GetProductName()} {resolve.GetVersionString()}")

    # Get project manager
    project_manager = resolve.GetProjectManager()
    current_project = project_manager.GetCurrentProject()

    if not current_project:
        print("Error: No project currently open")
        return False

    # Get current timeline
    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        print("Error: No timeline currently active")
        return False

    timeline_name = current_timeline.GetName()
    print(f"Timeline: {timeline_name}")

    # Get frame rate
    fps = float(current_timeline.GetSetting("timelineFrameRate"))
    print(f"Frame rate: {fps} fps")

    # Get timeline start timecode
    start_tc = current_timeline.GetStartTimecode()
    if not start_tc:
        start_tc = "01:00:00:00"  # Default

    print(f"Timeline start timecode: {start_tc}")

    # Convert input timecode to frame number
    frame = tc_to_frame(timecode, fps)
    print(f"Converted {timecode} to frame: {frame}")

    # Validate color
    valid_colors = [
        "Blue",
        "Cyan",
        "Green",
        "Yellow",
        "Red",
        "Pink",
        "Purple",
        "Fuchsia",
        "Rose",
        "Lavender",
        "Sky",
        "Mint",
        "Lemon",
        "Sand",
        "Cocoa",
        "Cream",
    ]

    if color not in valid_colors:
        print(f"Warning: Invalid color '{color}'. Using Blue instead.")
        color = "Blue"

    # Get clips to check if frame is valid
    clips = []
    for track_idx in range(1, 5):  # Check first 4 video tracks
        try:
            track_clips = current_timeline.GetItemListInTrack("video", track_idx)
            if track_clips and len(track_clips) > 0:
                clips.extend(track_clips)
        except:
            continue

    # Check if frame is within a clip
    frame_in_clip = False
    for clip in clips:
        if clip.GetStart() <= frame <= clip.GetEnd():
            frame_in_clip = True
            clip_name = clip.GetName()
            print(f"Frame {frame} is within clip: {clip_name}")
            break

    if not frame_in_clip:
        print(
            f"Warning: Frame {frame} is not within any clip. Marker may not appear correctly."
        )

    # Add the marker
    print(f"Adding marker: Frame={frame}, Color={color}, Note='{note}'")
    result = current_timeline.AddMarker(frame, color, note or "Marker", note, 1, "")

    if result:
        print(f"✓ Successfully added {color} marker at {timecode} (frame {frame})")
        return True
    else:
        print(f"✗ Failed to add marker at {timecode} (frame {frame})")

        # Check if a marker already exists at this frame
        markers = current_timeline.GetMarkers() or {}
        if frame in markers:
            print(f"A marker already exists at frame {frame}.")
            # Try alternate position
            alt_frame = frame + 1
            print(
                f"Trying alternate position: frame {alt_frame} ({frame_to_tc(alt_frame, fps)})"
            )

            alt_result = current_timeline.AddMarker(
                alt_frame, color, note or "Marker", note, 1, ""
            )

            if alt_result:
                print(
                    f"✓ Successfully added {color} marker at alternate position: {frame_to_tc(alt_frame, fps)} (frame {alt_frame})"
                )
                return True

        return False


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Add a marker at a specific timecode position"
    )
    parser.add_argument("timecode", help="Timecode position (HH:MM:SS:FF)")
    parser.add_argument("color", nargs="?", default="Blue", help="Marker color")
    parser.add_argument("note", nargs="?", default="", help="Marker note")

    args = parser.parse_args()

    # Validate timecode format
    if not args.timecode or len(args.timecode.split(":")) != 4:
        print("Error: Invalid timecode format. Use HH:MM:SS:FF format.")
        return

    # Add the marker
    success = add_marker(args.timecode, args.color, args.note)

    print(f"\nMarker {'added successfully' if success else 'addition failed'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <timecode> [color] [note]")
        print(f'Example: {sys.argv[0]} 01:00:15:00 Red "My marker note"')
        sys.exit(1)

    main()
