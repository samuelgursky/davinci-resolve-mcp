from mcp.server.fastmcp import FastMCP
import sys
import os
import json
from typing import List, Dict, Any, Union, Optional
from .fixed_timeline_functions import get_resolve_instance

# Add DaVinci Resolve script module paths based on OS
def add_resolve_module_path():
    """Add the appropriate DaVinci Resolve API path based on the operating system."""
    if sys.platform.startswith("darwin"):
        # macOS
        resolve_api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/"
        script_path = os.path.expanduser("~/") + resolve_api_path
        if not os.path.isdir(script_path):
            script_path = resolve_api_path
    elif sys.platform.startswith("win") or sys.platform.startswith("cygwin"):
        # Windows
        resolve_api_path = "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules\\"
        script_path = resolve_api_path
    elif sys.platform.startswith("linux"):
        # Linux
        resolve_api_path = "/opt/resolve/Developer/Scripting/Modules/"
        script_path = resolve_api_path
    else:
        raise ValueError(f"Unsupported platform: {sys.platform}")
        
    if os.path.isdir(script_path):
        sys.path.append(script_path)
        return True
    else:
        return False

# Initialize Resolve API
try:
    if add_resolve_module_path():
        import DaVinciResolveScript as dvr_script
        resolve = dvr_script.scriptapp("Resolve")
        if not resolve:
            print("Error: Unable to connect to DaVinci Resolve. Make sure Resolve is running.")
            sys.exit(1)
    else:
        print("Error: Could not locate DaVinci Resolve API modules.")
        sys.exit(1)
except ImportError:
    print("Error: Could not import DaVinci Resolve API. Make sure Resolve is running.")
    sys.exit(1)

# Create an MCP server for DaVinci Resolve
mcp = FastMCP("DaVinci Resolve")

# Helper functions for common Resolve object access
def get_project_manager():
    """Get the project manager object."""
    return resolve.GetProjectManager()

def get_current_project():
    """Get the current project object or None if no project is open."""
    project_manager = get_project_manager()
    return project_manager.GetCurrentProject() if project_manager else None

def get_current_timeline():
    """Get the current timeline object or None if no timeline is open."""
    project = get_current_project()
    return project.GetCurrentTimeline() if project else None

def get_media_pool():
    """Get the media pool object or None if no project is open."""
    project = get_current_project()
    return project.GetMediaPool() if project else None

def get_current_page():
    """Get the current page name (Edit, Color, Fairlight, etc.)."""
    return resolve.GetCurrentPage()

