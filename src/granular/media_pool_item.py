"""MediaPoolItem operations and metadata helpers."""

from src.granular.common import *  # noqa: F401,F403

resolve = ResolveProxy()

@mcp.tool()
def link_proxy_media(clip_name: str, proxy_file_path: str) -> str:
    """Link a proxy media file to a clip.
    
    Args:
        clip_name: Name of the clip to link proxy to
        proxy_file_path: Path to the proxy media file
    """
    pm, current_project = get_current_project()
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
    pm, current_project = get_current_project()
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
    pm, current_project = get_current_project()
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
    pm, current_project = get_current_project()
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
    pm, current_project = get_current_project()
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
def set_media_pool_clip_name(clip_id: str, new_name: str) -> Dict[str, Any]:
    """Rename a Media Pool clip.

    Args:
        clip_id: Unique ID of the clip.
        new_name: New clip name.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    missing = _requires_method(clip, "SetName", "20.2")
    if missing:
        return missing
    result = clip.SetName(new_name)
    return {"success": bool(result), "name": new_name}


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
def link_clip_full_resolution_media(clip_id: str, full_res_media_path: str) -> Dict[str, Any]:
    """Link full resolution media to a proxy clip.

    Args:
        clip_id: Unique ID of the clip.
        full_res_media_path: Absolute path to the full resolution media file.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    missing = _requires_method(clip, "LinkFullResolutionMedia", "20.0")
    if missing:
        return missing
    result = clip.LinkFullResolutionMedia(full_res_media_path)
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
def replace_media_pool_clip_preserve_sub_clip(clip_id: str, file_path: str) -> Dict[str, Any]:
    """Replace a clip's underlying media while preserving subclip extents.

    Args:
        clip_id: Unique ID of the clip to replace.
        file_path: Absolute path to the replacement media file.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    missing = _requires_method(clip, "ReplaceClipPreserveSubClip", "20.0")
    if missing:
        return missing
    result = clip.ReplaceClipPreserveSubClip(file_path)
    return {"success": bool(result)}


@mcp.tool()
def monitor_clip_growing_file(clip_id: str) -> Dict[str, Any]:
    """Monitor a growing media file for the given Media Pool clip."""
    _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip_by_id(mp.GetRootFolder(), clip_id)
    if not clip:
        return {"error": f"Clip {clip_id} not found"}
    missing = _requires_method(clip, "MonitorGrowingFile", "20.0")
    if missing:
        return missing
    result = clip.MonitorGrowingFile()
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
