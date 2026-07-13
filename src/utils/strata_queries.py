"""Perception-strata queries — editorial questions as cross-track joins.

The strata store (events/curves/words/beats) is the vocabulary; these are
the sentences: take_diff (compare deliveries of the same line),
cut_candidates (rank joint frames with reasons), strata_query (windowed
cross-track fetch, timeline-projectable).

The line these never cross: measure, compare, flag, aim — never decide.
take_diff reports deltas, not a winner; cut_candidates ranks frames with
evidence, the editor picks.
"""

from __future__ import annotations

import difflib
import math
import statistics
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.utils import strata, timeline_brain_db

_WORD_STRIP = ".,!?;:\"'()[]—–-…"


def _norm_word(word: str) -> str:
    return word.strip().strip(_WORD_STRIP).lower()


def _resolve(project_root: str, clip_ref: Any) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    from src.utils import analysis_store

    conn = timeline_brain_db.connect(project_root)
    clip_uuid = analysis_store.resolve_clip_uuid(conn, clip_ref)
    if not clip_uuid:
        return None, {"success": False, "error": f"Unknown clip ref: {clip_ref!r}"}
    return clip_uuid, None


def _finite(values: Sequence[float]) -> List[float]:
    return [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]


def _curve_slice(curve: Optional[Dict[str, Any]], start: float, end: float) -> List[float]:
    if not curve or not curve.get("values"):
        return []
    rate = float(curve["sample_rate"])
    offset = float(curve.get("start_seconds") or 0.0)
    lo = max(0, int((start - offset) * rate))
    hi = min(len(curve["values"]), int((end - offset) * rate) + 1)
    return curve["values"][lo:hi] if hi > lo else []


