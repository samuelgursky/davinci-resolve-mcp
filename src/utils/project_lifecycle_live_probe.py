#!/usr/bin/env python3
"""Live Project / Database / Archive boundary probe."""

from __future__ import annotations

import json
import platform
import shutil
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


def _delete_disposable_project(server, name: str) -> Dict[str, Any]:
    result = server.project_manager(
        "safe_project_delete",
        {"name": name, "close_current": True, "save_current": True},
    )
    if result.get("error") and "currently open" in result.get("error", ""):
        result = server.project_manager("safe_project_delete", {"name": name})
    return result


def _first_setting_value(snapshot: Dict[str, Any], keys: list[str]) -> Optional[Dict[str, Any]]:
    settings = snapshot.get("settings")
    if not isinstance(settings, dict):
        return None
    for key in keys:
        value = settings.get(key)
        if value not in (None, ""):
            return {key: value}
    return None


def run_probe(server, output_dir: Path, keep_open: bool = False) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_project_lifecycle_probe_"))
    timestamp = int(time.time())
    project_name = f"_mcp_project_lifecycle_probe_{timestamp}"
    imported_name = f"_mcp_project_lifecycle_import_{timestamp}"
    restored_name = f"_mcp_project_lifecycle_restore_{timestamp}"
    archive_restored_name = f"_mcp_project_lifecycle_archive_restore_{timestamp}"
    timeline_name = "Project Lifecycle Probe Timeline"
    folder_name = f"_mcp_project_folder_{timestamp}"
    layout_name = f"_mcp_layout_probe_{timestamp}"
    layout_import_name = f"_mcp_layout_import_{timestamp}"
    cleanup_projects: list[str] = []
    cleanup_layouts: list[str] = []
    delete_results: Dict[str, Any] = {}
    recorder = ProbeRecorder()

    metadata: Dict[str, Any] = {
        "title": "Project / Database / Archive Kernel Capability Probe",
        "timestamp_utc": utc_timestamp(),
        "python": sys.version,
        "platform": platform.platform(),
        "output_dir": str(output_dir),
        "work_dir": str(work_dir),
        "project_name": project_name,
        "imported_project_name": imported_name,
        "restored_project_name": restored_name,
        "archive_restored_project_name": archive_restored_name,
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

        _record_tool_result(recorder, "capabilities", "project_capabilities_pre_create", server.project_manager("project_capabilities"))
        _record_tool_result(recorder, "database", "database_capabilities_pre_create", server.project_manager("database_capabilities"))
        db_caps = server.project_manager("database_capabilities")
        if isinstance(db_caps, dict) and db_caps.get("current"):
            _record_tool_result(
                recorder,
                "database",
                "safe_set_current_database_dry_run",
                server.project_manager("safe_set_current_database", {"db_info": db_caps["current"]}),
            )

        create_result = server.project_manager("safe_project_create", {"name": project_name})
        _require_success("project_manager.safe_project_create", create_result)
        cleanup_projects.append(project_name)
        print(f"Created disposable project: {project_name}")

        _record_tool_result(recorder, "lifecycle", "safe_project_create", create_result)
        _record_tool_result(recorder, "lifecycle", "get_current", server.project_manager("get_current"))
        _record_tool_result(recorder, "lifecycle", "create_empty_timeline", server.media_pool("create_timeline", {"name": timeline_name}))
        _record_tool_result(recorder, "lifecycle", "save_project_before_export", server.project_manager("save"))
        _record_tool_result(recorder, "lifecycle", "probe_project_lifecycle", server.project_manager("probe_project_lifecycle"))
        _record_tool_result(recorder, "settings", "project_settings_snapshot", server.project_manager("project_settings_snapshot"))

        snapshot = server.project_manager("project_settings_snapshot")
        setting_payload = _first_setting_value(
            snapshot if isinstance(snapshot, dict) else {},
            ["timelineResolutionWidth", "timelineResolutionHeight", "timelineFrameRate"],
        )
        if setting_payload:
            _record_tool_result(
                recorder,
                "settings",
                "safe_set_project_settings_same_value_restore",
                server.project_manager("safe_set_project_settings", {"settings": setting_payload, "restore": True}),
            )
        else:
            recorder.record(
                "settings",
                "safe_set_project_settings_same_value_restore",
                "not_applicable",
                details={"reason": "No non-empty candidate project setting was readable"},
                evidence=snapshot,
            )

        _record_tool_result(
            recorder,
            "settings",
            "probe_project_settings_try_write_dry_run",
            server.project_manager("probe_project_settings", {"try_write": True, "dry_run": True}),
        )
        _record_tool_result(recorder, "presets", "preset_lifecycle_probe", server.project_manager("preset_lifecycle_probe"))

        drp_path = work_dir / "project-lifecycle-export.drp"
        archive_path = work_dir / "project-lifecycle-archive.dra"
        archive_folder_path = work_dir / "project-lifecycle-archive-folder"
        _record_tool_result(
            recorder,
            "lifecycle",
            "safe_project_export",
            server.project_manager("safe_project_export", {"name": project_name, "path": str(drp_path)}),
        )
        if drp_path.exists():
            import_result = server.project_manager("safe_project_import", {"name": imported_name, "path": str(drp_path)})
            if import_result.get("success"):
                cleanup_projects.append(imported_name)
            _record_tool_result(recorder, "lifecycle", "safe_project_import", import_result)

            restore_result = server.project_manager("safe_project_restore", {"name": restored_name, "path": str(drp_path)})
            if restore_result.get("success"):
                cleanup_projects.append(restored_name)
            _record_tool_result(recorder, "lifecycle", "safe_project_restore_from_drp", restore_result)
        else:
            recorder.record(
                "lifecycle",
                "safe_project_import",
                "not_applicable",
                details={"reason": "DRP export path was not created"},
            )
            recorder.record(
                "lifecycle",
                "safe_project_restore_from_drp",
                "not_applicable",
                details={"reason": "DRP export path was not created"},
            )

        archive_file_result = server.project_manager(
            "safe_project_archive",
            {
                "name": project_name,
                "path": str(archive_path),
                "src_media": False,
                "render_cache": False,
                "proxy_media": False,
            },
        )
        _record_tool_result(
            recorder,
            "archive",
            "safe_project_archive_no_media_dra_path",
            archive_file_result,
            expected_status=None if archive_file_result.get("success") else "partially_supported",
        )
        archive_folder_result = server.project_manager(
            "safe_project_archive",
            {
                "name": project_name,
                "path": str(archive_folder_path),
                "src_media": False,
                "render_cache": False,
                "proxy_media": False,
            },
        )
        _record_tool_result(
            recorder,
            "archive",
            "safe_project_archive_no_media_folder_path",
            archive_folder_result,
            expected_status=None if archive_folder_result.get("success") else "partially_supported",
        )
        archive_restore_source = archive_path if archive_file_result.get("success") else archive_folder_path
        if archive_file_result.get("success") or archive_folder_result.get("success"):
            archive_restore = server.project_manager(
                "safe_project_restore",
                {"name": archive_restored_name, "path": str(archive_restore_source)},
            )
            if archive_restore.get("success"):
                cleanup_projects.append(archive_restored_name)
            _record_tool_result(
                recorder,
                "archive",
                "safe_project_restore_from_archive",
                archive_restore,
                expected_status=None if archive_restore.get("success") else "partially_supported",
            )
        else:
            recorder.record(
                "archive",
                "safe_project_restore_from_archive",
                "not_applicable",
                details={"reason": "No archive path was created successfully"},
            )
        _record_tool_result(
            recorder,
            "archive",
            "safe_project_archive_rejects_media_flags",
            server.project_manager(
                "safe_project_archive",
                {"name": project_name, "path": str(work_dir / "reject.dra"), "src_media": True, "dry_run": True},
            ),
            expected_status="unsupported",
        )

        _record_tool_result(recorder, "folders", "folder_list_before", server.project_manager_folders("list"))
        _record_tool_result(recorder, "folders", "folder_create", server.project_manager_folders("create", {"name": folder_name}))
        _record_tool_result(recorder, "folders", "folder_open", server.project_manager_folders("open", {"name": folder_name}))
        _record_tool_result(recorder, "folders", "folder_get_current", server.project_manager_folders("get_current"))
        _record_tool_result(recorder, "folders", "folder_goto_parent", server.project_manager_folders("goto_parent"))
        _record_tool_result(recorder, "folders", "folder_delete", server.project_manager_folders("delete", {"name": folder_name}))

        for page in ["media", "cut", "edit", "fusion", "color", "fairlight", "deliver"]:
            _record_tool_result(
                recorder,
                "app_state",
                f"open_page_{page}",
                server.resolve_control("open_page", {"page": page}),
                expected_status=None,
            )
        _record_tool_result(recorder, "app_state", "get_page", server.resolve_control("get_page"))
        keyframe_mode = server.resolve_control("get_keyframe_mode")
        _record_tool_result(recorder, "app_state", "get_keyframe_mode", keyframe_mode)
        if isinstance(keyframe_mode, dict) and "mode" in keyframe_mode:
            _record_tool_result(
                recorder,
                "app_state",
                "set_keyframe_mode_same_value",
                server.resolve_control("set_keyframe_mode", {"mode": keyframe_mode["mode"]}),
            )

        layout_path = work_dir / "layout-preset.layout"
        layout_save = server.layout_presets("save", {"name": layout_name})
        if layout_save.get("success"):
            cleanup_layouts.append(layout_name)
        _record_tool_result(recorder, "presets", "layout_save", layout_save)
        _record_tool_result(recorder, "presets", "layout_update", server.layout_presets("update", {"name": layout_name}))
        _record_tool_result(recorder, "presets", "layout_load", server.layout_presets("load", {"name": layout_name}))
        _record_tool_result(recorder, "presets", "layout_export", server.layout_presets("export", {"name": layout_name, "path": str(layout_path)}))
        if layout_path.exists():
            layout_import = server.layout_presets("import_preset", {"name": layout_import_name, "path": str(layout_path)})
            if layout_import.get("success"):
                cleanup_layouts.append(layout_import_name)
            _record_tool_result(recorder, "presets", "layout_import", layout_import)
        else:
            recorder.record(
                "presets",
                "layout_import",
                "not_applicable",
                details={"reason": "layout export path was not created"},
            )

        preset_probe = server.project_manager("preset_lifecycle_probe")
        render_presets = []
        if isinstance(preset_probe, dict):
            render_presets = preset_probe.get("render_presets", {}).get("items", []) or []
        if render_presets:
            render_preset_name = render_presets[0].get("Name") if isinstance(render_presets[0], dict) else render_presets[0]
            if render_preset_name:
                _record_tool_result(
                    recorder,
                    "presets",
                    "render_preset_export",
                    server.render_presets("export_render", {"name": render_preset_name, "path": str(work_dir / "render-preset.xml")}),
                    expected_status=None,
                )
        else:
            recorder.record(
                "presets",
                "render_preset_export",
                "not_applicable",
                details={"reason": "No render presets were listed"},
                evidence=preset_probe,
            )

        _record_tool_result(recorder, "report", "project_boundary_report", server.project_manager("project_boundary_report"))

        if keep_open:
            server.project_manager("save")
            print(f"LEFT PROJECTS OPEN FOR INSPECTION: {cleanup_projects}")
            cleanup_projects = []

    finally:
        for layout_name_to_delete in reversed(cleanup_layouts):
            delete_results[f"layout:{layout_name_to_delete}"] = server.layout_presets("delete", {"name": layout_name_to_delete})
            print(f"Deleted layout preset {layout_name_to_delete}: {delete_results[f'layout:{layout_name_to_delete}']}")
        if not keep_open:
            for disposable_project in reversed(cleanup_projects):
                delete_results[f"project:{disposable_project}"] = _delete_disposable_project(server, disposable_project)
                print(f"Deleted disposable project {disposable_project}: {delete_results[f'project:{disposable_project}']}")

    metadata["cleanup"] = delete_results
    report = recorder.to_report(
        metadata,
        {
            "json": str(output_dir / "project-lifecycle-probe.json"),
            "markdown": str(output_dir / "project-lifecycle-probe.md"),
        },
    )
    json_path = output_dir / "project-lifecycle-probe.json"
    markdown_path = output_dir / "project-lifecycle-probe.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    print(f"Wrote JSON report: {json_path}")
    print(f"Wrote Markdown report: {markdown_path}")
    print(f"Counts: {json.dumps(report['counts'], sort_keys=True)}")
    if not keep_open:
        shutil.rmtree(work_dir, ignore_errors=True)
        print(f"Removed project lifecycle work directory: {work_dir}")

    failed_cleanup = {key: value for key, value in delete_results.items() if value.get("success") is not True and not value.get("error", "").startswith("No ")}
    if failed_cleanup:
        raise AssertionError(f"Cleanup failed: {failed_cleanup!r}")
    return report
