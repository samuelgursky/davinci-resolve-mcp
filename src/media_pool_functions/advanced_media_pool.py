"""
Advanced Media Pool Functions for DaVinci Resolve MCP

This module provides enhanced Media Pool functionality including:
- Advanced folder navigation
- Bulk operations for clips
- Smart bins integration
"""

import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from ..resolve_init import get_resolve

# ===== Helper Functions =====

def _get_media_pool():
    """
    Helper function to get the media pool object
    
    Returns:
        MediaPool object or None if not available
    """
    resolve = get_resolve()
    if not resolve:
        return None
    
    pm = resolve.GetProjectManager()
    if not pm:
        return None
    
    project = pm.GetCurrentProject()
    if not project:
        return None
    
    media_pool = project.GetMediaPool()
    return media_pool

def _get_folder_by_path(path: str, create_if_missing: bool = False):
    """
    Get a media pool folder by path (e.g. "Master/Scenes/Scene 1")
    
    Args:
        path: Path to the folder, using '/' as separator
        create_if_missing: If True, creates folders that don't exist
        
    Returns:
        Folder object or None if not found
    """
    media_pool = _get_media_pool()
    if not media_pool:
        return None
    
    # Get root folder
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return None
    
    # Handle empty or root path
    if not path or path == "/" or path == "Root":
        return root_folder
    
    # Split path into parts
    parts = path.strip("/").split("/")
    current_folder = root_folder
    
    # Traverse path
    for part in parts:
        found = False
        
        # Get subfolders
        subfolders = current_folder.GetSubFolderList()
        
        # Look for matching subfolder
        for subfolder in subfolders:
            if subfolder.GetName() == part:
                current_folder = subfolder
                found = True
                break
        
        # Create folder if not found and creation is enabled
        if not found:
            if create_if_missing:
                new_folder = media_pool.AddSubFolder(current_folder, part)
                if new_folder:
                    current_folder = new_folder
                else:
                    return None
            else:
                return None
    
    return current_folder

def _convert_folder_to_dict(folder, include_clips: bool = False, include_subfolders: bool = False, recursive: bool = False):
    """
    Convert a folder object to a dictionary representation
    
    Args:
        folder: Folder object
        include_clips: If True, includes clips in the folder
        include_subfolders: If True, includes subfolder info
        recursive: If True, includes complete subfolder hierarchy
        
    Returns:
        Dictionary representation of the folder
    """
    if not folder:
        return None
    
    result = {
        "name": folder.GetName(),
        "is_root": folder.GetName() == "Master"  # Root folder is named "Master"
    }
    
    # Include clips if requested
    if include_clips:
        clips = folder.GetClipList()
        clip_list = []
        
        for clip in clips:
            clip_info = {
                "name": clip.GetName(),
                "duration": clip.GetDuration(),
                "type": clip.GetClipProperty("Type"),
            }
            
            # Try to get additional properties
            try:
                properties = [
                    "Resolution", "Format", "FrameRate", "IsTimeline",
                    "Flags", "Keyword", "Comments"
                ]
                for prop in properties:
                    clip_info[prop.lower()] = clip.GetClipProperty(prop)
            except:
                pass
                
            clip_list.append(clip_info)
            
        result["clips"] = clip_list
        result["clip_count"] = len(clip_list)
    
    # Include subfolders if requested
    if include_subfolders:
        subfolders = folder.GetSubFolderList()
        subfolder_list = []
        
        for subfolder in subfolders:
            if recursive:
                # Recursive call for full hierarchy
                subfolder_dict = _convert_folder_to_dict(
                    subfolder, 
                    include_clips=include_clips, 
                    include_subfolders=True, 
                    recursive=True
                )
                subfolder_list.append(subfolder_dict)
            else:
                # Just get names for non-recursive
                subfolder_list.append({
                    "name": subfolder.GetName()
                })
                
        result["subfolders"] = subfolder_list
        result["subfolder_count"] = len(subfolder_list)
    
    return result

# ===== Main Functions =====

def get_folder_hierarchy(include_clips: bool = False):
    """
    Get the complete folder hierarchy of the media pool
    
    Args:
        include_clips: If True, includes all clips in each folder
        
    Returns:
        Dictionary containing the full folder hierarchy
    """
    media_pool = _get_media_pool()
    if not media_pool:
        return {"error": "Could not get media pool"}
    
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return {"error": "Could not get root folder"}
    
    hierarchy = _convert_folder_to_dict(
        root_folder, 
        include_clips=include_clips, 
        include_subfolders=True, 
        recursive=True
    )
    
    return {"status": "success", "hierarchy": hierarchy}

