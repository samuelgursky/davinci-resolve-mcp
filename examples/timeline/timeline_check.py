#!/usr/bin/env python3
"""
Detailed timeline check to analyze clip positions and timecode mapping
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


def frame_to_tc(frame, fps):
    """Convert frame number to timecode"""
    total_seconds = frame / fps
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    frames = int((total_seconds - int(total_seconds)) * fps)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def main():
    print("\n===== DETAILED TIMELINE ANALYSIS =====\n")

    # Connect to Resolve
    resolve = dvr_script.scriptapp("Resolve")
    if not resolve:
        print("Error: Failed to connect to DaVinci Resolve")
        return

    print(f"Connected to: {resolve.GetProductName()} {resolve.GetVersionString()}")

    # Get project manager
    project_manager = resolve.GetProjectManager()
    current_project = project_manager.GetCurrentProject()
    current_timeline = current_project.GetCurrentTimeline()

    print(f"Project: {current_project.GetName()}")
    print(f"Timeline: {current_timeline.GetName()}")

    # Get timeline settings
    fps = float(current_timeline.GetSetting("timelineFrameRate"))
    print(f"Frame rate: {fps}")

    start_frame = current_timeline.GetStartFrame()
    end_frame = current_timeline.GetEndFrame()

    # Calculate real timecodes
    start_tc = frame_to_tc(start_frame, fps)
    end_tc = frame_to_tc(end_frame, fps)

    print(f"\nTimeline spans frames {start_frame} to {end_frame}")
    print(f"Timeline estimated timecode: {start_tc} to {end_tc}")

    # Check if we can get actual timecode
    try:
        start_timecode = current_timeline.GetStartTimecode()
        print(f"Timeline actual start timecode: {start_timecode}")
    except:
        print("Could not get actual start timecode")

    # Check timecode display settings
    tc_drop = current_timeline.GetSetting("timelineDropFrameTimecode")
    print(f"Drop frame: {tc_drop}")

    # Get playhead position
    try:
        playhead_frame = current_timeline.GetCurrentVideoFrame()
        playhead_tc = frame_to_tc(playhead_frame, fps)
        print(f"\nPlayhead at frame {playhead_frame} (approx. TC: {playhead_tc})")
    except Exception as e:
        print(f"Error getting playhead: {str(e)}")

    # Get clips
    clips = []
    for track_idx in range(1, 5):  # Check first 4 video tracks
        try:
            track_clips = current_timeline.GetItemListInTrack("video", track_idx)
            if track_clips and len(track_clips) > 0:
                clips.extend(track_clips)
        except:
            continue

    print(f"\nFound {len(clips)} clips:")
    for i, clip in enumerate(clips):
        clip_name = clip.GetName()
        start_frame = clip.GetStart()
        end_frame = clip.GetEnd()

        # Get the source frame info
        try:
            source_start = clip.GetLeftOffset()
            source_end = source_start + (end_frame - start_frame)
            print(f"  Clip {i+1}: '{clip_name}'")
            print(
                f"    Timeline: frames {start_frame}-{end_frame} ({frame_to_tc(start_frame, fps)}-{frame_to_tc(end_frame, fps)})"
            )
            print(f"    Source: frames {source_start}-{source_end}")
        except Exception as e:
            print(f"  Clip {i+1}: '{clip_name}'")
            print(
                f"    Timeline: frames {start_frame}-{end_frame} ({frame_to_tc(start_frame, fps)}-{frame_to_tc(end_frame, fps)})"
            )
            print(f"    Source info error: {str(e)}")

    # Get markers
    markers = current_timeline.GetMarkers() or {}
    print(f"\nFound {len(markers)} markers:")

    sorted_markers = sorted(markers.items())
    for frame, marker_data in sorted_markers:
        color = marker_data.get("color", "Unknown")
        name = marker_data.get("name", "")
        tc = frame_to_tc(frame, fps)
        print(f"  Marker at frame {frame} (TC: {tc}):")
        print(f"    Color: {color}")
        print(f"    Name: {name}")

    # Try to determine timeline start offset
    try:
        one_hour_frames = int(fps * 60 * 60)
        print("\nTimeline offset analysis:")
        print(f"  One hour in frames: {one_hour_frames}")
        print(
            f"  If timeline starts at 01:00:00:00, first frame should be {one_hour_frames}"
        )
        offset = start_frame - one_hour_frames
        print(f"  Detected offset: {offset} frames")

        if offset >= 0:
            print(
                f"  Timeline appears to start at {frame_to_tc(offset + one_hour_frames, fps)}"
            )
        else:
            print(
                f"  Timeline appears to start at {frame_to_tc(one_hour_frames - abs(offset), fps)}"
            )
    except Exception as e:
        print(f"Error analyzing offset: {str(e)}")

    print("\n===== END OF ANALYSIS =====")


if __name__ == "__main__":
    main()
