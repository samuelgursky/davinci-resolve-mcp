#!/usr/bin/env python3
"""Live Review Annotation boundary probe."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.utils.timeline_kernel_probe import ProbeRecorder, render_markdown_report, utc_timestamp


def _require_success(label: str, result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise AssertionError(f"{label}: expected dict, got {result!r}")
    if result.get("error"):
        raise AssertionError(f"{label}: {result['error']}")
    if "success" in result and result["success"] is not True:
        raise AssertionError(f"{label}: expected success=True, got {result!r}")
    return result


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
            "unsupported" if expected_boundary else "partially_supported",
            details={"reason": "success returned false", "expected_boundary": expected_boundary},
            evidence=result,
        )
        return
    recorder.record(category, name, "supported", evidence=result)


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args], check=True, timeout=120)


def _make_synthetic_video(work_dir: Path) -> Path:
    video = work_dir / "review_annotation_probe.mov"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24:duration=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=550:sample_rate=48000:duration=4",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-y",
            str(video),
        ]
    )
    return video


def _first_imported_clip(imported_items):
    for item in imported_items or []:
        try:
            if item.GetUniqueId():
                return item
        except Exception:
            pass
    return None


def run_probe(server, output_dir: Path, keep_open: bool = False) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_review_annotation_probe_"))
    project_name = f"_mcp_review_annotation_probe_{int(time.time())}"
    timeline_name = "Review Annotation Probe Timeline"
    recorder = ProbeRecorder()
    created_project = False
    delete_result: Optional[Dict[str, Any]] = None

    metadata: Dict[str, Any] = {
        "title": "Review Annotation Kernel Capability Probe",
        "timestamp_utc": utc_timestamp(),
        "python": sys.version,
        "platform": platform.platform(),
        "output_dir": str(output_dir),
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
        server.resolve_control("open_page", {"page": "edit"})

        video = _make_synthetic_video(work_dir)
        metadata["synthetic_media"] = {"video": str(video)}
        print(f"Generated synthetic media under: {work_dir}")

        resolve = server.get_resolve()
        project = resolve.GetProjectManager().GetCurrentProject()
        media_pool = project.GetMediaPool()
        imported = media_pool.ImportMedia([str(video)]) or []
        clip = _first_imported_clip(imported)
        if not clip:
            raise AssertionError("Failed to import synthetic review media")
        clip_id = clip.GetUniqueId()
        metadata["clip_id"] = clip_id
        timeline = media_pool.CreateTimelineFromClips(timeline_name, [clip])
        if not timeline:
            raise AssertionError("Failed to create review annotation timeline")
        project.SetCurrentTimeline(timeline)
        timeline.SetCurrentTimecode("01:00:00:01")
        print(f"Created timeline: {timeline_name}")

        _record_tool_result(recorder, "capabilities", "annotation_capabilities", server.timeline_markers("annotation_capabilities"))
        _record_tool_result(
            recorder,
            "normalization",
            "normalize_marker_payload",
            server.timeline_markers(
                "normalize_marker_payload",
                {"frameId": "24", "color": "green", "label": "Normalized", "comment": "Payload", "customData": "normalized-24"},
            ),
        )
        _record_tool_result(
            recorder,
            "normalization",
            "invalid_color_boundary",
            server.timeline_markers("normalize_marker_payload", {"frame": 25, "color": "Invisible"}),
            expected_boundary=True,
        )

        timeline_markers = [
            ("add_frame", {"frame": 4, "color": "Blue", "name": "Frame", "note": "frame alias", "custom_data": "tl-frame"}),
            ("add_frame_id", {"frame_id": 8, "color": "Green", "name": "Frame ID", "note": "frame_id alias", "custom_data": "tl-frame-id"}),
            ("add_frameId", {"frameId": 12, "color": "Yellow", "name": "FrameId", "note": "frameId alias", "custom_data": "tl-frameId"}),
            ("add_timecode", {"timecode": "00:00:00:16", "color": "Red", "name": "Timecode", "note": "timecode alias", "custom_data": "tl-timecode"}),
            ("add_current_playhead", {"color": "Cyan", "name": "Current", "note": "current playhead", "custom_data": "tl-current"}),
        ]
        for name, params in timeline_markers:
            _record_tool_result(recorder, "timeline_markers", name, server.timeline_markers("add", params))

        _record_tool_result(recorder, "timeline_markers", "get_all", server.timeline_markers("get_all"))
        _record_tool_result(
            recorder,
            "timeline_markers",
            "get_by_custom_data",
            server.timeline_markers("get_by_custom_data", {"custom_data": "tl-frame"}),
        )
        _record_tool_result(
            recorder,
            "timeline_markers",
            "update_custom_data",
            server.timeline_markers("update_custom_data", {"frame": 4, "custom_data": "tl-frame-updated"}),
        )
        _record_tool_result(
            recorder,
            "timeline_markers",
            "get_custom_data",
            server.timeline_markers("get_custom_data", {"frame": 4}),
        )

        for index, color in enumerate(
            ["Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia", "Rose", "Lavender", "Sky", "Mint", "Lemon", "Sand", "Cocoa", "Cream"],
            start=40,
        ):
            _record_tool_result(
                recorder,
                "marker_colors",
                f"color_{color}",
                server.timeline_markers("add", {"frame": index, "color": color, "name": color, "custom_data": f"color-{color.lower()}"}),
            )

        _record_tool_result(
            recorder,
            "copy",
            "copy_timeline_to_item",
            server.timeline_markers(
                "copy_annotations",
                {"source": {"scope": "timeline"}, "target": {"scope": "timeline_item", "track_type": "video", "track_index": 1, "item_index": 0}},
            ),
        )
        _record_tool_result(
            recorder,
            "timeline_item",
            "sync_marker_custom_data",
            server.timeline_markers(
                "sync_marker_custom_data",
                {"scope": "timeline_item", "track_type": "video", "track_index": 1, "item_index": 0, "frame": 4, "custom_data": "item-synced"},
            ),
        )
        _record_tool_result(
            recorder,
            "timeline_item",
            "add_flag",
            server.timeline_item_markers("add_flag", {"track_type": "video", "track_index": 1, "item_index": 0, "color": "Blue"}),
        )
        _record_tool_result(
            recorder,
            "timeline_item",
            "get_flags",
            server.timeline_item_markers("get_flags", {"track_type": "video", "track_index": 1, "item_index": 0}),
        )
        _record_tool_result(
            recorder,
            "timeline_item",
            "set_clip_color",
            server.timeline_item_markers("set_clip_color", {"track_type": "video", "track_index": 1, "item_index": 0, "color": "Blue"}),
        )
        _record_tool_result(
            recorder,
            "timeline_item",
            "get_clip_color",
            server.timeline_item_markers("get_clip_color", {"track_type": "video", "track_index": 1, "item_index": 0}),
        )

        _record_tool_result(
            recorder,
            "media_pool_item",
            "marker_add",
            server.media_pool_item_markers(
                "add",
                {"clip_id": clip_id, "frame": 20, "color": "Blue", "name": "Media", "note": "media marker", "custom_data": "mpi-20"},
            ),
        )
        _record_tool_result(
            recorder,
            "media_pool_item",
            "add_flag",
            server.media_pool_item_markers("add_flag", {"clip_id": clip_id, "color": "Blue"}),
        )
        _record_tool_result(
            recorder,
            "media_pool_item",
            "set_clip_color",
            server.media_pool_item("set_clip_color", {"clip_id": clip_id, "color": "Blue"}),
        )
        _record_tool_result(
            recorder,
            "move",
            "move_media_pool_to_timeline",
            server.timeline_markers(
                "move_annotations",
                {"source": {"scope": "media_pool_item", "clip_id": clip_id}, "target": {"scope": "timeline"}},
            ),
        )

        _record_tool_result(recorder, "report", "probe_annotations", server.timeline_markers("probe_annotations"))
        _record_tool_result(recorder, "report", "export_review_report", server.timeline_markers("export_review_report"))
        _record_tool_result(recorder, "report", "annotation_boundary_report", server.timeline_markers("annotation_boundary_report"))

        _record_tool_result(
            recorder,
            "cleanup",
            "clear_timeline_item_annotations",
            server.timeline_markers(
                "clear_annotations_by_scope",
                {"scope": "timeline_item", "track_type": "video", "track_index": 1, "item_index": 0, "all": True, "clear_flags": True, "clear_clip_color": True},
            ),
        )
        _record_tool_result(
            recorder,
            "cleanup",
            "clear_timeline_annotations",
            server.timeline_markers("clear_annotations_by_scope", {"scope": "timeline", "all": True}),
        )
        _record_tool_result(
            recorder,
            "cleanup",
            "clear_media_pool_flags",
            server.media_pool_item_markers("clear_flags", {"clip_id": clip_id, "color": "Blue"}),
        )
        _record_tool_result(
            recorder,
            "cleanup",
            "clear_media_pool_color",
            server.media_pool_item("clear_clip_color", {"clip_id": clip_id}),
        )

        if keep_open:
            server.project_manager("save")
            print(f"LEFT PROJECT OPEN FOR INSPECTION: {project_name}")
            created_project = False

    finally:
        if created_project:
            server.project_manager("save")
            server.project_manager("close")
            delete_result = server.project_manager("delete", {"name": project_name})
            print(f"Deleted disposable project: {delete_result}")

    report = recorder.to_report(
        metadata,
        {
            "json": str(output_dir / "review-annotation-probe.json"),
            "markdown": str(output_dir / "review-annotation-probe.md"),
        },
    )
    json_path = output_dir / "review-annotation-probe.json"
    markdown_path = output_dir / "review-annotation-probe.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    print(f"Wrote JSON report: {json_path}")
    print(f"Wrote Markdown report: {markdown_path}")
    print(f"Counts: {json.dumps(report['counts'], sort_keys=True)}")
    if not keep_open:
        shutil.rmtree(work_dir, ignore_errors=True)
        print(f"Removed synthetic media directory: {work_dir}")

    if delete_result and delete_result.get("success") is not True:
        raise AssertionError(f"Cleanup failed for {project_name}: {delete_result!r}")
    return report
