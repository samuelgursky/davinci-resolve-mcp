#!/usr/bin/env python3
"""Live Media Pool / ingest boundary probe.

Creates a disposable Resolve project with generated synthetic media, probes
Media Storage, Media Pool, Folder, MediaPoolItem, and annotation surfaces,
writes JSON/Markdown evidence reports, and deletes the project unless
--keep-open is provided.

Run with Python 3.10-3.12 against a running Resolve Studio instance:

  python3.11 tests/live_media_pool_ingest_validation.py --output-dir /tmp/media-pool-ingest-probe
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
            "partially_supported" if not expected_boundary else "unsupported",
            details={"reason": "success returned false", "expected_boundary": expected_boundary},
            evidence=result,
        )
        return
    if expected_boundary and result.get("imported") == 0:
        recorder.record(
            category,
            name,
            "unsupported",
            details={"reason": "Resolve returned zero imported items for expected negative fixture"},
            evidence=result,
        )
        return
    recorder.record(category, name, "supported", evidence=result)


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args], check=True)


def _make_synthetic_assets(work_dir: Path) -> Dict[str, Path]:
    video = work_dir / "ingest_probe_video.mov"
    video_alt = work_dir / "ingest_probe_video_alt.mov"
    audio = work_dir / "ingest_probe_audio.wav"
    still = work_dir / "ingest_probe_still.png"
    sequence_dir = work_dir / "sequence"
    sequence_dir.mkdir(parents=True, exist_ok=True)

    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24:duration=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=48000:duration=5",
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
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=24:duration=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:sample_rate=48000:duration=5",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-y",
            str(video_alt),
        ]
    )
    _run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", "-y", str(audio)])
    _run_ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=96x54", "-frames:v", "1", "-y", str(still)])
    for index, color in enumerate(("blue", "green", "yellow"), start=1):
        frame_path = sequence_dir / f"ingest_probe_seq_{index:03d}.png"
        _run_ffmpeg(["-f", "lavfi", "-i", f"color=c={color}:s=96x54", "-frames:v", "1", "-y", str(frame_path)])

    unsupported = work_dir / "not_media.txt"
    unsupported.write_text("synthetic non-media boundary fixture\n", encoding="utf-8")
    return {
        "video": video,
        "video_alt": video_alt,
        "audio": audio,
        "still": still,
        "sequence_pattern": sequence_dir / "ingest_probe_seq_%03d.png",
        "unsupported": unsupported,
    }


def _first_imported_clip_id(imported_items) -> Optional[str]:
    for item in imported_items or []:
        try:
            item_id = item.GetUniqueId()
        except Exception:
            item_id = None
        if item_id:
            return str(item_id)
    return None


def run_probe(server, output_dir: Path, keep_open: bool = False) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_media_pool_ingest_probe_"))
    project_name = f"_mcp_media_pool_ingest_probe_{int(time.time())}"
    recorder = ProbeRecorder()
    created_project = False
    delete_result: Optional[Dict[str, Any]] = None

    metadata: Dict[str, Any] = {
        "title": "Media Pool Ingest Kernel Capability Probe",
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
        server.resolve_control("open_page", {"page": "media"})

        assets = _make_synthetic_assets(work_dir)
        metadata["synthetic_media"] = {key: str(value) for key, value in assets.items()}
        print(f"Generated synthetic media under: {work_dir}")

        resolve = server.get_resolve()
        project = resolve.GetProjectManager().GetCurrentProject()
        media_pool = project.GetMediaPool()

        imported_video = media_pool.ImportMedia([str(assets["video"])]) or []
        video_id = _first_imported_clip_id(imported_video)
        if not video_id:
            raise AssertionError("Failed to import synthetic video")
        metadata["video_clip_id"] = video_id
        print(f"Imported video clip: {video_id}")

        imported_target = media_pool.ImportMedia([str(assets["video_alt"])]) or []
        target_video_id = _first_imported_clip_id(imported_target)
        if not target_video_id:
            raise AssertionError("Failed to import target synthetic video")
        metadata["target_video_clip_id"] = target_video_id

        imports = {
            "audio": server.media_pool("import_media", {"paths": [str(assets["audio"])]}),
            "still": server.media_pool("import_media", {"paths": [str(assets["still"])]}),
            "sequence": server.media_pool(
                "import_media",
                {
                    "clip_infos": [
                        {
                            "FilePath": str(assets["sequence_pattern"]),
                            "StartIndex": 1,
                            "EndIndex": 3,
                        }
                    ]
                },
            ),
            "unsupported_text": server.media_pool("import_media", {"paths": [str(assets["unsupported"])]}),
        }
        for name, result in imports.items():
            _record_tool_result(recorder, "imports", name, result, expected_boundary=(name == "unsupported_text"))

        kernel_imports = {
            "safe_import_media_dry_run": server.media_pool(
                "safe_import_media",
                {"paths": [str(assets["audio"])], "dry_run": True},
            ),
            "safe_import_media": server.media_pool(
                "safe_import_media",
                {"paths": [str(assets["audio"])]},
            ),
            "safe_import_sequence": server.media_pool(
                "safe_import_sequence",
                {
                    "pattern": str(assets["sequence_pattern"]),
                    "start_index": 1,
                    "end_index": 3,
                },
            ),
            "safe_import_folder_dry_run": server.media_pool(
                "safe_import_folder",
                {"path": str(work_dir), "dry_run": True},
            ),
        }
        for name, result in kernel_imports.items():
            _record_tool_result(recorder, "kernel_imports", name, result)

        _record_tool_result(recorder, "storage", "get_volumes", server.media_storage("get_volumes"))
        _record_tool_result(
            recorder,
            "storage",
            "get_files_work_dir",
            server.media_storage("get_files", {"path": str(work_dir)}),
        )
        _record_tool_result(recorder, "capabilities", "ingest_capabilities", server.media_pool("ingest_capabilities"))
        _record_tool_result(recorder, "probe", "probe_media_pool", server.media_pool("probe_media_pool", {"depth": 2}))
        _record_tool_result(
            recorder,
            "probe",
            "probe_ingest_item_by_id",
            server.media_pool("probe_ingest_item", {"clip_ids": [video_id]}),
        )
        _record_tool_result(
            recorder,
            "probe",
            "probe_clip_properties",
            server.media_pool("probe_clip_properties", {"clip_ids": [video_id]}),
        )
        _record_tool_result(
            recorder,
            "probe",
            "media_pool_boundary_report",
            server.media_pool("media_pool_boundary_report", {"depth": 1, "clip_ids": [video_id]}),
        )

        _record_tool_result(
            recorder,
            "organization",
            "set_selected",
            server.media_pool("set_selected", {"clip_id": video_id}),
        )
        _record_tool_result(recorder, "organization", "get_selected", server.media_pool("get_selected"))
        _record_tool_result(
            recorder,
            "probe",
            "probe_ingest_item_selected",
            server.media_pool("probe_ingest_item", {"selected": True}),
        )

        subfolder = server.media_pool("add_subfolder", {"name": "Ingest Probe"})
        _record_tool_result(recorder, "organization", "add_subfolder", subfolder)
        _record_tool_result(
            recorder,
            "organization",
            "set_current_folder",
            server.media_pool("set_current_folder", {"path": "Master/Ingest Probe"}),
        )
        _record_tool_result(recorder, "folder", "get_current_folder", server.media_pool("get_current_folder"))
        _record_tool_result(recorder, "folder", "folder_get_subfolders", server.folder("get_subfolders", {"path": "Master"}))
        _record_tool_result(recorder, "folder", "folder_is_stale", server.folder("is_stale", {"path": "Master"}))
        _record_tool_result(recorder, "organization", "reset_current_folder", server.media_pool("set_current_folder", {"path": "Master"}))
        _record_tool_result(
            recorder,
            "organization",
            "organize_clips_dry_run",
            server.media_pool(
                "organize_clips",
                {"clip_ids": [target_video_id], "target_path": "Master/Ingest Probe", "dry_run": True},
            ),
        )
        _record_tool_result(
            recorder,
            "organization",
            "organize_clips",
            server.media_pool(
                "organize_clips",
                {"clip_ids": [target_video_id], "target_path": "Master/Ingest Probe"},
            ),
        )

        _record_tool_result(
            recorder,
            "metadata",
            "set_metadata_scalar",
            server.media_pool_item("set_metadata", {"clip_id": video_id, "key": "Comments", "value": "MCP ingest probe"}),
        )
        _record_tool_result(
            recorder,
            "metadata",
            "get_metadata_comments",
            server.media_pool_item("get_metadata", {"clip_id": video_id, "key": "Comments"}),
        )
        _record_tool_result(
            recorder,
            "metadata",
            "set_third_party_metadata",
            server.media_pool_item(
                "set_third_party_metadata",
                {"clip_id": video_id, "key": "mcp_ingest_probe", "value": "supported"},
            ),
        )
        _record_tool_result(
            recorder,
            "metadata",
            "get_third_party_metadata",
            server.media_pool_item("get_third_party_metadata", {"clip_id": video_id, "key": "mcp_ingest_probe"}),
        )
        _record_tool_result(
            recorder,
            "metadata",
            "get_clip_property_all",
            server.media_pool_item("get_clip_property", {"clip_id": video_id}),
        )
        _record_tool_result(
            recorder,
            "metadata",
            "get_clip_property_file_path",
            server.media_pool_item("get_clip_property", {"clip_id": video_id, "key": "File Path"}),
        )
        _record_tool_result(
            recorder,
            "metadata",
            "normalize_metadata",
            server.media_pool(
                "normalize_metadata",
                {
                    "clip_ids": [target_video_id],
                    "metadata": {"Comments": "MCP normalized metadata"},
                    "third_party_metadata": {"mcp_ingest_normalized": "true"},
                },
            ),
        )
        _record_tool_result(
            recorder,
            "metadata",
            "copy_metadata",
            server.media_pool(
                "copy_metadata",
                {"source_clip_id": video_id, "target_clip_ids": [target_video_id], "include_third_party": True},
            ),
        )

        _record_tool_result(
            recorder,
            "annotations",
            "set_clip_color",
            server.media_pool_item("set_clip_color", {"clip_id": video_id, "color": "Blue"}),
        )
        _record_tool_result(
            recorder,
            "annotations",
            "get_clip_color",
            server.media_pool_item("get_clip_color", {"clip_id": video_id}),
        )
        _record_tool_result(
            recorder,
            "annotations",
            "marker_add",
            server.media_pool_item_markers(
                "add",
                {
                    "clip_id": video_id,
                    "frame": 12,
                    "color": "Blue",
                    "name": "Ingest Probe",
                    "note": "Synthetic media marker",
                    "duration": 1,
                    "custom_data": "mcp-ingest-probe",
                },
            ),
        )
        _record_tool_result(
            recorder,
            "annotations",
            "marker_get_custom_data",
            server.media_pool_item_markers(
                "get_custom_data",
                {"clip_id": video_id, "frame": 12},
            ),
        )
        _record_tool_result(
            recorder,
            "annotations",
            "marker_update_custom_data",
            server.media_pool_item_markers(
                "update_custom_data",
                {"clip_id": video_id, "frame": 12, "custom_data": "mcp-ingest-probe-updated"},
            ),
        )
        _record_tool_result(
            recorder,
            "annotations",
            "flag_add",
            server.media_pool_item_markers("add_flag", {"clip_id": video_id, "color": "Blue"}),
        )
        _record_tool_result(
            recorder,
            "annotations",
            "flag_get",
            server.media_pool_item_markers("get_flags", {"clip_id": video_id}),
        )
        _record_tool_result(
            recorder,
            "annotations",
            "set_mark_in_out",
            server.media_pool_item("set_mark_in_out", {"clip_id": video_id, "mark_in": 0, "mark_out": 24}),
        )
        _record_tool_result(
            recorder,
            "annotations",
            "get_mark_in_out",
            server.media_pool_item("get_mark_in_out", {"clip_id": video_id}),
        )
        _record_tool_result(
            recorder,
            "annotations",
            "set_clip_marks",
            server.media_pool("set_clip_marks", {"clip_ids": [target_video_id], "mark_in": 0, "mark_out": 24}),
        )
        _record_tool_result(
            recorder,
            "annotations",
            "copy_clip_annotations",
            server.media_pool(
                "copy_clip_annotations",
                {"source_clip_id": video_id, "target_clip_ids": [target_video_id]},
            ),
        )

        _record_tool_result(
            recorder,
            "links",
            "link_proxy",
            server.media_pool_item("link_proxy", {"clip_id": video_id, "proxy_path": str(assets["video"])}),
        )
        _record_tool_result(
            recorder,
            "links",
            "unlink_proxy",
            server.media_pool_item("unlink_proxy", {"clip_id": video_id}),
        )
        _record_tool_result(
            recorder,
            "links",
            "link_proxy_checked",
            server.media_pool("link_proxy_checked", {"clip_id": video_id, "proxy_path": str(assets["video"])}),
        )
        _record_tool_result(
            recorder,
            "links",
            "safe_relink_dry_run",
            server.media_pool("safe_relink", {"clip_ids": [video_id], "folder_path": str(work_dir), "dry_run": True}),
        )
        _record_tool_result(
            recorder,
            "links",
            "safe_unlink_dry_run",
            server.media_pool("safe_unlink", {"clip_ids": [video_id], "dry_run": True}),
        )
        _record_tool_result(
            recorder,
            "links",
            "link_full_resolution_checked",
            server.media_pool("link_full_resolution_checked", {"clip_id": video_id, "path": str(assets["video"])}),
        )

        metadata_path = output_dir / "ingest_metadata.csv"
        _record_tool_result(
            recorder,
            "exports",
            "export_metadata",
            server.media_pool("export_metadata", {"path": str(metadata_path), "clip_ids": [video_id]}),
        )

        _record_tool_result(
            recorder,
            "cleanup_mutations",
            "clear_clip_color",
            server.media_pool_item("clear_clip_color", {"clip_id": video_id}),
        )
        _record_tool_result(
            recorder,
            "cleanup_mutations",
            "clear_flags",
            server.media_pool_item_markers("clear_flags", {"clip_id": video_id, "color": "Blue"}),
        )
        _record_tool_result(
            recorder,
            "cleanup_mutations",
            "delete_marker",
            server.media_pool_item_markers("delete_at_frame", {"clip_id": video_id, "frame": 12}),
        )
        _record_tool_result(
            recorder,
            "cleanup_mutations",
            "clear_mark_in_out",
            server.media_pool_item("clear_mark_in_out", {"clip_id": video_id}),
        )
        _record_tool_result(
            recorder,
            "cleanup_mutations",
            "clear_clip_marks",
            server.media_pool("clear_clip_marks", {"clip_ids": [target_video_id]}),
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
            "json": str(output_dir / "media-pool-ingest-probe.json"),
            "markdown": str(output_dir / "media-pool-ingest-probe.md"),
        },
    )
    json_path = output_dir / "media-pool-ingest-probe.json"
    markdown_path = output_dir / "media-pool-ingest-probe.md"
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
