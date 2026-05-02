"""Timeline resources and operations."""

from src.granular.common import *  # noqa: F401,F403

resolve = ResolveProxy()

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
    pm, current_project = get_current_project()
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


@mcp.tool()
def create_timeline(name: str) -> str:
    """Create a new timeline with the given name.
    
    Args:
        name: The name for the new timeline
    """
    resolve = get_resolve()
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
def set_current_timeline(name: str) -> str:
    """Switch to a timeline by name.
    
    Args:
        name: The name of the timeline to set as current
    """
    resolve = get_resolve()
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


@mcp.resource("resolve://timeline-clips")
def list_timeline_clips() -> List[Dict[str, Any]]:
    """List all clips in the current timeline."""
    pm, current_project = get_current_project()
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
def timeline_add_track(
    track_type: str,
    audio_type: Optional[str] = None,
    index: Optional[int] = None,
) -> Dict[str, Any]:
    """Add a new track to the timeline.

    Mirrors Timeline.AddTrack(trackType, {newTrackOptions}) per docs line 327.

    Args:
        track_type: 'video', 'audio', or 'subtitle'.
        audio_type: For audio tracks: 'mono', 'stereo', 'lrc', 'lcr', 'lrcs', 'lcrs',
            'quad', '5.0', '5.0film', '5.1', '5.1film', '7.0', '7.0film', '7.1',
            '7.1film', 'adaptive1' through 'adaptive36'. Defaults to 'mono' for audio
            tracks if omitted.
        index: 1-based track index where 1 <= index <= GetTrackCount(track_type) + 1.
            If omitted or out of bounds, the track is appended.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    options: Dict[str, Any] = {}
    if audio_type is not None:
        options["audioType"] = audio_type
    if index is not None:
        options["index"] = index
    if options:
        result = tl.AddTrack(track_type, options)
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
def timeline_get_voice_isolation_state(track_index: int) -> Dict[str, Any]:
    """Get voice isolation state for an audio track.

    Args:
        track_index: 1-based audio track index.
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    missing = _requires_method(tl, "GetVoiceIsolationState", "20.1")
    if missing:
        return missing
    state = tl.GetVoiceIsolationState(track_index)
    return {"state": state if state else {"isEnabled": False, "amount": 0}}


@mcp.tool()
def timeline_set_voice_isolation_state(track_index: int, state: Dict[str, Any]) -> Dict[str, Any]:
    """Set voice isolation state for an audio track.

    Args:
        track_index: 1-based audio track index.
        state: Dict with isEnabled (bool) and amount (0-100).
    """
    _, tl, err = _get_timeline()
    if err:
        return err
    missing = _requires_method(tl, "SetVoiceIsolationState", "20.1")
    if missing:
        return missing
    result = tl.SetVoiceIsolationState(track_index, state)
    return {"success": bool(result)}


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
def timeline_create_subtitles_from_audio(
    language: str = "auto",
    preset: str = "default",
    chars_per_line: Optional[int] = None,
    line_break: Optional[str] = None,
    gap: Optional[int] = None,
) -> Dict[str, Any]:
    """Create subtitles from audio in the current timeline.

    Mirrors Timeline.CreateSubtitlesFromAudio({autoCaptionSettings}) per docs lines 718-761.

    Args:
        language: 'auto', 'danish', 'dutch', 'english', 'french', 'german', 'italian',
            'japanese', 'korean', 'mandarin_simplified', 'mandarin_traditional',
            'norwegian', 'portuguese', 'russian', 'spanish', 'swedish'. Default: 'auto'.
        preset: 'default', 'teletext', 'netflix'. Default: 'default'.
        chars_per_line: Integer 1-60. Resolve default is 42 (or 16 for Netflix preset).
        line_break: 'single' or 'double'. Default: 'single' on Resolve side.
        gap: Integer 0-10. Default: 0 on Resolve side.
    """
    r = get_resolve()
    if r is None:
        return {"error": "Not connected to DaVinci Resolve"}
    _, tl, err = _get_timeline()
    if err:
        return err
    settings, settings_err = _build_subtitle_settings(
        r, language=language, preset=preset,
        chars_per_line=chars_per_line, line_break=line_break, gap=gap,
    )
    if settings_err:
        return settings_err
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
    result = tl.GetCurrentClipThumbnailImage()
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


@mcp.tool()
def create_timeline_from_clips(
    name: str,
    clip_ids: Optional[List[str]] = None,
    clip_infos: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create a new timeline from specified media pool clips.

    Args:
        name: Name for the new timeline.
        clip_ids: Simple form — list of MediaPoolItem unique IDs to append end-to-end.
        clip_infos: Positioned form — list of dicts with keys clip_id (or
            media_pool_item_id), start_frame, end_frame, record_frame.
            Mirrors MediaPool.CreateTimelineFromClips(name, [{clipInfo}, ...]).
        If both are None, uses the currently selected media pool clips.
    """
    _, mp, err = _get_mp()
    if err:
        return err
    if clip_infos is not None:
        if not isinstance(clip_infos, list) or not clip_infos:
            return {"error": "clip_infos must be a non-empty list"}
        root = mp.GetRootFolder()
        built = []
        for i, ci in enumerate(clip_infos):
            row, row_err = _build_create_clip_info_dict(root, ci, i)
            if row_err:
                return row_err
            built.append(row)
        tl = mp.CreateTimelineFromClips(name, built)
    elif clip_ids:
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
