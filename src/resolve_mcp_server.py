#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server
A server that connects to DaVinci Resolve via the Model Context Protocol (MCP)

Version: 2.0.1 - Bug Fixes, Consolidated Tool Features
"""

import os
import sys
import logging
from typing import List, Dict, Any, Optional, Union

# Add src directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Import platform utilities
from src.utils.platform import setup_environment, get_platform, get_resolve_paths

# Setup platform-specific paths and environment variables
paths = get_resolve_paths()
RESOLVE_API_PATH = paths["api_path"]
RESOLVE_LIB_PATH = paths["lib_path"]
RESOLVE_MODULES_PATH = paths["modules_path"]

os.environ["RESOLVE_SCRIPT_API"] = RESOLVE_API_PATH
os.environ["RESOLVE_SCRIPT_LIB"] = RESOLVE_LIB_PATH

# Add the module path to Python's path if it's not already there
if RESOLVE_MODULES_PATH not in sys.path:
    sys.path.append(RESOLVE_MODULES_PATH)

# Import MCP
from mcp.server.fastmcp import FastMCP

# Import our utility functions
from src.utils.platform import setup_environment, get_platform, get_resolve_paths
from src.utils.object_inspection import (
    inspect_object,
    get_object_methods,
    get_object_properties,
    print_object_help,
    convert_lua_to_python
)
from src.utils.layout_presets import (
    list_layout_presets,
    save_layout_preset,
    load_layout_preset,
    export_layout_preset,
    import_layout_preset,
    delete_layout_preset
)
from src.utils.app_control import (
    quit_resolve_app,
    get_app_state,
    restart_resolve_app,
    open_project_settings,
    open_preferences
)
from src.utils.cloud_operations import (
    create_cloud_project,
    import_cloud_project,
    restore_cloud_project,
    get_cloud_project_list,
    export_project_to_cloud,
    add_user_to_cloud_project,
    remove_user_from_cloud_project
)
from src.utils.project_properties import (
    get_all_project_properties,
    get_project_property,
    set_project_property,
    get_timeline_format_settings,
    set_timeline_format,
    get_superscale_settings,
    set_superscale_settings,
    get_color_settings,
    set_color_science_mode,
    set_color_space,
    get_project_metadata,
    get_project_info
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("davinci-resolve-mcp")

# Log server version and platform
VERSION = "2.0.1"
logger.info(f"Starting DaVinci Resolve MCP Server v{VERSION}")
logger.info(f"Detected platform: {get_platform()}")
logger.info(f"Using Resolve API path: {RESOLVE_API_PATH}")
logger.info(f"Using Resolve library path: {RESOLVE_LIB_PATH}")

# Create MCP server instance
mcp = FastMCP("DaVinciResolveMCP")

# Initialize connection to DaVinci Resolve
try:
    # Direct import from the Modules directory
    sys.path.insert(0, RESOLVE_MODULES_PATH)
    import DaVinciResolveScript as dvr_script
    resolve = dvr_script.scriptapp("Resolve")
    if resolve:
        logger.info(f"Connected to DaVinci Resolve: {resolve.GetProductName()} {resolve.GetVersionString()}")
    else:
        logger.error("Failed to get Resolve object. Is DaVinci Resolve running?")
except ImportError as e:
    logger.error(f"Failed to import DaVinciResolveScript: {str(e)}")
    logger.error("Check that DaVinci Resolve is installed and running.")
    logger.error(f"RESOLVE_SCRIPT_API: {RESOLVE_API_PATH}")
    logger.error(f"RESOLVE_SCRIPT_LIB: {RESOLVE_LIB_PATH}")
    logger.error(f"RESOLVE_MODULES_PATH: {RESOLVE_MODULES_PATH}")
    logger.error(f"sys.path: {sys.path}")
    resolve = None
except Exception as e:
    logger.error(f"Unexpected error initializing Resolve: {str(e)}")
    resolve = None

# ------------------
# MCP Tools/Resources
# ------------------

@mcp.resource("resolve://version")
def get_resolve_version() -> str:
    """Get DaVinci Resolve version information."""
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    return f"{resolve.GetProductName()} {resolve.GetVersionString()}"

@mcp.resource("resolve://current-page")
def get_current_page() -> str:
    """Get the current page open in DaVinci Resolve (Edit, Color, Fusion, etc.)."""
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    return resolve.GetCurrentPage()

@mcp.tool()
def switch_page(page: str) -> str:
    """Switch to a specific page in DaVinci Resolve.
    
    Args:
        page: The page to switch to. Options: 'media', 'cut', 'edit', 'fusion', 'color', 'fairlight', 'deliver'
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    valid_pages = ['media', 'cut', 'edit', 'fusion', 'color', 'fairlight', 'deliver']
    page = page.lower()
    
    if page not in valid_pages:
        return f"Error: Invalid page name. Must be one of: {', '.join(valid_pages)}"
    
    result = resolve.OpenPage(page)
    if result:
        return f"Successfully switched to {page} page"
    else:
        return f"Failed to switch to {page} page"

# ------------------
# Project Management
# ------------------

@mcp.resource("resolve://projects")
def list_projects() -> List[str]:
    """List all available projects in the current database."""
    if resolve is None:
        return ["Error: Not connected to DaVinci Resolve"]
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return ["Error: Failed to get Project Manager"]
    
    projects = project_manager.GetProjectListInCurrentFolder()
    
    # Filter out any empty strings that might be in the list
    return [p for p in projects if p]

@mcp.resource("resolve://current-project")
def get_current_project_name() -> str:
    """Get the name of the currently open project."""
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "No project currently open"
    
    return current_project.GetName()

@mcp.resource("resolve://project-settings")
def get_project_settings() -> Dict[str, Any]:
    """Get all project settings from the current project."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    try:
        # Get all settings
        return current_project.GetSetting('')
    except Exception as e:
        return {"error": f"Failed to get project settings: {str(e)}"}

@mcp.resource("resolve://project-setting/{setting_name}")
def get_project_setting(setting_name: str) -> Dict[str, Any]:
    """Get a specific project setting by name.
    
    Args:
        setting_name: The specific setting to retrieve.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    try:
        # Get specific setting
        value = current_project.GetSetting(setting_name)
        return {setting_name: value}
    except Exception as e:
        return {"error": f"Failed to get project setting '{setting_name}': {str(e)}"}

@mcp.tool()
def set_project_setting(setting_name: str, setting_value: Any) -> str:
    """Set a project setting to the specified value.
    
    Args:
        setting_name: The name of the setting to change
        setting_value: The new value for the setting (can be string, integer, float, or boolean)
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    try:
        # Convert setting_value to string if it's not already
        if not isinstance(setting_value, str):
            setting_value = str(setting_value)
            
        # Try to determine if this should be a numeric value
        # DaVinci Resolve sometimes expects numeric values for certain settings
        try:
            # Check if it's a number in string form
            if setting_value.isdigit() or (setting_value.startswith('-') and setting_value[1:].isdigit()):
                # It's an integer
                numeric_value = int(setting_value)
                # Try with numeric value first
                if current_project.SetSetting(setting_name, numeric_value):
                    return f"Successfully set project setting '{setting_name}' to numeric value {numeric_value}"
            elif '.' in setting_value and setting_value.replace('.', '', 1).replace('-', '', 1).isdigit():
                # It's a float
                numeric_value = float(setting_value)
                # Try with float value
                if current_project.SetSetting(setting_name, numeric_value):
                    return f"Successfully set project setting '{setting_name}' to numeric value {numeric_value}"
        except (ValueError, TypeError):
            # Not a number or conversion failed, continue with string value
            pass
            
        # Fall back to string value if numeric didn't work or wasn't applicable
        result = current_project.SetSetting(setting_name, setting_value)
        if result:
            return f"Successfully set project setting '{setting_name}' to '{setting_value}'"
        else:
            return f"Failed to set project setting '{setting_name}'"
    except Exception as e:
        return f"Error setting project setting: {str(e)}"

@mcp.tool()
def open_project(name: str) -> str:
    """Open a project by name.
    
    Args:
        name: The name of the project to open
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    if not name:
        return "Error: Project name cannot be empty"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    # Check if project exists
    projects = project_manager.GetProjectListInCurrentFolder()
    if name not in projects:
        return f"Error: Project '{name}' not found. Available projects: {', '.join(projects)}"
    
    result = project_manager.LoadProject(name)
    if result:
        return f"Successfully opened project '{name}'"
    else:
        return f"Failed to open project '{name}'"

@mcp.tool()
def create_project(name: str) -> str:
    """Create a new project with the given name.
    
    Args:
        name: The name for the new project
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    if not name:
        return "Error: Project name cannot be empty"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    # Check if project already exists
    projects = project_manager.GetProjectListInCurrentFolder()
    if name in projects:
        return f"Error: Project '{name}' already exists"
    
    result = project_manager.CreateProject(name)
    if result:
        return f"Successfully created project '{name}'"
    else:
        return f"Failed to create project '{name}'"

@mcp.tool()
def save_project() -> str:
    """Save the current project.
    
    Note that DaVinci Resolve typically auto-saves projects, so this may not be necessary.
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    project_name = current_project.GetName()
    success = False
    error_message = None
    
    # Try multiple approaches to save the project
    try:
        # Method 1: Try direct save method if available
        try:
            if hasattr(current_project, "SaveProject"):
                result = current_project.SaveProject()
                if result:
                    logger.info(f"Project '{project_name}' saved using SaveProject method")
                    success = True
        except Exception as e:
            logger.error(f"Error in SaveProject method: {str(e)}")
            error_message = str(e)
            
        # Method 2: Try project manager save method
        if not success:
            try:
                if hasattr(project_manager, "SaveProject"):
                    result = project_manager.SaveProject()
                    if result:
                        logger.info(f"Project '{project_name}' saved using ProjectManager.SaveProject method")
                        success = True
            except Exception as e:
                logger.error(f"Error in ProjectManager.SaveProject method: {str(e)}")
                if not error_message:
                    error_message = str(e)
        
        # Method 3: Try the export method as a backup approach
        if not success:
            try:
                # Get a temporary file path in the same location as other project files
                import tempfile
                import os
                temp_dir = tempfile.gettempdir()
                temp_file = os.path.join(temp_dir, f"{project_name}_temp.drp")
                
                # Try to export the project, which should trigger a save
                result = project_manager.ExportProject(project_name, temp_file)
                if result:
                    logger.info(f"Project '{project_name}' saved via temporary export to {temp_file}")
                    # Try to clean up temp file
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except:
                        pass
                    success = True
            except Exception as e:
                logger.error(f"Error in export method: {str(e)}")
                if not error_message:
                    error_message = str(e)
                    
        # If all else fails, rely on auto-save
        if not success:
            return f"Automatic save likely in effect for project '{project_name}'. Manual save attempts failed: {error_message if error_message else 'Unknown error'}"
        else:
            return f"Successfully saved project '{project_name}'"
            
    except Exception as e:
        logger.error(f"Error saving project: {str(e)}")
        return f"Error saving project: {str(e)}"

@mcp.tool()
def close_project() -> str:
    """Close the current project.
    
    This closes the current project without saving. If you need to save, use the save_project function first.
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    project_name = current_project.GetName()
    
    # Close the project
    try:
        result = project_manager.CloseProject(current_project)
        if result:
            logger.info(f"Project '{project_name}' closed successfully")
            return f"Successfully closed project '{project_name}'"
        else:
            logger.error(f"Failed to close project '{project_name}'")
            return f"Failed to close project '{project_name}'"
    except Exception as e:
        logger.error(f"Error closing project: {str(e)}")
        return f"Error closing project: {str(e)}"

# ------------------
# Timeline Operations
# ------------------

@mcp.resource("resolve://timelines")
def list_timelines() -> List[str]:
    """List all timelines in the current project."""
    logger.info("Received request to list timelines")
    
    if resolve is None:
        logger.error("Not connected to DaVinci Resolve")
        return ["Error: Not connected to DaVinci Resolve"]
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        logger.error("Failed to get Project Manager")
        return ["Error: Failed to get Project Manager"]
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        logger.error("No project currently open")
        return ["Error: No project currently open"]
    
    timeline_count = current_project.GetTimelineCount()
    logger.info(f"Timeline count: {timeline_count}")
    
    timelines = []
    
    for i in range(1, timeline_count + 1):
        timeline = current_project.GetTimelineByIndex(i)
        if timeline:
            timeline_name = timeline.GetName()
            timelines.append(timeline_name)
            logger.info(f"Found timeline {i}: {timeline_name}")
    
    if not timelines:
        logger.info("No timelines found in the current project")
        return ["No timelines found in the current project"]
    
    logger.info(f"Returning {len(timelines)} timelines: {', '.join(timelines)}")
    return timelines

@mcp.resource("resolve://current-timeline")
def get_current_timeline() -> Dict[str, Any]:
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
    
    # Get basic timeline information
    result = {
        "name": current_timeline.GetName(),
        "fps": current_timeline.GetSetting("timelineFrameRate"),
        "resolution": {
            "width": current_timeline.GetSetting("timelineResolutionWidth"),
            "height": current_timeline.GetSetting("timelineResolutionHeight")
        },
        "duration": current_timeline.GetEndFrame() - current_timeline.GetStartFrame() + 1
    }
    
    return result

@mcp.resource("resolve://timeline-tracks/{timeline_name}")
def get_timeline_tracks(timeline_name: str = None) -> Dict[str, Any]:
    """Get the track structure of a timeline.
    
    Args:
        timeline_name: Optional name of the timeline to get tracks from. Uses current timeline if None.
    """
    from api.timeline_operations import get_timeline_tracks as get_tracks_func
    return get_tracks_func(resolve, timeline_name)

@mcp.tool()
def create_timeline(name: str) -> str:
    """Create a new timeline with the given name.
    
    Args:
        name: The name for the new timeline
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
    
    timeline = media_pool.CreateEmptyTimeline(name)
    if timeline:
        return f"Successfully created timeline '{name}'"
    else:
        return f"Failed to create timeline '{name}'"

@mcp.tool()
def create_empty_timeline(name: str, 
                       frame_rate: str = None, 
                       resolution_width: int = None, 
                       resolution_height: int = None,
                       start_timecode: str = None,
                       video_tracks: int = None,
                       audio_tracks: int = None) -> str:
    """Create a new timeline with the given name and custom settings.
    
    Args:
        name: The name for the new timeline
        frame_rate: Optional frame rate (e.g. "24", "29.97", "30", "60")
        resolution_width: Optional width in pixels (e.g. 1920)
        resolution_height: Optional height in pixels (e.g. 1080)
        start_timecode: Optional start timecode (e.g. "01:00:00:00")
        video_tracks: Optional number of video tracks (Default is project setting)
        audio_tracks: Optional number of audio tracks (Default is project setting)
    """
    from api.timeline_operations import create_empty_timeline as create_empty_timeline_func
    return create_empty_timeline_func(resolve, name, frame_rate, resolution_width, 
                                    resolution_height, start_timecode, 
                                    video_tracks, audio_tracks)

@mcp.tool()
def delete_timeline(name: str) -> str:
    """Delete a timeline by name.
    
    Args:
        name: The name of the timeline to delete
    """
    from api.timeline_operations import delete_timeline as delete_timeline_func
    return delete_timeline_func(resolve, name)

@mcp.tool()
def set_current_timeline(name: str) -> str:
    """Switch to a timeline by name.
    
    Args:
        name: The name of the timeline to set as current
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
    
    # Find the timeline by name
    timeline_count = current_project.GetTimelineCount()
    for i in range(1, timeline_count + 1):
        timeline = current_project.GetTimelineByIndex(i)
        if timeline and timeline.GetName() == name:
            result = current_project.SetCurrentTimeline(timeline)
            if result:
                return f"Successfully switched to timeline '{name}'"
            else:
                return f"Failed to switch to timeline '{name}'"
    
    return f"Error: Timeline '{name}' not found"

@mcp.tool()
def add_marker(frame: int = None, color: str = "Blue", note: str = "") -> str:
    """Add a marker at the specified frame in the current timeline.
    
    Args:
        frame: The frame number to add the marker at (defaults to current position if None)
        color: The marker color (Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream)
        note: Text note to add to the marker
    """
    from api.timeline_operations import add_marker as add_marker_func
    return add_marker_func(resolve, frame, color, note)

# ------------------
# Media Pool Operations
# ------------------

@mcp.resource("resolve://media-pool-clips")
def list_media_pool_clips() -> List[Dict[str, Any]]:
    """List all clips in the root folder of the media pool."""
    if resolve is None:
        return [{"error": "Not connected to DaVinci Resolve"}]
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return [{"error": "Failed to get Project Manager"}]
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return [{"error": "No project currently open"}]
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return [{"error": "Failed to get Media Pool"}]
    
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return [{"error": "Failed to get root folder"}]
    
    clips = root_folder.GetClipList()
    if not clips:
        return [{"info": "No clips found in the root folder"}]
    
    # Return a simplified list with basic clip info
    result = []
    for clip in clips:
        result.append({
            "name": clip.GetName(),
            "duration": clip.GetDuration(),
            "fps": clip.GetClipProperty("FPS")
        })
    
    return result

@mcp.tool()
def import_media(file_path: str) -> str:
    """Import media file into the current project's media pool.
    
    Args:
        file_path: The path to the media file to import
    """
    from api.media_operations import import_media as import_media_func
    return import_media_func(resolve, file_path)

@mcp.tool()
def delete_media(clip_name: str) -> str:
    """Delete a media clip from the media pool by name.
    
    Args:
        clip_name: Name of the clip to delete
    """
    from api.media_operations import delete_media as delete_media_func
    return delete_media_func(resolve, clip_name)

@mcp.tool()
def move_media_to_bin(clip_name: str, bin_name: str) -> str:
    """Move a media clip to a specific bin in the media pool.
    
    Args:
        clip_name: Name of the clip to move
        bin_name: Name of the target bin
    """
    from api.media_operations import move_media_to_bin as move_media_func
    return move_media_func(resolve, clip_name, bin_name)

@mcp.tool()
def auto_sync_audio(clip_names: List[str], sync_method: str = "waveform", 
                   append_mode: bool = False, target_bin: str = None) -> str:
    """Sync audio between clips with customizable settings.
    
    Args:
        clip_names: List of clip names to sync
        sync_method: Method to use for synchronization - 'waveform' or 'timecode'
        append_mode: Whether to append the audio or replace it
        target_bin: Optional bin to move synchronized clips to
    """
    from api.media_operations import auto_sync_audio as auto_sync_audio_func
    return auto_sync_audio_func(resolve, clip_names, sync_method, append_mode, target_bin)

@mcp.tool()
def unlink_clips(clip_names: List[str]) -> str:
    """Unlink specified clips, disconnecting them from their media files.
    
    Args:
        clip_names: List of clip names to unlink
    """
    from api.media_operations import unlink_clips as unlink_clips_func
    return unlink_clips_func(resolve, clip_names)

@mcp.tool()
def relink_clips(clip_names: List[str], media_paths: List[str] = None, 
                folder_path: str = None, recursive: bool = False) -> str:
    """Relink specified clips to their media files.
    
    Args:
        clip_names: List of clip names to relink
        media_paths: Optional list of specific media file paths to use for relinking
        folder_path: Optional folder path to search for media files
        recursive: Whether to search the folder path recursively
    """
    from api.media_operations import relink_clips as relink_clips_func
    return relink_clips_func(resolve, clip_names, media_paths, folder_path, recursive)

@mcp.tool()
def create_sub_clip(clip_name: str, start_frame: int, end_frame: int, 
                   sub_clip_name: str = None, bin_name: str = None) -> str:
    """Create a subclip from the specified clip using in and out points.
    
    Args:
        clip_name: Name of the source clip
        start_frame: Start frame (in point)
        end_frame: End frame (out point)
        sub_clip_name: Optional name for the subclip (defaults to original name with '_subclip')
        bin_name: Optional bin to place the subclip in
    """
    from api.media_operations import create_sub_clip as create_sub_clip_func
    return create_sub_clip_func(resolve, clip_name, start_frame, end_frame, sub_clip_name, bin_name)

@mcp.tool()
def create_bin(name: str) -> str:
    """Create a new bin/folder in the media pool.
    
    Args:
        name: The name for the new bin
    """
    from api.media_operations import create_bin as create_bin_func
    return create_bin_func(resolve, name)

@mcp.resource("resolve://media-pool-bins")
def list_media_pool_bins() -> List[Dict[str, Any]]:
    """List all bins/folders in the media pool."""
    from api.media_operations import list_bins as list_bins_func
    return list_bins_func(resolve)

@mcp.resource("resolve://media-pool-bin/{bin_name}")
def get_media_pool_bin_contents(bin_name: str) -> List[Dict[str, Any]]:
    """Get contents of a specific bin/folder in the media pool.
    
    Args:
        bin_name: The name of the bin to get contents from. Use 'Master' for the root folder.
    """
    from api.media_operations import get_bin_contents as get_bin_contents_func
    return get_bin_contents_func(resolve, bin_name)

@mcp.resource("resolve://timeline-clips")
def list_timeline_clips() -> List[Dict[str, Any]]:
    """List all clips in the current timeline."""
    if resolve is None:
        return [{"error": "Not connected to DaVinci Resolve"}]
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return [{"error": "Failed to get Project Manager"}]
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return [{"error": "No project currently open"}]
    
    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        return [{"error": "No timeline currently active"}]
    
    try:
        # Get all tracks in the timeline
        # Video tracks are 1-based index (1 is first track)
        video_track_count = current_timeline.GetTrackCount("video")
        audio_track_count = current_timeline.GetTrackCount("audio")
        
        clips = []
        
        # Process video tracks
        for track_index in range(1, video_track_count + 1):
            track_items = current_timeline.GetItemListInTrack("video", track_index)
            if track_items:
                for item in track_items:
                    clips.append({
                        "name": item.GetName(),
                        "type": "video",
                        "track": track_index,
                        "start_frame": item.GetStart(),
                        "end_frame": item.GetEnd(),
                        "duration": item.GetDuration()
                    })
        
        # Process audio tracks
        for track_index in range(1, audio_track_count + 1):
            track_items = current_timeline.GetItemListInTrack("audio", track_index)
            if track_items:
                for item in track_items:
                    clips.append({
                        "name": item.GetName(),
                        "type": "audio",
                        "track": track_index,
                        "start_frame": item.GetStart(),
                        "end_frame": item.GetEnd(),
                        "duration": item.GetDuration()
                    })
        
        if not clips:
            return [{"info": "No clips found in the current timeline"}]
        
        return clips
    except Exception as e:
        return [{"error": f"Error listing timeline clips: {str(e)}"}]

@mcp.tool()
def list_timelines_tool() -> List[str]:
    """List all timelines in the current project as a tool."""
    logger.info("Received request to list timelines via tool")
    return list_timelines()

@mcp.tool()
def add_clip_to_timeline(clip_name: str, timeline_name: str = None) -> str:
    """Add a media pool clip to the timeline.
    
    Args:
        clip_name: Name of the clip in the media pool
        timeline_name: Optional timeline to target (uses current if not specified)
    """
    from api.media_operations import add_clip_to_timeline as add_clip_func
    return add_clip_func(resolve, clip_name, timeline_name)

# ------------------
# Color Page Operations
# ------------------

@mcp.resource("resolve://color/current-node")
def get_current_color_node() -> Dict[str, Any]:
    """Get information about the current node in the color page."""
    from api.color_operations import get_current_node as get_node_func
    return get_node_func(resolve)

@mcp.resource("resolve://color/wheels/{node_index}")
def get_color_wheel_params(node_index: int = None) -> Dict[str, Any]:
    """Get color wheel parameters for a specific node.
    
    Args:
        node_index: Index of the node to get color wheels from (uses current node if None)
    """
    from api.color_operations import get_color_wheels as get_wheels_func
    return get_wheels_func(resolve, node_index)

@mcp.tool()
def apply_lut(lut_path: str, node_index: int = None) -> str:
    """Apply a LUT to a node in the color page.
    
    Args:
        lut_path: Path to the LUT file to apply
        node_index: Index of the node to apply the LUT to (uses current node if None)
    """
    from api.color_operations import apply_lut as apply_lut_func
    return apply_lut_func(resolve, lut_path, node_index)

@mcp.tool()
def set_color_wheel_param(wheel: str, param: str, value: float, node_index: int = None) -> str:
    """Set a color wheel parameter for a node.
    
    Args:
        wheel: Which color wheel to adjust ('lift', 'gamma', 'gain', 'offset')
        param: Which parameter to adjust ('red', 'green', 'blue', 'master')
        value: The value to set (typically between -1.0 and 1.0)
        node_index: Index of the node to set parameter for (uses current node if None)
    """
    from api.color_operations import set_color_wheel_param as set_param_func
    return set_param_func(resolve, wheel, param, value, node_index)

@mcp.tool()
def add_node(node_type: str = "serial", label: str = None) -> str:
    """Add a new node to the current grade in the color page.
    
    Args:
        node_type: Type of node to add. Options: 'serial', 'parallel', 'layer'
        label: Optional label/name for the new node
    """
    from api.color_operations import add_node as add_node_func
    return add_node_func(resolve, node_type, label)

@mcp.tool()
def copy_grade(source_clip_name: str = None, target_clip_name: str = None, mode: str = "full") -> str:
    """Copy a grade from one clip to another in the color page.
    
    Args:
        source_clip_name: Name of the source clip to copy grade from (uses current clip if None)
        target_clip_name: Name of the target clip to apply grade to (uses current clip if None)
        mode: What to copy - 'full' (entire grade), 'current_node', or 'all_nodes'
    """
    from api.color_operations import copy_grade as copy_grade_func
    return copy_grade_func(resolve, source_clip_name, target_clip_name, mode)

# ------------------
# Delivery Page Operations
# ------------------

@mcp.resource("resolve://delivery/render-presets")
def get_render_presets() -> List[Dict[str, Any]]:
    """Get all available render presets in the current project."""
    from api.delivery_operations import get_render_presets as get_presets_func
    return get_presets_func(resolve)

@mcp.tool()
def add_to_render_queue(preset_name: str, timeline_name: str = None, use_in_out_range: bool = False) -> Dict[str, Any]:
    """Add a timeline to the render queue with the specified preset.
    
    Args:
        preset_name: Name of the render preset to use
        timeline_name: Name of the timeline to render (uses current if None)
        use_in_out_range: Whether to render only the in/out range instead of entire timeline
    """
    from api.delivery_operations import add_to_render_queue as add_queue_func
    return add_queue_func(resolve, preset_name, timeline_name, use_in_out_range)

@mcp.tool()
def start_render() -> Dict[str, Any]:
    """Start rendering the jobs in the render queue."""
    from api.delivery_operations import start_render as start_render_func
    return start_render_func(resolve)

@mcp.resource("resolve://delivery/render-queue/status")
def get_render_queue_status() -> Dict[str, Any]:
    """Get the status of jobs in the render queue."""
    from api.delivery_operations import get_render_queue_status as get_status_func
    return get_status_func(resolve)

@mcp.tool()
def clear_render_queue() -> Dict[str, Any]:
    """Clear all jobs from the render queue."""
    from api.delivery_operations import clear_render_queue as clear_queue_func
    return clear_queue_func(resolve)

@mcp.tool()
def link_proxy_media(clip_name: str, proxy_file_path: str) -> str:
    """Link a proxy media file to a clip.
    
    Args:
        clip_name: Name of the clip to link proxy to
        proxy_file_path: Path to the proxy media file
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Find the clip by name
    clips = get_all_media_pool_clips(media_pool)
    target_clip = None
    
    for clip in clips:
        if clip.GetName() == clip_name:
            target_clip = clip
            break
    
    if not target_clip:
        return f"Error: Clip '{clip_name}' not found in Media Pool"
    
    # Check if file exists
    if not os.path.exists(proxy_file_path):
        return f"Error: Proxy file '{proxy_file_path}' does not exist"
    
    try:
        result = target_clip.LinkProxyMedia(proxy_file_path)
        if result:
            return f"Successfully linked proxy media '{proxy_file_path}' to clip '{clip_name}'"
        else:
            return f"Failed to link proxy media to clip '{clip_name}'"
    except Exception as e:
        return f"Error linking proxy media: {str(e)}"

