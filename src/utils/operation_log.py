"""Structured operation log for mutating tool calls.

This log is deliberately narrower than execution traces and separate from the
security audit log. It records the user-visible mutation attempt: which tool
action ran, its risk, whether it was a dry run, a compact summary, and the
final status.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.utils.bool_params import coerce_bool, explicit_bool_param
from src.utils import log_paths, operation_result

logger = logging.getLogger("resolve-mcp.operation-log")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PreferenceProvider = Callable[[str], Any]
_PREFERENCE_PROVIDER: Optional[_PreferenceProvider] = None


def register_preference_provider(fn: _PreferenceProvider) -> None:
    global _PREFERENCE_PROVIDER
    _PREFERENCE_PROVIDER = fn


def _read_preference(key: str, default: Any = None) -> Any:
    if _PREFERENCE_PROVIDER is None:
        return default
    try:
        value = _PREFERENCE_PROVIDER(key)
    except Exception:
        return default
    return default if value is None else value


def _coerce_bool(value: Any, default: bool = False) -> bool:
    return coerce_bool(value, default)


def operation_log_enabled() -> bool:
    return _coerce_bool(_read_preference("destructive.operation_log", True), True)


def operation_log_path() -> str:
    operator = os.environ.get("RESOLVE_MCP_OPERATION_LOG_FILE")
    if operator:
        return log_paths.normalize(operator)
    default = str(_REPO_ROOT / "logs" / "operation-log.jsonl")
    configured = _read_preference("destructive.operation_log_path", None)
    if configured:
        # Writable through setup and possibly set before the confinement
        # (GHSA-3rvw-8897-xq63), so it is checked on every use.
        problem = log_paths.log_path_problem(str(configured))
        if problem:
            logger.warning("ignoring destructive.operation_log_path %r: %s", configured, problem)
            return default
        return log_paths.normalize(str(configured))
    return default


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _dry_run_requested(params: Optional[Dict[str, Any]], result: Any) -> bool:
    requested = explicit_bool_param(params, "dry_run", "dryRun")
    if requested is not None:
        return requested
    if isinstance(result, dict) and "dry_run" in result:
        return coerce_bool(result.get("dry_run"))
    return False


def _envelope(result: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    nested = result.get(operation_result.ENVELOPE_KEY)
    if isinstance(nested, dict):
        return nested
    if {"operation", "execution_id", "status"}.intersection(result):
        return result
    return {}


def _operation_id(result: Any, envelope: Dict[str, Any]) -> str:
    if isinstance(result, dict) and result.get("operation_id"):
        return str(result["operation_id"])
    execution_id = envelope.get("execution_id")
    if execution_id:
        return str(execution_id)
    return f"op_{uuid.uuid4().hex[:12]}"


def _status(result: Any, envelope: Dict[str, Any]) -> str:
    raw_status = result.get("status") if isinstance(result, dict) else None
    error = result.get("error") if isinstance(result, dict) else None
    category = error.get("category") if isinstance(error, dict) else None
    if raw_status in {
        "blocked_by_security_policy",
        "dry_run_unavailable",
        "confirmation_required",
    }:
        return "blocked"
    if category in {
        "destructive_blocked",
        "dry_run_unavailable",
        "pending_user_decision",
    }:
        return "blocked"
    return str(envelope.get("status") or operation_result.normalize_status(result))


def _summary(
    tool_name: str,
    action: str,
    status: str,
    envelope: Dict[str, Any],
    *,
    dry_run: bool = False,
) -> str:
    operation = f"{tool_name}.{action}"
    changes = envelope.get("changes")
    if dry_run and status == "success":
        return f"{operation} dry-run preview"
    if isinstance(changes, dict) and changes:
        parts = [f"{key}={value}" for key, value in sorted(changes.items())[:4]]
        return f"{operation} {status}; " + ", ".join(parts)
    if status == "blocked":
        return f"{operation} blocked before mutation"
    return f"{operation} {status}"


def build_record(
    *,
    tool_name: str,
    action: str,
    params: Optional[Dict[str, Any]],
    result: Any,
    risk: Dict[str, Any],
) -> Dict[str, Any]:
    env = _envelope(result)
    status = _status(result, env)
    dry_run = _dry_run_requested(params, result)
    record = {
        "operation_id": _operation_id(result, env),
        "tool": tool_name,
        "action": action,
        "operation": f"{tool_name}.{action}",
        "risk_level": risk.get("level", "unknown"),
        "risk_established": risk.get("recognised"),
        "dry_run": dry_run,
        "timestamp": _now_iso(),
        "summary": _summary(tool_name, action, status, env, dry_run=dry_run),
        "status": status,
    }
    if env.get("execution_id") and env.get("execution_id") != record["operation_id"]:
        record["execution_id"] = env["execution_id"]
    if risk.get("blast_radius"):
        record["blast_radius"] = risk["blast_radius"]
    if env.get("duration_ms") is not None:
        record["duration_ms"] = env["duration_ms"]
    if env.get("changes") is not None:
        record["changes"] = env["changes"]
    return record


def build_exception_record(
    *,
    tool_name: str,
    action: str,
    params: Optional[Dict[str, Any]],
    exc: Exception,
    risk: Dict[str, Any],
    duration_ms: int,
) -> Dict[str, Any]:
    exception_type = exc.__class__.__name__
    operation = f"{tool_name}.{action}"
    return {
        "operation_id": f"op_{uuid.uuid4().hex[:12]}",
        "tool": tool_name,
        "action": action,
        "operation": operation,
        "risk_level": risk.get("level", "unknown"),
        "risk_established": risk.get("recognised"),
        "dry_run": _dry_run_requested(params, None),
        "timestamp": _now_iso(),
        "summary": f"{operation} failed with {exception_type}",
        "status": "failed",
        "blast_radius": risk.get("blast_radius"),
        "duration_ms": max(0, int(duration_ms)),
        "exception": {
            "type": exception_type,
            "message": str(exc),
        },
    }


def write_record(record: Dict[str, Any]) -> None:
    if not operation_log_enabled():
        return
    path = operation_log_path()
    try:
        log_paths.append_line(path, json.dumps(record, sort_keys=True, default=str) + "\n")
    except Exception as exc:
        logger.warning("operation log write failed: %s", exc)
