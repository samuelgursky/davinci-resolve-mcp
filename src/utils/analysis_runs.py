"""Run-scoping for the destructive-op hook (C6 hardening).

A *run* groups a sequence of destructive operations under a single ID so that:

1. **Archives collapse correctly.** Without run scoping, every destructive call
   without an explicit `analysis_run_id` archives separately. A single brain
   operation that touches five clips creates five archives. With run scoping,
   the brain calls `begin_run` once, every subsequent destructive call within
   that run reuses the same ID, and only the first one archives — the rest log
   brain_edits under the same archived predecessor.
2. **Cumulative metrics are computable.** `end_run` aggregates every brain_edit
   for the run, captures a final timeline snapshot, and writes the rollup to
   `analysis_runs.summary_json`. That's the row the dashboard reads to answer
   "did this run improve the cut?"
3. **Provenance is tracked.** Each run records its `initiator` (e.g.
   "control_panel", "brain.chat", "agent.batch", "user.explicit"). The
   `brain_edits.initiator` column is populated from the active run.

Process-level state: a single `current_run_id` per process. The MCP server and
the dashboard are separate processes, each with their own current run; that's
intentional — a dashboard-initiated archive shouldn't get bundled into the
brain's in-flight run.

Threading: `_CURRENT_RUN` access is guarded by a lock, but a run is logically
single-threaded. If two requests overlap with different `begin_run` calls,
the second one's begin replaces the first — the first run remains in the DB
but no longer accumulates edits. We could enforce stack-style nesting later if
overlap becomes a real concern.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from src.utils import timeline_brain_db

logger = logging.getLogger("resolve-mcp.analysis-runs")

_LOCK = threading.Lock()
_CURRENT_RUN: Dict[str, Optional[str]] = {"id": None, "initiator": None, "label": None}

# B3 — Auto-run idle tracking. Bumped on every destructive call within a run.
_LAST_DESTRUCTIVE_AT: Dict[str, float] = {"epoch": 0.0}
_DEFAULT_AUTO_RUN_IDLE_TIMEOUT_S = 90.0


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


# ── Public API ───────────────────────────────────────────────────────────────


def begin_run(
    *,
    project_root: str,
    label: Optional[str] = None,
    initiator: Optional[str] = None,
    analysis_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Open a new run. Stamps `analysis_run_id` (or generates one) as the
    process-level current run so the hook reads it automatically."""
    run_id = analysis_run_id or _new_run_id()
    started_at = _now_iso()
    with timeline_brain_db.transaction(project_root) as txn:
        txn.execute(
            """
            INSERT INTO analysis_runs(id, label, initiator, started_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                label = COALESCE(excluded.label, analysis_runs.label),
                initiator = COALESCE(excluded.initiator, analysis_runs.initiator)
            """,
            (run_id, label, initiator, started_at),
        )
    with _LOCK:
        # If an earlier run is still active, log a warning — the user probably
        # forgot to end_run.
        if _CURRENT_RUN["id"] and _CURRENT_RUN["id"] != run_id:
            logger.warning(
                "begin_run replacing previously-active run %s with %s (no end_run was called)",
                _CURRENT_RUN["id"], run_id,
            )
        _CURRENT_RUN["id"] = run_id
        _CURRENT_RUN["initiator"] = initiator
        _CURRENT_RUN["label"] = label
    return {
        "success": True,
        "analysis_run_id": run_id,
        "label": label,
        "initiator": initiator,
        "started_at": started_at,
    }