@mcp.tool()
def unlink_proxy_media(clip_name: str) -> str:
    """Unlink proxy media from a clip.
    
    Args:
        clip_name: Name of the clip to unlink proxy from
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Find the clip by name
    clips = get_all_media_pool_clips(media_pool)
    target_clip = None
    
    for clip in clips:
        if clip.GetName() == clip_name:
            target_clip = clip
            break
    
    if not target_clip:
        return f"Error: Clip '{clip_name}' not found in Media Pool"
    
    try:
        result = target_clip.UnlinkProxyMedia()
        if result:
            return f"Successfully unlinked proxy media from clip '{clip_name}'"
        else:
            return f"Failed to unlink proxy media from clip '{clip_name}'"
    except Exception as e:
        return f"Error unlinking proxy media: {str(e)}"

@mcp.tool()
def replace_clip(clip_name: str, replacement_path: str) -> str:
    """Replace a clip with another media file.
    
    Args:
        clip_name: Name of the clip to be replaced
        replacement_path: Path to the replacement media file
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Find the clip by name
    clips = get_all_media_pool_clips(media_pool)
    target_clip = None
    
    for clip in clips:
        if clip.GetName() == clip_name:
            target_clip = clip
            break
    
    if not target_clip:
        return f"Error: Clip '{clip_name}' not found in Media Pool"
    
    # Check if file exists
    if not os.path.exists(replacement_path):
        return f"Error: Replacement file '{replacement_path}' does not exist"
    
    try:
        result = target_clip.ReplaceClip(replacement_path)
        if result:
            return f"Successfully replaced clip '{clip_name}' with '{replacement_path}'"
        else:
            return f"Failed to replace clip '{clip_name}'"
    except Exception as e:
        return f"Error replacing clip: {str(e)}"

@mcp.tool()
def transcribe_audio(clip_name: str, language: str = "en-US") -> str:
    """Transcribe audio for a clip.
    
    Args:
        clip_name: Name of the clip to transcribe
        language: Language code for transcription (default: en-US)
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Find the clip by name
    clips = get_all_media_pool_clips(media_pool)
    target_clip = None
    
    for clip in clips:
        if clip.GetName() == clip_name:
            target_clip = clip
            break
    
    if not target_clip:
        return f"Error: Clip '{clip_name}' not found in Media Pool"
    
    try:
        result = target_clip.TranscribeAudio(language)
        if result:
            return f"Successfully started audio transcription for clip '{clip_name}' in language '{language}'"
        else:
            return f"Failed to start audio transcription for clip '{clip_name}'"
    except Exception as e:
        return f"Error during audio transcription: {str(e)}"

@mcp.tool()
def clear_transcription(clip_name: str) -> str:
    """Clear audio transcription for a clip.
    
    Args:
        clip_name: Name of the clip to clear transcription from
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Find the clip by name
    clips = get_all_media_pool_clips(media_pool)
    target_clip = None
    
    for clip in clips:
        if clip.GetName() == clip_name:
            target_clip = clip
            break
    
    if not target_clip:
        return f"Error: Clip '{clip_name}' not found in Media Pool"
    
    try:
        result = target_clip.ClearTranscription()
        if result:
            return f"Successfully cleared audio transcription for clip '{clip_name}'"
        else:
            return f"Failed to clear audio transcription for clip '{clip_name}'"
    except Exception as e:
        return f"Error clearing audio transcription: {str(e)}"

# Utility function to get all clips from the media pool (recursively)
def get_all_media_pool_clips(media_pool):
    """Get all clips from media pool recursively including subfolders."""
    clips = []
    root_folder = media_pool.GetRootFolder()
    
    def process_folder(folder):
        folder_clips = folder.GetClipList()
        if folder_clips:
            clips.extend(folder_clips)
        
        sub_folders = folder.GetSubFolderList()
        for sub_folder in sub_folders:
            process_folder(sub_folder)
    
    process_folder(root_folder)
    return clips

@mcp.tool()
def export_folder(folder_name: str, export_path: str, export_type: str = "DRB") -> str:
    """Export a folder to a DRB file or other format.
    
    Args:
        folder_name: Name of the folder to export
        export_path: Path to save the exported file
        export_type: Export format (DRB is default and currently the only supported option)
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Find the folder by name
    target_folder = None
    root_folder = media_pool.GetRootFolder()
    
    if folder_name.lower() == "root" or folder_name.lower() == "master":
        target_folder = root_folder
    else:
        # Search for the folder by name
        folders = get_all_media_pool_folders(media_pool)
        for folder in folders:
            if folder.GetName() == folder_name:
                target_folder = folder
                break
    
    if not target_folder:
        return f"Error: Folder '{folder_name}' not found in Media Pool"
    
    # Check if directory exists, create if not
    export_dir = os.path.dirname(export_path)
    if not os.path.exists(export_dir) and export_dir:
        try:
            os.makedirs(export_dir)
        except Exception as e:
            return f"Error creating directory for export: {str(e)}"
    
    # Export the folder
    try:
        result = target_folder.Export(export_path)
        if result:
            return f"Successfully exported folder '{folder_name}' to '{export_path}'"
        else:
            return f"Failed to export folder '{folder_name}'"
    except Exception as e:
        return f"Error exporting folder: {str(e)}"

@mcp.tool()
def transcribe_folder_audio(folder_name: str, language: str = "en-US") -> str:
    """Transcribe audio for all clips in a folder.
    
    Args:
        folder_name: Name of the folder containing clips to transcribe
        language: Language code for transcription (default: en-US)
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Find the folder by name
    target_folder = None
    root_folder = media_pool.GetRootFolder()
    
    if folder_name.lower() == "root" or folder_name.lower() == "master":
        target_folder = root_folder
    else:
        # Search for the folder by name
        folders = get_all_media_pool_folders(media_pool)
        for folder in folders:
            if folder.GetName() == folder_name:
                target_folder = folder
                break
    
    if not target_folder:
        return f"Error: Folder '{folder_name}' not found in Media Pool"
    
    # Transcribe audio in the folder
    try:
        result = target_folder.TranscribeAudio(language)
        if result:
            return f"Successfully started audio transcription for folder '{folder_name}' in language '{language}'"
        else:
            return f"Failed to start audio transcription for folder '{folder_name}'"
    except Exception as e:
        return f"Error during audio transcription: {str(e)}"

@mcp.tool()
def clear_folder_transcription(folder_name: str) -> str:
    """Clear audio transcription for all clips in a folder.
    
    Args:
        folder_name: Name of the folder to clear transcriptions from
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Find the folder by name
    target_folder = None
    root_folder = media_pool.GetRootFolder()
    
    if folder_name.lower() == "root" or folder_name.lower() == "master":
        target_folder = root_folder
    else:
        # Search for the folder by name
        folders = get_all_media_pool_folders(media_pool)
        for folder in folders:
            if folder.GetName() == folder_name:
                target_folder = folder
                break
    
    if not target_folder:
        return f"Error: Folder '{folder_name}' not found in Media Pool"
    
    # Clear transcription for the folder
    try:
        result = target_folder.ClearTranscription()
        if result:
            return f"Successfully cleared audio transcription for folder '{folder_name}'"
        else:
            return f"Failed to clear audio transcription for folder '{folder_name}'"
    except Exception as e:
        return f"Error clearing audio transcription: {str(e)}"

# Utility function to get all folders from the media pool (recursively)
def get_all_media_pool_folders(media_pool):
    """Get all folders from media pool recursively."""
    folders = []
    root_folder = media_pool.GetRootFolder()
    
    def process_folder(folder):
        folders.append(folder)
        
        sub_folders = folder.GetSubFolderList()
        for sub_folder in sub_folders:
            process_folder(sub_folder)
    
    process_folder(root_folder)
    return folders

# ------------------
# Cache Management
# ------------------

@mcp.resource("resolve://cache/settings")
def get_cache_settings() -> Dict[str, Any]:
    """Get current cache settings from the project."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    try:
        # Get all cache-related settings
        settings = {}
        cache_keys = [
            "CacheMode", 
            "CacheClipMode",
            "OptimizedMediaMode",
            "ProxyMode", 
            "ProxyQuality",
            "TimelineCacheMode",
            "LocalCachePath",
            "NetworkCachePath"
        ]
        
        for key in cache_keys:
            value = current_project.GetSetting(key)
            settings[key] = value
            
        return settings
    except Exception as e:
        return {"error": f"Failed to get cache settings: {str(e)}"}

@mcp.tool()
def set_cache_mode(mode: str) -> str:
    """Set cache mode for the current project.
    
    Args:
        mode: Cache mode to set. Options: 'auto', 'on', 'off'
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Validate mode
    valid_modes = ["auto", "on", "off"]
    mode = mode.lower()
    if mode not in valid_modes:
        return f"Error: Invalid cache mode. Must be one of: {', '.join(valid_modes)}"
    
    # Convert mode to API value
    mode_map = {
        "auto": "0",
        "on": "1",
        "off": "2"
    }
    
    try:
        result = current_project.SetSetting("CacheMode", mode_map[mode])
        if result:
            return f"Successfully set cache mode to '{mode}'"
        else:
            return f"Failed to set cache mode to '{mode}'"
    except Exception as e:
        return f"Error setting cache mode: {str(e)}"

@mcp.tool()
def set_optimized_media_mode(mode: str) -> str:
    """Set optimized media mode for the current project.
    
    Args:
        mode: Optimized media mode to set. Options: 'auto', 'on', 'off'
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Validate mode
    valid_modes = ["auto", "on", "off"]
    mode = mode.lower()
    if mode not in valid_modes:
        return f"Error: Invalid optimized media mode. Must be one of: {', '.join(valid_modes)}"
    
    # Convert mode to API value
    mode_map = {
        "auto": "0",
        "on": "1",
        "off": "2"
    }
    
    try:
        result = current_project.SetSetting("OptimizedMediaMode", mode_map[mode])
        if result:
            return f"Successfully set optimized media mode to '{mode}'"
        else:
            return f"Failed to set optimized media mode to '{mode}'"
    except Exception as e:
        return f"Error setting optimized media mode: {str(e)}"

@mcp.tool()
def set_proxy_mode(mode: str) -> str:
    """Set proxy media mode for the current project.
    
    Args:
        mode: Proxy mode to set. Options: 'auto', 'on', 'off'
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Validate mode
    valid_modes = ["auto", "on", "off"]
    mode = mode.lower()
    if mode not in valid_modes:
        return f"Error: Invalid proxy mode. Must be one of: {', '.join(valid_modes)}"
    
    # Convert mode to API value
    mode_map = {
        "auto": "0",
        "on": "1",
        "off": "2"
    }
    
    try:
        result = current_project.SetSetting("ProxyMode", mode_map[mode])
        if result:
            return f"Successfully set proxy mode to '{mode}'"
        else:
            return f"Failed to set proxy mode to '{mode}'"
    except Exception as e:
        return f"Error setting proxy mode: {str(e)}"

@mcp.tool()
def set_proxy_quality(quality: str) -> str:
    """Set proxy media quality for the current project.
    
    Args:
        quality: Proxy quality to set. Options: 'quarter', 'half', 'threeQuarter', 'full'
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Validate quality
    valid_qualities = ["quarter", "half", "threeQuarter", "full"]
    if quality not in valid_qualities:
        return f"Error: Invalid proxy quality. Must be one of: {', '.join(valid_qualities)}"
    
    # Convert quality to API value
    quality_map = {
        "quarter": "0",
        "half": "1",
        "threeQuarter": "2",
        "full": "3"
    }
    
    try:
        result = current_project.SetSetting("ProxyQuality", quality_map[quality])
        if result:
            return f"Successfully set proxy quality to '{quality}'"
        else:
            return f"Failed to set proxy quality to '{quality}'"
    except Exception as e:
        return f"Error setting proxy quality: {str(e)}"

@mcp.tool()
def set_cache_path(path_type: str, path: str) -> str:
    """Set cache file path for the current project.
    
    Args:
        path_type: Type of cache path to set. Options: 'local', 'network'
        path: File system path for the cache
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Validate path_type
    valid_path_types = ["local", "network"]
    path_type = path_type.lower()
    if path_type not in valid_path_types:
        return f"Error: Invalid path type. Must be one of: {', '.join(valid_path_types)}"
    
    # Check if directory exists
    if not os.path.exists(path):
        return f"Error: Path '{path}' does not exist"
    
    setting_key = "LocalCachePath" if path_type == "local" else "NetworkCachePath"
    
    try:
        result = current_project.SetSetting(setting_key, path)
        if result:
            return f"Successfully set {path_type} cache path to '{path}'"
        else:
            return f"Failed to set {path_type} cache path to '{path}'"
    except Exception as e:
        return f"Error setting cache path: {str(e)}"

@mcp.tool()
def generate_optimized_media(clip_names: List[str] = None) -> str:
    """Generate optimized media for specified clips or all clips if none specified.
    
    Args:
        clip_names: Optional list of clip names. If None, processes all clips in media pool
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Get clips to process
    if clip_names:
        # Get specified clips
        all_clips = get_all_media_pool_clips(media_pool)
        clips_to_process = []
        missing_clips = []
        
        for name in clip_names:
            found = False
            for clip in all_clips:
                if clip.GetName() == name:
                    clips_to_process.append(clip)
                    found = True
                    break
            if not found:
                missing_clips.append(name)
        
        if missing_clips:
            return f"Error: Could not find these clips: {', '.join(missing_clips)}"
        
        if not clips_to_process:
            return "Error: No valid clips found to process"
    else:
        # Get all clips
        clips_to_process = get_all_media_pool_clips(media_pool)
    
    try:
        # Select the clips
        media_pool.SetCurrentFolder(media_pool.GetRootFolder())
        for clip in clips_to_process:
            clip.AddFlag("Green")  # Temporarily add flag to help with selection
        
        # Switch to Media page if not already there
        current_page = resolve.GetCurrentPage()
        if current_page != "media":
            resolve.OpenPage("media")
        
        # Select clips with Green flag
        media_pool.SetClipSelection([clip for clip in clips_to_process])
        
        # Generate optimized media
        result = current_project.GenerateOptimizedMedia()
        
        # Remove temporary flags
        for clip in clips_to_process:
            clip.ClearFlags("Green")
        
        if result:
            return f"Successfully started optimized media generation for {len(clips_to_process)} clips"
        else:
            return f"Failed to start optimized media generation"
    except Exception as e:
        # Clean up flags in case of error
        try:
            for clip in clips_to_process:
                clip.ClearFlags("Green")
        except:
            pass
        return f"Error generating optimized media: {str(e)}"

@mcp.tool()
def delete_optimized_media(clip_names: List[str] = None) -> str:
    """Delete optimized media for specified clips or all clips if none specified.
    
    Args:
        clip_names: Optional list of clip names. If None, processes all clips in media pool
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Get clips to process
    if clip_names:
        # Get specified clips
        all_clips = get_all_media_pool_clips(media_pool)
        clips_to_process = []
        missing_clips = []
        
        for name in clip_names:
            found = False
            for clip in all_clips:
                if clip.GetName() == name:
                    clips_to_process.append(clip)
                    found = True
                    break
            if not found:
                missing_clips.append(name)
        
        if missing_clips:
            return f"Error: Could not find these clips: {', '.join(missing_clips)}"
        
        if not clips_to_process:
            return "Error: No valid clips found to process"
    else:
        # Get all clips
        clips_to_process = get_all_media_pool_clips(media_pool)
    
    try:
        # Select the clips
        media_pool.SetCurrentFolder(media_pool.GetRootFolder())
        for clip in clips_to_process:
            clip.AddFlag("Green")  # Temporarily add flag to help with selection
        
        # Switch to Media page if not already there
        current_page = resolve.GetCurrentPage()
        if current_page != "media":
            resolve.OpenPage("media")
        
        # Select clips with Green flag
        media_pool.SetClipSelection([clip for clip in clips_to_process])
        
        # Delete optimized media
        result = current_project.DeleteOptimizedMedia()
        
        # Remove temporary flags
        for clip in clips_to_process:
            clip.ClearFlags("Green")
        
        if result:
            return f"Successfully deleted optimized media for {len(clips_to_process)} clips"
        else:
            return f"Failed to delete optimized media"
    except Exception as e:
        # Clean up flags in case of error
        try:
            for clip in clips_to_process:
                clip.ClearFlags("Green")
        except:
            pass
        return f"Error deleting optimized media: {str(e)}"

# ------------------
# Timeline Item Properties
# ------------------

@mcp.resource("resolve://timeline-item/{timeline_item_id}")
def get_timeline_item_properties(timeline_item_id: str) -> Dict[str, Any]:
    """Get properties of a specific timeline item by ID.
    
    Args:
        timeline_item_id: The ID of the timeline item to get properties for
    """
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
    
    try:
        # Find the timeline item by ID
        # We'll need to get all items from all tracks and check their IDs
        video_track_count = current_timeline.GetTrackCount("video")
        audio_track_count = current_timeline.GetTrackCount("audio")
        
        timeline_item = None
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        # If not found, search audio tracks
        if not timeline_item:
            for track_index in range(1, audio_track_count + 1):
                items = current_timeline.GetItemListInTrack("audio", track_index)
                if items:
                    for item in items:
                        if str(item.GetUniqueId()) == timeline_item_id:
                            timeline_item = item
                            break
                if timeline_item:
                    break
        
        if not timeline_item:
            return {"error": f"Timeline item with ID '{timeline_item_id}' not found"}
        
        # Get basic properties
        properties = {
            "id": timeline_item_id,
            "name": timeline_item.GetName(),
            "type": timeline_item.GetType(),
            "start_frame": timeline_item.GetStart(),
            "end_frame": timeline_item.GetEnd(),
            "duration": timeline_item.GetDuration()
        }
        
        # Get additional properties if it's a video item
        if timeline_item.GetType() == "Video":
            # Transform properties
            properties["transform"] = {
                "position": {
                    "x": timeline_item.GetProperty("Pan"),
                    "y": timeline_item.GetProperty("Tilt")
                },
                "zoom": timeline_item.GetProperty("ZoomX"),  # ZoomX/ZoomY can be different for non-uniform scaling
                "zoom_x": timeline_item.GetProperty("ZoomX"),
                "zoom_y": timeline_item.GetProperty("ZoomY"),
                "rotation": timeline_item.GetProperty("Rotation"),
                "anchor_point": {
                    "x": timeline_item.GetProperty("AnchorPointX"),
                    "y": timeline_item.GetProperty("AnchorPointY")
                },
                "pitch": timeline_item.GetProperty("Pitch"),
                "yaw": timeline_item.GetProperty("Yaw")
            }
            
            # Crop properties
            properties["crop"] = {
                "left": timeline_item.GetProperty("CropLeft"),
                "right": timeline_item.GetProperty("CropRight"),
                "top": timeline_item.GetProperty("CropTop"),
                "bottom": timeline_item.GetProperty("CropBottom")
            }
            
            # Composite properties
            properties["composite"] = {
                "mode": timeline_item.GetProperty("CompositeMode"),
                "opacity": timeline_item.GetProperty("Opacity")
            }
            
            # Dynamic zoom properties
            properties["dynamic_zoom"] = {
                "enabled": timeline_item.GetProperty("DynamicZoomEnable"),
                "mode": timeline_item.GetProperty("DynamicZoomMode")
            }
            
            # Retime properties
            properties["retime"] = {
                "speed": timeline_item.GetProperty("Speed"),
                "process": timeline_item.GetProperty("RetimeProcess")
            }
            
            # Stabilization properties
            properties["stabilization"] = {
                "enabled": timeline_item.GetProperty("StabilizationEnable"),
                "method": timeline_item.GetProperty("StabilizationMethod"),
                "strength": timeline_item.GetProperty("StabilizationStrength")
            }
        
        # Audio-specific properties
        if timeline_item.GetType() == "Audio" or timeline_item.GetMediaType() == "Audio":
            properties["audio"] = {
                "volume": timeline_item.GetProperty("Volume"),
                "pan": timeline_item.GetProperty("Pan"),
                "eq_enabled": timeline_item.GetProperty("EQEnable"),
                "normalize_enabled": timeline_item.GetProperty("NormalizeEnable"),
                "normalize_level": timeline_item.GetProperty("NormalizeLevel")
            }
        
        return properties
        
    except Exception as e:
        return {"error": f"Error getting timeline item properties: {str(e)}"}

@mcp.resource("resolve://timeline-items")
def get_timeline_items() -> List[Dict[str, Any]]:
    """Get all items in the current timeline with their IDs and basic properties."""
    if resolve is None:
        return [{"error": "Not connected to DaVinci Resolve"}]
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return [{"error": "Failed to get Project Manager"}]
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return [{"error": "No project currently open"}]
    
    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        return [{"error": "No timeline currently active"}]
    
    try:
        # Get all tracks in the timeline
        video_track_count = current_timeline.GetTrackCount("video")
        audio_track_count = current_timeline.GetTrackCount("audio")
        
        items = []
        
        # Process video tracks
        for track_index in range(1, video_track_count + 1):
            track_items = current_timeline.GetItemListInTrack("video", track_index)
            if track_items:
                for item in track_items:
                    items.append({
                        "id": str(item.GetUniqueId()),
                        "name": item.GetName(),
                        "type": "video",
                        "track": track_index,
                        "start_frame": item.GetStart(),
                        "end_frame": item.GetEnd(),
                        "duration": item.GetDuration()
                    })
        
        # Process audio tracks
        for track_index in range(1, audio_track_count + 1):
            track_items = current_timeline.GetItemListInTrack("audio", track_index)
            if track_items:
                for item in track_items:
                    items.append({
                        "id": str(item.GetUniqueId()),
                        "name": item.GetName(),
                        "type": "audio",
                        "track": track_index,
                        "start_frame": item.GetStart(),
                        "end_frame": item.GetEnd(),
                        "duration": item.GetDuration()
                    })
        
        if not items:
            return [{"info": "No items found in the current timeline"}]
        
        return items
    except Exception as e:
        return [{"error": f"Error listing timeline items: {str(e)}"}]

@mcp.tool()
def set_timeline_item_transform(timeline_item_id: str, 
                               property_name: str, 
                               property_value: float) -> str:
    """Set a transform property for a timeline item.
    
    Args:
        timeline_item_id: The ID of the timeline item to modify
        property_name: The name of the property to set. Options include:
                      'Pan', 'Tilt', 'ZoomX', 'ZoomY', 'Rotation', 'AnchorPointX', 
                      'AnchorPointY', 'Pitch', 'Yaw'
        property_value: The value to set for the property
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
    
    # Validate property name
    valid_properties = [
        'Pan', 'Tilt', 'ZoomX', 'ZoomY', 'Rotation', 
        'AnchorPointX', 'AnchorPointY', 'Pitch', 'Yaw'
    ]
    
    if property_name not in valid_properties:
        return f"Error: Invalid property name. Must be one of: {', '.join(valid_properties)}"
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        
        timeline_item = None
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        if not timeline_item:
            return f"Error: Video timeline item with ID '{timeline_item_id}' not found"
        
        if timeline_item.GetType() != "Video":
            return f"Error: Timeline item with ID '{timeline_item_id}' is not a video item"
        
        # Set the property
        result = timeline_item.SetProperty(property_name, property_value)
        if result:
            return f"Successfully set {property_name} to {property_value} for timeline item '{timeline_item.GetName()}'"
        else:
            return f"Failed to set {property_name} for timeline item '{timeline_item.GetName()}'"
    except Exception as e:
        return f"Error setting timeline item property: {str(e)}"

