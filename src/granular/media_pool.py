"""Media pool operations and MediaPool API tools."""

from src.granular.common import *  # noqa: F401,F403

resolve = ResolveProxy()

@mcp.resource("resolve://media-pool-clips")
def list_media_pool_clips() -> List[Dict[str, Any]]:
    """List all clips in the root folder of the media pool."""
    pm, current_project = get_current_project()
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
