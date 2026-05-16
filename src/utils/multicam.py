"""Helpers for source-safe multicam setup timelines.

Resolve's public scripting API does not expose native multicam clip creation.
These helpers build append plans for a stacked prep timeline that can be
converted to a native multicam clip in Resolve's UI.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple


FindClip = Callable[[Any, str], Any]


_SOURCE_TIMECODE_KEYS = (
    "Start TC",
    "Start Timecode",
    "Start Time Code",
    "Source Start TC",
    "Source Start Timecode",
)

_FPS_KEYS = ("FPS", "Frame Rate", "Video Frame Rate")
_FRAME_COUNT_KEYS = ("Frames", "Frame Count", "Video Frames")
_DURATION_KEYS = ("Duration", "Video Duration")


def _err(message: str) -> Dict[str, str]:
    return {"error": message}


def _frame_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.strip())
        if not match:
            return None
        value = match.group(0)
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def parse_frame_rate(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value) if float(value) > 0 else None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    fps = float(match.group(0))
    return fps if fps > 0 else None


def _nominal_timecode_rate(fps: float) -> int:
    if abs(fps - 23.976) < 0.02:
        return 24
    if abs(fps - 29.97) < 0.02:
        return 30
    if abs(fps - 47.952) < 0.05:
        return 48
    if abs(fps - 59.94) < 0.05:
        return 60
    return int(round(fps))


def timecode_to_frames(timecode: Any, fps: Any, *, drop_frame: Optional[bool] = None) -> Optional[int]:
    """Convert HH:MM:SS:FF timecode to a frame count.

    Semicolon timecode implies drop-frame. When drop_frame is not specified,
    29.97/59.94 colon timecode is treated as non-drop-frame.
    """
    rate = parse_frame_rate(fps)
    if rate is None:
        return None
    text = str(timecode or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})([:;])(\d{2})$", text)
    if not match:
        return None
    hours, minutes, seconds, sep, frames = match.groups()
    hh = int(hours)
    mm = int(minutes)
    ss = int(seconds)
    ff = int(frames)
    nominal = _nominal_timecode_rate(rate)
    if mm > 59 or ss > 59 or ff >= nominal:
        return None
    total = ((hh * 3600 + mm * 60 + ss) * nominal) + ff
    use_drop = (sep == ";") if drop_frame is None else bool(drop_frame)
    if use_drop and nominal in (30, 60):
        drop_frames = 2 if nominal == 30 else 4
        total_minutes = hh * 60 + mm
        total -= drop_frames * (total_minutes - total_minutes // 10)
    return total


def _get_clip_property_map(clip: Any) -> Dict[str, Any]:
    try:
        props = clip.GetClipProperty()
    except Exception:
        props = None
    return dict(props) if isinstance(props, dict) else {}


def _prop_from_map(props: Dict[str, Any], key: str) -> Any:
    if key in props:
        return props[key]
    key_norm = key.strip().lower()
    for existing, value in props.items():
        if str(existing).strip().lower() == key_norm:
            return value
    return None


def _clip_property(clip: Any, props: Dict[str, Any], keys: Tuple[str, ...]) -> Any:
    for key in keys:
        value = _prop_from_map(props, key)
        if value not in (None, ""):
            return value
    for key in keys:
        try:
            value = clip.GetClipProperty(key)
        except Exception:
            value = None
        if value not in (None, ""):
            return value
    return None


def _clip_name(clip: Any, fallback: str) -> str:
    try:
        name = clip.GetName()
    except Exception:
        name = None
    return str(name or fallback)


def _clip_duration_frames(clip: Any, props: Dict[str, Any], fps: Optional[float]) -> Optional[int]:
    frames = _frame_int(_clip_property(clip, props, _FRAME_COUNT_KEYS))
    if frames is not None and frames > 0:
        return frames
    try:
        duration = clip.GetDuration()
    except Exception:
        duration = None
    frames = _frame_int(duration)
    if frames is not None and frames > 0:
        return frames
    if duration and ":" in str(duration) and fps is not None:
        frames = timecode_to_frames(duration, fps)
        if frames is not None and frames > 0:
            return frames
    duration_value = _clip_property(clip, props, _DURATION_KEYS)
    frames = _frame_int(duration_value)
    if frames is not None and frames > 0 and ":" not in str(duration_value):
        return frames
    if fps is None:
        return None
    return timecode_to_frames(duration_value, fps)


def _angle_source_range(angle: Dict[str, Any], clip: Any, props: Dict[str, Any], fps: Optional[float], index: int):
    start = _frame_int(angle.get("start_frame", angle.get("startFrame", 0)))
    if start is None or start < 0:
        return None, None, _err(f"angles[{index}] start_frame must be a non-negative frame number")
    end = _frame_int(angle.get("end_frame", angle.get("endFrame")))
    if end is None:
        duration = _frame_int(angle.get("duration_frames", angle.get("durationFrames")))
        if duration is None:
            duration = _clip_duration_frames(clip, props, fps)
        if duration is not None:
            end = start + duration
    if end is None:
        return None, None, _err(
            f"angles[{index}] requires end_frame/duration_frames, or clip properties with Frames/Duration"
        )
    if end <= start:
        return None, None, _err(f"angles[{index}] end_frame must be greater than start_frame")
    return start, end, None


def _normalize_sync_mode(value: Any) -> Optional[str]:
    raw = str(value or "stack_start").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "none": "stack_start",
        "start": "stack_start",
        "stack": "stack_start",
        "stack_start": "stack_start",
        "common_start": "stack_start",
        "manual": "record_frame",
        "record": "record_frame",
        "record_frame": "record_frame",
        "record_frames": "record_frame",
        "timecode": "source_timecode",
        "source_timecode": "source_timecode",
        "source_tc": "source_timecode",
    }
    return aliases.get(raw)


def _normalize_audio_mode(value: Any, include_audio: bool) -> Optional[str]:
    if not include_audio:
        return "none"
    raw = str(value or "matching").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "none": "none",
        "off": "none",
        "matching": "matching",
        "match": "matching",
        "per_angle": "matching",
        "first": "first",
        "first_angle": "first",
        "scratch": "first",
    }
    return aliases.get(raw)


def _selected_record_frame(
    *,
    angle: Dict[str, Any],
    clip: Any,
    props: Dict[str, Any],
    fps: Optional[float],
    sync_mode: str,
    timeline_start_timecode: str,
    record_frame_start: int,
    index: int,
):
    offset = _frame_int(angle.get("record_offset", angle.get("recordOffset", 0)))
    if offset is None:
        return None, _err(f"angles[{index}] record_offset must be numeric")
    if sync_mode == "source_timecode":
        tc = (
            angle.get("source_timecode")
            or angle.get("sourceTimecode")
            or angle.get("start_timecode")
            or angle.get("startTimecode")
            or _clip_property(clip, props, _SOURCE_TIMECODE_KEYS)
        )
        if not tc:
            return None, _err(f"angles[{index}] has no source_timecode or readable clip Start TC")
        tc_frames = timecode_to_frames(tc, fps)
        start_frames = timecode_to_frames(timeline_start_timecode, fps)
        if tc_frames is None or start_frames is None:
            return None, _err(f"angles[{index}] could not parse source/timeline timecode at fps={fps!r}")
        return record_frame_start + (tc_frames - start_frames) + offset, None
    if sync_mode == "record_frame":
        manual = _frame_int(angle.get("record_frame", angle.get("recordFrame")))
        if manual is None:
            manual = record_frame_start
        return manual + offset, None
    return record_frame_start + offset, None


def build_multicam_setup_plan(root: Any, params: Dict[str, Any], find_clip: FindClip):
    """Build a stacked multicam setup plan from media pool clip IDs."""
    params = params or {}
    name = str(params.get("name") or "Multicam Setup")
    raw_angles = params.get("angles")
    if raw_angles is None:
        clip_ids = params.get("clip_ids") or params.get("clipIds")
        if not isinstance(clip_ids, list) or not clip_ids:
            return None, _err("setup_multicam_timeline requires angles or clip_ids")
        raw_angles = [{"clip_id": clip_id} for clip_id in clip_ids]
    if not isinstance(raw_angles, list) or not raw_angles:
        return None, _err("angles must be a non-empty list")

    sync_mode = _normalize_sync_mode(params.get("sync_mode", params.get("syncMode")))
    if not sync_mode:
        return None, _err("sync_mode must be stack_start, record_frame, or source_timecode")

    include_video = bool(params.get("include_video", params.get("includeVideo", True)))
    include_audio = bool(params.get("include_audio", params.get("includeAudio", False)))
    if not include_video and not include_audio:
        return None, _err("At least one of include_video or include_audio must be true")
    audio_mode = _normalize_audio_mode(params.get("audio_track_mode", params.get("audioTrackMode")), include_audio)
    if not audio_mode:
        return None, _err("audio_track_mode must be matching, first, or none")

    default_fps = parse_frame_rate(params.get("frame_rate", params.get("frameRate")))
    timeline_start_timecode = str(
        params.get("timeline_start_timecode")
        or params.get("timelineStartTimecode")
        or params.get("start_timecode")
        or params.get("startTimecode")
        or "01:00:00:00"
    )
    record_frame_start = _frame_int(params.get("record_frame_start", params.get("recordFrameStart", 0)))
    if record_frame_start is None:
        return None, _err("record_frame_start must be numeric")

    rows: List[Dict[str, Any]] = []
    angles: List[Dict[str, Any]] = []
    max_video_track = 0
    max_audio_track = 0
    allow_negative = bool(params.get("allow_negative_record_frame", params.get("allowNegativeRecordFrame", False)))
    record_frame_mode = params.get("record_frame_mode", params.get("recordFrameMode", "relative"))

    for index, raw in enumerate(raw_angles):
        if not isinstance(raw, dict):
            return None, _err(f"angles[{index}] must be an object")
        clip_id = raw.get("clip_id") or raw.get("media_pool_item_id") or raw.get("clipId")
        if not clip_id:
            return None, _err(f"angles[{index}] requires clip_id or media_pool_item_id")
        clip = find_clip(root, str(clip_id))
        if not clip:
            return None, _err(f"angles[{index}]: media pool clip not found: {clip_id}")
        props = _get_clip_property_map(clip)
        fps = parse_frame_rate(raw.get("frame_rate", raw.get("frameRate"))) or parse_frame_rate(
            _clip_property(clip, props, _FPS_KEYS)
        ) or default_fps
        source_start, source_end, range_err = _angle_source_range(raw, clip, props, fps, index)
        if range_err:
            return None, range_err
        record_frame, record_err = _selected_record_frame(
            angle=raw,
            clip=clip,
            props=props,
            fps=fps,
            sync_mode=sync_mode,
            timeline_start_timecode=timeline_start_timecode,
            record_frame_start=record_frame_start,
            index=index,
        )
        if record_err:
            return None, record_err
        if record_frame is None or (record_frame < 0 and not allow_negative):
            return None, _err(f"angles[{index}] resolved to a negative record frame")

        video_track = _frame_int(raw.get("track_index", raw.get("trackIndex", index + 1)))
        if video_track is None or video_track < 1:
            return None, _err(f"angles[{index}] track_index must be a positive integer")
        audio_track = _frame_int(raw.get("audio_track_index", raw.get("audioTrackIndex", video_track)))
        if audio_track is None or audio_track < 1:
            return None, _err(f"angles[{index}] audio_track_index must be a positive integer")
        angle_name = str(raw.get("angle_name") or raw.get("angleName") or _clip_name(clip, str(clip_id)))

        angle_summary = {
            "angle_index": index + 1,
            "angle_name": angle_name,
            "clip_id": str(clip_id),
            "clip_name": _clip_name(clip, str(clip_id)),
            "source_start": source_start,
            "source_end": source_end,
            "record_frame": record_frame,
            "video_track_index": video_track,
            "audio_track_index": audio_track if audio_mode != "none" else None,
            "fps": fps,
        }
        angles.append(angle_summary)
        common = {
            "clip_id": str(clip_id),
            "start_frame": source_start,
            "end_frame": source_end,
            "record_frame": record_frame,
            "record_frame_mode": raw.get("record_frame_mode", raw.get("recordFrameMode", record_frame_mode)),
            "angle_index": index + 1,
            "angle_name": angle_name,
        }
        if include_video:
            rows.append({**common, "track_index": video_track, "media_type": 1, "role": "video"})
            max_video_track = max(max_video_track, video_track)
        if audio_mode == "matching" or (audio_mode == "first" and index == 0):
            rows.append({**common, "track_index": audio_track, "media_type": 2, "role": "audio"})
            max_audio_track = max(max_audio_track, audio_track)

    return {
        "success": True,
        "name": name,
        "sync_mode": sync_mode,
        "start_timecode": params.get("start_timecode") or params.get("startTimecode"),
        "timeline_start_timecode": timeline_start_timecode,
        "include_video": include_video,
        "include_audio": include_audio,
        "audio_track_mode": audio_mode,
        "angles": angles,
        "append_rows": rows,
        "max_video_track": max_video_track,
        "max_audio_track": max_audio_track,
        "native_multicam_created": False,
        "native_multicam_api": False,
        "manual_reference": "DaVinci Resolve 20 Manual, Edit > Chapter 42, Multicam Editing",
        "next_step": (
            "Resolve's public scripting API does not expose native multicam clip creation. "
            "Use the created prep timeline directly, or in Resolve convert the timeline/"
            "compound clip to a multicam clip from the Media Pool context menu."
        ),
    }, None
