"""Folder-oriented tools for media pool folders."""

from src.granular.common import *  # noqa: F401,F403

resolve = ResolveProxy()

@mcp.tool()
def export_folder(folder_name: str, export_path: str, export_type: str = "DRB") -> str:
    """Export a folder to a DRB file or other format.
    
    Args:
        folder_name: Name of the folder to export
        export_path: Path to save the exported file
        export_type: Export format (DRB is default and currently the only supported option)
    """
    pm, current_project = get_current_project()
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
    pm, current_project = get_current_project()
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
    pm, current_project = get_current_project()
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
