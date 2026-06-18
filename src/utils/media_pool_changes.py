"""Media-pool destructive-op logger (C6 hardening).

Media pool ops don't mutate a timeline directly, so they bypass the
timeline-version-on-mutate path. But they DO have downstream effects on
timelines (offline clips, broken references), so we log them to a dedicated
`media_pool_changes` table for provenance + future diff work.

Captures: action, target clip/folder id and name, the params payload, and the
active run/initiator. Doesn't try to snapshot bin state — that's potentially
huge; defer to a manual `snapshot_media_pool` action when needed.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from src.utils import timeline_brain_db

logger = logging.getLogger("resolve-mcp.media-pool-changes")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _extract_target_info(action: str, params: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Best-effort id/name extraction from the action payload."""
    if not isinstance(params, dict):
        return {"target_id": None, "target_name": None}
    # Try common shapes.
    for key in ("clip_id", "folder_id", "id", "target_id"):
        if params.get(key):
            return {"target_id": str(params[key]), "target_name": params.get("name") or params.get("clip_name") or params.get("folder_name")}
    # List shapes (delete_media_pool_clips takes clip_ids: [...])
    for key in ("clip_ids", "ids", "folder_ids"):
        if isinstance(params.get(key), list) and params[key]:
            ids = params[key]
            return {"target_id": ",".join(str(x) for x in ids[:5]) + (" +more" if len(ids) > 5 else ""), "target_name": None}
    return {"target_id": None, "target_name": params.get("name") or None}


def log_media_pool_change(
    *,
    project_root: str,
    analysis_run_id: Optional[str],
    action: str,
    params: Optional[Dict[str, Any]] = None,
    before_state: Optional[Dict[str, Any]] = None,
    after_state: Optional[Dict[str, Any]] = None,
    initiator: Optional[str] = None,
) -> Dict[str, Any]:
    target = _extract_target_info(action, params)
    params_json = json.dumps(params, default=str) if params is not None else None
    before_json = json.dumps(before_state, default=str) if before_state is not None else None
    after_json = json.dumps(after_state, default=str) if after_state is not None else None
    created_at = _now_iso()

    with timeline_brain_db.transaction(project_root) as txn:
        cursor = txn.execute(
            """
            INSERT INTO media_pool_changes(
                analysis_run_id, action, target_id, target_name,
                before_state_json, after_state_json, params_json,
                initiator, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_run_id, action, target["target_id"], target["target_name"],
                before_json, after_json, params_json,
                initiator, created_at,
            ),
        )
        row_id = cursor.lastrowid
    return {"success": True, "row_id": row_id, "created_at": created_at}


def get_media_pool_change_history(
    *,
    project_root: str,
    analysis_run_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    # SQLite treats a negative LIMIT as "no limit"; clamp (EX8).
    try:
        limit = max(1, min(1000, int(limit)))
    except (TypeError, ValueError):
        limit = 50
    conn = timeline_brain_db.connect(project_root)
    clauses: List[str] = []
    args: List[Any] = []
    if analysis_run_id:
        clauses.append("analysis_run_id = ?")
        args.append(analysis_run_id)
    if action:
        clauses.append("action = ?")
        args.append(action)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"""
        SELECT id, analysis_run_id, action, target_id, target_name,
               before_state_json, after_state_json, params_json,
               initiator, created_at
        FROM media_pool_changes
        {where}
        ORDER BY id DESC
        LIMIT ?
        """,
        (*args, int(limit)),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for key in ("before_state_json", "after_state_json", "params_json"):
            raw = d.pop(key)
            d[key[:-5]] = json.loads(raw) if raw else None
        out.append(d)
    return out
