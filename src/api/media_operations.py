#!/usr/bin/env python3
"""
DaVinci Resolve Media Operations
"""

import logging
import os
from typing import List, Dict, Any

logger = logging.getLogger("davinci-resolve-mcp.media")


def list_media_pool_clips(resolve) -> List[Dict[str, Any]]:
    """List all clips in the media pool of the current project."""
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

    # Get the root folder and all its clips
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return [{"error": "Failed to get Root Folder"}]

    clips = root_folder.GetClipList()

    # Format clip info
    clip_info = []
    for clip in clips:
        if clip:
            clip_info.append(
                {
                    "name": clip.GetName(),
                    "type": clip.GetClipProperty()["Type"],
                    "duration": clip.GetClipProperty()["Duration"],
                    "fps": clip.GetClipProperty().get("FPS", "Unknown"),
                }
            )

    return clip_info if clip_info else [{"info": "No clips found in the media pool"}]


def import_media(resolve, file_path: str) -> str:
    """Import a media file into the current project's media pool."""
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    # Validate file path
    if not file_path:
        return "Error: File path cannot be empty"

    if not os.path.exists(file_path):
        return f"Error: File '{file_path}' does not exist"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"

    # Import the media file
    # DaVinci Resolve API expects a list of file paths
    imported_media = media_pool.ImportMedia([file_path])

    if imported_media and len(imported_media) > 0:
        return f"Successfully imported '{os.path.basename(file_path)}'"
    else:
        return (
            f"Failed to import '{file_path}'. The file may be in an unsupported format."
        )


def create_bin(resolve, name: str) -> str:
    """Create a new bin/folder in the media pool."""
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    if not name:
        return "Error: Bin name cannot be empty"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"

    # Get the root folder to add the bin to
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return "Error: Failed to get Root Folder"

    # Check if bin already exists (by checking the subfolders)
    folders = root_folder.GetSubFolderList()
    for folder in folders:
        if folder.GetName() == name:
            return f"Error: Bin '{name}' already exists"

    # Create the bin
    new_bin = media_pool.AddSubFolder(root_folder, name)

    if new_bin:
        return f"Successfully created bin '{name}'"
    else:
        return f"Failed to create bin '{name}'"


def list_bins(resolve) -> List[Dict[str, Any]]:
    """List all bins/folders in the media pool of the current project."""
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

    # Get the root folder
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return [{"error": "Failed to get Root Folder"}]

    # Get all subfolders (bins) from the root folder
    folders = root_folder.GetSubFolderList()

    # Format bin info
    bin_info = []

    # Add root folder information
    bin_info.append(
        {
            "name": root_folder.GetName() or "Master",
            "is_root": True,
            "clip_count": len(root_folder.GetClipList()),
        }
    )

    # Add all subfolders (bins)
    for folder in folders:
        if folder:
            bin_info.append(
                {
                    "name": folder.GetName(),
                    "is_root": False,
                    "clip_count": len(folder.GetClipList()),
                }
            )

    return (
        bin_info if len(bin_info) > 1 else [{"info": "No bins found in the media pool"}]
    )


def get_bin_contents(resolve, bin_name: str) -> List[Dict[str, Any]]:
    """Get the contents of a specific bin/folder in the media pool.

    Args:
        resolve: The DaVinci Resolve instance
        bin_name: The name of the bin to get contents from. Use 'Master' for the root folder.
    """
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

    # Get the root folder
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return [{"error": "Failed to get Root Folder"}]

    # Check if we want the root folder (Master)
    if bin_name.lower() == "master" or bin_name == root_folder.GetName():
        clips = root_folder.GetClipList()
        return format_clip_list(clips, "Master")

    # Otherwise search for the bin in subfolders
    folders = root_folder.GetSubFolderList()
    target_folder = None

    for folder in folders:
        if folder and folder.GetName() == bin_name:
            target_folder = folder
            break

    if not target_folder:
        return [{"error": f"Bin '{bin_name}' not found in Media Pool"}]

    # Get clips from the target folder
    clips = target_folder.GetClipList()
    return format_clip_list(clips, bin_name)


