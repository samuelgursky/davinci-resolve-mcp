#!/usr/bin/env python3
"""Live timeline edit kernel boundary probe.

Creates a disposable Resolve project with synthetic media, probes the deepest
timeline-editing API surfaces this project knows about, writes JSON/Markdown
evidence reports, and deletes the project unless --keep-open is provided.

Run with Python 3.10-3.12 against a running Resolve Studio instance:

  python3.11 tests/live_duplicate_clips_validation.py --output-dir /tmp/timeline-kernel-probe
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
import time
import types
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.utils.timeline_kernel_probe import (
    ProbeRecorder,
    ordered_unique,
    parse_api_class_methods,
    parse_timeline_item_property_keys,
    render_markdown_report,
    utc_timestamp,
    values_match,
)

PROPERTY_CANDIDATES: Dict[str, Any] = {
    "Pan": 0.33,
    "Tilt": -0.25,
    "ZoomX": 1.15,
    "ZoomY": 1.1,
    "ZoomGang": False,
    "RotationAngle": 8.0,
    "AnchorPointX": 0.05,
    "AnchorPointY": -0.05,
    "Pitch": 0.1,
    "Yaw": -0.1,
    "FlipX": True,
    "FlipY": False,
    "CropLeft": 2.0,
    "CropRight": 1.0,
    "CropTop": 1.0,
    "CropBottom": 2.0,
    "CropSoftness": 4.0,
    "CropRetain": True,
    "DynamicZoomEnable": True,
    "DynamicZoomMode": 1,
    "DynamicZoomEase": 2,
    "CompositeMode": 1,
    "Opacity": 72.0,
    "Distortion": 0.1,
    "Speed": 100.0,
    "RetimeProcess": 1,
    "MotionEstimation": 1,
    "Scaling": 2,
    "ResizeFilter": 3,
    "StabilizationEnable": True,
    "StabilizationMethod": 1,
    "StabilizationStrength": 0.75,
    "Volume": -6.0,
    "AudioSyncOffsetIsManual": False,
    "AudioSyncOffset": 0,
    "EQEnable": False,
    "NormalizeEnable": False,
    "NormalizeLevel": -12.0,
}

EXTRA_TIMELINE_METHODS = [
    "GetItemsInTrack",
    "GetCurrentVideoItem",
    "GetCurrentTimecode",
    "SetCurrentTimecode",
]

EXTRA_TIMELINE_ITEM_METHODS = [
    "GetType",
    "GetMediaType",
    "AddKeyframe",
    "GetKeyframeCount",
    "GetKeyframeAtIndex",
    "GetPropertyAtKeyframeIndex",
    "SetKeyframeInterpolation",
    "GetIsColorOutputCacheEnabled",
    "SetColorOutputCache",
    "GetIsFusionOutputCacheEnabled",
    "SetFusionOutputCache",
    "GetVoiceIsolationState",
    "SetVoiceIsolationState",
]


def _install_mcp_stubs() -> None:
    """Allow importing src.server when MCP deps are absent from Python 3.11."""

    class FastMCP:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self, *args, **kwargs):
            def decorate(func):
                return func

            return decorate

        def resource(self, *args, **kwargs):
            def decorate(func):
                return func

            return decorate

    def stdio_server(*args, **kwargs):
        raise RuntimeError("stdio_server is not used by the live timeline kernel probe")

    anyio = types.ModuleType("anyio")
    anyio.run = lambda func: func()

    mcp = types.ModuleType("mcp")
    server = types.ModuleType("mcp.server")
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    stdio = types.ModuleType("mcp.server.stdio")

    fastmcp.FastMCP = FastMCP
    stdio.stdio_server = stdio_server

    sys.modules.setdefault("anyio", anyio)
    sys.modules.setdefault("mcp", mcp)
    sys.modules.setdefault("mcp.server", server)
    sys.modules.setdefault("mcp.server.fastmcp", fastmcp)
    sys.modules.setdefault("mcp.server.stdio", stdio)


def _require_success(label: str, result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise AssertionError(f"{label}: expected dict, got {result!r}")
    if result.get("error"):
        raise AssertionError(f"{label}: {result['error']}")
    if "success" in result and result["success"] is not True:
        raise AssertionError(f"{label}: expected success=True, got {result!r}")
    return result


def _frame_int(value) -> int:
    return int(round(float(value)))


def _source_start(item) -> int:
    if hasattr(item, "GetSourceStartFrame"):
        try:
            value = item.GetSourceStartFrame()
            if value is not None:
                return _frame_int(value)
        except Exception:
            pass
    return _frame_int(item.GetLeftOffset())


def _make_synthetic_media(work_dir: Path) -> Path:
    media_path = work_dir / "timeline_kernel_probe_source.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24:duration=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=5",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-y",
            str(media_path),
        ],
        check=True,
    )
    return media_path


def _safe_call(func, *args):
    try:
        return func(*args), None
    except Exception as exc:
        return None, exc


def _safe_item_id(item) -> Optional[str]:
    if not item:
        return None
    try:
        return str(item.GetUniqueId())
    except Exception:
        return None


def _safe_timeline_id(timeline) -> Optional[str]:
    if not timeline:
        return None
    try:
        return str(timeline.GetUniqueId())
    except Exception:
        return None


def _ensure_current_timeline(
    recorder: ProbeRecorder,
    project,
    timeline,
    label: str,
    *,
    required: bool = False,
) -> bool:
    """Best-effort current timeline guard for Resolve bridge versions with flaky setters."""
    if not project or not timeline:
        if required:
            raise AssertionError("No project or timeline available to set current timeline")
        recorder.record(
            "runtime.current_timeline",
            label,
            "unsupported",
            details={"reason": "No project or timeline available"},
        )
        return False

    target_id = _safe_timeline_id(timeline)
    get_current = getattr(project, "GetCurrentTimeline", None)
    if callable(get_current):
        current, current_exc = _safe_call(get_current)
        if current:
            current_id = _safe_timeline_id(current)
            if not target_id or not current_id or current_id == target_id:
                return True
        elif current_exc:
            recorder.record(
                "runtime.current_timeline",
                f"{label}.get_current",
                "error",
                details={"exception": repr(current_exc)},
            )

    setter = getattr(project, "SetCurrentTimeline", None)
    if callable(setter):
        ok, set_exc = _safe_call(setter, timeline)
        if ok:
            return True
        recorder.record(
            "runtime.current_timeline",
            f"{label}.set_current",
            "partially_supported",
            details={"returned": ok, "exception": repr(set_exc) if set_exc else None},
        )
    else:
        recorder.record(
            "runtime.current_timeline",
            f"{label}.set_current",
            "version_or_page_dependent",
            details={"reason": "Project.SetCurrentTimeline is not callable in this Resolve bridge state"},
        )

    if callable(get_current):
        current, _ = _safe_call(get_current)
        if current:
            current_id = _safe_timeline_id(current)
            if not target_id or not current_id or current_id == target_id:
                return True

    if required:
        raise AssertionError("Failed to create or set current timeline")
    return False


def _record_method_availability(
    recorder: ProbeRecorder,
    obj,
    category: str,
    class_name: str,
    method_names: Iterable[str],
) -> None:
    for method_name in ordered_unique(method_names):
        recorder.record(
            category,
            f"{class_name}.{method_name}",
            "supported" if callable(getattr(obj, method_name, None)) else "unsupported",
        )


def _record_tool_result(
    recorder: ProbeRecorder,
    category: str,
    name: str,
    result: Dict[str, Any],
    *,
    expected_boundary: bool = False,
) -> None:
    if not isinstance(result, dict):
        recorder.record(category, name, "error", details={"reason": "non-dict result", "result": repr(result)})
        return
    if result.get("error"):
        recorder.record(
            category,
            name,
            "unsupported" if expected_boundary else "error",
            details={"reason": result.get("error"), "expected_boundary": expected_boundary},
            evidence=result,
        )
        return
    if "success" in result and result["success"] is not True:
        recorder.record(
            category,
            name,
            "partially_supported",
            details={"reason": "success flag was false"},
            evidence=result,
        )
        return
    if result.get("results") and any(row.get("success") is False for row in result["results"] if isinstance(row, dict)):
        recorder.record(category, name, "partially_supported", evidence=result)
        return
    recorder.record(category, name, "supported", evidence=result)


def _probe_property(recorder: ProbeRecorder, item, item_label: str, key: str) -> None:
    get_property = getattr(item, "GetProperty", None)
    set_property = getattr(item, "SetProperty", None)
    if not callable(get_property):
        recorder.record(f"properties.{item_label}", key, "unsupported", details={"reason": "GetProperty missing"})
        return

    original, read_error = _safe_call(get_property, key)
    read_available = read_error is None and original is not None
    candidate = PROPERTY_CANDIDATES.get(key, original if original is not None else 1)

    if not callable(set_property):
        status = "read_only" if read_available else "unsupported"
        recorder.record(
            f"properties.{item_label}",
            key,
            status,
            details={"read": original, "reason": "SetProperty missing" if read_available else "property unavailable"},
        )
        return

    write_result, write_error = _safe_call(set_property, key, candidate)
    readback, readback_error = _safe_call(get_property, key)
    restore_result = None
    if read_available and write_result:
        restore_result, _ = _safe_call(set_property, key, original)

    details = {
        "read": original,
        "write": bool(write_result) if write_error is None else False,
        "write_error": repr(write_error) if write_error else None,
        "readback": readback,
        "readback_error": repr(readback_error) if readback_error else None,
        "restore": bool(restore_result) if restore_result is not None else None,
    }

    if read_error is not None:
        status = "error"
        details["read_error"] = repr(read_error)
    elif write_error is not None:
        status = "partially_supported" if read_available else "unsupported"
    elif not write_result:
        status = "partially_supported" if read_available else "unsupported"
        details["reason"] = "SetProperty returned false"
    elif readback is None:
        status = "write_only_unverifiable"
    elif values_match(readback, candidate):
        status = "supported"
    else:
        status = "partially_supported"
        details["reason"] = "SetProperty returned true but readback did not match"

    recorder.record(f"properties.{item_label}", key, status, details=details)


def _probe_keyframe(recorder: ProbeRecorder, item, item_label: str, key: str) -> None:
    add_keyframe = getattr(item, "AddKeyframe", None)
    get_count = getattr(item, "GetKeyframeCount", None)
    get_at_index = getattr(item, "GetKeyframeAtIndex", None)
    get_value = getattr(item, "GetPropertyAtKeyframeIndex", None)
    if not callable(add_keyframe):
        recorder.record(f"keyframes.{item_label}", key, "unsupported", details={"reason": "AddKeyframe missing"})
        return

    before = None
    if callable(get_count):
        before, _ = _safe_call(get_count, key)
    value = PROPERTY_CANDIDATES.get(key, 1)
    added, add_error = _safe_call(add_keyframe, key, 0, value)
    after = None
    if callable(get_count):
        after, _ = _safe_call(get_count, key)

    evidence: List[Dict[str, Any]] = []
    if callable(get_at_index) and callable(get_value) and after:
        for index in range(int(after)):
            keyframe, keyframe_error = _safe_call(get_at_index, key, index)
            prop_value, value_error = _safe_call(get_value, key, index)
            evidence.append(
                {
                    "index": index,
                    "keyframe": keyframe,
                    "keyframe_error": repr(keyframe_error) if keyframe_error else None,
                    "value": prop_value,
                    "value_error": repr(value_error) if value_error else None,
                }
            )

    details = {
        "before": before,
        "added": bool(added) if add_error is None else False,
        "add_error": repr(add_error) if add_error else None,
        "after": after,
        "read_methods": {
            "GetKeyframeCount": callable(get_count),
            "GetKeyframeAtIndex": callable(get_at_index),
            "GetPropertyAtKeyframeIndex": callable(get_value),
        },
    }
    if add_error:
        status = "error"
    elif added and after is not None and int(after) > int(before or 0):
        status = "supported"
    elif added:
        status = "write_only_unverifiable"
    elif before is not None:
        status = "partially_supported"
        details["reason"] = "AddKeyframe returned false"
    else:
        status = "unsupported"
        details["reason"] = "AddKeyframe returned false and keyframe readback is unavailable"
    recorder.record(f"keyframes.{item_label}", key, status, details=details, evidence=evidence)


def _probe_markers_flags_color_enabled(recorder: ProbeRecorder, item, item_label: str) -> None:
    marker_frame = 9
    add_marker = getattr(item, "AddMarker", None)
    if callable(add_marker):
        added, exc = _safe_call(add_marker, marker_frame, "Green", "Probe marker", "Timeline kernel probe", 1, "kernel-probe")
        markers, markers_exc = _safe_call(item.GetMarkers) if callable(getattr(item, "GetMarkers", None)) else ({}, None)
        custom, custom_exc = (
            _safe_call(item.GetMarkerCustomData, marker_frame)
            if callable(getattr(item, "GetMarkerCustomData", None))
            else (None, None)
        )
        deleted, delete_exc = (
            _safe_call(item.DeleteMarkerByCustomData, "kernel-probe")
            if callable(getattr(item, "DeleteMarkerByCustomData", None))
            else (None, None)
        )
        status = "supported" if added and markers_exc is None else "partially_supported"
        recorder.record(
            f"metadata.{item_label}",
            "markers",
            status,
            details={
                "added": bool(added),
                "add_error": repr(exc) if exc else None,
                "marker_count": len(markers or {}) if isinstance(markers, dict) else None,
                "custom_data": custom,
                "custom_error": repr(custom_exc) if custom_exc else None,
                "deleted": bool(deleted) if deleted is not None else None,
                "delete_error": repr(delete_exc) if delete_exc else None,
            },
        )
    else:
        recorder.record(f"metadata.{item_label}", "markers", "unsupported", details={"reason": "AddMarker missing"})

    if callable(getattr(item, "AddFlag", None)):
        added, exc = _safe_call(item.AddFlag, "Green")
        flags, flags_exc = _safe_call(item.GetFlagList) if callable(getattr(item, "GetFlagList", None)) else ([], None)
        cleared, clear_exc = _safe_call(item.ClearFlags, "Green") if callable(getattr(item, "ClearFlags", None)) else (None, None)
        recorder.record(
            f"metadata.{item_label}",
            "flags",
            "supported" if added and flags_exc is None else "partially_supported",
            details={
                "added": bool(added),
                "add_error": repr(exc) if exc else None,
                "flags": flags,
                "flags_error": repr(flags_exc) if flags_exc else None,
                "cleared": bool(cleared) if cleared is not None else None,
                "clear_error": repr(clear_exc) if clear_exc else None,
            },
        )
    else:
        recorder.record(f"metadata.{item_label}", "flags", "unsupported", details={"reason": "AddFlag missing"})

    if callable(getattr(item, "SetClipColor", None)):
        original, _ = _safe_call(item.GetClipColor) if callable(getattr(item, "GetClipColor", None)) else (None, None)
        set_result, exc = _safe_call(item.SetClipColor, "Teal")
        readback, read_exc = _safe_call(item.GetClipColor) if callable(getattr(item, "GetClipColor", None)) else (None, None)
        clear_result, clear_exc = _safe_call(item.ClearClipColor) if callable(getattr(item, "ClearClipColor", None)) else (None, None)
        if original:
            _safe_call(item.SetClipColor, original)
        recorder.record(
            f"metadata.{item_label}",
            "clip_color",
            "supported" if set_result and readback == "Teal" else "partially_supported",
            details={
                "read": original,
                "write": bool(set_result),
                "write_error": repr(exc) if exc else None,
                "readback": readback,
                "readback_error": repr(read_exc) if read_exc else None,
                "clear": bool(clear_result) if clear_result is not None else None,
                "clear_error": repr(clear_exc) if clear_exc else None,
            },
        )
    else:
        recorder.record(f"metadata.{item_label}", "clip_color", "unsupported", details={"reason": "SetClipColor missing"})

    if callable(getattr(item, "SetClipEnabled", None)):
        original, _ = _safe_call(item.GetClipEnabled) if callable(getattr(item, "GetClipEnabled", None)) else (None, None)
        set_result, exc = _safe_call(item.SetClipEnabled, False)
        readback, read_exc = _safe_call(item.GetClipEnabled) if callable(getattr(item, "GetClipEnabled", None)) else (None, None)
        if original is not None:
            _safe_call(item.SetClipEnabled, bool(original))
        recorder.record(
            f"metadata.{item_label}",
            "enabled_state",
            "supported" if set_result and readback is False else "partially_supported",
            details={
                "read": original,
                "write": bool(set_result),
                "write_error": repr(exc) if exc else None,
                "readback": readback,
                "readback_error": repr(read_exc) if read_exc else None,
            },
        )
    else:
        recorder.record(f"metadata.{item_label}", "enabled_state", "unsupported", details={"reason": "SetClipEnabled missing"})


def _probe_cache_voice_takes_fusion_grade(
    recorder: ProbeRecorder,
    item,
    duplicate_item,
    media_pool_item,
    item_label: str,
    output_dir: Path,
) -> None:
    for cache_name, getter_name, setter_name, value in (
        ("color_cache", "GetIsColorOutputCacheEnabled", "SetColorOutputCache", "On"),
        ("fusion_cache", "GetIsFusionOutputCacheEnabled", "SetFusionOutputCache", "Auto"),
    ):
        getter = getattr(item, getter_name, None)
        setter = getattr(item, setter_name, None)
        if not callable(getter) or not callable(setter):
            recorder.record(f"advanced.{item_label}", cache_name, "unsupported", details={"reason": "cache API missing"})
            continue
        original, read_exc = _safe_call(getter)
        set_result, set_exc = _safe_call(setter, value)
        readback, readback_exc = _safe_call(getter)
        if original is not None:
            _safe_call(setter, original)
        recorder.record(
            f"advanced.{item_label}",
            cache_name,
            "supported" if set_result and readback is not None else "partially_supported",
            details={
                "read": original,
                "read_error": repr(read_exc) if read_exc else None,
                "write": bool(set_result),
                "write_error": repr(set_exc) if set_exc else None,
                "readback": readback,
                "readback_error": repr(readback_exc) if readback_exc else None,
            },
        )

    if callable(getattr(item, "GetVoiceIsolationState", None)) and callable(getattr(item, "SetVoiceIsolationState", None)):
        original, read_exc = _safe_call(item.GetVoiceIsolationState)
        set_result, set_exc = _safe_call(item.SetVoiceIsolationState, {"isEnabled": True, "amount": 25})
        readback, readback_exc = _safe_call(item.GetVoiceIsolationState)
        if original:
            _safe_call(item.SetVoiceIsolationState, original)
        recorder.record(
            f"advanced.{item_label}",
            "item_voice_isolation",
            "supported" if set_result and readback else "partially_supported",
            details={
                "read": original,
                "read_error": repr(read_exc) if read_exc else None,
                "write": bool(set_result),
                "write_error": repr(set_exc) if set_exc else None,
                "readback": readback,
                "readback_error": repr(readback_exc) if readback_exc else None,
            },
        )
    else:
        recorder.record(
            f"advanced.{item_label}",
            "item_voice_isolation",
            "unsupported",
            details={"reason": "item voice isolation API missing"},
        )

    if callable(getattr(item, "AddTake", None)):
        added, add_exc = _safe_call(item.AddTake, media_pool_item, 24, 71)
        count, count_exc = _safe_call(item.GetTakesCount) if callable(getattr(item, "GetTakesCount", None)) else (None, None)
        take, take_exc = (
            _safe_call(item.GetTakeByIndex, int(count or 1))
            if callable(getattr(item, "GetTakeByIndex", None)) and count
            else (None, None)
        )
        selected, select_exc = (
            _safe_call(item.SelectTakeByIndex, int(count))
            if callable(getattr(item, "SelectTakeByIndex", None)) and count
            else (None, None)
        )
        deleted, delete_exc = (
            _safe_call(item.DeleteTakeByIndex, int(count))
            if callable(getattr(item, "DeleteTakeByIndex", None)) and count
            else (None, None)
        )
        recorder.record(
            f"advanced.{item_label}",
            "takes",
            "supported" if added and count else "partially_supported",
            details={
                "added": bool(added),
                "add_error": repr(add_exc) if add_exc else None,
                "count": count,
                "count_error": repr(count_exc) if count_exc else None,
                "take_read": bool(take),
                "take_error": repr(take_exc) if take_exc else None,
                "selected": bool(selected) if selected is not None else None,
                "select_error": repr(select_exc) if select_exc else None,
                "deleted": bool(deleted) if deleted is not None else None,
                "delete_error": repr(delete_exc) if delete_exc else None,
            },
        )
    else:
        recorder.record(f"advanced.{item_label}", "takes", "unsupported", details={"reason": "AddTake missing"})

    if callable(getattr(item, "AddFusionComp", None)):
        comp, add_exc = _safe_call(item.AddFusionComp)
        count, count_exc = _safe_call(item.GetFusionCompCount) if callable(getattr(item, "GetFusionCompCount", None)) else (None, None)
        names, names_exc = (
            _safe_call(item.GetFusionCompNameList)
            if callable(getattr(item, "GetFusionCompNameList", None))
            else (None, None)
        )
        export_path = output_dir / f"{item_label}_fusion_comp.setting"
        exported, export_exc = (
            _safe_call(item.ExportFusionComp, str(export_path), 1)
            if callable(getattr(item, "ExportFusionComp", None)) and count
            else (None, None)
        )
        recorder.record(
            f"advanced.{item_label}",
            "fusion_comps",
            "supported" if comp and count else "partially_supported",
            details={
                "added": bool(comp),
                "add_error": repr(add_exc) if add_exc else None,
                "count": count,
                "count_error": repr(count_exc) if count_exc else None,
                "names": names,
                "names_error": repr(names_exc) if names_exc else None,
                "exported": bool(exported) if exported is not None else None,
                "export_error": repr(export_exc) if export_exc else None,
                "export_path": str(export_path) if exported else None,
            },
        )
    else:
        recorder.record(f"advanced.{item_label}", "fusion_comps", "unsupported", details={"reason": "AddFusionComp missing"})

    if callable(getattr(item, "CopyGrades", None)) and duplicate_item:
        copied, copy_exc = _safe_call(item.CopyGrades, [duplicate_item])
        recorder.record(
            f"advanced.{item_label}",
            "copy_grades",
            "supported" if copied else "partially_supported",
            details={"copied": bool(copied), "copy_error": repr(copy_exc) if copy_exc else None},
        )
    else:
        recorder.record(f"advanced.{item_label}", "copy_grades", "unsupported", details={"reason": "CopyGrades missing"})


def _probe_timeline_operations(recorder: ProbeRecorder, server, timeline, source_id: str, source_duration: int) -> Optional[str]:
    duplicate_ids: List[str] = []

    def duplicate(name: str, params: Dict[str, Any]) -> Optional[str]:
        payload = dict(params)
        payload.setdefault("clip_ids", [source_id])
        result = server.timeline("duplicate_clips", payload)
        _record_tool_result(recorder, "operations.duplicate", name, result)
        try:
            item_id = result["results"][0]["timeline_item_id"]
        except Exception:
            return None
        if item_id:
            duplicate_ids.append(item_id)
        return item_id

    duplicate("same_time_cross_track", {"placement": "same_time", "target_track_index": 2})
    duplicate("offset", {"record_frame_offset": 180, "target_track_index": 2})
    duplicate("track_above", {"placement": "track_above"})
    duplicate("after_source", {"placement": "after_source"})
    duplicate("next_gap", {"placement": "next_gap", "target_track_index": 2})
    server.timeline_markers("set_current_timecode", {"timecode": "00:00:28:00"})
    duplicate("at_playhead", {"placement": "at_playhead", "target_track_index": 2})
    duplicate("include_linked_audio", {"record_frame": 780, "target_track_index": 2, "include_linked": True})

    copy_alias = server.timeline("copy_clips", {"clip_ids": [source_id], "target_track_index": 2, "record_frame": 840})
    _record_tool_result(recorder, "operations.duplicate", "copy_clips_alias", copy_alias)

    selected = server.timeline("duplicate_clips", {"selected": True, "target_track_index": 2, "record_frame": 880})
    if isinstance(selected, dict) and selected.get("error"):
        recorder.record(
            "operations.duplicate",
            "selected_or_current_fallback",
            "version_or_page_dependent",
            details={"reason": selected.get("error")},
            evidence=selected,
        )
    else:
        _record_tool_result(recorder, "operations.duplicate", "selected_or_current_fallback", selected)

    copy_range = server.timeline(
        "copy_range",
        {"start_frame": 110, "end_frame": 130, "record_frame": 930, "track_types": ["video"], "target_track_index": 2},
    )
    _record_tool_result(recorder, "operations.range", "copy_range", copy_range)

    duplicate_range = server.timeline(
        "duplicate_range",
        {"start_frame": 112, "end_frame": 128, "record_frame": 970, "track_types": ["video"], "target_track_index": 2},
    )
    _record_tool_result(recorder, "operations.range", "duplicate_range", duplicate_range)

    occupant_id = duplicate("overwrite_destination_fixture", {"target_track_index": 2, "record_frame": 1020})
    overwrite = server.timeline(
        "overwrite_range",
        {"start_frame": 100, "end_frame": 120, "record_frame": 1020, "track_types": ["video"], "target_track_index": 2},
    )
    _record_tool_result(recorder, "operations.range", "overwrite_range", overwrite)
    if occupant_id and not server._find_timeline_item_by_id(timeline, occupant_id):
        recorder.record("operations.range", "overwrite_deleted_destination_overlap", "supported")
    elif occupant_id:
        recorder.record("operations.range", "overwrite_deleted_destination_overlap", "partially_supported")

    lift_fixture_id = duplicate("lift_fixture", {"target_track_index": 1, "record_frame": 1120})
    lift = server.timeline(
        "lift_range",
        {"start_frame": 1120, "end_frame": 1120 + source_duration, "track_types": ["video"], "track_indices": [1]},
    )
    _record_tool_result(recorder, "operations.range", "lift_range_exact_item", lift)
    if lift_fixture_id and not server._find_timeline_item_by_id(timeline, lift_fixture_id):
        recorder.record("operations.range", "lift_deleted_exact_item", "supported")
    elif lift_fixture_id:
        recorder.record("operations.range", "lift_deleted_exact_item", "partially_supported")

    partial_lift = server.timeline(
        "lift_range",
        {"start_frame": 105, "end_frame": 110, "track_types": ["video"], "track_indices": [1]},
    )
    _record_tool_result(recorder, "operations.boundaries", "partial_lift_without_razor", partial_lift, expected_boundary=True)

    move_fixture_id = duplicate("move_fixture", {"target_track_index": 1, "record_frame": 1220})
    if move_fixture_id:
        move = server.timeline(
            "move_clips",
            {"clip_ids": [move_fixture_id], "target_track_index": 2, "record_frame": 1280},
        )
        _record_tool_result(recorder, "operations.duplicate", "move_clips", move)

    invalid_track = server.timeline("duplicate_clips", {"clip_ids": [source_id], "target_track_index": 99})
    _record_tool_result(recorder, "operations.boundaries", "invalid_target_track", invalid_track, expected_boundary=True)

    return duplicate_ids[0] if duplicate_ids else None


def _probe_source_less_boundaries(recorder: ProbeRecorder, server, timeline) -> None:
    probes: List[Tuple[str, Any]] = []
    for name, call in (
        ("insert_fusion_composition", lambda: timeline.InsertFusionCompositionIntoTimeline()),
        ("insert_title_text", lambda: timeline.InsertTitleIntoTimeline("Text")),
    ):
        item, exc = _safe_call(call)
        if exc:
            recorder.record("operations.source_less", name, "error", details={"exception": repr(exc)})
            continue
        if not item:
            recorder.record("operations.source_less", name, "unsupported", details={"reason": "Resolve returned no item"})
            continue
        probes.append((name, item))
        recorder.record("operations.source_less", name, "supported", details={"timeline_item_id": _safe_item_id(item)})

    for name, item in probes:
        item_id = _safe_item_id(item)
        if not item_id:
            continue
        result = server.timeline("duplicate_clips", {"clip_ids": [item_id], "target_track_index": 2, "record_frame": 1400})
        _record_tool_result(
            recorder,
            "operations.boundaries",
            f"{name}_append_clone_without_media_pool_item",
            result,
            expected_boundary=True,
        )


def _probe_track_controls(recorder: ProbeRecorder, server, timeline) -> None:
    for track_type, index in (("video", 1), ("audio", 1)):
        name = f"{track_type}.{index}"
        original_name = None
        try:
            original_name = timeline.GetTrackName(track_type, index)
        except Exception:
            pass
        result = server.timeline("set_track_name", {"track_type": track_type, "index": index, "name": f"Probe {name}"})
        _record_tool_result(recorder, "operations.tracks", f"set_track_name.{name}", result)
        enabled = server.timeline("set_track_enable", {"track_type": track_type, "index": index, "enabled": True})
        _record_tool_result(recorder, "operations.tracks", f"set_track_enable.{name}", enabled)
        locked = server.timeline("set_track_lock", {"track_type": track_type, "index": index, "locked": False})
        _record_tool_result(recorder, "operations.tracks", f"set_track_lock.{name}", locked)
        if original_name:
            server.timeline("set_track_name", {"track_type": track_type, "index": index, "name": original_name})

    voice_get = server.timeline("get_voice_isolation_state", {"track_index": 1})
    _record_tool_result(recorder, "operations.tracks", "audio_track_voice_isolation_get", voice_get)
    voice_set = server.timeline("set_voice_isolation_state", {"track_index": 1, "state": {"isEnabled": True, "amount": 20}})
    _record_tool_result(recorder, "operations.tracks", "audio_track_voice_isolation_set", voice_set)


def run_probe(server, output_dir: Path, keep_open: bool = False) -> Dict[str, Any]:
    recorder = ProbeRecorder()
    project_name = f"_mcp_timeline_kernel_probe_{int(time.time())}"
    timeline_name = "timeline_kernel_boundary_probe"
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_timeline_kernel_probe_"))
    created_project = False
    delete_result = None
    metadata: Dict[str, Any] = {
        "timestamp_utc": utc_timestamp(),
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "project_name": project_name,
    }

    try:
        version = _require_success("resolve_control.get_version", server.resolve_control("get_version"))
        metadata.update(
            {
                "product": version.get("product"),
                "version": version.get("version"),
                "version_string": version.get("version_string"),
            }
        )
        print(f"Connected to {metadata['product']} {metadata['version_string']}")

        _require_success("project_manager.create", server.project_manager("create", {"name": project_name}))
        created_project = True
        print(f"Created disposable project: {project_name}")
        _require_success("resolve_control.open_page", server.resolve_control("open_page", {"page": "edit"}))

        media_path = _make_synthetic_media(work_dir)
        metadata["synthetic_media"] = str(media_path)
        print(f"Generated synthetic media: {media_path}")

        resolve = server.get_resolve()
        project = resolve.GetProjectManager().GetCurrentProject()
        media_pool = project.GetMediaPool()
        imported = media_pool.ImportMedia([str(media_path)])
        if not imported:
            raise AssertionError(f"Failed to import synthetic media: {media_path}")
        media_pool_item = imported[0]
        media_pool_item_id = media_pool_item.GetUniqueId()

        timeline = media_pool.CreateEmptyTimeline(timeline_name)
        if not timeline:
            raise AssertionError("Failed to create timeline")
        _ensure_current_timeline(recorder, project, timeline, "initial", required=True)

        for _ in range(max(0, 3 - int(timeline.GetTrackCount("video") or 0))):
            _require_success("timeline.add_track video", server.timeline("add_track", {"track_type": "video"}))
        for _ in range(max(0, 2 - int(timeline.GetTrackCount("audio") or 0))):
            _require_success(
                "timeline.add_track audio",
                server.timeline("add_track", {"track_type": "audio", "options": {"audio_type": "stereo"}}),
            )
        server.timeline("set_start_timecode", {"timecode": "00:00:00:00"})

        append = _require_success(
            "media_pool.append_to_timeline video",
            server.media_pool(
                "append_to_timeline",
                {
                    "clip_infos": [
                        {
                            "media_pool_item_id": media_pool_item_id,
                            "start_frame": 24,
                            "end_frame": 71,
                            "record_frame": 100,
                            "track_index": 1,
                            "media_type": 1,
                        }
                    ]
                },
            ),
        )
        source_id = append["items"][0]["timeline_item_id"]
        source_item = server._find_timeline_item_by_id(timeline, source_id)
        if not source_item:
            raise AssertionError(f"Could not recover source item: {source_id}")

        audio_append = _require_success(
            "media_pool.append_to_timeline linked audio",
            server.media_pool(
                "append_to_timeline",
                {
                    "clip_infos": [
                        {
                            "media_pool_item_id": media_pool_item_id,
                            "start_frame": 24,
                            "end_frame": 71,
                            "record_frame": 100,
                            "track_index": 1,
                            "media_type": 2,
                        }
                    ]
                },
            ),
        )
        audio_id = audio_append["items"][0]["timeline_item_id"]
        audio_item = server._find_timeline_item_by_id(timeline, audio_id)
        if not audio_item:
            raise AssertionError(f"Could not recover audio item: {audio_id}")
        timeline.SetClipsLinked([source_item, audio_item], True)

        source_duration = _frame_int(source_item.GetDuration())
        metadata["source"] = {
            "timeline_item_id": source_id,
            "duration": source_duration,
            "source_start": _source_start(source_item),
        }

        api_text = Path("docs/reference/resolve_scripting_api.txt").read_text(encoding="utf-8")
        documented_property_keys = parse_timeline_item_property_keys(api_text)
        local_property_keys = []
        for keys in server._DUPLICATE_COPY_PROPERTY_KEYS.values():
            local_property_keys.extend(keys)
        property_keys = ordered_unique(documented_property_keys + local_property_keys + list(PROPERTY_CANDIDATES))

        timeline_methods = ordered_unique(parse_api_class_methods(api_text, "Timeline") + EXTRA_TIMELINE_METHODS)
        timeline_item_methods = ordered_unique(parse_api_class_methods(api_text, "TimelineItem") + EXTRA_TIMELINE_ITEM_METHODS)
        _record_method_availability(recorder, timeline, "runtime_methods.timeline", "Timeline", timeline_methods)
        _record_method_availability(recorder, source_item, "runtime_methods.timeline_item.video", "TimelineItem", timeline_item_methods)
        _record_method_availability(recorder, audio_item, "runtime_methods.timeline_item.audio", "TimelineItem", timeline_item_methods)

        duplicate_for_advanced_id = _probe_timeline_operations(recorder, server, timeline, source_id, source_duration)
        duplicate_for_advanced = (
            server._find_timeline_item_by_id(timeline, duplicate_for_advanced_id) if duplicate_for_advanced_id else None
        )
        _probe_track_controls(recorder, server, timeline)
        _probe_source_less_boundaries(recorder, server, timeline)
        _ensure_current_timeline(recorder, project, timeline, "before_property_probe")

        for key in property_keys:
            _probe_property(recorder, source_item, "video", key)
            _probe_property(recorder, audio_item, "audio", key)

        for key in property_keys:
            _probe_keyframe(recorder, source_item, "video", key)

        _probe_markers_flags_color_enabled(recorder, source_item, "video")
        _probe_markers_flags_color_enabled(recorder, audio_item, "audio")
        _probe_cache_voice_takes_fusion_grade(
            recorder,
            source_item,
            duplicate_for_advanced,
            media_pool_item,
            "video",
            output_dir,
        )

        _ensure_current_timeline(recorder, project, timeline, "before_mcp_capabilities")
        capabilities = server.timeline("edit_kernel_capabilities")
        _record_tool_result(recorder, "mcp_capabilities", "edit_kernel_capabilities", capabilities)
        probe = server.timeline("probe_edit_kernel_item", {"clip_ids": [source_id, audio_id]})
        if isinstance(probe, dict) and probe.get("error") == "No current timeline":
            recorder.record(
                "mcp_capabilities",
                "probe_edit_kernel_item",
                "version_or_page_dependent",
                details={
                    "reason": (
                        "Project.SetCurrentTimeline was not callable after source-less item probing; "
                        "the live validation covers this tool when Resolve keeps a current timeline"
                    )
                },
                evidence=probe,
            )
            direct_probe = server._timeline_probe_edit_kernel_item(timeline, {"clip_ids": [source_id, audio_id]})
            if isinstance(direct_probe, dict) and direct_probe.get("error"):
                recorder.record(
                    "mcp_capabilities",
                    "probe_edit_kernel_item_direct_timeline_object",
                    "version_or_page_dependent",
                    details={
                        "reason": (
                            "The retained timeline object could not resolve the original item IDs after "
                            "source-less item probing changed Resolve's timeline focus"
                        )
                    },
                    evidence=direct_probe,
                )
            else:
                _record_tool_result(
                    recorder,
                    "mcp_capabilities",
                    "probe_edit_kernel_item_direct_timeline_object",
                    direct_probe,
                )
        else:
            _record_tool_result(recorder, "mcp_capabilities", "probe_edit_kernel_item", probe)

        recorder.record(
            "operations.boundaries",
            "transition_cloning",
            "unsupported",
            details={"reason": "Resolve public API exposes no transition cloning primitive on TimelineItem"},
        )
        recorder.record(
            "operations.boundaries",
            "razor_or_split",
            "unsupported",
            details={"reason": "Resolve public API exposes no direct timeline split/razor primitive"},
        )
        recorder.record(
            "operations.boundaries",
            "opaque_speed_ramp_internals",
            "partially_supported",
            details={
                "reason": "Speed/RetimeProcess/MotionEstimation and keyframes are visible when Resolve exposes them; opaque speed ramp curves are not independently inspectable"
            },
        )

        if keep_open:
            server.project_manager("save")
            print(f"LEFT PROJECT OPEN FOR INSPECTION: {project_name}")
            created_project = False

    except Exception as exc:
        recorder.record(
            "probe",
            "fatal",
            "error",
            details={"exception": repr(exc), "traceback": traceback.format_exc()},
        )
        raise
    finally:
        if created_project:
            server.project_manager("save")
            server.project_manager("close")
            delete_result = server.project_manager("delete", {"name": project_name})
            print(f"Deleted disposable project: {delete_result}")

    if delete_result is not None and delete_result.get("success") is not True:
        raise AssertionError(f"Cleanup failed for {project_name}: {delete_result!r}")

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata["output_dir"] = str(output_dir)
    report = recorder.to_report(metadata, artifacts={})
    json_path = output_dir / "timeline-edit-kernel-probe.json"
    markdown_path = output_dir / "timeline-edit-kernel-probe.md"
    report["artifacts"] = {"json": str(json_path), "markdown": str(markdown_path)}
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    print(f"Wrote JSON report: {json_path}")
    print(f"Wrote Markdown report: {markdown_path}")
    print(f"Counts: {json.dumps(report['counts'], sort_keys=True)}")
    return report
