"""DB-canonical clip-analysis store (C1 / Phase A of the analysis program).

The per-project SQLite DB (timeline_brain.sqlite, schema v9+) is the source of
truth for clip analysis. analysis.json on disk is a derived export written in
lockstep after every ingest. Shape is hybrid:

- ``analysis_reports.report_json`` — the canonical full payload per clip.
- Normalized tables for what downstream phases query: ``clips`` (identity +
  headline columns), ``clip_aliases`` (any stable id → clip_uuid), ``shots``,
  ``subjective_fields``/``field_changelog`` (per-field provenance),
  ``transcript_segments``, ``frames``, ``qc_observations``.

Export contract: export = report blob + current *human* subjective fields
overlaid. Machine values are already inside the blob because the blob is
rewritten on every ingest; human rows always win and survive re-analysis.

Reader contract: readers go DB-first and fall back to analysis.json when the
clip has no rows (reports written before v9, or job-linked report dirs that
live under another project root).

This module must not import media_analysis at module level (media_analysis
calls into here from the analysis write path) — helpers are imported lazily.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from src.utils import timeline_brain_db

logger = logging.getLogger("resolve-mcp.analysis-store")

# Source label for machine-derived subjective rows written at ingest time.
MACHINE_SOURCE = "vision_v0.2"
HUMAN_SOURCE = "human"

# Clip-level subjective groups inside report["visual"] that get flattened into
# subjective_fields rows. Structural/computed visual keys stay blob-only.
_SUBJECTIVE_CLIP_GROUPS = (
    "clip_summary",
    "clip_summary_oneliner",
    "editorial_classification",
    "content",
    "shot_and_style",
    "slate",
    "editing_notes",
)

# Shot keys that are structural (identity/geometry), not subjective fields.
_SHOT_STRUCTURAL_KEYS = {
    "shot_index",
    "shot_uuid",
    "time_seconds_start",
    "time_seconds_end",
    "frame_indices_used",
    "frame_indices",
    "qc_flags",
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _ma():
    """Lazy import of media_analysis helpers (avoids a circular import)."""
    from src.utils import media_analysis

    return media_analysis


def shot_uuid_for(clip_uuid: str, start: Any, end: Any) -> str:
    """Stable shot id: clip + time region rounded to the nearest second.

    Survives small boundary jitter on re-analysis so corrections and timeline
    references keep pointing at the same shot.
    """
    try:
        start_r = int(round(float(start)))
    except (TypeError, ValueError):
        start_r = -1
    try:
        end_r = int(round(float(end)))
    except (TypeError, ValueError):
        end_r = -1
    return _ma().short_hash(f"shot:{clip_uuid}:{start_r}:{end_r}", 12)


def _flatten_fields(value: Any, prefix: str, out: Dict[str, Any]) -> None:
    """Flatten nested dicts to dot-path leaves; lists/scalars are leaves."""
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_fields(child, child_prefix, out)
    else:
        if prefix:
            out[prefix] = value


def clip_subjective_fields(visual: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten the clip-level subjective groups of a visual block."""
    out: Dict[str, Any] = {}
    if not isinstance(visual, dict):
        return out
    for group in _SUBJECTIVE_CLIP_GROUPS:
        if group in visual:
            _flatten_fields(visual.get(group), group, out)
    return out


