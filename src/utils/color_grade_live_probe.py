#!/usr/bin/env python3
"""Live Color / Grade boundary probe."""

from __future__ import annotations

import hashlib
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
from .resolve_writes import set_current_timeline, describe_switch_failure


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



# ── api_truth re-verification ────────────────────────────────────────────────
#
# The entries these confirm were measured on Studio 21.1.0.14. A fact nobody can
# re-measure decays into folklore the moment Blackmagic ships a build, so each
# check below re-derives the behaviour and records `drifted` when what it sees
# stops matching what api_truth claims. The point is not to pass; it is to
# notice when the answer changes.

_LUT_PAGES = ("media", "edit", "fusion", "fairlight", "deliver", "color")


def _lut_digest(path: Path) -> Optional[str]:
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _verify_copygrades_replaces_wholesale(recorder, resolve, items, work_dir: Path) -> None:
    """TimelineItem.CopyGrades: does it still replace, and still leave no version?

    Measured by baking each state to a 33-point LUT and comparing bytes. There is
    no GetCDL to read back, and GetToolsInNode reports only which tools exist —
    it returns the same list either way — so the exported LUT is the only handle
    on what the grade actually became.
    """
    if len(items) < 2:
        recorder.record("api_truth", "CopyGrades_replaces_wholesale", "not_applicable",
                        details={"reason": "probe timeline has fewer than two items"})
        return

    src, tgt = items[0], items[1]
    lut_type = resolve.EXPORT_LUT_33PTCUBE
    hand = work_dir / "trap_target_handwork.cube"
    source = work_dir / "trap_source_grade.cube"
    after = work_dir / "trap_target_after_copy.cube"

    # Every return here is checked. SetCDL and ExportLUT both report refusal as a
    # bare False, and a probe that grades nothing, exports nothing, and then
    # compares two identical empty LUTs would conclude "no replacement" with
    # total confidence. A measurement built on unchecked setup is worse than no
    # measurement, because it gets written down as a fact.
    setup: Dict[str, bool] = {}
    try:
        setup["target_reset"] = bool(tgt.GetNodeGraph().ResetAllGrades())
        setup["target_setcdl"] = bool(tgt.SetCDL(
            {"NodeIndex": "1", "Slope": "0.5 0.5 1.5", "Offset": "0.1 0.1 0.1",
             "Power": "1.0 1.0 1.0", "Saturation": "0.3"}))
        versions_before = list(tgt.GetVersionNameList(0) or [])
        setup["export_handwork"] = bool(tgt.ExportLUT(lut_type, str(hand)))

        setup["source_reset"] = bool(src.GetNodeGraph().ResetAllGrades())
        setup["source_setcdl"] = bool(src.SetCDL(
            {"NodeIndex": "1", "Slope": "2.0 1.0 1.0", "Offset": "0.0 0.0 0.0",
             "Power": "1.0 1.0 1.0", "Saturation": "1.0"}))
        setup["export_source"] = bool(src.ExportLUT(lut_type, str(source)))

        returned = bool(src.CopyGrades([tgt]))
        setup["export_after"] = bool(tgt.ExportLUT(lut_type, str(after)))
        versions_after = list(tgt.GetVersionNameList(0) or [])
    except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
        recorder.record_exception("api_truth", "CopyGrades_replaces_wholesale", exc)
        return

    # Only the calls the measurement actually depends on can abort it. The two
    # resets are best-effort tidying: the stubs type ResetAllGrades as -> bool,
    # but "nothing to reset" plausibly returns False on an already-clean graph,
    # and gating on that would abort every run. Their returns are still recorded
    # rather than dropped.
    required = ("target_setcdl", "export_handwork",
                "source_setcdl", "export_source", "export_after")
    failed_setup = sorted(k for k in required if not setup.get(k))
    if failed_setup:
        recorder.record(
            "api_truth", "CopyGrades_replaces_wholesale", "error",
            details={"setup": setup, "failed_setup": failed_setup,
                     "reason": "probe setup did not take, so nothing below would be "
                               "a measurement of CopyGrades"},
        )
        _cleanup_exported_files([{"path": str(f)} for f in (hand, source, after)])
        return

    d_hand, d_source, d_after = _lut_digest(hand), _lut_digest(source), _lut_digest(after)
    replaced = d_after is not None and d_after == d_source and d_after != d_hand
    made_version = versions_after != versions_before

    details = {
        "setup": setup,
        "copygrades_returned": returned,
        "handwork_digest": d_hand,
        "source_digest": d_source,
        "target_after_copy_digest": d_after,
        "target_became_byte_identical_to_source": replaced,
        "versions_before": versions_before,
        "versions_after": versions_after,
        "created_a_recovery_version": made_version,
        "api_truth_claims": "replaces wholesale, returns True, creates no version",
    }
    # api_truth says: replaced and unrecoverable. Anything else is news.
    if replaced and not made_version:
        recorder.record("api_truth", "CopyGrades_replaces_wholesale", "supported", details=details)
    else:
        details["drifted"] = (
            "CopyGrades no longer matches its api_truth entry — re-read the entry "
            "and the destroys_prior_work flag before trusting either."
        )
        recorder.record("api_truth", "CopyGrades_replaces_wholesale", "error", details=details)

    _cleanup_exported_files([{"path": str(f)} for f in (hand, source, after)])


