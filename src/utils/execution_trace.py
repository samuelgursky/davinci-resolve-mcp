"""Agent execution tracing and observability ("Why did the editor do this?").

Translates agent execution tracing concepts to DaVinci Resolve MCP.
Connects multi-step tool calls, timing (duration_ms), semantic changes, and
readback verifications under unified execution traces so human editors and AI
agents can inspect, debug, and understand AI editorial workflows.

Key capabilities:
  1. Correlated execution traces across multi-step agent actions.
  2. Per-tool timing (duration_ms) and invocation counts.
  3. Semantic change aggregation (e.g. items_deleted, items_added).
  4. Cumulative verification rollup (passed, checks, contradictions).
  5. In-memory thread-safe ring buffer with fast queries:
     - get_execution_trace(execution_id?) / get_execution(id)
     - list_recent_executions(limit?)
     - begin_execution(request?, execution_id?)
     - end_execution(execution_id?, verification?)
  6. Non-blocking best-effort logging.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("resolve-mcp.execution-trace")

MAX_RECENT_EXECUTIONS = 100

_LOCK = threading.Lock()
_EXECUTIONS_BY_ID: Dict[str, Dict[str, Any]] = {}
_RECENT_ORDER: Deque[str] = collections.deque(maxlen=MAX_RECENT_EXECUTIONS)
_ACTIVE_EXECUTION_ID: Optional[str] = None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_execution_id() -> str:
    """Generate a correlated execution ID with prefix 'exec_'."""
    return f"exec_{uuid.uuid4().hex[:12]}"


def current_execution_id() -> Optional[str]:
    """Return the active multi-turn execution ID for this session, if any."""
    with _LOCK:
        return _ACTIVE_EXECUTION_ID


def _clean_trace_dict(trace: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep copy of the execution trace for safe serialization."""
    return json.loads(json.dumps(trace))


