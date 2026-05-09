#!/usr/bin/env python3
"""Live Timeline Conform / Interchange boundary probe."""

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
        recorder.record(category, name, expected_status or "error", details={"reason": result.get("error")}, evidence=result)
        return
    if "success" in result and result["success"] is not True:
        recorder.record(
            category,
            name,
            expected_status or "partially_supported",
            details={"reason": "success returned false"},
            evidence=result,
        )
        return
    recorder.record(category, name, expected_status or "supported", evidence=result)


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args], check=True)


def _make_synthetic_video(work_dir: Path, name: str, source: str, frequency: int) -> Path:
    video = work_dir / name
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"{source}=size=640x360:rate=24:duration=4",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=48000:duration=4",
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


def _first_imported(imported_items):
    for item in imported_items or []:
        try:
            if item.GetUniqueId():
                return item
        except Exception:
            pass
    return None


def _clip_id(clip) -> Optional[str]:
    try:
        return str(clip.GetUniqueId())
    except Exception:
        return None


def run_probe(server, output_dir: Path, keep_open: bool = False) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_timeline_conform_probe_"))
    interchange_dir = output_dir / "interchange"
    interchange_dir.mkdir(parents=True, exist_ok=True)
    project_name = f"_mcp_timeline_conform_probe_{int(time.time())}"
    timeline_name = "Timeline Conform Probe"
    recorder = ProbeRecorder()
    created_project = False
    delete_result: Optional[Dict[str, Any]] = None

    metadata: Dict[str, Any] = {
        "title": "Timeline Conform / Interchange Kernel Capability Probe",
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

        video_a = _make_synthetic_video(work_dir, "conform_A.mov", "testsrc2", 440)
        video_b = _make_synthetic_video(work_dir, "conform_B.mov", "testsrc", 660)
        metadata["synthetic_media"] = {"video_a": str(video_a), "video_b": str(video_b)}
        print(f"Generated synthetic media under: {work_dir}")

        resolve = server.get_resolve()
        project = resolve.GetProjectManager().GetCurrentProject()
        media_pool = project.GetMediaPool()
        imported = media_pool.ImportMedia([str(video_a), str(video_b)]) or []
        if len(imported) < 2:
            raise AssertionError("Failed to import synthetic conform media")
        clip_a = _first_imported([imported[0]])
        clip_b = _first_imported([imported[1]])
        if not clip_a or not clip_b:
            raise AssertionError("Failed to resolve imported MediaPoolItems")

        timeline = media_pool.CreateTimelineFromClips(
            timeline_name,
            [{"mediaPoolItem": clip_a, "startFrame": 0, "endFrame": 48, "recordFrame": 86400}],
        )
        if not timeline:
            raise AssertionError("Failed to create conform timeline")
        project.SetCurrentTimeline(timeline)
        media_pool.AppendToTimeline(
            [
                {"mediaPoolItem": clip_b, "startFrame": 0, "endFrame": 48, "recordFrame": 86472, "trackIndex": 1, "mediaType": 1},
                {"mediaPoolItem": clip_b, "startFrame": 0, "endFrame": 48, "recordFrame": 86400, "trackIndex": 1, "mediaType": 2},
            ]
        )
        print(f"Created timeline: {timeline_name}")

        _record_tool_result(recorder, "capabilities", "conform_capabilities", server.timeline("conform_capabilities"))
        _record_tool_result(recorder, "inspection", "probe_timeline_structure", server.timeline("probe_timeline_structure"))
        _record_tool_result(recorder, "analysis", "detect_gaps_overlaps", server.timeline("detect_gaps_overlaps"))
        _record_tool_result(recorder, "analysis", "source_range_report", server.timeline("source_range_report", {"handles": 8}))
        _record_tool_result(recorder, "analysis", "detect_missing_media_initial", server.timeline("detect_missing_media"))
        _record_tool_result(
            recorder,
            "analysis",
            "build_relink_plan_initial",
            server.timeline("build_relink_plan", {"search_roots": [str(work_dir)]}),
        )
        _record_tool_result(recorder, "report", "conform_boundary_report", server.timeline("conform_boundary_report", {"handles": 8}))

        for fmt, suffix in (("fcpxml", ".fcpxml"), ("drt", ".drt"), ("edl", ".edl"), ("aaf", ".aaf"), ("otio", ".otio")):
            result = server.timeline(
                "export_timeline_checked",
                {"format": fmt, "path": str(interchange_dir / f"conform_probe_{fmt}{suffix}")},
            )
            _record_tool_result(
                recorder,
                "interchange.export",
                f"export_{fmt}",
                result,
                expected_status=None if result.get("success") else "version_or_page_dependent",
            )

        for fmt in ("fcpxml", "drt"):
            result = server.timeline(
                "probe_interchange_roundtrip",
                {
                    "format": fmt,
                    "output_dir": str(interchange_dir),
                    "cleanup_imported": True,
                    "import_source_clips": False,
                    "include_clip_properties": False,
                },
            )
            roundtrip_status = None
            if result.get("success") and (result.get("comparison") or {}).get("difference_count", 0):
                roundtrip_status = "partially_supported"
            elif not result.get("success"):
                roundtrip_status = "version_or_page_dependent"
            _record_tool_result(
                recorder,
                "interchange.roundtrip",
                f"roundtrip_{fmt}",
                result,
                expected_status=roundtrip_status,
            )

        # Exercise synthetic-only missing-media and relink surfaces through the
        # existing Media Pool safe wrappers. These operate on generated media.
        clip_b_id = _clip_id(clip_b)
        if clip_b_id:
            _record_tool_result(
                recorder,
                "missing_media.synthetic",
                "safe_unlink_synthetic_clip",
                server.media_pool("safe_unlink", {"clip_ids": [clip_b_id]}),
            )
            _record_tool_result(
                recorder,
                "missing_media.synthetic",
                "detect_missing_media_after_unlink",
                server.timeline("detect_missing_media"),
            )
            _record_tool_result(
                recorder,
                "missing_media.synthetic",
                "build_relink_plan_after_unlink",
                server.timeline("build_relink_plan", {"search_roots": [str(work_dir)]}),
            )
            _record_tool_result(
                recorder,
                "missing_media.synthetic",
                "safe_relink_synthetic_clip",
                server.media_pool("safe_relink", {"clip_ids": [clip_b_id], "folder_path": str(work_dir)}),
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
            "json": str(output_dir / "timeline-conform-probe.json"),
            "markdown": str(output_dir / "timeline-conform-probe.md"),
        },
    )
    json_path = output_dir / "timeline-conform-probe.json"
    markdown_path = output_dir / "timeline-conform-probe.md"
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