def format_clip_list(clips, bin_name: str) -> List[Dict[str, Any]]:
    """Helper function to format clip info from a clip list."""
    if not clips:
        return [{"info": f"No clips found in bin '{bin_name}'"}]

    clip_info = []
    for clip in clips:
        if clip:
            properties = clip.GetClipProperty()
            clip_info.append(
                {
                    "name": clip.GetName(),
                    "type": properties.get("Type", "Unknown"),
                    "duration": properties.get("Duration", "Unknown"),
                    "fps": properties.get("FPS", "Unknown"),
                    "resolution": f"{properties.get('Width', '?')}x{properties.get('Height', '?')}",
                    "bin": bin_name,
                }
            )

    return clip_info


def list_timeline_clips(resolve) -> List[Dict[str, Any]]:
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

    # Get all video tracks
    video_tracks = current_timeline.GetTrackCount("video")

    clip_info = []
    for track_index in range(1, video_tracks + 1):
        # Note: Track indices in Resolve API are 1-based
        clips = current_timeline.GetItemListInTrack("video", track_index)

        for clip in clips:
            if clip:
                clip_info.append(
                    {
                        "name": clip.GetName(),
                        "track": f"V{track_index}",
                        "start_frame": clip.GetStart(),
                        "end_frame": clip.GetEnd(),
                        "duration": clip.GetDuration(),
                    }
                )

    # Get audio tracks as well
    audio_tracks = current_timeline.GetTrackCount("audio")
    for track_index in range(1, audio_tracks + 1):
        clips = current_timeline.GetItemListInTrack("audio", track_index)

        for clip in clips:
            if clip:
                clip_info.append(
                    {
                        "name": clip.GetName(),
                        "track": f"A{track_index}",
                        "start_frame": clip.GetStart(),
                        "end_frame": clip.GetEnd(),
                        "duration": clip.GetDuration(),
                    }
                )

    return (
        clip_info if clip_info else [{"info": "No clips found in the current timeline"}]
    )


def add_clip_to_timeline(resolve, clip_name: str, timeline_name: str = None) -> str:
    """Add a media pool clip to the timeline.

    Args:
        resolve: The DaVinci Resolve instance
        clip_name: Name of the clip in the media pool
        timeline_name: Optional timeline to target (uses current if not specified)
    """
    if not resolve:
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

    # Get all clips in root folder
    root_folder = media_pool.GetRootFolder()
    clips = root_folder.GetClipList()

    target_clip = None
    for clip in clips:
        if clip.GetName() == clip_name:
            target_clip = clip
            break

    if not target_clip:
        return f"Error: Clip '{clip_name}' not found in Media Pool"

    # Get the target timeline
    timeline = None
    if timeline_name:
        # Switch to the specified timeline
        timeline_count = current_project.GetTimelineCount()
        for i in range(1, timeline_count + 1):
            t = current_project.GetTimelineByIndex(i)
            if t and t.GetName() == timeline_name:
                timeline = t
                current_project.SetCurrentTimeline(timeline)
                break

        if not timeline:
            return f"Error: Timeline '{timeline_name}' not found"
    else:
        # Use current timeline
        timeline = current_project.GetCurrentTimeline()
        if not timeline:
            return "Error: No timeline currently active"

    # Add clip to timeline
    # We need to use media_pool.AppendToTimeline() which expects a list of clips
    result = media_pool.AppendToTimeline([target_clip])

    if result and len(result) > 0:
        return f"Successfully added clip '{clip_name}' to timeline"
    else:
        return f"Failed to add clip '{clip_name}' to timeline"


