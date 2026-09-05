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
  6. Best-effort append-only persistence beside the server's own log.

Adapted from the design contributed in PR #183.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Union

logger = logging.getLogger("resolve-mcp.execution-trace")

MAX_RECENT_EXECUTIONS = 100

#: Where traces are written, unless RESOLVE_MCP_TRACE_FILE overrides it.
#:
#: Anchored to the repository root, the way `server.log`,
#: `media-analysis-preferences.json` and `server-preferences.json` all are.
#: Deriving it from `os.getcwd()` instead put the file wherever the MCP client
#: happened to launch the server from — and since the generated client configs
#: set no `cwd`, that is usually a directory with no `logs/` in it, where the
#: original code returned None and wrote nothing at all. Silently. A feature
#: whose whole purpose is answering "why did the editor do this?" is worth
#: rather more than a file that may or may not exist depending on the launcher.
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Size at which the trace log is rotated, and how many old files are kept.
#:
#: The in-memory ring is capped at 100 executions; the file had no bound at all,
#: and it takes one append per tool call. A default-on log that grows without
#: limit on a working editorial machine is a slow leak, so it rolls over to
#: `.1` and starts fresh — one generation back is enough for "what did the
#: agent just do", which is the whole question this feature answers.
MAX_TRACE_LOG_BYTES = 8 * 1024 * 1024
TRACE_LOG_GENERATIONS = 1

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
        # None, not True. Nothing reported any evidence either way, and
        # collapsing that into a boolean makes the rollup assert a pass it
        # never observed — which then reaches a human as "Passed: yes" in an
        # exported audit report.
        status = "unverified"
        passed = None

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
            # None, not True. "Nothing was checked" is not "everything passed",
            # and the difference reaches a human in an exported audit report —
            # see _execution_report_markdown.
            "passed": None,
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
                    "passed": None,  # see above: unknown, not passed
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
                        "passed": None,  # see above: unknown, not passed
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


# ── Audit Reports ───────────────────────────────────────────────────────────

def _report_format(report_format: str) -> str:
    fmt = str(report_format or "markdown").strip().lower()
    if fmt in {"md", "markdown"}:
        return "markdown"
    if fmt == "json":
        return "json"
    raise ValueError("format must be markdown or json")


def _report_extension(report_format: str) -> str:
    return ".md" if _report_format(report_format) == "markdown" else ".json"


def _report_filename(execution_id: str, report_format: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(execution_id or "execution")).strip("._")
    if not safe_id:
        safe_id = "execution"
    return f"{safe_id}{_report_extension(report_format)}"


def execution_report_dir() -> str:
    """Directory used for generated execution audit reports."""
    override = os.environ.get("RESOLVE_MCP_TRACE_REPORT_DIR")
    if override:
        return os.path.realpath(os.path.abspath(os.path.expanduser(override)))
    return str(_REPO_ROOT / "logs" / "execution-reports")


def _default_report_path(trace: Dict[str, Any], report_format: str) -> str:
    return str(Path(execution_report_dir()) / _report_filename(trace["execution_id"], report_format))


def _format_ms(value: Any) -> str:
    try:
        return f"{max(0, int(value))} ms"
    except (TypeError, ValueError):
        return "0 ms"


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def _markdown_row(*cells: Any) -> str:
    escaped = []
    for cell in cells:
        text = _scalar(cell).replace("\n", " ").replace("|", "\\|")
        escaped.append(text)
    return "| " + " | ".join(escaped) + " |"


def _execution_report_json(trace: Dict[str, Any], *, include_steps: bool = True) -> Dict[str, Any]:
    """Return a stable, compact report object derived from safe trace summaries."""
    out = {
        "execution_id": trace.get("execution_id"),
        "request": trace.get("request"),
        "status": trace.get("status"),
        "started_at": trace.get("started_at"),
        "ended_at": trace.get("ended_at"),
        "duration_ms": trace.get("duration_ms", 0),
        "initiator": trace.get("initiator"),
        "is_active": trace.get("is_active", False),
        "tools": trace.get("tools", []),
        "changes": trace.get("changes"),
        "verification": trace.get("verification", {}),
        "warnings": trace.get("warnings", []),
    }
    if trace.get("notes"):
        out["notes"] = trace.get("notes")
    if include_steps:
        out["steps"] = trace.get("steps", [])
    return out


