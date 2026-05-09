#!/usr/bin/env python3
"""Live Color / Grade boundary probe."""

from __future__ import annotations

import json
import os
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
    expected_status: Optional[str] = None,
) -> None:
    if not isinstance(result, dict):
        recorder.record(category, name, "error", details={"reason": "non-dict result", "result": repr(result)})
        return
    if result.get("error"):
        recorder.record(
            category,
            name,
            expected_status or "error",
            details={"reason": result.get("error"), "expected_status": expected_status},
            evidence=result,
        )
        return
    if "success" in result and result["success"] is not True:
        recorder.record(
            category,
            name,
            expected_status or "partially_supported",
            details={"reason": "success returned false", "expected_status": expected_status},
            evidence=result,
        )
        return
    recorder.record(category, name, expected_status or "supported", evidence=result)


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args], check=True)


def _make_synthetic_video(work_dir: Path) -> Path:
    video = work_dir / "color_grade_probe.mov"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "smptebars=size=640x360:rate=24:duration=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:sample_rate=48000:duration=4",
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


def _timeline_video_items(timeline):
    try:
        return timeline.GetItemListInTrack("video", 1) or []
    except Exception:
        return []


def _cleanup_exported_files(files):
    folders = set()
    for file_info in files or []:
        path = file_info.get("path")
        if not path:
            continue
        folders.add(os.path.dirname(path))
        try:
            os.remove(path)
        except OSError:
            pass
    for folder in folders:
        try:
            if os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
        except OSError:
            pass


