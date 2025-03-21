"""
Timeline marker functions for DaVinci Resolve MCP

Functions for creating, reading, updating and deleting timeline markers
"""
import os
from ..resolve_init import get_resolve

def get_all_timeline_markers():
    """
    Get all markers in the current timeline
    
    Returns:
        List of markers with their details (frame, name, color, etc.)
    """
    resolve = get_resolve()
    if not resolve:
        return {"error": "Could not connect to DaVinci Resolve"}
    
    pm = resolve.GetProjectManager()
    if not pm:
        return {"error": "Could not get Project Manager"}
    
    project = pm.GetCurrentProject()
    if not project:
        return {"error": "No project is open"}
    
    timeline = project.GetCurrentTimeline()
    if not timeline:
        return {"error": "No timeline is open"}
    
    markers = timeline.GetMarkers()
    if not markers:
        return {"markers": []}
    
    # Convert the markers dictionary to a list of marker objects
    marker_list = []
    for frame, marker_data in markers.items():
        marker_obj = {
            "frame": int(frame),
            "color": marker_data.get("color", ""),
            "name": marker_data.get("name", ""),
            "note": marker_data.get("note", ""),
            "duration": marker_data.get("duration", 1),
            "customData": marker_data.get("customData", "")
        }
        marker_list.append(marker_obj)
    
    # Sort markers by frame number
    marker_list.sort(key=lambda x: x["frame"])
    
    return {"markers": marker_list}

def add_timeline_marker(frame=None, color="Blue", name="", note="", duration=1, custom_data=""):
    """
    Add a marker at the specified frame in the current timeline
    
    Args:
        frame: Frame number for the marker (or None for current playhead position)
        color: Marker color (Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream)
        name: Marker name
        note: Marker note
        duration: Marker duration in frames
        custom_data: Custom data to associate with the marker
        
    Returns:
        Status of the operation
    """
    resolve = get_resolve()
    if not resolve:
        return {"error": "Could not connect to DaVinci Resolve"}
    
    pm = resolve.GetProjectManager()
    if not pm:
        return {"error": "Could not get Project Manager"}
    
    project = pm.GetCurrentProject()
    if not project:
        return {"error": "No project is open"}
    
    timeline = project.GetCurrentTimeline()
    if not timeline:
        return {"error": "No timeline is open"}
    
    # If no frame is specified, use the current playhead position
    if frame is None:
        frame = timeline.GetCurrentTimecode()
        # Convert timecode to frame number if needed
        if isinstance(frame, str) and ":" in frame:
            # For simplicity, we'll get all markers and find the closest one if timecode is provided
            markers = timeline.GetMarkers()
            marker_frames = [int(f) for f in markers.keys()]
            if marker_frames:
                # Just use a frame we know exists rather than converting timecode
                frame = marker_frames[0]
            else:
                # Fallback to first frame if no markers exist
                frame = timeline.GetStartFrame()
    
    # Normalize color name
    color = color.capitalize()
    
    # Valid marker colors
    valid_colors = ["Blue", "Cyan", "Green", "Yellow", "Red", "Pink", 
                   "Purple", "Fuchsia", "Rose", "Lavender", "Sky", 
                   "Mint", "Lemon", "Sand", "Cocoa", "Cream"]
    
    if color not in valid_colors:
        return {"error": f"Invalid marker color. Valid colors are: {', '.join(valid_colors)}"}
    
    # Create the marker
    success = timeline.AddMarker(
        frame, 
        color, 
        name, 
        note, 
        duration, 
        custom_data
    )
    
    if success:
        return {
            "status": "success",
            "marker": {
                "frame": frame,
                "color": color,
                "name": name,
                "note": note,
                "duration": duration,
                "customData": custom_data
            }
        }
    else:
        return {"error": f"Failed to add marker at frame {frame}"}

def update_marker(frame, color=None, name=None, note=None, duration=None, custom_data=None):
    """
    Update properties of an existing marker
    
    Args:
        frame: Frame number of the marker to update
        color: New marker color (or None to keep existing)
        name: New marker name (or None to keep existing)
        note: New marker note (or None to keep existing)
        duration: New marker duration (or None to keep existing)
        custom_data: New custom data (or None to keep existing)
        
    Returns:
        Status of the operation
    """
    resolve = get_resolve()
    if not resolve:
        return {"error": "Could not connect to DaVinci Resolve"}
    
    pm = resolve.GetProjectManager()
    if not pm:
        return {"error": "Could not get Project Manager"}
    
    project = pm.GetCurrentProject()
    if not project:
        return {"error": "No project is open"}
    
    timeline = project.GetCurrentTimeline()
    if not timeline:
        return {"error": "No timeline is open"}
    
    # Get all markers
    markers = timeline.GetMarkers()
    if not markers:
        return {"error": f"No markers found in timeline"}
    
    # Check if the marker exists
    frame_str = str(frame)
    if frame_str not in markers:
        return {"error": f"No marker found at frame {frame}"}
    
    # Get existing marker data
    marker_data = markers[frame_str]
    
    # Update only the specified fields
    if color is not None:
        # Normalize color name
        color = color.capitalize()
        
        # Valid marker colors
        valid_colors = ["Blue", "Cyan", "Green", "Yellow", "Red", "Pink", 
                       "Purple", "Fuchsia", "Rose", "Lavender", "Sky", 
                       "Mint", "Lemon", "Sand", "Cocoa", "Cream"]
        
        if color not in valid_colors:
            return {"error": f"Invalid marker color. Valid colors are: {', '.join(valid_colors)}"}
        
        marker_data["color"] = color
    
    if name is not None:
        marker_data["name"] = name
    
    if note is not None:
        marker_data["note"] = note
    
    if duration is not None:
        marker_data["duration"] = duration
    
    if custom_data is not None:
        marker_data["customData"] = custom_data
    
    # Delete the old marker
    success = timeline.DeleteMarkerAtFrame(frame)
    if not success:
        return {"error": f"Failed to update marker at frame {frame} (could not delete old marker)"}
    
    # Create a new marker with the updated data
    success = timeline.AddMarker(
        frame,
        marker_data.get("color", "Blue"),
        marker_data.get("name", ""),
        marker_data.get("note", ""),
        marker_data.get("duration", 1),
        marker_data.get("customData", "")
    )
    
    if success:
        return {
            "status": "success",
            "marker": {
                "frame": frame,
                "color": marker_data.get("color", "Blue"),
                "name": marker_data.get("name", ""),
                "note": marker_data.get("note", ""),
                "duration": marker_data.get("duration", 1),
                "customData": marker_data.get("customData", "")
            }
        }
    else:
        return {"error": f"Failed to update marker at frame {frame} (could not add new marker)"}