def _execution_report_markdown(trace: Dict[str, Any], *, include_steps: bool = True) -> str:
    report = _execution_report_json(trace, include_steps=include_steps)
    lines = [
        "# Execution Audit Report",
        "",
        _markdown_row("Field", "Value"),
        _markdown_row("---", "---"),
        _markdown_row("Execution ID", report.get("execution_id")),
        _markdown_row("Request", report.get("request")),
        _markdown_row("Status", report.get("status")),
        _markdown_row("Started", report.get("started_at")),
        _markdown_row("Ended", report.get("ended_at")),
        _markdown_row("Duration", _format_ms(report.get("duration_ms"))),
        _markdown_row("Initiator", report.get("initiator")),
        "",
        "## Tool Summary",
        "",
    ]

    tools = report.get("tools") or []
    if tools:
        lines.extend([
            _markdown_row("Tool", "Calls", "Duration"),
            _markdown_row("---", "---:", "---:"),
        ])
        for tool in tools:
            lines.append(_markdown_row(tool.get("tool"), tool.get("count", 0), _format_ms(tool.get("duration_ms"))))
    else:
        lines.append("No tool calls recorded.")

    lines.extend(["", "## Changes", ""])
    changes = report.get("changes")
    if isinstance(changes, dict) and changes:
        lines.extend([
            _markdown_row("Change", "Value"),
            _markdown_row("---", "---"),
        ])
        for key in sorted(changes):
            lines.append(_markdown_row(key, changes[key]))
    else:
        lines.append("No semantic changes recorded.")

    verification = report.get("verification") or {}
    lines.extend([
        "",
        "## Verification",
        "",
        _markdown_row("Field", "Value"),
        _markdown_row("---", "---"),
        _markdown_row("Status", verification.get("status")),
        _markdown_row("Passed", _verification_passed_label(verification)),
        _markdown_row("Contradiction", verification.get("contradiction")),
        _markdown_row("Checks", len(verification.get("checks") or [])),
    ])

    warnings = report.get("warnings") or []
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {_scalar(w)}" for w in warnings)
    else:
        lines.append("No warnings recorded.")

    if report.get("notes"):
        lines.extend(["", "## Notes", "", _scalar(report["notes"])])

    if include_steps:
        lines.extend(["", "## Steps", ""])
        steps = report.get("steps") or []
        if steps:
            lines.extend([
                _markdown_row("#", "Timestamp", "Operation", "Status", "Duration"),
                _markdown_row("---:", "---", "---", "---", "---:"),
            ])
            for step in steps:
                lines.append(_markdown_row(
                    step.get("seq"),
                    step.get("timestamp"),
                    step.get("operation"),
                    step.get("status"),
                    _format_ms(step.get("duration_ms")),
                ))
        else:
            lines.append("No steps recorded.")

    lines.append("")
    return "\n".join(lines)


def _verification_passed_label(verification: Dict[str, Any]) -> str:
    """How the Passed row reads when nothing was actually verified.

    A report that prints `Status: unverified` beside `Passed: yes` is read by a
    human as "it passed" — the two lines are inches apart and only one of them
    is scanned. Unverified means no evidence was reported, which is a question
    still open, not a clean bill of health; an audit document is the last place
    that distinction should be left to the reader.
    """
    passed = verification.get("passed")
    if passed is None:
        return "not established — no checks recorded"
    return "yes" if passed else "no"


def render_execution_report(
    trace: Dict[str, Any],
    *,
    report_format: str = "markdown",
    include_steps: bool = True,
) -> Union[str, Dict[str, Any]]:
    """Render an execution trace as a Markdown or JSON audit report."""
    fmt = _report_format(report_format)
    if fmt == "json":
        return _execution_report_json(trace, include_steps=include_steps)
    return _execution_report_markdown(trace, include_steps=include_steps)