def delete_media(resolve, clip_name: str) -> str:
    """Delete a media clip from the media pool by name.

    Args:
        resolve: The DaVinci Resolve instance
        clip_name: Name of the clip to delete

    Returns:
        String indicating success or failure with detailed error message
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

    # Get all clips in root folder and all subfolders
    all_clips = []
    target_clip = None

    # Get the root folder
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return "Error: Failed to get Root Folder"

    # Get clips from root folder
    root_clips = root_folder.GetClipList()
    if root_clips:
        all_clips.extend(root_clips)

    # Get clips from subfolders
    folders = root_folder.GetSubFolderList()
    for folder in folders:
        if folder:
            folder_clips = folder.GetClipList()
            if folder_clips:
                all_clips.extend(folder_clips)

    # Find the clip by name
    for clip in all_clips:
        if clip and clip.GetName() == clip_name:
            target_clip = clip
            break

    if not target_clip:
        return f"Error: Clip '{clip_name}' not found in Media Pool"

    # Delete the clip
    try:
        result = media_pool.DeleteClips([target_clip])
        if result:
            return f"Successfully deleted clip '{clip_name}' from Media Pool"
        else:
            return f"Failed to delete clip '{clip_name}' from Media Pool"
    except Exception as e:
        return f"Error deleting clip: {str(e)}"


def move_media_to_bin(resolve, clip_name: str, bin_name: str) -> str:
    """Move a media clip to a specific bin in the media pool.

    Args:
        resolve: The DaVinci Resolve instance
        clip_name: Name of the clip to move
        bin_name: Name of the target bin

    Returns:
        String indicating success or failure with detailed error message
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

    # Get the root folder
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return "Error: Failed to get Root Folder"

    # Find the target bin
    target_folder = None

    # Check if we want the root folder
    if bin_name.lower() == "master" or bin_name == root_folder.GetName():
        target_folder = root_folder
    else:
        # Search in subfolders
        folders = root_folder.GetSubFolderList()
        for folder in folders:
            if folder and folder.GetName() == bin_name:
                target_folder = folder
                break

    if not target_folder:
        return f"Error: Bin '{bin_name}' not found in Media Pool"

    # Find the clip by name
    all_clips = []
    target_clip = None

    # Get clips from root folder
    root_clips = root_folder.GetClipList()
    if root_clips:
        all_clips.extend(root_clips)

    # Get clips from subfolders
    folders = root_folder.GetSubFolderList()
    for folder in folders:
        if folder:
            folder_clips = folder.GetClipList()
            if folder_clips:
                all_clips.extend(folder_clips)

    # Find the clip by name
    for clip in all_clips:
        if clip and clip.GetName() == clip_name:
            target_clip = clip
            break

    if not target_clip:
        return f"Error: Clip '{clip_name}' not found in Media Pool"

    # Move the clip to the target bin
    try:
        result = media_pool.MoveClips([target_clip], target_folder)
        if result:
            return f"Successfully moved clip '{clip_name}' to bin '{bin_name}'"
        else:
            return f"Failed to move clip '{clip_name}' to bin '{bin_name}'"
    except Exception as e:
        return f"Error moving clip: {str(e)}"


