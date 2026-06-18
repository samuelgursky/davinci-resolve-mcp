#!/usr/bin/env python3
"""Live Render / Deliver boundary probe.

Creates a disposable Resolve project with generated synthetic media, probes
render format/codec/settings/job/quick-export surfaces, writes JSON/Markdown
evidence reports, deletes the project, and removes generated media/render
outputs.
"""

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
    partial_on_false: bool = True,
) -> None:
    if not isinstance(result, dict):
        recorder.record(category, name, "error", details={"reason": "non-dict result", "result": repr(result)})
        return
    if result.get("error"):
        recorder.record(category, name, "error", details={"reason": result.get("error")}, evidence=result)
        return
    if "success" in result and result["success"] is not True:
        recorder.record(
            category,
            name,
            "partially_supported" if partial_on_false else "unsupported",
            details={"reason": "success returned false"},
            evidence=result,
        )
        return
    recorder.record(category, name, "supported", evidence=result)


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args], check=True, timeout=120)


def _make_synthetic_video(work_dir: Path) -> Path:
    video = work_dir / "render_probe_source.mov"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=48000:duration=2",
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


def _choose_render_format_codec(server) -> Dict[str, Optional[str]]:
    formats_result = server.render("get_formats")
    formats = formats_result.get("formats") if isinstance(formats_result, dict) else {}
    if not isinstance(formats, dict) or not formats:
        return {"format": None, "codec": None, "label": None}

    preferred_formats = ["mp4", "QuickTime"]
    format_names = [fmt for fmt in preferred_formats if fmt in formats]
    format_names.extend([fmt for fmt in formats if fmt not in format_names])

    for fmt in format_names:
        codecs_result = server.render("get_codecs", {"format": fmt})
        codecs = codecs_result.get("codecs") if isinstance(codecs_result, dict) else {}
        if not isinstance(codecs, dict) or not codecs:
            continue
        preferred = []
        for label, codec in codecs.items():
            text = f"{label} {codec}".lower()
            if "h.264" in text or "h264" in text:
                preferred.insert(0, (label, codec))
            else:
                preferred.append((label, codec))
        label, codec = preferred[0]
        return {"format": fmt, "codec": codec, "label": label}
    return {"format": None, "codec": None, "label": None}


def _render_output_files(render_dir: Path):
    if not render_dir.exists():
        return []
    return sorted(str(path) for path in render_dir.iterdir() if path.is_file())


