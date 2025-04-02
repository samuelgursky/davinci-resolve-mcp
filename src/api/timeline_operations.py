#!/usr/bin/env python3
"""
DaVinci Resolve Timeline Operations
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("davinci-resolve-mcp.timeline")


def list_timelines(resolve) -> List[str]:
    """List all timelines in the current project."""
    if resolve is None:
        return ["Error: Not connected to DaVinci Resolve"]

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return ["Error: Failed to get Project Manager"]

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return ["Error: No project currently open"]

    timeline_count = current_project.GetTimelineCount()
    timelines = []

    for i in range(1, timeline_count + 1):
        timeline = current_project.GetTimelineByIndex(i)
        if timeline:
            timelines.append(timeline.GetName())

    return timelines if timelines else ["No timelines found in the current project"]


def get_current_timeline_info(resolve) -> Dict[str, Any]:
    """Get information about the current timeline."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}

    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        return {"error": "No timeline currently active"}

    # Get basic timeline info
    info = {
        "name": current_timeline.GetName(),
        "framerate": current_timeline.GetSetting("timelineFrameRate"),
        "resolution": {
            "width": current_timeline.GetSetting("timelineResolutionWidth"),
            "height": current_timeline.GetSetting("timelineResolutionHeight"),
        },
        "start_timecode": current_timeline.GetStartTimecode(),
    }

    return info


def create_timeline(resolve, name: str) -> str:
    """Create a new timeline with the given name."""
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    if not name:
        return "Error: Timeline name cannot be empty"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"

    # Check if timeline already exists to avoid duplicates
    existing_timelines = list_timelines(resolve)
    if name in existing_timelines:
        return f"Error: Timeline '{name}' already exists"

    # Create the timeline
    timeline = media_pool.CreateEmptyTimeline(name)
    if timeline:
        return f"Successfully created timeline '{name}'"
    else:
        return f"Failed to create timeline '{name}'"