@mcp.tool()
def set_timeline_item_crop(timeline_item_id: str, 
                          crop_type: str, 
                          crop_value: float) -> str:
    """Set a crop property for a timeline item.
    
    Args:
        timeline_item_id: The ID of the timeline item to modify
        crop_type: The type of crop to set. Options: 'Left', 'Right', 'Top', 'Bottom'
        crop_value: The value to set for the crop (typically 0.0 to 1.0)
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
    
    # Validate crop type
    valid_crop_types = ['Left', 'Right', 'Top', 'Bottom']
    
    if crop_type not in valid_crop_types:
        return f"Error: Invalid crop type. Must be one of: {', '.join(valid_crop_types)}"
    
    property_name = f"Crop{crop_type}"
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        
        timeline_item = None
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        if not timeline_item:
            return f"Error: Video timeline item with ID '{timeline_item_id}' not found"
        
        if timeline_item.GetType() != "Video":
            return f"Error: Timeline item with ID '{timeline_item_id}' is not a video item"
        
        # Set the property
        result = timeline_item.SetProperty(property_name, crop_value)
        if result:
            return f"Successfully set crop {crop_type.lower()} to {crop_value} for timeline item '{timeline_item.GetName()}'"
        else:
            return f"Failed to set crop {crop_type.lower()} for timeline item '{timeline_item.GetName()}'"
    except Exception as e:
        return f"Error setting timeline item crop: {str(e)}"

@mcp.tool()
def set_timeline_item_composite(timeline_item_id: str, 
                               composite_mode: str = None, 
                               opacity: float = None) -> str:
    """Set composite properties for a timeline item.
    
    Args:
        timeline_item_id: The ID of the timeline item to modify
        composite_mode: Optional composite mode to set (e.g., 'Normal', 'Add', 'Multiply')
        opacity: Optional opacity value to set (0.0 to 1.0)
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
    
    # Validate inputs
    if composite_mode is None and opacity is None:
        return "Error: Must specify at least one of composite_mode or opacity"
    
    # Valid composite modes
    valid_composite_modes = [
        'Normal', 'Add', 'Subtract', 'Difference', 'Multiply', 'Screen', 
        'Overlay', 'Hardlight', 'Softlight', 'Darken', 'Lighten', 'ColorDodge', 
        'ColorBurn', 'Exclusion', 'Hue', 'Saturation', 'Color', 'Luminosity'
    ]
    
    if composite_mode and composite_mode not in valid_composite_modes:
        return f"Error: Invalid composite mode. Must be one of: {', '.join(valid_composite_modes)}"
    
    if opacity is not None and (opacity < 0.0 or opacity > 1.0):
        return "Error: Opacity must be between 0.0 and 1.0"
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        
        timeline_item = None
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        if not timeline_item:
            return f"Error: Video timeline item with ID '{timeline_item_id}' not found"
        
        if timeline_item.GetType() != "Video":
            return f"Error: Timeline item with ID '{timeline_item_id}' is not a video item"
        
        success = True
        
        # Set composite mode if specified
        if composite_mode:
            result = timeline_item.SetProperty("CompositeMode", composite_mode)
            if not result:
                success = False
        
        # Set opacity if specified
        if opacity is not None:
            result = timeline_item.SetProperty("Opacity", opacity)
            if not result:
                success = False
        
        if success:
            changes = []
            if composite_mode:
                changes.append(f"composite mode to '{composite_mode}'")
            if opacity is not None:
                changes.append(f"opacity to {opacity}")
            
            return f"Successfully set {' and '.join(changes)} for timeline item '{timeline_item.GetName()}'"
        else:
            return f"Failed to set some composite properties for timeline item '{timeline_item.GetName()}'"
    except Exception as e:
        return f"Error setting timeline item composite properties: {str(e)}"

@mcp.tool()
def set_timeline_item_retime(timeline_item_id: str, 
                            speed: float = None, 
                            process: str = None) -> str:
    """Set retiming properties for a timeline item.
    
    Args:
        timeline_item_id: The ID of the timeline item to modify
        speed: Optional speed factor (e.g., 0.5 for 50%, 2.0 for 200%)
        process: Optional retime process. Options: 'NearestFrame', 'FrameBlend', 'OpticalFlow'
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
    
    # Validate inputs
    if speed is None and process is None:
        return "Error: Must specify at least one of speed or process"
    
    if speed is not None and speed <= 0:
        return "Error: Speed must be greater than 0"
    
    valid_processes = ['NearestFrame', 'FrameBlend', 'OpticalFlow']
    if process and process not in valid_processes:
        return f"Error: Invalid retime process. Must be one of: {', '.join(valid_processes)}"
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        
        timeline_item = None
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        if not timeline_item:
            return f"Error: Video timeline item with ID '{timeline_item_id}' not found"
        
        success = True
        
        # Set speed if specified
        if speed is not None:
            result = timeline_item.SetProperty("Speed", speed)
            if not result:
                success = False
        
        # Set retime process if specified
        if process:
            result = timeline_item.SetProperty("RetimeProcess", process)
            if not result:
                success = False
        
        if success:
            changes = []
            if speed is not None:
                changes.append(f"speed to {speed}x")
            if process:
                changes.append(f"retime process to '{process}'")
            
            return f"Successfully set {' and '.join(changes)} for timeline item '{timeline_item.GetName()}'"
        else:
            return f"Failed to set some retime properties for timeline item '{timeline_item.GetName()}'"
    except Exception as e:
        return f"Error setting timeline item retime properties: {str(e)}"

@mcp.tool()
def set_timeline_item_stabilization(timeline_item_id: str, 
                                   enabled: bool = None, 
                                   method: str = None,
                                   strength: float = None) -> str:
    """Set stabilization properties for a timeline item.
    
    Args:
        timeline_item_id: The ID of the timeline item to modify
        enabled: Optional boolean to enable/disable stabilization
        method: Optional stabilization method. Options: 'Perspective', 'Similarity', 'Translation'
        strength: Optional strength value (0.0 to 1.0)
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
    
    # Validate inputs
    if enabled is None and method is None and strength is None:
        return "Error: Must specify at least one parameter to modify"
    
    valid_methods = ['Perspective', 'Similarity', 'Translation']
    if method and method not in valid_methods:
        return f"Error: Invalid stabilization method. Must be one of: {', '.join(valid_methods)}"
    
    if strength is not None and (strength < 0.0 or strength > 1.0):
        return "Error: Strength must be between 0.0 and 1.0"
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        
        timeline_item = None
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        if not timeline_item:
            return f"Error: Video timeline item with ID '{timeline_item_id}' not found"
        
        if timeline_item.GetType() != "Video":
            return f"Error: Timeline item with ID '{timeline_item_id}' is not a video item"
        
        success = True
        
        # Set enabled if specified
        if enabled is not None:
            result = timeline_item.SetProperty("StabilizationEnable", 1 if enabled else 0)
            if not result:
                success = False
        
        # Set method if specified
        if method:
            result = timeline_item.SetProperty("StabilizationMethod", method)
            if not result:
                success = False
        
        # Set strength if specified
        if strength is not None:
            result = timeline_item.SetProperty("StabilizationStrength", strength)
            if not result:
                success = False
        
        if success:
            changes = []
            if enabled is not None:
                changes.append(f"stabilization {'enabled' if enabled else 'disabled'}")
            if method:
                changes.append(f"stabilization method to '{method}'")
            if strength is not None:
                changes.append(f"stabilization strength to {strength}")
            
            return f"Successfully set {' and '.join(changes)} for timeline item '{timeline_item.GetName()}'"
        else:
            return f"Failed to set some stabilization properties for timeline item '{timeline_item.GetName()}'"
    except Exception as e:
        return f"Error setting timeline item stabilization properties: {str(e)}"

@mcp.tool()
def set_timeline_item_audio(timeline_item_id: str, 
                           volume: float = None, 
                           pan: float = None,
                           eq_enabled: bool = None) -> str:
    """Set audio properties for a timeline item.
    
    Args:
        timeline_item_id: The ID of the timeline item to modify
        volume: Optional volume level (usually 0.0 to 2.0, where 1.0 is unity gain)
        pan: Optional pan value (-1.0 to 1.0, where -1.0 is left, 0 is center, 1.0 is right)
        eq_enabled: Optional boolean to enable/disable EQ
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
    
    # Validate inputs
    if volume is None and pan is None and eq_enabled is None:
        return "Error: Must specify at least one parameter to modify"
    
    if volume is not None and volume < 0.0:
        return "Error: Volume must be greater than or equal to 0.0"
    
    if pan is not None and (pan < -1.0 or pan > 1.0):
        return "Error: Pan must be between -1.0 and 1.0"
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        audio_track_count = current_timeline.GetTrackCount("audio")
        
        timeline_item = None
        is_audio = False
        
        # Search audio tracks first
        for track_index in range(1, audio_track_count + 1):
            items = current_timeline.GetItemListInTrack("audio", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        is_audio = True
                        break
            if timeline_item:
                break
        
        # If not found in audio tracks, search video tracks (might be a video clip with audio)
        if not timeline_item:
            for track_index in range(1, video_track_count + 1):
                items = current_timeline.GetItemListInTrack("video", track_index)
                if items:
                    for item in items:
                        if str(item.GetUniqueId()) == timeline_item_id:
                            timeline_item = item
                            break
                if timeline_item:
                    break
        
        if not timeline_item:
            return f"Error: Timeline item with ID '{timeline_item_id}' not found"
        
        # Check if the item has audio capabilities
        if not is_audio and timeline_item.GetMediaType() != "Audio":
            return f"Error: Timeline item with ID '{timeline_item_id}' does not have audio properties"
        
        success = True
        
        # Set volume if specified
        if volume is not None:
            result = timeline_item.SetProperty("Volume", volume)
            if not result:
                success = False
        
        # Set pan if specified
        if pan is not None:
            result = timeline_item.SetProperty("Pan", pan)
            if not result:
                success = False
        
        # Set EQ enabled if specified
        if eq_enabled is not None:
            result = timeline_item.SetProperty("EQEnable", 1 if eq_enabled else 0)
            if not result:
                success = False
        
        if success:
            changes = []
            if volume is not None:
                changes.append(f"volume to {volume}")
            if pan is not None:
                changes.append(f"pan to {pan}")
            if eq_enabled is not None:
                changes.append(f"EQ {'enabled' if eq_enabled else 'disabled'}")
            
            return f"Successfully set {' and '.join(changes)} for timeline item '{timeline_item.GetName()}'"
        else:
            return f"Failed to set some audio properties for timeline item '{timeline_item.GetName()}'"
    except Exception as e:
        return f"Error setting timeline item audio properties: {str(e)}"

# ------------------
# Keyframe Control
# ------------------

@mcp.resource("resolve://timeline-item/{timeline_item_id}/keyframes/{property_name}")
def get_timeline_item_keyframes(timeline_item_id: str, property_name: str) -> Dict[str, Any]:
    """Get keyframes for a specific timeline item by ID.
    
    Args:
        timeline_item_id: The ID of the timeline item to get keyframes for
        property_name: Optional property name to filter keyframes (e.g., 'Pan', 'ZoomX')
    """
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
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        audio_track_count = current_timeline.GetTrackCount("audio")
        
        timeline_item = None
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        # If not found, search audio tracks
        if not timeline_item:
            for track_index in range(1, audio_track_count + 1):
                items = current_timeline.GetItemListInTrack("audio", track_index)
                if items:
                    for item in items:
                        if str(item.GetUniqueId()) == timeline_item_id:
                            timeline_item = item
                            break
                if timeline_item:
                    break
        
        if not timeline_item:
            return {"error": f"Timeline item with ID '{timeline_item_id}' not found"}
        
        # Get all keyframeable properties for this item
        keyframeable_properties = []
        keyframes = {}
        
        # Common keyframeable properties for video items
        video_properties = [
            'Pan', 'Tilt', 'ZoomX', 'ZoomY', 'Rotation', 'AnchorPointX', 'AnchorPointY',
            'Pitch', 'Yaw', 'Opacity', 'CropLeft', 'CropRight', 'CropTop', 'CropBottom'
        ]
        
        # Audio-specific keyframeable properties
        audio_properties = ['Volume', 'Pan']
        
        # Check if it's a video item
        if timeline_item.GetType() == "Video":
            # Check each property to see if it has keyframes
            for prop in video_properties:
                if timeline_item.GetKeyframeCount(prop) > 0:
                    keyframeable_properties.append(prop)
                    
                    # Get all keyframes for this property
                    keyframes[prop] = []
                    keyframe_count = timeline_item.GetKeyframeCount(prop)
                    
                    for i in range(keyframe_count):
                        # Get the frame position and value of the keyframe
                        frame_pos = timeline_item.GetKeyframeAtIndex(prop, i)["frame"]
                        value = timeline_item.GetPropertyAtKeyframeIndex(prop, i)
                        
                        keyframes[prop].append({
                            "frame": frame_pos,
                            "value": value
                        })
        
        # Check if it has audio properties (could be video with audio or audio-only)
        if timeline_item.GetType() == "Audio" or timeline_item.GetMediaType() == "Audio":
            # Check each audio property for keyframes
            for prop in audio_properties:
                if timeline_item.GetKeyframeCount(prop) > 0:
                    keyframeable_properties.append(prop)
                    
                    # Get all keyframes for this property
                    keyframes[prop] = []
                    keyframe_count = timeline_item.GetKeyframeCount(prop)
                    
                    for i in range(keyframe_count):
                        # Get the frame position and value of the keyframe
                        frame_pos = timeline_item.GetKeyframeAtIndex(prop, i)["frame"]
                        value = timeline_item.GetPropertyAtKeyframeIndex(prop, i)
                        
                        keyframes[prop].append({
                            "frame": frame_pos,
                            "value": value
                        })
        
        # Filter by property_name if specified
        if property_name:
            if property_name in keyframes:
                return {
                    "item_id": timeline_item_id,
                    "item_name": timeline_item.GetName(),
                    "properties": [property_name],
                    "keyframes": {property_name: keyframes[property_name]}
                }
            else:
                return {
                    "item_id": timeline_item_id,
                    "item_name": timeline_item.GetName(),
                    "properties": [],
                    "keyframes": {}
                }
        
        # Return all keyframes
        return {
            "item_id": timeline_item_id,
            "item_name": timeline_item.GetName(),
            "properties": keyframeable_properties,
            "keyframes": keyframes
        }
        
    except Exception as e:
        return {"error": f"Error getting timeline item keyframes: {str(e)}"}

@mcp.tool()
def add_keyframe(timeline_item_id: str, property_name: str, frame: int, value: float) -> str:
    """Add a keyframe at the specified frame for a timeline item property.
    
    Args:
        timeline_item_id: The ID of the timeline item to add keyframe to
        property_name: The name of the property to keyframe (e.g., 'Pan', 'ZoomX')
        frame: Frame position for the keyframe
        value: Value to set at the keyframe
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
    
    # Valid keyframeable properties
    video_properties = [
        'Pan', 'Tilt', 'ZoomX', 'ZoomY', 'Rotation', 'AnchorPointX', 'AnchorPointY',
        'Pitch', 'Yaw', 'Opacity', 'CropLeft', 'CropRight', 'CropTop', 'CropBottom'
    ]
    
    audio_properties = ['Volume', 'Pan']
    
    valid_properties = video_properties + audio_properties
    
    if property_name not in valid_properties:
        return f"Error: Invalid property name. Must be one of: {', '.join(valid_properties)}"
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        audio_track_count = current_timeline.GetTrackCount("audio")
        
        timeline_item = None
        is_audio = False
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        # If not found, search audio tracks
        if not timeline_item:
            for track_index in range(1, audio_track_count + 1):
                items = current_timeline.GetItemListInTrack("audio", track_index)
                if items:
                    for item in items:
                        if str(item.GetUniqueId()) == timeline_item_id:
                            timeline_item = item
                            is_audio = True
                            break
                if timeline_item:
                    break
        
        if not timeline_item:
            return f"Error: Timeline item with ID '{timeline_item_id}' not found"
        
        # Check if the specified property is valid for this item type
        if is_audio and property_name not in audio_properties:
            return f"Error: Property '{property_name}' is not available for audio items"
        
        if not is_audio and property_name not in video_properties and timeline_item.GetType() != "Video":
            return f"Error: Property '{property_name}' is not available for this item type"
            
        # Validate frame is within the item's range
        start_frame = timeline_item.GetStart()
        end_frame = timeline_item.GetEnd()
        
        if frame < start_frame or frame > end_frame:
            return f"Error: Frame {frame} is outside the item's range ({start_frame} to {end_frame})"
        
        # Add the keyframe
        result = timeline_item.AddKeyframe(property_name, frame, value)
        
        if result:
            return f"Successfully added keyframe for {property_name} at frame {frame} with value {value}"
        else:
            return f"Failed to add keyframe for {property_name} at frame {frame}"
        
    except Exception as e:
        return f"Error adding keyframe: {str(e)}"

@mcp.tool()
def modify_keyframe(timeline_item_id: str, property_name: str, frame: int, new_value: float = None, new_frame: int = None) -> str:
    """Modify an existing keyframe by changing its value or frame position.
    
    Args:
        timeline_item_id: The ID of the timeline item
        property_name: The name of the property with keyframe
        frame: Current frame position of the keyframe to modify
        new_value: Optional new value for the keyframe
        new_frame: Optional new frame position for the keyframe
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
    
    if new_value is None and new_frame is None:
        return "Error: Must specify at least one of new_value or new_frame"
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        audio_track_count = current_timeline.GetTrackCount("audio")
        
        timeline_item = None
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        # If not found, search audio tracks
        if not timeline_item:
            for track_index in range(1, audio_track_count + 1):
                items = current_timeline.GetItemListInTrack("audio", track_index)
                if items:
                    for item in items:
                        if str(item.GetUniqueId()) == timeline_item_id:
                            timeline_item = item
                            break
                if timeline_item:
                    break
        
        if not timeline_item:
            return f"Error: Timeline item with ID '{timeline_item_id}' not found"
        
        # Check if the property has keyframes
        keyframe_count = timeline_item.GetKeyframeCount(property_name)
        if keyframe_count == 0:
            return f"Error: No keyframes found for property '{property_name}'"
        
        # Find the keyframe at the specified frame
        keyframe_index = -1
        for i in range(keyframe_count):
            kf = timeline_item.GetKeyframeAtIndex(property_name, i)
            if kf["frame"] == frame:
                keyframe_index = i
                break
        
        if keyframe_index == -1:
            return f"Error: No keyframe found at frame {frame} for property '{property_name}'"
        
        if new_frame is not None:
            # Check if new frame is within the item's range
            start_frame = timeline_item.GetStart()
            end_frame = timeline_item.GetEnd()
            
            if new_frame < start_frame or new_frame > end_frame:
                return f"Error: New frame {new_frame} is outside the item's range ({start_frame} to {end_frame})"
                
            # Delete the keyframe at the current frame
            current_value = timeline_item.GetPropertyAtKeyframeIndex(property_name, keyframe_index)
            timeline_item.DeleteKeyframe(property_name, frame)
            
            # Add a new keyframe at the new frame position with the current value (or new value if specified)
            value = new_value if new_value is not None else current_value
            result = timeline_item.AddKeyframe(property_name, new_frame, value)
            
            if result:
                return f"Successfully moved keyframe for {property_name} from frame {frame} to frame {new_frame}"
            else:
                return f"Failed to move keyframe for {property_name}"
        else:
            # Only changing the value, not the frame position
            # We need to delete and re-add the keyframe with the new value
            timeline_item.DeleteKeyframe(property_name, frame)
            result = timeline_item.AddKeyframe(property_name, frame, new_value)
            
            if result:
                return f"Successfully updated keyframe value for {property_name} at frame {frame} to {new_value}"
            else:
                return f"Failed to update keyframe value for {property_name} at frame {frame}"
        
    except Exception as e:
        return f"Error modifying keyframe: {str(e)}"

@mcp.tool()
def delete_keyframe(timeline_item_id: str, property_name: str, frame: int) -> str:
    """Delete a keyframe at the specified frame for a timeline item property.
    
    Args:
        timeline_item_id: The ID of the timeline item
        property_name: The name of the property with keyframe to delete
        frame: Frame position of the keyframe to delete
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
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        audio_track_count = current_timeline.GetTrackCount("audio")
        
        timeline_item = None
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        # If not found, search audio tracks
        if not timeline_item:
            for track_index in range(1, audio_track_count + 1):
                items = current_timeline.GetItemListInTrack("audio", track_index)
                if items:
                    for item in items:
                        if str(item.GetUniqueId()) == timeline_item_id:
                            timeline_item = item
                            break
                if timeline_item:
                    break
        
        if not timeline_item:
            return f"Error: Timeline item with ID '{timeline_item_id}' not found"
        
        # Check if the property has keyframes
        keyframe_count = timeline_item.GetKeyframeCount(property_name)
        if keyframe_count == 0:
            return f"Error: No keyframes found for property '{property_name}'"
        
        # Check if there's a keyframe at the specified frame
        keyframe_exists = False
        for i in range(keyframe_count):
            kf = timeline_item.GetKeyframeAtIndex(property_name, i)
            if kf["frame"] == frame:
                keyframe_exists = True
                break
        
        if not keyframe_exists:
            return f"Error: No keyframe found at frame {frame} for property '{property_name}'"
        
        # Delete the keyframe
        result = timeline_item.DeleteKeyframe(property_name, frame)
        
        if result:
            return f"Successfully deleted keyframe for {property_name} at frame {frame}"
        else:
            return f"Failed to delete keyframe for {property_name} at frame {frame}"
        
    except Exception as e:
        return f"Error deleting keyframe: {str(e)}"