def safe_api_call(func):
    """Decorator to safely call Resolve API functions and handle exceptions."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return {"error": f"API Error: {str(e)}"}
    return wrapper

# PROJECT TOOLS
@mcp.tool()
@safe_api_call
def get_project_info() -> Dict[str, Any]:
    """Get information about the current project in DaVinci Resolve."""
    project = get_current_project()
    
    if not project:
        return {"error": "No project is currently open"}
    
    # Get the timeline count
    timeline_count = project.GetTimelineCount()
    
    return {
        "name": project.GetName(),
        "frame_rate": project.GetSetting("timelineFrameRate"),
        "resolution": {
            "width": project.GetSetting("timelineResolutionWidth"),
            "height": project.GetSetting("timelineResolutionHeight")
        },
        "timeline_count": timeline_count,
        "current_timeline": project.GetCurrentTimeline().GetName() if project.GetCurrentTimeline() else None,
        "current_page": get_current_page()
    }

@mcp.tool()
@safe_api_call
def get_project_list() -> List[str]:
    """Get a list of all projects in the current database."""
    project_manager = get_project_manager()
    
    if not project_manager:
        return {"error": "Could not access project manager"}
    
    project_list = project_manager.GetProjectListInCurrentFolder()
    return project_list

@mcp.tool()
@safe_api_call
def switch_to_project(project_name: str) -> Dict[str, Any]:
    """Switch to a different project.
    
    Args:
        project_name: The name of the project to switch to
        
    Returns:
        Status of the operation
    """
    project_manager = get_project_manager()
    
    if not project_manager:
        return {"error": "Could not access project manager"}
    
    # Check if the project exists
    project_list = project_manager.GetProjectListInCurrentFolder()
    if project_name not in project_list:
        return {"error": f"Project '{project_name}' not found"}
    
    # Load the project
    project = project_manager.LoadProject(project_name)
    if not project:
        return {"error": f"Failed to load project '{project_name}'"}
    
    return {"status": "success", "project": project_name}

# TIMELINE TOOLS
@mcp.tool()
@safe_api_call
def get_current_timeline_name() -> str:
    """Get the name of the current timeline."""
    timeline = get_current_timeline()
    
    if not timeline:
        return "No timeline is currently open"
    
    return timeline.GetName()

@mcp.tool()
@safe_api_call
def get_timeline_info() -> Dict[str, Any]:
    """Get detailed information about the current timeline."""
    timeline = get_current_timeline()
    
    if not timeline:
        return {"error": "No timeline is currently open"}
    
    # Get timeline information
    info = {
        "name": timeline.GetName(),
        "video_track_count": timeline.GetTrackCount("video"),
        "audio_track_count": timeline.GetTrackCount("audio")
    }
    
    # Try to get additional timeline information
    try:
        info["start_frame"] = timeline.GetStartFrame()
        info["end_frame"] = timeline.GetEndFrame()
        
        # Calculate frame count if both start and end frames were retrieved
        if "start_frame" in info and "end_frame" in info:
            info["frame_count"] = info["end_frame"] - info["start_frame"] + 1
    except:
        pass
        
    # Try to get timecode information
    try:
        info["timecode_start"] = timeline.GetStartTimecode()
        info["timecode_end"] = timeline.GetEndTimecode()
    except:
        pass
    
    # Try to get project settings
    project = get_current_project()
    try:
        info["fps"] = project.GetSetting("timelineFrameRate")
        info["resolution"] = {
            "width": project.GetSetting("timelineResolutionWidth"),
            "height": project.GetSetting("timelineResolutionHeight")
        }
    except:
        pass
        
    return info

@mcp.tool()
@safe_api_call
def get_project_timelines() -> List[Dict[str, Any]]:
    """Get a list of all timelines in the current project."""
    project = get_current_project()
    
    if not project:
        return {"error": "No project is currently open"}
    
    # Get the number of timelines in the project
    timeline_count = project.GetTimelineCount()
    
    # Get information about each timeline
    timelines = []
    for i in range(1, timeline_count + 1):
        try:
            timeline = project.GetTimelineByIndex(i)
            if timeline:
                timeline_info = {
                    "index": i,
                    "name": timeline.GetName()
                }
                
                # Try to get additional information
                try:
                    timeline_info["video_track_count"] = timeline.GetTrackCount("video")
                    timeline_info["audio_track_count"] = timeline.GetTrackCount("audio")
                except:
                    pass
                    
                timelines.append(timeline_info)
        except:
            continue
    
    return timelines

@mcp.tool()
@safe_api_call
def get_timeline_clip_names() -> List[Dict[str, Any]]:
    """Get the names of all clips in the current timeline."""
    timeline = get_current_timeline()
    
    if not timeline:
        return {"error": "No timeline is currently open"}
    
    # Get all clips in the timeline
    clip_names = []
    video_tracks_count = timeline.GetTrackCount("video")
    
    for track_index in range(1, video_tracks_count + 1):
        # GetItemListInTrack returns a list of clips
        clips = timeline.GetItemListInTrack("video", track_index)
        if clips:
            for clip in clips:
                clip_names.append({
                    "track": f"V{track_index}",
                    "name": clip.GetName(),
                    "duration": clip.GetDuration()
                })
    
    # Also get audio clips
    audio_tracks_count = timeline.GetTrackCount("audio")
    for track_index in range(1, audio_tracks_count + 1):
        clips = timeline.GetItemListInTrack("audio", track_index)
        if clips:
            for clip in clips:
                clip_names.append({
                    "track": f"A{track_index}",
                    "name": clip.GetName(),
                    "duration": clip.GetDuration()
                })
                
    return clip_names

@mcp.tool()
@safe_api_call
def get_clip_details(track_type: str = "video", track_index: int = 1, clip_index: int = 0) -> Dict[str, Any]:
    """Get detailed information about a specific clip in the timeline.
    
    Args:
        track_type: The type of track ('video' or 'audio')
        track_index: The index of the track (1-based)
        clip_index: The index of the clip in the track (0-based)
    
    Returns:
        A dictionary with clip details or an error message
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
        return {"error": f"Clip index {clip_index} not found in {track_type} track {track_index}"}
    
    # Get the specific clip
    clip = clips[clip_index]
    
    # Collect basic clip properties
    properties = {
        "name": clip.GetName(),
        "duration": clip.GetDuration()
    }
    
    # Try to get additional timeline item properties
    try:
        properties["start_frame"] = clip.GetStart()
        properties["end_frame"] = clip.GetEnd()
    except:
        pass
        
    try:
        properties["track"] = f"{track_type[0].upper()}{track_index}"
    except:
        pass
    
    # Try to access media pool item
    try:
        # First try the standard method
        media_item = clip.GetMediaPoolItem()
        has_media_item = media_item is not None
        properties["media_pool_item"] = has_media_item
        
        # If we have a valid media pool item, get its properties
        if has_media_item:
            try:
                media_props = {
                    "name": media_item.GetName()
                }
                
                # Try to get additional media properties
                try:
                    media_props["clip_color"] = media_item.GetClipColor()
                except:
                    pass
                    
                # Try to get clip properties using the GetClipProperty method
                for prop in ["Duration", "FPS", "File Path", "Resolution", "Format"]:
                    try:
                        media_props[prop.lower().replace(" ", "_")] = media_item.GetClipProperty(prop)
                    except:
                        pass
                        
                properties["media"] = media_props
            except Exception as e:
                properties["media_error"] = str(e)
        else:
            # Alternative approach for media properties
            try:
                # Try to access metadata directly from the timeline item
                if hasattr(clip, "GetMetadata"):
                    metadata = clip.GetMetadata()
                    if metadata:
                        properties["metadata"] = metadata
            except:
                pass
    except Exception as e:
        properties["media_pool_error"] = str(e)
    
    return properties