def _redact_file_payloads(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return result
    redacted = dict(result)
    files = []
    for file_info in result.get("files", []) or []:
        if not isinstance(file_info, dict):
            files.append(file_info)
            continue
        files.append({key: value for key, value in file_info.items() if key not in {"data", "data_base64"}})
    if "files" in redacted:
        redacted["files"] = files
    return redacted


def run_probe(server, output_dir: Path, keep_open: bool = False) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_color_grade_probe_"))
    project_name = f"_mcp_color_grade_probe_{int(time.time())}"
    timeline_name = "Color Grade Probe Timeline"
    recorder = ProbeRecorder()
    created_project = False
    delete_result: Optional[Dict[str, Any]] = None
    exported_gallery_files = []

    metadata: Dict[str, Any] = {
        "title": "Color Grade Kernel Capability Probe",
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

        video = _make_synthetic_video(work_dir)
        metadata["synthetic_media"] = {"video": str(video)}
        print(f"Generated synthetic media under: {work_dir}")

        resolve = server.get_resolve()
        project = resolve.GetProjectManager().GetCurrentProject()
        media_pool = project.GetMediaPool()
        imported = media_pool.ImportMedia([str(video)]) or []
        clip = _first_imported_clip(imported)
        if not clip:
            raise AssertionError("Failed to import synthetic color media")
        timeline = media_pool.CreateTimelineFromClips(timeline_name, [clip])
        if not timeline:
            raise AssertionError("Failed to create color grade timeline")
        project.SetCurrentTimeline(timeline)
        media_pool.AppendToTimeline([clip])
        timeline.SetCurrentTimecode("01:00:00:01")
        server.resolve_control("open_page", {"page": "color"})
        print(f"Created timeline: {timeline_name}")

        items = _timeline_video_items(timeline)
        metadata["timeline_item_count"] = len(items)
        target_id = items[1].GetUniqueId() if len(items) > 1 else None

        scope = {"track_type": "video", "track_index": 1, "item_index": 0}
        _record_tool_result(recorder, "capabilities", "grade_capabilities", server.timeline_item_color("grade_capabilities", scope))
        _record_tool_result(
            recorder,
            "inspection",
            "probe_grade_item",
            server.timeline_item_color("probe_grade_item", {**scope, "max_nodes": 3}),
        )
        _record_tool_result(
            recorder,
            "inspection",
            "probe_item_node_graph",
            server.timeline_item_color("probe_node_graph", {**scope, "source": "item", "max_nodes": 3}),
        )
        _record_tool_result(
            recorder,
            "inspection",
            "probe_timeline_node_graph",
            server.timeline_item_color("probe_node_graph", {**scope, "source": "timeline", "include_nodes": False}),
        )

        cdl = {
            "NodeIndex": 1,
            "Slope": [1.05, 1.0, 0.95],
            "Offset": [0.0, 0.0, 0.0],
            "Power": [1.0, 1.0, 1.0],
            "Saturation": 1.05,
        }
        _record_tool_result(
            recorder,
            "cdl",
            "safe_set_cdl_dry_run",
            server.timeline_item_color("safe_set_cdl", {**scope, "cdl": cdl, "dry_run": True}),
        )
        _record_tool_result(
            recorder,
            "cdl",
            "safe_set_cdl_apply",
            server.timeline_item_color("safe_set_cdl", {**scope, "cdl": cdl}),
        )

        _record_tool_result(
            recorder,
            "versions",
            "grade_version_snapshot_before",
            server.timeline_item_color("grade_version_snapshot", scope),
        )
        _record_tool_result(
            recorder,
            "versions",
            "add_version",
            server.timeline_item_color("add_version", {**scope, "name": "MCP Probe Look", "type": 0}),
        )
        _record_tool_result(
            recorder,
            "versions",
            "rename_version",
            server.timeline_item_color(
                "rename_version",
                {**scope, "old_name": "MCP Probe Look", "new_name": "MCP Probe Look Renamed", "type": 0},
            ),
        )
        _record_tool_result(
            recorder,
            "versions",
            "grade_version_restore",
            server.timeline_item_color("grade_version_restore", {**scope, "name": "MCP Probe Look Renamed", "type": 0}),
        )
        _record_tool_result(
            recorder,
            "versions",
            "load_default_version",
            server.timeline_item_color("load_version", {**scope, "name": "Version 1", "type": 0}),
        )
        _record_tool_result(
            recorder,
            "versions",
            "delete_version",
            server.timeline_item_color("delete_version", {**scope, "name": "MCP Probe Look Renamed", "type": 0}),
        )

        if target_id:
            _record_tool_result(
                recorder,
                "copy",
                "safe_copy_grade",
                server.timeline_item_color("safe_copy_grade", {**scope, "target_ids": [target_id]}),
            )
        else:
            recorder.record("copy", "safe_copy_grade", "not_applicable", details={"reason": "No second video item"})

        lut_path = str(work_dir / "probe_look.cube")
        _record_tool_result(
            recorder,
            "lut",
            "safe_export_lut",
            server.timeline_item_color("safe_export_lut", {**scope, "type": "33ptcube", "path": lut_path}),
        )

        group_name = f"MCP Probe Group {int(time.time())}"
        group_created = server.project_settings("add_color_group", {"name": group_name})
        _record_tool_result(recorder, "color_groups", "add_color_group", group_created)
        if not group_created.get("error") and group_created.get("success"):
            _record_tool_result(
                recorder,
                "color_groups",
                "assign_color_group",
                server.timeline_item_color("assign_color_group", {**scope, "group_name": group_name}),
            )
            _record_tool_result(
                recorder,
                "color_groups",
                "color_group_capabilities",
                server.timeline_item_color("color_group_capabilities", scope),
            )
            _record_tool_result(
                recorder,
                "color_groups",
                "probe_color_group_pre",
                server.timeline_item_color(
                    "probe_node_graph",
                    {**scope, "source": "color_group_pre", "group_name": group_name, "include_nodes": False},
                ),
            )
            _record_tool_result(
                recorder,
                "color_groups",
                "probe_color_group_post",
                server.timeline_item_color(
                    "probe_node_graph",
                    {**scope, "source": "color_group_post", "group_name": group_name, "include_nodes": False},
                ),
            )
            _record_tool_result(
                recorder,
                "color_groups",
                "remove_from_color_group",
                server.timeline_item_color("remove_from_color_group", scope),
            )
            _record_tool_result(
                recorder,
                "color_groups",
                "delete_color_group",
                server.project_settings("delete_color_group", {"name": group_name}),
            )

        _record_tool_result(
            recorder,
            "gallery",
            "gallery_capabilities",
            server.timeline_item_color("gallery_capabilities", scope),
        )
        _record_tool_result(recorder, "gallery", "get_still_albums", server.gallery("get_still_albums"))
        _record_tool_result(recorder, "gallery", "create_still_album", server.gallery("create_still_album"))
        drx_path = None
        frame_drx_path = str(work_dir / "current_frame.drx")
        frame_drx_result = server.project_settings("export_frame_as_still", {"path": frame_drx_path})
        frame_drx_expected = None
        if isinstance(frame_drx_result, dict) and frame_drx_result.get("success") is not True:
            frame_drx_expected = "version_or_page_dependent"
        _record_tool_result(
            recorder,
            "drx",
            "export_current_frame_as_still_drx",
            frame_drx_result,
            expected_status=frame_drx_expected,
        )
        if isinstance(frame_drx_result, dict) and frame_drx_result.get("success") and os.path.isfile(frame_drx_path):
            drx_path = frame_drx_path

        still_result = server.gallery_stills(
            "grab_and_export",
            {"folder_path": str(work_dir / "stills"), "prefix": "color_grade_probe", "format": "jpg", "cleanup": False},
        )
        gallery_expected = None
        if isinstance(still_result, dict) and still_result.get("error"):
            gallery_expected = "version_or_page_dependent"
        _record_tool_result(
            recorder,
            "gallery",
            "grab_and_export",
            _redact_file_payloads(still_result),
            expected_status=gallery_expected,
        )
        exported_gallery_files = still_result.get("files", []) if isinstance(still_result, dict) else []
        if not drx_path:
            for file_info in exported_gallery_files:
                if str(file_info.get("path", "")).lower().endswith(".drx"):
                    drx_path = file_info["path"]
                    break
        if drx_path:
            apply_params = {**scope, "path": drx_path, "grade_mode": 0}
            if not str(drx_path).startswith(str(work_dir)):
                apply_params["require_temp_path"] = False
            _record_tool_result(
                recorder,
                "drx",
                "safe_apply_drx",
                server.timeline_item_color("safe_apply_drx", apply_params),
            )
        else:
            recorder.record("drx", "safe_apply_drx", "not_applicable", details={"reason": "No DRX was exported by gallery probe"})

        _record_tool_result(
            recorder,
            "report",
            "grade_boundary_report",
            server.timeline_item_color("grade_boundary_report", {**scope, "include_timeline_graph": True}),
        )

        if keep_open:
            server.project_manager("save")
            print(f"LEFT PROJECT OPEN FOR INSPECTION: {project_name}")
            created_project = False

    finally:
        _cleanup_exported_files(exported_gallery_files)
        if created_project:
            server.project_manager("save")
            server.project_manager("close")
            delete_result = server.project_manager("delete", {"name": project_name})
            print(f"Deleted disposable project: {delete_result}")

    report = recorder.to_report(
        metadata,
        {
            "json": str(output_dir / "color-grade-probe.json"),
            "markdown": str(output_dir / "color-grade-probe.md"),
        },
    )
    json_path = output_dir / "color-grade-probe.json"
    markdown_path = output_dir / "color-grade-probe.md"
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