def auto_sync_audio(
    resolve,
    clip_names: List[str],
    sync_method: str = "waveform",
    append_mode: bool = False,
    target_bin: str = None,
) -> str:
    """Sync audio between clips with customizable settings.

    Args:
        resolve: The DaVinci Resolve instance
        clip_names: List of clip names to sync
        sync_method: Method to use for synchronization - 'waveform' or 'timecode'
        append_mode: Whether to append the audio or replace it
        target_bin: Optional bin to move synchronized clips to

    Returns:
        String indicating success or failure with detailed error message
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    if not clip_names or len(clip_names) < 2:
        return "Error: At least two clips are required for audio synchronization"

    # Validate sync method
    if sync_method not in ["waveform", "timecode"]:
        return "Error: Sync method must be 'waveform' or 'timecode'"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"

    # Get all clips from media pool
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return "Error: Failed to get Root Folder"

    all_clips = []

    # Get clips from root folder
    root_clips = root_folder.GetClipList()
    if root_clips:
        all_clips.extend(root_clips)

    # Get clips from subfolders
    folders = root_folder.GetSubFolderList()
    for folder in folders:
        if folder:
            folder_clips = folder.GetClipList()
            if folder_clips:
                all_clips.extend(folder_clips)

    # Find clips by name
    clips_to_sync = []
    for name in clip_names:
        found = False
        for clip in all_clips:
            if clip and clip.GetName() == name:
                clips_to_sync.append(clip)
                found = True
                break
        if not found:
            return f"Error: Clip '{name}' not found in Media Pool"

    # Set the clips as selected in media pool
    try:
        result = media_pool.SetCurrentFolder(root_folder)
        if not result:
            return "Error: Failed to set current folder to root"

        result = media_pool.SelectClips(clips_to_sync)
        if not result:
            return "Error: Failed to select clips for syncing"

        # Set sync options
        sync_options = {
            "syncMethod": 0
            if sync_method == "waveform"
            else 1,  # 0 for waveform, 1 for timecode
            "appendMode": append_mode,  # True to append audio, False to replace
        }

        # Perform the auto sync
        result = media_pool.AutoSyncAudio(sync_options)

        if not result:
            return "Error: Failed to sync audio for the selected clips"

        # If a target bin is specified, move the synced clips there
        if target_bin:
            target_folder = None

            # Check if we want the root folder
            if target_bin.lower() == "master" or target_bin == root_folder.GetName():
                target_folder = root_folder
            else:
                # Search in subfolders
                for folder in folders:
                    if folder and folder.GetName() == target_bin:
                        target_folder = folder
                        break

            if not target_folder:
                return f"Warning: Synced clips but bin '{target_bin}' not found for moving clips"

            # Move the synced clips to the target bin
            move_result = media_pool.MoveClips(clips_to_sync, target_folder)
            if not move_result:
                return f"Warning: Synced clips but failed to move them to bin '{target_bin}'"

        return f"Successfully synced audio for {len(clips_to_sync)} clips using {sync_method} method"

    except Exception as e:
        return f"Error syncing audio: {str(e)}"


def unlink_clips(resolve, clip_names: List[str]) -> str:
    """Unlink specified clips, disconnecting them from their media files.

    Args:
        resolve: The DaVinci Resolve instance
        clip_names: List of clip names to unlink

    Returns:
        String indicating success or failure with detailed error message
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    if not clip_names or len(clip_names) == 0:
        return "Error: No clip names provided for unlinking"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"

    # Get all clips from media pool
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return "Error: Failed to get Root Folder"

    all_clips = []

    # Get clips from root folder
    root_clips = root_folder.GetClipList()
    if root_clips:
        all_clips.extend(root_clips)

    # Get clips from subfolders
    folders = root_folder.GetSubFolderList()
    for folder in folders:
        if folder:
            folder_clips = folder.GetClipList()
            if folder_clips:
                all_clips.extend(folder_clips)

    # Find clips by name
    clips_to_unlink = []
    not_found_clips = []

    for name in clip_names:
        found = False
        for clip in all_clips:
            if clip and clip.GetName() == name:
                clips_to_unlink.append(clip)
                found = True
                break
        if not found:
            not_found_clips.append(name)

    if not_found_clips:
        return f"Error: Clips not found in Media Pool: {', '.join(not_found_clips)}"

    if not clips_to_unlink:
        return "Error: No valid clips found to unlink"

    try:
        # Unlink the clips
        result = media_pool.UnlinkClips(clips_to_unlink)

        if result:
            return f"Successfully unlinked {len(clips_to_unlink)} clips"
        else:
            return "Error: Failed to unlink clips"

    except Exception as e:
        return f"Error unlinking clips: {str(e)}"