@mcp.tool()
@safe_api_call
def get_timeline_markers() -> List[Dict[str, Any]]:
    """Get all markers in the current timeline."""
    timeline = get_current_timeline()
    
    if not timeline:
        return {"error": "No timeline is currently open"}
    
    # Get all markers
    markers = timeline.GetMarkers()
    
    # Convert markers to a list
    marker_list = []
    for frame, marker in markers.items():
        marker_list.append({
            "frame": frame,
            "name": marker.get("name", ""),
            "color": marker.get("color", ""),
            "duration": marker.get("duration", 0),
            "note": marker.get("note", ""),
            "customData": marker.get("customData", "")
        })
    
    return marker_list

@mcp.tool()
@safe_api_call
def add_timeline_marker(frame_id: int, color: str = "Blue", name: str = "", note: str = "", duration: int = 1) -> Dict[str, Any]:
    """Add a marker at the specified frame in the timeline.
    
    Args:
        frame_id: Frame number where the marker should be added
        color: Marker color (Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon)
        name: Name of the marker
        note: Note text for the marker
        duration: Duration of the marker in frames
        
    Returns:
        Status of the operation
    """
    timeline = get_current_timeline()
    
    if not timeline:
        return {"error": "No timeline is currently open"}
    
    # Validate parameters
    valid_colors = ["Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", 
                   "Fuchsia", "Rose", "Lavender", "Sky", "Mint", "Lemon"]
    
    if color not in valid_colors:
        return {"error": f"Invalid color. Choose from: {', '.join(valid_colors)}"}
    
    # Create the marker
    marker_properties = {
        "color": color,
        "name": name,
        "note": note,
        "duration": duration
    }
    
    # Add the marker
    success = timeline.AddMarker(frame_id, marker_properties)
    
    if success:
        return {"status": "success", "frame": frame_id, "marker": marker_properties}
    else:
        return {"error": f"Failed to add marker at frame {frame_id}"}