@mcp.tool()
def set_keyframe_interpolation(timeline_item_id: str, property_name: str, frame: int, interpolation_type: str) -> str:
    """Set the interpolation type for a keyframe.
    
    Args:
        timeline_item_id: The ID of the timeline item
        property_name: The name of the property with keyframe
        frame: Frame position of the keyframe
        interpolation_type: Type of interpolation. Options: 'Linear', 'Bezier', 'Ease-In', 'Ease-Out'
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
    
    # Validate interpolation type
    valid_interpolation_types = ['Linear', 'Bezier', 'Ease-In', 'Ease-Out']
    if interpolation_type not in valid_interpolation_types:
        return f"Error: Invalid interpolation type. Must be one of: {', '.join(valid_interpolation_types)}"
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        audio_track_count = current_timeline.GetTrackCount("audio")
        
        timeline_item = None
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        # If not found, search audio tracks
        if not timeline_item:
            for track_index in range(1, audio_track_count + 1):
                items = current_timeline.GetItemListInTrack("audio", track_index)
                if items:
                    for item in items:
                        if str(item.GetUniqueId()) == timeline_item_id:
                            timeline_item = item
                            break
                if timeline_item:
                    break
        
        if not timeline_item:
            return f"Error: Timeline item with ID '{timeline_item_id}' not found"
        
        # Check if the property has keyframes
        keyframe_count = timeline_item.GetKeyframeCount(property_name)
        if keyframe_count == 0:
            return f"Error: No keyframes found for property '{property_name}'"
        
        # Check if there's a keyframe at the specified frame
        keyframe_exists = False
        for i in range(keyframe_count):
            kf = timeline_item.GetKeyframeAtIndex(property_name, i)
            if kf["frame"] == frame:
                keyframe_exists = True
                break
        
        if not keyframe_exists:
            return f"Error: No keyframe found at frame {frame} for property '{property_name}'"
        
        # Set the interpolation type
        interpolation_map = {
            'Linear': 0,
            'Bezier': 1,
            'Ease-In': 2,
            'Ease-Out': 3
        }
        
        # Get current keyframe value
        value = None
        for i in range(keyframe_count):
            kf = timeline_item.GetKeyframeAtIndex(property_name, i)
            if kf["frame"] == frame:
                value = timeline_item.GetPropertyAtKeyframeIndex(property_name, i)
                break
        
        # Delete the old keyframe
        timeline_item.DeleteKeyframe(property_name, frame)
        
        # Add a new keyframe with the same value but different interpolation
        result = timeline_item.AddKeyframe(property_name, frame, value, interpolation_map[interpolation_type])
        
        if result:
            return f"Successfully set interpolation for {property_name} keyframe at frame {frame} to {interpolation_type}"
        else:
            return f"Failed to set interpolation for {property_name} keyframe at frame {frame}"
        
    except Exception as e:
        return f"Error setting keyframe interpolation: {str(e)}"

@mcp.tool()
def enable_keyframes(timeline_item_id: str, keyframe_mode: str = "All") -> str:
    """Enable keyframe mode for a timeline item.
    
    Args:
        timeline_item_id: The ID of the timeline item
        keyframe_mode: Keyframe mode to enable. Options: 'All', 'Color', 'Sizing'
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
    
    # Validate keyframe mode
    valid_keyframe_modes = ['All', 'Color', 'Sizing']
    if keyframe_mode not in valid_keyframe_modes:
        return f"Error: Invalid keyframe mode. Must be one of: {', '.join(valid_keyframe_modes)}"
    
    try:
        # Find the timeline item by ID
        video_track_count = current_timeline.GetTrackCount("video")
        
        timeline_item = None
        
        # Search video tracks
        for track_index in range(1, video_track_count + 1):
            items = current_timeline.GetItemListInTrack("video", track_index)
            if items:
                for item in items:
                    if str(item.GetUniqueId()) == timeline_item_id:
                        timeline_item = item
                        break
            if timeline_item:
                break
        
        if not timeline_item:
            return f"Error: Video timeline item with ID '{timeline_item_id}' not found"
        
        if timeline_item.GetType() != "Video":
            return f"Error: Timeline item with ID '{timeline_item_id}' is not a video item"
        
        # Set the keyframe mode
        keyframe_mode_map = {
            'All': 0,
            'Color': 1,
            'Sizing': 2
        }
        
        result = timeline_item.SetProperty("KeyframeMode", keyframe_mode_map[keyframe_mode])
        
        if result:
            return f"Successfully enabled {keyframe_mode} keyframe mode for timeline item '{timeline_item.GetName()}'"
        else:
            return f"Failed to enable {keyframe_mode} keyframe mode for timeline item '{timeline_item.GetName()}'"
        
    except Exception as e:
        return f"Error enabling keyframe mode: {str(e)}"

# ------------------
# Color Preset Management
# ------------------

@mcp.resource("resolve://color/presets")
def get_color_presets() -> List[Dict[str, Any]]:
    """Get all available color presets in the current project."""
    if resolve is None:
        return [{"error": "Not connected to DaVinci Resolve"}]
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return [{"error": "Failed to get Project Manager"}]
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return [{"error": "No project currently open"}]
    
    # Switch to color page to access presets
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return [{"error": "Failed to get gallery"}]
        
        # Get all albums
        albums = gallery.GetAlbums()
        if not albums:
            return [{"info": "No albums found in gallery"}]
        
        result = []
        for album in albums:
            # Get stills in the album
            stills = album.GetStills()
            album_info = {
                "name": album.GetName(),
                "stills": []
            }
            
            if stills:
                for still in stills:
                    still_info = {
                        "id": still.GetUniqueId(),
                        "label": still.GetLabel(),
                        "timecode": still.GetTimecode(),
                        "isGrabbed": still.IsGrabbed()
                    }
                    album_info["stills"].append(still_info)
            
            result.append(album_info)
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
            
        return result
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return [{"error": f"Error retrieving color presets: {str(e)}"}]

@mcp.tool()
def save_color_preset(clip_name: str = None, preset_name: str = None, album_name: str = "DaVinci Resolve") -> str:
    """Save a color preset from the specified clip.
    
    Args:
        clip_name: Name of the clip to save preset from (uses current clip if None)
        preset_name: Name to give the preset (uses clip name if None)
        album_name: Album to save the preset to (default: "DaVinci Resolve")
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get the current timeline
        current_timeline = current_project.GetCurrentTimeline()
        if not current_timeline:
            return "Error: No timeline is currently open"
        
        # Get the specific clip or current clip
        if clip_name:
            # Find the clip by name in the timeline
            timeline_clips = current_timeline.GetItemListInTrack("video", 1)
            target_clip = None
            
            for clip in timeline_clips:
                if clip.GetName() == clip_name:
                    target_clip = clip
                    break
            
            if not target_clip:
                return f"Error: Clip '{clip_name}' not found in the timeline"
            
            # Select the clip
            current_timeline.SetCurrentSelectedItem(target_clip)
        
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Get or create album
        album = None
        albums = gallery.GetAlbums()
        
        if albums:
            for a in albums:
                if a.GetName() == album_name:
                    album = a
                    break
        
        if not album:
            # Create a new album if it doesn't exist
            album = gallery.CreateAlbum(album_name)
            if not album:
                return f"Error: Failed to create album '{album_name}'"
        
        # Set preset name if specified
        final_preset_name = preset_name
        if not final_preset_name:
            if clip_name:
                final_preset_name = f"{clip_name} Preset"
            else:
                # Get current clip name if available
                current_clip = current_timeline.GetCurrentVideoItem()
                if current_clip:
                    final_preset_name = f"{current_clip.GetName()} Preset"
                else:
                    final_preset_name = f"Preset {len(album.GetStills()) + 1}"
        
        # Capture still
        result = gallery.GrabStill()
        
        if not result:
            return "Error: Failed to grab still for the preset"
        
        # Get the still that was just created
        stills = album.GetStills()
        if stills:
            latest_still = stills[-1]  # Assume the last one is the one we just grabbed
            # Set the label
            latest_still.SetLabel(final_preset_name)
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        return f"Successfully saved color preset '{final_preset_name}' to album '{album_name}'"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error saving color preset: {str(e)}"

@mcp.tool()
def apply_color_preset(preset_id: str = None, preset_name: str = None, 
                     clip_name: str = None, album_name: str = "DaVinci Resolve") -> str:
    """Apply a color preset to the specified clip.
    
    Args:
        preset_id: ID of the preset to apply (if known)
        preset_name: Name of the preset to apply (searches in album)
        clip_name: Name of the clip to apply preset to (uses current clip if None)
        album_name: Album containing the preset (default: "DaVinci Resolve")
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    if not preset_id and not preset_name:
        return "Error: Must provide either preset_id or preset_name"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get the current timeline
        current_timeline = current_project.GetCurrentTimeline()
        if not current_timeline:
            return "Error: No timeline is currently open"
        
        # Get the specific clip or current clip
        if clip_name:
            # Find the clip by name in the timeline
            timeline_clips = current_timeline.GetItemListInTrack("video", 1)
            target_clip = None
            
            for clip in timeline_clips:
                if clip.GetName() == clip_name:
                    target_clip = clip
                    break
            
            if not target_clip:
                return f"Error: Clip '{clip_name}' not found in the timeline"
            
            # Select the clip
            current_timeline.SetCurrentSelectedItem(target_clip)
        
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Find the album
        album = None
        albums = gallery.GetAlbums()
        
        if albums:
            for a in albums:
                if a.GetName() == album_name:
                    album = a
                    break
        
        if not album:
            return f"Error: Album '{album_name}' not found"
        
        # Find the still to apply
        stills = album.GetStills()
        if not stills:
            return f"Error: No presets found in album '{album_name}'"
        
        target_still = None
        
        if preset_id:
            # Find by ID
            for still in stills:
                if still.GetUniqueId() == preset_id:
                    target_still = still
                    break
        elif preset_name:
            # Find by name
            for still in stills:
                if still.GetLabel() == preset_name:
                    target_still = still
                    break
        
        if not target_still:
            search_term = preset_id if preset_id else preset_name
            return f"Error: Preset '{search_term}' not found in album '{album_name}'"
        
        # Apply the preset
        result = target_still.ApplyToClip()
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if result:
            return f"Successfully applied color preset to {'specified clip' if clip_name else 'current clip'}"
        else:
            return f"Failed to apply color preset"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error applying color preset: {str(e)}"

@mcp.tool()
def delete_color_preset(preset_id: str = None, preset_name: str = None, 
                       album_name: str = "DaVinci Resolve") -> str:
    """Delete a color preset.
    
    Args:
        preset_id: ID of the preset to delete (if known)
        preset_name: Name of the preset to delete (searches in album)
        album_name: Album containing the preset (default: "DaVinci Resolve")
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    if not preset_id and not preset_name:
        return "Error: Must provide either preset_id or preset_name"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Find the album
        album = None
        albums = gallery.GetAlbums()
        
        if albums:
            for a in albums:
                if a.GetName() == album_name:
                    album = a
                    break
        
        if not album:
            return f"Error: Album '{album_name}' not found"
        
        # Find the still to delete
        stills = album.GetStills()
        if not stills:
            return f"Error: No presets found in album '{album_name}'"
        
        target_still = None
        
        if preset_id:
            # Find by ID
            for still in stills:
                if still.GetUniqueId() == preset_id:
                    target_still = still
                    break
        elif preset_name:
            # Find by name
            for still in stills:
                if still.GetLabel() == preset_name:
                    target_still = still
                    break
        
        if not target_still:
            search_term = preset_id if preset_id else preset_name
            return f"Error: Preset '{search_term}' not found in album '{album_name}'"
        
        # Delete the preset
        result = album.DeleteStill(target_still)
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if result:
            return f"Successfully deleted color preset from album '{album_name}'"
        else:
            return f"Failed to delete color preset"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error deleting color preset: {str(e)}"

@mcp.tool()
def create_color_preset_album(album_name: str) -> str:
    """Create a new album for color presets.
    
    Args:
        album_name: Name for the new album
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Check if album already exists
        albums = gallery.GetAlbums()
        
        if albums:
            for a in albums:
                if a.GetName() == album_name:
                    # Return to the original page if we switched
                    if current_page != "color":
                        resolve.OpenPage(current_page)
                    return f"Album '{album_name}' already exists"
        
        # Create a new album
        album = gallery.CreateAlbum(album_name)
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if album:
            return f"Successfully created album '{album_name}'"
        else:
            return f"Failed to create album '{album_name}'"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error creating album: {str(e)}"

@mcp.tool()
def delete_color_preset_album(album_name: str) -> str:
    """Delete a color preset album.
    
    Args:
        album_name: Name of the album to delete
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Find the album
        album = None
        albums = gallery.GetAlbums()
        
        if albums:
            for a in albums:
                if a.GetName() == album_name:
                    album = a
                    break
        
        if not album:
            # Return to the original page if we switched
            if current_page != "color":
                resolve.OpenPage(current_page)
            return f"Error: Album '{album_name}' not found"
        
        # Delete the album
        result = gallery.DeleteAlbum(album)
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if result:
            return f"Successfully deleted album '{album_name}'"
        else:
            return f"Failed to delete album '{album_name}'"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error deleting album: {str(e)}"

@mcp.tool()
def export_lut(clip_name: str = None, 
              export_path: str = None, 
              lut_format: str = "Cube", 
              lut_size: str = "33Point") -> str:
    """Export a LUT from the current clip's grade.
    
    Args:
        clip_name: Name of the clip to export grade from (uses current clip if None)
        export_path: Path to save the LUT file (generated if None)
        lut_format: Format of the LUT. Options: 'Cube', 'Davinci', '3dl', 'Panasonic'
        lut_size: Size of the LUT. Options: '17Point', '33Point', '65Point'
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get the current timeline
        current_timeline = current_project.GetCurrentTimeline()
        if not current_timeline:
            return "Error: No timeline is currently open"
        
        # Get the specific clip or current clip
        if clip_name:
            # Find the clip by name in the timeline
            timeline_clips = current_timeline.GetItemListInTrack("video", 1)
            target_clip = None
            
            for clip in timeline_clips:
                if clip.GetName() == clip_name:
                    target_clip = clip
                    break
            
            if not target_clip:
                return f"Error: Clip '{clip_name}' not found in the timeline"
            
            # Select the clip
            current_timeline.SetCurrentSelectedItem(target_clip)
        
        # Generate export path if not provided
        if not export_path:
            import tempfile
            clip_name_safe = clip_name if clip_name else "current_clip"
            clip_name_safe = clip_name_safe.replace(' ', '_').replace(':', '-')
            
            extension = ".cube"
            if lut_format.lower() == "davinci":
                extension = ".ilut"
            elif lut_format.lower() == "3dl":
                extension = ".3dl"
            elif lut_format.lower() == "panasonic":
                extension = ".vlut"
                
            export_path = os.path.join(tempfile.gettempdir(), f"{clip_name_safe}_lut{extension}")
        
        # Validate LUT format
        valid_formats = ['Cube', 'Davinci', '3dl', 'Panasonic']
        if lut_format not in valid_formats:
            return f"Error: Invalid LUT format. Must be one of: {', '.join(valid_formats)}"
        
        # Validate LUT size
        valid_sizes = ['17Point', '33Point', '65Point']
        if lut_size not in valid_sizes:
            return f"Error: Invalid LUT size. Must be one of: {', '.join(valid_sizes)}"
        
        # Map format string to numeric value expected by DaVinci Resolve API
        format_map = {
            'Cube': 0,
            'Davinci': 1,
            '3dl': 2,
            'Panasonic': 3
        }
        
        # Map size string to numeric value
        size_map = {
            '17Point': 0,
            '33Point': 1,
            '65Point': 2
        }
        
        # Get current clip
        current_clip = current_timeline.GetCurrentVideoItem()
        if not current_clip:
            return "Error: No clip is currently selected"
        
        # Create a directory for the export path if it doesn't exist
        export_dir = os.path.dirname(export_path)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)
        
        # Export the LUT
        colorpage = resolve.GetCurrentPage() == "color"
        if not colorpage:
            resolve.OpenPage("color")
        
        # Access Color page functionality 
        result = current_project.ExportCurrentGradeAsLUT(
            format_map[lut_format], 
            size_map[lut_size], 
            export_path
        )
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if result:
            return f"Successfully exported LUT to '{export_path}' in {lut_format} format with {lut_size} size"
        else:
            return f"Failed to export LUT"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error exporting LUT: {str(e)}"

@mcp.resource("resolve://color/lut-formats")
def get_lut_formats() -> Dict[str, Any]:
    """Get available LUT export formats and sizes."""
    formats = {
        "formats": [
            {
                "name": "Cube",
                "extension": ".cube",
                "description": "Industry standard LUT format supported by most applications"
            },
            {
                "name": "Davinci",
                "extension": ".ilut",
                "description": "DaVinci Resolve's native LUT format"
            },
            {
                "name": "3dl",
                "extension": ".3dl",
                "description": "ASSIMILATE SCRATCH and some Autodesk applications"
            },
            {
                "name": "Panasonic",
                "extension": ".vlut",
                "description": "Panasonic VariCam and other Panasonic cameras"
            }
        ],
        "sizes": [
            {
                "name": "17Point",
                "description": "Smaller file size, less precision (17x17x17)"
            },
            {
                "name": "33Point",
                "description": "Standard size with good balance of precision and file size (33x33x33)"
            },
            {
                "name": "65Point",
                "description": "Highest precision but larger file size (65x65x65)"
            }
        ]
    }
    return formats

@mcp.tool()
def export_all_powergrade_luts(export_dir: str) -> str:
    """Export all PowerGrade presets as LUT files.
    
    Args:
        export_dir: Directory to save the exported LUTs
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Get PowerGrade album
        powergrade_album = None
        albums = gallery.GetAlbums()
        
        if albums:
            for album in albums:
                if album.GetName() == "PowerGrade":
                    powergrade_album = album
                    break
        
        if not powergrade_album:
            return "Error: PowerGrade album not found"
        
        # Get all stills in the PowerGrade album
        stills = powergrade_album.GetStills()
        if not stills:
            return "Error: No stills found in PowerGrade album"
        
        # Create export directory if it doesn't exist
        if not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)
        
        # Export each still as a LUT
        exported_count = 0
        failed_stills = []
        
        for still in stills:
            still_name = still.GetLabel()
            if not still_name:
                still_name = f"PowerGrade_{still.GetUniqueId()}"
            
            # Create safe filename
            safe_name = ''.join(c if c.isalnum() or c in ['-', '_'] else '_' for c in still_name)
            lut_path = os.path.join(export_dir, f"{safe_name}.cube")
            
            # Apply the still to the current clip
            current_clip = current_timeline.GetCurrentVideoItem()
            if not current_clip:
                failed_stills.append(f"{still_name} (no clip selected)")
                continue
            
            # Apply the grade from the still
            applied = still.ApplyToClip()
            if not applied:
                failed_stills.append(f"{still_name} (could not apply grade)")
                continue
            
            # Export as LUT
            result = current_project.ExportCurrentGradeAsLUT(0, 1, lut_path)  # Cube format, 33-point
            
            if result:
                exported_count += 1
            else:
                failed_stills.append(f"{still_name} (export failed)")
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if failed_stills:
            return f"Exported {exported_count} LUTs to '{export_dir}'. Failed to export: {', '.join(failed_stills)}"
        else:
            return f"Successfully exported all {exported_count} PowerGrade LUTs to '{export_dir}'"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error exporting PowerGrade LUTs: {str(e)}"

# ------------------
# Object Inspection
# ------------------

@mcp.resource("resolve://inspect/resolve")
def inspect_resolve_object() -> Dict[str, Any]:
    """Inspect the main resolve object and return its methods and properties."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    return inspect_object(resolve)

@mcp.resource("resolve://inspect/project-manager")
def inspect_project_manager_object() -> Dict[str, Any]:
    """Inspect the project manager object and return its methods and properties."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    return inspect_object(project_manager)

@mcp.resource("resolve://inspect/current-project")
def inspect_current_project_object() -> Dict[str, Any]:
    """Inspect the current project object and return its methods and properties."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    return inspect_object(current_project)

@mcp.resource("resolve://inspect/media-pool")
def inspect_media_pool_object() -> Dict[str, Any]:
    """Inspect the media pool object and return its methods and properties."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return {"error": "Failed to get Media Pool"}
    
    return inspect_object(media_pool)

@mcp.resource("resolve://inspect/current-timeline")
def inspect_current_timeline_object() -> Dict[str, Any]:
    """Inspect the current timeline object and return its methods and properties."""
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
    
    return inspect_object(current_timeline)

@mcp.tool()
def object_help(object_type: str) -> str:
    """
    Get human-readable help for a DaVinci Resolve API object.
    
    Args:
        object_type: Type of object to get help for ('resolve', 'project_manager', 
                     'project', 'media_pool', 'timeline', 'media_storage')
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    # Map object type string to actual object
    obj = None
    
    if object_type == 'resolve':
        obj = resolve
    elif object_type == 'project_manager':
        obj = resolve.GetProjectManager()
    elif object_type == 'project':
        pm = resolve.GetProjectManager()
        if pm:
            obj = pm.GetCurrentProject()
    elif object_type == 'media_pool':
        pm = resolve.GetProjectManager()
        if pm:
            project = pm.GetCurrentProject()
            if project:
                obj = project.GetMediaPool()
    elif object_type == 'timeline':
        pm = resolve.GetProjectManager()
        if pm:
            project = pm.GetCurrentProject()
            if project:
                obj = project.GetCurrentTimeline()
    elif object_type == 'media_storage':
        obj = resolve.GetMediaStorage()
    else:
        return f"Error: Unknown object type '{object_type}'"
    
    if obj is None:
        return f"Error: Failed to get {object_type} object"
    
    # Generate and return help text
    return print_object_help(obj)

@mcp.tool()
def inspect_custom_object(object_path: str) -> Dict[str, Any]:
    """
    Inspect a custom DaVinci Resolve API object by path.
    
    Args:
        object_path: Path to the object using dot notation (e.g., 'resolve.GetMediaStorage()')
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    try:
        # Start with resolve object
        obj = resolve
        
        # Split the path and traverse down
        parts = object_path.split('.')
        
        # Skip the first part if it's 'resolve'
        start_index = 1 if parts[0].lower() == 'resolve' else 0
        
        for i in range(start_index, len(parts)):
            part = parts[i]
            
            # Check if it's a method call
            if part.endswith('()'):
                method_name = part[:-2]
                if hasattr(obj, method_name) and callable(getattr(obj, method_name)):
                    obj = getattr(obj, method_name)()
                else:
                    return {"error": f"Method '{method_name}' not found or not callable"}
            else:
                # It's an attribute access
                if hasattr(obj, part):
                    obj = getattr(obj, part)
                else:
                    return {"error": f"Attribute '{part}' not found"}
        
        # Inspect the object we've retrieved
        return inspect_object(obj)
    except Exception as e:
        return {"error": f"Error inspecting object: {str(e)}"}

# ------------------
# Layout Presets
# ------------------

@mcp.resource("resolve://layout-presets")
def get_layout_presets() -> List[Dict[str, Any]]:
    """Get all available layout presets for DaVinci Resolve."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    return list_layout_presets(layout_type="ui")

@mcp.tool()
def save_layout_preset_tool(preset_name: str) -> Dict[str, Any]:
    """Save the current UI layout as a preset.

    Calls Resolve.SaveLayoutPreset() to save the current UI layout.

    Args:
        preset_name: Name for the saved preset.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.SaveLayoutPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}

@mcp.tool()
def load_layout_preset_tool(preset_name: str) -> Dict[str, Any]:
    """Load a UI layout preset.

    Calls Resolve.LoadLayoutPreset() to load a saved UI layout.

    Args:
        preset_name: Name of the preset to load.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.LoadLayoutPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}

@mcp.tool()
def export_layout_preset_tool(preset_name: str, export_path: str) -> Dict[str, Any]:
    """Export a layout preset to a file.

    Calls Resolve.ExportLayoutPreset() to export a preset to disk.

    Args:
        preset_name: Name of the preset to export.
        export_path: Absolute file path to export the preset to.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.ExportLayoutPreset(preset_name, export_path)
    return {"success": bool(result), "preset_name": preset_name, "export_path": export_path}

@mcp.tool()
def import_layout_preset_tool(import_path: str, preset_name: str = None) -> Dict[str, Any]:
    """Import a layout preset from a file.

    Calls Resolve.ImportLayoutPreset() to import a preset from disk.

    Args:
        import_path: Absolute path to the preset file to import.
        preset_name: Name to save the imported preset as (uses filename if None).
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    if preset_name:
        result = resolve.ImportLayoutPreset(import_path, preset_name)
    else:
        result = resolve.ImportLayoutPreset(import_path)
        preset_name = os.path.splitext(os.path.basename(import_path))[0]
    return {"success": bool(result), "preset_name": preset_name, "import_path": import_path}

@mcp.tool()
def delete_layout_preset_tool(preset_name: str) -> Dict[str, Any]:
    """Delete a layout preset.

    Calls Resolve.DeleteLayoutPreset() to remove a saved preset.

    Args:
        preset_name: Name of the preset to delete.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.DeleteLayoutPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}

# ------------------
# App Control
# ------------------

@mcp.resource("resolve://app/state")
def get_app_state_endpoint() -> Dict[str, Any]:
    """Get DaVinci Resolve application state information."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "connected": False}
    
    return get_app_state(resolve)