def _aggregate_changes(
    cumulative: Optional[Dict[str, Any]],
    delta: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not delta:
        return cumulative
    if cumulative is None:
        return dict(delta)

    out = dict(cumulative)
    for k, v in delta.items():
        if isinstance(v, (int, float)):
            existing = out.get(k, 0)
            if isinstance(existing, (int, float)):
                out[k] = existing + v
            else:
                out[k] = v
        else:
            out[k] = v
    return out


def _merge_verification(
    current: Dict[str, Any],
    step_verif: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not isinstance(step_verif, dict):
        return current

    checks = list(current.get("checks", []))
    new_checks = step_verif.get("checks", [])
    if isinstance(new_checks, list):
        checks.extend(new_checks)

    contradiction = bool(current.get("contradiction")) or bool(step_verif.get("contradiction"))

    # Determine status priority: contradiction > failed > partial > passed > unverified
    statuses = {current.get("status", "unverified"), step_verif.get("status", "unverified")}
    if contradiction or "contradiction" in statuses:
        status = "contradiction"
        passed = False
    elif "failed" in statuses:
        status = "failed"
        passed = False
    elif "partial" in statuses:
        status = "partial"
        passed = False
    elif "passed" in statuses:
        status = "passed"
        passed = True
    else:
        status = "unverified"
        passed = True

    return {
        "status": status,
        "passed": passed,
        "contradiction": contradiction,
        "checks": checks,
    }


def begin_execution(
    request: Optional[str] = None,
    *,
    execution_id: Optional[str] = None,
    initiator: Optional[str] = None,
) -> Dict[str, Any]:
    """Start an active multi-step execution trace for the session.

    Subsequent tool calls will automatically thread under this execution ID
    until end_execution() is called.
    """
    global _ACTIVE_EXECUTION_ID

    exec_id = execution_id or new_execution_id()
    now = _now_iso()

    trace: Dict[str, Any] = {
        "execution_id": exec_id,
        "request": str(request).strip() if request else None,
        "status": "running",
        "started_at": now,
        "ended_at": None,
        "duration_ms": 0,
        "tools": [],
        "steps": [],
        "changes": None,
        "verification": {
            "status": "unverified",
            "passed": True,
            "contradiction": False,
            "checks": [],
        },
        "warnings": [],
        "initiator": initiator or "agent",
        "is_active": True,
    }

    with _LOCK:
        _EXECUTIONS_BY_ID[exec_id] = trace
        if exec_id in _RECENT_ORDER:
            _RECENT_ORDER.remove(exec_id)
        _RECENT_ORDER.appendleft(exec_id)
        _ACTIVE_EXECUTION_ID = exec_id

    _persist_trace_event("begin", trace)
    return {
        "success": True,
        "execution_id": exec_id,
        "started_at": now,
        "request": trace["request"],
    }


def end_execution(
    execution_id: Optional[str] = None,
    *,
    verification: Optional[Dict[str, Any]] = None,
    status: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """End an active execution trace and calculate final rollups."""
    global _ACTIVE_EXECUTION_ID

    target_id = execution_id or _ACTIVE_EXECUTION_ID
    if not target_id:
        return None

    now = _now_iso()
    with _LOCK:
        trace = _EXECUTIONS_BY_ID.get(target_id)
        if not trace:
            return None

        trace["ended_at"] = now
        trace["is_active"] = False

        if verification:
            trace["verification"] = _merge_verification(trace["verification"], verification)

        if notes:
            trace["notes"] = str(notes).strip()

        # Deduce overall status if not explicitly passed
        if status:
            trace["status"] = status
        else:
            if trace["verification"].get("contradiction"):
                trace["status"] = "failed"
            elif any(s.get("status") == "failed" for s in trace.get("steps", [])):
                trace["status"] = "failed"
            elif any(s.get("status") == "partial" for s in trace.get("steps", [])):
                trace["status"] = "partial"
            elif any(s.get("status") == "blocked" for s in trace.get("steps", [])):
                trace["status"] = "blocked"
            else:
                trace["status"] = "success"

        # If this was the active session execution, clear it
        if _ACTIVE_EXECUTION_ID == target_id:
            _ACTIVE_EXECUTION_ID = None

        copy_trace = _clean_trace_dict(trace)

    _persist_trace_event("end", copy_trace)
    return copy_trace


def record_step(
    tool: str,
    action: str,
    params: Optional[Dict[str, Any]],
    raw_result: Any,
    duration_ms: int,
    *,
    execution_id: Optional[str] = None,
    status: Optional[str] = None,
    verification: Optional[Dict[str, Any]] = None,
    changes: Optional[Dict[str, Any]] = None,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Record a single tool call step into an execution trace.

    If execution_id is provided or an active execution exists, appends to it.
    Otherwise, creates a self-contained single-step execution trace.
    """
    op_name = f"{tool}.{action}"
    step_status = status or ("failed" if isinstance(raw_result, dict) and raw_result.get("error") else "success")
    now = _now_iso()

    step_record: Dict[str, Any] = {
        "seq": 1,
        "tool": tool,
        "action": action,
        "operation": op_name,
        "duration_ms": max(0, int(duration_ms)),
        "status": step_status,
        "timestamp": now,
    }
    if verification:
        step_record["verification"] = verification
    if changes:
        step_record["changes"] = changes
    if warnings:
        step_record["warnings"] = warnings

    with _LOCK:
        target_id = execution_id or _ACTIVE_EXECUTION_ID
        is_single_step = False

        if not target_id:
            target_id = new_execution_id()
            is_single_step = True
            request_text = None
            if isinstance(params, dict):
                request_text = params.get("request") or params.get("prompt") or params.get("reason")
            trace: Dict[str, Any] = {
                "execution_id": target_id,
                "request": str(request_text).strip() if request_text else None,
                "status": step_status,
                "started_at": now,
                "ended_at": now,
                "duration_ms": 0,
                "tools": [],
                "steps": [],
                "changes": None,
                "verification": {
                    "status": "unverified",
                    "passed": True,
                    "contradiction": False,
                    "checks": [],
                },
                "warnings": [],
                "initiator": "tool_call",
                "is_active": False,
            }
            _EXECUTIONS_BY_ID[target_id] = trace
            _RECENT_ORDER.appendleft(target_id)
        else:
            trace = _EXECUTIONS_BY_ID.get(target_id)
            if not trace:
                trace = {
                    "execution_id": target_id,
                    "request": None,
                    "status": "running",
                    "started_at": now,
                    "ended_at": None,
                    "duration_ms": 0,
                    "tools": [],
                    "steps": [],
                    "changes": None,
                    "verification": {
                        "status": "unverified",
                        "passed": True,
                        "contradiction": False,
                        "checks": [],
                    },
                    "warnings": [],
                    "initiator": "agent",
                    "is_active": True,
                }
                _EXECUTIONS_BY_ID[target_id] = trace
                _RECENT_ORDER.appendleft(target_id)

        # Update trace request if provided in params and currently empty
        if not trace.get("request") and isinstance(params, dict):
            req = params.get("request") or params.get("prompt") or params.get("reason")
            if req:
                trace["request"] = str(req).strip()

        step_record["seq"] = len(trace["steps"]) + 1
        trace["steps"].append(step_record)
        trace["duration_ms"] = int(trace.get("duration_ms", 0)) + max(0, int(duration_ms))

        # Update aggregated tools entry (matching user format)
        found_tool = None
        for t in trace["tools"]:
            if t.get("tool") == op_name or t.get("tool") == action:
                found_tool = t
                break

        if found_tool:
            found_tool["count"] = int(found_tool.get("count", 1)) + 1
            found_tool["duration_ms"] = int(found_tool.get("duration_ms", 0)) + max(0, int(duration_ms))
        else:
            trace["tools"].append({
                "tool": op_name,
                "count": 1,
                "duration_ms": max(0, int(duration_ms)),
            })

        # Aggregate changes
        if changes:
            trace["changes"] = _aggregate_changes(trace.get("changes"), changes)

        # Merge verification
        if verification:
            trace["verification"] = _merge_verification(trace["verification"], verification)

        # Merge warnings
        if warnings:
            existing_warnings = set(trace.get("warnings", []))
            for w in warnings:
                w_str = str(w).strip()
                if w_str and w_str not in existing_warnings:
                    trace["warnings"].append(w_str)
                    existing_warnings.add(w_str)

        if is_single_step:
            trace["status"] = step_status
            trace["ended_at"] = now

        result_copy = _clean_trace_dict(trace)

    _persist_trace_event("step", {"execution_id": target_id, "step": step_record})
    return result_copy


def get_execution_trace(execution_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Look up an execution trace by ID.

    If execution_id is omitted, returns the most recent execution trace.
    """
    with _LOCK:
        if not execution_id:
            if not _RECENT_ORDER:
                return None
            target_id = _RECENT_ORDER[0]
        else:
            target_id = execution_id

        trace = _EXECUTIONS_BY_ID.get(target_id)
        if not trace:
            return None
        return _clean_trace_dict(trace)


def get_execution(execution_id: str) -> Optional[Dict[str, Any]]:
    """Alias for get_execution_trace(execution_id)."""
    return get_execution_trace(execution_id)


def list_recent_executions(limit: int = 20) -> List[Dict[str, Any]]:
    """List recent executions (newest first) with summary information."""
    max_count = max(1, min(int(limit), MAX_RECENT_EXECUTIONS))
    out: List[Dict[str, Any]] = []

    with _LOCK:
        for exec_id in list(_RECENT_ORDER)[:max_count]:
            trace = _EXECUTIONS_BY_ID.get(exec_id)
            if not trace:
                continue
            summary = {
                "execution_id": trace["execution_id"],
                "request": trace.get("request"),
                "status": trace.get("status"),
                "started_at": trace.get("started_at"),
                "ended_at": trace.get("ended_at"),
                "duration_ms": trace.get("duration_ms", 0),
                "tool_count": len(trace.get("tools", [])),
                "step_count": len(trace.get("steps", [])),
                "tools": trace.get("tools", []),
                "verification": trace.get("verification", {}),
                "changes": trace.get("changes"),
            }
            out.append(summary)

    return out


def clear_executions() -> Dict[str, Any]:
    """Clear in-memory execution traces and active execution ID."""
    global _ACTIVE_EXECUTION_ID
    with _LOCK:
        count = len(_EXECUTIONS_BY_ID)
        _EXECUTIONS_BY_ID.clear()
        _RECENT_ORDER.clear()
        _ACTIVE_EXECUTION_ID = None
    return {"success": True, "cleared": count}


# ── Persistence (Best-Effort) ────────────────────────────────────────────────

def _trace_log_path() -> Optional[str]:
    override = os.environ.get("RESOLVE_MCP_TRACE_FILE")
    if override:
        return override
    # Default to logs/execution-traces.jsonl in current working directory if logs dir exists
    logs_dir = os.path.join(os.getcwd(), "logs")
    if os.path.isdir(logs_dir):
        return os.path.join(logs_dir, "execution-traces.jsonl")
    return None


def _persist_trace_event(event_type: str, data: Any) -> None:
    """Non-blocking, best-effort append to trace log. Never raises."""
    try:
        path = _trace_log_path()
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps({
            "event": event_type,
            "timestamp": _now_iso(),
            "data": data,
        }) + "\n"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as exc:  # pragma: no cover
        logger.debug("Failed to persist execution trace event: %s", exc)
