"""Media pool operations and MediaPool API tools."""

from src.granular.common import *  # noqa: F401,F403
from src.utils.multicam import build_multicam_setup_plan

resolve = ResolveProxy()


def _ensure_timeline_tracks_for_multicam(timeline, track_type: str, needed: int, audio_type: str = "stereo"):
    needed = max(0, int(needed or 0))
    added = 0
    try:
        current = int(timeline.GetTrackCount(track_type) or 0)
    except Exception as exc:
        return {"success": False, "error": f"GetTrackCount({track_type}) failed: {exc}"}
    while current < needed:
        try:
            if track_type == "audio":
                ok = timeline.AddTrack(track_type, {"audioType": audio_type})
            else:
                ok = timeline.AddTrack(track_type)
        except TypeError:
            ok = timeline.AddTrack(track_type)
        except Exception as exc:
            return {"success": False, "error": f"AddTrack({track_type}) failed: {exc}"}
        if not ok:
            return {"success": False, "error": f"AddTrack({track_type}) returned false at track {current + 1}"}
        current += 1
        added += 1
    return {"success": True, "existing": current - added, "added": added, "count": current}


def _set_multicam_track_names(timeline, plan):
    results = []
    for angle in plan.get("angles") or []:
        angle_name = angle.get("angle_name") or f"Angle {angle.get('angle_index')}"
        video_track = angle.get("video_track_index")
        if video_track:
            try:
                results.append({
                    "track_type": "video",
                    "track_index": video_track,
                    "name": angle_name,
                    "success": bool(timeline.SetTrackName("video", int(video_track), str(angle_name))),
                })
            except Exception as exc:
                results.append({"track_type": "video", "track_index": video_track, "success": False, "error": str(exc)})
        audio_track = angle.get("audio_track_index")
        if audio_track:
            try:
                results.append({
                    "track_type": "audio",
                    "track_index": audio_track,
                    "name": angle_name,
                    "success": bool(timeline.SetTrackName("audio", int(audio_track), str(angle_name))),
                })
            except Exception as exc:
                results.append({"track_type": "audio", "track_index": audio_track, "success": False, "error": str(exc)})
    return results


def _appended_item_summary(item):
    try:
        item_id = item.GetUniqueId()
    except Exception:
        item_id = None
    try:
        name = item.GetName()
    except Exception:
        name = None
    return {"timeline_item_id": item_id, "name": name}

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


