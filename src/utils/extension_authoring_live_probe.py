#!/usr/bin/env python3
"""Live Extension Authoring boundary probe."""

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


def _record_nested_success(
    recorder: ProbeRecorder,
    category: str,
    name: str,
    result: Dict[str, Any],
    keys: list[str],
    *,
    expected_status: Optional[str] = None,
) -> None:
    evidence: Dict[str, Any] = {}
    failures = []
    for key in keys:
        value = result.get(key)
        evidence[key] = value
        if isinstance(value, dict):
            if value.get("error"):
                failures.append(f"{key}: {value['error']}")
            elif "success" in value and value["success"] is not True:
                failures.append(f"{key}: success returned false")
        elif value is None:
            failures.append(f"{key}: missing")
    if failures:
        recorder.record(category, name, expected_status or "partially_supported", details={"reason": "; ".join(failures)}, evidence=evidence)
    else:
        recorder.record(category, name, expected_status or "supported", evidence=evidence)


def run_probe(server, output_dir: Path, keep_open: bool = False) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_extension_authoring_probe_"))
    timestamp = int(time.time())
    project_name = f"_mcp_extension_authoring_probe_{timestamp}"
    recorder = ProbeRecorder()
    cleanup_project = False
    delete_result: Optional[Dict[str, Any]] = None

    names = {
        "fuse": f"_mcp_fuse_lifecycle_{timestamp}",
        "dctl_lut": f"_mcp_dctl_lut_{timestamp}",
        "dctl_aces": f"_mcp_dctl_aces_{timestamp}",
        "script_py": f"_mcp_script_py_{timestamp}",
        "script_lua": f"_mcp_script_lua_{timestamp}",
    }

    metadata: Dict[str, Any] = {
        "title": "Extension Authoring Kernel Capability Probe",
        "timestamp_utc": utc_timestamp(),
        "python": sys.version,
        "platform": platform.platform(),
        "output_dir": str(output_dir),
        "work_dir": str(work_dir),
        "project_name": project_name,
        "extension_names": names,
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

        create = server.project_manager("safe_project_create", {"name": project_name})
        _require_success("project_manager.safe_project_create", create)
        cleanup_project = True
        print(f"Created disposable project: {project_name}")

        _record_tool_result(recorder, "project", "safe_project_create", create)
        _record_tool_result(recorder, "capabilities", "extension_capabilities", server.script_plugin("extension_capabilities"))
        for extension_type, category in [
            ("fuse", None),
            ("dctl", "lut"),
            ("dctl", "aces_idt"),
            ("dctl", "aces_odt"),
            ("script", "Utility"),
        ]:
            params = {"extension_type": extension_type}
            if category:
                params["category"] = category
            _record_tool_result(
                recorder,
                "lifecycle",
                f"refresh_or_restart_required_{extension_type}_{category or 'default'}",
                server.script_plugin("refresh_or_restart_required", params),
            )

        fuse_probe = server.script_plugin("probe_fuse_lifecycle", {
            "name": names["fuse"],
            "kind": "color_matrix",
            "install": True,
            "cleanup": True,
            "overwrite": True,
        })
        _record_nested_success(recorder, "fuse", "probe_fuse_lifecycle_install_read_list_remove", fuse_probe, ["install", "read", "list", "remove"])

        dctl_lut_probe = server.script_plugin("probe_dctl_lifecycle", {
            "name": names["dctl_lut"],
            "kind": "transform",
            "category": "lut",
            "subdir": "MCP",
            "install": True,
            "refresh_luts": True,
            "cleanup": True,
            "overwrite": True,
        })
        _record_nested_success(
            recorder,
            "dctl",
            "probe_dctl_lut_lifecycle_install_refresh_remove",
            dctl_lut_probe,
            ["install", "read", "list", "refresh_luts", "remove"],
        )

        dctl_aces_probe = server.script_plugin("probe_dctl_lifecycle", {
            "name": names["dctl_aces"],
            "kind": "aces_idt",
            "category": "aces_idt",
            "subdir": "MCP",
            "install": True,
            "cleanup": True,
            "overwrite": True,
        })
        _record_nested_success(
            recorder,
            "dctl",
            "probe_dctl_aces_lifecycle_install_remove",
            dctl_aces_probe,
            ["install", "read", "list", "remove"],
        )

        script_py_probe = server.script_plugin("probe_script_lifecycle", {
            "name": names["script_py"],
            "kind": "scaffold",
            "language": "py",
            "category": "Utility",
            "install": True,
            "execute": True,
            "cleanup": True,
            "overwrite": True,
            "timeout": 120,
        })
        _record_nested_success(
            recorder,
            "script",
            "probe_script_python_lifecycle_install_execute_remove",
            script_py_probe,
            ["install", "read", "list", "execute", "remove"],
        )

        script_lua_probe = server.script_plugin("probe_script_lifecycle", {
            "name": names["script_lua"],
            "kind": "scaffold",
            "language": "lua",
            "category": "Utility",
            "install": True,
            "execute": True,
            "cleanup": True,
            "overwrite": True,
            "timeout": 120,
        })
        _record_nested_success(
            recorder,
            "script",
            "probe_script_lua_lifecycle_install_execute_remove",
            script_lua_probe,
            ["install", "read", "list", "execute", "remove"],
        )

        _record_tool_result(
            recorder,
            "script",
            "run_inline_python_stdout",
            server.script_plugin("run_inline", {"language": "py", "source": "print('extension inline py ok')", "timeout": 60}),
        )
        _record_tool_result(
            recorder,
            "script",
            "run_inline_lua_stdout_result",
            server.script_plugin("run_inline", {"language": "lua", "source": "print('extension inline lua ok')\nreturn 'lua-result'", "timeout": 60}),
        )
        _record_tool_result(
            recorder,
            "guards",
            "safe_install_rejects_unmarked_source",
            server.script_plugin("safe_install_extension", {
                "extension_type": "script",
                "name": f"_mcp_unmarked_{timestamp}",
                "source": "print('missing marker')",
                "language": "py",
                "category": "Utility",
                "dry_run": True,
            }),
            expected_status="unsupported",
        )
        _record_tool_result(
            recorder,
            "report",
            "extension_boundary_report",
            server.script_plugin("extension_boundary_report", {"include_template_matrix": True}),
        )

        if keep_open:
            server.project_manager("save")
            cleanup_project = False
            print(f"LEFT PROJECT OPEN FOR INSPECTION: {project_name}")

    finally:
        if cleanup_project:
            server.project_manager("save")
            server.project_manager("close")
            delete_result = server.project_manager("safe_project_delete", {"name": project_name})
            print(f"Deleted disposable project: {delete_result}")

    metadata["cleanup"] = {"project": delete_result}
    report = recorder.to_report(
        metadata,
        {
            "json": str(output_dir / "extension-authoring-probe.json"),
            "markdown": str(output_dir / "extension-authoring-probe.md"),
        },
    )
    json_path = output_dir / "extension-authoring-probe.json"
    markdown_path = output_dir / "extension-authoring-probe.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    print(f"Wrote JSON report: {json_path}")
    print(f"Wrote Markdown report: {markdown_path}")
    print(f"Counts: {json.dumps(report['counts'], sort_keys=True)}")
    if not keep_open:
        shutil.rmtree(work_dir, ignore_errors=True)
        print(f"Removed extension authoring work directory: {work_dir}")

    if delete_result and delete_result.get("success") is not True:
        raise AssertionError(f"Cleanup failed for {project_name}: {delete_result!r}")
    return report
