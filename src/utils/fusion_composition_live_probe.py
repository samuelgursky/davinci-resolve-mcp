#!/usr/bin/env python3
"""Live Fusion Composition boundary probe."""

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
    video = work_dir / "fusion_composition_probe.mov"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=24:duration=4",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
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
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_fusion_composition_probe_"))
    project_name = f"_mcp_fusion_composition_probe_{int(time.time())}"
    timeline_name = "Fusion Composition Probe Timeline"
    recorder = ProbeRecorder()
    created_project = False
    delete_result: Optional[Dict[str, Any]] = None

    metadata: Dict[str, Any] = {
        "title": "Fusion Composition Kernel Capability Probe",
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
            raise AssertionError("Failed to import synthetic Fusion media")
        timeline = media_pool.CreateTimelineFromClips(timeline_name, [clip])
        if not timeline:
            raise AssertionError("Failed to create Fusion timeline")
        project.SetCurrentTimeline(timeline)
        timeline.SetCurrentTimecode("01:00:00:01")
        print(f"Created timeline: {timeline_name}")

        item_scope = {"track_type": "video", "track_index": 1, "item_index": 0}
        comp_scope = {"timeline_item": item_scope}

        _record_tool_result(recorder, "timeline_item_fusion", "add_comp", server.timeline_item_fusion("add_comp", item_scope))
        _record_tool_result(recorder, "timeline_item_fusion", "get_comp_count", server.timeline_item_fusion("get_comp_count", item_scope))
        _record_tool_result(recorder, "timeline_item_fusion", "get_comp_names", server.timeline_item_fusion("get_comp_names", item_scope))

        _record_tool_result(recorder, "capabilities", "fusion_graph_capabilities", server.fusion_comp("fusion_graph_capabilities", comp_scope))
        _record_tool_result(
            recorder,
            "inspection",
            "probe_fusion_comp_initial",
            server.fusion_comp("probe_fusion_comp", {**comp_scope, "include_io": False}),
        )

        for tool_type, name in (
            ("Background", "MCP_Background"),
            ("TextPlus", "MCP_Text"),
            ("Merge", "MCP_Merge"),
            ("Transform", "MCP_Transform"),
            ("Blur", "MCP_Blur"),
        ):
            _record_tool_result(
                recorder,
                "tools",
                f"safe_add_{tool_type}",
                server.fusion_comp("safe_add_tool", {**comp_scope, "tool_type": tool_type, "name": name, "include_io": True}),
            )

        _record_tool_result(
            recorder,
            "inputs",
            "safe_set_text",
            server.fusion_comp(
                "safe_set_inputs",
                {**comp_scope, "tool_name": "MCP_Text", "inputs": {"StyledText": "MCP Fusion Probe"}, "readback": True},
            ),
        )
        _record_tool_result(
            recorder,
            "inputs",
            "safe_set_background_color",
            server.fusion_comp(
                "safe_set_inputs",
                {
                    **comp_scope,
                    "tool_name": "MCP_Background",
                    "inputs": {
                        "TopLeftRed": 0.1,
                        "TopLeftGreen": 0.2,
                        "TopLeftBlue": 0.7,
                        "TopLeftAlpha": 1.0,
                    },
                    "readback": True,
                },
            ),
        )
        _record_tool_result(
            recorder,
            "inspection",
            "probe_text_tool",
            server.fusion_comp("probe_fusion_tool", {**comp_scope, "tool_name": "MCP_Text", "include_io": True}),
        )
        _record_tool_result(
            recorder,
            "wiring",
            "safe_connect_text_to_mediaout",
            server.fusion_comp(
                "safe_connect_tools",
                {**comp_scope, "target_tool": "MediaOut1", "input_name": "Input", "source_tool": "MCP_Text"},
            ),
        )
        _record_tool_result(
            recorder,
            "bulk",
            "bulk_set_inputs",
            server.fusion_comp(
                "bulk_set_inputs",
                {
                    "ops": [
                        {**comp_scope, "tool_name": "MCP_Text", "input_name": "Size", "value": 0.08},
                        {**comp_scope, "tool_name": "MCP_Background", "input_name": "GlobalOut", "value": 96},
                    ]
                },
            ),
        )
        _record_tool_result(
            recorder,
            "composition",
            "set_frame_range",
            server.fusion_comp("set_frame_range", {**comp_scope, "start": 0, "end": 96}),
        )
        export_path = str(work_dir / "fusion_probe.setting")
        _record_tool_result(
            recorder,
            "timeline_item_fusion",
            "export_comp",
            server.timeline_item_fusion("export_comp", {**item_scope, "path": export_path, "index": 1}),
        )
        _record_tool_result(
            recorder,
            "report",
            "fusion_boundary_report",
            server.fusion_comp("fusion_boundary_report", {**comp_scope, "include_io": False}),
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
            "json": str(output_dir / "fusion-composition-probe.json"),
            "markdown": str(output_dir / "fusion-composition-probe.md"),
        },
    )
    json_path = output_dir / "fusion-composition-probe.json"
    markdown_path = output_dir / "fusion-composition-probe.md"
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