def get_folder_by_path(path: str, include_clips: bool = False, include_subfolders: bool = False):
    """
    Get a folder by path
    
    Args:
        path: Path to the folder (e.g. "Master/Scenes/Scene 1")
        include_clips: If True, includes clips in the folder
        include_subfolders: If True, includes immediate subfolders info
        
    Returns:
        Dictionary containing folder information
    """
    media_pool = _get_media_pool()
    if not media_pool:
        return {"error": "Could not get media pool"}
    
    folder = _get_folder_by_path(path)
    if not folder:
        return {"error": f"Folder not found: {path}"}
    
    folder_dict = _convert_folder_to_dict(
        folder, 
        include_clips=include_clips, 
        include_subfolders=include_subfolders
    )
    
    return {"status": "success", "folder": folder_dict}

def create_folder_path(path: str):
    """
    Create a folder path, creating any missing folders along the way
    
    Args:
        path: Path to create (e.g. "Master/Scenes/Scene 1/Takes")
        
    Returns:
        Status of the operation
    """
    media_pool = _get_media_pool()
    if not media_pool:
        return {"error": "Could not get media pool"}
    
    folder = _get_folder_by_path(path, create_if_missing=True)
    if not folder:
        return {"error": f"Failed to create folder path: {path}"}
    
    folder_dict = _convert_folder_to_dict(folder)
    
    return {
        "status": "success", 
        "message": f"Created folder path: {path}", 
        "folder": folder_dict
    }

def set_current_folder(path: str):
    """
    Set the current working folder in the media pool
    
    Args:
        path: Path to the folder (e.g. "Master/Scenes/Scene 1")
        
    Returns:
        Status of the operation
    """
    media_pool = _get_media_pool()
    if not media_pool:
        return {"error": "Could not get media pool"}
    
    folder = _get_folder_by_path(path)
    if not folder:
        return {"error": f"Folder not found: {path}"}
    
    success = media_pool.SetCurrentFolder(folder)
    if not success:
        return {"error": f"Failed to set current folder to: {path}"}
    
    return {
        "status": "success", 
        "message": f"Current folder set to: {path}"
    }

def get_current_folder():
    """
    Get the current working folder in the media pool
    
    Returns:
        Dictionary containing folder information
    """
    media_pool = _get_media_pool()
    if not media_pool:
        return {"error": "Could not get media pool"}
    
    folder = media_pool.GetCurrentFolder()
    if not folder:
        return {"error": "Could not get current folder"}
    
    folder_dict = _convert_folder_to_dict(
        folder, 
        include_clips=True, 
        include_subfolders=True
    )
    
    return {"status": "success", "folder": folder_dict}

def move_clips_between_folders(source_path: str, destination_path: str, clip_names: List[str] = None):
    """
    Move clips between folders
    
    Args:
        source_path: Path to source folder
        destination_path: Path to destination folder
        clip_names: List of clip names to move (None = all clips)
        
    Returns:
        Status of the operation
    """
    media_pool = _get_media_pool()
    if not media_pool:
        return {"error": "Could not get media pool"}
    
    # Get source folder
    source_folder = _get_folder_by_path(source_path)
    if not source_folder:
        return {"error": f"Source folder not found: {source_path}"}
    
    # Get destination folder
    dest_folder = _get_folder_by_path(destination_path)
    if not dest_folder:
        return {"error": f"Destination folder not found: {destination_path}"}
    
    # Get clips from source folder
    all_clips = source_folder.GetClipList()
    if not all_clips:
        return {"error": f"No clips found in source folder: {source_path}"}
    
    clips_to_move = []
    
    # Filter clips by name if specified
    if clip_names:
        for clip in all_clips:
            if clip.GetName() in clip_names:
                clips_to_move.append(clip)
        
        if not clips_to_move:
            return {"error": "None of the specified clips found in source folder"}
    else:
        clips_to_move = all_clips
    
    # Move clips
    result = media_pool.MoveClips(clips_to_move, dest_folder)
    
    if result:
        return {
            "status": "success",
            "message": f"Moved {len(clips_to_move)} clips from {source_path} to {destination_path}"
        }
    else:
        return {"error": "Failed to move clips between folders"}

def create_smart_bin(name: str, search_criteria: Dict[str, Any]):
    """
    Create a smart bin with search criteria
    
    Args:
        name: Name for the smart bin
        search_criteria: Dictionary with search criteria
            Example: {
                "Keywords": "interview",
                "Clip Type": "video",
                "Frame Rate": "24",
                "Resolution": "1920x1080"
            }
        
    Returns:
        Status of the operation
    """
    media_pool = _get_media_pool()
    if not media_pool:
        return {"error": "Could not get media pool"}
    
    # Convert search criteria to match API expectations
    search_string = ""
    for key, value in search_criteria.items():
        search_string += f"{key}:{value} "
    
    search_string = search_string.strip()
    
    # Create smart bin
    result = media_pool.CreateSmartBin(name, search_string)
    
    if result:
        return {
            "status": "success",
            "message": f"Created smart bin: {name}",
            "search_criteria": search_criteria
        }
    else:
        return {"error": f"Failed to create smart bin: {name}"}