@mcp.tool()
def quit_app(force: bool = False, save_project: bool = True) -> str:
    """
    Quit DaVinci Resolve application.
    
    Args:
        force: Whether to force quit even if unsaved changes (potentially dangerous)
        save_project: Whether to save the project before quitting
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    result = quit_resolve_app(resolve, force, save_project)
    
    if result:
        return "DaVinci Resolve quit command sent successfully"
    else:
        return "Failed to quit DaVinci Resolve"

@mcp.tool()
def restart_app(wait_seconds: int = 5) -> str:
    """
    Restart DaVinci Resolve application.
    
    Args:
        wait_seconds: Seconds to wait between quit and restart
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    result = restart_resolve_app(resolve, wait_seconds)
    
    if result:
        return "DaVinci Resolve restart initiated successfully"
    else:
        return "Failed to restart DaVinci Resolve"

@mcp.tool()
def open_settings() -> str:
    """Open the Project Settings dialog in DaVinci Resolve."""
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    result = open_project_settings(resolve)
    
    if result:
        return "Project Settings dialog opened successfully"
    else:
        return "Failed to open Project Settings dialog"

@mcp.tool()
def open_app_preferences() -> str:
    """Open the Preferences dialog in DaVinci Resolve."""
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    result = open_preferences(resolve)
    
    if result:
        return "Preferences dialog opened successfully"
    else:
        return "Failed to open Preferences dialog"

# ------------------
# Cloud Project Operations
# ------------------

@mcp.resource("resolve://cloud/projects")
def get_cloud_projects() -> Dict[str, Any]:
    """Get list of available cloud projects."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return get_cloud_project_list(resolve)

@mcp.tool()
def create_cloud_project_tool(project_name: str, folder_path: str = None) -> Dict[str, Any]:
    """Create a new cloud project.
    
    Args:
        project_name: Name for the new cloud project
        folder_path: Optional path for the cloud project folder
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return create_cloud_project(resolve, project_name, folder_path)

@mcp.tool()
def import_cloud_project_tool(cloud_id: str, project_name: str = None) -> Dict[str, Any]:
    """Import a project from DaVinci Resolve cloud.
    
    Args:
        cloud_id: Cloud ID or reference of the project to import
        project_name: Optional custom name for the imported project (uses original name if None)
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return import_cloud_project(resolve, cloud_id, project_name)

@mcp.tool()
def restore_cloud_project_tool(cloud_id: str, project_name: str = None) -> Dict[str, Any]:
    """Restore a project from DaVinci Resolve cloud.
    
    Args:
        cloud_id: Cloud ID or reference of the project to restore
        project_name: Optional custom name for the restored project (uses original name if None)
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return restore_cloud_project(resolve, cloud_id, project_name)

@mcp.tool()
def export_project_to_cloud_tool(project_name: str = None) -> Dict[str, Any]:
    """Export current or specified project to DaVinci Resolve cloud.
    
    Args:
        project_name: Optional name of project to export (uses current project if None)
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return export_project_to_cloud(resolve, project_name)

@mcp.tool()
def add_user_to_cloud_project_tool(cloud_id: str, user_email: str, permissions: str = "viewer") -> Dict[str, Any]:
    """Add a user to a cloud project with specified permissions.
    
    Args:
        cloud_id: Cloud ID of the project
        user_email: Email of the user to add
        permissions: Permission level (viewer, editor, admin)
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return add_user_to_cloud_project(resolve, cloud_id, user_email, permissions)

@mcp.tool()
def remove_user_from_cloud_project_tool(cloud_id: str, user_email: str) -> Dict[str, Any]:
    """Remove a user from a cloud project.
    
    Args:
        cloud_id: Cloud ID of the project
        user_email: Email of the user to remove
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return remove_user_from_cloud_project(resolve, cloud_id, user_email)

# ------------------
# Project Properties
# ------------------

@mcp.resource("resolve://project/properties")
def get_project_properties_endpoint() -> Dict[str, Any]:
    """Get all project properties for the current project."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_all_project_properties(current_project)

@mcp.resource("resolve://project/property/{property_name}")
def get_project_property_endpoint(property_name: str) -> Dict[str, Any]:
    """Get a specific project property value.
    
    Args:
        property_name: Name of the property to get
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    value = get_project_property(current_project, property_name)
    return {property_name: value}

@mcp.tool()
def set_project_property_tool(property_name: str, property_value: Any) -> str:
    """Set a project property value.
    
    Args:
        property_name: Name of the property to set
        property_value: Value to set for the property
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    result = set_project_property(current_project, property_name, property_value)
    
    if result:
        return f"Successfully set project property '{property_name}' to '{property_value}'"
    else:
        return f"Failed to set project property '{property_name}'"

@mcp.resource("resolve://project/timeline-format")
def get_timeline_format() -> Dict[str, Any]:
    """Get timeline format settings for the current project."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_timeline_format_settings(current_project)

@mcp.tool()
def set_timeline_format_tool(width: int, height: int, frame_rate: float, interlaced: bool = False) -> str:
    """Set timeline format (resolution and frame rate).
    
    Args:
        width: Timeline width in pixels
        height: Timeline height in pixels
        frame_rate: Timeline frame rate
        interlaced: Whether the timeline should use interlaced processing
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    result = set_timeline_format(current_project, width, height, frame_rate, interlaced)
    
    if result:
        interlace_status = "interlaced" if interlaced else "progressive"
        return f"Successfully set timeline format to {width}x{height} at {frame_rate} fps ({interlace_status})"
    else:
        return "Failed to set timeline format"

@mcp.resource("resolve://project/superscale")
def get_superscale_settings_endpoint() -> Dict[str, Any]:
    """Get SuperScale settings for the current project."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_superscale_settings(current_project)

@mcp.tool()
def set_superscale_settings_tool(enabled: bool, quality: int = 0) -> str:
    """Set SuperScale settings for the current project.
    
    Args:
        enabled: Whether SuperScale is enabled
        quality: SuperScale quality (0=Auto, 1=Better Quality, 2=Smoother)
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    quality_names = {
        0: "Auto",
        1: "Better Quality",
        2: "Smoother"
    }
    
    result = set_superscale_settings(current_project, enabled, quality)
    
    if result:
        status = "enabled" if enabled else "disabled"
        quality_name = quality_names.get(quality, "Unknown")
        return f"Successfully {status} SuperScale with quality set to {quality_name}"
    else:
        return "Failed to set SuperScale settings"

@mcp.resource("resolve://project/color-settings")
def get_color_settings_endpoint() -> Dict[str, Any]:
    """Get color science and color space settings for the current project."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_color_settings(current_project)

@mcp.tool()
def set_color_science_mode_tool(mode: str) -> str:
    """Set color science mode for the current project.
    
    Args:
        mode: Color science mode ('YRGB', 'YRGB Color Managed', 'ACEScct', or numeric value)
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    result = set_color_science_mode(current_project, mode)
    
    if result:
        return f"Successfully set color science mode to '{mode}'"
    else:
        return f"Failed to set color science mode to '{mode}'"

@mcp.tool()
def set_color_space_tool(color_space: str, gamma: str = None) -> str:
    """Set timeline color space and gamma.
    
    Args:
        color_space: Timeline color space (e.g., 'Rec.709', 'DCI-P3 D65', 'Rec.2020')
        gamma: Timeline gamma (e.g., 'Rec.709 Gamma', 'Gamma 2.4')
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    result = set_color_space(current_project, color_space, gamma)
    
    if result:
        if gamma:
            return f"Successfully set timeline color space to '{color_space}' with gamma '{gamma}'"
        else:
            return f"Successfully set timeline color space to '{color_space}'"
    else:
        return "Failed to set timeline color space"

@mcp.resource("resolve://project/metadata")
def get_project_metadata_endpoint() -> Dict[str, Any]:
    """Get metadata for the current project."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_project_metadata(current_project)

@mcp.resource("resolve://project/info")
def get_project_info_endpoint() -> Dict[str, Any]:
    """Get comprehensive information about the current project."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_project_info(current_project)

# ------------------
# MediaStorage Tools
# ------------------

@mcp.tool()
def get_mounted_volumes() -> Dict[str, Any]:
    """Get list of mounted volumes displayed in Resolve's Media Storage."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    ms = resolve.GetMediaStorage()
    if not ms:
        return {"error": "Failed to get MediaStorage"}
    volumes = ms.GetMountedVolumeList()
    return {"volumes": volumes if volumes else []}

@mcp.tool()
def get_media_storage_subfolders(folder_path: str) -> Dict[str, Any]:
    """Get subfolders in a given absolute folder path from Media Storage.

    Args:
        folder_path: Absolute path to the folder to list subfolders for.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    ms = resolve.GetMediaStorage()
    if not ms:
        return {"error": "Failed to get MediaStorage"}
    subfolders = ms.GetSubFolderList(folder_path)
    return {"folder_path": folder_path, "subfolders": subfolders if subfolders else []}

@mcp.tool()
def get_media_storage_files(folder_path: str) -> Dict[str, Any]:
    """Get media and file listings in a given absolute folder path from Media Storage.

    Args:
        folder_path: Absolute path to the folder to list files for.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    ms = resolve.GetMediaStorage()
    if not ms:
        return {"error": "Failed to get MediaStorage"}
    files = ms.GetFileList(folder_path)
    return {"folder_path": folder_path, "files": files if files else []}

@mcp.tool()
def reveal_in_media_storage(file_path: str) -> Dict[str, Any]:
    """Reveal a file path in Resolve's Media Storage browser.

    Args:
        file_path: Absolute path to the file to reveal.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    ms = resolve.GetMediaStorage()
    if not ms:
        return {"error": "Failed to get MediaStorage"}
    result = ms.RevealInStorage(file_path)
    return {"success": bool(result), "file_path": file_path}

@mcp.tool()
def add_items_to_media_pool_from_storage(file_paths: List[str]) -> Dict[str, Any]:
    """Add specified file/folder paths from Media Storage into current Media Pool folder.

    Args:
        file_paths: List of absolute file or folder paths to add to the Media Pool.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    ms = resolve.GetMediaStorage()
    if not ms:
        return {"error": "Failed to get MediaStorage"}
    clips = ms.AddItemListToMediaPool(file_paths)
    if clips:
        return {"success": True, "clips_added": len(clips)}
    return {"success": False, "error": "Failed to add items to Media Pool"}

@mcp.tool()
def add_clip_mattes_to_media_pool(media_pool_item_id: str, matte_paths: List[str]) -> Dict[str, Any]:
    """Add clip mattes from Media Storage to a MediaPoolItem.

    Args:
        media_pool_item_id: The unique ID of the MediaPoolItem.
        matte_paths: List of absolute file paths for the matte files.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    ms = resolve.GetMediaStorage()
    if not ms:
        return {"error": "Failed to get MediaStorage"}

    # Find the media pool item by ID
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    mp = project.GetMediaPool()
    root = mp.GetRootFolder()

    # Search for clip by ID
    def find_clip_by_id(folder, target_id):
        for clip in (folder.GetClipList() or []):
            if clip.GetUniqueId() == target_id:
                return clip
        for sub in (folder.GetSubFolderList() or []):
            found = find_clip_by_id(sub, target_id)
            if found:
                return found
        return None

    clip = find_clip_by_id(root, media_pool_item_id)
    if not clip:
        return {"error": f"MediaPoolItem with ID {media_pool_item_id} not found"}

    result = ms.AddClipMattesToMediaPool(clip, matte_paths, root)
    return {"success": bool(result)}

@mcp.tool()
def add_timeline_mattes_to_media_pool(timeline_item_index: int, matte_paths: List[str], track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Add timeline mattes from Media Storage to a timeline item.

    Args:
        timeline_item_index: 0-based index of the item in the track.
        matte_paths: List of absolute file paths for the matte files.
        track_type: Track type ('video' or 'audio'). Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    ms = resolve.GetMediaStorage()
    if not ms:
        return {"error": "Failed to get MediaStorage"}

    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    timeline = project.GetCurrentTimeline()
    if not timeline:
        return {"error": "No current timeline"}

    items = timeline.GetItemListInTrack(track_type, track_index)
    if not items or timeline_item_index >= len(items):
        return {"error": f"Timeline item at index {timeline_item_index} not found"}

    item = items[timeline_item_index]
    result = ms.AddTimelineMattesToMediaPool(item, matte_paths)
    return {"success": bool(result)}


# ------------------
# Resolve Object Tools (missing methods)
# ------------------

@mcp.tool()
def get_resolve_version_fields() -> Dict[str, Any]:
    """Get DaVinci Resolve version as structured fields [major, minor, patch, build, suffix]."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    version = resolve.GetVersion()
    if version:
        return {"major": version[0], "minor": version[1], "patch": version[2], "build": version[3], "suffix": version[4] if len(version) > 4 else ""}
    return {"error": "Failed to get version"}

@mcp.tool()
def get_fusion_object() -> Dict[str, Any]:
    """Get the Fusion object. Starting point for Fusion scripts."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    fusion = resolve.Fusion()
    if fusion:
        return {"success": True, "fusion_available": True}
    return {"success": False, "fusion_available": False}

@mcp.tool()
def update_layout_preset(preset_name: str) -> Dict[str, Any]:
    """Overwrite an existing layout preset with the current UI layout.

    Args:
        preset_name: Name of the preset to overwrite.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.UpdateLayoutPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}

@mcp.tool()
def import_render_preset(preset_path: str) -> Dict[str, Any]:
    """Import a render preset from a file.

    Args:
        preset_path: Absolute path to the render preset file.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.ImportRenderPreset(preset_path)
    return {"success": bool(result), "preset_path": preset_path}

@mcp.tool()
def export_render_preset(preset_name: str, export_path: str) -> Dict[str, Any]:
    """Export a render preset to a file.

    Args:
        preset_name: Name of the render preset to export.
        export_path: Absolute path where the preset file will be saved.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.ExportRenderPreset(preset_name, export_path)
    return {"success": bool(result), "preset_name": preset_name, "export_path": export_path}

@mcp.tool()
def import_burn_in_preset(preset_path: str) -> Dict[str, Any]:
    """Import a burn-in preset from a file.

    Args:
        preset_path: Absolute path to the burn-in preset file.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.ImportBurnInPreset(preset_path)
    return {"success": bool(result), "preset_path": preset_path}

@mcp.tool()
def export_burn_in_preset(preset_name: str, export_path: str) -> Dict[str, Any]:
    """Export a burn-in preset to a file.

    Args:
        preset_name: Name of the burn-in preset to export.
        export_path: Absolute path where the preset file will be saved.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.ExportBurnInPreset(preset_name, export_path)
    return {"success": bool(result), "preset_name": preset_name, "export_path": export_path}

@mcp.tool()
def get_keyframe_mode() -> Dict[str, Any]:
    """Get the current keyframe mode in Resolve. Returns 0=ALL, 1=COLOR, 2=SIZING."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    mode = resolve.GetKeyframeMode()
    mode_names = {0: "All", 1: "Color", 2: "Sizing"}
    return {"keyframe_mode": mode, "mode_name": mode_names.get(mode, "Unknown")}

@mcp.tool()
def set_keyframe_mode(mode: int) -> Dict[str, Any]:
    """Set the keyframe mode in Resolve.

    Args:
        mode: Keyframe mode - 0=All, 1=Color, 2=Sizing.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    if mode not in (0, 1, 2):
        return {"error": "Invalid mode. Must be 0 (All), 1 (Color), or 2 (Sizing)"}
    result = resolve.SetKeyframeMode(mode)
    mode_names = {0: "All", 1: "Color", 2: "Sizing"}
    return {"success": bool(result), "keyframe_mode": mode, "mode_name": mode_names[mode]}

@mcp.tool()
def quit_resolve() -> Dict[str, Any]:
    """Quit DaVinci Resolve. WARNING: This will close the application."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.Quit()
    return {"success": True, "message": "DaVinci Resolve is quitting"}


# ------------------
# ProjectManager Tools (missing methods)
# ------------------

@mcp.tool()
def archive_project(project_name: str, archive_path: str, archive_src_media: bool = True, archive_render_cache: bool = True, archive_proxy_media: bool = False) -> Dict[str, Any]:
    """Archive a project to a file with optional media.

    Args:
        project_name: Name of the project to archive.
        archive_path: Absolute path for the archive file (.dra).
        archive_src_media: Include source media in archive. Default: True.
        archive_render_cache: Include render cache. Default: True.
        archive_proxy_media: Include proxy media. Default: False.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.ArchiveProject(project_name, archive_path, archive_src_media, archive_render_cache, archive_proxy_media)
    return {"success": bool(result), "project_name": project_name, "archive_path": archive_path}

@mcp.tool()
def delete_project(project_name: str) -> Dict[str, Any]:
    """Delete a project from the current database. WARNING: This is irreversible.

    Args:
        project_name: Name of the project to delete.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.DeleteProject(project_name)
    return {"success": bool(result), "project_name": project_name}

@mcp.tool()
def create_project_folder(folder_name: str) -> Dict[str, Any]:
    """Create a new folder in the current project folder location.

    Args:
        folder_name: Name of the folder to create.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.CreateFolder(folder_name)
    return {"success": bool(result), "folder_name": folder_name}

@mcp.tool()
def delete_project_folder(folder_name: str) -> Dict[str, Any]:
    """Delete a folder from the current project folder location.

    Args:
        folder_name: Name of the folder to delete.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.DeleteFolder(folder_name)
    return {"success": bool(result), "folder_name": folder_name}

@mcp.tool()
def get_project_folder_list() -> Dict[str, Any]:
    """Get list of folders in the current project folder location."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    folders = pm.GetFolderListInCurrentFolder()
    return {"folders": folders if folders else []}

@mcp.tool()
def goto_root_project_folder() -> Dict[str, Any]:
    """Navigate to the root project folder."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.GotoRootFolder()
    return {"success": bool(result)}

@mcp.tool()
def goto_parent_project_folder() -> Dict[str, Any]:
    """Navigate up one level in the project folder hierarchy."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.GotoParentFolder()
    return {"success": bool(result)}

@mcp.tool()
def get_current_project_folder() -> Dict[str, Any]:
    """Get the name of the current project folder."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    folder = pm.GetCurrentFolder()
    return {"current_folder": folder}

@mcp.tool()
def open_project_folder(folder_name: str) -> Dict[str, Any]:
    """Open/navigate into a project folder.

    Args:
        folder_name: Name of the folder to open.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.OpenFolder(folder_name)
    return {"success": bool(result), "folder_name": folder_name}

@mcp.tool()
def import_project_from_file(file_path: str) -> Dict[str, Any]:
    """Import a project from a .drp file.

    Args:
        file_path: Absolute path to the .drp project file.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.ImportProject(file_path)
    return {"success": bool(result), "file_path": file_path}

@mcp.tool()
def export_project_to_file(project_name: str, file_path: str, with_stills_and_luts: bool = True) -> Dict[str, Any]:
    """Export a project to a .drp file.

    Args:
        project_name: Name of the project to export.
        file_path: Absolute path for the exported .drp file.
        with_stills_and_luts: Include stills and LUTs in export. Default: True.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.ExportProject(project_name, file_path, with_stills_and_luts)
    return {"success": bool(result), "project_name": project_name, "file_path": file_path}

@mcp.tool()
def restore_project(file_path: str) -> Dict[str, Any]:
    """Restore a project from an archive (.dra) file.

    Args:
        file_path: Absolute path to the .dra archive file.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.RestoreProject(file_path)
    return {"success": bool(result), "file_path": file_path}

@mcp.tool()
def get_current_database() -> Dict[str, Any]:
    """Get information about the current database."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    db = pm.GetCurrentDatabase()
    return db if db else {"error": "Failed to get current database"}

@mcp.tool()
def get_database_list() -> Dict[str, Any]:
    """Get list of all available databases."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    dbs = pm.GetDatabaseList()
    return {"databases": dbs if dbs else []}

@mcp.tool()
def set_current_database(db_info: Dict[str, str]) -> Dict[str, Any]:
    """Switch to a different database.

    Args:
        db_info: Database info dict with keys 'DbType' and 'DbName'. Example: {"DbType": "Disk", "DbName": "Local Database"}
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.SetCurrentDatabase(db_info)
    return {"success": bool(result), "database": db_info}


# ------------------
# Project Tools (missing methods)
# ------------------

@mcp.tool()
def set_project_name(name: str) -> Dict[str, Any]:
    """Rename the current project.

    Args:
        name: New name for the project.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SetName(name)
    return {"success": bool(result), "name": name}

@mcp.tool()
def get_timeline_by_index(index: int) -> Dict[str, Any]:
    """Get a timeline by its 1-based index.

    Args:
        index: 1-based timeline index.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    tl = project.GetTimelineByIndex(index)
    if tl:
        return {"name": tl.GetName(), "start_frame": tl.GetStartFrame(), "end_frame": tl.GetEndFrame(), "unique_id": tl.GetUniqueId()}
    return {"error": f"No timeline at index {index}"}

@mcp.tool()
def get_project_preset_list() -> Dict[str, Any]:
    """Get list of available project presets."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    presets = project.GetPresetList()
    return {"presets": presets if presets else []}

@mcp.tool()
def set_project_preset(preset_name: str) -> Dict[str, Any]:
    """Apply a project preset to the current project.

    Args:
        preset_name: Name of the preset to apply.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SetPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}

@mcp.tool()
def delete_render_job(job_id: str) -> Dict[str, Any]:
    """Delete a specific render job by its ID.

    Args:
        job_id: The unique ID of the render job to delete.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.DeleteRenderJob(job_id)
    return {"success": bool(result), "job_id": job_id}

@mcp.tool()
def get_render_job_list() -> Dict[str, Any]:
    """Get list of all render jobs in the queue."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    jobs = project.GetRenderJobList()
    return {"render_jobs": jobs if jobs else []}

@mcp.tool()
def start_rendering_jobs(job_ids: Optional[List[str]] = None, is_interactive_mode: bool = False) -> Dict[str, Any]:
    """Start rendering jobs. If no job IDs specified, renders all queued jobs.

    Args:
        job_ids: Optional list of job IDs to render. If None, renders all.
        is_interactive_mode: If True, enables interactive rendering mode.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    if job_ids:
        result = project.StartRendering(job_ids, is_interactive_mode)
    else:
        result = project.StartRendering(is_interactive_mode)
    return {"success": bool(result)}

@mcp.tool()
def stop_rendering() -> Dict[str, Any]:
    """Stop the current rendering process."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    project.StopRendering()
    return {"success": True}

@mcp.tool()
def is_rendering_in_progress() -> Dict[str, Any]:
    """Check if rendering is currently in progress."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.IsRenderingInProgress()
    return {"is_rendering": bool(result)}

@mcp.tool()
def load_render_preset(preset_name: str) -> Dict[str, Any]:
    """Load a render preset by name.

    Args:
        preset_name: Name of the render preset to load.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.LoadRenderPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}

@mcp.tool()
def save_as_new_render_preset(preset_name: str) -> Dict[str, Any]:
    """Save current render settings as a new preset.

    Args:
        preset_name: Name for the new render preset.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SaveAsNewRenderPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}

@mcp.tool()
def delete_render_preset(preset_name: str) -> Dict[str, Any]:
    """Delete a render preset.

    Args:
        preset_name: Name of the render preset to delete.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.DeleteRenderPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}

@mcp.tool()
def set_render_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Set render settings for the current project.

    Args:
        settings: Dict of render settings. Supported keys include:
            SelectAllFrames (bool), MarkIn (int), MarkOut (int),
            TargetDir (str), CustomName (str), UniqueFilenameStyle (0/1),
            ExportVideo (bool), ExportAudio (bool), FormatWidth (int),
            FormatHeight (int), FrameRate (float), VideoQuality (int/str),
            AudioCodec (str), AudioBitDepth (int), AudioSampleRate (int),
            ColorSpaceTag (str), GammaTag (str), ExportAlpha (bool).
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SetRenderSettings(settings)
    return {"success": bool(result)}

@mcp.tool()
def get_render_job_status(job_id: str) -> Dict[str, Any]:
    """Get the status of a specific render job.

    Args:
        job_id: The unique ID of the render job.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    status = project.GetRenderJobStatus(job_id)
    return status if status else {"error": f"No render job with ID {job_id}"}

@mcp.tool()
def get_render_formats() -> Dict[str, Any]:
    """Get all available render formats."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    formats = project.GetRenderFormats()
    return {"formats": formats if formats else {}}

@mcp.tool()
def get_render_codecs(format_name: str) -> Dict[str, Any]:
    """Get available codecs for a given render format.

    Args:
        format_name: Render format name (e.g. 'mp4', 'mov', 'avi').
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    codecs = project.GetRenderCodecs(format_name)
    return {"format": format_name, "codecs": codecs if codecs else {}}

@mcp.tool()
def get_current_render_format_and_codec() -> Dict[str, Any]:
    """Get the current render format and codec setting."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.GetCurrentRenderFormatAndCodec()
    return result if result else {"error": "Failed to get render format and codec"}

