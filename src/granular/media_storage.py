"""MediaStorage tools."""

from src.granular.common import *  # noqa: F401,F403

resolve = ResolveProxy()

@mcp.tool()
def get_mounted_volumes() -> Dict[str, Any]:
    """Get list of mounted volumes displayed in Resolve's Media Storage."""
    resolve = get_resolve()
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
    resolve = get_resolve()
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
    resolve = get_resolve()
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
    resolve = get_resolve()
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
    resolve = get_resolve()
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
    resolve = get_resolve()
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
    resolve = get_resolve()
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