def get_smart_bins():
    """
    Get a list of all smart bins in the project
    
    Returns:
        Dictionary containing smart bin information
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
    
    # There's no direct API to get smart bins, so we need to use
    # the MediaPool.GetFolderByName() function and test for known smart bins
    
    # Common Blackmagic-created smart bins
    default_bins = [
        "All Clips", "All Video Clips", "All Audio Clips", 
        "Timelines", "Favorites", "Recently Added"
    ]
    
    media_pool = project.GetMediaPool()
    
    smart_bins = []
    for bin_name in default_bins:
        smart_bin = media_pool.GetFolderByName(bin_name)
        if smart_bin:
            # Get clips in this smart bin
            clips = smart_bin.GetClipList()
            clip_count = len(clips) if clips else 0
            
            smart_bins.append({
                "name": bin_name,
                "is_default": True,
                "clip_count": clip_count
            })
    
    # Get user-created smart bins by trying folder names
    # This is a limited approach but there's no direct API for this
    
    # For now we'll just return what we found
    return {
        "status": "success",
        "smart_bins": smart_bins
    }

def delete_smart_bin(name: str):
    """
    Delete a smart bin
    
    Args:
        name: Name of the smart bin to delete
        
    Returns:
        Status of the operation
    """
    media_pool = _get_media_pool()
    if not media_pool:
        return {"error": "Could not get media pool"}
    
    # Check if the smart bin exists
    smart_bin = media_pool.GetFolderByName(name)
    if not smart_bin:
        return {"error": f"Smart bin not found: {name}"}
    
    # Try to delete it
    # Note: DeleteSmartBin is not explicitly in the API but some functions
    # exist that aren't documented
    try:
        result = media_pool.DeleteSmartBin(name)
        if result:
            return {
                "status": "success",
                "message": f"Deleted smart bin: {name}"
            }
        else:
            return {"error": f"Failed to delete smart bin: {name}"}
    except:
        # Try alternative method
        try:
            result = media_pool.DeleteFolder(smart_bin)
            if result:
                return {
                    "status": "success",
                    "message": f"Deleted smart bin: {name}"
                }
            else:
                return {"error": f"Failed to delete smart bin: {name}"}
        except:
            return {"error": f"Failed to delete smart bin (unsupported operation): {name}"}

def bulk_set_clip_property(folder_path: str, property_name: str, property_value: str, clip_names: List[str] = None):
    """
    Set a property on multiple clips in a folder
    
    Args:
        folder_path: Path to the folder containing clips
        property_name: Name of the property to set
        property_value: Value to set
        clip_names: List of clip names to modify (None = all clips)
        
    Returns:
        Status of the operation
    """
    media_pool = _get_media_pool()
    if not media_pool:
        return {"error": "Could not get media pool"}
    
    # Get folder
    folder = _get_folder_by_path(folder_path)
    if not folder:
        return {"error": f"Folder not found: {folder_path}"}
    
    # Get clips
    all_clips = folder.GetClipList()
    if not all_clips:
        return {"error": f"No clips found in folder: {folder_path}"}
    
    clips_to_modify = []
    
    # Filter clips by name if specified
    if clip_names:
        for clip in all_clips:
            if clip.GetName() in clip_names:
                clips_to_modify.append(clip)
        
        if not clips_to_modify:
            return {"error": "None of the specified clips found in folder"}
    else:
        clips_to_modify = all_clips
    
    # Set property on each clip
    success_count = 0
    for clip in clips_to_modify:
        try:
            result = clip.SetClipProperty(property_name, property_value)
            if result:
                success_count += 1
        except:
            # Some properties might not be settable, continue with others
            continue
    
    if success_count > 0:
        return {
            "status": "success",
            "message": f"Set {property_name} to '{property_value}' on {success_count} of {len(clips_to_modify)} clips"
        }
    else:
        return {"error": f"Failed to set property {property_name} on any clips"}

def import_files_to_folder(file_paths: List[str], folder_path: str = None):
    """
    Import files to a specific folder
    
    Args:
        file_paths: List of file paths to import
        folder_path: Path to destination folder (None = current folder)
        
    Returns:
        Status of the operation
    """
    media_pool = _get_media_pool()
    if not media_pool:
        return {"error": "Could not get media pool"}
    
    # Get destination folder
    if folder_path:
        folder = _get_folder_by_path(folder_path)
        if not folder:
            return {"error": f"Destination folder not found: {folder_path}"}
        
        # Set as current folder
        media_pool.SetCurrentFolder(folder)
    
    # Check if files exist
    valid_files = []
    for file_path in file_paths:
        if os.path.exists(file_path):
            valid_files.append(file_path)
    
    if not valid_files:
        return {"error": "None of the specified files exist"}
    
    # Import files
    imported_clips = media_pool.ImportMedia(valid_files)
    
    if imported_clips:
        # Get names of imported clips
        clip_names = [clip.GetName() for clip in imported_clips]
        
        return {
            "status": "success",
            "message": f"Imported {len(imported_clips)} of {len(file_paths)} files",
            "imported_clip_count": len(imported_clips),
            "imported_clip_names": clip_names
        }
    else:
        return {"error": "Failed to import files"}

# ===== MCP Interface Functions =====

def mcp_get_folder_hierarchy(include_clips: bool = False):
    """
    MCP function to get the complete folder hierarchy of the media pool
    
    Args:
        include_clips: If True, includes all clips in each folder
        
    Returns:
        Dictionary containing the full folder hierarchy
    """
    return get_folder_hierarchy(include_clips)

def mcp_get_folder_by_path(path: str, include_clips: bool = False, include_subfolders: bool = False):
    """
    MCP function to get a folder by path
    
    Args:
        path: Path to the folder (e.g. "Master/Scenes/Scene 1")
        include_clips: If True, includes clips in the folder
        include_subfolders: If True, includes immediate subfolders info
        
    Returns:
        Dictionary containing folder information
    """
    return get_folder_by_path(path, include_clips, include_subfolders)

def mcp_create_folder_path(path: str):
    """
    MCP function to create a folder path, creating any missing folders along the way
    
    Args:
        path: Path to create (e.g. "Master/Scenes/Scene 1/Takes")
        
    Returns:
        Status of the operation
    """
    return create_folder_path(path)

def mcp_set_current_folder(path: str):
    """
    MCP function to set the current working folder in the media pool
    
    Args:
        path: Path to the folder (e.g. "Master/Scenes/Scene 1")
        
    Returns:
        Status of the operation
    """
    return set_current_folder(path)

def mcp_get_current_folder():
    """
    MCP function to get the current working folder in the media pool
    
    Returns:
        Dictionary containing folder information
    """
    return get_current_folder()

def mcp_move_clips_between_folders(source_path: str, destination_path: str, clip_names: List[str] = None):
    """
    MCP function to move clips between folders
    
    Args:
        source_path: Path to source folder
        destination_path: Path to destination folder
        clip_names: List of clip names to move (None = all clips)
        
    Returns:
        Status of the operation
    """
    return move_clips_between_folders(source_path, destination_path, clip_names)

def mcp_create_smart_bin(name: str, search_criteria: Dict[str, Any]):
    """
    MCP function to create a smart bin with search criteria
    
    Args:
        name: Name for the smart bin
        search_criteria: Dictionary with search criteria
            Example: {
                "Keywords": "interview",
                "Clip Type": "video",
                "Frame Rate": "24",
                "Resolution": "1920x1080"
            }
        
    Returns:
        Status of the operation
    """
    return create_smart_bin(name, search_criteria)

def mcp_get_smart_bins():
    """
    MCP function to get a list of all smart bins in the project
    
    Returns:
        Dictionary containing smart bin information
    """
    return get_smart_bins()

def mcp_delete_smart_bin(name: str):
    """
    MCP function to delete a smart bin
    
    Args:
        name: Name of the smart bin to delete
        
    Returns:
        Status of the operation
    """
    return delete_smart_bin(name)

def mcp_bulk_set_clip_property(folder_path: str, property_name: str, property_value: str, clip_names: List[str] = None):
    """
    MCP function to set a property on multiple clips in a folder
    
    Args:
        folder_path: Path to the folder containing clips
        property_name: Name of the property to set
        property_value: Value to set
        clip_names: List of clip names to modify (None = all clips)
        
    Returns:
        Status of the operation
    """
    return bulk_set_clip_property(folder_path, property_name, property_value, clip_names)

def mcp_import_files_to_folder(file_paths: List[str], folder_path: str = None):
    """
    MCP function to import files to a specific folder
    
    Args:
        file_paths: List of file paths to import
        folder_path: Path to destination folder (None = current folder)
        
    Returns:
        Status of the operation
    """
    return import_files_to_folder(file_paths, folder_path) 