def create_empty_timeline(
    resolve,
    name: str,
    frame_rate: str = None,
    resolution_width: int = None,
    resolution_height: int = None,
    start_timecode: str = None,
    video_tracks: int = None,
    audio_tracks: int = None,
) -> str:
    """Create a new timeline with the given name and custom settings.

    Args:
        resolve: The DaVinci Resolve instance
        name: The name for the new timeline
        frame_rate: Optional frame rate (e.g. "24", "29.97", "30", "60")
        resolution_width: Optional width in pixels (e.g. 1920)
        resolution_height: Optional height in pixels (e.g. 1080)
        start_timecode: Optional start timecode (e.g. "01:00:00:00")
        video_tracks: Optional number of video tracks (Default is project setting)
        audio_tracks: Optional number of audio tracks (Default is project setting)

    Returns:
        String indicating success or failure with detailed error message
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    if not name:
        return "Error: Timeline name cannot be empty"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"

    # Check if timeline already exists to avoid duplicates
    existing_timelines = list_timelines(resolve)
    if name in existing_timelines:
        return f"Error: Timeline '{name}' already exists"

    # Store original settings to restore later if needed
    original_settings = {}
    settings_to_modify = {}

    # Prepare settings modifications
    if frame_rate is not None:
        setting_name = "timelineFrameRate"
        original_settings[setting_name] = current_project.GetSetting(setting_name)
        settings_to_modify[setting_name] = frame_rate

    if resolution_width is not None:
        setting_name = "timelineResolutionWidth"
        original_settings[setting_name] = current_project.GetSetting(setting_name)
        settings_to_modify[setting_name] = str(resolution_width)

    if resolution_height is not None:
        setting_name = "timelineResolutionHeight"
        original_settings[setting_name] = current_project.GetSetting(setting_name)
        settings_to_modify[setting_name] = str(resolution_height)

    # Apply settings before creating timeline
    for setting_name, setting_value in settings_to_modify.items():
        logger.info(f"Setting project setting {setting_name} to {setting_value}")
        current_project.SetSetting(setting_name, setting_value)

    # Create the timeline
    timeline = media_pool.CreateEmptyTimeline(name)

    if not timeline:
        # Timeline creation failed, restore original settings
        for setting_name, setting_value in original_settings.items():
            current_project.SetSetting(setting_name, setting_value)
        return f"Failed to create timeline '{name}'"

    # Set the timeline as current to modify it
    current_project.SetCurrentTimeline(timeline)

    # Setup timecode if specified
    if start_timecode is not None:
        try:
            success = timeline.SetStartTimecode(start_timecode)
            if not success:
                logger.warning(f"Failed to set start timecode to {start_timecode}")
        except Exception as e:
            logger.error(f"Error setting start timecode: {str(e)}")

    # Add video tracks if specified
    if (
        video_tracks is not None and video_tracks > 1
    ):  # Timeline comes with 1 video track by default
        # Resolve does not have a direct API for adding tracks
        # This would need to be implemented using UI automation or future API versions
        logger.info(
            f"Custom video track count ({video_tracks}) will need to be set manually"
        )

    # Add audio tracks if specified
    if (
        audio_tracks is not None and audio_tracks > 1
    ):  # Timeline comes with 1 audio track by default
        # Resolve does not have a direct API for adding tracks
        logger.info(
            f"Custom audio track count ({audio_tracks}) will need to be set manually"
        )

    # Restore original settings if needed
    if original_settings:
        for setting_name, setting_value in original_settings.items():
            current_project.SetSetting(setting_name, setting_value)

    return f"Successfully created timeline '{name}' with custom settings"


def set_current_timeline(resolve, name: str) -> str:
    """Switch to a timeline by name."""
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    if not name:
        return "Error: Timeline name cannot be empty"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    # First get a list of all timelines
    timeline_count = current_project.GetTimelineCount()

    for i in range(1, timeline_count + 1):
        timeline = current_project.GetTimelineByIndex(i)
        if timeline and timeline.GetName() == name:
            # Found the timeline, set it as current
            current_project.SetCurrentTimeline(timeline)
            # Verify it was set
            current_timeline = current_project.GetCurrentTimeline()
            if current_timeline and current_timeline.GetName() == name:
                return f"Successfully switched to timeline '{name}'"
            else:
                return f"Error: Failed to switch to timeline '{name}'"

    return f"Error: Timeline '{name}' not found"


def add_marker(
    resolve, frame: Optional[int] = None, color: str = "Blue", note: str = ""
) -> str:
    """Add a marker at the specified frame in the current timeline.

    Args:
        resolve: The DaVinci Resolve instance
        frame: The frame number to add the marker at (defaults to auto-selection if None)
        color: The marker color (Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia,
               Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream)
        note: Text note to add to the marker

    Returns:
        String indicating success or failure with detailed error message
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        return "Error: No timeline currently active"

    # Get timeline information
    try:
        timeline_start = current_timeline.GetStartFrame()
        timeline_end = current_timeline.GetEndFrame()
        timeline_name = current_timeline.GetName()
        print(
            f"Timeline '{timeline_name}' frame range: {timeline_start}-{timeline_end}"
        )
    except Exception as e:
        return f"Error: Failed to get timeline information: {str(e)}"

    # Validate marker color
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
        return (
            f"Error: Invalid marker color. Valid colors are: {', '.join(valid_colors)}"
        )

    try:
        # Get information about clips in the timeline
        clips = []
        for track_idx in range(1, 5):  # Check first 4 video tracks
            try:
                track_clips = current_timeline.GetItemListInTrack("video", track_idx)
                if track_clips and len(track_clips) > 0:
                    clips.extend(track_clips)
            except:
                continue

        if not clips:
            return "Error: No clips found in timeline. Add media to the timeline first."

        # Get existing markers to avoid conflicts
        existing_markers = current_timeline.GetMarkers() or {}

        # If no frame specified, find a good position
        if frame is None:
            # Try to find a frame in the middle of a clip that doesn't have a marker
            for clip in clips:
                clip_start = clip.GetStart()
                clip_end = clip.GetEnd()

                # Try middle of clip
                mid_frame = clip_start + ((clip_end - clip_start) // 2)
                if mid_frame not in existing_markers:
                    frame = mid_frame
                    break

                # Try middle + 1
                if (mid_frame + 1) not in existing_markers:
                    frame = mid_frame + 1
                    break

                # Try other positions in the clip
                for offset in [10, 20, 30, 40, 50]:
                    test_frame = clip_start + offset
                    if (
                        clip_start <= test_frame <= clip_end
                        and test_frame not in existing_markers
                    ):
                        frame = test_frame
                        break

            # If we still don't have a frame, use the first valid position we can find
            if frame is None:
                for f in range(timeline_start, timeline_end, 10):
                    if f not in existing_markers:
                        # Check if this frame is within a clip
                        for clip in clips:
                            if clip.GetStart() <= f <= clip.GetEnd():
                                frame = f
                                break
                    if frame is not None:
                        break

            # If we still don't have a frame, report error
            if frame is None:
                return "Error: Could not find a valid frame position for marker. Try specifying a frame number."

        # Frame specified - validate it
        else:
            # Check if frame is within timeline bounds
            if frame < timeline_start or frame > timeline_end:
                return f"Error: Frame {frame} is out of timeline bounds ({timeline_start}-{timeline_end})"

            # Check if frame already has a marker
            if frame in existing_markers:
                # Suggest an alternate frame
                alternate_found = False
                alternates = [frame + 1, frame - 1, frame + 2, frame + 5, frame + 10]

                for alt_frame in alternates:
                    if (
                        timeline_start <= alt_frame <= timeline_end
                        and alt_frame not in existing_markers
                    ):
                        # Check if frame is within a clip
                        for clip in clips:
                            if clip.GetStart() <= alt_frame <= clip.GetEnd():
                                return f"Error: A marker already exists at frame {frame}. Try frame {alt_frame} instead."

                return f"Error: A marker already exists at frame {frame}. Try a different frame position."

            # Verify frame is within a clip
            frame_in_clip = False
            for clip in clips:
                if clip.GetStart() <= frame <= clip.GetEnd():
                    frame_in_clip = True
                    break

            if not frame_in_clip:
                return f"Error: Frame {frame} is not within any media in the timeline. Markers must be on actual clips."

        # Add the marker
        print(f"Adding marker at frame {frame} with color {color}")
        marker_result = current_timeline.AddMarker(
            frame,  # frameId
            color,  # color
            note,  # name - we'll use the note for this
            note,  # note
            1,  # duration - default to 1 frame
            "",  # customData - not used for now
        )

        if marker_result:
            return (
                f"Successfully added {color} marker at frame {frame} with note: {note}"
            )
        else:
            return f"Failed to add marker at frame {frame}"

    except Exception as e:
        return f"Error adding marker: {str(e)}"


def delete_timeline(resolve, name: str) -> str:
    """Delete a timeline by name.

    Args:
        resolve: The DaVinci Resolve instance
        name: The name of the timeline to delete

    Returns:
        String indicating success or failure with detailed error message
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    # First check if the timeline exists
    timeline_count = current_project.GetTimelineCount()
    target_timeline = None

    # Find the timeline by name
    for i in range(1, timeline_count + 1):
        timeline = current_project.GetTimelineByIndex(i)
        if timeline and timeline.GetName() == name:
            target_timeline = timeline
            break

    if not target_timeline:
        return f"Error: Timeline '{name}' not found"

    # Check if it's the current timeline
    current_timeline = current_project.GetCurrentTimeline()
    if current_timeline and current_timeline.GetName() == name:
        # We shouldn't delete the current timeline - need to switch to another one first
        # Find another timeline to switch to
        another_timeline = None
        for i in range(1, timeline_count + 1):
            timeline = current_project.GetTimelineByIndex(i)
            if timeline and timeline.GetName() != name:
                another_timeline = timeline
                break

        if another_timeline:
            # Switch to this timeline first
            current_project.SetCurrentTimeline(another_timeline)
        else:
            return "Error: Cannot delete the only timeline in the project. Create a new timeline first."

    # Now delete the timeline
    try:
        # The DeleteTimelines method takes a list of timelines
        result = current_project.DeleteTimelines([target_timeline])

        if result:
            return f"Successfully deleted timeline '{name}'"
        else:
            return f"Failed to delete timeline '{name}'"
    except Exception as e:
        return f"Error deleting timeline: {str(e)}"


def get_timeline_tracks(resolve, timeline_name: str = None) -> Dict[str, Any]:
    """Get the track structure of a timeline.

    Args:
        resolve: The DaVinci Resolve instance
        timeline_name: Optional name of the timeline to get tracks from. Uses current timeline if None.

    Returns:
        Dictionary with track information
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}

    # Determine which timeline to use
    timeline = None
    if timeline_name:
        # Find the timeline by name
        timeline_count = current_project.GetTimelineCount()
        for i in range(1, timeline_count + 1):
            t = current_project.GetTimelineByIndex(i)
            if t and t.GetName() == timeline_name:
                timeline = t
                break

        if not timeline:
            return {"error": f"Timeline '{timeline_name}' not found"}
    else:
        # Use current timeline
        timeline = current_project.GetCurrentTimeline()
        if not timeline:
            return {"error": "No timeline currently active"}

    timeline_name = timeline.GetName()

    try:
        # Get track counts
        video_track_count = timeline.GetTrackCount("video")
        audio_track_count = timeline.GetTrackCount("audio")
        subtitle_track_count = timeline.GetTrackCount("subtitle")

        # Get track information
        tracks = {
            "name": timeline_name,
            "video": {"count": video_track_count, "tracks": []},
            "audio": {"count": audio_track_count, "tracks": []},
            "subtitle": {"count": subtitle_track_count, "tracks": []},
        }

        # Get information about video tracks
        for i in range(1, video_track_count + 1):
            track_info = {
                "index": i,
                "name": f"V{i}",  # Default name format
                "enabled": timeline.GetIsTrackEnabled("video", i),
                "clip_count": 0,
            }

            # Get clips in this track
            clips = timeline.GetItemListInTrack("video", i)
            track_info["clip_count"] = len(clips) if clips else 0

            tracks["video"]["tracks"].append(track_info)

        # Get information about audio tracks
        for i in range(1, audio_track_count + 1):
            track_info = {
                "index": i,
                "name": f"A{i}",  # Default name format
                "enabled": timeline.GetIsTrackEnabled("audio", i),
                "clip_count": 0,
            }

            # Get clips in this track
            clips = timeline.GetItemListInTrack("audio", i)
            track_info["clip_count"] = len(clips) if clips else 0

            tracks["audio"]["tracks"].append(track_info)

        # Get information about subtitle tracks
        for i in range(1, subtitle_track_count + 1):
            track_info = {
                "index": i,
                "name": f"S{i}",  # Default name format
                "enabled": timeline.GetIsTrackEnabled("subtitle", i),
                "clip_count": 0,
            }

            # Get clips in this track
            clips = timeline.GetItemListInTrack("subtitle", i)
            track_info["clip_count"] = len(clips) if clips else 0

            tracks["subtitle"]["tracks"].append(track_info)

        return tracks

    except Exception as e:
        return {"error": f"Error getting timeline tracks: {str(e)}"}
