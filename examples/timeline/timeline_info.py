#!/usr/bin/env python3
"""
Get detailed timeline information from DaVinci Resolve
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
    print("\n===== Timeline Information =====\n")

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
        frame_rate = 24.0

    # Get timeline information
    start_frame = current_timeline.GetStartFrame()
    end_frame = current_timeline.GetEndFrame()

    print(f"Timeline frame range: {start_frame} to {end_frame}")

    # Calculate timecode equivalent of the frame range
    hours_start = start_frame // (frame_rate * 60 * 60)
    minutes_start = (start_frame % (frame_rate * 60 * 60)) // (frame_rate * 60)
    seconds_start = (start_frame % (frame_rate * 60)) // frame_rate
    frames_start = start_frame % frame_rate

    hours_end = end_frame // (frame_rate * 60 * 60)
    minutes_end = (end_frame % (frame_rate * 60 * 60)) // (frame_rate * 60)
    seconds_end = (end_frame % (frame_rate * 60)) // frame_rate
    frames_end = end_frame % frame_rate

    start_tc = f"{int(hours_start):02d}:{int(minutes_start):02d}:{int(seconds_start):02d}:{int(frames_start):02d}"
    end_tc = f"{int(hours_end):02d}:{int(minutes_end):02d}:{int(seconds_end):02d}:{int(frames_end):02d}"

    print(f"Timeline approx. timecode range: {start_tc} to {end_tc}")

    # Calculate various time positions
    one_hour_frames = int(frame_rate * 60 * 60)
    print("\nTime calculations:")
    print(f"One hour in frames: {one_hour_frames}")
    print(f"01:00:00:00 would be frame: {one_hour_frames}")
    print(f"02:00:00:00 would be frame: {one_hour_frames * 2}")

    # Get clips in timeline
    clips = []
    for track_idx in range(1, 5):  # Check first 4 video tracks
        try:
            track_clips = current_timeline.GetItemListInTrack("video", track_idx)
            if track_clips and len(track_clips) > 0:
                clips.extend(track_clips)
        except:
            continue

    print(f"\nFound {len(clips)} clips in timeline:")
    for i, clip in enumerate(clips):
        clip_start = clip.GetStart()
        clip_end = clip.GetEnd()
        clip_name = clip.GetName()
        print(f"Clip {i+1}: '{clip_name}'")
        print(f"  Frame range: {clip_start} to {clip_end}")
        print(f"  Duration: {clip_end - clip_start} frames")

        # Calculate timecode equivalent (rough estimate)
        hours_start = clip_start // (frame_rate * 60 * 60)
        minutes_start = (clip_start % (frame_rate * 60 * 60)) // (frame_rate * 60)
        seconds_start = (clip_start % (frame_rate * 60)) // frame_rate
        frames_start = clip_start % frame_rate

        tc_start = f"{int(hours_start):02d}:{int(minutes_start):02d}:{int(seconds_start):02d}:{int(frames_start):02d}"
        print(f"  Approx. start TC: {tc_start}")
        print()

    # Get existing markers
    markers = current_timeline.GetMarkers() or {}
    print(f"\nFound {len(markers)} markers in timeline:")

    sorted_markers = sorted(markers.items())
    for frame, marker_data in sorted_markers:
        color = marker_data.get("color", "Unknown")
        name = marker_data.get("name", "")

        # Calculate timecode equivalent (rough estimate)
        hours = frame // (frame_rate * 60 * 60)
        minutes = (frame % (frame_rate * 60 * 60)) // (frame_rate * 60)
        seconds = (frame % (frame_rate * 60)) // frame_rate
        frames = frame % frame_rate

        tc = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}:{int(frames):02d}"
        print(f"Marker at frame {frame} (approx. TC: {tc}):")
        print(f"  Color: {color}")
        print(f"  Name: {name}")
        print()

    print("\n===== End of Information =====")


if __name__ == "__main__":
    main()
