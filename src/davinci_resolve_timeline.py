"""
DaVinci Resolve Timeline Operations MCP Functions

This module provides functions to manipulate DaVinci Resolve timelines.
"""

import sys
import os
import json
from typing import Dict, Any, Optional, Union, List

# Try to import the DaVinci Resolve scripting module
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    resolve_api_path = os.environ.get(
        "RESOLVE_SCRIPT_API",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
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


def mcp_create_timeline(
    timeline_name: str,
    resolution: Optional[Dict[str, str]] = None,
    frame_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Create a new empty timeline.

    Args:
        timeline_name: The name for the new timeline
        resolution: Dictionary with 'width' and 'height' keys (optional)
        frame_rate: The frame rate for the timeline (optional)

    Returns:
        A dictionary with the status of the operation
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

        # If resolution or frame rate are provided, set project settings first
        if resolution or frame_rate:
            if resolution:
                width = resolution.get("width")
                height = resolution.get("height")
                if width and height:
                    current_project.SetSetting("timelineResolutionWidth", str(width))
                    current_project.SetSetting("timelineResolutionHeight", str(height))

            if frame_rate:
                current_project.SetSetting("timelineFrameRate", str(frame_rate))

        # Create the timeline
        # Make sure to pass the timeline name as a string
        timeline = media_pool.CreateEmptyTimeline(str(timeline_name))

        # Check if timeline was created successfully
        if timeline:
            # Get all timelines and verify our new one exists
            timeline_count = current_project.GetTimelineCount()
            found = False

            for i in range(1, timeline_count + 1):
                check_timeline = current_project.GetTimelineByIndex(i)
                if check_timeline and check_timeline.GetName() == timeline_name:
                    found = True
                    timeline = check_timeline
                    break

            if found:
                # Set as current timeline
                current_project.SetCurrentTimeline(timeline)

                # Get basic timeline info
                timeline_info = {"name": timeline.GetName()}

                # Try to get additional info
                try:
                    timeline_info["start_frame"] = timeline.GetStartFrame()
                    timeline_info["end_frame"] = timeline.GetEndFrame()
                    timeline_info["video_tracks"] = timeline.GetTrackCount("video")
                    timeline_info["audio_tracks"] = timeline.GetTrackCount("audio")
                except Exception as e:
                    print(f"Warning: Could not get all timeline info: {e}")

                return {
                    "status": "success",
                    "message": f"Timeline '{timeline_name}' created successfully",
                    "timeline_info": timeline_info,
                }
            else:
                return {
                    "error": f"Timeline was created but could not be found by name: '{timeline_name}'"
                }
        else:
            return {"error": f"Failed to create timeline '{timeline_name}'"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_delete_timeline(timeline_name: str) -> Dict[str, Any]:
    """
    Delete a timeline from the current project.

    Args:
        timeline_name: The name of the timeline to delete

    Returns:
        A dictionary with the status of the operation
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

        # Find the timeline by name
        timeline_count = current_project.GetTimelineCount()
        if timeline_count == 0:
            return {"error": "No timelines in the current project"}

        timeline_found = False
        timeline_object = None
        timeline_index = -1

        for i in range(1, timeline_count + 1):
            timeline = current_project.GetTimelineByIndex(i)
            if timeline and timeline.GetName() == timeline_name:
                timeline_found = True
                timeline_object = timeline
                timeline_index = i
                break

        if not timeline_found:
            return {"error": f"Timeline '{timeline_name}' not found"}

        # Check if it's the current timeline
        current_timeline = current_project.GetCurrentTimeline()
        current_timeline_is_target = (
            current_timeline and current_timeline.GetName() == timeline_name
        )

        # If we're deleting the current timeline and there are others, switch to another timeline first
        if current_timeline_is_target and timeline_count > 1:
            for j in range(1, timeline_count + 1):
                if j != timeline_index:
                    other_timeline = current_project.GetTimelineByIndex(j)
                    if other_timeline:
                        current_project.SetCurrentTimeline(other_timeline)
                        print(f"Switched to timeline: {other_timeline.GetName()}")
                        break

        # Delete the timeline
        try:
            success = current_project.DeleteTimeline(timeline_object)

            if success:
                return {
                    "status": "success",
                    "message": f"Timeline '{timeline_name}' deleted successfully",
                }
            else:
                # Try an alternative approach if the standard way failed
                media_pool = current_project.GetMediaPool()
                if media_pool:
                    # Some versions of Resolve require using the media pool to delete timelines
                    success = media_pool.DeleteTimelines([timeline_object])
                    if success:
                        return {
                            "status": "success",
                            "message": f"Timeline '{timeline_name}' deleted successfully via media pool",
                        }

                return {"error": f"Failed to delete timeline '{timeline_name}'"}
        except Exception as e:
            return {"error": f"Error while deleting timeline: {str(e)}"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_duplicate_timeline(timeline_name: str, new_name: str) -> Dict[str, Any]:
    """
    Duplicate an existing timeline.

    Args:
        timeline_name: The name of the timeline to duplicate
        new_name: The name for the new timeline

    Returns:
        A dictionary with the status of the operation
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

        # Find the timeline by name
        timeline_count = current_project.GetTimelineCount()
        if timeline_count == 0:
            return {"error": "No timelines in the current project"}

        timeline_found = False
        source_timeline = None

        for i in range(1, timeline_count + 1):
            timeline = current_project.GetTimelineByIndex(i)
            if timeline and timeline.GetName() == timeline_name:
                timeline_found = True
                source_timeline = timeline
                break

        if not timeline_found or not source_timeline:
            return {"error": f"Timeline '{timeline_name}' not found"}

        # Duplicate the timeline
        try:
            # Ensure new_name is a string
            new_name = str(new_name)

            # Try using the project API first
            new_timeline = current_project.DuplicateTimeline(source_timeline, new_name)

            if not new_timeline:
                # Try an alternative approach if the standard way failed
                media_pool = current_project.GetMediaPool()
                if media_pool:
                    # Some versions of Resolve require using the media pool to duplicate timelines
                    new_timeline = media_pool.DuplicateTimeline(
                        source_timeline, new_name
                    )

            # Verify if the timeline was created
            if new_timeline:
                # Get basic timeline info
                timeline_info = {"name": new_timeline.GetName()}

                # Try to get additional info
                try:
                    timeline_info["start_frame"] = new_timeline.GetStartFrame()
                    timeline_info["end_frame"] = new_timeline.GetEndFrame()
                    timeline_info["video_tracks"] = new_timeline.GetTrackCount("video")
                    timeline_info["audio_tracks"] = new_timeline.GetTrackCount("audio")
                except Exception as e:
                    print(f"Warning: Could not get all timeline info: {e}")

                return {
                    "status": "success",
                    "message": f"Timeline '{timeline_name}' duplicated as '{new_name}'",
                    "timeline_info": timeline_info,
                }
            else:
                # Manual duplication as last resort
                try:
                    # Create an empty timeline with the new name
                    media_pool = current_project.GetMediaPool()
                    new_timeline = media_pool.CreateEmptyTimeline(new_name)

                    if new_timeline:
                        # Note: This doesn't actually copy the content, just creates an empty timeline
                        return {
                            "status": "partial_success",
                            "message": f"Created empty timeline '{new_name}', but could not copy content from '{timeline_name}'",
                            "timeline_info": {"name": new_timeline.GetName()},
                        }
                    else:
                        return {
                            "error": f"Failed to duplicate timeline '{timeline_name}'"
                        }
                except Exception as e:
                    return {"error": f"Manual duplication failed: {str(e)}"}
        except Exception as e:
            return {"error": f"Error while duplicating timeline: {str(e)}"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_set_current_timeline(timeline_name: str) -> Dict[str, Any]:
    """
    Set the specified timeline as the current timeline.

    Args:
        timeline_name: The name of the timeline to set as current

    Returns:
        A dictionary with the status of the operation
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

        # Find the timeline by name
        timeline_count = current_project.GetTimelineCount()
        timeline_found = False

        for i in range(1, timeline_count + 1):
            timeline = current_project.GetTimelineByIndex(i)
            if timeline.GetName() == timeline_name:
                timeline_found = True

                # Set as current timeline
                success = current_project.SetCurrentTimeline(timeline)

                if success:
                    return {
                        "status": "success",
                        "message": f"Timeline '{timeline_name}' set as current timeline",
                    }
                else:
                    return {
                        "error": f"Failed to set timeline '{timeline_name}' as current"
                    }

        if not timeline_found:
            return {"error": f"Timeline '{timeline_name}' not found"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_add_timeline_marker(
    frame_position: int,
    color: str = "Blue",
    name: str = "",
    note: str = "",
    duration: int = 1,
) -> Dict[str, Any]:
    """
    Add a marker to the current timeline.

    Args:
        frame_position: The frame position to add the marker
        color: The marker color (Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream)
        name: The marker name
        note: The marker note
        duration: The marker duration in frames

    Returns:
        A dictionary with the status of the operation
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

        current_timeline = current_project.GetCurrentTimeline()
        if not current_timeline:
            return {"error": "No timeline is currently active"}

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
            color = "Blue"  # Default to blue if invalid color

        # Add the marker
        marker_id = current_timeline.AddMarker(
            frame_position, color, name, note, duration
        )

        if marker_id:
            return {
                "status": "success",
                "message": f"Marker added at frame {frame_position}",
                "marker_id": marker_id,
            }
        else:
            return {"error": f"Failed to add marker at frame {frame_position}"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_delete_timeline_marker(marker_id: str) -> Dict[str, Any]:
    """
    Delete a marker from the current timeline.

    Args:
        marker_id: The ID of the marker to delete

    Returns:
        A dictionary with the status of the operation
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

        current_timeline = current_project.GetCurrentTimeline()
        if not current_timeline:
            return {"error": "No timeline is currently active"}

        # Delete the marker
        success = current_timeline.DeleteMarkerByCustomID(marker_id)

        if success:
            return {
                "status": "success",
                "message": f"Marker with ID {marker_id} deleted successfully",
            }
        else:
            return {"error": f"Failed to delete marker with ID {marker_id}"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_export_timeline(
    timeline_name: Optional[str] = None,
    file_path: str = "",
    export_type: str = "fcpxml",
) -> Dict[str, Any]:
    """
    Export a timeline to a file.

    Args:
        timeline_name: The name of the timeline to export (or None for current timeline)
        file_path: The path where the file should be saved
        export_type: The export format (fcpxml, aaf, edl, etc.)

    Returns:
        A dictionary with the status of the operation
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

        # Get the timeline to export
        target_timeline = None

        if timeline_name:
            # Find the timeline by name
            timeline_count = current_project.GetTimelineCount()
            timeline_found = False

            for i in range(1, timeline_count + 1):
                timeline = current_project.GetTimelineByIndex(i)
                if timeline and timeline.GetName() == timeline_name:
                    target_timeline = timeline
                    timeline_found = True
                    break

            if not timeline_found:
                return {"error": f"Timeline '{timeline_name}' not found"}
        else:
            # Use current timeline
            target_timeline = current_project.GetCurrentTimeline()
            if not target_timeline:
                return {"error": "No timeline is currently active"}
            timeline_name = target_timeline.GetName()

        # Validate export_type
        valid_export_types = ["fcpxml", "aaf", "edl", "txt", "html"]
        export_type = export_type.lower()

        if export_type not in valid_export_types:
            return {
                "error": f"Invalid export type. Choose from: {', '.join(valid_export_types)}"
            }

        # Create directory if it doesn't exist
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except Exception as e:
                return {"error": f"Failed to create directory: {str(e)}"}

        # If file_path is empty, create a default one
        if not file_path:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            filename = f"{timeline_name}_{export_type}.{export_type}"
            file_path = os.path.join(desktop, filename)

        # Ensure the file has the correct extension
        if not file_path.lower().endswith(f".{export_type}"):
            file_path = f"{file_path}.{export_type}"

        # Export the timeline
        try:
            if export_type == "fcpxml":
                success = target_timeline.Export(file_path, resolve.EXPORT_FCPXML)
            elif export_type == "aaf":
                success = target_timeline.Export(file_path, resolve.EXPORT_AAF)
            elif export_type == "edl":
                success = target_timeline.Export(file_path, resolve.EXPORT_EDL)
            elif export_type == "txt":
                success = target_timeline.Export(file_path, resolve.EXPORT_TXT)
            elif export_type == "html":
                success = target_timeline.Export(file_path, resolve.EXPORT_HTML)
            else:
                return {"error": f"Export type '{export_type}' not implemented"}

            if success:
                return {
                    "status": "success",
                    "message": f"Timeline '{timeline_name}' exported successfully",
                    "file_path": file_path,
                    "export_type": export_type,
                }
            else:
                # Try alternative export method
                media_storage = resolve.GetMediaStorage()
                if media_storage:
                    # Some versions may use different API
                    if export_type == "fcpxml":
                        success = media_storage.ExportFCPXML(target_timeline, file_path)
                    elif export_type == "aaf":
                        success = media_storage.ExportAAF(target_timeline, file_path)
                    elif export_type == "edl":
                        success = media_storage.ExportEDL(target_timeline, file_path)

                    if success:
                        return {
                            "status": "success",
                            "message": f"Timeline '{timeline_name}' exported successfully via MediaStorage",
                            "file_path": file_path,
                            "export_type": export_type,
                        }

                return {
                    "error": f"Failed to export timeline '{timeline_name}' as {export_type}"
                }
        except Exception as e:
            return {"error": f"Export error: {str(e)}"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}