def _verify_exportlut_page_gate(recorder, server, resolve, items, work_dir: Path) -> None:
    """TimelineItem.ExportLUT: still Color-page only, still no stale file?"""
    if not items:
        recorder.record("api_truth", "ExportLUT_page_gated", "not_applicable",
                        details={"reason": "no timeline items"})
        return

    item = items[0]
    lut_type = resolve.EXPORT_LUT_33PTCUBE
    by_page = {}
    written = []
    try:
        for page in _LUT_PAGES:
            server.resolve_control("open_page", {"page": page})
            out = work_dir / f"trap_lut_{page}.cube"
            returned = bool(item.ExportLUT(lut_type, str(out)))
            exists = out.exists()
            by_page[page] = {"returned": returned, "wrote_file": exists}
            if exists:
                written.append({"path": str(out)})
        server.resolve_control("open_page", {"page": "color"})
    except Exception as exc:  # noqa: BLE001
        recorder.record_exception("api_truth", "ExportLUT_page_gated", exc)
        return

    off_page = [p for p in _LUT_PAGES if p != "color"]
    gated = (
        by_page.get("color", {}).get("returned") is True
        and all(by_page[p]["returned"] is False for p in off_page)
    )
    stale = [p for p in off_page if by_page[p]["wrote_file"]]

    details = {"by_page": by_page, "stale_files_written_on_failure": stale,
               "api_truth_claims": "True only on color; no file written elsewhere"}
    if gated and not stale:
        recorder.record("api_truth", "ExportLUT_page_gated", "version_or_page_dependent", details=details)
    else:
        details["drifted"] = "ExportLUT page behaviour no longer matches its api_truth entry."
        recorder.record("api_truth", "ExportLUT_page_gated", "error", details=details)

    _cleanup_exported_files(written)


def _verify_duplicatetimeline_moves_pointer(recorder, project, timeline) -> None:
    """Timeline.DuplicateTimeline: does it still silently steal `current`?"""
    try:
        before_id = timeline.GetUniqueId()
        dup = timeline.DuplicateTimeline("Trap Probe Duplicate")
        if dup is None:
            recorder.record("api_truth", "DuplicateTimeline_moves_current", "error",
                            details={"reason": "DuplicateTimeline returned None"})
            return
        current = project.GetCurrentTimeline()
        moved = bool(current) and current.GetUniqueId() != before_id
        restored, _ = set_current_timeline(project, timeline)
    except Exception as exc:  # noqa: BLE001
        recorder.record_exception("api_truth", "DuplicateTimeline_moves_current", exc)
        return

    details = {
        "current_moved_to_duplicate": moved,
        "setcurrenttimeline_restored_it": bool(restored),
        "api_truth_claims": "the pointer moves to the duplicate; SetCurrentTimeline restores it",
    }
    if moved and restored:
        recorder.record("api_truth", "DuplicateTimeline_moves_current", "supported", details=details)
    else:
        details["drifted"] = (
            "DuplicateTimeline pointer behaviour changed — timeline_versioning "
            "compensates for it, so check that code too."
        )
        recorder.record("api_truth", "DuplicateTimeline_moves_current", "error", details=details)


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
        # A discarded False here would run the whole probe against whatever
        # timeline was already current, and every measurement below would be a
        # reading of the wrong thing reported as a reading of this one.
        switched, switch_detail = set_current_timeline(project, timeline)
        if not switched:
            raise AssertionError(
                describe_switch_failure(switch_detail, "probing the color grade timeline"))
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

        # Re-measure the api_truth entries this probe is the home for. Runs last:
        # it deliberately overwrites grades on the probe clips.
        _verify_copygrades_replaces_wholesale(recorder, resolve, items, work_dir)
        _verify_exportlut_page_gate(recorder, server, resolve, items, work_dir)
        _verify_duplicatetimeline_moves_pointer(recorder, project, timeline)

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