def shot_subjective_fields(shot_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a shot entry's subjective fields (everything non-structural)."""
    out: Dict[str, Any] = {}
    if not isinstance(shot_entry, dict):
        return out
    for key, value in shot_entry.items():
        if key in _SHOT_STRUCTURAL_KEYS:
            continue
        _flatten_fields(value, str(key), out)
    return out


# ── identity ──────────────────────────────────────────────────────────────────


def clip_identity(report: Dict[str, Any], *, clip_dir: Optional[str] = None) -> Tuple[str, List[Tuple[str, str]]]:
    """Return (clip_uuid, [(alias, kind), ...]) for a report.

    clip_uuid is the canonical rename-stable hash (normalized file_path basis);
    aliases cover legacy hashes, clip_id, media_id, raw/normalized file path,
    and the report folder's name + embedded hash.
    """
    ma = _ma()
    record = report.get("clip") if isinstance(report.get("clip"), dict) else {}
    hashes = ma.stable_clip_match_hashes(record)
    aliases: List[Tuple[str, str]] = []
    folder_hash = None
    folder_name = os.path.basename(str(clip_dir).rstrip("/\\")) if clip_dir else None
    if folder_name:
        folder_hash = ma.clip_directory_hash(folder_name)
    clip_uuid = hashes[0] if hashes else (folder_hash or ma.short_hash(folder_name or "clip", 12))
    for h in hashes:
        aliases.append((h, "hash"))
    if folder_hash:
        aliases.append((folder_hash, "hash"))
    if folder_name:
        aliases.append((folder_name, "clip_dir"))
    for key, kind in (("clip_id", "clip_id"), ("media_id", "media_id")):
        value = record.get(key)
        if value:
            aliases.append((str(value), kind))
    file_path = record.get("file_path")
    if file_path:
        aliases.append((ma.normalize_path(file_path), "file_path"))
        aliases.append((str(file_path), "file_path"))
    deduped: List[Tuple[str, str]] = []
    seen = set()
    for alias, kind in aliases:
        if alias and alias not in seen:
            seen.add(alias)
            deduped.append((alias, kind))
    return clip_uuid, deduped


def resolve_clip_uuid(conn: sqlite3.Connection, ref: Any) -> Optional[str]:
    """Resolve any clip reference (uuid, hash, clip_id, path, folder) to clip_uuid."""
    if not ref:
        return None
    candidate = str(ref)
    row = conn.execute("SELECT clip_uuid FROM clips WHERE clip_uuid = ?", (candidate,)).fetchone()
    if row:
        return str(row["clip_uuid"])
    row = conn.execute("SELECT clip_uuid FROM clip_aliases WHERE alias = ?", (candidate,)).fetchone()
    if row:
        return str(row["clip_uuid"])
    # Folder names carry the hash as a suffix; absolute paths reduce to basename.
    base = os.path.basename(candidate.rstrip("/\\"))
    if base != candidate:
        for probe in (base, _ma().clip_directory_hash(base) or ""):
            if not probe:
                continue
            row = conn.execute("SELECT clip_uuid FROM clip_aliases WHERE alias = ?", (probe,)).fetchone()
            if row:
                return str(row["clip_uuid"])
    else:
        probe = _ma().clip_directory_hash(base)
        if probe:
            row = conn.execute("SELECT clip_uuid FROM clip_aliases WHERE alias = ?", (probe,)).fetchone()
            if row:
                return str(row["clip_uuid"])
    return None


# ── ingest ────────────────────────────────────────────────────────────────────


def _duration_seconds(report: Dict[str, Any]) -> Optional[float]:
    for path in (
        ("clip_analysis_markers", "duration_seconds"),
        ("cut_analysis", "duration_seconds"),
    ):
        node: Any = report
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, (int, float)):
            return float(node)
    technical = report.get("technical") if isinstance(report.get("technical"), dict) else {}
    fmt = technical.get("format") if isinstance(technical.get("format"), dict) else {}
    if isinstance(fmt.get("duration_seconds"), (int, float)):
        return float(fmt["duration_seconds"])
    return None


