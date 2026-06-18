#!/usr/bin/env python3
"""Live Audio / Fairlight boundary probe."""

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
        recorder.record(category, name, expected_status or "partially_supported", details={"reason": "success returned false"}, evidence=result)
        return
    recorder.record(category, name, expected_status or "supported", evidence=result)


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args], check=True, timeout=120)


def _make_synthetic_media(work_dir: Path) -> Dict[str, Path]:
    video = work_dir / "audio_fairlight_video.mov"
    audio = work_dir / "audio_fairlight_audio.wav"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=24:duration=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=3",
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
    _run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", "-y", str(audio)])
    return {"video": video, "audio": audio}


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
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_audio_fairlight_probe_"))
    project_name = f"_mcp_audio_fairlight_probe_{int(time.time())}"
    timeline_name = "Audio Fairlight Probe"
    recorder = ProbeRecorder()
    created_project = False
    delete_result: Optional[Dict[str, Any]] = None

    metadata: Dict[str, Any] = {
        "title": "Audio / Fairlight Kernel Capability Probe",
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

        assets = _make_synthetic_media(work_dir)
        metadata["synthetic_media"] = {key: str(value) for key, value in assets.items()}
        print(f"Generated synthetic media under: {work_dir}")

        resolve = server.get_resolve()
        project = resolve.GetProjectManager().GetCurrentProject()
        media_pool = project.GetMediaPool()
        imported = media_pool.ImportMedia([str(assets["video"]), str(assets["audio"])]) or []
        if len(imported) < 2:
            raise AssertionError("Failed to import synthetic audio media")
        video_clip = _first_imported([imported[0]])
        audio_clip = _first_imported([imported[1]])
        if not video_clip or not audio_clip:
            raise AssertionError("Failed to resolve imported audio MediaPoolItems")
        timeline = media_pool.CreateTimelineFromClips(timeline_name, [video_clip])
        if not timeline:
            raise AssertionError("Failed to create audio timeline")
        project.SetCurrentTimeline(timeline)
        print(f"Created timeline: {timeline_name}")

        video_clip_id = _clip_id(video_clip)
        audio_clip_id = _clip_id(audio_clip)
        clip_ids = [clip_id for clip_id in (video_clip_id, audio_clip_id) if clip_id]

        _record_tool_result(recorder, "capabilities", "audio_capabilities", server.timeline("audio_capabilities"))
        _record_tool_result(recorder, "track", "probe_audio_track", server.timeline("probe_audio_track", {"track_index": 1}))
        _record_tool_result(recorder, "item", "probe_audio_item", server.timeline("probe_audio_item", {"track_type": "audio", "track_index": 1, "item_index": 0}))
        _record_tool_result(
            recorder,
            "item",
            "safe_set_audio_properties_dry_run",
            server.timeline("safe_set_audio_properties", {"track_type": "audio", "track_index": 1, "item_index": 0, "properties": {"Volume": -3}, "dry_run": True}),
        )
        _record_tool_result(
            recorder,
            "item",
            "safe_set_audio_properties_restore",
            server.timeline("safe_set_audio_properties", {"track_type": "audio", "track_index": 1, "item_index": 0, "properties": {"Volume": -3}, "restore": True}),
        )
        _record_tool_result(recorder, "voice", "voice_isolation_capabilities", server.timeline("voice_isolation_capabilities", {"track_index": 1, "track_type": "audio"}))
        _record_tool_result(recorder, "mapping", "audio_mapping_report", server.timeline("audio_mapping_report", {"clip_ids": clip_ids}))
        _record_tool_result(
            recorder,
            "sync",
            "safe_auto_sync_audio_dry_run",
            server.timeline("safe_auto_sync_audio", {"clip_ids": clip_ids, "settings": {"syncBy": "waveform", "channel": "auto"}, "dry_run": True}),
        )
        auto_sync = server.timeline("safe_auto_sync_audio", {"clip_ids": clip_ids, "settings": {"syncBy": "waveform", "channel": "auto"}, "dry_run": False})
        _record_tool_result(
            recorder,
            "sync",
            "safe_auto_sync_audio_execute",
            auto_sync,
            expected_status=None if auto_sync.get("success") else "partially_supported",
        )
        _record_tool_result(recorder, "transcription", "transcription_capabilities", server.timeline("transcription_capabilities", {"clip_ids": clip_ids}))

        if video_clip_id:
            transcribe = server.media_pool_item("transcribe_audio", {"clip_id": video_clip_id})
            _record_tool_result(
                recorder,
                "transcription",
                "media_pool_item_transcribe_audio",
                transcribe,
                expected_status=None if transcribe.get("success") else "version_or_page_dependent",
            )
            clear = server.media_pool_item("clear_transcription", {"clip_id": video_clip_id})
            _record_tool_result(
                recorder,
                "transcription",
                "media_pool_item_clear_transcription",
                clear,
                expected_status=None if clear.get("success") else "version_or_page_dependent",
            )

        subtitles = server.timeline("subtitle_generation_probe", {"settings": {}, "allow_generate": True})
        _record_tool_result(
            recorder,
            "subtitles",
            "subtitle_generation_probe_execute",
            subtitles,
            expected_status=None if subtitles.get("success") else "version_or_page_dependent",
        )

        _record_tool_result(
            recorder,
            "fairlight",
            "get_fairlight_presets",
            server.resolve_control("get_fairlight_presets"),
            expected_status=None,
        )
        _record_tool_result(
            recorder,
            "fairlight",
            "insert_audio",
            server.project_settings("insert_audio", {"media_path": str(assets["audio"]), "start_offset": 0, "duration": 24}),
        )
        _record_tool_result(recorder, "report", "fairlight_boundary_report", server.timeline("fairlight_boundary_report", {"clip_ids": clip_ids}))

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
            "json": str(output_dir / "audio-fairlight-probe.json"),
            "markdown": str(output_dir / "audio-fairlight-probe.md"),
        },
    )
    json_path = output_dir / "audio-fairlight-probe.json"
    markdown_path = output_dir / "audio-fairlight-probe.md"
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