def end_run(
    *,
    project_root: str,
    analysis_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Close a run. Aggregates brain_edits + version count into `summary_json`."""
    target_run_id: Optional[str] = analysis_run_id
    with _LOCK:
        active = _CURRENT_RUN["id"]
        if target_run_id is None:
            target_run_id = active
        if active == target_run_id:
            _CURRENT_RUN["id"] = None
            _CURRENT_RUN["initiator"] = None
            _CURRENT_RUN["label"] = None
    if not target_run_id:
        return {"success": False, "error": "no active run; pass analysis_run_id to end a specific run"}

    conn = timeline_brain_db.connect(project_root)
    edits = conn.execute(
        """
        SELECT edit_type, target_metric, before_value, after_value
        FROM brain_edits WHERE analysis_run_id = ?
        """,
        (target_run_id,),
    ).fetchall()
    version_rows = conn.execute(
        """
        SELECT COUNT(*) AS c, MIN(version) AS min_v, MAX(version) AS max_v
        FROM timeline_versions WHERE analysis_run_id = ?
        """,
        (target_run_id,),
    ).fetchone()

    summary = _summarise_run(list(edits), version_rows)
    ended_at = _now_iso()
    with timeline_brain_db.transaction(project_root) as txn:
        txn.execute(
            "UPDATE analysis_runs SET ended_at = ?, summary_json = ? WHERE id = ?",
            (ended_at, json.dumps(summary), target_run_id),
        )

    return {
        "success": True,
        "analysis_run_id": target_run_id,
        "ended_at": ended_at,
        "summary": summary,
    }


def current_run_id() -> Optional[str]:
    """Read the active process-level run ID. None if no run is open."""
    with _LOCK:
        return _CURRENT_RUN["id"]


# ── B3 — Auto-run lifecycle ──────────────────────────────────────────────────


def ensure_auto_run_for_destructive(
    *,
    project_root: str,
    idle_timeout_seconds: Optional[float] = None,
) -> str:
    """Return the analysis_run_id to use for a destructive op.

    Behavior:
    - If a run is already active and within the idle timeout: reuse it, bump idle timer.
    - If a run is active but idle timer expired: end_run it, open a fresh auto-run.
    - If no run is active: open a fresh auto-run with initiator="auto".

    The caller (destructive_hook) plumbs the returned run_id through the
    rest of its bookkeeping just as it would an explicit begin_run id.
    """
    timeout = float(idle_timeout_seconds if idle_timeout_seconds is not None else _DEFAULT_AUTO_RUN_IDLE_TIMEOUT_S)
    now = time.time()
    with _LOCK:
        active = _CURRENT_RUN["id"]
        last = _LAST_DESTRUCTIVE_AT["epoch"]
        if active and last and (now - last) > timeout:
            # idle timeout — auto-close before opening fresh
            stale_id = active
            _CURRENT_RUN["id"] = None
            _CURRENT_RUN["initiator"] = None
            _CURRENT_RUN["label"] = None
        else:
            stale_id = None

    if stale_id:
        try:
            end_run(project_root=project_root, analysis_run_id=stale_id)
        except Exception as exc:  # never block the destructive call on close failure
            logger.warning("auto end_run for %s failed: %s", stale_id, exc)

    with _LOCK:
        if _CURRENT_RUN["id"]:
            _LAST_DESTRUCTIVE_AT["epoch"] = now
            return str(_CURRENT_RUN["id"])

    # Open a fresh auto-run.
    result = begin_run(project_root=project_root, label=f"auto-{_now_iso()}", initiator="auto")
    with _LOCK:
        _LAST_DESTRUCTIVE_AT["epoch"] = now
    return str(result["analysis_run_id"])


def bump_idle_timer() -> None:
    """Called by destructive_hook on every wrap entry within an active run."""
    with _LOCK:
        _LAST_DESTRUCTIVE_AT["epoch"] = time.time()


def current_run_initiator() -> Optional[str]:
    with _LOCK:
        return _CURRENT_RUN["initiator"]


def get_run(project_root: str, analysis_run_id: str) -> Optional[Dict[str, Any]]:
    conn = timeline_brain_db.connect(project_root)
    row = conn.execute(
        "SELECT id, label, initiator, started_at, ended_at, summary_json FROM analysis_runs WHERE id = ?",
        (analysis_run_id,),
    ).fetchone()
    if row is None:
        return None
    out = dict(row)
    raw = out.pop("summary_json")
    out["summary"] = json.loads(raw) if raw else None
    return out


def list_runs(project_root: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    # SQLite treats a negative LIMIT as "no limit"; clamp (EX8).
    try:
        limit = max(1, min(1000, int(limit)))
    except (TypeError, ValueError):
        limit = 50
    conn = timeline_brain_db.connect(project_root)
    rows = conn.execute(
        """
        SELECT id, label, initiator, started_at, ended_at, summary_json
        FROM analysis_runs
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        raw = d.pop("summary_json")
        d["summary"] = json.loads(raw) if raw else None
        out.append(d)
    return out


# ── Test hooks ───────────────────────────────────────────────────────────────


def _reset_for_test() -> None:
    """Tests only: clear the process-level current run."""
    with _LOCK:
        _CURRENT_RUN["id"] = None
        _CURRENT_RUN["initiator"] = None
        _CURRENT_RUN["label"] = None
        _LAST_DESTRUCTIVE_AT["epoch"] = 0.0


# ── Helpers ──────────────────────────────────────────────────────────────────


def _summarise_run(edits: List[Any], version_row: Any) -> Dict[str, Any]:
    """Aggregate brain_edits into a per-metric rollup."""
    per_metric: Dict[str, Dict[str, Any]] = {}
    for edit in edits:
        metric = edit["target_metric"] if isinstance(edit, dict) or hasattr(edit, "__getitem__") else None
        try:
            metric = edit["target_metric"]
            before = edit["before_value"]
            after = edit["after_value"]
        except (KeyError, IndexError, TypeError):
            continue
        if not metric:
            continue
        bucket = per_metric.setdefault(metric, {"edit_count": 0, "first_before": None, "last_after": None, "total_delta": 0.0})
        bucket["edit_count"] += 1
        if before is not None and bucket["first_before"] is None:
            bucket["first_before"] = float(before)
        if after is not None:
            bucket["last_after"] = float(after)
        if before is not None and after is not None:
            try:
                bucket["total_delta"] = round(bucket["total_delta"] + (float(after) - float(before)), 6)
            except (TypeError, ValueError):
                pass

    return {
        "edit_count": len(edits),
        "version_count": int(version_row["c"]) if version_row and version_row["c"] is not None else 0,
        "first_version": (int(version_row["min_v"]) if version_row and version_row["min_v"] is not None else None),
        "last_version": (int(version_row["max_v"]) if version_row and version_row["max_v"] is not None else None),
        "per_metric": per_metric,
    }
