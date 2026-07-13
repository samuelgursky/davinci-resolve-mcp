"""Perception strata — store + query layer for the timecoded track model.

The strata are per-clip, timecoded annotation tracks in the per-project
timeline-brain DB (schema v13+): ``events`` (point/span occurrences),
``curves`` (sampled float32 series), ``transcript_words`` (word-level
timestamps promoted out of the report blob), and ``story_beats`` (units of
meaning with supersede semantics).

Design rules (mirrors analysis_store):
- All times are clip-relative seconds. Timeline/record-time projection is a
  query-layer concern (via timeline_clip_usage), never an analyzer concern.
- Analyzers are *track writers*: a machine re-run replaces its own
  (clip, track, source) rows. Rows with source='human' are never touched by
  machine writers and always win.
- No heavy imports at module level. The store layer is stdlib-only; numpy
  and ffmpeg live in strata_analyzers and are optional.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.utils import timeline_brain_db
from src.utils.embeddings import pack_vector as _pack_vector
from src.utils.embeddings import unpack_vector as _unpack_vector

logger = logging.getLogger("resolve-mcp.strata")

HUMAN_SOURCE = "human"

# Well-known track names. Not enforced by the schema (new analyzers may add
# tracks freely); listed so agents and the dashboard have a stable vocabulary.
EVENT_TRACKS = (
    "pause",        # speech gap inside a spoken region (duration = gap length)
    "breath",       # audible inhale candidate inside a speech gap
    "hesitation",   # filler word (uh/um/er) from the transcript
    "beat",         # musical beat (payload: {"tempo_bpm": float})
    "downbeat",     # low-confidence bar-start estimate
    "blink",        # eye blink (payload may carry entity_uuid)
    "gesture_boundary",
)
CURVE_TRACKS = (
    "pitch",          # Hz; NaN where unvoiced/silent
    "vocal_energy",   # RMS 0..1
    "speech_rate",    # words/sec smoothed
    "motion_energy",  # mean abs frame difference 0..1
    "loudness",       # momentary LUFS-like envelope
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


# ── clip resolution — the ONE resolver for every strata surface ──────────────


def resolve_clip(
    project_root: str,
    clip_ref: Any,
    *,
    require_media: bool = False,
) -> Tuple[Optional[sqlite3.Connection], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Resolve a clip ref to ``(conn, clip, error)`` — exactly one of
    ``clip``/``error`` is set (conn is always usable when clip is set).

    ``clip`` carries {clip_uuid, clip_name, file_path, duration_seconds, fps}.
    Uses the same pre-v9 auto-ingest fallback as deep_vision, so a ref that
    resolves for deepen resolves identically for every strata action. With
    ``require_media=True`` the clip's media file must exist on disk.
    """
    from src.utils import analysis_store

    conn = timeline_brain_db.connect(project_root)
    clip_uuid = analysis_store.resolve_clip_uuid_ingesting(project_root, conn, clip_ref)
    if not clip_uuid:
        return conn, None, {
            "success": False,
            "error": f"Unknown clip ref: {clip_ref!r} (older analysis root? run db_ingest first)",
        }
    row = conn.execute(
        "SELECT clip_uuid, clip_name, file_path, duration_seconds, fps FROM clips WHERE clip_uuid = ?",
        (clip_uuid,),
    ).fetchone()
    if row is None:
        return conn, None, {"success": False, "error": f"No clips row for {clip_uuid}"}
    clip = {
        "clip_uuid": clip_uuid,
        "clip_name": row["clip_name"],
        "file_path": row["file_path"],
        "duration_seconds": row["duration_seconds"],
        "fps": row["fps"],
    }
    if require_media:
        file_path = clip["file_path"]
        if not file_path or not os.path.isfile(file_path):
            return conn, None, {
                "success": False,
                "error": f"Media file not accessible for clip {clip['clip_name']!r}: {file_path!r}",
                "clip_uuid": clip_uuid,
            }
    return conn, clip, None


# ── float32 blob convention — ONE codec, shared with embeddings.vector ───────


def pack_curve(values: Sequence[float]) -> bytes:
    """Encode a float sequence as a little-endian float32 BLOB."""
    return _pack_vector([float(v) for v in values])


