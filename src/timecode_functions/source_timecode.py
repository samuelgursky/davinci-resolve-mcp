"""
DaVinci Resolve Source Timecode Functions

This module provides functions for working with source timecodes in DaVinci Resolve.
"""

import sys
import os
from typing import Dict, Any, List, Union, Optional

# Try to import the DaVinci Resolve scripting module
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    resolve_api_path = os.environ.get(
        "RESOLVE_SCRIPT_API",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
    )
    resolve_module_path = os.path.join(resolve_api_path, "Modules")
    sys.path.append(resolve_module_path)
    import DaVinciResolveScript as dvr
except ImportError:
    print("Error: Could not import DaVinci Resolve scripting modules")


def get_resolve_instance():
    """Get the current instance of DaVinci Resolve"""
    try:
        resolve = dvr.scriptapp("Resolve")
        return resolve
    except NameError:
        print("Error: DaVinci Resolve not found")
        return None


def get_project_manager():
    """Get the project manager object."""
    resolve = get_resolve_instance()
    return resolve.GetProjectManager() if resolve else None


def get_current_project():
    """Get the current project object or None if no project is open."""
    project_manager = get_project_manager()
    return project_manager.GetCurrentProject() if project_manager else None


def get_current_timeline():
    """Get the current timeline object or None if no timeline is open."""
    project = get_current_project()
    return project.GetCurrentTimeline() if project else None


def timecode_to_frames(timecode: str, fps: float) -> int:
    """
    Convert a timecode string to frame count.
    
    Args:
        timecode: Timecode string in format "HH:MM:SS:FF"
        fps: Frames per second
        
    Returns:
        Frame count
    """
    try:
        parts = timecode.split(":")
        if len(parts) != 4:
            return 0
            
        hours, minutes, seconds, frames = map(int, parts)
        
        # Calculate total frames
        total_frames = (hours * 3600 + minutes * 60 + seconds) * int(fps) + frames
        return total_frames
    except (ValueError, AttributeError):
        return 0


def frames_to_timecode(frame_count: int, fps: float) -> str:
    """
    Convert frame count to timecode string.
    
    Args:
        frame_count: Number of frames
        fps: Frames per second
        
    Returns:
        Timecode string in format "HH:MM:SS:FF"
    """
    try:
        # Get integer FPS
        int_fps = int(fps)
        
        # Calculate components
        total_seconds = frame_count // int_fps
        frames = frame_count % int_fps
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"
    except (ValueError, TypeError):
        return "00:00:00:00"


def calculate_source_timecode(start_tc: str, offset_frames: int, fps: float) -> str:
    """
    Calculate a new timecode by adding frames to a starting timecode.
    
    Args:
        start_tc: Starting timecode in format "HH:MM:SS:FF"
        offset_frames: Number of frames to add
        fps: Frames per second
    
    Returns:
        New timecode string in format "HH:MM:SS:FF"
    """
    # Convert start timecode to frames
    start_frames = timecode_to_frames(start_tc, fps)
    
    # Add offset
    new_frames = start_frames + offset_frames
    
    # Convert back to timecode
    return frames_to_timecode(new_frames, fps)


def get_clip_source_timecode(clip, media_item) -> Dict[str, Any]:
    """
    Get source timecode information for a clip.
    
    Args:
        clip: Timeline clip object
        media_item: Media pool item object
        
    Returns:
        Dictionary with source timecode information
    """
    source_tc_info = {}
    
    try:
        # Get source properties
        source_tc_info["source_start_tc"] = media_item.GetClipProperty("Start TC")
        source_tc_info["source_end_tc"] = media_item.GetClipProperty("End TC")
        source_tc_info["fps"] = float(media_item.GetClipProperty("FPS"))
        
        # Get the timeline in/out points relative to source
        source_tc_info["source_in"] = clip.GetLeftOffset()  # Frames from start of source
        source_tc_info["source_out"] = source_tc_info["source_in"] + clip.GetDuration()
        
        # Calculate actual source timecodes for timeline in/out points
        if "source_start_tc" in source_tc_info and "source_in" in source_tc_info:
            source_tc_info["timeline_source_in_tc"] = calculate_source_timecode(
                source_tc_info["source_start_tc"], 
                source_tc_info["source_in"], 
                source_tc_info["fps"]
            )
            source_tc_info["timeline_source_out_tc"] = calculate_source_timecode(
                source_tc_info["source_start_tc"], 
                source_tc_info["source_out"], 
                source_tc_info["fps"]
            )
    except Exception as e:
        source_tc_info["source_timecode_error"] = str(e)
    
    return source_tc_info


