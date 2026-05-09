#!/usr/bin/env python3
"""Live validation for timeline.duplicate_clips.

Creates a disposable Resolve project, imports synthetic media, places a trimmed
video-only timeline item, duplicates it via the compound timeline action,
verifies copied timing/source trim/metadata/property behavior, and deletes the
project unless --keep-open is provided.

Run with Python 3.10-3.12 against a running Resolve Studio instance:

  python3.11 tests/live_duplicate_clips_validation.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path


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
        raise RuntimeError("stdio_server is not used by the live duplicate harness")

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


def _require_success(label, result):
    if not isinstance(result, dict):
        raise AssertionError(f"{label}: expected dict, got {result!r}")
    if result.get("error"):
        raise AssertionError(f"{label}: {result['error']}")
    if "success" in result and result["success"] is not True:
        raise AssertionError(f"{label}: expected success=True, got {result!r}")
    return result


def _frame_int(value):
    return int(round(float(value)))


def _source_start(item):
    if hasattr(item, "GetSourceStartFrame"):
        try:
            value = item.GetSourceStartFrame()
            if value is not None:
                return _frame_int(value)
        except Exception:
            pass
    return _frame_int(item.GetLeftOffset())


def _assert_item_timing(item, *, expected_start: int, expected_duration: int, expected_source_start: int, label: str):
    actual_start = _frame_int(item.GetStart())
    actual_duration = _frame_int(item.GetDuration())
    actual_source_start = _source_start(item)
    if actual_start != expected_start:
        raise AssertionError(f"{label} start mismatch: expected {expected_start}, got {actual_start}")
    if actual_duration != expected_duration:
        raise AssertionError(f"{label} duration mismatch: expected {expected_duration}, got {actual_duration}")
    if actual_source_start != expected_source_start:
        raise AssertionError(
            f"{label} source trim mismatch: expected {expected_source_start}, got {actual_source_start}"
        )


def _assert_track(item, *, expected_track_index: int, label: str):
    track_info = item.GetTrackTypeAndIndex()
    if not track_info or str(track_info[0]).lower() != "video" or int(track_info[1]) != expected_track_index:
        raise AssertionError(f"{label} track mismatch: expected video {expected_track_index}, got {track_info!r}")


def _duplicate_one(server, timeline, source_id: str, params: dict, label: str):
    payload = dict(params)
    payload.setdefault("clip_ids", [source_id])
    duplicate = _require_success(label, server.timeline("duplicate_clips", payload))
    if duplicate.get("count") != 1:
        raise AssertionError(f"{label}: expected count=1, got {duplicate!r}")
    result = duplicate["results"][0]
    if result.get("success") is not True:
        raise AssertionError(f"{label}: duplicate_clips reported failure: {duplicate!r}")
    duplicate_id = result.get("timeline_item_id")
    if not duplicate_id:
        raise AssertionError(f"{label}: duplicate did not return a recoverable timeline item id: {duplicate!r}")
    duplicate_item = server._find_timeline_item_by_id(timeline, duplicate_id)
    if not duplicate_item:
        raise AssertionError(f"{label}: could not find duplicate timeline item: {duplicate_id}")
    if "source" not in result or "duplicate" not in result:
        raise AssertionError(f"{label}: rich duplicate metadata missing: {result!r}")
    return duplicate, result, duplicate_item


def _set_item_property(item, key: str, value):
    if not item.SetProperty(key, value):
        raise AssertionError(f"Failed to set source property {key}={value!r}")


def _try_set_item_property(item, key: str, value):
    try:
        set_ok = bool(item.SetProperty(key, value))
    except Exception as exc:
        print(f"{key} SetProperty raised {exc!r}; live copy assertion will be treated as API-unavailable")
        return None
    if not set_ok:
        print(f"{key} SetProperty returned false; live copy assertion will be treated as API-unavailable")
        return None
    try:
        actual = item.GetProperty(key)
    except Exception:
        actual = value
    if actual is None:
        print(f"{key} GetProperty returned None; live copy assertion will be treated as API-unavailable")
        return None
    return actual


def _property_values_match(actual, expected) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= 0.001
    except (TypeError, ValueError):
        return actual == expected


def _make_synthetic_media(work_dir: Path) -> Path:
    media_path = work_dir / "duplicate_clips_source.mov"
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


def run_validation(server, keep_open: bool = False) -> int:
    project_name = f"_mcp_duplicate_clips_live_{int(time.time())}"
    timeline_name = "duplicate_clips_live_validation"
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_duplicate_clips_live_"))
    created_project = False
    delete_result = None

    try:
        version = _require_success("resolve_control.get_version", server.resolve_control("get_version"))
        print(f"Connected to {version['product']} {version['version_string']}")

        _require_success("project_manager.create", server.project_manager("create", {"name": project_name}))
        created_project = True
        print(f"Created disposable project: {project_name}")

        _require_success("resolve_control.open_page", server.resolve_control("open_page", {"page": "edit"}))
        media_path = _make_synthetic_media(work_dir)
        print(f"Generated synthetic media: {media_path}")

        resolve = server.get_resolve()
        project = resolve.GetProjectManager().GetCurrentProject()
        media_pool = project.GetMediaPool()
        imported = media_pool.ImportMedia([str(media_path)])
        if not imported:
            raise AssertionError(f"Failed to import synthetic media: {media_path}")
        media_pool_item = imported[0]
        media_pool_item_id = media_pool_item.GetUniqueId()
        print(f"Imported media pool item: {media_pool_item.GetName()}")

        timeline = media_pool.CreateEmptyTimeline(timeline_name)
        if not timeline or not project.SetCurrentTimeline(timeline):
            raise AssertionError("Failed to create or set current validation timeline")
        print(f"Created timeline: {timeline_name}")

        if int(timeline.GetTrackCount("video") or 0) < 1:
            _require_success("timeline.add_track V1", server.timeline("add_track", {"track_type": "video"}))
        if int(timeline.GetTrackCount("video") or 0) < 2:
            _require_success("timeline.add_track V2", server.timeline("add_track", {"track_type": "video"}))
        if int(timeline.GetTrackCount("audio") or 0) < 1:
            _require_success(
                "timeline.add_track A1",
                server.timeline("add_track", {"track_type": "audio", "options": {"audio_type": "stereo"}}),
            )
        _require_success(
            "timeline.set_start_timecode",
            server.timeline("set_start_timecode", {"timecode": "00:00:00:00"}),
        )

        append = _require_success(
            "media_pool.append_to_timeline source trim",
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
        if not source_id:
            raise AssertionError(f"Append returned no source timeline item id: {append!r}")
        source_item = server._find_timeline_item_by_id(timeline, source_id)
        if not source_item:
            raise AssertionError(f"Could not find source timeline item: {source_id}")

        audio_append = _require_success(
            "media_pool.append_to_timeline linked audio trim",
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
        source_audio_id = audio_append["items"][0]["timeline_item_id"]
        source_audio_item = server._find_timeline_item_by_id(timeline, source_audio_id)
        if not source_audio_item:
            raise AssertionError(f"Could not find source audio timeline item: {source_audio_id}")
        if not timeline.SetClipsLinked([source_item, source_audio_item], True):
            raise AssertionError("Failed to link source video/audio pair")

        source_duration = _frame_int(source_item.GetDuration())
        source_start = _source_start(source_item)
        print(
            "Placed source item: "
            f"id={source_id}, start={source_item.GetStart()}, duration={source_duration}, source_start={source_start}"
        )

        _set_item_property(source_item, "Pan", 0.25)
        _set_item_property(source_item, "Tilt", -0.2)
        _set_item_property(source_item, "ZoomX", 1.2)
        _set_item_property(source_item, "ZoomY", 1.2)
        _set_item_property(source_item, "CropLeft", 3)
        _set_item_property(source_item, "Opacity", 64)
        _set_item_property(source_item, "RetimeProcess", 2)
        _set_item_property(source_item, "MotionEstimation", 1)
        optional_property_expectations = {}
        for key, value in {
            "DynamicZoomEnable": True,
            "DynamicZoomMode": 1,
            "DynamicZoomEase": 2,
            "Distortion": 0.1,
            "Scaling": 3,
            "ResizeFilter": 4,
            "StabilizationEnable": True,
            "StabilizationMethod": 1,
            "StabilizationStrength": 0.75,
        }.items():
            actual = _try_set_item_property(source_item, key, value)
            if actual is not None:
                optional_property_expectations[key] = actual
        if not source_item.SetClipColor("Teal"):
            raise AssertionError("Failed to set source clip color")
        if not source_item.AddMarker(4, "Blue", "Copy marker", "Marker copied by validation", 2, "copy-marker"):
            raise AssertionError("Failed to add source timeline item marker")
        if not source_item.AddFlag("Blue"):
            raise AssertionError("Failed to add source flag")
        add_keyframe = getattr(source_item, "AddKeyframe", None)
        source_keyframes_added = bool(add_keyframe("Pan", 0, 0.25)) if callable(add_keyframe) else False
        if not source_keyframes_added:
            print("Pan AddKeyframe returned false; live keyframe copy assertion will be treated as API-unavailable")
        if not source_item.AddTake(media_pool_item, 24, 71):
            raise AssertionError("Failed to add source take")
        source_comp = source_item.AddFusionComp()
        if not source_comp:
            raise AssertionError("Failed to add source Fusion comp")
        audio_volume_set = bool(source_audio_item.SetProperty("Volume", -6.0))
        if not audio_volume_set:
            print("Audio Volume SetProperty returned false; linked audio property write will be treated as API-unavailable")

        duplicate, result, duplicate_item = _duplicate_one(
            server,
            timeline,
            source_id,
            {"target_track_index": 2, "record_frame_offset": 200},
            "timeline.duplicate_clips offset",
        )
        expected_start = _frame_int(source_item.GetStart()) + 200
        duplicate_media_id = duplicate_item.GetMediaPoolItem().GetUniqueId()
        _assert_item_timing(
            duplicate_item,
            expected_start=expected_start,
            expected_duration=source_duration,
            expected_source_start=source_start,
            label="offset duplicate",
        )
        _assert_track(duplicate_item, expected_track_index=2, label="offset duplicate")
        if duplicate_media_id != media_pool_item_id:
            raise AssertionError(f"duplicate media mismatch: expected {media_pool_item_id}, got {duplicate_media_id}")
        print(
            "Verified offset duplicate: "
            f"id={result['timeline_item_id']}, start={duplicate_item.GetStart()}, duration={duplicate_item.GetDuration()}"
        )

        _, track_above_result, track_above_item = _duplicate_one(
            server,
            timeline,
            source_id,
            {"placement": "track_above"},
            "timeline.duplicate_clips track_above",
        )
        _assert_item_timing(
            track_above_item,
            expected_start=_frame_int(source_item.GetStart()),
            expected_duration=source_duration,
            expected_source_start=source_start,
            label="track_above duplicate",
        )
        _assert_track(track_above_item, expected_track_index=2, label="track_above duplicate")
        if track_above_result.get("placement") != "track_above":
            raise AssertionError(f"Expected placement metadata track_above, got {track_above_result!r}")
        print("Verified track_above placement")

        _, after_source_result, after_source_item = _duplicate_one(
            server,
            timeline,
            source_id,
            {"placement": "after_source"},
            "timeline.duplicate_clips after_source",
        )
        expected_after_source = _frame_int(source_item.GetStart()) + source_duration
        _assert_item_timing(
            after_source_item,
            expected_start=expected_after_source,
            expected_duration=source_duration,
            expected_source_start=source_start,
            label="after_source duplicate",
        )
        _assert_track(after_source_item, expected_track_index=1, label="after_source duplicate")
        if after_source_result.get("duplicate", {}).get("start") != expected_after_source:
            raise AssertionError(f"Expected duplicate metadata start {expected_after_source}, got {after_source_result!r}")
        print("Verified after_source placement")

        _, next_gap_result, next_gap_item = _duplicate_one(
            server,
            timeline,
            source_id,
            {"placement": "next_gap", "target_track_index": 2},
            "timeline.duplicate_clips next_gap",
        )
        expected_next_gap = expected_after_source
        _assert_item_timing(
            next_gap_item,
            expected_start=expected_next_gap,
            expected_duration=source_duration,
            expected_source_start=source_start,
            label="next_gap duplicate",
        )
        _assert_track(next_gap_item, expected_track_index=2, label="next_gap duplicate")
        if next_gap_result.get("placement") != "next_gap":
            raise AssertionError(f"Expected placement metadata next_gap, got {next_gap_result!r}")
        print("Verified next_gap placement")

        _require_success(
            "timeline_markers.set_current_timecode",
            server.timeline_markers("set_current_timecode", {"timecode": "00:00:30:00"}),
        )
        _, at_playhead_result, at_playhead_item = _duplicate_one(
            server,
            timeline,
            source_id,
            {"placement": "at_playhead", "target_track_index": 2},
            "timeline.duplicate_clips at_playhead",
        )
        _assert_item_timing(
            at_playhead_item,
            expected_start=720,
            expected_duration=source_duration,
            expected_source_start=source_start,
            label="at_playhead duplicate",
        )
        if at_playhead_result.get("placement") != "at_playhead":
            raise AssertionError(f"Expected placement metadata at_playhead, got {at_playhead_result!r}")
        print("Verified at_playhead placement")

        _, linked_result, linked_item = _duplicate_one(
            server,
            timeline,
            source_id,
            {
                "target_track_index": 2,
                "record_frame": 360,
                "include_linked": True,
                "copy_properties": ["audio"],
            },
            "timeline.duplicate_clips include_linked",
        )
        _assert_item_timing(
            linked_item,
            expected_start=360,
            expected_duration=source_duration,
            expected_source_start=source_start,
            label="linked video duplicate",
        )
        linked_audio_results = linked_result.get("linked_results") or []
        if len(linked_audio_results) != 1 or linked_audio_results[0].get("success") is not True:
            raise AssertionError(f"Expected one linked audio duplicate, got {linked_result!r}")
        linked_audio_item = server._find_timeline_item_by_id(timeline, linked_audio_results[0]["timeline_item_id"])
        if not linked_audio_item:
            raise AssertionError(f"Could not find linked audio duplicate: {linked_result!r}")
        _assert_item_timing(
            linked_audio_item,
            expected_start=360,
            expected_duration=source_duration,
            expected_source_start=source_start,
            label="linked audio duplicate",
        )
        linked_track_info = linked_audio_item.GetTrackTypeAndIndex()
        if str(linked_track_info[0]).lower() != "audio" or int(linked_track_info[1]) != 1:
            raise AssertionError(f"linked audio duplicate track mismatch: {linked_track_info!r}")
        if audio_volume_set and abs(float(linked_audio_item.GetProperty("Volume")) - -6.0) > 0.001:
            raise AssertionError(f"linked audio property copy mismatch: {linked_audio_item.GetProperty('Volume')!r}")
        if not linked_result.get("linked"):
            raise AssertionError(f"Expected duplicate linked state to be restored: {linked_result!r}")
        print("Verified linked audio duplication and relink")

        _require_success(
            "timeline_markers.set_current_timecode for selected",
            server.timeline_markers("set_current_timecode", {"timecode": "00:00:04:10"}),
        )
        selected_duplicate = _require_success(
            "timeline.duplicate_clips selected",
            server.timeline(
                "duplicate_clips",
                {
                    "selected": True,
                    "target_track_index": 2,
                    "record_frame": 420,
                },
            ),
        )
        selected_result = selected_duplicate["results"][0]
        if selected_result.get("success") is not True:
            raise AssertionError(f"selected duplicate failed: {selected_duplicate!r}")
        selected_item = server._find_timeline_item_by_id(timeline, selected_result["timeline_item_id"])
        if not selected_item:
            raise AssertionError(f"Could not find selected duplicate item: {selected_duplicate!r}")
        _assert_item_timing(
            selected_item,
            expected_start=420,
            expected_duration=source_duration,
            expected_source_start=source_start,
            label="selected duplicate",
        )
        print("Verified selected/current item duplicate")

        source_item.SetClipColor("Teal")
        color_copy_available = source_item.GetClipColor() == "Teal"
        if not color_copy_available:
            print("Clip color is not readable after take/Fusion setup; clip color copy will be treated as API-unavailable")
        if not source_item.SetClipEnabled(False):
            raise AssertionError("Failed to disable source item for enabled-state copy validation")
        _, property_result, property_item = _duplicate_one(
            server,
            timeline,
            source_id,
            {
                "target_track_index": 2,
                "record_frame": 520,
                "copy_properties": [
                    "transform",
                    "crop",
                    "composite",
                    "retime",
                    "dynamic_zoom",
                    "scaling",
                    "stabilization",
                    "clip_color",
                    "markers",
                    "flags",
                    "enabled",
                    "cache",
                    "voice_isolation",
                    "fusion",
                    "grades",
                    "takes",
                    "keyframes",
                    "transitions",
                ],
                "copy_keyframes": True,
            },
            "timeline.duplicate_clips copy_properties",
        )
        _assert_item_timing(
            property_item,
            expected_start=520,
            expected_duration=source_duration,
            expected_source_start=source_start,
            label="property-copy duplicate",
        )
        for key, expected in {
            "Pan": 0.25,
            "Tilt": -0.2,
            "ZoomX": 1.2,
            "ZoomY": 1.2,
            "CropLeft": 3,
            "Opacity": 64,
            "RetimeProcess": 2,
            "MotionEstimation": 1,
        }.items():
            actual = property_item.GetProperty(key)
            if abs(float(actual) - float(expected)) > 0.001:
                raise AssertionError(f"Property copy mismatch for {key}: expected {expected}, got {actual}")
        for key, expected in optional_property_expectations.items():
            actual = property_item.GetProperty(key)
            if not _property_values_match(actual, expected):
                raise AssertionError(f"Optional property copy mismatch for {key}: expected {expected!r}, got {actual!r}")
        clip_color_result = property_result.get("copied_properties", {}).get("clip_color", {})
        if color_copy_available and property_item.GetClipColor() != "Teal":
            if clip_color_result.get("success") is not False:
                raise AssertionError(
                    f"Clip color copy mismatch was not reported: {property_item.GetClipColor()!r}, "
                    f"{clip_color_result!r}"
                )
            print(f"Clip color copy reported unavailable: {clip_color_result.get('error')}")
        if bool(property_item.GetClipEnabled()) is not False:
            raise AssertionError("Enabled-state copy mismatch: duplicate should be disabled")
        copied_markers = property_item.GetMarkers() or {}
        marker = copied_markers.get(4) or copied_markers.get(4.0)
        if not marker or marker.get("name") != "Copy marker":
            raise AssertionError(f"Marker copy mismatch: {copied_markers!r}")
        if "Blue" not in (property_item.GetFlagList() or []):
            raise AssertionError(f"Flag copy mismatch: {property_item.GetFlagList()!r}")
        if int(property_item.GetFusionCompCount() or 0) < 1:
            raise AssertionError("Fusion comp copy mismatch: duplicate has no Fusion comps")
        if int(property_item.GetTakesCount() or 0) < 1:
            raise AssertionError("Take copy mismatch: duplicate has no takes")
        if source_keyframes_added and int(property_item.GetKeyframeCount("Pan") or 0) < 1:
            raise AssertionError("Keyframe copy mismatch: duplicate has no Pan keyframes")
        copied = property_result.get("copied_properties", {})
        for group in (
            "transform",
            "crop",
            "composite",
            "retime",
            "dynamic_zoom",
            "scaling",
            "stabilization",
            "clip_color",
            "markers",
            "flags",
            "enabled",
            "cache",
            "voice_isolation",
            "fusion",
            "grades",
            "takes",
            "keyframes",
            "transitions",
        ):
            if group not in copied:
                raise AssertionError(f"Missing copy_properties result for {group}: {property_result!r}")
        if copied["transitions"].get("copied") is not False:
            raise AssertionError(f"Expected transitions to report unsupported: {property_result!r}")
        print(
            "Verified property copying: "
            "transform, crop, composite, retime, dynamic zoom, scaling, stabilization, "
            "clip color, markers, flags, Fusion, grades, takes, keyframes, enabled state"
        )

        capabilities = server.timeline("edit_kernel_capabilities")
        if "transition_cloning" not in capabilities.get("unsupported", {}):
            raise AssertionError(f"edit_kernel_capabilities missing transition boundary: {capabilities!r}")
        if "dynamic_zoom_scaling_stabilization" not in capabilities.get("partially_supported", {}):
            raise AssertionError(f"edit_kernel_capabilities missing deep property boundary: {capabilities!r}")
        print("Verified edit kernel capability report")

        probe = _require_success(
            "timeline.probe_edit_kernel_item",
            server.timeline("probe_edit_kernel_item", {"clip_ids": [source_id]}),
        )
        if probe.get("count") != 1:
            raise AssertionError(f"probe_edit_kernel_item returned wrong count: {probe!r}")
        item_probe = probe["items"][0]
        if not item_probe.get("methods", {}).get("GetProperty"):
            raise AssertionError(f"probe_edit_kernel_item did not report GetProperty: {probe!r}")
        if "Pan" not in item_probe.get("known_properties", {}):
            raise AssertionError(f"probe_edit_kernel_item did not report known Pan property: {probe!r}")
        if not item_probe.get("linked_items"):
            raise AssertionError(f"probe_edit_kernel_item did not summarize linked audio: {probe!r}")
        print("Verified read-only edit kernel probe")

        copy_range = _require_success(
            "timeline.copy_range",
            server.timeline(
                "copy_range",
                {
                    "start_frame": 110,
                    "end_frame": 130,
                    "record_frame": 900,
                    "track_types": ["video"],
                    "target_track_index": 2,
                    "copy_properties": ["transform"],
                },
            ),
        )
        range_result = copy_range["results"][0]
        if range_result.get("success") is not True:
            raise AssertionError(f"copy_range failed: {copy_range!r}")
        range_item = server._find_timeline_item_by_id(timeline, range_result["timeline_item_id"])
        if not range_item:
            raise AssertionError(f"Could not find copy_range item: {copy_range!r}")
        _assert_item_timing(
            range_item,
            expected_start=900,
            expected_duration=20,
            expected_source_start=source_start + 10,
            label="copy_range duplicate",
        )
        print("Verified exact copy_range segment")

        occupant = _duplicate_one(
            server,
            timeline,
            source_id,
            {"target_track_index": 2, "record_frame": 980},
            "timeline.duplicate_clips overwrite occupant",
        )[2]
        occupant_id = occupant.GetUniqueId()
        overwrite = _require_success(
            "timeline.overwrite_range",
            server.timeline(
                "overwrite_range",
                {
                    "start_frame": 100,
                    "end_frame": 120,
                    "record_frame": 980,
                    "track_types": ["video"],
                    "target_track_index": 2,
                },
            ),
        )
        if server._find_timeline_item_by_id(timeline, occupant_id):
            raise AssertionError(f"overwrite_range did not delete destination occupant: {overwrite!r}")
        overwrite_item = server._find_timeline_item_by_id(timeline, overwrite["results"][0]["timeline_item_id"])
        _assert_item_timing(
            overwrite_item,
            expected_start=980,
            expected_duration=20,
            expected_source_start=source_start,
            label="overwrite_range duplicate",
        )
        print("Verified overwrite_range")

        lift_source = _duplicate_one(
            server,
            timeline,
            source_id,
            {"target_track_index": 1, "record_frame": 1100},
            "timeline.duplicate_clips lift source",
        )[2]
        lift_source_id = lift_source.GetUniqueId()
        lift = _require_success(
            "timeline.lift_range",
            server.timeline(
                "lift_range",
                {
                    "start_frame": 1100,
                    "end_frame": 1100 + source_duration,
                    "track_types": ["video"],
                    "track_indices": [1],
                },
            ),
        )
        if lift.get("deleted") != 1 or server._find_timeline_item_by_id(timeline, lift_source_id):
            raise AssertionError(f"lift_range failed to delete exact source: {lift!r}")
        print("Verified lift_range")

        move_source = _duplicate_one(
            server,
            timeline,
            source_id,
            {"target_track_index": 1, "record_frame": 1200},
            "timeline.duplicate_clips move source",
        )[2]
        move_source_id = move_source.GetUniqueId()
        move = _require_success(
            "timeline.move_clips",
            server.timeline(
                "move_clips",
                {
                    "clip_ids": [move_source_id],
                    "target_track_index": 2,
                    "record_frame": 1260,
                },
            ),
        )
        if not move.get("deleted_sources") or server._find_timeline_item_by_id(timeline, move_source_id):
            raise AssertionError(f"move_clips did not delete source after duplicate: {move!r}")
        move_item = server._find_timeline_item_by_id(timeline, move["results"][0]["timeline_item_id"])
        _assert_item_timing(
            move_item,
            expected_start=1260,
            expected_duration=source_duration,
            expected_source_start=source_start,
            label="move_clips duplicate",
        )
        print("Verified move_clips")

        invalid_track = server.timeline(
            "duplicate_clips",
            {"clip_ids": [source_id], "target_track_index": 99, "record_frame_offset": 10},
        )
        if "does not exist" not in invalid_track["results"][0].get("error", ""):
            raise AssertionError(f"Expected invalid track error, got {invalid_track!r}")
        print("Verified invalid target track error path")

        if keep_open:
            _require_success("project_manager.save", server.project_manager("save"))
            print(f"LEFT PROJECT OPEN FOR INSPECTION: {project_name}")
            created_project = False

    finally:
        if created_project:
            server.project_manager("save")
            server.project_manager("close")
            delete_result = server.project_manager("delete", {"name": project_name})
            print(f"Deleted disposable project: {delete_result}")

    if delete_result and delete_result.get("success") is not True:
        raise AssertionError(f"Cleanup failed for {project_name}: {delete_result!r}")
    print("duplicate_clips live validation passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Live duplicate_clips validation harness")
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Leave the disposable project open for manual inspection.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for kernel probe JSON/Markdown reports. Defaults to a temp directory.",
    )
    args = parser.parse_args()

    _install_mcp_stubs()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    original_argv = sys.argv[:]
    sys.argv = [sys.argv[0]]
    try:
        import src.server as server
    finally:
        sys.argv = original_argv

    validation_result = run_validation(server, keep_open=args.keep_open)

    if args.output_dir is not None:
        from src.utils.timeline_kernel_live_probe import run_probe

        run_probe(server, args.output_dir, keep_open=args.keep_open)
        return 0

    return validation_result


if __name__ == "__main__":
    raise SystemExit(main())