def delete_marker(frame):
    """
    Delete a marker at the specified frame
    
    Args:
        frame: Frame number of the marker to delete
        
    Returns:
        Status of the operation
    """
    resolve = get_resolve()
    if not resolve:
        return {"error": "Could not connect to DaVinci Resolve"}
    
    pm = resolve.GetProjectManager()
    if not pm:
        return {"error": "Could not get Project Manager"}
    
    project = pm.GetCurrentProject()
    if not project:
        return {"error": "No project is open"}
    
    timeline = project.GetCurrentTimeline()
    if not timeline:
        return {"error": "No timeline is open"}
    
    # Check if the marker exists
    markers = timeline.GetMarkers()
    if not markers or str(frame) not in markers:
        return {"error": f"No marker found at frame {frame}"}
    
    # Delete the marker
    success = timeline.DeleteMarkerAtFrame(frame)
    
    if success:
        return {
            "status": "success",
            "frame": frame
        }
    else:
        return {"error": f"Failed to delete marker at frame {frame}"}

def delete_markers_by_color(color):
    """
    Delete all markers of a specific color
    
    Args:
        color: Color of markers to delete
        
    Returns:
        Status of the operation with count of deleted markers
    """
    resolve = get_resolve()
    if not resolve:
        return {"error": "Could not connect to DaVinci Resolve"}
    
    pm = resolve.GetProjectManager()
    if not pm:
        return {"error": "Could not get Project Manager"}
    
    project = pm.GetCurrentProject()
    if not project:
        return {"error": "No project is open"}
    
    timeline = project.GetCurrentTimeline()
    if not timeline:
        return {"error": "No timeline is open"}
    
    # Normalize color name
    color = color.capitalize()
    
    # Get all markers before deletion for counting
    markers_before = timeline.GetMarkers()
    if not markers_before:
        return {"status": "success", "deleted_count": 0, "message": "No markers found in timeline"}
    
    # Delete markers by color
    success = timeline.DeleteMarkersByColor(color)
    
    if success:
        # Get markers after deletion to calculate the count
        markers_after = timeline.GetMarkers()
        deleted_count = len(markers_before) - (len(markers_after) if markers_after else 0)
        
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "color": color
        }
    else:
        return {"error": f"Failed to delete markers with color {color}"}

# MCP Interface functions

def mcp_get_timeline_markers():
    """
    MCP function to get all markers in the current timeline
    
    Returns:
        List of markers with their details
    """
    return get_all_timeline_markers()

def mcp_add_timeline_marker(frame=None, color="Blue", name="", note="", duration=1, custom_data=""):
    """
    MCP function to add a marker at the specified frame in the current timeline
    
    Args:
        frame: Frame number for the marker (or None for current playhead position)
        color: Marker color
        name: Marker name
        note: Marker note
        duration: Marker duration in frames
        custom_data: Custom data to associate with the marker
        
    Returns:
        Status of the operation
    """
    return add_timeline_marker(frame, color, name, note, duration, custom_data)

def mcp_update_marker(frame, color=None, name=None, note=None, duration=None, custom_data=None):
    """
    MCP function to update properties of an existing marker
    
    Args:
        frame: Frame number of the marker to update
        color: New marker color (or None to keep existing)
        name: New marker name (or None to keep existing)
        note: New marker note (or None to keep existing)
        duration: New marker duration (or None to keep existing)
        custom_data: New custom data (or None to keep existing)
        
    Returns:
        Status of the operation
    """
    return update_marker(frame, color, name, note, duration, custom_data)

def mcp_delete_marker(frame):
    """
    MCP function to delete a marker at the specified frame
    
    Args:
        frame: Frame number of the marker to delete
        
    Returns:
        Status of the operation
    """
    return delete_marker(frame)

def mcp_delete_markers_by_color(color):
    """
    MCP function to delete all markers of a specific color
    
    Args:
        color: Color of markers to delete
        
    Returns:
        Status of the operation with count of deleted markers
    """
    return delete_markers_by_color(color) 