def mcp_get_clip_source_timecode(
    track_type: str = "video", track_index: int = 1, clip_index: int = 0
) -> Dict[str, Any]:
    """
    Get detailed source timecode information about a specific clip in the timeline.

    Args:
        track_type: The type of track ('video' or 'audio')
        track_index: The index of the track (1-based)
        clip_index: The index of the clip in the track (0-based)

    Returns:
        A dictionary with clip source timecode details or an error message
    """
    timeline = get_current_timeline()

    if not timeline:
        return {"error": "No timeline is currently open"}

    # Validate track type
    if track_type not in ["video", "audio"]:
        return {"error": "Track type must be 'video' or 'audio'"}

    # Validate track index
    track_count = timeline.GetTrackCount(track_type)
    if track_index < 1 or track_index > track_count:
        return {"error": f"Track index must be between 1 and {track_count}"}

    # Get clips in the track
    clips = timeline.GetItemListInTrack(track_type, track_index)

    if not clips or len(clips) <= clip_index:
        return {
            "error": f"Clip index {clip_index} not found in {track_type} track {track_index}"
        }

    # Get the specific clip
    clip = clips[clip_index]

    # Collect basic clip properties
    properties = {
        "name": clip.GetName(), 
        "duration": clip.GetDuration(),
        "track": f"{track_type[0].upper()}{track_index}",
        "track_type": track_type,
        "track_index": track_index,
        "clip_index": clip_index
    }

    try:
        properties["start_frame"] = clip.GetStart()
        properties["end_frame"] = clip.GetEnd()
    except:
        pass

    # Try to access media pool item
    try:
        # First try the standard method
        media_item = clip.GetMediaPoolItem()
        has_media_item = media_item is not None
        properties["media_pool_item"] = has_media_item

        # If we have a valid media pool item, get source timecode information
        if has_media_item:
            source_tc_info = get_clip_source_timecode(clip, media_item)
            properties.update(source_tc_info)
            
            # Add file path
            try:
                properties["file_path"] = media_item.GetClipProperty("File Path")
            except:
                pass
    except Exception as e:
        properties["media_pool_error"] = str(e)

    return properties


def mcp_get_source_timecode_report() -> Dict[str, Any]:
    """
    Generate a comprehensive report of all clips in the timeline with their source timecode information.
    
    Returns:
        A dictionary with the timeline name and a list of clips with source timecodes
    """
    timeline = get_current_timeline()
    
    if not timeline:
        return {"error": "No timeline is currently open"}
    
    report = {
        "timeline_name": timeline.GetName(),
        "clips": []
    }
    
    # Process video tracks
    video_track_count = timeline.GetTrackCount("video")
    for track_idx in range(1, video_track_count + 1):
        clips = timeline.GetItemListInTrack("video", track_idx)
        
        for clip_idx, clip in enumerate(clips):
            clip_info = mcp_get_clip_source_timecode("video", track_idx, clip_idx)
            report["clips"].append(clip_info)
    
    # Process audio tracks
    audio_track_count = timeline.GetTrackCount("audio")
    for track_idx in range(1, audio_track_count + 1):
        clips = timeline.GetItemListInTrack("audio", track_idx)
        
        for clip_idx, clip in enumerate(clips):
            clip_info = mcp_get_clip_source_timecode("audio", track_idx, clip_idx)
            report["clips"].append(clip_info)
    
    return report


def mcp_export_source_timecode_report(
    export_path: str,
    format: str = "csv",  # Options: csv, json, edl
    video_tracks_only: bool = False
) -> Dict[str, Any]:
    """
    Export a report of all timeline clips with their source timecodes.
    
    Args:
        export_path: Path where the report should be saved
        format: Report format (csv, json, or edl)
        video_tracks_only: If True, only include video tracks in the report
    
    Returns:
        Status of the export operation
    """
    import json
    import os
    
    # Get the report data
    report_data = mcp_get_source_timecode_report()
    
    if "error" in report_data:
        return report_data
    
    # Filter to video tracks if requested
    if video_tracks_only:
        report_data["clips"] = [clip for clip in report_data["clips"] 
                               if clip.get("track_type") == "video"]
    
    try:
        # Ensure the directory exists
        export_dir = os.path.dirname(export_path)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir)
            
        if format.lower() == "csv":
            # Export as CSV
            with open(export_path, 'w') as f:
                # Write header
                f.write("Name,Track,Timeline Start,Timeline End,Duration,Source In TC,Source Out TC,File Path\n")
                
                # Write data
                for clip in report_data["clips"]:
                    f.write(f"{clip.get('name', '')},{clip.get('track', '')},"
                            f"{clip.get('start_frame', '')},{clip.get('end_frame', '')},"
                            f"{clip.get('duration', '')},"
                            f"{clip.get('timeline_source_in_tc', '')},{clip.get('timeline_source_out_tc', '')},"
                            f"{clip.get('file_path', '')}\n")
        
        elif format.lower() == "json":
            # Export as JSON
            with open(export_path, 'w') as f:
                json.dump(report_data, f, indent=2)
        
        elif format.lower() == "edl":
            # Export as EDL format
            with open(export_path, 'w') as f:
                # Write EDL header
                f.write(f"TITLE: {report_data['timeline_name']}\n")
                f.write("FCM: NON-DROP FRAME\n\n")
                
                # Write EDL entries
                for i, clip in enumerate(report_data["clips"]):
                    if "timeline_source_in_tc" in clip and "timeline_source_out_tc" in clip:
                        if clip.get("track_type") == "video":  # EDL typically only includes video
                            # Write EDL entry
                            f.write(f"{i+1:03d}  {clip.get('name', 'CLIP')}       V     C        ")
                            f.write(f"{frames_to_timecode(clip.get('start_frame', 0), 24.0)} ")
                            f.write(f"{frames_to_timecode(clip.get('end_frame', 0), 24.0)} ")
                            f.write(f"{clip.get('timeline_source_in_tc', '00:00:00:00')} ")
                            f.write(f"{clip.get('timeline_source_out_tc', '00:00:00:00')}\n")
                            
                            # Write additional clip info as comments
                            f.write(f"* FROM CLIP NAME: {clip.get('name', '')}\n")
                            f.write(f"* SOURCE FILE: {clip.get('file_path', '')}\n\n")
        
        else:
            return {"error": f"Unsupported format: {format}. Supported formats are: csv, json, edl"}
        
        return {
            "status": "success",
            "message": f"Source timecode report exported to {export_path}",
            "format": format,
            "clips_exported": len(report_data["clips"])
        }
    
    except Exception as e:
        return {"error": f"Failed to export report: {str(e)}"} 