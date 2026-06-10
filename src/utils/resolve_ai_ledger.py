"""Resolve 21 AI-ops ledger.

Records each Resolve-local AI scripting op (audio classification, IntelliSearch,
slate analysis, motion-deblur, speech generation). These run on Resolve's own
GPU/AI engine and do NOT consume the Claude-side analysis token budget tracked
in `analysis_caps`, so they get their own ledger.

The value of the ledger is mostly the **wall-clock + file/byte accounting** for
the two media-creating ops (`remove_motion_blur`, `generate_speech`). For the
bool-returning analysis ops, an invocation counter + duration is what is
reliable (some may queue work asynchronously inside Resolve, so the recorded
duration is the script-call duration, not necessarily the engine completion).

Persistence reuses `timeline_brain_db` (table `resolve_ai_op_usage`, schema v7).
Every write is best-effort: a ledger failure must never block or corrupt the
underlying Resolve op.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from src.utils import actor_identity, timeline_brain_db

logger = logging.getLogger("resolve-mcp.resolve-ai-ledger")

OP_CLASS_ANALYSIS = "analysis"
OP_CLASS_RENDER = "render"  # produces a new media file

# op name -> (op_class, extra_required or None). The op names match the
# consolidated-server action names.
OP_META: Dict[str, Dict[str, Optional[str]]] = {
    "perform_audio_classification": {"op_class": OP_CLASS_ANALYSIS, "extra_required": None},
    "clear_audio_classification": {"op_class": OP_CLASS_ANALYSIS, "extra_required": None},
    "analyze_for_intellisearch": {"op_class": OP_CLASS_ANALYSIS, "extra_required": "AI IntelliSearch"},
    "analyze_for_slate": {"op_class": OP_CLASS_ANALYSIS, "extra_required": "AI Slate ID"},
    "remove_motion_blur": {"op_class": OP_CLASS_RENDER, "extra_required": None},
    "generate_speech": {"op_class": OP_CLASS_RENDER, "extra_required": "AI Speech Generator"},
}


def op_meta(op: str) -> Dict[str, Optional[str]]:
    return OP_META.get(op, {"op_class": OP_CLASS_ANALYSIS, "extra_required": None})


def _iso(when: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(when if when is not None else time.time()))


def _day_bucket(when: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(when if when is not None else time.time()))


def record_op(
    *,
    project_root: str,
    op: str,
    clip_id: Optional[str] = None,
    session_id: Optional[str] = None,
    success: bool = False,
    wall_clock_ms: int = 0,
    output_path: Optional[str] = None,
    output_bytes: Optional[int] = None,
    error: Optional[str] = None,
    actor: Optional[str] = None,
) -> Optional[int]:
    """Persist one ledger row. Returns the row id, or None on any failure.

    Best-effort: never raises. Callers run this after the Resolve op so a ledger
    problem cannot affect the op itself.
    """
    if not project_root:
        return None
    meta = op_meta(op)
    now = time.time()
    try:
        with timeline_brain_db.transaction(project_root) as txn:
            cursor = txn.execute(
                """
                INSERT INTO resolve_ai_op_usage(
                    op, op_class, clip_id, session_id, success, wall_clock_ms,
                    output_path, output_bytes, extra_required, error,
                    occurred_at, day_bucket, actor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    op, meta["op_class"], clip_id, session_id, 1 if success else 0,
                    int(wall_clock_ms), output_path,
                    int(output_bytes) if output_bytes is not None else None,
                    meta["extra_required"], error,
                    _iso(now), _day_bucket(now),
                    actor or actor_identity.actor_string(),
                ),
            )
            return cursor.lastrowid
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("resolve_ai_ledger.record_op failed: %s", exc)
        return None


