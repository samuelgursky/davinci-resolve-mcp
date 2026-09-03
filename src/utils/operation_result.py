"""Standardized operation result envelope for DaVinci Resolve MCP Server.

This module establishes a common result envelope across all MCP tool actions:

{
  "status": "success" | "partial" | "blocked" | "failed",
  "operation": "timeline.ripple_insert",
  "execution_id": "exec_4a9b2c8f1e0d",

  "result": { ... },

  "verification": {
    "status": "passed" | "failed" | "contradiction" | "unverified",
    "checks": [...]
  },

  "changes": {
    "items_added": int,
    "items_moved": int,
    "items_deleted": int,
    "items_updated": int,
    ...
  },

  "warnings": []
}

Supported envelope modes:
  - "dual" (default): provides both the structured envelope keys AND top-level
    legacy domain keys for 100% backward compatibility with existing tests and clients.
  - "pure": outputs only the standardized envelope dictionary without top-level domain key mirrors.
  - "legacy": returns raw un-enveloped dict.
"""

from __future__ import annotations

import os
import uuid
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("resolve-mcp.operation-result")

_CURRENT_ENVELOPE_MODE = os.environ.get("RESOLVE_MCP_RESULT_ENVELOPE", "dual").lower()
if _CURRENT_ENVELOPE_MODE not in {"dual", "pure", "legacy"}:
    _CURRENT_ENVELOPE_MODE = "dual"


def get_envelope_mode() -> str:
    """Return the current default envelope mode ('dual', 'pure', or 'legacy')."""
    return _CURRENT_ENVELOPE_MODE


def set_envelope_mode(mode: str) -> str:
    """Set the current default envelope mode ('dual', 'pure', or 'legacy')."""
    global _CURRENT_ENVELOPE_MODE
    clean = (mode or "").lower().strip()
    if clean in {"dual", "pure", "legacy"}:
        _CURRENT_ENVELOPE_MODE = clean
    return _CURRENT_ENVELOPE_MODE


def new_execution_id() -> str:
    """Generate a compact, unique execution ID for tracing."""
    return f"exec_{uuid.uuid4().hex[:12]}"


def normalize_status(raw_result: Any) -> str:
    """Determine the high-level operation status from the raw action result.

    Returns one of:
      - 'blocked': Requires confirm-token or gated action approval.
      - 'failed': Explicit error or falsey success.
      - 'partial': Multi-operation where some items succeeded and some failed.
      - 'success': Successful operation.
    """
    if not isinstance(raw_result, dict):
        return "success" if bool(raw_result) else "failed"

    # Blocked by confirm token or approval gate
    if "confirm_token" in raw_result or raw_result.get("pending_confirm") or raw_result.get("blocked"):
        return "blocked"

    # Explicit error structure
    if "error" in raw_result and raw_result["error"]:
        return "failed"
    if raw_result.get("success") is False:
        return "failed"

    # Partial execution in bulk operations
    if raw_result.get("partial") is True:
        return "partial"
    succeeded = raw_result.get("succeeded")
    failed = raw_result.get("failed")
    if isinstance(succeeded, int) and isinstance(failed, int) and succeeded > 0 and failed > 0:
        return "partial"

    return "success"


def extract_warnings(raw_result: Any) -> List[str]:
    """Collect and normalize warnings from the result payload."""
    if not isinstance(raw_result, dict):
        return []

    warnings: List[str] = []

    # 'warnings' list
    raw_warnings = raw_result.get("warnings")
    if isinstance(raw_warnings, list):
        for w in raw_warnings:
            if w:
                warnings.append(str(w))
    elif isinstance(raw_warnings, str) and raw_warnings.strip():
        warnings.append(raw_warnings.strip())

    # 'warning' single string
    raw_warning = raw_result.get("warning")
    if isinstance(raw_warning, str) and raw_warning.strip() and raw_warning not in warnings:
        warnings.append(raw_warning.strip())

    # 'ignored_options'
    ignored = raw_result.get("ignored_options")
    if isinstance(ignored, (list, dict)) and ignored:
        warnings.append(f"Ignored unsupported options: {ignored}")

    return warnings