@mcp.tool()
@safe_api_call
def delete_timeline_marker(frame_id: int) -> Dict[str, Any]:
    """Delete a marker at the specified frame in the timeline.
    
    Args:
        frame_id: Frame number where the marker should be deleted
        
    Returns:
        Status of the operation
    """
    timeline = get_current_timeline()
    
    if not timeline:
        return {"error": "No timeline is currently open"}
    
    # Delete the marker
    success = timeline.DeleteMarkerAtFrame(frame_id)
    
    if success:
        return {"status": "success", "frame": frame_id}
    else:
        return {"error": f"Failed to delete marker at frame {frame_id}"}

# PLAYBACK CONTROL
@mcp.tool()
@safe_api_call
def get_playhead_position() -> Dict[str, Any]:
    """Get the current playhead position in the timeline."""
    timeline = get_current_timeline()
    
    if not timeline:
        return {"error": "No timeline is currently open"}
    
    # Get current frame position
    current_frame = timeline.GetCurrentTimecode()
    frame_position = timeline.GetCurrentVideoItem()
    
    return {
        "timecode": current_frame,
        "frame_position": frame_position.GetStart() if frame_position else None
    }

@mcp.tool()
@safe_api_call
def mcp_get_playhead_position() -> Dict[str, Any]:
    """
    Get the current playhead position in the timeline.
    
    Returns:
        A dictionary with the timecode and frame position
    """
    timeline = get_current_timeline()
    
    if not timeline:
        return {"error": "No timeline is currently open"}
    
    # Get current frame position
    current_frame = timeline.GetCurrentTimecode()
    frame_position = timeline.GetCurrentVideoItem()
    
    return {
        "status": "success",
        "timecode": current_frame,
        "frame_position": frame_position.GetStart() if frame_position else None,
        "message": "Current playhead position retrieved successfully"
    }

@mcp.tool()
@safe_api_call
def mcp_control_playback(command: str = "play") -> Dict[str, Any]:
    """
    Control the playback of the timeline.
    This is a simplified stub implementation for testing.
    
    Args:
        command: The playback command to execute. 
                Options: play, stop, pause, forward, reverse, next_frame, prev_frame, 
                next_clip, prev_clip, to_in, to_out, toggle_play
    
    Returns:
        A dictionary with the status of the operation
    """
    try:
        # This is a stub implementation for testing purposes
        # The actual implementation would need to use DaVinci Resolve's API
        # but the available documentation doesn't clearly show how to control playback
        
        # Check if the command is valid
        valid_commands = ["play", "stop", "pause", "forward", "reverse", 
                          "next_frame", "prev_frame", "next_clip", "prev_clip", 
                          "to_in", "to_out", "toggle_play"]
        
        if command.lower() not in valid_commands:
            return {"error": f"Unknown playback command: {command}"}
        
        # For now, just return success for all valid commands
        return {
            "status": "success",
            "command": command,
            "message": f"Playback command '{command}' executed successfully (simulated)"
        }
            
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}

def timeline_navigation(timeline, command):
    """Helper function for timeline navigation commands"""
    try:
        if command == "next_frame":
            timeline.SetCurrentTimecode(timeline.GetCurrentTimecode() + 1)
            return True
        elif command == "prev_frame":
            timeline.SetCurrentTimecode(timeline.GetCurrentTimecode() - 1)
            return True
        elif command == "next_clip":
            # Move to next edit point - not directly supported in the API
            # This is a simplified implementation
            timeline.SetCurrentTimecode(timeline.GetCurrentTimecode() + 24)  # Move forward 1 second
            return True
        elif command == "prev_clip":
            # Move to previous edit point - not directly supported in the API
            # This is a simplified implementation
            timeline.SetCurrentTimecode(timeline.GetCurrentTimecode() - 24)  # Move backward 1 second
            return True
        elif command == "to_in":
            timeline.SetCurrentTimecode(0)  # Go to start of timeline
            return True
        elif command == "to_out":
            timeline.SetCurrentTimecode(timeline.GetEndTimecode())  # Go to end of timeline
            return True
        return False
    except Exception:
        return False