class timed:
    """Context manager that times a Resolve AI op and records it on exit.

    Usage:
        with resolve_ai_ledger.timed(project_root, "analyze_for_slate", clip_id=cid) as rec:
            ok = bool(clip.AnalyzeForSlate(color))
            rec.success = ok
        # row written automatically; exceptions are recorded then re-raised.

    For media-creating ops, set rec.output_path / rec.output_bytes before exit.
    All recording is best-effort and never masks the op's own exception.
    """

    def __init__(
        self,
        project_root: Optional[str],
        op: str,
        *,
        clip_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.project_root = project_root
        self.op = op
        self.clip_id = clip_id
        self.session_id = session_id
        self.success: bool = False
        self.output_path: Optional[str] = None
        self.output_bytes: Optional[int] = None
        self.error: Optional[str] = None
        self.row_id: Optional[int] = None
        self._start: float = 0.0

    def __enter__(self) -> "timed":
        self._start = time.time()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        wall_clock_ms = int((time.time() - self._start) * 1000)
        if exc is not None and self.error is None:
            self.error = f"{exc_type.__name__}: {exc}" if exc_type else str(exc)
        if self.project_root:
            self.row_id = record_op(
                project_root=self.project_root,
                op=self.op,
                clip_id=self.clip_id,
                session_id=self.session_id,
                success=self.success,
                wall_clock_ms=wall_clock_ms,
                output_path=self.output_path,
                output_bytes=self.output_bytes,
                error=self.error,
            )
        return False  # never suppress the op's own exception


def get_usage(
    *,
    project_root: str,
    session_id: Optional[str] = None,
    op: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Return recent ledger rows, newest first."""
    if not project_root:
        return []
    clauses: List[str] = []
    args: List[Any] = []
    if session_id:
        clauses.append("session_id = ?")
        args.append(session_id)
    if op:
        clauses.append("op = ?")
        args.append(op)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    try:
        conn = timeline_brain_db.connect(project_root)
        rows = conn.execute(
            f"""
            SELECT op, op_class, clip_id, session_id, success, wall_clock_ms,
                   output_path, output_bytes, extra_required, error, occurred_at, actor
            FROM resolve_ai_op_usage{where}
            ORDER BY id DESC LIMIT ?
            """,
            (*args, int(limit)),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("resolve_ai_ledger.get_usage failed: %s", exc)
        return []
    return [dict(r) for r in rows]


def get_summary(*, project_root: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate ledger rows into per-op and overall totals.

    Returns counts, successes, total wall-clock, and total files/bytes created
    (the latter meaningful only for render-class ops).
    """
    empty = {"by_op": {}, "totals": {"runs": 0, "successes": 0, "failures": 0,
                                      "wall_clock_ms": 0, "files_created": 0, "bytes_created": 0}}
    if not project_root:
        return empty
    clause = " WHERE session_id = ?" if session_id else ""
    args = (session_id,) if session_id else ()
    try:
        conn = timeline_brain_db.connect(project_root)
        rows = conn.execute(
            f"""
            SELECT op, op_class, success, wall_clock_ms, output_path, output_bytes
            FROM resolve_ai_op_usage{clause}
            """,
            args,
        ).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("resolve_ai_ledger.get_summary failed: %s", exc)
        return empty

    by_op: Dict[str, Dict[str, Any]] = {}
    totals = {"runs": 0, "successes": 0, "failures": 0, "wall_clock_ms": 0,
              "files_created": 0, "bytes_created": 0}
    for r in rows:
        op = r["op"]
        bucket = by_op.setdefault(op, {
            "op_class": r["op_class"], "runs": 0, "successes": 0, "failures": 0,
            "wall_clock_ms": 0, "files_created": 0, "bytes_created": 0,
        })
        bucket["runs"] += 1
        totals["runs"] += 1
        if r["success"]:
            bucket["successes"] += 1
            totals["successes"] += 1
        else:
            bucket["failures"] += 1
            totals["failures"] += 1
        bucket["wall_clock_ms"] += r["wall_clock_ms"] or 0
        totals["wall_clock_ms"] += r["wall_clock_ms"] or 0
        if r["output_path"]:
            bucket["files_created"] += 1
            totals["files_created"] += 1
        if r["output_bytes"]:
            bucket["bytes_created"] += r["output_bytes"]
            totals["bytes_created"] += r["output_bytes"]
    return {"by_op": by_op, "totals": totals}