def extract_verification(raw_result: Any) -> Dict[str, Any]:
    """Extract and standardize verification outcome into a structured block."""
    if not isinstance(raw_result, dict):
        return {"status": "unverified", "checks": []}

    # If verification is already structured:
    if "verification" in raw_result and isinstance(raw_result["verification"], dict):
        v = raw_result["verification"]
        return {
            "status": v.get("status", "passed" if v.get("verified") else "unverified"),
            "checks": v.get("checks", []),
            "contradiction": bool(v.get("contradiction", False)),
            **{k: v for k, v in v.items() if k not in {"status", "checks", "contradiction"}},
        }

    checks: List[Dict[str, Any]] = []
    status = "unverified"
    contradiction = False

    # Check readback results (from verify_by_readback or custom readbacks)
    readback = raw_result.get("readback")
    if isinstance(readback, dict):
        missing = readback.get("missing")
        if isinstance(missing, list):
            missing_count = len(missing)
            checks.append({
                "check": "readback_verification",
                "passed": missing_count == 0,
                "missing_items": missing_count,
            })
            status = "passed" if missing_count == 0 else "failed"
        else:
            checks.append({"check": "readback_verification", "passed": True, "details": readback})
            status = "passed"

    if "verified" in raw_result:
        verified_val = bool(raw_result["verified"])
        contradiction = bool(raw_result.get("contradiction", False))
        checks.append({
            "check": "readback_post_state",
            "passed": verified_val,
            "contradiction": contradiction,
            "observed": raw_result.get("observed"),
        })
        if contradiction:
            status = "contradiction"
        elif verified_val:
            status = "passed"
        else:
            status = "failed"

    # Check property restore failures (e.g. in ripple_insert or move_clips)
    if "property_restore_failures" in raw_result:
        fails = int(raw_result.get("property_restore_failures", 0))
        restored = int(raw_result.get("properties_restored_items", 0))
        checks.append({
            "check": "property_restore",
            "passed": fails == 0,
            "restored_items": restored,
            "failures": fails,
        })
        if fails > 0 and status == "passed":
            status = "partial"

    # Bulk operation counts
    if isinstance(raw_result.get("succeeded"), int) and isinstance(raw_result.get("failed"), int):
        succeeded = raw_result["succeeded"]
        failed = raw_result["failed"]
        checks.append({
            "check": "bulk_operations",
            "passed": failed == 0,
            "succeeded": succeeded,
            "failed": failed,
        })
        if status == "unverified":
            if failed == 0 and succeeded > 0:
                status = "passed"
            elif succeeded > 0 and failed > 0:
                status = "partial"
            elif succeeded == 0 and failed > 0:
                status = "failed"

    return {
        "status": status,
        "checks": checks,
        "contradiction": contradiction,
    }


def extract_changes(raw_result: Any) -> Dict[str, Any]:
    """Extract semantic change summary from action outputs and versioning deltas."""
    if not isinstance(raw_result, dict):
        return {}

    changes: Dict[str, Any] = {}

    # Explicit changes block
    if "changes" in raw_result and isinstance(raw_result["changes"], dict):
        changes.update(raw_result["changes"])

    # Items added / inserted
    if "items_added" in raw_result:
        changes["items_added"] = int(raw_result["items_added"])
    elif "inserted_clips" in raw_result:
        changes["items_added"] = int(raw_result["inserted_clips"])
    elif "inserted" in raw_result and isinstance(raw_result["inserted"], (int, list)):
        changes["items_added"] = len(raw_result["inserted"]) if isinstance(raw_result["inserted"], list) else int(raw_result["inserted"])

    # Items moved / shifted
    if "items_moved" in raw_result:
        changes["items_moved"] = int(raw_result["items_moved"])
    elif "tail_items_shifted" in raw_result:
        changes["items_moved"] = int(raw_result["tail_items_shifted"])

    # Items deleted / removed
    if "items_deleted" in raw_result:
        changes["items_deleted"] = int(raw_result["items_deleted"])
    elif "deleted_sources" in raw_result:
        ds = raw_result["deleted_sources"]
        changes["items_deleted"] = len(ds) if isinstance(ds, list) else int(ds)
    elif "deleted" in raw_result and isinstance(raw_result["deleted"], (int, list)):
        changes["items_deleted"] = len(raw_result["deleted"]) if isinstance(raw_result["deleted"], list) else int(raw_result["deleted"])

    # Properties updated
    if "properties_updated" in raw_result:
        changes["properties_updated"] = int(raw_result["properties_updated"])
    elif "properties_restored_items" in raw_result:
        changes["properties_updated"] = int(raw_result["properties_restored_items"])
    elif "updated" in raw_result and isinstance(raw_result["updated"], (int, list)):
        changes["items_updated"] = len(raw_result["updated"]) if isinstance(raw_result["updated"], list) else int(raw_result["updated"])

    # Shift frames
    if "shift_frames" in raw_result:
        changes["shift_frames"] = raw_result["shift_frames"]

    # Versioning / metric delta from @_destructive_op
    versioning = raw_result.get("_versioning")
    if isinstance(versioning, dict):
        metric = versioning.get("metric")
        before = versioning.get("before_value")
        after = versioning.get("after_value")
        if metric and before is not None and after is not None:
            changes["metric"] = metric
            changes["before_value"] = before
            changes["after_value"] = after
            try:
                changes["delta"] = round(float(after) - float(before), 4)
            except (ValueError, TypeError):
                pass
        if versioning.get("archived"):
            changes["timeline_archived"] = True
            if versioning.get("archived_version"):
                changes["archived_version"] = versioning["archived_version"]

    return changes