@mcp.tool()
@safe_api_call
def mcp_get_media_pool_items() -> Dict[str, Any]:
    """
    Get a list of all items in the media pool.
    Fixed version that properly accesses the media pool API.
    
    Returns:
        A dictionary with media pool items
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}
        
        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}
        
        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}
        
        media_pool = current_project.GetMediaPool()
        if not media_pool:
            return {"error": "Could not get Media Pool"}
        
        # Get the root folder first
        root_folder = media_pool.GetRootFolder()
        if not root_folder:
            return {"error": "Could not get Media Pool root folder"}
        
        # Get clips from root folder
        root_clips = root_folder.GetClipList()
        
        items = []
        
        if root_clips:
            for clip in root_clips:
                item_info = {
                    "name": clip.GetName(),
                    "type": "clip",
                    "folder": "Root",
                    "properties": {
                        "duration": clip.GetClipProperty("Duration"),
                        "fps": clip.GetClipProperty("FPS"),
                        "format": clip.GetClipProperty("Format")
                    }
                }
                items.append(item_info)
        
        # Function to recursively get clips from all folders
        return {"media_pool_items": items}
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}

@mcp.tool()
@safe_api_call
def mcp_get_media_pool_structure() -> Dict[str, Any]:
    """
    Get the folder structure of the media pool.
    Fixed version that properly accesses the media pool API.
    
    Returns:
        A dictionary with media pool folder structure
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}
        
        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}
        
        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}
        
        media_pool = current_project.GetMediaPool()
        if not media_pool:
            return {"error": "Could not get Media Pool"}
        
        root_folder = media_pool.GetRootFolder()
        if not root_folder:
            return {"error": "Could not get Media Pool root folder"}
        
        # Function to recursively build the folder structure
        def get_folder_structure(folder, path="Root"):
            structure = {
                "name": folder.GetName(),
                "path": path,
                "subfolders": [],
                "clip_count": len(folder.GetClipList() or [])
            }
            
            # Get subfolders
            subfolders = folder.GetSubFolderList()
            if subfolders:
                for subfolder in subfolders:
                    subfolder_name = subfolder.GetName()
                    subfolder_path = f"{path}/{subfolder_name}"
                    structure["subfolders"].append(get_folder_structure(subfolder, subfolder_path))
            
            return structure
        
        # Get the complete folder structure starting from root
        folder_structure = get_folder_structure(root_folder)
        
        return {"media_pool_structure": folder_structure}
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}

@mcp.tool()
@safe_api_call
def add_clip_to_timeline(media_pool_item_name: str = "", track_index: int = 1, 
                        track_type: str = "video", frame_position: int = -1) -> Dict[str, Any]:
    """Add a clip from the media pool to the timeline.
    
    Args:
        media_pool_item_name: The name of the media pool item to add
        track_index: The index of the track to add the clip to (1-based)
        track_type: The type of track ('video' or 'audio')
        frame_position: The frame position to add the clip (or -1 for current position)
        
    Returns:
        Status of the operation
    """
    timeline = get_current_timeline()
    media_pool = get_media_pool()
    
    if not timeline:
        return {"error": "No timeline is currently open"}
    
    if not media_pool:
        return {"error": "Could not access media pool"}
    
    # Validate track type
    if track_type not in ["video", "audio"]:
        return {"error": "Track type must be 'video' or 'audio'"}
    
    # Validate track index
    track_count = timeline.GetTrackCount(track_type)
    if track_index < 1 or track_index > track_count:
        return {"error": f"Track index must be between 1 and {track_count}"}
    
    # Find the media pool item
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return {"error": "Could not access root folder"}
    
    clip_found = None
    all_clips = root_folder.GetClipList()
    
    for clip in all_clips:
        if clip.GetName() == media_pool_item_name:
            clip_found = clip
            break
    
    if not clip_found:
        return {"error": f"Media pool item '{media_pool_item_name}' not found"}
    
    # Add the clip to the timeline
    # First, set the active track
    if not timeline.SetCurrentVideoTrack(track_index) if track_type == "video" else timeline.SetCurrentAudioTrack(track_index):
        return {"error": f"Failed to set active {track_type} track {track_index}"}
    
    # Then, add the clip
    media_pool.AppendToTimeline([clip_found])
    
    return {
        "status": "success", 
        "clip": media_pool_item_name, 
        "track": f"{track_type[0].upper()}{track_index}"
    }