def relink_clips(
    resolve,
    clip_names: List[str],
    media_paths: List[str] = None,
    folder_path: str = None,
    recursive: bool = False,
) -> str:
    """Relink specified clips to their media files.

    Args:
        resolve: The DaVinci Resolve instance
        clip_names: List of clip names to relink
        media_paths: Optional list of specific media file paths to use for relinking
        folder_path: Optional folder path to search for media files
        recursive: Whether to search the folder path recursively

    Returns:
        String indicating success or failure with detailed error message
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    if not clip_names or len(clip_names) == 0:
        return "Error: No clip names provided for relinking"

    if media_paths is None and folder_path is None:
        return "Error: Either media_paths or folder_path must be provided for relinking"

    if media_paths is not None and folder_path is not None:
        return "Error: Cannot specify both media_paths and folder_path, choose one approach"

    if (
        media_paths is not None
        and len(media_paths) > 0
        and len(media_paths) != len(clip_names)
    ):
        return "Error: If providing media_paths, the number must match the number of clip_names"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"

    # Get all clips from media pool
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return "Error: Failed to get Root Folder"

    all_clips = []

    # Get clips from root folder
    root_clips = root_folder.GetClipList()
    if root_clips:
        all_clips.extend(root_clips)

    # Get clips from subfolders
    folders = root_folder.GetSubFolderList()
    for folder in folders:
        if folder:
            folder_clips = folder.GetClipList()
            if folder_clips:
                all_clips.extend(folder_clips)

    # Find clips by name
    clips_to_relink = []
    not_found_clips = []

    for name in clip_names:
        found = False
        for clip in all_clips:
            if clip and clip.GetName() == name:
                clips_to_relink.append(clip)
                found = True
                break
        if not found:
            not_found_clips.append(name)

    if not_found_clips:
        return f"Error: Clips not found in Media Pool: {', '.join(not_found_clips)}"

    if not clips_to_relink:
        return "Error: No valid clips found to relink"

    try:
        # Relink the clips
        result = False

        if media_paths:
            # Relink with specific media paths
            # Note: The API expects clips and paths to be matched by index
            result = media_pool.RelinkClips(clips_to_relink, media_paths)
        else:
            # Relink by searching in folder path
            relink_options = {"recursive": recursive}
            result = media_pool.RelinkClips(
                clips_to_relink, [], folder_path, relink_options
            )

        if result:
            if media_paths:
                return f"Successfully relinked {len(clips_to_relink)} clips to specified media paths"
            else:
                return f"Successfully relinked {len(clips_to_relink)} clips using media from {folder_path}"
        else:
            if media_paths:
                return "Error: Failed to relink clips to specified media paths"
            else:
                return f"Error: Failed to relink clips using media from {folder_path}"

    except Exception as e:
        return f"Error relinking clips: {str(e)}"


def create_sub_clip(
    resolve,
    clip_name: str,
    start_frame: int,
    end_frame: int,
    sub_clip_name: str = None,
    bin_name: str = None,
) -> str:
    """Create a subclip from the specified clip using in and out points.

    Args:
        resolve: The DaVinci Resolve instance
        clip_name: Name of the source clip
        start_frame: Start frame (in point)
        end_frame: End frame (out point)
        sub_clip_name: Optional name for the subclip (defaults to original name with '_subclip')
        bin_name: Optional bin to place the subclip in

    Returns:
        String indicating success or failure with detailed error message
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    if not clip_name:
        return "Error: Clip name cannot be empty"

    if start_frame >= end_frame:
        return "Error: Start frame must be less than end frame"

    if start_frame < 0:
        return "Error: Start frame cannot be negative"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"

    # Get all clips from media pool
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        return "Error: Failed to get Root Folder"

    all_clips = []

    # Get clips from root folder
    root_clips = root_folder.GetClipList()
    if root_clips:
        all_clips.extend(root_clips)

    # Get clips from subfolders
    folders = root_folder.GetSubFolderList()
    for folder in folders:
        if folder:
            folder_clips = folder.GetClipList()
            if folder_clips:
                all_clips.extend(folder_clips)

    # Find the source clip
    source_clip = None
    for clip in all_clips:
        if clip and clip.GetName() == clip_name:
            source_clip = clip
            break

    if not source_clip:
        return f"Error: Source clip '{clip_name}' not found in Media Pool"

    # Set the target folder for the subclip
    target_folder = root_folder
    if bin_name:
        target_folder = None
        # Check if it's the root folder
        if bin_name.lower() == "master" or bin_name == root_folder.GetName():
            target_folder = root_folder
        else:
            # Search for the bin in subfolders
            for folder in folders:
                if folder and folder.GetName() == bin_name:
                    target_folder = folder
                    break

            if not target_folder:
                return f"Error: Target bin '{bin_name}' not found in Media Pool"

    # Set the current folder to the target folder
    result = media_pool.SetCurrentFolder(target_folder)
    if not result:
        return f"Error: Failed to set current folder to '{target_folder.GetName()}'"

    # Generate a subclip name if not provided
    if not sub_clip_name:
        sub_clip_name = f"{clip_name}_subclip"

    # Set in/out points for the source clip
    result = source_clip.SetMarkInOut(start_frame, end_frame)
    if not result:
        return f"Error: Failed to set in/out points on clip '{clip_name}'"

    try:
        # Create the subclip using CreateSubClip
        sub_clip = media_pool.CreateSubClip(sub_clip_name, source_clip)

        if sub_clip:
            # Clear the mark in/out points from the source clip
            source_clip.ClearMarkInOut()

            return f"Successfully created subclip '{sub_clip_name}' from frames {start_frame} to {end_frame}"
        else:
            # Clear the mark in/out points if subclip creation failed
            source_clip.ClearMarkInOut()

            return f"Error: Failed to create subclip from '{clip_name}'"

    except Exception as e:
        # Always clear the mark in/out points in case of exceptions
        try:
            source_clip.ClearMarkInOut()
        except:
            pass

        return f"Error creating subclip: {str(e)}"
