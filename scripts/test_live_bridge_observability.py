#!/usr/bin/env python3
"""Script to verify live DaVinci Resolve app connection and test agent observability changes.

Run:
    DAVINCI_RESOLVE_BRIDGE_CONFIG=~/.davinci-resolve-mcp/bridge.json venv/bin/python scripts/test_live_bridge_observability.py
"""

import json
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Set default bridge config path if not provided
if "DAVINCI_RESOLVE_BRIDGE_CONFIG" not in os.environ:
    fallback = Path.home() / ".davinci-resolve-mcp/bridge.json"
    if fallback.is_file():
        os.environ["DAVINCI_RESOLVE_BRIDGE_CONFIG"] = str(fallback)

if "DAVINCI_RESOLVE_BRIDGE" not in os.environ:
    os.environ["DAVINCI_RESOLVE_BRIDGE"] = "1"

from src.utils import resolve_bridge_client as rbc
from src.server import resolve_control, timeline


def test_live_bridge():
    print("=" * 70)
    print("DaVinci Resolve MCP — Live Bridge & Observability Test")
    print("=" * 70)
    print(f"Config path : {rbc.config_path()}")

    # 1. Test live connection
    try:
        proxy = rbc.connect(require_enabled=False)
        product = proxy.GetProductName()
        version = proxy.GetVersionString()
        page = proxy.GetCurrentPage()
        print("Status      : CONNECTED")
        print(f"Product     : {product} (v{version})")
        print(f"Active Page : {page}")
    except rbc.BridgeUnavailable as e:
        print("\n[!] Bridge is NOT currently listening.")
        print("To start it:")
        print("  1. In DaVinci Resolve, open a project.")
        print("  2. Go to the menu: Workspace ▸ Scripts ▸ resolve_bridge")
        print("  3. Re-run this script once the bridge starts listening.")
        print(f"Details: {e}")
        return False
    except Exception as e:
        print(f"\n[!] Connection failed: {type(e).__name__}: {e}")
        return False

    pm = proxy.GetProjectManager()
    proj = pm.GetCurrentProject() if pm else None
    proj_name = proj.GetName() if proj else "None (Project Manager Open)"
    print(f"Project     : {proj_name}")

    tl = proj.GetCurrentTimeline() if proj else None
    tl_name = tl.GetName() if tl else "None"
    print(f"Timeline    : {tl_name}")

    # 2. Test pre-flight risk inspection with live Resolve state
    print("\n--- 1. Testing inspect_operation with live state ---")
    inspect_res = resolve_control(
        action="inspect_operation",
        params={
            "tool": "timeline",
            "target_action": "delete_clips",
            "target_params": {"timeline_item_ids": ["c1", "c2"]},
        },
    )
    print("inspect_operation result:")
    print(json.dumps(inspect_res, indent=2))
    assert inspect_res.get("success"), "inspect_operation should succeed"
    assert inspect_res.get("risk", {}).get("level") == "high"
    assert inspect_res.get("destructive") is True
    assert inspect_res.get("confirmation_required") is True

    # 3. Test list_lifecycle_hooks
    print("\n--- 2. Testing list_lifecycle_hooks ---")
    hooks_res = resolve_control(action="list_lifecycle_hooks", params={})
    print(f"Registered lifecycle hooks: {[h['name'] for h in hooks_res.get('hooks', [])]}")
    assert hooks_res.get("success"), "list_lifecycle_hooks should succeed"

    # 4. Test dry-run simulation on live session
    print("\n--- 3. Testing dry-run safety simulation ---")
    dry_res = timeline(
        action="delete_clips",
        params={"timeline_item_ids": ["sample_item"], "dry_run": True},
    )
    print("dry_run interception result:")
    print(json.dumps(dry_res, indent=2))
    assert dry_res.get("dry_run") is True or dry_res.get("_operation", {}).get("status") == "dry_run"

    # 5. Test multi-step execution tracing on live session
    print("\n--- 4. Testing execution tracing lifecycle ---")
    begin_res = resolve_control(
        action="begin_execution",
        params={"request": "Live DaVinci Resolve test execution"},
    )
    exec_id = begin_res.get("execution_id")
    print(f"Begun execution: {exec_id}")

    # Perform live tool calls within this execution
    page_res = resolve_control(action="get_page")
    print(f"Executed resolve_control(get_page): {page_res.get('page')}")

    tl_info = timeline(action="get_current")
    print(f"Executed timeline(get_current): name={tl_info.get('name')}, duration={tl_info.get('end_frame', 0) - tl_info.get('start_frame', 0)} frames")

    trace_res = resolve_control(action="get_execution_trace", params={"execution_id": exec_id})
    print("Execution trace snapshot:")
    print(json.dumps(trace_res.get("trace"), indent=2))

    # Export report
    report_res = resolve_control(
        action="export_execution_report",
        params={"execution_id": exec_id, "format": "markdown", "overwrite": True},
    )
    print(f"Exported audit report to: {report_res.get('path')}")

    end_res = resolve_control(action="end_execution", params={"execution_id": exec_id})
    print(f"Ended execution: status={end_res.get('trace', {}).get('status')}")

    print("\n" + "=" * 70)
    print("ALL LIVE BRIDGE & OBSERVABILITY TESTS PASSED!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = test_live_bridge()
    sys.exit(0 if success else 1)