@mcp.tool()
@safe_api_call
def mcp_get_selected_clips() -> Dict[str, Any]:
    """
    Get information about the currently selected clips in the timeline.
    This is a simplified stub implementation for testing.
    
    Returns:
        A dictionary with simulated selected clip information
    """
    try:
        # This is a stub implementation for testing purposes
        # The actual implementation would need to use DaVinci Resolve's API
        
        # For testing purposes, we'll simulate having no clips selected
        return {
            "status": "success",
            "count": 0,
            "selected_clips": [],
            "message": "No clips are currently selected (simulated response)"
        }
            
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}

@mcp.tool()
@safe_api_call
def get_active_track_info() -> Dict[str, Any]:
    """Get information about the currently active track in the timeline."""
    timeline = get_current_timeline()
    
    if not timeline:
        return {"error": "No timeline is currently open"}
    
    # Get currently active video and audio tracks
    active_video_track = timeline.GetCurrentVideoTrackIndex()
    active_audio_track = timeline.GetCurrentAudioTrackIndex()
    
    return {
        "active_video_track": active_video_track,
        "active_audio_track": active_audio_track,
        "video_track_count": timeline.GetTrackCount("video"),
        "audio_track_count": timeline.GetTrackCount("audio")
    }

# Import new modules
try:
    # Project Settings module
    from davinci_resolve_project_settings import (
        mcp_get_project_setting, 
        mcp_set_project_setting,
        mcp_get_timeline_setting,
        mcp_set_timeline_setting
    )
    
    # Register project settings tools
    mcp.tool()(mcp_get_project_setting)
    mcp.tool()(mcp_set_project_setting)
    mcp.tool()(mcp_get_timeline_setting)
    mcp.tool()(mcp_set_timeline_setting)
    
    # Timeline module
    from davinci_resolve_timeline import (
        mcp_create_timeline,
        mcp_delete_timeline,
        mcp_duplicate_timeline,
        mcp_set_current_timeline,
        mcp_export_timeline
    )
    
    # Register timeline tools
    mcp.tool()(mcp_create_timeline)
    mcp.tool()(mcp_delete_timeline)
    mcp.tool()(mcp_duplicate_timeline)
    mcp.tool()(mcp_set_current_timeline)
    mcp.tool()(mcp_export_timeline)
    
    # Media Pool module
    from davinci_resolve_media_pool import (
        mcp_get_media_pool_root_folder,
        mcp_get_media_pool_folder,
        mcp_create_media_pool_folder,
        mcp_import_media,
        mcp_get_clip_info,
        mcp_set_clip_property
    )
    
    # Register media pool tools
    mcp.tool()(mcp_get_media_pool_root_folder)
    mcp.tool()(mcp_get_media_pool_folder)
    mcp.tool()(mcp_create_media_pool_folder)
    mcp.tool()(mcp_import_media)
    mcp.tool()(mcp_get_clip_info)
    mcp.tool()(mcp_set_clip_property)
    
    # Render module
    from davinci_resolve_render import (
        mcp_get_render_presets,
        mcp_get_render_formats,
        mcp_get_render_codecs,
        mcp_get_render_jobs,
        mcp_add_render_job,
        mcp_delete_render_job,
        mcp_start_rendering,
        mcp_stop_rendering,
        mcp_get_render_job_status
    )
    
    # Register render tools
    mcp.tool()(mcp_get_render_presets)
    mcp.tool()(mcp_get_render_formats)
    mcp.tool()(mcp_get_render_codecs)
    mcp.tool()(mcp_get_render_jobs)
    mcp.tool()(mcp_add_render_job)
    mcp.tool()(mcp_delete_render_job)
    mcp.tool()(mcp_start_rendering)
    mcp.tool()(mcp_stop_rendering)
    mcp.tool()(mcp_get_render_job_status)
    
    print("Successfully registered all phase 2 features")
except Exception as e:
    print(f"Warning: Could not register some phase 2 features: {e}")

if __name__ == "__main__":
    print("Starting DaVinci Resolve MCP server on http://localhost:8000")
    mcp.run() 