@mcp.tool()
def set_current_render_format_and_codec(format_name: str, codec_name: str) -> Dict[str, Any]:
    """Set the render format and codec.

    Args:
        format_name: Render format (e.g. 'mp4', 'mov').
        codec_name: Codec name (e.g. 'H264', 'H265', 'ProRes422HQ').
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SetCurrentRenderFormatAndCodec(format_name, codec_name)
    return {"success": bool(result), "format": format_name, "codec": codec_name}

@mcp.tool()
def get_current_render_mode() -> Dict[str, Any]:
    """Get the current render mode (0=Individual Clips, 1=Single Clip)."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    mode = project.GetCurrentRenderMode()
    return {"render_mode": mode, "mode_name": "Individual Clips" if mode == 0 else "Single Clip"}

@mcp.tool()
def set_current_render_mode(mode: int) -> Dict[str, Any]:
    """Set the render mode.

    Args:
        mode: 0 for Individual Clips, 1 for Single Clip.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SetCurrentRenderMode(mode)
    return {"success": bool(result), "render_mode": mode}

@mcp.tool()
def get_render_resolutions(format_name: str, codec_name: str) -> Dict[str, Any]:
    """Get available render resolutions for a format/codec combination.

    Args:
        format_name: Render format (e.g. 'mp4').
        codec_name: Codec name (e.g. 'H264').
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    resolutions = project.GetRenderResolutions(format_name, codec_name)
    return {"format": format_name, "codec": codec_name, "resolutions": resolutions if resolutions else []}

@mcp.tool()
def refresh_lut_list() -> Dict[str, Any]:
    """Refresh the LUT list in the project. Call after adding new LUT files."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.RefreshLUTList()
    return {"success": bool(result)}

@mcp.tool()
def get_project_unique_id() -> Dict[str, Any]:
    """Get the unique ID of the current project."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    uid = project.GetUniqueId()
    return {"unique_id": uid}

@mcp.tool()
def insert_audio_to_current_track(file_path: str) -> Dict[str, Any]:
    """Insert audio file to current track at playhead position.

    Args:
        file_path: Absolute path to the audio file.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.InsertAudioToCurrentTrackAtPlayhead(file_path)
    return {"success": bool(result), "file_path": file_path}

@mcp.tool()
def load_burn_in_preset(preset_name: str) -> Dict[str, Any]:
    """Load a burn-in preset by name for the project.

    Args:
        preset_name: Name of the burn-in preset to load.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.LoadBurnInPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}

@mcp.tool()
def export_current_frame_as_still(file_path: str) -> Dict[str, Any]:
    """Export the current frame as a still image.

    Args:
        file_path: Absolute path for the exported still image.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.ExportCurrentFrameAsStill(file_path)
    return {"success": bool(result), "file_path": file_path}

@mcp.tool()
def get_color_groups_list() -> Dict[str, Any]:
    """Get list of all color groups in the current project."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    groups = project.GetColorGroupsList()
    if groups:
        return {"color_groups": [{"name": g.GetName()} for g in groups]}
    return {"color_groups": []}

@mcp.tool()
def add_color_group(group_name: str) -> Dict[str, Any]:
    """Create a new color group in the current project.

    Args:
        group_name: Name for the new color group.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.AddColorGroup(group_name)
    return {"success": bool(result), "group_name": group_name}

@mcp.tool()
def delete_color_group(group_name: str) -> Dict[str, Any]:
    """Delete a color group from the current project.

    Args:
        group_name: Name of the color group to delete.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    # Find the group by name
    groups = project.GetColorGroupsList()
    target = None
    if groups:
        for g in groups:
            if g.GetName() == group_name:
                target = g
                break
    if not target:
        return {"error": f"Color group '{group_name}' not found"}
    result = project.DeleteColorGroup(target)
    return {"success": bool(result), "group_name": group_name}