def export_execution_report(
    execution_id: Optional[str] = None,
    *,
    report_format: str = "markdown",
    output_path: Optional[str] = None,
    overwrite: bool = False,
    include_steps: bool = True,
) -> Optional[Dict[str, Any]]:
    """Write an execution audit report to disk.

    The export is built from trace summaries, not raw tool arguments/results.
    """
    trace = get_execution_trace(execution_id)
    if not trace:
        return None

    fmt = _report_format(report_format)
    path = output_path or _default_report_path(trace, fmt)
    real_path = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    if os.path.exists(real_path) and not overwrite:
        raise FileExistsError(f"Report already exists: {real_path}")

    rendered = render_execution_report(trace, report_format=fmt, include_steps=include_steps)
    os.makedirs(os.path.dirname(real_path), exist_ok=True)
    if fmt == "json":
        payload = json.dumps(rendered, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    else:
        payload = str(rendered)
    with open(real_path, "w", encoding="utf-8") as fh:
        fh.write(payload)

    return {
        "success": True,
        "execution_id": trace["execution_id"],
        "format": fmt,
        "path": real_path,
        "bytes": len(payload.encode("utf-8")),
        "included_steps": bool(include_steps),
    }


# ── Persistence (Best-Effort) ────────────────────────────────────────────────

def trace_log_path() -> str:
    """The file traces are appended to. Always a path, never None.

    Returning None when a directory did not happen to exist made persistence
    an invisible coin flip; the directory is created on first write instead.
    """
    override = os.environ.get("RESOLVE_MCP_TRACE_FILE")
    if override:
        return os.path.realpath(os.path.abspath(os.path.expanduser(override)))
    return str(_REPO_ROOT / "logs" / "execution-traces.jsonl")


def persistence_status() -> Dict[str, Any]:
    """Whether traces are reaching disk, and where.

    Reported alongside every query so "no traces in the file" is answerable
    without reading this module: an unwritable path says so here rather than
    being swallowed by the best-effort append.
    """
    path = trace_log_path()
    status: Dict[str, Any] = {"path": path, "writable": False, "exists": False,
                              "reason": None}
    try:
        status["exists"] = os.path.isfile(path)
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        status["writable"] = os.access(directory, os.W_OK)
        if not status["writable"]:
            status["reason"] = f"{directory} is not writable"
    except OSError as exc:
        status["reason"] = str(exc)
    return status


# Kept for callers that used the private name; the public one is the path itself.
_trace_log_path = trace_log_path


def _rotate_if_oversized(path: str) -> None:
    """Roll the trace log over once it passes the size cap. Never raises."""
    try:
        if os.path.getsize(path) < MAX_TRACE_LOG_BYTES:
            return
    except OSError:
        return
    try:
        previous = f"{path}.{TRACE_LOG_GENERATIONS}"
        if os.path.exists(previous):
            os.remove(previous)
        os.replace(path, previous)
    except OSError as exc:
        logger.debug("Could not rotate the execution trace log: %s", exc)


def _persist_trace_event(event_type: str, data: Any) -> None:
    """Best-effort append to the trace log. Never raises.

    Synchronous, on the calling thread — not "non-blocking", as this was
    originally described. It is a buffered append of a few hundred bytes and
    measures at ~0.07ms per tool call on local disk, which is immaterial next
    to any Resolve round-trip, but the accurate word for it is *cheap*. It runs
    outside `_LOCK` so a slow filesystem cannot serialize concurrent tool calls.
    """
    try:
        path = trace_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _rotate_if_oversized(path)
        line = json.dumps({
            "event": event_type,
            "timestamp": _now_iso(),
            "data": data,
        }) + "\n"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as exc:  # pragma: no cover
        logger.debug("Failed to persist execution trace event: %s", exc)
