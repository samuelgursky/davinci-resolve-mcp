"""Brain-edit logging + metric capture (C6).

A *brain edit* is any timeline mutation that should be measured. Two callers:

1. **Automatic** — the destructive-op hook in `src/server.py` logs a row for
   every destructive action call, even when the caller didn't declare a metric.
   Gives history without requiring deliberate intent.
2. **Declared** — a caller that knows it's making an editorial improvement
   (a take swap, a gap close, a pacing tighten) passes `metric`, `direction`,
   and `rationale` in the action params, plus computes `before_value` and
   `after_value` from the metric vocabulary helpers below. These rows form the
   measurement substrate for tuning the brain.

The cross-project rollup (`brain_edits_registry.json`) is updated by
`update_brain_edits_registry()` after each `log_brain_edit()`. Mirrors the
existing `analysis_registry.json` pattern.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

from src.utils import actor_identity, timeline_brain_db

logger = logging.getLogger("resolve-mcp.brain-edits")

# ── Metric vocabulary ────────────────────────────────────────────────────────
#
# Starter set. Add new metrics here; the brain (and the dashboard) consult this
# registry to know how to render and aggregate them. `direction` is the
# default-better direction; an `direction` override at log-time wins.

METRIC_DURATION_SECONDS = "duration_seconds"
METRIC_AVG_PERFORMANCE = "avg_performance_score"
METRIC_CLIP_COUNT = "clip_count"
METRIC_GAP_COUNT = "gap_count"
METRIC_TOTAL_GAP_SECONDS = "total_gap_seconds"
METRIC_REDUNDANCY_SCORE = "redundancy_score"
METRIC_COLOR_INTENT = "color_intent"

METRIC_REGISTRY: Dict[str, Dict[str, Any]] = {
    METRIC_DURATION_SECONDS: {
        "label": "Duration (seconds)",
        "unit": "s",
        "default_direction": "target_value",
    },
    METRIC_AVG_PERFORMANCE: {
        "label": "Avg performance score",
        "unit": "score 0-1",
        "default_direction": "increase",
    },
    METRIC_CLIP_COUNT: {
        "label": "Clip count",
        "unit": "clips",
        "default_direction": "target_value",
    },
    METRIC_GAP_COUNT: {
        "label": "Gap count",
        "unit": "gaps",
        "default_direction": "decrease",
    },
    METRIC_TOTAL_GAP_SECONDS: {
        "label": "Total gap duration (seconds)",
        "unit": "s",
        "default_direction": "decrease",
    },
    METRIC_REDUNDANCY_SCORE: {
        "label": "Redundancy score",
        "unit": "score 0-1",
        "default_direction": "decrease",
    },
    METRIC_COLOR_INTENT: {
        "label": "Color intent",
        "unit": "qualitative",
        "default_direction": "target_value",
    },
}

DIRECTIONS = {"increase", "decrease", "target_value"}

# Cross-project registry filename (one level above project root)
REGISTRY_FILENAME = "brain_edits_registry.json"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Metric capture helpers ────────────────────────────────────────────────────


def capture_timeline_duration_seconds(timeline: Any) -> Optional[float]:
    """Compute duration in seconds from a Resolve Timeline handle."""
    try:
        start = int(timeline.GetStartFrame())
        end = int(timeline.GetEndFrame())
        fps_setting = timeline.GetSetting("timelineFrameRate")
        fps = float(fps_setting) if fps_setting else 24.0
        if fps <= 0:
            return None
        return max(0.0, (end - start) / fps)
    except Exception as exc:  # pragma: no cover — Resolve API surface
        logger.debug("capture_timeline_duration_seconds failed: %s", exc)
        return None


def capture_timeline_clip_count(timeline: Any) -> Optional[int]:
    """Sum of video + audio + subtitle clips across all tracks."""
    try:
        total = 0
        for tt in ("video", "audio", "subtitle"):
            count = timeline.GetTrackCount(tt)
            if not count:
                continue
            for ti in range(1, int(count) + 1):
                items = timeline.GetItemListInTrack(tt, ti) or []
                total += len(items)
        return total
    except Exception as exc:  # pragma: no cover
        logger.debug("capture_timeline_clip_count failed: %s", exc)
        return None


def capture_timeline_gap_stats(timeline: Any, *, track_types=("video",)) -> Dict[str, Any]:
    """Compute gap_count and total_gap_seconds on a timeline.

    Single-track-per-type gap detection: walks each track in order, accumulates
    the empty frames between consecutive items. Multi-track overlap is ignored
    here (gaps are per-track).
    """
    out = {"gap_count": 0, "total_gap_frames": 0, "total_gap_seconds": None}
    try:
        fps_setting = timeline.GetSetting("timelineFrameRate")
        fps = float(fps_setting) if fps_setting else 24.0
        for tt in track_types:
            count = timeline.GetTrackCount(tt)
            if not count:
                continue
            for ti in range(1, int(count) + 1):
                items = timeline.GetItemListInTrack(tt, ti) or []
                items_sorted = sorted(items, key=lambda it: int(it.GetStart()))
                for prev, curr in zip(items_sorted, items_sorted[1:]):
                    gap_frames = int(curr.GetStart()) - int(prev.GetEnd())
                    if gap_frames > 0:
                        out["gap_count"] += 1
                        out["total_gap_frames"] += gap_frames
        if fps > 0:
            out["total_gap_seconds"] = round(out["total_gap_frames"] / fps, 3)
    except Exception as exc:  # pragma: no cover
        logger.debug("capture_timeline_gap_stats failed: %s", exc)
    return out


METRIC_CAPTURERS: Dict[str, Callable[[Any], Any]] = {
    METRIC_DURATION_SECONDS: capture_timeline_duration_seconds,
    METRIC_CLIP_COUNT: capture_timeline_clip_count,
    METRIC_GAP_COUNT: lambda tl: capture_timeline_gap_stats(tl)["gap_count"],
    METRIC_TOTAL_GAP_SECONDS: lambda tl: capture_timeline_gap_stats(tl)["total_gap_seconds"],
}


def capture_metric(metric: str, timeline: Any) -> Optional[float]:
    """Capture a registered metric from a live timeline. None if not capturable."""
    fn = METRIC_CAPTURERS.get(metric)
    if fn is None:
        return None
    try:
        value = fn(timeline)
    except Exception as exc:  # pragma: no cover
        logger.debug("capture_metric(%s) failed: %s", metric, exc)
        return None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Logging ──────────────────────────────────────────────────────────────────


def log_brain_edit(
    *,
    project_root: str,
    analysis_run_id: str,
    edit_type: str,
    tool_name: Optional[str] = None,
    action_name: Optional[str] = None,
    timeline_before: Optional[str] = None,
    timeline_after: Optional[str] = None,
    target_metric: Optional[str] = None,
    metric_direction: Optional[str] = None,
    before_value: Optional[float] = None,
    after_value: Optional[float] = None,
    rationale: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    result_summary: Optional[Dict[str, Any]] = None,
    project_name: Optional[str] = None,
    initiator: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a brain-edit row + update the cross-project registry."""
    if target_metric is not None and target_metric not in METRIC_REGISTRY:
        logger.warning("Unknown metric '%s' — logging anyway", target_metric)
    if metric_direction is not None and metric_direction not in DIRECTIONS:
        return {"success": False, "error": f"Invalid direction: {metric_direction}"}

    params_json = json.dumps(params, default=str) if params is not None else None
    result_json = json.dumps(result_summary, default=str) if result_summary is not None else None
    created_at = _now_iso()

    with timeline_brain_db.transaction(project_root) as txn:
        cursor = txn.execute(
            """
            INSERT INTO brain_edits(
                analysis_run_id, timeline_before, timeline_after, edit_type,
                tool_name, action_name, target_metric, metric_direction,
                before_value, after_value, rationale, params_json,
                result_summary_json, created_at, initiator, actor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_run_id, timeline_before, timeline_after, edit_type,
                tool_name, action_name, target_metric, metric_direction,
                before_value, after_value, rationale, params_json,
                result_json, created_at, initiator,
                actor_identity.actor_string(),
            ),
        )
        row_id = cursor.lastrowid

    try:
        update_brain_edits_registry(
            project_root=project_root,
            project_name=project_name,
            summary={
                "row_id": row_id,
                "analysis_run_id": analysis_run_id,
                "timeline_before": timeline_before,
                "timeline_after": timeline_after,
                "edit_type": edit_type,
                "tool_name": tool_name,
                "action_name": action_name,
                "target_metric": target_metric,
                "before_value": before_value,
                "after_value": after_value,
                "delta": _compute_delta(before_value, after_value),
                "created_at": created_at,
            },
        )
    except Exception as exc:
        logger.warning("update_brain_edits_registry failed (non-fatal): %s", exc)

    return {"success": True, "row_id": row_id, "created_at": created_at}


def _compute_delta(before: Optional[float], after: Optional[float]) -> Optional[float]:
    if before is None or after is None:
        return None
    try:
        return round(float(after) - float(before), 6)
    except (TypeError, ValueError):
        return None


# ── Query ─────────────────────────────────────────────────────────────────────


def get_brain_edit_history(
    *,
    project_root: str,
    timeline_name: Optional[str] = None,
    analysis_run_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return brain_edit rows, optionally filtered by timeline or run, newest first."""
    # SQLite treats a negative LIMIT as "no limit"; clamp so a negative/huge
    # limit can't silently fetch the whole table (EX8).
    try:
        limit = max(1, min(1000, int(limit)))
    except (TypeError, ValueError):
        limit = 50
    conn = timeline_brain_db.connect(project_root)
    clauses: List[str] = []
    args: List[Any] = []
    if timeline_name:
        clauses.append("(timeline_before = ? OR timeline_after = ?)")
        args.extend([timeline_name, timeline_name])
    if analysis_run_id:
        clauses.append("analysis_run_id = ?")
        args.append(analysis_run_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"""
        SELECT id, analysis_run_id, timeline_before, timeline_after, edit_type,
               tool_name, action_name, target_metric, metric_direction,
               before_value, after_value, rationale, params_json,
               result_summary_json, created_at, rolled_back_at
        FROM brain_edits
        {where}
        ORDER BY id DESC
        LIMIT ?
        """,
        (*args, int(limit)),
    ).fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for key in ("params_json", "result_summary_json"):
            raw = d.pop(key)
            d[key[:-5]] = json.loads(raw) if raw else None
        d["delta"] = _compute_delta(d.get("before_value"), d.get("after_value"))
        out.append(d)
    return out


# ── Cross-project rollup ─────────────────────────────────────────────────────


def _registry_path_for(project_root: str) -> str:
    base_root = os.path.dirname(os.path.normpath(project_root))
    return os.path.join(base_root, REGISTRY_FILENAME)


def update_brain_edits_registry(
    *,
    project_root: str,
    project_name: Optional[str],
    summary: Dict[str, Any],
    max_rows: int = 5000,
) -> Dict[str, Any]:
    """Append `summary` to the cross-project registry; trim oldest beyond max_rows.

    The registry sits one level above each project_root (the analysis "base
    root"), so it aggregates every project that shares that base. Mirrors how
    `analysis_registry.json` is positioned.
    """
    if not project_root:
        return {"success": False, "error": "project_root required"}
    path = _registry_path_for(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    payload: Dict[str, Any]
    if os.path.isfile(path):
        try:
            with open(path, "r") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            payload = {"entries": []}
    else:
        payload = {"entries": []}

    entries = payload.setdefault("entries", [])
    entry = {
        "project_root": project_root,
        "project_name": project_name or os.path.basename(project_root.rstrip("/")),
        **summary,
    }
    entries.append(entry)
    if len(entries) > max_rows:
        del entries[: len(entries) - max_rows]
    payload["entries"] = entries
    payload["updated_at"] = _now_iso()

    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    os.replace(tmp_path, path)
    return {"success": True, "registry_path": path, "entry_count": len(entries)}


def read_brain_edits_registry(project_root: str) -> Dict[str, Any]:
    path = _registry_path_for(project_root)
    if not os.path.isfile(path):
        return {"entries": [], "registry_path": path}
    try:
        with open(path, "r") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"entries": [], "registry_path": path}
    payload["registry_path"] = path
    return payload