@mcp.tool()
def get_quick_export_render_presets() -> Dict[str, Any]:
    """Get list of available quick export render presets."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    presets = project.GetQuickExportRenderPresets()
    return {"presets": presets if presets else []}

@mcp.tool()
def render_with_quick_export(preset_name: str) -> Dict[str, Any]:
    """Render the current timeline using a Quick Export preset.

    Args:
        preset_name: Name of the Quick Export preset (e.g. 'H.264', 'YouTube', 'Vimeo').
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.RenderWithQuickExport(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


# ------------------
# Helper: get project/mediapool
# ------------------
def _get_mp():
    if resolve is None:
        return None, None, {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return None, None, {"error": "No project currently open"}
    mp = project.GetMediaPool()
    if not mp:
        return project, None, {"error": "Failed to get MediaPool"}
    return project, mp, None

def _find_clip_by_id(folder, target_id):
    for clip in (folder.GetClipList() or []):
        if clip.GetUniqueId() == target_id:
            return clip
    for sub in (folder.GetSubFolderList() or []):
        found = _find_clip_by_id(sub, target_id)
        if found:
            return found
    return None

def _find_clips_by_ids(folder, ids_set):
    found = []
    for clip in (folder.GetClipList() or []):
        if clip.GetUniqueId() in ids_set:
            found.append(clip)
    for sub in (folder.GetSubFolderList() or []):
        found.extend(_find_clips_by_ids(sub, ids_set))
    return found

def _navigate_to_folder(mp, folder_path):
    root = mp.GetRootFolder()
    if not folder_path or folder_path in ("Master", "/", ""):
        return root
    parts = folder_path.strip("/").split("/")
    if parts[0] == "Master":
        parts = parts[1:]
    current = root
    for part in parts:
        found = False
        for sub in (current.GetSubFolderList() or []):
            if sub.GetName() == part:
                current = sub
                found = True
                break
        if not found:
            return None
    return current

def _get_timeline():
    if resolve is None:
        return None, None, {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return None, None, {"error": "No project currently open"}
    tl = project.GetCurrentTimeline()
    if not tl:
        return project, None, {"error": "No current timeline"}
    return project, tl, None

def _get_timeline_item(track_type="video", track_index=1, item_index=0):
    _, tl, err = _get_timeline()
    if err:
        return None, err
    items = tl.GetItemListInTrack(track_type, track_index)
    if not items or item_index >= len(items):
        return None, {"error": f"No item at index {item_index} on {track_type} track {track_index}"}
    return items[item_index], None


# ------------------
# MediaPool Tools (remaining)
# ------------------

@mcp.tool()
def add_subfolder(folder_name: str) -> Dict[str, Any]:
    """Create a new subfolder in the current Media Pool folder.

    Args:
        folder_name: Name of the subfolder to create.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    folder = mp.AddSubFolder(mp.GetCurrentFolder(), folder_name)
    if folder:
        return {"success": True, "folder_name": folder.GetName(), "unique_id": folder.GetUniqueId()}
    return {"success": False, "error": f"Failed to create subfolder '{folder_name}'"}

@mcp.tool()
def refresh_media_pool_folders() -> Dict[str, Any]:
    """Refresh all folders in the Media Pool."""
    _, mp, err = _get_mp()
    if err:
        return err
    result = mp.RefreshFolders()
    return {"success": bool(result)}

@mcp.tool()
def import_timeline_from_file(file_path: str, import_options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Import a timeline from a file (AAF, EDL, XML, FCPXML, DRT, ADL, OTIO).

    Args:
        file_path: Absolute path to the timeline file.
        import_options: Optional dict of import options.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    if import_options:
        tl = mp.ImportTimelineFromFile(file_path, import_options)
    else:
        tl = mp.ImportTimelineFromFile(file_path)
    if tl:
        return {"success": True, "timeline_name": tl.GetName(), "unique_id": tl.GetUniqueId()}
    return {"success": False, "error": f"Failed to import timeline from '{file_path}'"}

@mcp.tool()
def delete_timelines_by_id(timeline_ids: List[str]) -> Dict[str, Any]:
    """Delete timelines by their unique IDs.

    Args:
        timeline_ids: List of timeline unique IDs to delete.
    """
    project, mp, err = _get_mp()
    if err:
        return err
    timelines = []
    for i in range(1, project.GetTimelineCount() + 1):
        tl = project.GetTimelineByIndex(i)
        if tl and tl.GetUniqueId() in timeline_ids:
            timelines.append(tl)
    if not timelines:
        return {"error": "No matching timelines found"}
    result = mp.DeleteTimelines(timelines)
    return {"success": bool(result), "deleted_count": len(timelines)}

@mcp.tool()
def set_current_media_pool_folder(folder_path: str) -> Dict[str, Any]:
    """Navigate to a specific folder in the Media Pool.

    Args:
        folder_path: Folder path using '/' separators from root (e.g. 'Master/Footage').
    """
    _, mp, err = _get_mp()
    if err:
        return err
    target = _navigate_to_folder(mp, folder_path)
    if not target:
        return {"error": f"Folder '{folder_path}' not found"}
    result = mp.SetCurrentFolder(target)
    return {"success": bool(result), "folder": target.GetName()}

@mcp.tool()
def delete_media_pool_clips(clip_ids: List[str]) -> Dict[str, Any]:
    """Delete clips from the Media Pool by their unique IDs.

    Args:
        clip_ids: List of clip unique IDs to delete.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clips = _find_clips_by_ids(mp.GetRootFolder(), set(clip_ids))
    if not clips:
        return {"error": "No matching clips found"}
    result = mp.DeleteClips(clips)
    return {"success": bool(result), "deleted_count": len(clips)}

@mcp.tool()
def import_folder_from_file(file_path: str) -> Dict[str, Any]:
    """Import a Media Pool folder structure from a file.

    Args:
        file_path: Absolute path to the file.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    result = mp.ImportFolderFromFile(file_path)
    return {"success": bool(result), "file_path": file_path}

@mcp.tool()
def delete_media_pool_folders(folder_names: List[str]) -> Dict[str, Any]:
    """Delete folders from the current Media Pool location.

    Args:
        folder_names: List of folder names to delete.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    current = mp.GetCurrentFolder()
    folders = [sub for sub in (current.GetSubFolderList() or []) if sub.GetName() in folder_names]
    if not folders:
        return {"error": "No matching folders found"}
    result = mp.DeleteFolders(folders)
    return {"success": bool(result), "deleted_count": len(folders)}

@mcp.tool()
def move_clips_to_folder(clip_ids: List[str], target_folder_path: str) -> Dict[str, Any]:
    """Move clips to a different Media Pool folder.

    Args:
        clip_ids: List of clip unique IDs to move.
        target_folder_path: Path to target folder (e.g. 'Master/Footage').
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clips = _find_clips_by_ids(mp.GetRootFolder(), set(clip_ids))
    if not clips:
        return {"error": "No matching clips found"}
    target = _navigate_to_folder(mp, target_folder_path)
    if not target:
        return {"error": f"Target folder '{target_folder_path}' not found"}
    result = mp.MoveClips(clips, target)
    return {"success": bool(result), "moved_count": len(clips)}

@mcp.tool()
def move_media_pool_folders(folder_names: List[str], target_folder_path: str) -> Dict[str, Any]:
    """Move folders to a different Media Pool location.

    Args:
        folder_names: List of folder names to move.
        target_folder_path: Path to target folder.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    current = mp.GetCurrentFolder()
    folders = [sub for sub in (current.GetSubFolderList() or []) if sub.GetName() in folder_names]
    if not folders:
        return {"error": "No matching folders found"}
    target = _navigate_to_folder(mp, target_folder_path)
    if not target:
        return {"error": f"Target folder '{target_folder_path}' not found"}
    result = mp.MoveFolders(folders, target)
    return {"success": bool(result), "moved_count": len(folders)}

@mcp.tool()
def get_clip_matte_list(clip_id: str) -> Dict[str, Any]:
    """Get list of clip mattes for a MediaPoolItem.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip with ID {clip_id} not found"}
    mattes = mp.GetClipMatteList(clip)
    return {"clip_id": clip_id, "mattes": mattes if mattes else []}

@mcp.tool()
def get_timeline_matte_list(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get list of timeline mattes for a timeline item.

    Args:
        item_index: 0-based index of the item in the track. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    project, mp, err = _get_mp()
    if err:
        return err
    tl = project.GetCurrentTimeline()
    if not tl:
        return {"error": "No current timeline"}
    items = tl.GetItemListInTrack(track_type, track_index)
    if not items or item_index >= len(items):
        return {"error": f"No item at index {item_index}"}
    mattes = mp.GetTimelineMatteList(items[item_index])
    return {"mattes": mattes if mattes else []}

@mcp.tool()
def delete_clip_mattes(clip_id: str, matte_paths: List[str]) -> Dict[str, Any]:
    """Delete clip mattes from a MediaPoolItem.

    Args:
        clip_id: Unique ID of the clip.
        matte_paths: List of matte file paths to delete.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip with ID {clip_id} not found"}
    result = mp.DeleteClipMattes(clip, matte_paths)
    return {"success": bool(result)}

@mcp.tool()
def export_media_pool_metadata(file_path: str) -> Dict[str, Any]:
    """Export metadata of clips in the current Media Pool folder to a CSV file.

    Args:
        file_path: Absolute path for the exported CSV file.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    result = mp.ExportMetadata(file_path)
    return {"success": bool(result), "file_path": file_path}

@mcp.tool()
def get_media_pool_unique_id() -> Dict[str, Any]:
    """Get the unique ID of the Media Pool."""
    _, mp, err = _get_mp()
    if err:
        return err
    return {"unique_id": mp.GetUniqueId()}

@mcp.tool()
def create_stereo_clip(left_clip_id: str, right_clip_id: str) -> Dict[str, Any]:
    """Create a stereo clip from left and right eye clips.

    Args:
        left_clip_id: Unique ID of the left eye clip.
        right_clip_id: Unique ID of the right eye clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    root = mp.GetRootFolder()
    left = _find_clip_by_id(root, left_clip_id)
    right = _find_clip_by_id(root, right_clip_id)
    if not left:
        return {"error": f"Left clip {left_clip_id} not found"}
    if not right:
        return {"error": f"Right clip {right_clip_id} not found"}
    result = mp.CreateStereoClip(left, right)
    return {"success": bool(result)}

@mcp.tool()
def get_selected_clips() -> Dict[str, Any]:
    """Get currently selected clips in the Media Pool."""
    _, mp, err = _get_mp()
    if err:
        return err
    clips = mp.GetSelectedClips()
    if clips:
        result = []
        for clip in clips:
            try:
                result.append({"name": clip.GetName(), "unique_id": clip.GetUniqueId()})
            except Exception:
                result.append({"name": "Unknown"})
        return {"selected_clips": result}
    return {"selected_clips": []}

@mcp.tool()
def set_selected_clip(clip_id: str) -> Dict[str, Any]:
    """Set a clip as selected in the Media Pool.

    Args:
        clip_id: Unique ID of the clip to select.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = mp.SetSelectedClip(clip)
    return {"success": bool(result)}


# ------------------
# Folder Tools (remaining)
# ------------------

@mcp.tool()
def get_folder_clip_list(folder_path: str = "") -> Dict[str, Any]:
    """Get list of clips in a Media Pool folder.

    Args:
        folder_path: Path from root. Empty for current folder.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    if folder_path:
        folder = _navigate_to_folder(mp, folder_path)
        if not folder:
            return {"error": f"Folder '{folder_path}' not found"}
    else:
        folder = mp.GetCurrentFolder()
    clips = folder.GetClipList()
    if clips:
        return {"folder": folder.GetName(), "clips": [{"name": c.GetName(), "unique_id": c.GetUniqueId()} for c in clips]}
    return {"folder": folder.GetName(), "clips": []}

@mcp.tool()
def get_folder_subfolder_list(folder_path: str = "") -> Dict[str, Any]:
    """Get list of subfolders in a Media Pool folder.

    Args:
        folder_path: Path from root. Empty for current folder.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    if folder_path:
        folder = _navigate_to_folder(mp, folder_path)
        if not folder:
            return {"error": f"Folder '{folder_path}' not found"}
    else:
        folder = mp.GetCurrentFolder()
    subs = folder.GetSubFolderList()
    if subs:
        return {"folder": folder.GetName(), "subfolders": [{"name": s.GetName(), "unique_id": s.GetUniqueId()} for s in subs]}
    return {"folder": folder.GetName(), "subfolders": []}

@mcp.tool()
def get_folder_is_stale(folder_path: str = "") -> Dict[str, Any]:
    """Check if a Media Pool folder is stale (needs refresh).

    Args:
        folder_path: Path from root. Empty for current folder.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    if folder_path:
        folder = _navigate_to_folder(mp, folder_path)
        if not folder:
            return {"error": f"Folder '{folder_path}' not found"}
    else:
        folder = mp.GetCurrentFolder()
    return {"folder": folder.GetName(), "is_stale": bool(folder.GetIsFolderStale())}

@mcp.tool()
def get_folder_unique_id(folder_path: str = "") -> Dict[str, Any]:
    """Get the unique ID of a Media Pool folder.

    Args:
        folder_path: Path from root. Empty for current folder.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    if folder_path:
        folder = _navigate_to_folder(mp, folder_path)
        if not folder:
            return {"error": f"Folder '{folder_path}' not found"}
    else:
        folder = mp.GetCurrentFolder()
    return {"folder": folder.GetName(), "unique_id": folder.GetUniqueId()}

@mcp.tool()
def folder_export(file_path: str, folder_path: str = "") -> Dict[str, Any]:
    """Export a Media Pool folder to a file.

    Args:
        file_path: Absolute path for the export.
        folder_path: Path from root. Empty for current folder.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    if folder_path:
        folder = _navigate_to_folder(mp, folder_path)
        if not folder:
            return {"error": f"Folder '{folder_path}' not found"}
    else:
        folder = mp.GetCurrentFolder()
    result = folder.Export(file_path)
    return {"success": bool(result), "file_path": file_path}

@mcp.tool()
def folder_transcribe_audio(folder_path: str = "") -> Dict[str, Any]:
    """Transcribe audio for all clips in a Media Pool folder.

    Args:
        folder_path: Path from root. Empty for current folder.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    if folder_path:
        folder = _navigate_to_folder(mp, folder_path)
        if not folder:
            return {"error": f"Folder '{folder_path}' not found"}
    else:
        folder = mp.GetCurrentFolder()
    result = folder.TranscribeAudio()
    return {"success": bool(result)}

@mcp.tool()
def folder_clear_transcription(folder_path: str = "") -> Dict[str, Any]:
    """Clear transcription for all clips in a Media Pool folder.

    Args:
        folder_path: Path from root. Empty for current folder.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    if folder_path:
        folder = _navigate_to_folder(mp, folder_path)
        if not folder:
            return {"error": f"Folder '{folder_path}' not found"}
    else:
        folder = mp.GetCurrentFolder()
    result = folder.ClearTranscription()
    return {"success": bool(result)}


# ------------------
# MediaPoolItem Tools (remaining)
# ------------------

@mcp.tool()
def get_clip_metadata(clip_id: str, metadata_type: str = "") -> Dict[str, Any]:
    """Get metadata for a Media Pool clip.

    Args:
        clip_id: Unique ID of the clip.
        metadata_type: Specific metadata key, or empty for all metadata.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    if metadata_type:
        result = clip.GetMetadata(metadata_type)
    else:
        result = clip.GetMetadata()
    return {"clip_id": clip_id, "metadata": result if result else {}}

@mcp.tool()
def set_clip_metadata(clip_id: str, metadata: Dict[str, str]) -> Dict[str, Any]:
    """Set metadata on a Media Pool clip.

    Args:
        clip_id: Unique ID of the clip.
        metadata: Dict of metadata key-value pairs to set.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.SetMetadata(metadata)
    return {"success": bool(result)}

@mcp.tool()
def get_clip_third_party_metadata(clip_id: str, metadata_key: str = "") -> Dict[str, Any]:
    """Get third-party metadata for a clip.

    Args:
        clip_id: Unique ID of the clip.
        metadata_key: Specific key, or empty for all.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    if metadata_key:
        result = clip.GetThirdPartyMetadata(metadata_key)
    else:
        result = clip.GetThirdPartyMetadata()
    return {"clip_id": clip_id, "third_party_metadata": result if result else {}}

@mcp.tool()
def set_clip_third_party_metadata(clip_id: str, metadata: Dict[str, str]) -> Dict[str, Any]:
    """Set third-party metadata on a clip.

    Args:
        clip_id: Unique ID of the clip.
        metadata: Dict of metadata key-value pairs.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.SetThirdPartyMetadata(metadata)
    return {"success": bool(result)}

@mcp.tool()
def get_clip_media_id(clip_id: str) -> Dict[str, Any]:
    """Get the media ID for a clip.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    media_id = clip.GetMediaId()
    return {"clip_id": clip_id, "media_id": media_id}

@mcp.tool()
def add_clip_marker(clip_id: str, frame_id: int, color: str, name: str, note: str = "", duration: int = 1, custom_data: str = "") -> Dict[str, Any]:
    """Add a marker to a Media Pool clip.

    Args:
        clip_id: Unique ID of the clip.
        frame_id: Frame number for the marker.
        color: Marker color (Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream).
        name: Marker name.
        note: Marker note. Default: empty.
        duration: Marker duration in frames. Default: 1.
        custom_data: Custom data string. Default: empty.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.AddMarker(frame_id, color, name, note, duration, custom_data)
    return {"success": bool(result)}

@mcp.tool()
def get_clip_markers(clip_id: str) -> Dict[str, Any]:
    """Get all markers on a Media Pool clip.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    markers = clip.GetMarkers()
    return {"clip_id": clip_id, "markers": markers if markers else {}}

@mcp.tool()
def get_clip_marker_by_custom_data(clip_id: str, custom_data: str) -> Dict[str, Any]:
    """Get a marker by its custom data string.

    Args:
        clip_id: Unique ID of the clip.
        custom_data: Custom data string to search for.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    marker = clip.GetMarkerByCustomData(custom_data)
    return {"marker": marker if marker else {}}

@mcp.tool()
def update_clip_marker_custom_data(clip_id: str, frame_id: int, custom_data: str) -> Dict[str, Any]:
    """Update the custom data of a clip marker.

    Args:
        clip_id: Unique ID of the clip.
        frame_id: Frame number of the marker.
        custom_data: New custom data string.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.UpdateMarkerCustomData(frame_id, custom_data)
    return {"success": bool(result)}

@mcp.tool()
def get_clip_marker_custom_data(clip_id: str, frame_id: int) -> Dict[str, Any]:
    """Get the custom data of a clip marker at a specific frame.

    Args:
        clip_id: Unique ID of the clip.
        frame_id: Frame number of the marker.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    data = clip.GetMarkerCustomData(frame_id)
    return {"frame_id": frame_id, "custom_data": data if data else ""}

@mcp.tool()
def delete_clip_markers_by_color(clip_id: str, color: str) -> Dict[str, Any]:
    """Delete all markers of a specific color on a clip.

    Args:
        clip_id: Unique ID of the clip.
        color: Color of markers to delete. Use '' to delete all.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.DeleteMarkersByColor(color)
    return {"success": bool(result)}

@mcp.tool()
def delete_clip_marker_at_frame(clip_id: str, frame_id: int) -> Dict[str, Any]:
    """Delete a marker at a specific frame on a clip.

    Args:
        clip_id: Unique ID of the clip.
        frame_id: Frame number of the marker to delete.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.DeleteMarkerAtFrame(frame_id)
    return {"success": bool(result)}

@mcp.tool()
def delete_clip_marker_by_custom_data(clip_id: str, custom_data: str) -> Dict[str, Any]:
    """Delete a marker by its custom data string.

    Args:
        clip_id: Unique ID of the clip.
        custom_data: Custom data string of the marker to delete.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.DeleteMarkerByCustomData(custom_data)
    return {"success": bool(result)}

@mcp.tool()
def add_clip_flag(clip_id: str, color: str) -> Dict[str, Any]:
    """Add a flag to a Media Pool clip.

    Args:
        clip_id: Unique ID of the clip.
        color: Flag color (Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream).
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.AddFlag(color)
    return {"success": bool(result)}

@mcp.tool()
def get_clip_flag_list(clip_id: str) -> Dict[str, Any]:
    """Get list of flags on a clip.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    flags = clip.GetFlagList()
    return {"clip_id": clip_id, "flags": flags if flags else []}

@mcp.tool()
def clear_clip_flags(clip_id: str, color: str = "") -> Dict[str, Any]:
    """Clear flags on a clip.

    Args:
        clip_id: Unique ID of the clip.
        color: Specific color to clear, or empty for all colors.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.ClearFlags(color)
    return {"success": bool(result)}

@mcp.tool()
def get_clip_color(clip_id: str) -> Dict[str, Any]:
    """Get the clip color of a Media Pool item.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    color = clip.GetClipColor()
    return {"clip_id": clip_id, "clip_color": color if color else ""}

@mcp.tool()
def set_clip_color(clip_id: str, color: str) -> Dict[str, Any]:
    """Set the clip color of a Media Pool item.

    Args:
        clip_id: Unique ID of the clip.
        color: Color name (Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Brown, Chocolate).
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.SetClipColor(color)
    return {"success": bool(result)}

@mcp.tool()
def clear_clip_color(clip_id: str) -> Dict[str, Any]:
    """Clear the clip color of a Media Pool item.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.ClearClipColor()
    return {"success": bool(result)}

@mcp.tool()
def set_clip_property(clip_id: str, property_name: str, property_value: str) -> Dict[str, Any]:
    """Set a property on a Media Pool clip.

    Args:
        clip_id: Unique ID of the clip.
        property_name: Property name (e.g. 'Clip Name', 'Comments', 'Description').
        property_value: Value to set.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.SetClipProperty(property_name, property_value)
    return {"success": bool(result)}

@mcp.tool()
def get_clip_property(clip_id: str, property_name: str = "") -> Dict[str, Any]:
    """Get a property of a Media Pool clip.

    Args:
        clip_id: Unique ID of the clip.
        property_name: Property name, or empty for all properties.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    if property_name:
        result = clip.GetClipProperty(property_name)
    else:
        result = clip.GetClipProperty()
    return {"clip_id": clip_id, "property": result if result else {}}

@mcp.tool()
def link_clip_proxy_media(clip_id: str, proxy_path: str) -> Dict[str, Any]:
    """Link proxy media to a clip.

    Args:
        clip_id: Unique ID of the clip.
        proxy_path: Absolute path to the proxy media file.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.LinkProxyMedia(proxy_path)
    return {"success": bool(result)}

@mcp.tool()
def unlink_clip_proxy_media(clip_id: str) -> Dict[str, Any]:
    """Unlink proxy media from a clip.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.UnlinkProxyMedia()
    return {"success": bool(result)}

@mcp.tool()
def replace_media_pool_clip(clip_id: str, new_file_path: str) -> Dict[str, Any]:
    """Replace a clip with a new media file.

    Args:
        clip_id: Unique ID of the clip to replace.
        new_file_path: Absolute path to the new media file.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.ReplaceClip(new_file_path)
    return {"success": bool(result)}

@mcp.tool()
def get_clip_unique_id_by_name(clip_name: str) -> Dict[str, Any]:
    """Find a clip by name and return its unique ID.

    Args:
        clip_name: Name of the clip to find.
    """
    _, mp, err = _get_mp()
    if err:
        return err

    def search(folder):
        for clip in (folder.GetClipList() or []):
            if clip.GetName() == clip_name:
                return clip
        for sub in (folder.GetSubFolderList() or []):
            found = search(sub)
            if found:
                return found
        return None

    clip = search(mp.GetRootFolder())
    if clip:
        return {"name": clip.GetName(), "unique_id": clip.GetUniqueId()}
    return {"error": f"Clip '{clip_name}' not found"}

@mcp.tool()
def transcribe_clip_audio(clip_id: str) -> Dict[str, Any]:
    """Transcribe audio for a specific clip.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.TranscribeAudio()
    return {"success": bool(result)}

@mcp.tool()
def clear_clip_transcription(clip_id: str) -> Dict[str, Any]:
    """Clear transcription for a specific clip.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.ClearTranscription()
    return {"success": bool(result)}

@mcp.tool()
def get_clip_audio_mapping(clip_id: str) -> Dict[str, Any]:
    """Get audio mapping for a clip.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    mapping = clip.GetAudioMapping()
    return {"clip_id": clip_id, "audio_mapping": mapping if mapping else ""}

@mcp.tool()
def get_clip_mark_in_out(clip_id: str) -> Dict[str, Any]:
    """Get mark in/out points for a clip.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.GetMarkInOut()
    return {"clip_id": clip_id, "mark_in_out": result if result else {}}

@mcp.tool()
def set_clip_mark_in_out(clip_id: str, mark_in: int, mark_out: int) -> Dict[str, Any]:
    """Set mark in/out points for a clip.

    Args:
        clip_id: Unique ID of the clip.
        mark_in: Mark in frame number.
        mark_out: Mark out frame number.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.SetMarkInOut(mark_in, mark_out)
    return {"success": bool(result)}

@mcp.tool()
def clear_clip_mark_in_out(clip_id: str) -> Dict[str, Any]:
    """Clear mark in/out points for a clip.

    Args:
        clip_id: Unique ID of the clip.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    result = clip.ClearMarkInOut()
    return {"success": bool(result)}


# ------------------
# Gallery Tools
# ------------------

@mcp.tool()
def get_gallery_album_name() -> Dict[str, Any]:
    """Get the name of the current gallery album."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    name = gallery.GetAlbumName()
    return {"album_name": name if name else ""}

@mcp.tool()
def set_gallery_album_name(name: str) -> Dict[str, Any]:
    """Set the name of the current gallery album.

    Args:
        name: New album name.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    result = gallery.SetAlbumName(name)
    return {"success": bool(result)}

@mcp.tool()
def get_gallery_still_albums() -> Dict[str, Any]:
    """Get list of all gallery still albums."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryStillAlbums()
    return {"albums": [str(a) for a in albums] if albums else []}

@mcp.tool()
def get_gallery_power_grade_albums() -> Dict[str, Any]:
    """Get list of all gallery power grade albums."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryPowerGradeAlbums()
    return {"albums": [str(a) for a in albums] if albums else []}

@mcp.tool()
def get_current_still_album() -> Dict[str, Any]:
    """Get the current still album."""
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    album = gallery.GetCurrentStillAlbum()
    return {"has_album": album is not None}

@mcp.tool()
def set_current_still_album(album_index: int) -> Dict[str, Any]:
    """Set the current still album by index.

    Args:
        album_index: 0-based index of the album in GetGalleryStillAlbums() list.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    result = gallery.SetCurrentStillAlbum(albums[album_index])
    return {"success": bool(result)}

@mcp.tool()
def create_gallery_still_album(album_name: str = "") -> Dict[str, Any]:
    """Create a new gallery still album.

    Args:
        album_name: Optional name for the new album.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    if album_name:
        album = gallery.CreateGalleryStillAlbum(album_name)
    else:
        album = gallery.CreateGalleryStillAlbum()
    return {"success": album is not None}

@mcp.tool()
def create_gallery_power_grade_album(album_name: str = "") -> Dict[str, Any]:
    """Create a new gallery power grade album.

    Args:
        album_name: Optional name for the new album.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    if album_name:
        album = gallery.CreateGalleryPowerGradeAlbum(album_name)
    else:
        album = gallery.CreateGalleryPowerGradeAlbum()
    return {"success": album is not None}


# ------------------
# GalleryStillAlbum Tools
# ------------------

@mcp.tool()
def get_album_stills(album_index: int = 0) -> Dict[str, Any]:
    """Get list of stills in a gallery album.

    Args:
        album_index: 0-based index of the album. Default: 0.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    return {"still_count": len(stills) if stills else 0}

@mcp.tool()
def get_still_label(album_index: int, still_index: int) -> Dict[str, Any]:
    """Get the label of a still in a gallery album.

    Args:
        album_index: 0-based album index.
        still_index: 0-based still index.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills or still_index >= len(stills):
        return {"error": f"No still at index {still_index}"}
    label = albums[album_index].GetLabel(stills[still_index])
    return {"label": label if label else ""}

@mcp.tool()
def set_still_label(album_index: int, still_index: int, label: str) -> Dict[str, Any]:
    """Set the label of a still in a gallery album.

    Args:
        album_index: 0-based album index.
        still_index: 0-based still index.
        label: New label for the still.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills or still_index >= len(stills):
        return {"error": f"No still at index {still_index}"}
    result = albums[album_index].SetLabel(stills[still_index], label)
    return {"success": bool(result)}

@mcp.tool()
def import_stills_to_album(album_index: int, file_paths: List[str]) -> Dict[str, Any]:
    """Import stills from file paths into a gallery album.

    Args:
        album_index: 0-based album index.
        file_paths: List of absolute file paths to import.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    result = albums[album_index].ImportStills(file_paths)
    return {"success": bool(result)}

@mcp.tool()
def export_stills_from_album(album_index: int, folder_path: str, file_prefix: str = "still", format: str = "dpx") -> Dict[str, Any]:
    """Export stills from a gallery album.

    Args:
        album_index: 0-based album index.
        folder_path: Directory to export to.
        file_prefix: Filename prefix. Default: 'still'.
        format: File format (dpx, cin, tif, jpg, png, ppm, bmp, xpm, drx). Default: 'dpx'.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills:
        return {"error": "No stills in album"}
    result = albums[album_index].ExportStills(stills, folder_path, file_prefix, format)
    return {"success": bool(result)}

@mcp.tool()
def delete_stills_from_album(album_index: int, still_indices: List[int]) -> Dict[str, Any]:
    """Delete stills from a gallery album.

    Args:
        album_index: 0-based album index.
        still_indices: List of 0-based still indices to delete.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills:
        return {"error": "No stills in album"}
    to_delete = [stills[i] for i in still_indices if i < len(stills)]
    result = albums[album_index].DeleteStills(to_delete)
    return {"success": bool(result)}


# ------------------
# Graph Tools
# ------------------

@mcp.tool()
def graph_get_num_nodes(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get number of nodes in the color graph for a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    return {"num_nodes": graph.GetNumNodes()}

@mcp.tool()
def graph_set_lut(node_index: int, lut_path: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Set LUT on a node in the color graph.

    Args:
        node_index: 1-based node index.
        lut_path: Absolute or relative LUT path.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    result = graph.SetLUT(node_index, lut_path)
    return {"success": bool(result)}

@mcp.tool()
def graph_get_lut(node_index: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get LUT path on a node in the color graph.

    Args:
        node_index: 1-based node index.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    lut = graph.GetLUT(node_index)
    return {"node_index": node_index, "lut_path": lut if lut else ""}

@mcp.tool()
def graph_set_node_cache_mode(node_index: int, cache_value: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Set the cache mode on a node.

    Args:
        node_index: 1-based node index.
        cache_value: -1=Auto, 0=Disabled, 1=Enabled.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    result = graph.SetNodeCacheMode(node_index, cache_value)
    return {"success": bool(result)}

@mcp.tool()
def graph_get_node_cache_mode(node_index: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get the cache mode of a node.

    Args:
        node_index: 1-based node index.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    mode = graph.GetNodeCacheMode(node_index)
    modes = {-1: "Auto", 0: "Disabled", 1: "Enabled"}
    return {"node_index": node_index, "cache_mode": mode, "mode_name": modes.get(mode, "Unknown")}

@mcp.tool()
def graph_get_node_label(node_index: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get the label of a node.

    Args:
        node_index: 1-based node index.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    label = graph.GetNodeLabel(node_index)
    return {"node_index": node_index, "label": label if label else ""}

@mcp.tool()
def graph_get_tools_in_node(node_index: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get list of tools used in a node.

    Args:
        node_index: 1-based node index.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    tools = graph.GetToolsInNode(node_index)
    return {"node_index": node_index, "tools": tools if tools else []}

@mcp.tool()
def graph_set_node_enabled(node_index: int, is_enabled: bool, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Enable or disable a node.

    Args:
        node_index: 1-based node index.
        is_enabled: True to enable, False to disable.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    result = graph.SetNodeEnabled(node_index, is_enabled)
    return {"success": bool(result)}

@mcp.tool()
def graph_apply_grade_from_drx(drx_path: str, grade_mode: int = 0, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Apply a grade from a .drx file to a timeline item's graph.

    Args:
        drx_path: Absolute path to the .drx file.
        grade_mode: 0=No keyframes, 1=Source Timecode aligned, 2=Start Frames aligned.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    result = graph.ApplyGradeFromDRX(drx_path, grade_mode)
    return {"success": bool(result)}

@mcp.tool()
def graph_apply_arri_cdl_lut(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Apply ARRI CDL and LUT to a timeline item's graph.

    Args:
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    result = graph.ApplyArriCdlLut()
    return {"success": bool(result)}

@mcp.tool()
def graph_reset_all_grades(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Reset all grades on a timeline item's graph.

    Args:
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    result = graph.ResetAllGrades()
    return {"success": bool(result)}


# ------------------
# ColorGroup Tools
# ------------------

@mcp.tool()
def get_color_group_clips(group_name: str) -> Dict[str, Any]:
    """Get clips in a color group for the current timeline.

    Args:
        group_name: Name of the color group.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    groups = project.GetColorGroupsList()
    target = None
    if groups:
        for g in groups:
            if g.GetName() == group_name:
                target = g
                break
    if not target:
        return {"error": f"Color group '{group_name}' not found"}
    clips = target.GetClipsInTimeline()
    if clips:
        return {"group": group_name, "clips": [{"name": c.GetName()} for c in clips]}
    return {"group": group_name, "clips": []}

@mcp.tool()
def get_color_group_pre_clip_node_graph(group_name: str) -> Dict[str, Any]:
    """Get the pre-clip node graph for a color group.

    Args:
        group_name: Name of the color group.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    groups = project.GetColorGroupsList()
    target = None
    if groups:
        for g in groups:
            if g.GetName() == group_name:
                target = g
                break
    if not target:
        return {"error": f"Color group '{group_name}' not found"}
    graph = target.GetPreClipNodeGraph()
    if graph:
        return {"group": group_name, "graph_type": "pre_clip", "num_nodes": graph.GetNumNodes()}
    return {"error": "No pre-clip node graph available"}

@mcp.tool()
def get_color_group_post_clip_node_graph(group_name: str) -> Dict[str, Any]:
    """Get the post-clip node graph for a color group.

    Args:
        group_name: Name of the color group.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    groups = project.GetColorGroupsList()
    target = None
    if groups:
        for g in groups:
            if g.GetName() == group_name:
                target = g
                break
    if not target:
        return {"error": f"Color group '{group_name}' not found"}
    graph = target.GetPostClipNodeGraph()
    if graph:
        return {"group": group_name, "graph_type": "post_clip", "num_nodes": graph.GetNumNodes()}
    return {"error": "No post-clip node graph available"}


# ------------------
# Timeline Tools (remaining)
# ------------------

@mcp.tool()
def timeline_set_name(name: str) -> Dict[str, Any]:
    """Rename the current timeline.

    Args:
        name: New name for the timeline.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.SetName(name)
    return {"success": bool(result), "name": name}

@mcp.tool()
def timeline_set_start_timecode(timecode: str) -> Dict[str, Any]:
    """Set the start timecode of the current timeline.

    Args:
        timecode: Timecode string (e.g. '01:00:00:00').
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.SetStartTimecode(timecode)
    return {"success": bool(result), "timecode": timecode}

@mcp.tool()
def timeline_get_current_timecode() -> Dict[str, Any]:
    """Get the current playhead timecode."""
    _, tl, err = _get_timeline()
    if err:
        return err
    return {"timecode": tl.GetCurrentTimecode()}

@mcp.tool()
def timeline_set_current_timecode(timecode: str) -> Dict[str, Any]:
    """Set the playhead to a specific timecode.

    Args:
        timecode: Timecode string (e.g. '01:00:05:00').
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.SetCurrentTimecode(timecode)
    return {"success": bool(result), "timecode": timecode}

@mcp.tool()
def timeline_add_track(track_type: str, sub_track_type: str = "") -> Dict[str, Any]:
    """Add a new track to the timeline.

    Args:
        track_type: 'video', 'audio', or 'subtitle'.
        sub_track_type: For audio: 'mono', 'stereo', '5.1', '7.1', 'adaptive'. Default: ''.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    if sub_track_type:
        result = tl.AddTrack(track_type, sub_track_type)
    else:
        result = tl.AddTrack(track_type)
    return {"success": bool(result), "track_type": track_type}

@mcp.tool()
def timeline_delete_track(track_type: str, track_index: int) -> Dict[str, Any]:
    """Delete a track from the timeline.

    Args:
        track_type: 'video', 'audio', or 'subtitle'.
        track_index: 1-based track index to delete.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.DeleteTrack(track_type, track_index)
    return {"success": bool(result)}

@mcp.tool()
def timeline_get_track_sub_type(track_type: str, track_index: int) -> Dict[str, Any]:
    """Get the sub-type of a track (e.g. mono, stereo for audio).

    Args:
        track_type: 'video' or 'audio'.
        track_index: 1-based track index.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    sub = tl.GetTrackSubType(track_type, track_index)
    return {"track_type": track_type, "track_index": track_index, "sub_type": sub if sub else ""}

@mcp.tool()
def timeline_set_track_enable(track_type: str, track_index: int, enabled: bool) -> Dict[str, Any]:
    """Enable or disable a track.

    Args:
        track_type: 'video' or 'audio'.
        track_index: 1-based track index.
        enabled: True to enable, False to disable.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.SetTrackEnable(track_type, track_index, enabled)
    return {"success": bool(result)}

@mcp.tool()
def timeline_get_is_track_enabled(track_type: str, track_index: int) -> Dict[str, Any]:
    """Check if a track is enabled.

    Args:
        track_type: 'video' or 'audio'.
        track_index: 1-based track index.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    enabled = tl.GetIsTrackEnabled(track_type, track_index)
    return {"enabled": bool(enabled)}

@mcp.tool()
def timeline_set_track_lock(track_type: str, track_index: int, locked: bool) -> Dict[str, Any]:
    """Lock or unlock a track.

    Args:
        track_type: 'video' or 'audio'.
        track_index: 1-based track index.
        locked: True to lock, False to unlock.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.SetTrackLock(track_type, track_index, locked)
    return {"success": bool(result)}

@mcp.tool()
def timeline_get_is_track_locked(track_type: str, track_index: int) -> Dict[str, Any]:
    """Check if a track is locked.

    Args:
        track_type: 'video' or 'audio'.
        track_index: 1-based track index.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    locked = tl.GetIsTrackLocked(track_type, track_index)
    return {"locked": bool(locked)}

@mcp.tool()
def timeline_delete_clips(clip_ids: List[str], track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Delete clips from the timeline.

    Args:
        clip_ids: List of clip unique IDs to delete.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    items = tl.GetItemListInTrack(track_type, track_index)
    if not items:
        return {"error": "No items in track"}
    to_delete = [i for i in items if i.GetUniqueId() in clip_ids]
    if not to_delete:
        return {"error": "No matching clips found"}
    result = tl.DeleteClips(to_delete)
    return {"success": bool(result), "deleted": len(to_delete)}

@mcp.tool()
def timeline_set_clips_linked(clip_ids: List[str], linked: bool, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Link or unlink clips in the timeline.

    Args:
        clip_ids: List of clip unique IDs.
        linked: True to link, False to unlink.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    items = tl.GetItemListInTrack(track_type, track_index)
    if not items:
        return {"error": "No items in track"}
    targets = [i for i in items if i.GetUniqueId() in clip_ids]
    if not targets:
        return {"error": "No matching clips found"}
    result = tl.SetClipsLinked(targets, linked)
    return {"success": bool(result)}

@mcp.tool()
def timeline_add_marker(frame_id: int, color: str, name: str, note: str = "", duration: int = 1, custom_data: str = "") -> Dict[str, Any]:
    """Add a marker to the current timeline.

    Args:
        frame_id: Frame number for the marker.
        color: Marker color (Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream).
        name: Marker name.
        note: Marker note. Default: empty.
        duration: Duration in frames. Default: 1.
        custom_data: Custom data string. Default: empty.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.AddMarker(frame_id, color, name, note, duration, custom_data)
    return {"success": bool(result)}

@mcp.tool()
def timeline_get_markers() -> Dict[str, Any]:
    """Get all markers on the current timeline."""
    _, tl, err = _get_timeline()
    if err:
        return err
    markers = tl.GetMarkers()
    return {"markers": markers if markers else {}}

@mcp.tool()
def timeline_get_marker_by_custom_data(custom_data: str) -> Dict[str, Any]:
    """Find a timeline marker by its custom data.

    Args:
        custom_data: Custom data string to search for.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    marker = tl.GetMarkerByCustomData(custom_data)
    return {"marker": marker if marker else {}}

@mcp.tool()
def timeline_update_marker_custom_data(frame_id: int, custom_data: str) -> Dict[str, Any]:
    """Update the custom data of a timeline marker.

    Args:
        frame_id: Frame number of the marker.
        custom_data: New custom data string.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.UpdateMarkerCustomData(frame_id, custom_data)
    return {"success": bool(result)}

@mcp.tool()
def timeline_get_marker_custom_data(frame_id: int) -> Dict[str, Any]:
    """Get the custom data of a timeline marker.

    Args:
        frame_id: Frame number of the marker.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    data = tl.GetMarkerCustomData(frame_id)
    return {"frame_id": frame_id, "custom_data": data if data else ""}

@mcp.tool()
def timeline_delete_markers_by_color(color: str) -> Dict[str, Any]:
    """Delete all timeline markers of a specific color.

    Args:
        color: Color of markers to delete. Use '' to delete all.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.DeleteMarkersByColor(color)
    return {"success": bool(result)}

@mcp.tool()
def timeline_delete_marker_at_frame(frame_id: int) -> Dict[str, Any]:
    """Delete a timeline marker at a specific frame.

    Args:
        frame_id: Frame number of the marker.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.DeleteMarkerAtFrame(frame_id)
    return {"success": bool(result)}

@mcp.tool()
def timeline_delete_marker_by_custom_data(custom_data: str) -> Dict[str, Any]:
    """Delete a timeline marker by custom data.

    Args:
        custom_data: Custom data of the marker to delete.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.DeleteMarkerByCustomData(custom_data)
    return {"success": bool(result)}

@mcp.tool()
def timeline_get_track_name(track_type: str, track_index: int) -> Dict[str, Any]:
    """Get the name of a track.

    Args:
        track_type: 'video' or 'audio'.
        track_index: 1-based track index.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    name = tl.GetTrackName(track_type, track_index)
    return {"track_name": name if name else ""}

@mcp.tool()
def timeline_set_track_name(track_type: str, track_index: int, name: str) -> Dict[str, Any]:
    """Set the name of a track.

    Args:
        track_type: 'video' or 'audio'.
        track_index: 1-based track index.
        name: New track name.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.SetTrackName(track_type, track_index, name)
    return {"success": bool(result)}

@mcp.tool()
def timeline_duplicate() -> Dict[str, Any]:
    """Duplicate the current timeline."""
    _, tl, err = _get_timeline()
    if err:
        return err
    new_tl = tl.DuplicateTimeline()
    if new_tl:
        return {"success": True, "name": new_tl.GetName(), "unique_id": new_tl.GetUniqueId()}
    return {"success": False, "error": "Failed to duplicate timeline"}

@mcp.tool()
def timeline_create_compound_clip(clip_ids: List[str], track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Create a compound clip from selected items.

    Args:
        clip_ids: List of timeline item unique IDs.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    items = tl.GetItemListInTrack(track_type, track_index)
    targets = [i for i in (items or []) if i.GetUniqueId() in clip_ids]
    if not targets:
        return {"error": "No matching items found"}
    result = tl.CreateCompoundClip(targets)
    if result:
        return {"success": True}
    return {"success": False, "error": "Failed to create compound clip"}

@mcp.tool()
def timeline_create_fusion_clip(clip_ids: List[str], track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Create a Fusion clip from selected items.

    Args:
        clip_ids: List of timeline item unique IDs.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    items = tl.GetItemListInTrack(track_type, track_index)
    targets = [i for i in (items or []) if i.GetUniqueId() in clip_ids]
    if not targets:
        return {"error": "No matching items found"}
    result = tl.CreateFusionClip(targets)
    if result:
        return {"success": True}
    return {"success": False, "error": "Failed to create Fusion clip"}

@mcp.tool()
def timeline_import_into(file_path: str, import_options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Import content into the current timeline from a file.

    Args:
        file_path: Path to the file to import (AAF, EDL, XML, etc.).
        import_options: Optional dict of import options.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    if import_options:
        result = tl.ImportIntoTimeline(file_path, import_options)
    else:
        result = tl.ImportIntoTimeline(file_path)
    return {"success": bool(result)}

@mcp.tool()
def timeline_export(file_path: str, export_type: str, export_subtype: str = "EXPORT_NONE") -> Dict[str, Any]:
    """Export the current timeline to a file.

    Args:
        file_path: Output file path.
        export_type: Export type (e.g. 'EXPORT_AAF', 'EXPORT_EDL', 'EXPORT_FCP_7_XML', 'EXPORT_FCPXML_1_10', 'EXPORT_DRT', 'EXPORT_TEXT_CSV', 'EXPORT_TEXT_TAB', 'EXPORT_OTIO', 'EXPORT_ALE').
        export_subtype: Export subtype for AAF/EDL. Default: 'EXPORT_NONE'.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    # Map string constants to resolve constants
    try:
        etype = getattr(resolve, export_type) if hasattr(resolve, export_type) else export_type
        esub = getattr(resolve, export_subtype) if hasattr(resolve, export_subtype) else export_subtype
    except Exception:
        etype = export_type
        esub = export_subtype
    result = tl.Export(file_path, etype, esub)
    return {"success": bool(result), "file_path": file_path}

@mcp.tool()
def timeline_insert_generator(generator_name: str, duration: Optional[int] = None) -> Dict[str, Any]:
    """Insert a generator into the timeline.

    Args:
        generator_name: Name of the generator to insert.
        duration: Optional duration in frames.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    if duration:
        result = tl.InsertGeneratorIntoTimeline(generator_name, {"duration": duration})
    else:
        result = tl.InsertGeneratorIntoTimeline(generator_name)
    return {"success": result is not None}

@mcp.tool()
def timeline_insert_fusion_generator(generator_name: str) -> Dict[str, Any]:
    """Insert a Fusion generator into the timeline.

    Args:
        generator_name: Name of the Fusion generator.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.InsertFusionGeneratorIntoTimeline(generator_name)
    return {"success": result is not None}

@mcp.tool()
def timeline_insert_fusion_composition() -> Dict[str, Any]:
    """Insert a Fusion composition into the timeline."""
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.InsertFusionCompositionIntoTimeline()
    return {"success": result is not None}

@mcp.tool()
def timeline_insert_ofx_generator(generator_name: str) -> Dict[str, Any]:
    """Insert an OFX generator into the timeline.

    Args:
        generator_name: Name of the OFX generator.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.InsertOFXGeneratorIntoTimeline(generator_name)
    return {"success": result is not None}

@mcp.tool()
def timeline_insert_title(title_name: str) -> Dict[str, Any]:
    """Insert a title into the timeline.

    Args:
        title_name: Name of the title to insert.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.InsertTitleIntoTimeline(title_name)
    return {"success": result is not None}

@mcp.tool()
def timeline_insert_fusion_title(title_name: str) -> Dict[str, Any]:
    """Insert a Fusion title into the timeline.

    Args:
        title_name: Name of the Fusion title.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.InsertFusionTitleIntoTimeline(title_name)
    return {"success": result is not None}

@mcp.tool()
def timeline_grab_still() -> Dict[str, Any]:
    """Grab a still from the current frame of the timeline."""
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.GrabStill()
    return {"success": result is not None}

@mcp.tool()
def timeline_grab_all_stills() -> Dict[str, Any]:
    """Grab stills from all frames at the current position across all timelines."""
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.GrabAllStills()
    return {"success": result is not None}

@mcp.tool()
def timeline_get_unique_id() -> Dict[str, Any]:
    """Get the unique ID of the current timeline."""
    _, tl, err = _get_timeline()
    if err:
        return err
    return {"unique_id": tl.GetUniqueId()}

@mcp.tool()
def timeline_create_subtitles_from_audio(language: str = "auto", preset: str = "default") -> Dict[str, Any]:
    """Create subtitles from audio in the current timeline.

    Args:
        language: Language for captioning ('auto', 'english', 'french', etc.). Default: 'auto'.
        preset: Caption preset ('default', 'teletext', 'netflix'). Default: 'default'.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    settings = {}
    result = tl.CreateSubtitlesFromAudio(settings)
    return {"success": bool(result)}

@mcp.tool()
def timeline_detect_scene_cuts() -> Dict[str, Any]:
    """Detect scene cuts in the current timeline."""
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.DetectSceneCuts()
    return {"success": bool(result)}

@mcp.tool()
def timeline_convert_to_stereo() -> Dict[str, Any]:
    """Convert the current timeline to stereo."""
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.ConvertTimelineToStereo()
    return {"success": bool(result)}

@mcp.tool()
def timeline_get_node_graph() -> Dict[str, Any]:
    """Get the node graph for the current timeline."""
    _, tl, err = _get_timeline()
    if err:
        return err
    graph = tl.GetNodeGraph()
    if graph:
        return {"has_graph": True, "num_nodes": graph.GetNumNodes()}
    return {"has_graph": False}

@mcp.tool()
def timeline_analyze_dolby_vision() -> Dict[str, Any]:
    """Analyze Dolby Vision for the current timeline."""
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.AnalyzeDolbyVision()
    return {"success": bool(result)}

@mcp.tool()
def timeline_get_current_video_item() -> Dict[str, Any]:
    """Get the current video item at the playhead."""
    _, tl, err = _get_timeline()
    if err:
        return err
    item = tl.GetCurrentVideoItem()
    if item:
        return {"name": item.GetName(), "unique_id": item.GetUniqueId(), "start": item.GetStart(), "end": item.GetEnd()}
    return {"item": None}

@mcp.tool()
def timeline_get_current_clip_thumbnail(width: int = 320, height: int = 180) -> Dict[str, Any]:
    """Get thumbnail image data for the current clip.

    Args:
        width: Thumbnail width. Default: 320.
        height: Thumbnail height. Default: 180.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.GetCurrentClipThumbnailImage({"width": width, "height": height})
    if result:
        return {"success": True, "has_data": bool(result)}
    return {"success": False}

@mcp.tool()
def timeline_get_media_pool_item() -> Dict[str, Any]:
    """Get the MediaPoolItem for the current timeline."""
    _, tl, err = _get_timeline()
    if err:
        return err
    mpi = tl.GetMediaPoolItem()
    if mpi:
        return {"name": mpi.GetName(), "unique_id": mpi.GetUniqueId()}
    return {"media_pool_item": None}

@mcp.tool()
def timeline_get_mark_in_out() -> Dict[str, Any]:
    """Get mark in/out points for the current timeline."""
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.GetMarkInOut()
    return result if result else {}

@mcp.tool()
def timeline_set_mark_in_out(mark_in: int, mark_out: int) -> Dict[str, Any]:
    """Set mark in/out points for the current timeline.

    Args:
        mark_in: Mark in frame number.
        mark_out: Mark out frame number.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.SetMarkInOut(mark_in, mark_out)
    return {"success": bool(result)}

@mcp.tool()
def timeline_clear_mark_in_out() -> Dict[str, Any]:
    """Clear mark in/out points for the current timeline."""
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.ClearMarkInOut()
    return {"success": bool(result)}


# ------------------
# TimelineItem Tools (remaining)
# ------------------

@mcp.tool()
def ti_get_info(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get comprehensive info about a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {
        "name": item.GetName(), "duration": item.GetDuration(),
        "start": item.GetStart(), "end": item.GetEnd(),
        "left_offset": item.GetLeftOffset(), "right_offset": item.GetRightOffset(),
        "source_start_frame": item.GetSourceStartFrame(), "source_end_frame": item.GetSourceEndFrame(),
        "unique_id": item.GetUniqueId(), "clip_enabled": item.GetClipEnabled()
    }

@mcp.tool()
def ti_get_source_start_time(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get source start time of a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"source_start_time": item.GetSourceStartTime(), "source_end_time": item.GetSourceEndTime()}

@mcp.tool()
def ti_set_property(property_name: str, property_value: Any, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Set a property on a timeline item.

    Args:
        property_name: Property name (Pan, Tilt, ZoomX, ZoomY, RotationAngle, Opacity, CropLeft, CropRight, CropTop, CropBottom, etc.).
        property_value: Value to set.
        item_index: 0-based item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    result = item.SetProperty(property_name, property_value)
    return {"success": bool(result)}

@mcp.tool()
def ti_get_property(property_name: str = "", item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get property of a timeline item.

    Args:
        property_name: Property name, or empty for all. Default: ''.
        item_index: 0-based item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    if property_name:
        result = item.GetProperty(property_name)
    else:
        result = item.GetProperty()
    return {"property": result}

@mcp.tool()
def ti_add_marker(frame_id: int, color: str, name: str, note: str = "", duration: int = 1, custom_data: str = "", item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Add a marker to a timeline item.

    Args:
        frame_id: Frame offset within the item.
        color: Marker color.
        name: Marker name.
        note: Marker note. Default: ''.
        duration: Duration in frames. Default: 1.
        custom_data: Custom data. Default: ''.
        item_index: 0-based item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    result = item.AddMarker(frame_id, color, name, note, duration, custom_data)
    return {"success": bool(result)}

@mcp.tool()
def ti_get_markers(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get all markers on a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"markers": item.GetMarkers() or {}}

@mcp.tool()
def ti_delete_markers_by_color(color: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Delete markers by color on a timeline item.

    Args:
        color: Color to delete. '' for all.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.DeleteMarkersByColor(color))}

@mcp.tool()
def ti_delete_marker_at_frame(frame_id: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Delete a marker at a frame on a timeline item.

    Args:
        frame_id: Frame number.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.DeleteMarkerAtFrame(frame_id))}

@mcp.tool()
def ti_delete_marker_by_custom_data(custom_data: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Delete a marker by custom data on a timeline item.

    Args:
        custom_data: Custom data of the marker.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.DeleteMarkerByCustomData(custom_data))}

@mcp.tool()
def ti_get_marker_by_custom_data(custom_data: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Find marker by custom data.

    Args:
        custom_data: Custom data to search for.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"marker": item.GetMarkerByCustomData(custom_data) or {}}

@mcp.tool()
def ti_update_marker_custom_data(frame_id: int, custom_data: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Update marker custom data.

    Args:
        frame_id: Frame number.
        custom_data: New custom data.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.UpdateMarkerCustomData(frame_id, custom_data))}

@mcp.tool()
def ti_get_marker_custom_data(frame_id: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get marker custom data.

    Args:
        frame_id: Frame number.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"custom_data": item.GetMarkerCustomData(frame_id) or ""}

@mcp.tool()
def ti_add_flag(color: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Add a flag to a timeline item.

    Args:
        color: Flag color.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.AddFlag(color))}

@mcp.tool()
def ti_get_flag_list(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get flags on a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"flags": item.GetFlagList() or []}

@mcp.tool()
def ti_clear_flags(color: str = "", item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Clear flags from a timeline item.

    Args:
        color: Color to clear, or '' for all.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.ClearFlags(color))}

@mcp.tool()
def ti_get_clip_color(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get clip color of a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"clip_color": item.GetClipColor() or ""}

@mcp.tool()
def ti_set_clip_color(color: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Set clip color of a timeline item.

    Args:
        color: Color name.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.SetClipColor(color))}

@mcp.tool()
def ti_clear_clip_color(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Clear clip color from a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.ClearClipColor())}

@mcp.tool()
def ti_add_fusion_comp(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Add a new Fusion composition to a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.AddFusionComp())}