def unpack_curve(blob: bytes) -> List[float]:
    """Decode a float32 BLOB back to a list of floats."""
    return _unpack_vector(blob)


def curve_stats(values: Sequence[float]) -> Dict[str, Any]:
    """min/max/mean over the finite samples — cheap query pre-filter."""
    finite = [v for v in values if not math.isnan(v)]
    if not finite:
        return {"count": len(values), "finite_count": 0}
    return {
        "count": len(values),
        "finite_count": len(finite),
        "min": min(finite),
        "max": max(finite),
        "mean": sum(finite) / len(finite),
    }


# ── writers ──────────────────────────────────────────────────────────────────


def replace_track_events(
    conn: sqlite3.Connection,
    clip_uuid: str,
    track: str,
    events: Iterable[Dict[str, Any]],
    *,
    source: str,
    analyzer_version: str,
) -> int:
    """Replace this writer's rows for (clip, track): idempotent re-runs.

    Each event: {time_seconds, duration_seconds?, payload?}. Human rows on
    the same track are left untouched.
    """
    if source == HUMAN_SOURCE:
        raise ValueError("machine writer API; human events go through record_human_event")
    conn.execute(
        "DELETE FROM events WHERE clip_uuid = ? AND track = ? AND source = ?",
        (clip_uuid, track, source),
    )
    now = _now()
    written = 0
    for event in events:
        t = event.get("time_seconds")
        if not isinstance(t, (int, float)) or math.isnan(float(t)):
            continue
        duration = event.get("duration_seconds")
        payload = event.get("payload")
        conn.execute(
            """
            INSERT INTO events
                (clip_uuid, track, time_seconds, duration_seconds,
                 payload_json, source, analyzer_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_uuid,
                track,
                float(t),
                float(duration) if isinstance(duration, (int, float)) else None,
                _dumps(payload) if payload is not None else None,
                source,
                analyzer_version,
                now,
            ),
        )
        written += 1
    return written


def record_human_event(
    conn: sqlite3.Connection,
    clip_uuid: str,
    track: str,
    time_seconds: float,
    *,
    duration_seconds: Optional[float] = None,
    payload: Any = None,
    author: str = "human",
) -> int:
    """Append one human-judged event (never bulk-replaced by machines)."""
    cur = conn.execute(
        """
        INSERT INTO events
            (clip_uuid, track, time_seconds, duration_seconds,
             payload_json, source, analyzer_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            clip_uuid,
            track,
            float(time_seconds),
            float(duration_seconds) if duration_seconds is not None else None,
            _dumps({"author": author, **(payload if isinstance(payload, dict) else {"value": payload} if payload is not None else {})}),
            HUMAN_SOURCE,
            "human",
            _now(),
        ),
    )
    return int(cur.lastrowid or 0)


