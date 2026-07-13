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
