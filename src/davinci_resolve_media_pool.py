"""
DaVinci Resolve Media Pool Operations MCP Functions

This module provides functions to manipulate the DaVinci Resolve Media Pool.
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


def mcp_get_media_pool_root_folder() -> Dict[str, Any]:
    """
    Get information about the Media Pool root folder.

    Returns:
        A dictionary with root folder information
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

        # Get basic information about the root folder
        folder_info = {"name": root_folder.GetName(), "children": []}

        # Get subfolders
        subfolders = root_folder.GetSubFolderList()
        for subfolder in subfolders:
            folder_info["children"].append(
                {"name": subfolder.GetName(), "type": "folder"}
            )

        # Get clips in root folder
        clips = root_folder.GetClipList()
        for clip in clips:
            folder_info["children"].append({"name": clip.GetName(), "type": "clip"})

        return {"root_folder": folder_info}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_get_media_pool_folder(folder_name: str) -> Dict[str, Any]:
    """
    Get information about a specific Media Pool folder.

    Args:
        folder_name: The name of the folder to get info about

    Returns:
        A dictionary with folder information
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

        # Find the folder by name
        target_folder = None
        if folder_name == root_folder.GetName():
            target_folder = root_folder
        else:
            # Recursive function to find folder
            def find_folder(parent_folder, name):
                subfolders = parent_folder.GetSubFolderList()
                for subfolder in subfolders:
                    if subfolder.GetName() == name:
                        return subfolder
                    result = find_folder(subfolder, name)
                    if result:
                        return result
                return None

            target_folder = find_folder(root_folder, folder_name)

        if not target_folder:
            return {"error": f"Folder '{folder_name}' not found"}

        # Get folder information
        folder_info = {"name": target_folder.GetName(), "children": []}

        # Get subfolders
        subfolders = target_folder.GetSubFolderList()
        for subfolder in subfolders:
            folder_info["children"].append(
                {"name": subfolder.GetName(), "type": "folder"}
            )

        # Get clips in folder
        clips = target_folder.GetClipList()
        for clip in clips:
            folder_info["children"].append({"name": clip.GetName(), "type": "clip"})

        return {"folder": folder_info}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_create_media_pool_folder(
    folder_name: str, parent_folder_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new folder in the Media Pool.

    Args:
        folder_name: The name for the new folder
        parent_folder_name: The name of the parent folder, or None for root folder

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

        # Get the parent folder
        parent_folder = None
        if parent_folder_name:
            root_folder = media_pool.GetRootFolder()

            # Recursive function to find folder
            def find_folder(parent, name):
                if parent.GetName() == name:
                    return parent

                subfolders = parent.GetSubFolderList()
                for subfolder in subfolders:
                    if subfolder.GetName() == name:
                        return subfolder
                    result = find_folder(subfolder, name)
                    if result:
                        return result
                return None

            parent_folder = find_folder(root_folder, parent_folder_name)

            if not parent_folder:
                return {"error": f"Parent folder '{parent_folder_name}' not found"}
        else:
            # Use root folder as parent
            parent_folder = media_pool.GetRootFolder()

        # Set current folder to parent
        media_pool.SetCurrentFolder(parent_folder)

        # Create new folder
        new_folder = media_pool.AddSubFolder(parent_folder, folder_name)

        if new_folder:
            return {
                "status": "success",
                "message": f"Folder '{folder_name}' created successfully",
                "folder_name": folder_name,
                "parent_folder": parent_folder.GetName(),
            }
        else:
            return {"error": f"Failed to create folder '{folder_name}'"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_import_media(
    file_paths: List[str], folder_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Import media files into the Media Pool.

    Args:
        file_paths: List of file paths to import
        folder_name: The name of the target folder, or None for current folder

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

        # Get the target folder
        target_folder = None
        if folder_name:
            root_folder = media_pool.GetRootFolder()

            # Recursive function to find folder
            def find_folder(parent, name):
                if parent.GetName() == name:
                    return parent

                subfolders = parent.GetSubFolderList()
                for subfolder in subfolders:
                    if subfolder.GetName() == name:
                        return subfolder
                    result = find_folder(subfolder, name)
                    if result:
                        return result
                return None

            target_folder = find_folder(root_folder, folder_name)

            if not target_folder:
                return {"error": f"Folder '{folder_name}' not found"}

            # Set as current folder
            media_pool.SetCurrentFolder(target_folder)

        # Import the files
        imported_clips = media_pool.ImportMedia(file_paths)

        if imported_clips:
            return {
                "status": "success",
                "message": f"Imported {len(imported_clips)} media files successfully",
                "imported_count": len(imported_clips),
                "target_folder": folder_name or media_pool.GetCurrentFolder().GetName(),
            }
        else:
            return {"error": "Failed to import media files"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_get_clip_info(clip_name: str) -> Dict[str, Any]:
    """
    Get information about a specific clip in the Media Pool.

    Args:
        clip_name: The name of the clip to get info about

    Returns:
        A dictionary with clip information
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

        # Recursive function to find clip in folders
        def find_clip(folder, name):
            clips = folder.GetClipList()
            for clip in clips:
                if clip.GetName() == name:
                    return clip

            subfolders = folder.GetSubFolderList()
            for subfolder in subfolders:
                result = find_clip(subfolder, name)
                if result:
                    return result
            return None

        clip = find_clip(root_folder, clip_name)

        if not clip:
            return {"error": f"Clip '{clip_name}' not found"}

        # Get clip properties
        clip_info = {
            "name": clip.GetName(),
            "duration": clip.GetClipProperty("Duration"),
            "fps": clip.GetClipProperty("FPS"),
            "format": clip.GetClipProperty("Format"),
            "resolution": {
                "width": clip.GetClipProperty("Resolution Width"),
                "height": clip.GetClipProperty("Resolution Height"),
            },
            "video_codec": clip.GetClipProperty("Video Codec"),
            "audio_codec": clip.GetClipProperty("Audio Codec"),
            "file_path": clip.GetClipProperty("File Path"),
        }

        return {"clip": clip_info}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_set_clip_property(
    clip_name: str, property_name: str, property_value: Any
) -> Dict[str, Any]:
    """
    Set a property for a clip in the Media Pool.

    Args:
        clip_name: The name of the clip
        property_name: The name of the property to set
        property_value: The value to set

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

        root_folder = media_pool.GetRootFolder()
        if not root_folder:
            return {"error": "Could not get Media Pool root folder"}

        # Recursive function to find clip in folders
        def find_clip(folder, name):
            clips = folder.GetClipList()
            for clip in clips:
                if clip.GetName() == name:
                    return clip

            subfolders = folder.GetSubFolderList()
            for subfolder in subfolders:
                result = find_clip(subfolder, name)
                if result:
                    return result
            return None

        clip = find_clip(root_folder, clip_name)

        if not clip:
            return {"error": f"Clip '{clip_name}' not found"}

        # Set clip property
        success = clip.SetClipProperty(property_name, property_value)

        if success:
            return {
                "status": "success",
                "message": f"Property '{property_name}' updated for clip '{clip_name}'",
                "clip": clip_name,
                "property": property_name,
                "value": property_value,
            }
        else:
            return {
                "error": f"Failed to update property '{property_name}' for clip '{clip_name}'"
            }

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}