def write_curve(
    conn: sqlite3.Connection,
    clip_uuid: str,
    track: str,
    values: Sequence[float],
    *,
    sample_rate: float,
    start_seconds: float = 0.0,
    source: str,
    analyzer_version: str,
) -> Dict[str, Any]:
    """Upsert one sampled series for (clip, track, source)."""
    stats = curve_stats(values)
    conn.execute(
        """
        INSERT OR REPLACE INTO curves
            (clip_uuid, track, start_seconds, sample_rate, values_blob,
             stats_json, source, analyzer_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            clip_uuid,
            track,
            float(start_seconds),
            float(sample_rate),
            pack_curve(values),
            _dumps(stats),
            source,
            analyzer_version,
            _now(),
        ),
    )
    return stats


# ── readers ──────────────────────────────────────────────────────────────────


def read_events(
    conn: sqlite3.Connection,
    clip_uuid: str,
    track: Optional[str] = None,
    *,
    start_seconds: Optional[float] = None,
    end_seconds: Optional[float] = None,
) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM events WHERE clip_uuid = ?"
    args: List[Any] = [clip_uuid]
    if track:
        sql += " AND track = ?"
        args.append(track)
    # Window semantics: a span event overlaps the window, not merely starts
    # inside it — a 3 s pause that began before the window is still a pause.
    # Point events (no duration) use the half-open [start, end) convention.
    if start_seconds is not None:
        start = float(start_seconds)
        # A bare OR on the overlap test is non-sargable (ix_events_clip_track
        # could never range-seek on time_seconds). Bound the lower edge by the
        # track's longest span instead: no overlapping event can start earlier
        # than start - MAX(duration). The MAX probe is a single b-tree descent
        # via ix_events_clip_track_span (v15).
        span_sql = "SELECT MAX(duration_seconds) FROM events WHERE clip_uuid = ?"
        span_args: List[Any] = [clip_uuid]
        if track:
            span_sql += " AND track = ?"
            span_args.append(track)
        max_span = conn.execute(span_sql, span_args).fetchone()[0] or 0.0
        sql += (
            " AND time_seconds >= ?"
            " AND (time_seconds >= ? OR time_seconds + COALESCE(duration_seconds, 0) > ?)"
        )
        args.extend([start - float(max_span), start, start])
    if end_seconds is not None:
        sql += " AND time_seconds < ?"
        args.append(float(end_seconds))
    sql += " ORDER BY time_seconds"
    out = []
    for row in conn.execute(sql, args).fetchall():
        item = {
            "track": row["track"],
            "time_seconds": row["time_seconds"],
            "duration_seconds": row["duration_seconds"],
            "source": row["source"],
            "analyzer_version": row["analyzer_version"],
        }
        if row["payload_json"]:
            try:
                item["payload"] = json.loads(row["payload_json"])
            except (TypeError, ValueError):
                pass
        out.append(item)
    return out


def read_curve(
    conn: sqlite3.Connection,
    clip_uuid: str,
    track: str,
    *,
    source: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    sql = "SELECT * FROM curves WHERE clip_uuid = ? AND track = ?"
    args: List[Any] = [clip_uuid, track]
    if source:
        sql += " AND source = ?"
        args.append(source)
    row = conn.execute(sql + " ORDER BY created_at DESC LIMIT 1", args).fetchone()
    if row is None:
        return None
    result = {
        "track": row["track"],
        "start_seconds": row["start_seconds"],
        "sample_rate": row["sample_rate"],
        "values": unpack_curve(row["values_blob"]),
        "source": row["source"],
        "analyzer_version": row["analyzer_version"],
    }
    if row["stats_json"]:
        try:
            result["stats"] = json.loads(row["stats_json"])
        except (TypeError, ValueError):
            pass
    return result


def curve_value_at(curve: Dict[str, Any], time_seconds: float) -> Optional[float]:
    """Sample a curve dict (from read_curve) at a clip time. None off-range/NaN."""
    values = curve.get("values") or []
    if not values:
        return None
    idx = int(round((time_seconds - float(curve.get("start_seconds") or 0.0)) * float(curve["sample_rate"])))
    if idx < 0 or idx >= len(values):
        return None
    v = values[idx]
    return None if math.isnan(v) else v


def read_words(
    conn: sqlite3.Connection,
    clip_uuid: str,
    *,
    start_seconds: Optional[float] = None,
    end_seconds: Optional[float] = None,
    match: Optional[str] = None,
) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM transcript_words WHERE clip_uuid = ?"
    args: List[Any] = [clip_uuid]
    if start_seconds is not None:
        sql += " AND start_seconds >= ?"
        args.append(float(start_seconds))
    if end_seconds is not None:
        sql += " AND start_seconds < ?"
        args.append(float(end_seconds))
    if match:
        escaped = match.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        sql += " AND word LIKE ? ESCAPE '\\'"
        args.append(f"%{escaped}%")
    sql += " ORDER BY segment_index, word_index"
    return [
        {
            "segment_index": row["segment_index"],
            "word_index": row["word_index"],
            "word": row["word"],
            "start_seconds": row["start_seconds"],
            "end_seconds": row["end_seconds"],
            "confidence": row["confidence"],
        }
        for row in conn.execute(sql, args).fetchall()
    ]


def list_tracks(conn: sqlite3.Connection, clip_uuid: str) -> Dict[str, Any]:
    """Per-clip inventory: which tracks exist, from which writers."""
    events = [
        {
            "track": row["track"],
            "source": row["source"],
            "analyzer_version": row["analyzer_version"],
            "count": row["n"],
        }
        for row in conn.execute(
            """
            SELECT track, source, analyzer_version, COUNT(*) AS n
            FROM events WHERE clip_uuid = ?
            GROUP BY track, source, analyzer_version ORDER BY track
            """,
            (clip_uuid,),
        ).fetchall()
    ]
    curves = [
        {
            "track": row["track"],
            "source": row["source"],
            "analyzer_version": row["analyzer_version"],
            "sample_rate": row["sample_rate"],
            "stats": json.loads(row["stats_json"]) if row["stats_json"] else None,
        }
        for row in conn.execute(
            "SELECT track, source, analyzer_version, sample_rate, stats_json FROM curves WHERE clip_uuid = ? ORDER BY track",
            (clip_uuid,),
        ).fetchall()
    ]
    word_count = conn.execute(
        "SELECT COUNT(*) AS n FROM transcript_words WHERE clip_uuid = ?", (clip_uuid,)
    ).fetchone()["n"]
    beat_count = conn.execute(
        "SELECT COUNT(*) AS n FROM story_beats WHERE clip_uuid = ? AND superseded_at IS NULL",
        (clip_uuid,),
    ).fetchone()["n"]
    return {
        "events": events,
        "curves": curves,
        "word_count": int(word_count),
        "story_beat_count": int(beat_count),
    }


# ── transcript words: ingest + backfill ──────────────────────────────────────


def _word_confidence(word: Dict[str, Any]) -> Optional[float]:
    for key in ("probability", "confidence", "score"):
        value = word.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def ingest_transcript_words(
    conn: sqlite3.Connection,
    clip_uuid: str,
    transcription: Dict[str, Any],
) -> int:
    """Rebuild transcript_words for a clip from a report's transcription block.

    Words normally live per-segment (``segments[*].words``); segments without
    their own words fall back to the top-level ``words`` list, bucketed by
    start time. When the block yields no words at all, existing rows are left
    untouched — a words-less re-analysis must not silently wipe previously
    ingested or backfilled words. Returns the number of word rows written.
    """
    if not isinstance(transcription, dict):
        return 0
    segments = transcription.get("segments") if isinstance(transcription.get("segments"), list) else []

    per_segment: List[List[Dict[str, Any]]] = []
    for seg in segments:
        words = seg.get("words") if isinstance(seg, dict) and isinstance(seg.get("words"), list) else []
        per_segment.append([w for w in words if isinstance(w, dict)])

    top_words = transcription.get("words") if isinstance(transcription.get("words"), list) else []
    top_words = [w for w in top_words if isinstance(w, dict)]
    if top_words:
        if not segments:
            per_segment = [top_words]
        else:
            bounds = []
            for seg in segments:
                start = seg.get("start") if isinstance(seg, dict) else None
                bounds.append(float(start) if isinstance(start, (int, float)) else 0.0)
            fallback: List[List[Dict[str, Any]]] = [[] for _ in segments]
            for word in top_words:
                t = word.get("start")
                t = float(t) if isinstance(t, (int, float)) else 0.0
                idx = 0
                for i, b in enumerate(bounds):
                    if t >= b:
                        idx = i
                fallback[idx].append(word)
            for i, words in enumerate(per_segment):
                if not words:
                    per_segment[i] = fallback[i]

    rows: List[tuple] = []
    for seg_idx, words in enumerate(per_segment):
        for word_idx, word in enumerate(words):
            text = str(word.get("word", word.get("text", ""))).strip()
            if not text:
                continue
            start = word.get("start")
            end = word.get("end")
            rows.append(
                (
                    clip_uuid,
                    seg_idx,
                    word_idx,
                    text,
                    float(start) if isinstance(start, (int, float)) else None,
                    float(end) if isinstance(end, (int, float)) else None,
                    _word_confidence(word),
                )
            )
    if not rows:
        return 0
    conn.execute("DELETE FROM transcript_words WHERE clip_uuid = ?", (clip_uuid,))
    conn.executemany(
        """
        INSERT OR REPLACE INTO transcript_words
            (clip_uuid, segment_index, word_index, word,
             start_seconds, end_seconds, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def backfill_transcript_words(project_root: str) -> Dict[str, Any]:
    """Populate transcript_words from every stored report blob.

    Reports written before v13 already carry per-word timestamps inside
    ``transcription.segments[*].words`` — this promotes them to rows without
    re-running any analysis. Idempotent.
    """
    conn = timeline_brain_db.connect(project_root)
    clips_seen = int(conn.execute("SELECT COUNT(*) FROM analysis_reports").fetchone()[0])
    clips_with_words = 0
    words_written = 0
    with timeline_brain_db.transaction(project_root) as txn:
        # Lazy cursor + substring prefilter: never hold every multi-MB report
        # blob in memory at once, and skip parsing reports that cannot carry
        # words. Reads and writes share the cached connection but touch
        # different tables, so interleaving is safe.
        cursor = txn.execute(
            "SELECT clip_uuid, report_json FROM analysis_reports "
            "WHERE report_json LIKE '%\"transcription\"%'"
        )
        for row in cursor:
            try:
                report = json.loads(row["report_json"])
            except (TypeError, ValueError):
                continue
            transcription = report.get("transcription") if isinstance(report, dict) else None
            if not isinstance(transcription, dict):
                continue
            n = ingest_transcript_words(txn, str(row["clip_uuid"]), transcription)
            if n:
                clips_with_words += 1
                words_written += n
    return {
        "success": True,
        "clips_seen": clips_seen,
        "clips_with_words": clips_with_words,
        "words_written": words_written,
    }


# ── status ───────────────────────────────────────────────────────────────────


def strata_status(project_root: str, clip_ref: Any = None) -> Dict[str, Any]:
    """Project-level (or per-clip) strata inventory."""
    conn = timeline_brain_db.connect(project_root)
    if clip_ref is not None:
        conn, clip, err = resolve_clip(project_root, clip_ref)
        if err:
            return err
        return {"success": True, "clip_uuid": clip["clip_uuid"], **list_tracks(conn, clip["clip_uuid"])}

    def _count(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    track_rows = conn.execute(
        "SELECT track, COUNT(*) AS n, COUNT(DISTINCT clip_uuid) AS clips FROM events GROUP BY track"
    ).fetchall()
    curve_rows = conn.execute(
        "SELECT track, COUNT(DISTINCT clip_uuid) AS clips FROM curves GROUP BY track"
    ).fetchall()
    clip_rows = conn.execute(
        """
        SELECT c.clip_uuid, c.clip_name, c.duration_seconds, c.fps, c.media_type,
               (SELECT COUNT(*) FROM transcript_words w WHERE w.clip_uuid = c.clip_uuid) AS word_count,
               (SELECT COUNT(DISTINCT track) FROM events e WHERE e.clip_uuid = c.clip_uuid) AS event_track_count,
               (SELECT COUNT(DISTINCT track) FROM curves v WHERE v.clip_uuid = c.clip_uuid) AS curve_track_count,
               (SELECT COUNT(*) FROM story_beats b WHERE b.clip_uuid = c.clip_uuid AND b.superseded_at IS NULL) AS story_beat_count
        FROM clips c ORDER BY c.clip_name LIMIT 500
        """
    ).fetchall()
    return {
        "success": True,
        "schema_version": timeline_brain_db.SCHEMA_VERSION,
        "clips": _count("SELECT COUNT(*) FROM clips"),
        "clips_with_words": _count("SELECT COUNT(DISTINCT clip_uuid) FROM transcript_words"),
        "word_count": _count("SELECT COUNT(*) FROM transcript_words"),
        "event_tracks": [
            {"track": r["track"], "events": r["n"], "clips": r["clips"]} for r in track_rows
        ],
        "curve_tracks": [{"track": r["track"], "clips": r["clips"]} for r in curve_rows],
        "story_beat_count": _count(
            "SELECT COUNT(*) FROM story_beats WHERE superseded_at IS NULL"
        ),
        "clip_rows": [
            {
                "clip_uuid": r["clip_uuid"],
                "clip_name": r["clip_name"],
                "duration_seconds": r["duration_seconds"],
                "fps": r["fps"],
                "media_type": r["media_type"],
                "word_count": int(r["word_count"]),
                "event_track_count": int(r["event_track_count"]),
                "curve_track_count": int(r["curve_track_count"]),
                "story_beat_count": int(r["story_beat_count"]),
            }
            for r in clip_rows
        ],
    }