def run_probe(server, output_dir: Path, keep_open: bool = False) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_render_deliver_probe_"))
    render_dir = output_dir / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    project_name = f"_mcp_render_deliver_probe_{int(time.time())}"
    timeline_name = "Render Deliver Probe Timeline"
    preset_name = f"_mcp_render_probe_preset_{int(time.time())}"
    recorder = ProbeRecorder()
    created_project = False
    delete_result: Optional[Dict[str, Any]] = None

    metadata: Dict[str, Any] = {
        "title": "Render Deliver Kernel Capability Probe",
        "timestamp_utc": utc_timestamp(),
        "python": sys.version,
        "platform": platform.platform(),
        "output_dir": str(output_dir),
        "project_name": project_name,
        "render_dir": str(render_dir),
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
            raise AssertionError("Failed to import synthetic render media")
        timeline = media_pool.CreateTimelineFromClips(timeline_name, [clip])
        if not timeline:
            raise AssertionError("Failed to create synthetic render timeline")
        project.SetCurrentTimeline(timeline)
        print(f"Created timeline: {timeline_name}")

        chosen = _choose_render_format_codec(server)
        metadata["chosen_format_codec"] = chosen
        render_settings = {
            "TargetDir": str(render_dir),
            "CustomName": "mcp_render_probe",
            "SelectAllFrames": True,
            "ExportVideo": True,
            "ExportAudio": True,
            "FormatWidth": 320,
            "FormatHeight": 180,
            "FrameRate": 24,
            "VideoQuality": "Least",
            "EnableUpload": False,
        }
        safe_settings = {key: value for key, value in render_settings.items() if key != "EnableUpload"}

        _record_tool_result(recorder, "capabilities", "render_capabilities", server.render("render_capabilities"))
        _record_tool_result(recorder, "matrix", "probe_render_matrix", server.render("probe_render_matrix"))
        settings_snapshot = server.render("probe_render_settings")
        _record_tool_result(recorder, "settings", "probe_render_settings", settings_snapshot)
        if isinstance(settings_snapshot.get("settings"), dict) and settings_snapshot["settings"].get("error"):
            recorder.record(
                "settings",
                "get_render_settings_readback",
                "version_or_page_dependent",
                details={"reason": settings_snapshot["settings"]["error"]},
            )
        if chosen["format"] and chosen["codec"]:
            _record_tool_result(
                recorder,
                "format_codec",
                "set_format_and_codec",
                server.render(
                    "set_format_and_codec",
                    {"format": chosen["format"], "codec": chosen["codec"]},
                ),
            )
            _record_tool_result(
                recorder,
                "format_codec",
                "get_resolutions_chosen",
                server.render("get_resolutions", {"format": chosen["format"], "codec": chosen["codec"]}),
            )
        else:
            recorder.record("format_codec", "choose_format_codec", "unsupported", details={"reason": "No render codec available"})
        _record_tool_result(
            recorder,
            "settings",
            "validate_render_settings",
            server.render(
                "validate_render_settings",
                {"settings": safe_settings, "require_temp_target": True},
            ),
        )
        _record_tool_result(
            recorder,
            "settings",
            "safe_set_render_settings",
            server.render(
                "safe_set_render_settings",
                {"settings": safe_settings, "require_temp_target": True},
            ),
        )

        _record_tool_result(recorder, "mode", "get_mode", server.render("get_mode"))
        current_mode = server.render("get_mode").get("mode", 0)
        _record_tool_result(recorder, "mode", "set_mode_restore", server.render("set_mode", {"mode": current_mode}))

        _record_tool_result(recorder, "presets", "list_presets", server.render("list_presets"))
        _record_tool_result(recorder, "presets", "save_preset", server.render("save_preset", {"name": preset_name}))
        _record_tool_result(recorder, "presets", "delete_preset", server.render("delete_preset", {"name": preset_name}))

        prepare_params = {
            "target_dir": str(render_dir),
            "settings": safe_settings,
            "custom_name": "mcp_render_probe_prepare",
            "dry_run": True,
        }
        if chosen["format"] and chosen["codec"]:
            prepare_params.update({"format": chosen["format"], "codec": chosen["codec"]})
        _record_tool_result(recorder, "jobs", "prepare_render_job_dry_run", server.render("prepare_render_job", prepare_params))

        lifecycle_params = {
            "target_dir": str(render_dir),
            "settings": safe_settings,
            "custom_name": "mcp_render_probe_lifecycle",
        }
        if chosen["format"] and chosen["codec"]:
            lifecycle_params.update({"format": chosen["format"], "codec": chosen["codec"]})
        _record_tool_result(
            recorder,
            "jobs",
            "render_job_lifecycle_probe",
            server.render("render_job_lifecycle_probe", lifecycle_params),
        )

        actual_params = {
            "target_dir": str(render_dir),
            "settings": {**safe_settings, "CustomName": "mcp_render_probe_actual"},
            "custom_name": "mcp_render_probe_actual",
        }
        if chosen["format"] and chosen["codec"]:
            actual_params.update({"format": chosen["format"], "codec": chosen["codec"]})
        prepared = server.render("prepare_render_job", actual_params)
        _record_tool_result(recorder, "jobs", "prepare_render_job", prepared)
        job_id = prepared.get("job_id") if isinstance(prepared, dict) else None
        if job_id:
            _record_tool_result(recorder, "jobs", "get_job_status_before_start", server.render("get_job_status", {"job_id": job_id}))
            start_result = server.render("start", {"job_ids": [job_id], "interactive": False})
            _record_tool_result(recorder, "jobs", "start_rendering", start_result)
            deadline = time.time() + 45
            while time.time() < deadline:
                rendering = server.render("is_rendering")
                if not rendering.get("rendering"):
                    break
                time.sleep(1)
            final_rendering = server.render("is_rendering")
            if final_rendering.get("rendering"):
                server.render("stop")
                recorder.record(
                    "jobs",
                    "render_completion",
                    "partially_supported",
                    details={"reason": "Render exceeded 45 second probe timeout and was stopped"},
                )
            else:
                files = _render_output_files(render_dir)
                status = "supported" if files else "write_only_unverifiable"
                recorder.record("jobs", "render_completion", status, evidence={"files": files})
            _record_tool_result(recorder, "jobs", "get_job_status_after_start", server.render("get_job_status", {"job_id": job_id}))
            _record_tool_result(recorder, "jobs", "delete_render_job", server.render("delete_job", {"job_id": job_id}))

        quick_caps = server.render("quick_export_capabilities")
        _record_tool_result(recorder, "quick_export", "quick_export_capabilities", quick_caps)
        quick_presets = quick_caps.get("presets") if isinstance(quick_caps, dict) else []
        if quick_presets:
            preset = quick_presets[0] if isinstance(quick_presets[0], str) else quick_presets[0].get("Name")
            _record_tool_result(
                recorder,
                "quick_export",
                "safe_quick_export_dry_run",
                server.render(
                    "safe_quick_export",
                    {
                        "preset": preset,
                        "target_dir": str(render_dir),
                        "custom_name": "mcp_quick_export_probe",
                        "dry_run": True,
                    },
                ),
            )
        else:
            recorder.record("quick_export", "safe_quick_export_dry_run", "not_applicable", details={"reason": "No quick export presets"})

        _record_tool_result(
            recorder,
            "report",
            "export_render_boundary_report",
            server.render("export_render_boundary_report", {"max_pairs": 20}),
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
            "json": str(output_dir / "render-deliver-probe.json"),
            "markdown": str(output_dir / "render-deliver-probe.md"),
        },
    )
    json_path = output_dir / "render-deliver-probe.json"
    markdown_path = output_dir / "render-deliver-probe.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    print(f"Wrote JSON report: {json_path}")
    print(f"Wrote Markdown report: {markdown_path}")
    print(f"Counts: {json.dumps(report['counts'], sort_keys=True)}")
    if not keep_open:
        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(render_dir, ignore_errors=True)
        print(f"Removed synthetic media directory: {work_dir}")
        print(f"Removed render output directory: {render_dir}")

    if delete_result and delete_result.get("success") is not True:
        raise AssertionError(f"Cleanup failed for {project_name}: {delete_result!r}")
    return report