def _delivery_metrics(
    conn,
    clip_uuid: str,
    words: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Prosodic profile of one take's aligned words. Measures; no judgment."""
    timed = [w for w in words if isinstance(w.get("start_seconds"), (int, float))]
    if not timed:
        return {"word_count": len(words), "timed": False}
    start = float(timed[0]["start_seconds"])
    last = timed[-1]
    end = float(last.get("end_seconds") or last["start_seconds"])
    duration = max(end - start, 1e-6)

    pauses = [
        e for e in strata.read_events(conn, clip_uuid, "pause", start_seconds=start, end_seconds=end)
    ]
    hesitations = strata.read_events(conn, clip_uuid, "hesitation", start_seconds=start, end_seconds=end)

    metrics: Dict[str, Any] = {
        "timed": True,
        "start_seconds": start,
        "end_seconds": end,
        "duration_seconds": round(duration, 3),
        "word_count": len(words),
        "words_per_second": round(len(timed) / duration, 3),
        "pause_count": len(pauses),
        "pause_total_seconds": round(sum(float(p.get("duration_seconds") or 0.0) for p in pauses), 3),
        "longest_pause_seconds": round(max((float(p.get("duration_seconds") or 0.0) for p in pauses), default=0.0), 3),
        "hesitation_count": len(hesitations),
    }

    pitch = _finite(_curve_slice(strata.read_curve(conn, clip_uuid, "pitch"), start, end))
    if len(pitch) >= 4:
        metrics["pitch"] = {
            "mean_hz": round(statistics.fmean(pitch), 1),
            "stdev_hz": round(statistics.pstdev(pitch), 1),
            "range_hz": round(max(pitch) - min(pitch), 1),
            "voiced_ratio": round(
                len(pitch) / max(1, len(_curve_slice(strata.read_curve(conn, clip_uuid, "pitch"), start, end))), 3
            ),
        }
    energy = _finite(_curve_slice(strata.read_curve(conn, clip_uuid, "vocal_energy"), start, end))
    if len(energy) >= 4:
        metrics["energy"] = {
            "mean": round(statistics.fmean(energy), 4),
            "stdev": round(statistics.pstdev(energy), 4),
            "peak": round(max(energy), 4),
        }
    return metrics


def take_diff(
    project_root: str,
    clip_a: Any,
    clip_b: Any,
    *,
    text: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare two deliveries of the same (or similar) line, with evidence.

    Aligns the takes on transcript words (difflib on normalized tokens; when
    `text` is given, each take is first narrowed to its best window matching
    that line). Returns per-take delivery metrics + deltas. It never says
    which take is better — that is the editor's call.
    """
    uuid_a, err = _resolve(project_root, clip_a)
    if err:
        return err
    uuid_b, err = _resolve(project_root, clip_b)
    if err:
        return err
    conn = timeline_brain_db.connect(project_root)
    words_a = strata.read_words(conn, uuid_a)
    words_b = strata.read_words(conn, uuid_b)
    if not words_a or not words_b:
        return {
            "success": False,
            "error": "both takes need transcript_words rows (run transcription / backfill_words first)",
            "words_a": len(words_a),
            "words_b": len(words_b),
        }

    if text:
        words_a = _best_text_window(words_a, text)
        words_b = _best_text_window(words_b, text)
        if not words_a or not words_b:
            return {"success": False, "error": f"line not found in one of the takes: {text!r}"}

    tokens_a = [_norm_word(w["word"]) for w in words_a]
    tokens_b = [_norm_word(w["word"]) for w in words_b]
    matcher = difflib.SequenceMatcher(a=tokens_a, b=tokens_b, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size > 0]
    aligned_a = [words_a[b.a + i] for b in blocks for i in range(b.size)]
    aligned_b = [words_b[b.b + i] for b in blocks for i in range(b.size)]
    ratio = matcher.ratio()

    metrics_a = _delivery_metrics(conn, uuid_a, aligned_a)
    metrics_b = _delivery_metrics(conn, uuid_b, aligned_b)

    deltas: Dict[str, Any] = {}
    for key in ("duration_seconds", "words_per_second", "pause_count", "pause_total_seconds", "longest_pause_seconds", "hesitation_count"):
        va, vb = metrics_a.get(key), metrics_b.get(key)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            deltas[key] = round(vb - va, 3)
    if isinstance(metrics_a.get("pitch"), dict) and isinstance(metrics_b.get("pitch"), dict):
        deltas["pitch_mean_hz"] = round(metrics_b["pitch"]["mean_hz"] - metrics_a["pitch"]["mean_hz"], 1)
        deltas["pitch_range_hz"] = round(metrics_b["pitch"]["range_hz"] - metrics_a["pitch"]["range_hz"], 1)
    if isinstance(metrics_a.get("energy"), dict) and isinstance(metrics_b.get("energy"), dict):
        deltas["energy_mean"] = round(metrics_b["energy"]["mean"] - metrics_a["energy"]["mean"], 4)

    return {
        "success": True,
        "alignment": {
            "ratio": round(ratio, 3),
            "aligned_word_count": len(aligned_a),
            "note": "metrics are computed over the aligned words only",
        },
        "take_a": {"clip_uuid": uuid_a, "text": " ".join(w["word"] for w in aligned_a), **{"metrics": metrics_a}},
        "take_b": {"clip_uuid": uuid_b, "text": " ".join(w["word"] for w in aligned_b), **{"metrics": metrics_b}},
        "deltas_b_minus_a": deltas,
        "judgment": "none — measure/compare only; the pick is the editor's",
    }


# ── strata_query — windowed cross-track fetch + word find + timeline scope ──

_EVENT_TRACK_DEFAULT = ("pause", "breath", "hesitation", "beat", "downbeat", "blink")
_CURVE_TRACK_DEFAULT = ("pitch", "vocal_energy", "speech_rate", "motion_energy",
                        "gaze_x", "gaze_y", "expression_mouth_open", "expression_brow_raise")


def _clip_bundle(
    conn,
    clip_uuid: str,
    start: Optional[float],
    end: Optional[float],
    *,
    include_curve_values: bool = False,
) -> Dict[str, Any]:
    """Everything the strata know about one clip window, joined."""
    bundle: Dict[str, Any] = {"clip_uuid": clip_uuid}
    row = conn.execute(
        "SELECT clip_name, duration_seconds, fps FROM clips WHERE clip_uuid = ?", (clip_uuid,)
    ).fetchone()
    if row:
        bundle["clip_name"] = row["clip_name"]
        bundle["fps"] = row["fps"]

    bundle["words"] = strata.read_words(conn, clip_uuid, start_seconds=start, end_seconds=end)

    events: Dict[str, List[Dict[str, Any]]] = {}
    for track in _EVENT_TRACK_DEFAULT:
        hits = strata.read_events(conn, clip_uuid, track, start_seconds=start, end_seconds=end)
        if hits:
            events[track] = hits
    bundle["events"] = events

    curves: Dict[str, Any] = {}
    for track in _CURVE_TRACK_DEFAULT:
        curve = strata.read_curve(conn, clip_uuid, track)
        if curve is None:
            continue
        lo = start if start is not None else 0.0
        hi = end if end is not None else (lo + len(curve["values"]) / float(curve["sample_rate"]))
        window = _finite(_curve_slice(curve, lo, hi))
        entry: Dict[str, Any] = {"sample_rate": curve["sample_rate"], "source": curve["source"]}
        if window:
            entry["window_stats"] = {
                "min": round(min(window), 4),
                "max": round(max(window), 4),
                "mean": round(sum(window) / len(window), 4),
            }
        if include_curve_values:
            entry["values"] = _curve_slice(curve, lo, hi)
            entry["start_seconds"] = lo
        curves[track] = entry
    bundle["curves"] = curves

    beat_sql = "SELECT * FROM story_beats WHERE clip_uuid = ? AND superseded_at IS NULL"
    args: List[Any] = [clip_uuid]
    if start is not None:
        beat_sql += " AND end_seconds > ?"
        args.append(start)
    if end is not None:
        beat_sql += " AND start_seconds < ?"
        args.append(end)
    bundle["story_beats"] = [
        {
            "beat_uuid": r["beat_uuid"],
            "start_seconds": r["start_seconds"],
            "end_seconds": r["end_seconds"],
            "beat_type": r["beat_type"],
            "label": r["label"],
            "summary": r["summary"],
        }
        for r in conn.execute(beat_sql + " ORDER BY start_seconds", args).fetchall()
    ]
    return bundle


def strata_query(
    project_root: str,
    *,
    clip_ref: Any = None,
    start_seconds: Optional[float] = None,
    end_seconds: Optional[float] = None,
    match_word: Optional[str] = None,
    context_seconds: float = 2.0,
    include_curve_values: bool = False,
    limit: int = 20,
) -> Dict[str, Any]:
    """The strata as one queryable surface.

    Modes:
    - clip window: clip_ref (+ start/end) → the full cross-track bundle.
    - word find:   match_word (project-wide or within clip_ref) → each hit
      with a ±context_seconds bundle around it — "find the moment", joined.
    """
    conn = timeline_brain_db.connect(project_root)

    if match_word:
        sql = (
            "SELECT w.clip_uuid, w.word, w.start_seconds, w.end_seconds, c.clip_name "
            "FROM transcript_words w JOIN clips c ON c.clip_uuid = w.clip_uuid "
            "WHERE w.word LIKE ?"
        )
        args: List[Any] = [f"%{match_word}%"]
        if clip_ref is not None:
            uuid_, err = _resolve(project_root, clip_ref)
            if err:
                return err
            sql += " AND w.clip_uuid = ?"
            args.append(uuid_)
        sql += " ORDER BY w.clip_uuid, w.start_seconds LIMIT ?"
        args.append(int(limit))
        hits = []
        for row in conn.execute(sql, args).fetchall():
            t = row["start_seconds"]
            hit: Dict[str, Any] = {
                "clip_uuid": row["clip_uuid"],
                "clip_name": row["clip_name"],
                "word": row["word"],
                "time_seconds": t,
            }
            if isinstance(t, (int, float)):
                hit["context"] = _clip_bundle(
                    conn,
                    row["clip_uuid"],
                    max(0.0, t - context_seconds),
                    t + context_seconds,
                    include_curve_values=include_curve_values,
                )
            hits.append(hit)
        return {"success": True, "mode": "word_find", "match": match_word, "hits": hits}

    if clip_ref is None:
        return {"success": False, "error": "strata_query needs clip_id and/or match_word"}
    uuid_, err = _resolve(project_root, clip_ref)
    if err:
        return err
    return {
        "success": True,
        "mode": "clip_window",
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        **_clip_bundle(conn, uuid_, start_seconds, end_seconds, include_curve_values=include_curve_values),
    }


def timeline_strata(
    project_root: str,
    timeline_name: str,
    *,
    timeline_version: Optional[int] = None,
    record_start_frame: Optional[int] = None,
    record_end_frame: Optional[int] = None,
    fps: float = 24.0,
    include_curve_values: bool = False,
) -> Dict[str, Any]:
    """Project clip strata through a timeline's recorded placements.

    Reads timeline_clip_usage (snapshotted at archive time), resolves each
    placed media-pool item back to its analyzed clip, and returns per-
    placement strata bundles. Placement rows carry RECORD in/out frames but
    not the source offset, so bundles are whole-clip; exact source↔record
    frame mapping needs the live timeline item and is labeled as such.
    """
    from src.utils import analysis_store

    conn = timeline_brain_db.connect(project_root)
    if timeline_version is None:
        row = conn.execute(
            "SELECT MAX(timeline_version) AS v FROM timeline_clip_usage WHERE timeline_name = ?",
            (timeline_name,),
        ).fetchone()
        if row is None or row["v"] is None:
            return {
                "success": False,
                "error": f"no clip-usage snapshots recorded for timeline {timeline_name!r}",
            }
        timeline_version = int(row["v"])

    sql = (
        "SELECT * FROM timeline_clip_usage WHERE timeline_name = ? AND timeline_version = ?"
    )
    args: List[Any] = [timeline_name, timeline_version]
    if record_start_frame is not None:
        sql += " AND out_frame > ?"
        args.append(int(record_start_frame))
    if record_end_frame is not None:
        sql += " AND in_frame < ?"
        args.append(int(record_end_frame))
    sql += " ORDER BY track_type, track_index, in_frame"

    placements = []
    unresolved = []
    for row in conn.execute(sql, args).fetchall():
        clip_uuid = analysis_store.resolve_clip_uuid(conn, row["media_pool_item_id"])
        placement = {
            "media_pool_item_id": row["media_pool_item_id"],
            "track_type": row["track_type"],
            "track_index": row["track_index"],
            "record_in_frame": row["in_frame"],
            "record_out_frame": row["out_frame"],
            "record_in_seconds": round(row["in_frame"] / fps, 3),
            "record_out_seconds": round(row["out_frame"] / fps, 3),
        }
        if clip_uuid:
            placement["strata"] = _clip_bundle(
                conn, clip_uuid, None, None, include_curve_values=include_curve_values
            )
        else:
            unresolved.append(row["media_pool_item_id"])
        placements.append(placement)

    return {
        "success": True,
        "timeline_name": timeline_name,
        "timeline_version": timeline_version,
        "fps_assumed": fps,
        "placements": placements,
        "unresolved_media_ids": sorted(set(unresolved)),
        "note": (
            "bundles are whole-clip (clip time); usage snapshots record placement, "
            "not source offset — frame-exact source↔record mapping needs the live item"
        ),
    }


# ── cut_candidates — the joint solver ────────────────────────────────────────
#
# Frame-level cut-point grammar, scored from whatever tracks exist:
#   cut on the blink · cut inside movement, not at its poles · don't cut
#   mid-word · don't bisect a breath · pauses are doors · land on the beat.
# Each feature contributes points AND a human-readable reason; missing
# tracks are reported, never silently treated as "no signal".

_CUT_WEIGHTS = {
    "mid_word": -3.0,
    "word_gap": 1.0,
    "in_pause": 2.0,
    "on_blink": 2.0,
    "bisects_breath": -1.5,
    "clears_breath": 0.75,
    "on_beat": 1.0,
    "in_motion_max": 0.75,
    "dead_still": -0.5,
}

_BLINK_TOLERANCE_FRAMES = 1.5
_BEAT_TOLERANCE_SECONDS = 0.05
_BREATH_CLEAR_SECONDS = 0.3


def cut_candidates(
    project_root: str,
    clip_ref: Any,
    time_seconds: float,
    *,
    window_seconds: float = 0.35,
    fps: Optional[float] = None,
    limit: int = 7,
) -> Dict[str, Any]:
    """Rank candidate cut frames around an intended joint, with reasons.

    Scores every frame in ±window_seconds on the cut-point grammar using the
    clip's available strata. Returns ranked candidates; the top row is a
    recommendation to *look at*, not a decision — aim, never decide.
    """
    uuid_, err = _resolve(project_root, clip_ref)
    if err:
        return err
    conn = timeline_brain_db.connect(project_root)
    if fps is None:
        row = conn.execute("SELECT fps, duration_seconds FROM clips WHERE clip_uuid = ?", (uuid_,)).fetchone()
        fps = float(row["fps"]) if row and row["fps"] else 24.0
    frame_dur = 1.0 / fps

    lo = max(0.0, time_seconds - window_seconds)
    hi = time_seconds + window_seconds
    fetch_lo, fetch_hi = lo - 2.0, hi + 2.0

    words = strata.read_words(conn, uuid_, start_seconds=fetch_lo, end_seconds=fetch_hi)
    pauses = strata.read_events(conn, uuid_, "pause", start_seconds=fetch_lo, end_seconds=fetch_hi)
    breaths = strata.read_events(conn, uuid_, "breath", start_seconds=fetch_lo, end_seconds=fetch_hi)
    blinks = strata.read_events(conn, uuid_, "blink", start_seconds=fetch_lo, end_seconds=fetch_hi)
    beats = strata.read_events(conn, uuid_, "beat", start_seconds=fetch_lo, end_seconds=fetch_hi)
    motion = strata.read_curve(conn, uuid_, "motion_energy")

    tracks_used = []
    tracks_missing = []
    for name, present in (
        ("transcript_words", bool(words)),
        ("pause", bool(pauses)),
        ("breath", bool(breaths)),
        ("blink", bool(blinks)),
        ("beat", bool(beats)),
        ("motion_energy", motion is not None),
    ):
        (tracks_used if present else tracks_missing).append(name)

    def score_frame(t: float) -> Tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []

        if words:
            inside = next(
                (
                    w for w in words
                    if isinstance(w.get("start_seconds"), (int, float))
                    and isinstance(w.get("end_seconds"), (int, float))
                    and w["start_seconds"] <= t < w["end_seconds"]
                ),
                None,
            )
            if inside:
                score += _CUT_WEIGHTS["mid_word"]
                reasons.append(f"mid-word — bisects “{inside['word']}”")
            else:
                score += _CUT_WEIGHTS["word_gap"]
                reasons.append("between words")

        for pause in pauses:
            start = float(pause["time_seconds"])
            dur = float(pause.get("duration_seconds") or 0.0)
            if start <= t < start + dur:
                score += _CUT_WEIGHTS["in_pause"]
                reasons.append(f"inside a {dur:.2f}s pause")
                break

        for blink in blinks:
            if abs(t - float(blink["time_seconds"])) <= _BLINK_TOLERANCE_FRAMES * frame_dur:
                score += _CUT_WEIGHTS["on_blink"]
                reasons.append("lands on a blink")
                break

        for breath in breaths:
            b_start = float(breath["time_seconds"])
            b_end = b_start + float(breath.get("duration_seconds") or 0.25)
            if b_start <= t < b_end:
                score += _CUT_WEIGHTS["bisects_breath"]
                reasons.append("bisects a breath")
                break
            if 0.0 <= t - b_end <= _BREATH_CLEAR_SECONDS:
                score += _CUT_WEIGHTS["clears_breath"]
                reasons.append("clears the inhale")
                break

        for beat in beats:
            if abs(t - float(beat["time_seconds"])) <= _BEAT_TOLERANCE_SECONDS:
                score += _CUT_WEIGHTS["on_beat"]
                reasons.append("on the musical beat")
                break

        if motion is not None:
            v = strata.curve_value_at(motion, t)
            if v is not None:
                if v >= 0.2:
                    bonus = _CUT_WEIGHTS["in_motion_max"] * min(v, 1.0)
                    score += bonus
                    reasons.append(f"inside movement (energy {v:.2f})")
                elif v < 0.05:
                    score += _CUT_WEIGHTS["dead_still"]
                    reasons.append("dead stillness")

        return score, reasons

    candidates = []
    n_frames = int(round((hi - lo) / frame_dur)) + 1
    for i in range(n_frames):
        t = lo + i * frame_dur
        score, reasons = score_frame(t)
        candidates.append(
            {
                "time_seconds": round(t, 4),
                "frame_offset": int(round((t - time_seconds) * fps)),
                "score": round(score, 3),
                "reasons": reasons,
            }
        )
    candidates.sort(key=lambda c: (-c["score"], abs(c["frame_offset"])))

    return {
        "success": True,
        "clip_uuid": uuid_,
        "requested_time_seconds": time_seconds,
        "fps": fps,
        "window_seconds": window_seconds,
        "candidates": candidates[: max(1, limit)],
        "tracks_used": tracks_used,
        "tracks_missing": tracks_missing,
        "note": "ranked evidence, not a decision — the editor picks the frame",
    }


def _best_text_window(words: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    """Narrow a take's words to the window best matching `text`."""
    target = [_norm_word(t) for t in text.split() if _norm_word(t)]
    if not target:
        return words
    tokens = [_norm_word(w["word"]) for w in words]
    n = len(target)
    if len(tokens) <= n:
        return words
    best_start, best_score = 0, -1.0
    # Slide a window of the target length (± slack) and score similarity.
    for start in range(0, len(tokens) - 1):
        window = tokens[start:start + n + max(2, n // 3)]
        score = difflib.SequenceMatcher(a=target, b=window, autojunk=False).ratio()
        if score > best_score:
            best_score, best_start = score, start
    if best_score < 0.4:
        return []
    end = min(len(words), best_start + n + max(2, n // 3))
    return words[best_start:end]
