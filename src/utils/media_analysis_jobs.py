"""Single-user batch jobs for source-safe media analysis.

The job layer is deliberately small and durable: SQLite tracks operational
state, the existing JSON reports remain the analysis source of truth, and each
runner call processes a bounded slice so agents do not need to hold long chat
turns open.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.utils.media_analysis import (
    ANALYSIS_VERSION,
    build_analysis_index,
    build_plan,
    detect_capabilities,
    execute_plan,
    normalize_path,
    plan_requires_capabilities,
    resolve_output_root,
    stable_clip_directory,
    summarize_reports,
)


JOBS_DB_FILENAME = "jobs.sqlite"
JOB_SCHEMA_VERSION = 1
JOB_DIR_NAME = "jobs"
MEDIA_EXTENSIONS = {
    ".3g2",
    ".3gp",
    ".aac",
    ".aif",
    ".aiff",
    ".ari",
    ".arx",
    ".braw",
    ".cin",
    ".crm",
    ".dng",
    ".dv",
    ".exr",
    ".flac",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mxf",
    ".ogg",
    ".r3d",
    ".rmf",
    ".wav",
    ".webm",
}


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _read_json(value: str) -> Dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _job_id(name: str, target: Dict[str, Any], created_at: str) -> str:
    basis = _stable_json({"name": name, "target": target, "created_at": created_at})
    return "job-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _is_relative_to(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:
        return False


def job_db_path(project_root: str, path: Optional[Any] = None) -> Tuple[Optional[str], Optional[str]]:
    root = normalize_path(project_root)
    candidate = normalize_path(path) if path else os.path.join(root, JOBS_DB_FILENAME)
    if not _is_relative_to(candidate, root):
        return None, "jobs database path must be under the project analysis root"
    return candidate, None


def _connect_jobs(project_root: str, path: Optional[Any] = None) -> sqlite3.Connection:
    db_path, err = job_db_path(project_root, path)
    if err or not db_path:
        raise ValueError(err or "Invalid jobs database path")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS job_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            phase TEXT NOT NULL,
            project_name TEXT NOT NULL,
            project_id TEXT,
            project_root TEXT NOT NULL,
            target_json TEXT NOT NULL,
            params_json TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            total_clips INTEGER NOT NULL DEFAULT 0,
            pending_clips INTEGER NOT NULL DEFAULT 0,
            running_clips INTEGER NOT NULL DEFAULT 0,
            succeeded_clips INTEGER NOT NULL DEFAULT 0,
            failed_clips INTEGER NOT NULL DEFAULT 0,
            skipped_clips INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            canceled_at TEXT
        );

        CREATE TABLE IF NOT EXISTS job_clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            clip_key TEXT NOT NULL,
            status TEXT NOT NULL,
            record_json TEXT NOT NULL,
            clip_plan_json TEXT NOT NULL,
            report_path TEXT,
            marker_plan_path TEXT,
            cache_status TEXT,
            error TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(job_id, position),
            FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_job_clips_job_status ON job_clips(job_id, status, position);
        CREATE INDEX IF NOT EXISTS idx_job_clips_clip_key ON job_clips(clip_key);

        CREATE TABLE IF NOT EXISTS job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            event_time TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            payload_json TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id, id);
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO job_metadata (key, value) VALUES (?, ?)",
        ("schema_version", str(JOB_SCHEMA_VERSION)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO job_metadata (key, value) VALUES (?, ?)",
        ("analysis_version", ANALYSIS_VERSION),
    )
    conn.commit()


def _event(conn: sqlite3.Connection, job_id: str, level: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
    conn.execute(
        "INSERT INTO job_events (job_id, event_time, level, message, payload_json) VALUES (?, ?, ?, ?, ?)",
        (job_id, _utc_now(), level, message, _stable_json(payload or {}) if payload else None),
    )


def _sync_job_counts(conn: sqlite3.Connection, job_id: str) -> Dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM job_clips WHERE job_id = ? GROUP BY status",
        (job_id,),
    ).fetchall()
    counts = {row["status"]: int(row["count"]) for row in rows}
    payload = {
        "pending_clips": counts.get("pending", 0),
        "running_clips": counts.get("running", 0),
        "succeeded_clips": counts.get("succeeded", 0),
        "failed_clips": counts.get("failed", 0),
        "skipped_clips": counts.get("skipped", 0),
    }
    conn.execute(
        """
        UPDATE jobs
        SET pending_clips = ?, running_clips = ?, succeeded_clips = ?,
            failed_clips = ?, skipped_clips = ?, updated_at = ?
        WHERE job_id = ?
        """,
        (
            payload["pending_clips"],
            payload["running_clips"],
            payload["succeeded_clips"],
            payload["failed_clips"],
            payload["skipped_clips"],
            _utc_now(),
            job_id,
        ),
    )
    return payload


def _row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _job_paths(project_root: str, job_id: str) -> Dict[str, str]:
    job_dir = os.path.join(normalize_path(project_root), JOB_DIR_NAME, job_id)
    return {
        "job_dir": job_dir,
        "progress_json": os.path.join(job_dir, "progress.json"),
        "events_jsonl": os.path.join(job_dir, "events.jsonl"),
    }


def _write_job_sidecars(conn: sqlite3.Connection, project_root: str, job_id: str) -> None:
    paths = _job_paths(project_root, job_id)
    os.makedirs(paths["job_dir"], exist_ok=True)
    status = batch_job_status(project_root, job_id)
    tmp_progress = f"{paths['progress_json']}.tmp"
    with open(tmp_progress, "w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp_progress, paths["progress_json"])

    rows = conn.execute(
        """
        SELECT event_time, level, message, payload_json
        FROM job_events
        WHERE job_id = ?
        ORDER BY id
        """,
        (job_id,),
    ).fetchall()
    tmp_events = f"{paths['events_jsonl']}.tmp"
    with open(tmp_events, "w", encoding="utf-8") as handle:
        for row in rows:
            payload = {
                "time": row["event_time"],
                "level": row["level"],
                "message": row["message"],
            }
            if row["payload_json"]:
                payload["payload"] = _read_json(row["payload_json"])
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    os.replace(tmp_events, paths["events_jsonl"])


def _job_summary_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    payload = _row_dict(row)
    total = int(payload.get("total_clips") or 0)
    done = int(payload.get("succeeded_clips") or 0) + int(payload.get("failed_clips") or 0) + int(payload.get("skipped_clips") or 0)
    payload["progress"] = {
        "done_clips": done,
        "total_clips": total,
        "percent": round((done / total) * 100, 2) if total else 0.0,
    }
    for json_key in ("target_json", "params_json"):
        target_key = json_key.replace("_json", "")
        payload[target_key] = _read_json(str(payload.pop(json_key, "{}")))
    payload.pop("plan_json", None)
    return payload


def records_from_paths(paths: Iterable[Any], *, recursive: bool = True) -> Tuple[List[Dict[str, Any]], List[str]]:
    records: List[Dict[str, Any]] = []
    warnings: List[str] = []
    seen = set()
    for raw_path in paths:
        if raw_path in (None, ""):
            continue
        path = normalize_path(raw_path)
        candidates: List[str] = []
        if os.path.isdir(path):
            walker = os.walk(path)
            for dirpath, dirnames, filenames in walker:
                if not recursive:
                    dirnames[:] = []
                for filename in sorted(filenames):
                    candidate = os.path.join(dirpath, filename)
                    if Path(candidate).suffix.lower() in MEDIA_EXTENSIONS:
                        candidates.append(candidate)
        elif os.path.isfile(path):
            if Path(path).suffix.lower() in MEDIA_EXTENSIONS:
                candidates.append(path)
            else:
                warnings.append(f"Skipping unsupported file extension: {path}")
        else:
            warnings.append(f"Path not found: {path}")
        for candidate in sorted(candidates):
            normalized = normalize_path(candidate)
            if normalized in seen:
                continue
            seen.add(normalized)
            records.append(
                {
                    "clip_id": None,
                    "clip_name": os.path.basename(normalized),
                    "bin_path": None,
                    "file_path": normalized,
                    "media_id": None,
                    "duration": None,
                    "fps": None,
                    "resolution": None,
                    "media_type": "file",
                }
            )
    return records, warnings


def create_batch_job(
    *,
    project_name: Any,
    project_id: Any = None,
    records: List[Dict[str, Any]],
    target: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
    capabilities: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    params = dict(params or {})
    params["dry_run"] = False
    params["session_only"] = False
    params["persist"] = True
    params.setdefault("cleanup_frames", True)
    params.setdefault("reuse_existing", True)
    params.setdefault("auto_build_index", True)

    plan = build_plan(
        project_name=project_name,
        project_id=project_id,
        records=records,
        target=target,
        params=params,
        capabilities=capabilities or detect_capabilities(),
    )
    if not plan.get("success"):
        return plan
    if plan.get("capability_gaps") and plan_requires_capabilities(plan):
        return {
            "success": False,
            "status": "missing_required_capabilities",
            "error": "Cannot create batch job because required local analysis tools are missing.",
            "plan": plan,
            "capability_gaps": plan.get("capability_gaps"),
            "install_guidance": plan.get("install_guidance"),
            "next_step": (
                "Install or configure the missing tools, then start the batch again. "
                "The MCP reports guidance only and does not install packages automatically."
            ),
        }

    project_root = plan["output_root"]["project_root"]
    os.makedirs(project_root, exist_ok=True)
    created_at = _utc_now()
    job_name = str(name or params.get("job_name") or params.get("jobName") or f"{target.get('type', 'analysis')} analysis")
    job_id = _job_id(job_name, target, f"{created_at}-{time.time_ns()}")
    conn = _connect_jobs(project_root)
    try:
        conn.execute(
            """
            INSERT INTO jobs (
                job_id, name, status, phase, project_name, project_id, project_root,
                target_json, params_json, plan_json, total_clips, pending_clips,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_name,
                "queued",
                "created",
                str(project_name or "Project"),
                str(project_id) if project_id is not None else None,
                project_root,
                _stable_json(target),
                _stable_json(params),
                _stable_json(plan),
                len(plan.get("clips") or []),
                len(plan.get("clips") or []),
                created_at,
                created_at,
            ),
        )
        for position, clip_plan in enumerate(plan.get("clips") or []):
            record = clip_plan.get("record") or {}
            conn.execute(
                """
                INSERT INTO job_clips (
                    job_id, position, clip_key, status, record_json, clip_plan_json,
                    cache_status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    position,
                    stable_clip_directory(record),
                    "pending",
                    _stable_json(record),
                    _stable_json(clip_plan),
                    clip_plan.get("cache_status"),
                    created_at,
                ),
            )
        _event(conn, job_id, "info", "Batch job created", {"clip_count": len(plan.get("clips") or [])})
        conn.commit()
        _write_job_sidecars(conn, project_root, job_id)
    finally:
        conn.close()

    return {
        "success": True,
        "job": batch_job_status(project_root, job_id),
        "plan": {
            "depth": plan.get("depth"),
            "clip_count": plan.get("clip_count"),
            "estimated_seconds_after_reuse": plan.get("estimated_seconds_after_reuse"),
            "analysis_keyframe_budget_per_clip": plan.get("analysis_keyframe_budget_per_clip"),
            "output_root": plan.get("output_root"),
            "reusable_clip_count": plan.get("reusable_clip_count"),
        },
    }


def create_batch_job_from_paths(
    *,
    project_name: Any,
    project_id: Any = None,
    paths: Iterable[Any],
    analysis_root: Any = None,
    recursive: bool = True,
    params: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    records, warnings = records_from_paths(paths, recursive=recursive)
    if not records:
        return {"success": False, "error": "No analyzable media files found", "warnings": warnings}
    params = dict(params or {})
    if analysis_root:
        params["analysis_root"] = analysis_root
    target = {
        "type": "paths",
        "paths": [record["file_path"] for record in records],
        "recursive": recursive,
    }
    result = create_batch_job(
        project_name=project_name,
        project_id=project_id,
        records=records,
        target=target,
        params=params,
        name=name,
    )
    if warnings:
        result.setdefault("warnings", warnings)
    return result


def list_batch_jobs(project_root: str, *, limit: Any = 50) -> Dict[str, Any]:
    root = normalize_path(project_root)
    db_path, err = job_db_path(root)
    if err:
        return {"success": False, "error": err}
    if not db_path or not os.path.isfile(db_path):
        return {"success": True, "project_root": root, "jobs": [], "count": 0}
    try:
        max_jobs = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        max_jobs = 50
    conn = _connect_jobs(root)
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max_jobs,),
        ).fetchall()
    finally:
        conn.close()
    jobs = [_job_summary_from_row(row) for row in rows]
    return {"success": True, "project_root": root, "jobs": jobs, "count": len(jobs)}


def batch_job_status(project_root: str, job_id: str, *, include_clips: bool = True, include_events: bool = True) -> Dict[str, Any]:
    root = normalize_path(project_root)
    conn = _connect_jobs(root)
    try:
        job = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not job:
            return {"success": False, "error": f"Batch job not found: {job_id}"}
        _sync_job_counts(conn, job_id)
        conn.commit()
        job = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        payload = _job_summary_from_row(job)
        payload["success"] = True
        payload["paths"] = _job_paths(root, job_id)
        if include_clips:
            payload["clips"] = [
                _row_dict(row)
                for row in conn.execute(
                    """
                    SELECT position, clip_key, status, report_path, marker_plan_path,
                           cache_status, error, attempts, started_at, completed_at
                    FROM job_clips
                    WHERE job_id = ?
                    ORDER BY position
                    """,
                    (job_id,),
                ).fetchall()
            ]
        if include_events:
            payload["events"] = [
                {
                    **{key: row[key] for key in ("event_time", "level", "message")},
                    "payload": _read_json(row["payload_json"]) if row["payload_json"] else None,
                }
                for row in conn.execute(
                    """
                    SELECT event_time, level, message, payload_json
                    FROM job_events
                    WHERE job_id = ?
                    ORDER BY id DESC
                    LIMIT 50
                    """,
                    (job_id,),
                ).fetchall()
            ]
    finally:
        conn.close()
    return payload


def _set_job_status(conn: sqlite3.Connection, job_id: str, status: str, phase: str, **extra: Any) -> None:
    fields = ["status = ?", "phase = ?", "updated_at = ?"]
    values: List[Any] = [status, phase, _utc_now()]
    for key, value in extra.items():
        fields.append(f"{key} = ?")
        values.append(value)
    values.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?", values)


def cancel_batch_job(project_root: str, job_id: str) -> Dict[str, Any]:
    root = normalize_path(project_root)
    conn = _connect_jobs(root)
    try:
        if not conn.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)).fetchone():
            return {"success": False, "error": f"Batch job not found: {job_id}"}
        conn.execute(
            "UPDATE job_clips SET status = 'pending', updated_at = ? WHERE job_id = ? AND status = 'running'",
            (_utc_now(), job_id),
        )
        _set_job_status(conn, job_id, "canceled", "canceled", canceled_at=_utc_now())
        _event(conn, job_id, "warning", "Batch job canceled")
        _sync_job_counts(conn, job_id)
        conn.commit()
        _write_job_sidecars(conn, root, job_id)
    finally:
        conn.close()
    return batch_job_status(root, job_id)


def resume_batch_job(project_root: str, job_id: str) -> Dict[str, Any]:
    root = normalize_path(project_root)
    conn = _connect_jobs(root)
    try:
        if not conn.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)).fetchone():
            return {"success": False, "error": f"Batch job not found: {job_id}"}
        conn.execute(
            "UPDATE job_clips SET status = 'pending', updated_at = ? WHERE job_id = ? AND status = 'running'",
            (_utc_now(), job_id),
        )
        _set_job_status(conn, job_id, "queued", "resumed", canceled_at=None)
        _event(conn, job_id, "info", "Batch job resumed")
        _sync_job_counts(conn, job_id)
        conn.commit()
        _write_job_sidecars(conn, root, job_id)
    finally:
        conn.close()
    return batch_job_status(root, job_id)


def _auto_build_index(conn: sqlite3.Connection, root: str, job_id: str, message: str) -> Dict[str, Any]:
    index = build_analysis_index(root)
    _event(conn, job_id, "info" if index.get("success") else "error", message, index)
    conn.commit()
    return index


def _finish_job_if_complete(
    conn: sqlite3.Connection,
    root: str,
    job_id: str,
    params: Dict[str, Any],
    *,
    index_already_refreshed: bool = False,
) -> None:
    counts = _sync_job_counts(conn, job_id)
    if counts["pending_clips"] or counts["running_clips"]:
        return
    status = "completed_with_errors" if counts["failed_clips"] else "completed"
    _set_job_status(conn, job_id, status, "complete", completed_at=_utc_now())
    _event(conn, job_id, "info", "Batch job completed", counts)
    conn.commit()
    summarize_reports(root)
    if params.get("auto_build_index", True) and not index_already_refreshed:
        _auto_build_index(conn, root, job_id, "Analysis index rebuilt")


def run_batch_job_slice(
    project_root: str,
    job_id: str,
    *,
    max_clips: Any = 1,
    max_seconds: Optional[Any] = None,
    capabilities: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    root = normalize_path(project_root)
    try:
        clip_limit = max(1, min(int(max_clips), 25))
    except (TypeError, ValueError):
        clip_limit = 1
    deadline = None
    if max_seconds not in (None, ""):
        try:
            deadline = time.monotonic() + max(1.0, float(max_seconds))
        except (TypeError, ValueError):
            deadline = None

    conn = _connect_jobs(root)
    processed: List[Dict[str, Any]] = []
    try:
        job = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not job:
            return {"success": False, "error": f"Batch job not found: {job_id}"}
        if job["status"] == "canceled":
            return {"success": False, "error": f"Batch job is canceled: {job_id}", "job": batch_job_status(root, job_id)}
        params = _read_json(job["params_json"])
        plan = _read_json(job["plan_json"])
        now = _utc_now()
        if job["started_at"] is None:
            conn.execute("UPDATE jobs SET started_at = ? WHERE job_id = ?", (now, job_id))
        _set_job_status(conn, job_id, "running", "analyzing")
        _event(conn, job_id, "info", "Running batch job slice", {"max_clips": clip_limit, "max_seconds": max_seconds})
        conn.commit()

        rows = conn.execute(
            """
            SELECT *
            FROM job_clips
            WHERE job_id = ? AND status = 'pending'
            ORDER BY position
            LIMIT ?
            """,
            (job_id, clip_limit),
        ).fetchall()

        for row in rows:
            if deadline is not None and time.monotonic() >= deadline:
                break
            clip_plan = _read_json(row["clip_plan_json"])
            mini_plan = copy.deepcopy(plan)
            mini_plan["clips"] = [clip_plan]
            mini_plan["clip_count"] = 1
            mini_plan["dry_run"] = False
            started_at = _utc_now()
            conn.execute(
                """
                UPDATE job_clips
                SET status = 'running', attempts = attempts + 1, started_at = ?,
                    updated_at = ?, error = NULL
                WHERE id = ?
                """,
                (started_at, started_at, row["id"]),
            )
            _sync_job_counts(conn, job_id)
            conn.commit()
            try:
                slice_params = copy.deepcopy(params)
                slice_params["auto_build_index"] = False
                # C6 caps integration: thread the job_id so per-job usage
                # rollups populate (otherwise JOB scope stays at zero).
                slice_params["job_id"] = job_id
                manifest = execute_plan(mini_plan, params=slice_params, capabilities=capabilities or detect_capabilities())
                clip_result = (manifest.get("clips") or [{}])[0] if isinstance(manifest, dict) else {}
                completed_at = _utc_now()
                if manifest.get("success") and clip_result.get("success"):
                    status = "skipped" if clip_result.get("reused") else "succeeded"
                    conn.execute(
                        """
                        UPDATE job_clips
                        SET status = ?, report_path = ?, marker_plan_path = ?,
                            cache_status = ?, completed_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            status,
                            clip_result.get("analysis_json"),
                            clip_result.get("marker_plan_json"),
                            clip_result.get("cache_status"),
                            completed_at,
                            completed_at,
                            row["id"],
                        ),
                    )
                    processed.append({"position": row["position"], "status": status, "report_path": clip_result.get("analysis_json")})
                    _event(conn, job_id, "info", f"Clip {row['position'] + 1} {status}", {"clip": clip_result.get("record")})
                else:
                    error = clip_result.get("error") or manifest.get("error") or "Clip analysis failed"
                    conn.execute(
                        """
                        UPDATE job_clips
                        SET status = 'failed', error = ?, completed_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (error, completed_at, completed_at, row["id"]),
                    )
                    processed.append({"position": row["position"], "status": "failed", "error": error})
                    _event(conn, job_id, "error", f"Clip {row['position'] + 1} failed", {"error": error})
            except Exception as exc:  # pragma: no cover - defensive for arbitrary media/tool failures
                completed_at = _utc_now()
                conn.execute(
                    """
                    UPDATE job_clips
                    SET status = 'failed', error = ?, completed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (str(exc), completed_at, completed_at, row["id"]),
                )
                processed.append({"position": row["position"], "status": "failed", "error": str(exc)})
                _event(conn, job_id, "error", f"Clip {row['position'] + 1} raised an exception", {"error": str(exc)})
            _sync_job_counts(conn, job_id)
            conn.commit()

        index_refreshed = False
        if params.get("auto_build_index", True) and any(
            row.get("status") in {"succeeded", "skipped"} for row in processed
        ):
            _auto_build_index(conn, root, job_id, "Analysis index refreshed after batch slice")
            index_refreshed = True

        _finish_job_if_complete(conn, root, job_id, params, index_already_refreshed=index_refreshed)
        _sync_job_counts(conn, job_id)
        conn.commit()
        current = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if current and current["status"] == "running":
            _set_job_status(conn, job_id, "queued", "waiting_for_next_slice")
            conn.commit()
        _write_job_sidecars(conn, root, job_id)
    finally:
        conn.close()

    return {
        "success": True,
        "processed_count": len(processed),
        "processed": processed,
        "job": batch_job_status(root, job_id),
    }


def project_root_for_dashboard(project_name: Any, project_id: Any = None, analysis_root: Any = None, source_paths: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    return resolve_output_root(
        project_name=project_name,
        project_id=project_id,
        analysis_root=analysis_root,
        source_paths=source_paths or [],
        create=True,
    )