@mcp.tool()
def ti_import_fusion_comp(file_path: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Import a Fusion composition from file.

    Args:
        file_path: Path to the .comp file.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.ImportFusionComp(file_path))}

@mcp.tool()
def ti_export_fusion_comp(file_path: str, comp_index: int = 1, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Export a Fusion composition to file.

    Args:
        file_path: Output path for the .comp file.
        comp_index: 1-based Fusion comp index. Default: 1.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    comp = item.GetFusionCompByIndex(comp_index)
    if not comp:
        return {"error": f"No Fusion comp at index {comp_index}"}
    return {"success": bool(item.ExportFusionComp(file_path, comp_index))}

@mcp.tool()
def ti_delete_fusion_comp(comp_name: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Delete a Fusion composition by name.

    Args:
        comp_name: Name of the Fusion composition.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.DeleteFusionCompByName(comp_name))}

@mcp.tool()
def ti_load_fusion_comp(comp_name: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Load a Fusion composition by name.

    Args:
        comp_name: Name of the Fusion composition.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.LoadFusionCompByName(comp_name))}

@mcp.tool()
def ti_rename_fusion_comp(old_name: str, new_name: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Rename a Fusion composition.

    Args:
        old_name: Current name.
        new_name: New name.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.RenameFusionCompByName(old_name, new_name))}

@mcp.tool()
def ti_get_fusion_comp_info(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get Fusion composition info for a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {
        "comp_count": item.GetFusionCompCount(),
        "comp_names": item.GetFusionCompNameList() or {}
    }

@mcp.tool()
def ti_add_version(version_name: str, version_type: int = 0, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Add a new color version to a timeline item.

    Args:
        version_name: Name for the new version.
        version_type: 0=Local, 1=Remote. Default: 0.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.AddVersion(version_name, version_type))}

@mcp.tool()
def ti_get_current_version(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get the current color version of a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"version": item.GetCurrentVersion() or {}}

@mcp.tool()
def ti_delete_version(version_name: str, version_type: int = 0, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Delete a color version.

    Args:
        version_name: Name of the version.
        version_type: 0=Local, 1=Remote. Default: 0.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.DeleteVersionByName(version_name, version_type))}

@mcp.tool()
def ti_load_version(version_name: str, version_type: int = 0, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Load a color version.

    Args:
        version_name: Name of the version.
        version_type: 0=Local, 1=Remote. Default: 0.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.LoadVersionByName(version_name, version_type))}

@mcp.tool()
def ti_rename_version(old_name: str, new_name: str, version_type: int = 0, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Rename a color version.

    Args:
        old_name: Current version name.
        new_name: New version name.
        version_type: 0=Local, 1=Remote. Default: 0.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.RenameVersionByName(old_name, new_name, version_type))}

@mcp.tool()
def ti_get_version_name_list(version_type: int = 0, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get list of version names.

    Args:
        version_type: 0=Local, 1=Remote. Default: 0.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"versions": item.GetVersionNameList(version_type) or []}

@mcp.tool()
def ti_set_cdl(cdl: Dict[str, Any], item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Set CDL (Color Decision List) values on a timeline item.

    Args:
        cdl: Dict with CDL values: {'NodeIndex': str, 'Slope': str, 'Offset': str, 'Power': str, 'Saturation': str}.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.SetCDL(cdl))}

@mcp.tool()
def ti_add_take(media_pool_item_id: str, start_frame: int = 0, end_frame: int = 0, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Add a take to a timeline item.

    Args:
        media_pool_item_id: Unique ID of the MediaPoolItem to use as take.
        start_frame: Start frame. Default: 0.
        end_frame: End frame. Default: 0.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    _, mp, mp_err = _get_mp()
    if mp_err:
        return mp_err
    mpi = _find_clip_by_id(mp.GetRootFolder(), media_pool_item_id)
    if not mpi:
        return {"error": f"MediaPoolItem {media_pool_item_id} not found"}
    return {"success": bool(item.AddTake(mpi, start_frame, end_frame))}

@mcp.tool()
def ti_get_takes_info(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get takes info for a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    count = item.GetTakesCount()
    selected = item.GetSelectedTakeIndex()
    takes = []
    for i in range(count):
        take = item.GetTakeByIndex(i + 1)
        takes.append(take if take else {})
    return {"takes_count": count, "selected_take_index": selected, "takes": takes}

@mcp.tool()
def ti_select_take(take_index: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Select a take by index.

    Args:
        take_index: 1-based take index.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.SelectTakeByIndex(take_index))}

@mcp.tool()
def ti_delete_take(take_index: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Delete a take by index.

    Args:
        take_index: 1-based take index.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.DeleteTakeByIndex(take_index))}

@mcp.tool()
def ti_finalize_take(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Finalize the selected take.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.FinalizeTake())}

@mcp.tool()
def ti_copy_grades(target_item_indices: List[int], track_type: str = "video", track_index: int = 1, source_item_index: int = 0) -> Dict[str, Any]:
    """Copy grades from one timeline item to others.

    Args:
        target_item_indices: List of 0-based indices of target items.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
        source_item_index: 0-based source item index. Default: 0.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    items = tl.GetItemListInTrack(track_type, track_index)
    if not items:
        return {"error": "No items in track"}
    source = items[source_item_index] if source_item_index < len(items) else None
    if not source:
        return {"error": "Source item not found"}
    targets = [items[i] for i in target_item_indices if i < len(items)]
    if not targets:
        return {"error": "No target items found"}
    result = source.CopyGrades(targets)
    return {"success": bool(result)}

@mcp.tool()
def ti_set_clip_enabled(enabled: bool, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Enable or disable a timeline item.

    Args:
        enabled: True to enable, False to disable.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.SetClipEnabled(enabled))}

@mcp.tool()
def ti_update_sidecar(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Update sidecar file for a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.UpdateSidecar())}

@mcp.tool()
def ti_load_burn_in_preset(preset_name: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Load a burn-in preset for a timeline item.

    Args:
        preset_name: Burn-in preset name.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.LoadBurnInPreset(preset_name))}

@mcp.tool()
def ti_create_magic_mask(mode: str = "Forward", item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Create a Magic Mask on a timeline item.

    Args:
        mode: 'Forward' or 'Backward'. Default: 'Forward'.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.CreateMagicMask(mode))}

@mcp.tool()
def ti_regenerate_magic_mask(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Regenerate Magic Mask on a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.RegenerateMagicMask())}

@mcp.tool()
def ti_stabilize(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Stabilize a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.Stabilize())}

@mcp.tool()
def ti_smart_reframe(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Apply Smart Reframe to a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.SmartReframe())}

@mcp.tool()
def ti_get_node_graph(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get the color node graph for a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if graph:
        return {"has_graph": True, "num_nodes": graph.GetNumNodes()}
    return {"has_graph": False}

@mcp.tool()
def ti_get_color_group(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get the color group for a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    group = item.GetColorGroup()
    if group:
        return {"group_name": group.GetName()}
    return {"group_name": None}

@mcp.tool()
def ti_assign_to_color_group(group_name: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Assign a timeline item to a color group.

    Args:
        group_name: Name of the color group.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    project = resolve.GetProjectManager().GetCurrentProject()
    groups = project.GetColorGroupsList()
    target = None
    if groups:
        for g in groups:
            if g.GetName() == group_name:
                target = g
                break
    if not target:
        return {"error": f"Color group '{group_name}' not found"}
    return {"success": bool(item.AssignToColorGroup(target))}

@mcp.tool()
def ti_remove_from_color_group(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Remove a timeline item from its color group.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.RemoveFromColorGroup())}

@mcp.tool()
def ti_export_lut(export_type: str, path: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Export LUT from a timeline item.

    Args:
        export_type: LUT type ('EXPORT_LUT_17PTCUBE', 'EXPORT_LUT_33PTCUBE', 'EXPORT_LUT_65PTCUBE', 'EXPORT_LUT_PANASONICVLUT').
        path: Output file path.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    try:
        etype = getattr(resolve, export_type) if hasattr(resolve, export_type) else export_type
    except Exception:
        etype = export_type
    return {"success": bool(item.ExportLUT(etype, path))}

@mcp.tool()
def ti_get_linked_items(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get items linked to a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    linked = item.GetLinkedItems()
    if linked:
        return {"linked_items": [{"name": li.GetName(), "unique_id": li.GetUniqueId()} for li in linked]}
    return {"linked_items": []}

@mcp.tool()
def ti_get_track_type_and_index(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get the track type and index for a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    result = item.GetTrackTypeAndIndex()
    return {"track_type": result[0] if result else "", "track_index": result[1] if result and len(result) > 1 else 0}

@mcp.tool()
def ti_get_source_audio_channel_mapping(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get source audio channel mapping for a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    mapping = item.GetSourceAudioChannelMapping()
    return {"audio_channel_mapping": mapping if mapping else ""}

@mcp.tool()
def ti_get_stereo_convergence_values(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get stereo convergence values for a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"convergence": item.GetStereoConvergenceValues() or {}}

@mcp.tool()
def ti_get_stereo_floating_window_params(eye: str = "left", item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get stereo floating window parameters.

    Args:
        eye: 'left' or 'right'. Default: 'left'.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    if eye == "left":
        return {"params": item.GetStereoLeftFloatingWindowParams() or {}}
    else:
        return {"params": item.GetStereoRightFloatingWindowParams() or {}}

@mcp.tool()
def ti_get_media_pool_item(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get the MediaPoolItem associated with a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    mpi = item.GetMediaPoolItem()
    if mpi:
        return {"name": mpi.GetName(), "unique_id": mpi.GetUniqueId()}
    return {"media_pool_item": None}

@mcp.tool()
def ti_get_cache_status(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get cache status for a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {
        "color_output_cache_enabled": bool(item.GetIsColorOutputCacheEnabled()),
        "fusion_output_cache_enabled": bool(item.GetIsFusionOutputCacheEnabled())
    }

@mcp.tool()
def ti_set_color_output_cache(enabled: bool, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Enable/disable color output cache for a timeline item.

    Args:
        enabled: True to enable, False to disable.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.SetColorOutputCache(enabled))}

@mcp.tool()
def ti_set_fusion_output_cache(enabled: bool, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Enable/disable Fusion output cache for a timeline item.

    Args:
        enabled: True to enable, False to disable.
        item_index: 0-based item index. Default: 0.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    return {"success": bool(item.SetFusionOutputCache(enabled))}


# ------------------
# Final API Gap Coverage (Experiment 4)
# ------------------

@mcp.tool()
def add_render_job() -> Dict[str, Any]:
    """Add a render job based on current render settings to the render queue.

    Returns the unique job ID string for the new render job.
    Configure render settings first with set_render_settings, set_render_format_and_codec, etc.
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    job_id = project.AddRenderJob()
    if job_id:
        return {"success": True, "job_id": job_id}
    return {"success": False, "error": "Failed to add render job. Check render settings are configured."}


@mcp.tool()
def load_cloud_project(project_name: str, project_media_path: str, sync_mode: str = "proxy") -> Dict[str, Any]:
    """Load a cloud project from DaVinci Resolve cloud.

    Args:
        project_name: Name of the cloud project to load.
        project_media_path: Local path for project media cache.
        sync_mode: Sync mode - 'proxy' or 'full' (default: 'proxy').
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    if not pm:
        return {"error": "Failed to get ProjectManager"}
    cloud_settings = {
        resolve.CLOUD_SETTING_PROJECT_NAME: project_name,
        resolve.CLOUD_SETTING_PROJECT_MEDIA_PATH: project_media_path,
        resolve.CLOUD_SETTING_SYNC_MODE: sync_mode,
    }
    project = pm.LoadCloudProject(cloud_settings)
    if project:
        return {"success": True, "project_name": project.GetName()}
    return {"success": False, "error": "Failed to load cloud project. Check cloud settings and connectivity."}


@mcp.tool()
def create_timeline_from_clips(name: str, clip_ids: List[str] = None) -> Dict[str, Any]:
    """Create a new timeline from specified media pool clips.

    Args:
        name: Name for the new timeline.
        clip_ids: List of MediaPoolItem unique IDs to include. If None, uses selected clips.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    if clip_ids:
        root = mp.GetRootFolder()
        clips = []
        for cid in clip_ids:
            clip = _find_clip_by_id(root, cid)
            if clip:
                clips.append(clip)
            else:
                return {"error": f"Clip not found: {cid}"}
        tl = mp.CreateTimelineFromClips(name, clips)
    else:
        selected = mp.GetSelectedClips()
        if not selected:
            return {"error": "No clips specified and no clips selected in media pool"}
        tl = mp.CreateTimelineFromClips(name, selected)
    if tl:
        return {"success": True, "timeline_name": tl.GetName(), "timeline_id": tl.GetUniqueId()}
    return {"success": False, "error": "Failed to create timeline from clips"}


@mcp.tool()
def set_timeline_setting(setting_name: str, setting_value: str) -> Dict[str, Any]:
    """Set a timeline setting value.

    Args:
        setting_name: Name of the timeline setting to set (e.g. 'useCustomSettings', 'timelineFrameRate',
                      'timelineResolutionWidth', 'timelineResolutionHeight', 'timelineOutputResolutionWidth',
                      'timelineOutputResolutionHeight', 'colorSpaceTimeline', 'colorSpaceOutput').
        setting_value: Value to set for the setting (string).
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    result = tl.SetSetting(setting_name, setting_value)
    return {"success": bool(result), "setting_name": setting_name, "setting_value": setting_value}


@mcp.tool()
def get_fusion_comp_by_name(comp_name: str, track_type: str = "video", track_index: int = 1, item_index: int = 0) -> Dict[str, Any]:
    """Get a Fusion composition from a timeline item by name.

    Args:
        comp_name: Name of the Fusion composition to retrieve.
        track_type: Track type ('video', 'audio', 'subtitle').
        track_index: Track index (1-based).
        item_index: Item index on the track (0-based).
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    comp = item.GetFusionCompByName(comp_name)
    if comp:
        return {"success": True, "comp_name": comp_name, "comp_available": True}
    return {"success": False, "error": f"Fusion composition '{comp_name}' not found on this timeline item"}


# Start the server
if __name__ == "__main__":
    try:
        if resolve is None:
            logger.error("Cannot start server without connection to DaVinci Resolve")
            sys.exit(1)
        
        logger.info("Starting DaVinci Resolve MCP Server")
        # Start the MCP server with the simple run method
        # Note: The MCP CLI tool handles port configuration, not FastMCP directly
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        sys.exit(1) 