def clean_result_payload(raw_result: Any) -> Any:
    """Prepare the inner result dictionary by omitting envelope duplicate keys."""
    if not isinstance(raw_result, dict):
        return raw_result

    # Omit envelope wrapper keys from inner result payload to keep it clean
    skip_keys = {
        "verification",
        "warnings",
        "_versioning",
    }
    return {k: v for k, v in raw_result.items() if k not in skip_keys}


def is_binary_or_mcp_content(obj: Any) -> bool:
    """Return True if obj is an MCP Image, TextContent, or other non-dict MCP resource."""
    if obj is None:
        return False
    cls_name = getattr(obj.__class__, "__name__", "")
    return cls_name in {"Image", "TextContent", "EmbeddedResource"}


def build_operation_envelope(
    tool_name: str,
    action: str,
    params: Optional[Dict[str, Any]],
    raw_result: Any,
    *,
    execution_id: Optional[str] = None,
    run_id: Optional[str] = None,
    mode: Optional[str] = None,
) -> Any:
    """Wrap an action's raw result into the standardized operation envelope.

    Args:
      tool_name: The compound tool name (e.g. 'timeline', 'media_pool')
      action: The specific action invoked (e.g. 'ripple_insert', 'delete_clips')
      params: Input parameters provided to the action
      raw_result: The raw return dictionary or value from the action handler
      execution_id: Optional specific execution id (defaults to new_execution_id)
      run_id: Optional analysis_run_id (from analysis_runs or _versioning)
      mode: 'dual' (default), 'pure', or 'legacy'

    Returns:
      A dictionary conforming to the structured operation envelope.
    """
    if is_binary_or_mcp_content(raw_result):
        return raw_result

    params_dict = params if isinstance(params, dict) else {}

    # Determine requested mode (priority: param -> argument -> default)
    param_mode = params_dict["envelope"] if "envelope" in params_dict else params_dict.get("_envelope")
    if isinstance(param_mode, str):
        selected_mode = param_mode.lower()
    elif isinstance(param_mode, bool):
        selected_mode = "pure" if param_mode else "legacy"
    else:
        selected_mode = (mode or get_envelope_mode()).lower()

    if selected_mode == "legacy":
        return raw_result if isinstance(raw_result, dict) else {"result": raw_result}

    # Extract execution_id / run_id
    if not execution_id:
        if isinstance(raw_result, dict) and "_versioning" in raw_result:
            v_run_id = raw_result["_versioning"].get("analysis_run_id")
            if v_run_id:
                execution_id = f"exec_{v_run_id}"
    if not execution_id:
        execution_id = new_execution_id()

    operation = f"{tool_name}.{action}"
    status = normalize_status(raw_result)
    verification = extract_verification(raw_result)
    changes = extract_changes(raw_result)
    warnings = extract_warnings(raw_result)
    result_payload = clean_result_payload(raw_result)

    envelope: Dict[str, Any] = {
        "status": status,
        "operation": operation,
        "execution_id": execution_id,
        "result": result_payload,
        "verification": verification,
        "changes": changes,
        "warnings": warnings,
    }

    if run_id:
        envelope["run_id"] = run_id
    elif isinstance(raw_result, dict) and "_versioning" in raw_result:
        v_run = raw_result["_versioning"].get("analysis_run_id")
        if v_run:
            envelope["run_id"] = v_run

    # In dual mode, mirror existing top-level keys for 100% backward compatibility
    if selected_mode == "dual" and isinstance(raw_result, dict):
        for k, v in raw_result.items():
            if k not in envelope:
                envelope[k] = v

    return envelope