def _current_subjective(conn: sqlite3.Connection, entity_type: str, entity_uuid: str) -> Dict[str, sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT * FROM subjective_fields
        WHERE entity_type = ? AND entity_uuid = ? AND superseded_at IS NULL
        """,
        (entity_type, entity_uuid),
    ).fetchall()
    return {str(r["field_path"]): r for r in rows}


def _write_subjective(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_uuid: str,
    fields: Dict[str, Any],
    *,
    source: str,
    author: str,
    confidence: Optional[str] = None,
    reason: Optional[str] = None,
    overwrite_human: bool = False,
) -> Dict[str, int]:
    """Upsert current values for an entity. Machine writes never replace a
    current human row unless overwrite_human is set (explicit revert path)."""
    now = _now()
    current = _current_subjective(conn, entity_type, entity_uuid)
    written = 0
    skipped_human = 0
    for field_path, value in fields.items():
        value_json = _dumps(value)
        existing = current.get(field_path)
        if existing is not None:
            # Identical value → keep the existing row and its provenance. A
            # different source re-deriving the same value must not re-attribute
            # it (a deep pass would otherwise claim every unchanged field).
            if str(existing["value_json"]) == value_json:
                continue
            if (
                str(existing["source"]) == HUMAN_SOURCE
                and source != HUMAN_SOURCE
                and not overwrite_human
            ):
                skipped_human += 1
                continue
            conn.execute(
                "UPDATE subjective_fields SET superseded_at = ? WHERE id = ?",
                (now, existing["id"]),
            )
        conn.execute(
            """
            INSERT INTO subjective_fields
                (entity_type, entity_uuid, field_path, value_json, confidence,
                 source, author, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entity_type, entity_uuid, field_path, value_json, confidence, source, author, now),
        )
        conn.execute(
            """
            INSERT INTO field_changelog
                (entity_type, entity_uuid, field_path, previous_value_json,
                 new_value_json, previous_source, new_source, previous_author,
                 new_author, change_reason, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_type,
                entity_uuid,
                field_path,
                existing["value_json"] if existing is not None else None,
                value_json,
                existing["source"] if existing is not None else None,
                source,
                existing["author"] if existing is not None else None,
                author,
                reason,
                now,
            ),
        )
        written += 1
    return {"written": written, "skipped_human": skipped_human}


def ingest_report(
    project_root: str,
    report: Dict[str, Any],
    *,
    clip_dir: Optional[str] = None,
    author: str = "system",
    source: str = MACHINE_SOURCE,
) -> Dict[str, Any]:
    """Write one analysis report into the DB (rows + canonical blob).

    Idempotent: re-ingesting the same report leaves identical state. Human
    subjective rows are never replaced by machine values.
    """
    if not isinstance(report, dict):
        return {"success": False, "error": "report must be a dict"}
    clip_uuid, aliases = clip_identity(report, clip_dir=clip_dir)
    record = report.get("clip") if isinstance(report.get("clip"), dict) else {}
    visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
    shot_entries = visual.get("shot_descriptions") if isinstance(visual.get("shot_descriptions"), list) else []
    motion = report.get("motion") if isinstance(report.get("motion"), dict) else {}
    cut_analysis = report.get("cut_analysis") if isinstance(report.get("cut_analysis"), dict) else {}
    transcription = report.get("transcription") if isinstance(report.get("transcription"), dict) else {}
    signature = report.get("analysis_signature") if isinstance(report.get("analysis_signature"), dict) else {}
    profile = report.get("analysis_profile") if isinstance(report.get("analysis_profile"), dict) else {}
    now = _now()

    with timeline_brain_db.transaction(project_root) as conn:
        existing = conn.execute(
            "SELECT created_at FROM clips WHERE clip_uuid = ?", (clip_uuid,)
        ).fetchone()
        created_at = str(existing["created_at"]) if existing else now
        conn.execute(
            """
            INSERT OR REPLACE INTO clips
                (clip_uuid, clip_dir, resolve_clip_id, media_id, clip_name,
                 file_path, bin_path, duration_seconds, fps, resolution,
                 media_type, summary, overall_motion_level, cut_count,
                 shot_count, analysis_version, depth, signature_hash,
                 analyzed_at, vision_status, vision_committed_at,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_uuid,
                os.path.basename(str(clip_dir).rstrip("/\\")) if clip_dir else None,
                record.get("clip_id"),
                record.get("media_id"),
                record.get("clip_name"),
                record.get("file_path"),
                record.get("bin_path"),
                _duration_seconds(report),
                record.get("fps") if isinstance(record.get("fps"), (int, float)) else None,
                record.get("resolution"),
                record.get("media_type"),
                report.get("summary"),
                motion.get("overall_motion_level"),
                cut_analysis.get("cut_count") if isinstance(cut_analysis.get("cut_count"), int) else None,
                len(shot_entries),
                report.get("analysis_version"),
                profile.get("depth"),
                signature.get("signature_hash"),
                report.get("analyzed_at"),
                report.get("vision_status"),
                report.get("vision_committed_at"),
                created_at,
                now,
            ),
        )
        for alias, kind in aliases:
            conn.execute(
                "INSERT OR IGNORE INTO clip_aliases (alias, clip_uuid, kind) VALUES (?, ?, ?)",
                (alias, clip_uuid, kind),
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO analysis_reports
                (clip_uuid, report_json, signature_hash, analyzed_at, written_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (clip_uuid, _dumps(report), signature.get("signature_hash"), report.get("analyzed_at"), now),
        )

        # Shots: rebuild rows, preserving created_at for stable shot_uuids.
        prior_shots = {
            str(r["shot_uuid"]): r
            for r in conn.execute("SELECT * FROM shots WHERE clip_uuid = ?", (clip_uuid,)).fetchall()
        }
        conn.execute("DELETE FROM shots WHERE clip_uuid = ?", (clip_uuid,))
        frame_to_shot: Dict[int, str] = {}
        subj_written = 0
        subj_skipped_human = 0
        for entry in shot_entries:
            if not isinstance(entry, dict):
                continue
            start = entry.get("time_seconds_start")
            end = entry.get("time_seconds_end")
            s_uuid = shot_uuid_for(clip_uuid, start, end)
            prior = prior_shots.get(s_uuid)
            frame_indices = entry.get("frame_indices_used") or entry.get("frame_indices") or []
            if not isinstance(frame_indices, list):
                frame_indices = []
            extra = {
                k: v
                for k, v in entry.items()
                if k not in _SHOT_STRUCTURAL_KEYS and k != "description"
            }
            conn.execute(
                """
                INSERT OR REPLACE INTO shots
                    (shot_uuid, clip_uuid, shot_index, time_seconds_start,
                     time_seconds_end, description, qc_flags_json,
                     frame_indices_json, extra_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    s_uuid,
                    clip_uuid,
                    int(entry.get("shot_index") or 0),
                    start if isinstance(start, (int, float)) else None,
                    end if isinstance(end, (int, float)) else None,
                    entry.get("description"),
                    _dumps(entry.get("qc_flags") or []),
                    _dumps(frame_indices),
                    _dumps(extra) if extra else None,
                    str(prior["created_at"]) if prior else now,
                    now,
                ),
            )
            for raw in frame_indices:
                try:
                    frame_to_shot[int(raw)] = s_uuid
                except (TypeError, ValueError):
                    continue
            stats = _write_subjective(
                conn, "shot", s_uuid, shot_subjective_fields(entry),
                source=source, author=author,
            )
            subj_written += stats["written"]
            subj_skipped_human += stats["skipped_human"]

        stats = _write_subjective(
            conn, "clip", clip_uuid, clip_subjective_fields(visual),
            source=source, author=author,
        )
        subj_written += stats["written"]
        subj_skipped_human += stats["skipped_human"]

        # Transcript segments.
        conn.execute("DELETE FROM transcript_segments WHERE clip_uuid = ?", (clip_uuid,))
        segments = transcription.get("segments") if isinstance(transcription.get("segments"), list) else []
        for idx, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO transcript_segments
                    (clip_uuid, segment_index, start_seconds, end_seconds, text, speaker_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    clip_uuid,
                    idx,
                    seg.get("start") if isinstance(seg.get("start"), (int, float)) else None,
                    seg.get("end") if isinstance(seg.get("end"), (int, float)) else None,
                    seg.get("text"),
                    seg.get("speaker") or seg.get("speaker_id"),
                ),
            )

        # Sampled frames. Shot mapping uses frame_indices_used when present,
        # with a time-containment fallback (some commit paths don't record
        # which frame indices fed which shot).
        shot_intervals: List[Tuple[float, float, str]] = []
        for entry in shot_entries:
            if not isinstance(entry, dict):
                continue
            s, e = entry.get("time_seconds_start"), entry.get("time_seconds_end")
            if isinstance(s, (int, float)) and isinstance(e, (int, float)):
                shot_intervals.append((float(s), float(e), shot_uuid_for(clip_uuid, s, e)))

        def _shot_for_time(t: Any) -> Optional[str]:
            if not isinstance(t, (int, float)):
                return None
            for s, e, uuid_ in shot_intervals:
                if s <= float(t) < e:
                    return uuid_
            return None

        conn.execute("DELETE FROM frames WHERE clip_uuid = ?", (clip_uuid,))
        keyframes = motion.get("analysis_keyframes") if isinstance(motion.get("analysis_keyframes"), list) else []
        for kf in keyframes:
            if not isinstance(kf, dict):
                continue
            try:
                frame_index = int(kf.get("index"))
            except (TypeError, ValueError):
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO frames
                    (clip_uuid, shot_uuid, frame_index, time_seconds, frame_path,
                     selection_reason, motion_peak)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clip_uuid,
                    frame_to_shot.get(frame_index) or _shot_for_time(kf.get("time_seconds")),
                    frame_index,
                    kf.get("time_seconds") if isinstance(kf.get("time_seconds"), (int, float)) else None,
                    kf.get("frame_path") or kf.get("path"),
                    kf.get("selection_reason"),
                    1 if kf.get("motion_peak") else 0,
                ),
            )

        # QC observations: machine rows rebuild; human-resolved rows persist.
        conn.execute(
            "DELETE FROM qc_observations WHERE clip_uuid = ? AND resolved = 0 AND source = ?",
            (clip_uuid, source),
        )
        resolved_keys = {
            (str(r["observation_type"]), str(r["message"]))
            for r in conn.execute(
                "SELECT observation_type, message FROM qc_observations WHERE clip_uuid = ? AND resolved = 1",
                (clip_uuid,),
            ).fetchall()
        }
        qc = visual.get("qc") if isinstance(visual.get("qc"), dict) else {}

        def _insert_qc(obs_type: str, severity: str, message: Any, related: Any = None, confidence: Any = None) -> None:
            msg = str(message or "").strip()
            if not msg or (obs_type, msg) in resolved_keys:
                return
            conn.execute(
                """
                INSERT INTO qc_observations
                    (clip_uuid, observation_type, severity, message,
                     related_shot_indices_json, confidence, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clip_uuid,
                    obs_type,
                    severity,
                    msg,
                    _dumps(related) if related else None,
                    str(confidence) if confidence else None,
                    source,
                    now,
                ),
            )

        for warning in qc.get("warnings") or []:
            _insert_qc("warning", "warn", warning)
        for obs in qc.get("continuity_observations") or []:
            if isinstance(obs, dict):
                _insert_qc(
                    str(obs.get("kind") or "continuity"),
                    "info",
                    obs.get("observation"),
                    related=obs.get("shot_indices"),
                    confidence=obs.get("confidence"),
                )
        for gap in qc.get("coverage_gaps") or []:
            _insert_qc("coverage_gap", "info", gap)

    return {
        "success": True,
        "clip_uuid": clip_uuid,
        "shot_count": len(shot_entries),
        "subjective_fields_written": subj_written,
        "subjective_fields_preserved_human": subj_skipped_human,
    }


# ── export / readers ─────────────────────────────────────────────────────────


def _overlay_human_fields(conn: sqlite3.Connection, clip_uuid: str, report: Dict[str, Any]) -> int:
    """Apply current human subjective rows onto a report dict. Returns count."""
    ma = _ma()
    visual = report.get("visual")
    if not isinstance(visual, dict):
        return 0
    shots_by_uuid: Dict[str, int] = {}
    for row in conn.execute(
        "SELECT shot_uuid, shot_index FROM shots WHERE clip_uuid = ?", (clip_uuid,)
    ).fetchall():
        shots_by_uuid[str(row["shot_uuid"])] = int(row["shot_index"])
    shot_entries = visual.get("shot_descriptions") if isinstance(visual.get("shot_descriptions"), list) else []
    applied = 0

    rows = conn.execute(
        """
        SELECT entity_type, entity_uuid, field_path, value_json
        FROM subjective_fields
        WHERE superseded_at IS NULL AND source = ?
          AND (
                (entity_type = 'clip' AND entity_uuid = ?)
             OR (entity_type = 'shot' AND entity_uuid IN
                    (SELECT shot_uuid FROM shots WHERE clip_uuid = ?))
          )
        """,
        (HUMAN_SOURCE, clip_uuid, clip_uuid),
    ).fetchall()
    for row in rows:
        try:
            value = json.loads(row["value_json"])
        except (TypeError, ValueError):
            continue
        path_parts = [p for p in str(row["field_path"]).split(".") if p]
        if not path_parts:
            continue
        if str(row["entity_type"]) == "clip":
            target: Any = visual
        else:
            shot_index = shots_by_uuid.get(str(row["entity_uuid"]))
            target = None
            if shot_index is not None:
                target = ma._find_shot_entry(shot_entries, str(shot_index))
            if target is None:
                target = ma._find_shot_entry(shot_entries, str(row["entity_uuid"]))
            if target is None:
                continue
        if ma._walk_set(target, path_parts, value):
            applied += 1
    return applied


def export_report(project_root: str, clip_ref: Any) -> Optional[Dict[str, Any]]:
    """Return the canonical report (blob + human overlay) or None if absent."""
    try:
        conn = timeline_brain_db.connect(project_root)
        clip_uuid = resolve_clip_uuid(conn, clip_ref)
        if not clip_uuid:
            return None
        row = conn.execute(
            "SELECT report_json FROM analysis_reports WHERE clip_uuid = ?", (clip_uuid,)
        ).fetchone()
        if not row:
            return None
        report = json.loads(row["report_json"])
        if not isinstance(report, dict):
            return None
        _overlay_human_fields(conn, clip_uuid, report)
        return report
    except (sqlite3.Error, ValueError, OSError) as exc:
        logger.debug("export_report fell back to JSON for %r: %s", clip_ref, exc)
        return None


def load_db_report(
    project_root: str,
    *,
    clip_dir: Optional[str] = None,
    clip_id: Optional[str] = None,
    clip_uuid: Optional[str] = None,
    file_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """DB-first reader used by panel/MCP readers. None means: fall back to JSON."""
    for ref in (clip_uuid, clip_id, clip_dir, file_path):
        if not ref:
            continue
        report = export_report(project_root, ref)
        if report is not None:
            return report
    return None


def export_report_file(project_root: str, clip_ref: Any, path: str) -> Optional[str]:
    """Write the derived analysis.json export for a clip. Returns the path."""
    report = export_report(project_root, clip_ref)
    if report is None:
        return None
    _ma()._write_json(path, report)
    return path


def list_clip_rows(project_root: str) -> List[Dict[str, Any]]:
    """Headline clip rows for list endpoints (no blobs)."""
    conn = timeline_brain_db.connect(project_root)
    rows = conn.execute("SELECT * FROM clips ORDER BY clip_name COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def db_status(project_root: str) -> Dict[str, Any]:
    """Counts + schema version for the analysis store of a project."""
    try:
        conn = timeline_brain_db.connect(project_root)
        version = timeline_brain_db._read_schema_version(conn)
        counts = {}
        for table in (
            "clips",
            "analysis_reports",
            "shots",
            "subjective_fields",
            "transcript_segments",
            "frames",
            "qc_observations",
        ):
            counts[table] = int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
        human = conn.execute(
            "SELECT COUNT(*) AS n FROM subjective_fields WHERE source = ? AND superseded_at IS NULL",
            (HUMAN_SOURCE,),
        ).fetchone()
        return {
            "success": True,
            "project_root": project_root,
            "db_path": timeline_brain_db.db_path_for_project(project_root),
            "schema_version": version,
            "canonical": version >= 9,
            "counts": counts,
            "current_human_fields": int(human["n"]),
        }
    except (sqlite3.Error, OSError) as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


# ── corrections (row level) ──────────────────────────────────────────────────


def record_human_correction(
    project_root: str,
    *,
    clip_ref: Any,
    entity_type: str,
    entity_uuid: Any,
    field_path: str,
    value: Any,
    author: str = "unknown",
    reason: Optional[str] = None,
    confidence: Optional[str] = None,
) -> Dict[str, Any]:
    """Row-level human correction: supersede current value, append changelog.

    `entity_uuid` accepts a shot_uuid OR a shot_index (resolved against the
    clip's shots), matching the sidecar contract.
    """
    with timeline_brain_db.transaction(project_root) as conn:
        clip_uuid = resolve_clip_uuid(conn, clip_ref)
        if not clip_uuid:
            return {"success": False, "error": f"clip not found in DB: {clip_ref}"}
        target_uuid = clip_uuid
        if entity_type == "shot":
            candidate = str(entity_uuid)
            row = conn.execute(
                "SELECT shot_uuid FROM shots WHERE clip_uuid = ? AND shot_uuid = ?",
                (clip_uuid, candidate),
            ).fetchone()
            if row is None:
                try:
                    row = conn.execute(
                        "SELECT shot_uuid FROM shots WHERE clip_uuid = ? AND shot_index = ?",
                        (clip_uuid, int(candidate)),
                    ).fetchone()
                except (TypeError, ValueError):
                    row = None
            if row is None:
                return {"success": False, "error": f"shot not found in DB: {entity_uuid}"}
            target_uuid = str(row["shot_uuid"])
        stats = _write_subjective(
            conn,
            entity_type,
            target_uuid,
            {field_path: value},
            source=HUMAN_SOURCE,
            author=author,
            confidence=confidence,
            reason=reason,
            overwrite_human=True,
        )
    return {
        "success": True,
        "clip_uuid": clip_uuid,
        "entity_type": entity_type,
        "entity_uuid": target_uuid,
        "field_path": field_path,
        "written": stats["written"],
    }


def clear_human_field(
    project_root: str,
    *,
    clip_ref: Any,
    entity_type: str,
    entity_uuid: Any,
    field_path: str,
    author: str = "unknown",
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Revert a field to machine-derived: supersede the current human row.

    The machine value lives in the report blob, so superseding the human row
    is all the export overlay needs to fall back to it.
    """
    now = _now()
    with timeline_brain_db.transaction(project_root) as conn:
        clip_uuid = resolve_clip_uuid(conn, clip_ref)
        if not clip_uuid:
            return {"success": False, "error": f"clip not found in DB: {clip_ref}"}
        target_uuid = clip_uuid
        if entity_type == "shot":
            candidate = str(entity_uuid)
            row = conn.execute(
                "SELECT shot_uuid FROM shots WHERE clip_uuid = ? AND shot_uuid = ?",
                (clip_uuid, candidate),
            ).fetchone()
            if row is None:
                try:
                    row = conn.execute(
                        "SELECT shot_uuid FROM shots WHERE clip_uuid = ? AND shot_index = ?",
                        (clip_uuid, int(candidate)),
                    ).fetchone()
                except (TypeError, ValueError):
                    row = None
            if row is None:
                return {"success": False, "error": f"shot not found in DB: {entity_uuid}"}
            target_uuid = str(row["shot_uuid"])
        existing = conn.execute(
            """
            SELECT * FROM subjective_fields
            WHERE entity_type = ? AND entity_uuid = ? AND field_path = ?
              AND superseded_at IS NULL AND source = ?
            """,
            (entity_type, target_uuid, field_path, HUMAN_SOURCE),
        ).fetchone()
        if existing is None:
            return {"success": True, "cleared": 0, "note": "no current human row"}
        conn.execute(
            "UPDATE subjective_fields SET superseded_at = ? WHERE id = ?",
            (now, existing["id"]),
        )
        conn.execute(
            """
            INSERT INTO field_changelog
                (entity_type, entity_uuid, field_path, previous_value_json,
                 new_value_json, previous_source, new_source, previous_author,
                 new_author, change_reason, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_type,
                target_uuid,
                field_path,
                existing["value_json"],
                _dumps(None),
                existing["source"],
                "machine_revert",
                existing["author"],
                author,
                reason or "reverted to machine-derived",
                now,
            ),
        )
    return {"success": True, "cleared": 1, "clip_uuid": clip_uuid, "entity_uuid": target_uuid}


def _ingest_corrections_sidecar(project_root: str, clip_dir_path: str, clip_uuid: str) -> int:
    """Import human rows from a corrections.json sidecar (db_ingest path)."""
    path = os.path.join(clip_dir_path, "corrections.json")
    if not os.path.isfile(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return 0
    current = data.get("current") if isinstance(data.get("current"), dict) else {}
    imported = 0
    for key, entry in current.items():
        if not isinstance(entry, dict) or entry.get("source") != HUMAN_SOURCE:
            continue
        parts = str(key).split(":", 2)
        if len(parts) != 3:
            continue
        entity_type, entity_uuid, field_path = parts
        if entity_type not in ("clip", "shot"):
            continue
        result = record_human_correction(
            project_root,
            clip_ref=clip_uuid,
            entity_type=entity_type,
            entity_uuid=clip_uuid if entity_type == "clip" else entity_uuid,
            field_path=field_path,
            value=entry.get("value"),
            author=str(entry.get("author") or "unknown"),
            reason="imported from corrections.json",
            confidence=entry.get("confidence"),
        )
        if result.get("success") and result.get("written"):
            imported += 1
    return imported


def ingest_project(project_root: str) -> Dict[str, Any]:
    """Walk clips/ and ingest every analysis.json + corrections.json sidecar.

    The migration entry point for projects analyzed before v9. Idempotent.
    """
    ma = _ma()
    root = ma.normalize_path(project_root)
    clips_root = os.path.join(root, "clips")
    ingested: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    corrections_imported = 0
    if os.path.isdir(clips_root):
        for entry in sorted(os.listdir(clips_root)):
            clip_dir_path = os.path.join(clips_root, entry)
            report_path = os.path.join(clip_dir_path, "analysis.json")
            if not os.path.isfile(report_path):
                continue
            try:
                with open(report_path, "r", encoding="utf-8") as handle:
                    report = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append({"clip_dir": entry, "error": f"{type(exc).__name__}: {exc}"})
                continue
            try:
                result = ingest_report(root, report, clip_dir=clip_dir_path)
            except (sqlite3.Error, ValueError) as exc:
                errors.append({"clip_dir": entry, "error": f"{type(exc).__name__}: {exc}"})
                continue
            if result.get("success"):
                corrections_imported += _ingest_corrections_sidecar(
                    root, clip_dir_path, str(result["clip_uuid"])
                )
                ingested.append({"clip_dir": entry, "clip_uuid": result["clip_uuid"]})
            else:
                errors.append({"clip_dir": entry, "error": result.get("error")})
    return {
        "success": not errors,
        "project_root": root,
        "ingested_count": len(ingested),
        "ingested": ingested,
        "corrections_imported": corrections_imported,
        "errors": errors,
        "status": db_status(root),
    }