@mcp.tool(annotations=EXTERNAL_WRITE_TOOL)
def import_media(
    paths: Optional[List[str]] = None,
    clip_infos: Optional[List[Dict[str, Any]]] = None,
    file_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Import media into the current project's media pool.

    Args:
        paths: Simple form — list of file or folder paths to import.
        clip_infos: Image-sequence form — list of dicts with keys FilePath
            (required), StartIndex, EndIndex. Mirrors
            MediaPool.ImportMedia([{clipInfo}, ...]). Each entry imports as
            one MediaPoolItem unless 'Show Individual Frames' is enabled.
            Example: [{"FilePath": "frame_%03d.dpx", "StartIndex": 1, "EndIndex": 100}]
        file_path: Single-path convenience for backward compatibility.
    """
    project, mp, err = _get_mp()
    if err:
        return err
    if clip_infos is not None:
        if not isinstance(clip_infos, list) or not clip_infos:
            return {"error": "clip_infos must be a non-empty list"}
        for i, ci in enumerate(clip_infos):
            if not isinstance(ci, dict):
                return {"error": f"clip_infos[{i}] must be an object"}
            if not ci.get("FilePath"):
                return {"error": f"clip_infos[{i}] requires FilePath"}
        result = mp.ImportMedia(clip_infos)
    else:
        path_list = paths if paths is not None else ([file_path] if file_path else None)
        if not path_list:
            return {"error": "Provide paths (list), clip_infos (image sequences), or file_path"}
        result = mp.ImportMedia(path_list)
    if not result:
        return {"success": False, "error": "Failed to import media"}
    return {
        "success": True,
        "imported": len(result),
        "clips": [{"name": c.GetName(), "id": c.GetUniqueId()} for c in result],
    }


@mcp.tool()
def append_to_timeline(
    clip_ids: Optional[List[str]] = None,
    clip_infos: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Append clips to the current timeline.

    Mirrors MediaPool.AppendToTimeline per docs lines 219-221. Two forms:

    Args:
        clip_ids: Simple form — list of MediaPoolItem unique IDs to append in order.
        clip_infos: Positioned form — list of dicts with keys clip_id (or
            media_pool_item_id), start_frame, end_frame, record_frame, track_index,
            and optional media_type (1=video only, 2=audio only). record_frame is
            relative to the current timeline start frame by default; pass
            record_frame_mode="absolute" for raw Resolve recordFrame values.
            Returns timeline_item_id per appended item.
    """
    project, mp, err = _get_mp()
    if err:
        return err
    if clip_infos is not None:
        if not isinstance(clip_infos, list) or not clip_infos:
            return {"error": "clip_infos must be a non-empty list"}
        root = mp.GetRootFolder()
        current_timeline = project.GetCurrentTimeline() if project else None
        timeline_start = _timeline_start_frame(current_timeline)
        built = []
        for i, ci in enumerate(clip_infos):
            row, row_err = _build_append_clip_info_dict(root, ci, i, timeline_start)
            if row_err:
                return row_err
            built.append(row)
        result = mp.AppendToTimeline(built)
        if not result:
            return {"success": False, "error": "Failed to append clip_infos to timeline"}
        items_out = []
        for i, item in enumerate(result):
            if not item:
                return {"success": False, "error": f"Missing timeline item at index {i}"}
            try:
                item_id = item.GetUniqueId()
                name = item.GetName()
            except Exception as exc:
                return {"success": False, "error": f"Invalid timeline item at index {i}: {exc}"}
            if not item_id:
                return {"success": False, "error": f"Missing timeline item id at index {i}"}
            items_out.append({"timeline_item_id": item_id, "name": name})
        return {"success": True, "count": len(items_out), "items": items_out}
    if not clip_ids:
        return {"error": "Provide clip_ids (simple) or clip_infos (positioned)"}
    root = mp.GetRootFolder()
    clips = [_find_clip_by_id(root, cid) for cid in clip_ids]
    clips = [c for c in clips if c]
    if not clips:
        return {"error": "No valid clips found"}
    result = mp.AppendToTimeline(clips)
    return {"success": True, "count": len(result) if result else 0}


@mcp.tool()
def setup_multicam_timeline(
    name: str = "Multicam Setup",
    clip_ids: Optional[List[str]] = None,
    angles: Optional[List[Dict[str, Any]]] = None,
    sync_mode: str = "stack_start",
    include_audio: bool = False,
    audio_track_mode: str = "matching",
    start_timecode: Optional[str] = None,
    timeline_start_timecode: Optional[str] = None,
    record_frame_start: int = 0,
    frame_rate: Optional[Any] = None,
    audio_type: str = "stereo",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Create a stacked multicam prep timeline from Media Pool clips.

    This does not create a native Resolve multicam clip because the public
    scripting API does not expose native multicam creation. It creates a prep
    timeline with one angle per video track and optional matching audio tracks.

    Args:
        name: Name for the setup timeline.
        clip_ids: Simple list of MediaPoolItem unique IDs, one per angle.
        angles: Detailed angle rows with clip_id, optional angle_name,
            start_frame/end_frame, record_frame, source_timecode, track_index.
        sync_mode: 'stack_start', 'record_frame', or 'source_timecode'.
        include_audio: Also append audio-only rows.
        audio_track_mode: 'matching' for per-angle audio tracks, or 'first'.
        start_timecode: Optional timeline start timecode to set after creation.
        timeline_start_timecode: Base timecode for source_timecode sync math.
        record_frame_start: Timeline-relative start frame for stack_start mode.
        frame_rate: Fallback frame rate for duration/timecode parsing.
        audio_type: Resolve audio track type when tracks must be added.
        dry_run: Return the plan without creating a timeline.
    """
    project, mp, err = _get_mp()
    if err:
        return err
    root = mp.GetRootFolder()
    params = {
        "name": name,
        "clip_ids": clip_ids,
        "angles": angles,
        "sync_mode": sync_mode,
        "include_audio": include_audio,
        "audio_track_mode": audio_track_mode,
        "start_timecode": start_timecode,
        "timeline_start_timecode": timeline_start_timecode,
        "record_frame_start": record_frame_start,
        "frame_rate": frame_rate,
        "audio_type": audio_type,
        "dry_run": dry_run,
    }
    plan, plan_err = build_multicam_setup_plan(root, params, _find_clip_by_id)
    if plan_err:
        return plan_err
    if dry_run:
        return {
            **plan,
            "dry_run": True,
            "would_create_timeline": True,
            "would_append": len(plan.get("append_rows") or []),
        }

    timeline = mp.CreateEmptyTimeline(plan["name"])
    if not timeline:
        return {"error": f"Failed to create multicam setup timeline: {plan['name']}"}
    try:
        project.SetCurrentTimeline(timeline)
    except Exception:
        pass
    if plan.get("start_timecode"):
        try:
            timeline.SetStartTimecode(plan["start_timecode"])
        except Exception:
            pass

    video_tracks = _ensure_timeline_tracks_for_multicam(timeline, "video", plan.get("max_video_track", 0))
    if not video_tracks.get("success"):
        return video_tracks
    audio_tracks = _ensure_timeline_tracks_for_multicam(
        timeline,
        "audio",
        plan.get("max_audio_track", 0),
        audio_type=audio_type,
    )
    if not audio_tracks.get("success"):
        return audio_tracks
    track_names = _set_multicam_track_names(timeline, plan)

    timeline_start = _timeline_start_frame(timeline)
    append_rows = plan.get("append_rows") or []
    append_infos = []
    for index, row in enumerate(append_rows):
        clip_info, clip_err = _build_append_clip_info_dict(root, row, index, timeline_start)
        if clip_err:
            return clip_err
        append_infos.append(clip_info)
    appended = mp.AppendToTimeline(append_infos)
    if not appended:
        return {"error": "AppendToTimeline returned no items for multicam setup"}

    items = []
    for index, item in enumerate(appended):
        summary = _appended_item_summary(item)
        summary["setup_row"] = append_rows[index]
        items.append(summary)
    return {
        **plan,
        "dry_run": False,
        "timeline_name": timeline.GetName(),
        "timeline_id": timeline.GetUniqueId(),
        "items": items,
        "track_setup": {"video": video_tracks, "audio": audio_tracks, "names": track_names},
    }


@mcp.tool()
def auto_sync_audio(
    clip_ids: List[str],
    sync_mode: Optional[str] = None,
    channel_number: Optional[Any] = None,
    retain_embedded_audio: Optional[bool] = None,
    retain_video_metadata: Optional[bool] = None,
) -> Dict[str, Any]:
    """Sync audio across multiple clips.

    Mirrors MediaPool.AutoSyncAudio([items], {audioSyncSettings}) per docs lines 600-614.

    Args:
        clip_ids: List of MediaPoolItem unique IDs to sync.
        sync_mode: 'waveform' or 'timecode' (default on Resolve side: 'timecode').
        channel_number: int >= 1 for channel offset, or 'automatic' (-1) / 'mix' (-2).
            Only used in waveform mode.
        retain_embedded_audio: keep clip's embedded audio after sync.
        retain_video_metadata: keep video clip's metadata after sync.
    """
    r = get_resolve()
    if r is None:
        return {"error": "Not connected to DaVinci Resolve"}
    _, mp, err = _get_mp()
    if err:
        return err
    if not clip_ids:
        return {"error": "clip_ids must be a non-empty list"}
    root = mp.GetRootFolder()
    clips = [_find_clip_by_id(root, cid) for cid in clip_ids]
    clips = [c for c in clips if c]
    if not clips:
        return {"error": "No valid clips found"}
    settings, settings_err = _build_audio_sync_settings(
        r, sync_mode=sync_mode, channel_number=channel_number,
        retain_embedded_audio=retain_embedded_audio,
        retain_video_metadata=retain_video_metadata,
    )
    if settings_err:
        return settings_err
    return {"success": bool(mp.AutoSyncAudio(clips, settings))}


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
    if not items or item_index < 0 or item_index >= len(items):  # reject negatives (EX5)
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
                logger.debug("Could not read selected clip identity", exc_info=True)
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
