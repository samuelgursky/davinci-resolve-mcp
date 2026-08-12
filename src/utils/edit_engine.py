"""Edit-engine planning layer (Phase E of the analysis program).

Pure evidence + planning: this module reads the DB-canonical analysis store
and produces dry-run plans with a per-decision rationale. It never imports
or touches Resolve — execution (timeline creation, lifts, swaps) lives in
server.py behind the confirm-token gate and the destructive hook, which
supplies versioning + brain_edits for free.

Plans persist under ``memory/edit_plans/<plan_id>.json`` with a content
fingerprint; execution revalidates the fingerprint so a stale plan cannot
run against a changed project.

Loops:
- E1 selects  — rank shots by select potential / best moments (deep-tier
  subjective rows, with description fallbacks), story-spine order, build a
  NEW selects timeline (additive; failure costs nothing).
- E2 tighten  — find dead air (transcript gaps within each timeline item's
  source range) and propose lifts toward a stated goal, applied to a
  DUPLICATE of the timeline, never the original.
- E3 swap     — rank alternate shots for a timeline item via the
  embeddings similarity index.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.utils import analysis_memory, analysis_store, timeline_brain_db
from src.utils import edit_handles as _edit_handles_mod
from src.utils import silence_ripple as _silence_ripple_mod
from src.utils import transcript_edit as _transcript_edit_mod

PLAN_DIR_NAME = "edit_plans"
DEFAULT_HANDLE_SECONDS = 0.25
DEFAULT_MIN_PAUSE_SECONDS = 1.5
DEFAULT_SILENCE_THRESHOLD_DB = _silence_ripple_mod.DEFAULT_THRESHOLD_DB
DEFAULT_SILENCE_MIN_STRIP_FRAMES = _silence_ripple_mod.DEFAULT_MIN_STRIP_FRAMES
DEFAULT_SILENCE_PRE_HEAD_FRAMES = _silence_ripple_mod.DEFAULT_PRE_HEAD_FRAMES
DEFAULT_SILENCE_POST_TAIL_FRAMES = _silence_ripple_mod.DEFAULT_POST_TAIL_FRAMES

_SELECT_RANK = {"high": 3, "medium": 2, "low": 1}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _plan_dir(project_root: str) -> str:
    return os.path.join(analysis_memory.memory_dir(project_root), PLAN_DIR_NAME)


def _plan_fingerprint(plan: Dict[str, Any]) -> str:
    body = {k: v for k, v in plan.items() if k not in ("fingerprint", "saved_at")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def save_plan(project_root: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    analysis_memory.ensure_memory_structure(project_root)
    os.makedirs(_plan_dir(project_root), exist_ok=True)
    plan = dict(plan)
    plan.setdefault("plan_id", uuid.uuid4().hex[:12])
    plan["saved_at"] = _now()
    plan["fingerprint"] = _plan_fingerprint(plan)
    path = os.path.join(_plan_dir(project_root), f"{plan['plan_id']}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(plan, handle, indent=2, default=str)
    os.replace(tmp, path)
    return plan


def load_plan(project_root: str, plan_id: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(_plan_dir(project_root), f"{str(plan_id)}.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            plan = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(plan, dict):
        return None
    if plan.get("fingerprint") != _plan_fingerprint(plan):
        return {"_corrupt": True, "plan_id": plan_id}
    return plan


def list_plans(project_root: str, *, limit: int = 20, include_corrupt: bool = False) -> Dict[str, Any]:
    """List saved plans, newest first.

    `include_corrupt=True` (panel browser) surfaces fingerprint-mismatched
    plans as ``{"plan_id", "corrupt": True}`` warning rows instead of hiding
    them; the default keeps the MCP-action shape unchanged.
    """
    directory = _plan_dir(project_root)
    rows: List[Dict[str, Any]] = []
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory), reverse=True):
            if not name.endswith(".json"):
                continue
            plan = load_plan(project_root, name[:-5])
            if not plan or plan.get("_corrupt"):
                if include_corrupt:
                    rows.append({"plan_id": name[:-5], "corrupt": True})
                continue
            rows.append({
                "plan_id": plan.get("plan_id"),
                "kind": plan.get("kind"),
                "saved_at": plan.get("saved_at"),
                "executed_at": plan.get("executed_at"),
                "summary": plan.get("summary"),
            })
    rows.sort(key=lambda r: str(r.get("saved_at") or ""), reverse=True)
    return {"success": True, "plans": rows[: max(1, int(limit))]}


def mark_plan_executed(project_root: str, plan_id: str, result_summary: Dict[str, Any]) -> None:
    plan = load_plan(project_root, plan_id)
    if not plan or plan.get("_corrupt"):
        return
    plan["executed_at"] = _now()
    plan["execution_summary"] = result_summary
    plan["fingerprint"] = _plan_fingerprint(plan)
    path = os.path.join(_plan_dir(project_root), f"{plan_id}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(plan, handle, indent=2, default=str)
    os.replace(tmp, path)


# ── shared evidence helpers ──────────────────────────────────────────────────


def _shot_groups(shot_row: Dict[str, Any]) -> Dict[str, Any]:
    extra = shot_row.get("extra_json")
    if not extra:
        return {}
    try:
        groups = json.loads(extra)
    except (TypeError, ValueError):
        return {}
    return groups if isinstance(groups, dict) else {}


def _clip_fps(clip_row: Dict[str, Any]) -> float:
    fps = clip_row.get("fps")
    try:
        fps = float(fps)
    except (TypeError, ValueError):
        fps = 0.0
    return fps if fps > 0 else 24.0


# ── E1: selects assembly ─────────────────────────────────────────────────────


def plan_selects(
    project_root: str,
    *,
    timeline_name: Optional[str] = None,
    max_duration_seconds: Optional[float] = None,
    min_select_potential: str = "medium",
    handle_seconds: float = DEFAULT_HANDLE_SECONDS,
    max_shots: int = 60,
) -> Dict[str, Any]:
    """Rank shots into a selects plan (story-spine order, additive)."""
    conn = timeline_brain_db.connect(project_root)
    clips = {str(r["clip_uuid"]): dict(r) for r in conn.execute(
        "SELECT * FROM clips ORDER BY clip_name COLLATE NOCASE"
    ).fetchall()}
    if not clips:
        return {"success": False, "error": "No analyzed clips in the DB — analyze (or db_ingest) first."}
    min_rank = _SELECT_RANK.get(str(min_select_potential).lower(), 2)

    candidates: List[Dict[str, Any]] = []
    clip_order = {uuid_: i for i, uuid_ in enumerate(clips)}
    for shot_row in conn.execute(
        "SELECT * FROM shots ORDER BY clip_uuid, shot_index"
    ).fetchall():
        shot = dict(shot_row)
        clip = clips.get(str(shot["clip_uuid"]))
        if not clip or not clip.get("resolve_clip_id"):
            continue
        start = shot.get("time_seconds_start")
        end = shot.get("time_seconds_end")
        if start is None or end is None or float(end) - float(start) < 0.4:
            continue
        groups = _shot_groups(shot)
        editorial = groups.get("editorial") if isinstance(groups.get("editorial"), dict) else {}
        select_potential = str(editorial.get("select_potential") or "").lower()
        best_moment = editorial.get("best_moment") if isinstance(editorial.get("best_moment"), dict) else None
        rank = _SELECT_RANK.get(select_potential, 0)
        evidence: List[str] = []
        if rank:
            evidence.append(f"editorial.select_potential={select_potential} (deep vision)")
        if best_moment:
            evidence.append(f"best_moment at {best_moment.get('time_seconds')}s: {best_moment.get('why')}")
        if rank == 0:
            # Standard-analyzed clips have no deep editorial fields — fall back
            # to clip-level select potential so E1 works day one.
            clip_sp = conn.execute(
                """
                SELECT value_json FROM subjective_fields
                WHERE entity_type='clip' AND entity_uuid=? AND superseded_at IS NULL
                  AND field_path='editorial_classification.select_potential'
                """,
                (shot["clip_uuid"],),
            ).fetchone()
            if clip_sp:
                try:
                    value = str(json.loads(clip_sp["value_json"])).lower()
                    rank = _SELECT_RANK.get(value, 0)
                    if rank:
                        evidence.append(f"clip-level select_potential={value} (no per-shot deep pass yet)")
                except (TypeError, ValueError):
                    pass
        if rank < min_rank:
            continue
        candidates.append({
            "clip_uuid": shot["clip_uuid"],
            "clip_name": clip.get("clip_name"),
            "resolve_clip_id": clip.get("resolve_clip_id"),
            "shot_uuid": shot["shot_uuid"],
            "shot_index": shot["shot_index"],
            "time_seconds_start": float(start),
            "time_seconds_end": float(end),
            "duration_seconds": round(float(end) - float(start), 3),
            "fps": _clip_fps(clip),
            "rank": rank,
            "description": shot.get("description"),
            "rationale": "; ".join(evidence) or "shot present in analysis",
            "_order": (clip_order[str(shot["clip_uuid"])], int(shot["shot_index"])),
        })

    if not candidates:
        return {
            "success": False,
            "error": (
                f"No shots at select_potential >= {min_select_potential}. Run a deep pass "
                "(media_analysis action='deepen') or lower min_select_potential."
            ),
        }

    # Highest rank wins the budget; story-spine order for the final sequence.
    candidates.sort(key=lambda c: (-c["rank"], c["_order"]))
    chosen: List[Dict[str, Any]] = []
    total = 0.0
    for candidate in candidates[: max(1, int(max_shots) * 3)]:
        duration = candidate["duration_seconds"] + 2 * float(handle_seconds)
        if max_duration_seconds and total + duration > float(max_duration_seconds) and chosen:
            continue
        chosen.append(candidate)
        total += duration
        if len(chosen) >= int(max_shots):
            break
    chosen.sort(key=lambda c: c["_order"])

    decisions = []
    clip_infos = []
    for candidate in chosen:
        fps = candidate["fps"]
        clip_row = clips.get(str(candidate["clip_uuid"])) or {}
        clip_duration = clip_row.get("duration_seconds")
        src_start = max(0.0, candidate["time_seconds_start"] - float(handle_seconds))
        src_end = candidate["time_seconds_end"] + float(handle_seconds)
        if isinstance(clip_duration, (int, float)) and clip_duration:
            src_end = min(src_end, float(clip_duration))
        start_frame = int(round(src_start * fps))
        # AppendToTimeline clipInfo endFrame is a half-open (exclusive) bound —
        # duration = endFrame - startFrame. See api_truth "AppendToTimeline
        # clipInfo endFrame". No -1: that would shave the last frame of every select.
        end_frame = max(start_frame + 1, int(round(src_end * fps)))
        decision = {k: v for k, v in candidate.items() if not k.startswith("_")}
        decision["source_frame_range"] = [start_frame, end_frame]
        decisions.append(decision)
        clip_infos.append({
            "clip_id": candidate["resolve_clip_id"],
            "start_frame": start_frame,
            "end_frame": end_frame,
        })

    name = timeline_name or f"Selects — {_now()[:10]}"
    plan = save_plan(project_root, {
        "kind": "selects",
        "timeline_name": name,
        "decisions": decisions,
        "clip_infos": clip_infos,
        "estimated_duration_seconds": round(total, 2),
        "summary": f"{len(decisions)} shots, ~{round(total, 1)}s → new timeline '{name}'",
        "settings": {
            "min_select_potential": min_select_potential,
            "max_duration_seconds": max_duration_seconds,
            "handle_seconds": handle_seconds,
        },
    })
    return {
        "success": True,
        "status": "plan_ready",
        "plan_id": plan["plan_id"],
        "kind": "selects",
        "timeline_name": name,
        "decision_count": len(decisions),
        "estimated_duration_seconds": plan["estimated_duration_seconds"],
        "decisions": decisions,
        "note": (
            "Dry-run plan. Execute with edit_engine(action='execute_selects', "
            "params={plan_id}) — a NEW timeline is created; nothing existing is touched."
        ),
    }


# ── E2: tighten ──────────────────────────────────────────────────────────────


def _speech_intervals(conn, clip_uuid: str) -> List[Tuple[float, float]]:
    rows = conn.execute(
        """
        SELECT start_seconds, end_seconds FROM transcript_segments
        WHERE clip_uuid = ? AND start_seconds IS NOT NULL AND end_seconds IS NOT NULL
        ORDER BY start_seconds
        """,
        (clip_uuid,),
    ).fetchall()
    return [(float(r["start_seconds"]), float(r["end_seconds"])) for r in rows]


def _gaps_in_range(
    intervals: Sequence[Tuple[float, float]],
    start: float,
    end: float,
    *,
    min_gap: float,
) -> List[Tuple[float, float]]:
    """Sub-ranges of [start, end] not covered by any interval, >= min_gap."""
    gaps: List[Tuple[float, float]] = []
    cursor = start
    for s, e in sorted(intervals):
        if e <= start or s >= end:
            continue
        s, e = max(s, start), min(e, end)
        if s - cursor >= min_gap:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if end - cursor >= min_gap:
        gaps.append((cursor, end))
    return gaps


def _dedupe_skipped(skipped: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse identical (item, reason) skip rows into one entry with a count.

    A timeline layer cut into many segments from one unanalyzed source clip
    otherwise reports the same skip once per segment (87 identical rows in a
    real two-layer session), which bloats the plan payload without adding
    signal. First occurrence order is preserved.
    """
    out: List[Dict[str, Any]] = []
    index: Dict[Tuple[Any, Any], Dict[str, Any]] = {}
    for row in skipped:
        key = (row.get("item"), row.get("reason"))
        hit = index.get(key)
        if hit is None:
            hit = dict(row)
            hit["count"] = 1
            index[key] = hit
            out.append(hit)
        else:
            hit["count"] += 1
    return out


def plan_tighten(
    project_root: str,
    *,
    items: Sequence[Dict[str, Any]],
    timeline_name: str,
    timeline_fps: float,
    target_ratio: Optional[float] = None,
    min_pause_seconds: float = DEFAULT_MIN_PAUSE_SECONDS,
    handle_seconds: float = DEFAULT_HANDLE_SECONDS,
    include_audio: bool = True,
) -> Dict[str, Any]:
    """Propose dead-air lifts for a timeline.

    `items` rows come from the server (Resolve read): each needs
    {timeline_start_frame, timeline_end_frame, source_start_frame,
     media_ref (clip id / path / hash), item_name?}. Optionally each row may
    carry {audio_track_indices: [int, ...]} naming the audio tracks that hold
    the item's linked audio. Lifts are returned in timeline frames, latest-first
    ready.

    When ``include_audio`` (the default), each kept video range is mirrored onto
    matching audio range(s) so the assembled variant carries sound — a
    speech-driven cut would otherwise come out silent (see #67). Audio is
    mirrored to the item's detected ``audio_track_indices``; absent that, it
    falls back to audio track 1, which is where a single linked A/V clip's audio
    lives.
    """
    if not items:
        return {"success": False, "error": "No timeline items supplied"}
    fps = float(timeline_fps) if timeline_fps and float(timeline_fps) > 0 else 24.0
    conn = timeline_brain_db.connect(project_root)

    lifts: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    item_specs: List[Dict[str, Any]] = []  # per usable item: source mapping for keep-range rebuild
    timeline_total_frames = 0
    for item_index, item in enumerate(items):
        try:
            tl_start = int(item["timeline_start_frame"])
            tl_end = int(item["timeline_end_frame"])
            src_start_frame = int(item.get("source_start_frame") or 0)
        except (KeyError, TypeError, ValueError):
            skipped.append({"item": item.get("item_name"), "reason": "missing frame fields"})
            continue
        timeline_total_frames += max(0, tl_end - tl_start)
        clip_uuid = analysis_store.resolve_clip_uuid(
            conn, item.get("media_ref")
        ) or analysis_store.resolve_clip_uuid(conn, item.get("media_path"))
        if not clip_uuid:
            skipped.append({"item": item.get("item_name"), "reason": "no analysis for source media (db_ingest or analyze first)"})
            item_specs.append({"item_index": item_index, "unanalyzed": True,
                               "resolve_clip_id": None, "item": item})
            continue
        clip_row = conn.execute("SELECT * FROM clips WHERE clip_uuid = ?", (clip_uuid,)).fetchone()
        clip_fps = _clip_fps(dict(clip_row)) if clip_row else fps
        src_start_sec = src_start_frame / clip_fps
        src_end_sec = src_start_sec + (tl_end - tl_start) / fps
        spec = {
            "item_index": item_index,
            "item": item,
            "clip_uuid": clip_uuid,
            "clip_fps": clip_fps,
            "resolve_clip_id": dict(clip_row).get("resolve_clip_id") if clip_row else None,
            "src_start_sec": src_start_sec,
            "src_end_sec": src_end_sec,
        }
        item_specs.append(spec)
        speech = _speech_intervals(conn, clip_uuid)
        if not speech:
            skipped.append({"item": item.get("item_name"), "reason": "no transcript segments — dead-air evidence unavailable"})
            continue
        for gap_start, gap_end in _gaps_in_range(speech, src_start_sec, src_end_sec, min_gap=float(min_pause_seconds)):
            # Keep handles on both sides of the lift.
            lift_start_sec = gap_start + float(handle_seconds)
            lift_end_sec = gap_end - float(handle_seconds)
            if lift_end_sec - lift_start_sec < 0.2:
                continue
            lift_start = tl_start + int(round((lift_start_sec - src_start_sec) * fps))
            lift_end = tl_start + int(round((lift_end_sec - src_start_sec) * fps))
            if lift_end <= lift_start:
                continue
            lifts.append({
                "kind": "dead_air",
                "action": "lift",
                "timeline_start_frame": lift_start,
                "timeline_end_frame": lift_end,
                "duration_seconds": round((lift_end - lift_start) / fps, 3),
                "item_name": item.get("item_name"),
                "item_index": item_index,
                "clip_uuid": clip_uuid,
                "source_lift_seconds": [round(lift_start_sec, 3), round(lift_end_sec, 3)],
                "rationale": (
                    f"No speech from {round(gap_start, 2)}s to {round(gap_end, 2)}s in the source "
                    f"transcript ({round(gap_end - gap_start, 2)}s pause; handles kept)."
                ),
                "evidence": {
                    "source_gap_seconds": [round(gap_start, 3), round(gap_end, 3)],
                    "basis": "transcript_segments",
                },
            })

    skipped = _dedupe_skipped(skipped)
    if not lifts:
        return {
            "success": False,
            "error": "No dead-air lifts found",
            "skipped": skipped,
            "note": f"min_pause_seconds={min_pause_seconds}; items without transcripts are skipped.",
        }

    lifts.sort(key=lambda l: -l["duration_seconds"])
    if target_ratio:
        target_frames = timeline_total_frames * float(target_ratio)
        chosen: List[Dict[str, Any]] = []
        removed = 0.0
        for lift in lifts:
            if removed >= target_frames:
                break
            chosen.append(lift)
            removed += (lift["timeline_end_frame"] - lift["timeline_start_frame"])
        lifts = chosen
    # Latest-first application order so earlier spans stay valid.
    lifts.sort(key=lambda l: -l["timeline_start_frame"])

    # Keep ranges: per item, the complement of its selected lifts, expressed as
    # media-pool SOURCE frame ranges. Execution assembles a tightened VARIANT
    # timeline from these (true partial trims; the original is never mutated).
    keep_ranges: List[Dict[str, Any]] = []
    lifts_by_item: Dict[int, List[Dict[str, Any]]] = {}
    for lift in lifts:
        lifts_by_item.setdefault(int(lift["item_index"]), []).append(lift)
    for spec in item_specs:
        item = spec["item"]
        if spec.get("unanalyzed") or not spec.get("resolve_clip_id"):
            # Items we can't trim ride along whole when their clip is known;
            # otherwise they were already reported in `skipped`.
            continue
        clip_fps = spec["clip_fps"]
        cursor = spec["src_start_sec"]
        segments: List[Tuple[float, float]] = []
        for lift in sorted(lifts_by_item.get(spec["item_index"], []), key=lambda l: l["source_lift_seconds"][0]):
            lift_start_sec, lift_end_sec = lift["source_lift_seconds"]
            if lift_start_sec - cursor > 0.05:
                segments.append((cursor, lift_start_sec))
            cursor = max(cursor, lift_end_sec)
        if spec["src_end_sec"] - cursor > 0.05:
            segments.append((cursor, spec["src_end_sec"]))
        audio_indices: List[int] = []
        if include_audio:
            audio_indices = [int(i) for i in (item.get("audio_track_indices") or []) if int(i) > 0]
            if not audio_indices:
                audio_indices = [1]
        for seg_start, seg_end in segments:
            start_frame = int(round(seg_start * clip_fps))
            # Half-open (exclusive) endFrame — duration = end - start. No -1, else
            # every kept segment loses its last frame (see api_truth endFrame entry).
            end_frame = max(start_frame + 1, int(round(seg_end * clip_fps)))
            keep_ranges.append({
                "clip_id": spec["resolve_clip_id"],
                "start_frame": start_frame,
                "end_frame": end_frame,
                "track_type": "video",
                "track_index": int(item.get("track_index") or 1),
            })
            # Mirror each kept video range onto its linked audio track(s) with
            # identical source frames so the variant stays frame-locked and
            # audible. mediaType 2 pulls the same media-pool item's audio.
            for audio_index in audio_indices:
                keep_ranges.append({
                    "clip_id": spec["resolve_clip_id"],
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "track_type": "audio",
                    "media_type": 2,
                    "track_index": audio_index,
                })

    removed_frames = sum(l["timeline_end_frame"] - l["timeline_start_frame"] for l in lifts)
    audio_keep_range_count = sum(1 for r in keep_ranges if r.get("track_type") == "audio")
    video_keep_range_count = len(keep_ranges) - audio_keep_range_count
    plan = save_plan(project_root, {
        "kind": "tighten",
        "timeline_name": timeline_name,
        "timeline_fps": fps,
        "lifts": lifts,
        "keep_ranges": keep_ranges,
        "include_audio": bool(include_audio),
        "skipped": skipped,
        "summary": (
            f"{len(lifts)} dead-air lifts, ~{round(removed_frames / fps, 1)}s removed "
            f"from '{timeline_name}' (assembled as a tightened variant"
            f"{', video + audio' if include_audio else ', video only'})"
        ),
        "settings": {
            "target_ratio": target_ratio,
            "min_pause_seconds": min_pause_seconds,
            "handle_seconds": handle_seconds,
            "include_audio": bool(include_audio),
        },
    })
    return {
        "success": True,
        "status": "plan_ready",
        "plan_id": plan["plan_id"],
        "kind": "tighten",
        "timeline_name": timeline_name,
        "lift_count": len(lifts),
        "estimated_removed_seconds": round(removed_frames / fps, 2),
        "lifts": lifts,
        "keep_range_count": len(keep_ranges),
        "video_keep_range_count": video_keep_range_count,
        "audio_keep_range_count": audio_keep_range_count,
        "include_audio": bool(include_audio),
        "skipped": skipped,
        "note": (
            "Dry-run plan. Execute with edit_engine(action='execute_tighten', "
            "params={plan_id}) — a tightened VARIANT timeline is assembled from "
            "the keep ranges; the original timeline is never mutated. "
            + (
                f"Audio is mirrored onto matching tracks ({audio_keep_range_count} "
                "audio ranges) so the variant is audible."
                if include_audio
                else "include_audio=False: the variant will be VIDEO-ONLY (silent)."
            )
        ),
    }


# ── E2b: waveform silence ripple (Resolve UI parity) ─────────────────────────


def _resolve_media_path(conn, item: Dict[str, Any]) -> Optional[str]:
    path = item.get("media_path") or item.get("file_path")
    if path and os.path.isfile(str(path)):
        return str(path)
    clip_uuid = analysis_store.resolve_clip_uuid(conn, item.get("media_ref"))
    if not clip_uuid:
        clip_uuid = analysis_store.resolve_clip_uuid(conn, item.get("media_path"))
    if not clip_uuid:
        return None
    row = conn.execute("SELECT file_path FROM clips WHERE clip_uuid = ?", (clip_uuid,)).fetchone()
    if not row or not row["file_path"]:
        return None
    fp = str(row["file_path"])
    return fp if os.path.isfile(fp) else None


def plan_silence_ripple(
    project_root: str,
    *,
    items: Sequence[Dict[str, Any]],
    timeline_name: str,
    timeline_fps: float,
    threshold_db: Optional[float] = None,
    min_strip_frames: float = DEFAULT_SILENCE_MIN_STRIP_FRAMES,
    pre_head_frames: float = DEFAULT_SILENCE_PRE_HEAD_FRAMES,
    post_tail_frames: float = DEFAULT_SILENCE_POST_TAIL_FRAMES,
    include_audio: bool = True,
) -> Dict[str, Any]:
    """Propose silence strips from waveform detection (ffmpeg silencedetect).

    Mirrors Resolve's *Clip → Audio Operations → Ripple Delete Silence*.
    Each timeline item is analyzed over its source trim; detected silences
    become lifts assembled into a tightened VARIANT via keep_ranges.
    """
    if not items:
        return {"success": False, "error": "No timeline items supplied"}
    fps = float(timeline_fps) if timeline_fps and float(timeline_fps) > 0 else 24.0
    min_strip_sec = _silence_ripple_mod.frames_to_seconds(min_strip_frames, fps)
    pre_head_sec = _silence_ripple_mod.frames_to_seconds(pre_head_frames, fps)
    post_tail_sec = _silence_ripple_mod.frames_to_seconds(post_tail_frames, fps)
    conn = timeline_brain_db.connect(project_root)

    lifts: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    item_specs: List[Dict[str, Any]] = []
    timeline_total_frames = 0

    for item_index, item in enumerate(items):
        try:
            tl_start = int(item["timeline_start_frame"])
            tl_end = int(item["timeline_end_frame"])
            src_start_frame = int(item.get("source_start_frame") or 0)
        except (KeyError, TypeError, ValueError):
            skipped.append({"item": item.get("item_name"), "reason": "missing frame fields"})
            continue
        timeline_total_frames += max(0, tl_end - tl_start)

        clip_uuid = analysis_store.resolve_clip_uuid(conn, item.get("media_ref"))
        if not clip_uuid:
            clip_uuid = analysis_store.resolve_clip_uuid(conn, item.get("media_path"))
        clip_row = None
        clip_fps = fps
        resolve_clip_id = None
        source_total_frames = None
        if clip_uuid:
            clip_row = conn.execute("SELECT * FROM clips WHERE clip_uuid = ?", (clip_uuid,)).fetchone()
            if clip_row:
                clip_fps = _clip_fps(dict(clip_row))
                resolve_clip_id = dict(clip_row).get("resolve_clip_id")
                # Needed to tell a keep range that ends mid-clip (has handles)
                # from one that runs to the last frame (has none). Absent length
                # means unverified, which is reported as such rather than
                # assumed clean — see edit_handles.
                _dur = dict(clip_row).get("duration_seconds")
                if isinstance(_dur, (int, float)) and _dur > 0:
                    source_total_frames = int(round(float(_dur) * clip_fps))
        resolve_clip_id = resolve_clip_id or item.get("media_ref")
        if not resolve_clip_id:
            skipped.append({
                "item": item.get("item_name"),
                "reason": "no media reference — OMITTED from the assembled variant",
            })
            continue

        src_start_sec = src_start_frame / clip_fps
        src_end_sec = src_start_sec + (tl_end - tl_start) / fps
        spec = {
            "item_index": item_index,
            "item": item,
            "clip_uuid": clip_uuid,
            "clip_fps": clip_fps,
            "resolve_clip_id": resolve_clip_id,
            "src_start_sec": src_start_sec,
            "src_end_sec": src_end_sec,
            "source_total_frames": source_total_frames,
            # Default: ride along whole. Overwritten below when waveform
            # evidence is available for this item.
            "keep_segments": [(src_start_sec, src_end_sec)],
            "strip_regions": [],
        }

        media_path = _resolve_media_path(conn, item)
        if not media_path:
            skipped.append({
                "item": item.get("item_name"),
                "reason": "no readable media file path — kept whole in variant",
            })
            item_specs.append(spec)
            continue
        if not _silence_ripple_mod.ffmpeg_available():
            return {
                "success": False,
                "error": (
                    "ffmpeg not found on PATH — waveform silence detection "
                    "requires ffmpeg (see media_analysis capabilities)"
                ),
            }

        # An explicit threshold is honoured as given; omitting it calibrates the
        # gate from this slice's own dynamics. An unusable calibration means no
        # threshold suits this material — keep the item whole rather than strip
        # it against a gate that was never validated against the audio.
        item_threshold = threshold_db
        calibration = None
        if item_threshold is None:
            calibration = _silence_ripple_mod.calibrate_silence_gate(
                media_path, src_start_sec, src_end_sec
            )
            spec["calibration"] = calibration.as_dict()
            if not calibration.usable:
                skipped.append({
                    "item": item.get("item_name"),
                    "reason": f"silence gate could not be calibrated — kept whole: {calibration.reason}",
                    "calibration": calibration.as_dict(),
                })
                item_specs.append(spec)
                continue
            item_threshold = calibration.gate_db

        strip_regions, keep_segments = _silence_ripple_mod.plan_item_silence_strips(
            media_path,
            src_start_sec,
            src_end_sec,
            threshold_db=float(item_threshold),
            min_strip_sec=min_strip_sec,
            pre_head_sec=pre_head_sec,
            post_tail_sec=post_tail_sec,
        )
        spec["keep_segments"] = keep_segments
        spec["strip_regions"] = strip_regions
        spec["threshold_db"] = float(item_threshold)
        item_specs.append(spec)

        for strip_start, strip_end in strip_regions:
            lift_start = tl_start + int(round((strip_start - src_start_sec) * fps))
            lift_end = tl_start + int(round((strip_end - src_start_sec) * fps))
            if lift_end <= lift_start:
                continue
            lifts.append({
                "kind": "silence",
                "action": "ripple_delete",
                "timeline_start_frame": lift_start,
                "timeline_end_frame": lift_end,
                "duration_seconds": round((lift_end - lift_start) / fps, 3),
                "item_name": item.get("item_name"),
                "item_index": item_index,
                "source_lift_seconds": [round(strip_start, 3), round(strip_end, 3)],
                "rationale": (
                    f"Waveform silence {round(strip_start, 2)}s–{round(strip_end, 2)}s "
                    f"(threshold {round(float(item_threshold), 1)} dB, min {min_strip_frames} frames)."
                ),
                "evidence": {
                    "basis": "ffmpeg_silencedetect",
                    "threshold_db": round(float(item_threshold), 2),
                    "threshold_source": "explicit" if threshold_db is not None else "calibrated",
                    "calibration": spec.get("calibration"),
                    "source_gap_seconds": [round(strip_start, 3), round(strip_end, 3)],
                },
            })

    skipped = _dedupe_skipped(skipped)
    if not lifts:
        return {
            "success": False,
            "error": "No silence regions found above threshold",
            "skipped": skipped,
            "note": (
                f"threshold_db={'auto-calibrated per item' if threshold_db is None else threshold_db}, "
                f"min_strip_frames={min_strip_frames}; items without readable file paths carry no "
                "waveform evidence, and items whose gate could not be calibrated were kept whole "
                "rather than stripped against an unvalidated threshold (both — see skipped)."
            ),
            "calibrations": [
                {"item": s["item"].get("item_name"), **s["calibration"]}
                for s in item_specs
                if s.get("calibration")
            ],
        }

    lifts.sort(key=lambda l: -l["timeline_start_frame"])

    keep_ranges: List[Dict[str, Any]] = []
    for spec in item_specs:
        item = spec["item"]
        clip_fps = spec["clip_fps"]
        audio_indices: List[int] = []
        if include_audio:
            audio_indices = [int(i) for i in (item.get("audio_track_indices") or []) if int(i) > 0]
            if not audio_indices:
                audio_indices = [1]
        for seg_start, seg_end in spec.get("keep_segments") or []:
            start_frame = int(round(seg_start * clip_fps))
            end_frame = max(start_frame + 1, int(round(seg_end * clip_fps)))
            keep_ranges.append({
                "clip_id": spec["resolve_clip_id"],
                "start_frame": start_frame,
                "end_frame": end_frame,
                "track_type": "video",
                "track_index": int(item.get("track_index") or 1),
            })
            for audio_index in audio_indices:
                keep_ranges.append({
                    "clip_id": spec["resolve_clip_id"],
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "track_type": "audio",
                    "media_type": 2,
                    "track_index": audio_index,
                })

    removed_frames = sum(l["timeline_end_frame"] - l["timeline_start_frame"] for l in lifts)
    audio_keep_range_count = sum(1 for r in keep_ranges if r.get("track_type") == "audio")
    video_keep_range_count = len(keep_ranges) - audio_keep_range_count

    # A tighten optimizes for removing silence and knows nothing about the media
    # colour, VFX and sound need either side of a join. Surface it at plan time
    # rather than letting it be discovered after picture lock.
    handle_report = _edit_handles_mod.check_keep_range_handles(
        keep_ranges,
        source_bounds={
            spec["resolve_clip_id"]: spec["source_total_frames"]
            for spec in item_specs
            if spec.get("resolve_clip_id") and spec.get("source_total_frames")
        },
    )
    plan = save_plan(project_root, {
        "kind": "silence_ripple",
        "handle_report": handle_report,
        "timeline_name": timeline_name,
        "timeline_fps": fps,
        "lifts": lifts,
        "keep_ranges": keep_ranges,
        "include_audio": bool(include_audio),
        "skipped": skipped,
        "summary": (
            f"{len(lifts)} silence strips, ~{round(removed_frames / fps, 1)}s removed "
            f"from '{timeline_name}' (waveform ripple-delete variant"
            f"{', video + audio' if include_audio else ', video only'})"
        ),
        "settings": {
            "threshold_db": threshold_db,
            "threshold_source": "explicit" if threshold_db is not None else "calibrated_per_item",
            "min_strip_frames": min_strip_frames,
            "pre_head_frames": pre_head_frames,
            "post_tail_frames": post_tail_frames,
            "include_audio": bool(include_audio),
        },
        "calibrations": [
            {"item": s["item"].get("item_name"), **s["calibration"]}
            for s in item_specs
            if s.get("calibration")
        ],
    })
    result = {
        "success": True,
        "status": "plan_ready",
        "plan_id": plan["plan_id"],
        "kind": "silence_ripple",
        "timeline_name": timeline_name,
        "lift_count": len(lifts),
        "estimated_removed_seconds": round(removed_frames / fps, 2),
        "lifts": lifts,
        "keep_range_count": len(keep_ranges),
        "video_keep_range_count": video_keep_range_count,
        "audio_keep_range_count": audio_keep_range_count,
        "include_audio": bool(include_audio),
        "skipped": skipped,
        "handle_report": handle_report,
        "note": (
            "Dry-run plan. Execute with edit_engine(action='execute_silence_ripple', "
            "params={plan_id}) — a tightened VARIANT timeline is assembled from "
            "waveform silence detection; the original timeline is never mutated. "
            "Tune threshold_db / min_strip_frames to match Resolve's "
            "Ripple Delete Silence dialog."
        ),
    }
    if video_keep_range_count == 0:
        result["warning"] = (
            "Plan removes ALL planned content (no keep ranges survived) — "
            "the source audio may be quieter than threshold_db throughout. "
            "Check the threshold before executing; execution will refuse this plan."
        )
    return result


# ── E2b: dead space, marked for review ───────────────────────────────────────

#: Resolve marker colours. Red reads as "look here" and is what editors reach
#: for when asking to be shown something before agreeing to it.
DEAD_SPACE_MARKER_COLOR = "Red"
DEAD_SPACE_UNCERTAIN_MARKER_COLOR = "Yellow"

#: Separation above the usability floor below which a gate is "usable but only
#: just". Speech and room are close together at that point, so the detection is
#: correct-in-principle and worth a human's eye before it is acted on.
MARGINAL_SEPARATION_MARGIN_DB = 6.0


def _calibration_is_marginal(calibration) -> bool:
    """True when a calibrated gate barely cleared its own credibility floor.

    Returns False for an explicit caller-supplied threshold (nothing was
    calibrated, so there is no confidence to report) and for digital silence
    (unambiguous by construction).
    """
    if calibration is None or not getattr(calibration, "usable", False):
        return False
    separation = getattr(calibration, "separation_db", None)
    if separation is None or not math.isfinite(separation):
        return False
    floor = _silence_ripple_mod.MIN_SEPARATION_DB
    return separation < floor + MARGINAL_SEPARATION_MARGIN_DB


def plan_dead_space_markers(
    project_root: str,
    *,
    items: Sequence[Dict[str, Any]],
    timeline_name: str,
    timeline_fps: float,
    threshold_db: Optional[float] = None,
    tightness: Optional[str] = None,
    min_strip_frames: float = DEFAULT_SILENCE_MIN_STRIP_FRAMES,
    pre_head_frames: float = DEFAULT_SILENCE_PRE_HEAD_FRAMES,
    post_tail_frames: float = DEFAULT_SILENCE_POST_TAIL_FRAMES,
) -> Dict[str, Any]:
    """Find dead space and propose MARKERS for a human to review — cut nothing.

    Why this exists as its own verb rather than a flag on `plan_silence_ripple`:

    An editor asked to be shown the gaps before agreeing to lose them — "mark
    all the spots with dead space with a red marker so I can review, and then
    I'll approve" — which is the review gate this project's own guidance
    recommends. There was no tool for it. `plan_silence_ripple` is calibrated
    and correct but its output is a tightened *variant timeline*, and
    `media_analysis`'s marker plan marks *shots on a clip*, not dead space on a
    timeline. With nothing to call, an agent asked to do this improvises its own
    detection and places markers by hand — which is exactly what happened, and
    the markers landed on "pretty random spots" while missing the obvious gaps.

    The detection here is deliberately the *same* calibrated gate as the ripple
    path, so what you review is what you would get. The difference is only that
    this proposes an annotation instead of an edit.
    """
    if not items:
        return {"success": False, "error": "No timeline items supplied"}
    fps = float(timeline_fps) if timeline_fps and float(timeline_fps) > 0 else 24.0

    try:
        scaled = _silence_ripple_mod.apply_tightness(
            tightness=tightness,
            pre_head_frames=pre_head_frames,
            post_tail_frames=post_tail_frames,
            min_strip_frames=min_strip_frames,
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    min_strip_sec = _silence_ripple_mod.frames_to_seconds(scaled["min_strip_frames"], fps)
    pre_head_sec = _silence_ripple_mod.frames_to_seconds(scaled["pre_head_frames"], fps)
    post_tail_sec = _silence_ripple_mod.frames_to_seconds(scaled["post_tail_frames"], fps)
    conn = timeline_brain_db.connect(project_root)

    markers: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    calibrations: List[Dict[str, Any]] = []
    total_dead_frames = 0

    for item_index, item in enumerate(items):
        try:
            tl_start = int(item["timeline_start_frame"])
            tl_end = int(item["timeline_end_frame"])
            src_start_frame = int(item.get("source_start_frame") or 0)
        except (KeyError, TypeError, ValueError):
            skipped.append({"item": item.get("item_name"), "reason": "missing frame fields"})
            continue

        clip_uuid = analysis_store.resolve_clip_uuid(conn, item.get("media_ref"))
        if not clip_uuid:
            clip_uuid = analysis_store.resolve_clip_uuid(conn, item.get("media_path"))
        clip_fps = fps
        if clip_uuid:
            clip_row = conn.execute(
                "SELECT * FROM clips WHERE clip_uuid = ?", (clip_uuid,)
            ).fetchone()
            if clip_row:
                clip_fps = _clip_fps(dict(clip_row))

        src_start_sec = src_start_frame / clip_fps
        src_end_sec = src_start_sec + (tl_end - tl_start) / fps

        media_path = _resolve_media_path(conn, item)
        if not media_path:
            skipped.append({
                "item": item.get("item_name"),
                "reason": "no readable media file path — not analyzed, and therefore NOT marked clean",
            })
            continue
        if not _silence_ripple_mod.ffmpeg_available():
            return {
                "success": False,
                "error": (
                    "ffmpeg not found on PATH — waveform silence detection "
                    "requires ffmpeg (see media_analysis capabilities)"
                ),
            }

        item_threshold = threshold_db
        calibration = None
        if item_threshold is None:
            calibration = _silence_ripple_mod.calibrate_silence_gate(
                media_path, src_start_sec, src_end_sec
            )
            calibrations.append({"item": item.get("item_name"), **calibration.as_dict()})
            if not calibration.usable:
                # Not markable is not the same as no dead space. Saying nothing
                # here would read as "this item is clean", which is a lie by
                # omission on exactly the material most likely to need review.
                skipped.append({
                    "item": item.get("item_name"),
                    "reason": f"silence gate could not be calibrated — NOT analyzed: {calibration.reason}",
                    "calibration": calibration.as_dict(),
                })
                continue
            item_threshold = calibration.gate_db

        strip_regions, _keep = _silence_ripple_mod.plan_item_silence_strips(
            media_path,
            src_start_sec,
            src_end_sec,
            threshold_db=float(item_threshold),
            min_strip_sec=min_strip_sec,
            pre_head_sec=pre_head_sec,
            post_tail_sec=post_tail_sec,
        )

        for strip_start, strip_end in strip_regions:
            marker_start = tl_start + int(round((strip_start - src_start_sec) * fps))
            marker_end = tl_start + int(round((strip_end - src_start_sec) * fps))
            duration = max(1, marker_end - marker_start)
            total_dead_frames += duration
            seconds = round(duration / fps, 2)
            # A gate that only just cleared the separation floor is a usable
            # gate, not a confident one — speech and room are nearly the same
            # level here, so these regions deserve a second look rather than the
            # same red as an unambiguous hole. Yellow says "probably, check me".
            uncertain = _calibration_is_marginal(calibration)
            markers.append({
                "timeline_start_frame": marker_start,
                "duration_frames": duration,
                "color": DEAD_SPACE_UNCERTAIN_MARKER_COLOR if uncertain else DEAD_SPACE_MARKER_COLOR,
                "name": f"Dead space {seconds}s",
                "note": (
                    f"{seconds}s below {round(float(item_threshold), 1)} dB in "
                    f"{item.get('item_name') or 'item'} "
                    f"({'auto-calibrated' if threshold_db is None else 'explicit'} gate, "
                    f"tightness={scaled['tightness']}). "
                    f"Guards: {scaled['pre_head_frames']:.0f} frames kept before, "
                    f"{scaled['post_tail_frames']:.0f} after, so speech either side is untouched."
                ),
                "item_name": item.get("item_name"),
                "item_index": item_index,
                "source_gap_seconds": [round(strip_start, 3), round(strip_end, 3)],
                "evidence": {
                    "basis": "ffmpeg_silencedetect",
                    "threshold_db": round(float(item_threshold), 2),
                    "threshold_source": "explicit" if threshold_db is not None else "calibrated",
                },
            })

    skipped = _dedupe_skipped(skipped)
    markers.sort(key=lambda m: m["timeline_start_frame"])

    return {
        "success": True,
        "kind": "dead_space_markers",
        "timeline_name": timeline_name,
        "timeline_fps": fps,
        "tightness": scaled["tightness"],
        "marker_count": len(markers),
        "total_dead_seconds": round(total_dead_frames / fps, 2),
        "markers": markers,
        "calibrations": calibrations,
        "skipped": skipped,
        "analyzed_item_count": len(items) - len(skipped),
        "note": (
            "Review-only. NOTHING is cut and no marker has been written yet — write "
            "them with timeline_markers, delete the ones you disagree with, then "
            "tighten. Detection is the same calibrated gate as "
            "plan_silence_ripple, so what you see marked here is what that would "
            "remove at this tightness. Items in `skipped` were NOT analyzed and are "
            "not certified clean."
        ),
    }


# ── E3: swap alternates ──────────────────────────────────────────────────────


def plan_swap(
    project_root: str,
    *,
    item: Dict[str, Any],
    timeline_name: str,
    timeline_fps: float,
    kind: str = "visual",
    limit: int = 5,
) -> Dict[str, Any]:
    """Rank alternate shots for one timeline item via the similarity index.

    `item` comes from the server: {timeline_start_frame, timeline_end_frame,
    source_start_frame, media_ref, item_name?, track_index?}.
    """
    from src.utils import embeddings

    conn = timeline_brain_db.connect(project_root)
    clip_uuid = analysis_store.resolve_clip_uuid(
        conn, item.get("media_ref")
    ) or analysis_store.resolve_clip_uuid(conn, item.get("media_path"))
    if not clip_uuid:
        return {"success": False, "error": "No analysis for the item's source media (db_ingest or analyze first)"}
    clip_row = conn.execute("SELECT * FROM clips WHERE clip_uuid = ?", (clip_uuid,)).fetchone()
    clip_fps = _clip_fps(dict(clip_row)) if clip_row else 24.0
    fps = float(timeline_fps) if timeline_fps and float(timeline_fps) > 0 else 24.0
    try:
        tl_start = int(item["timeline_start_frame"])
        tl_end = int(item["timeline_end_frame"])
        src_start_frame = int(item.get("source_start_frame") or 0)
    except (KeyError, TypeError, ValueError):
        return {"success": False, "error": "item requires timeline_start_frame/timeline_end_frame/source_start_frame"}
    src_mid_sec = src_start_frame / clip_fps + ((tl_end - tl_start) / fps) / 2.0
    shot_row = conn.execute(
        """
        SELECT * FROM shots
        WHERE clip_uuid = ? AND time_seconds_start <= ? AND time_seconds_end > ?
        """,
        (clip_uuid, src_mid_sec, src_mid_sec),
    ).fetchone()
    if not shot_row:
        return {"success": False, "error": f"No analyzed shot covers source time {round(src_mid_sec, 2)}s"}
    shot = dict(shot_row)

    found = embeddings.find_similar(
        project_root,
        shot_uuid=shot["shot_uuid"],
        kind=kind,
        entity_types=["shot"],
        limit=int(limit) * 2,
    )
    if not found.get("success"):
        return found
    duration_frames = tl_end - tl_start
    needed_seconds = duration_frames / fps

    # Vision-confirmed alt takes outrank raw cosine similarity (spec §4).
    from src.utils import shot_relationships as _shot_relationships
    confirmed_alts = set(_shot_relationships.confirmed_alt_take_shot_uuids(conn, shot["shot_uuid"]))

    def _viable_alternate(
        *, clip_uuid: Any, shot_uuid_: Any, shot_index: Any, description: Any,
        alt_start: Any, alt_end: Any, score: Any, rationale: str,
    ) -> Optional[Dict[str, Any]]:
        alt_clip = conn.execute(
            "SELECT * FROM clips WHERE clip_uuid = ?", (clip_uuid,)
        ).fetchone()
        if not alt_clip or not alt_clip["resolve_clip_id"]:
            return None
        if alt_start is None or alt_end is None:
            return None
        if (float(alt_end) - float(alt_start)) < needed_seconds:
            return None  # alternate too short to fill the slot
        alt = dict(alt_clip)
        alt_fps = _clip_fps(alt)
        start_frame = int(round(float(alt_start) * alt_fps))
        # Half-open (exclusive) endFrame — duration = end - start fills the slot
        # exactly. No -1, else the replacement lands one frame short of the slot.
        end_frame = start_frame + int(round(needed_seconds * alt_fps))
        return {
            "score": score,
            "clip_uuid": clip_uuid,
            "clip_name": alt.get("clip_name"),
            "resolve_clip_id": alt["resolve_clip_id"],
            "shot_uuid": shot_uuid_,
            "shot_index": shot_index,
            "description": description,
            "source_frame_range": [start_frame, end_frame],
            "confirmed_alt_take": str(shot_uuid_) in confirmed_alts,
            "rationale": rationale,
        }

    alternates: List[Dict[str, Any]] = []
    seen_shot_uuids: set = set()
    for hit in found.get("results") or []:
        hit_uuid = str(hit.get("entity_uuid"))
        is_confirmed = hit_uuid in confirmed_alts
        basis = (
            f"vision-confirmed alt_take_of relationship (cosine {hit.get('score')} agrees)"
            if is_confirmed
            else f"cosine {hit.get('score')} to the current shot ({kind} embedding)"
        )
        alternate = _viable_alternate(
            clip_uuid=hit.get("clip_uuid"), shot_uuid_=hit.get("entity_uuid"),
            shot_index=hit.get("shot_index"), description=hit.get("description"),
            alt_start=hit.get("time_seconds_start"), alt_end=hit.get("time_seconds_end"),
            score=hit.get("score"),
            rationale=f"{basis}; long enough to fill the slot exactly",
        )
        if alternate:
            alternates.append(alternate)
            seen_shot_uuids.add(hit_uuid)
    # Confirmed alt takes the cosine search missed still belong in the list.
    for alt_uuid in confirmed_alts - seen_shot_uuids:
        alt_shot = conn.execute("SELECT * FROM shots WHERE shot_uuid = ?", (alt_uuid,)).fetchone()
        if not alt_shot:
            continue
        alt_shot = dict(alt_shot)
        alternate = _viable_alternate(
            clip_uuid=alt_shot.get("clip_uuid"), shot_uuid_=alt_uuid,
            shot_index=alt_shot.get("shot_index"), description=alt_shot.get("description"),
            alt_start=alt_shot.get("time_seconds_start"), alt_end=alt_shot.get("time_seconds_end"),
            score=None,
            rationale="vision-confirmed alt_take_of relationship (not surfaced by the cosine search); long enough to fill the slot exactly",
        )
        if alternate:
            alternates.append(alternate)
    alternates.sort(key=lambda a: (not a.get("confirmed_alt_take"), -(a.get("score") or 0.0)))
    alternates = alternates[: int(limit)]
    if not alternates:
        return {
            "success": False,
            "error": "No viable alternates (similar shots were too short or their clips are not in this Resolve project)",
        }

    plan = save_plan(project_root, {
        "kind": "swap",
        "timeline_name": timeline_name,
        "timeline_fps": fps,
        "item": {
            "timeline_start_frame": tl_start,
            "timeline_end_frame": tl_end,
            "track_index": item.get("track_index") or 1,
            "item_name": item.get("item_name"),
            "current_shot_uuid": shot["shot_uuid"],
            "current_description": shot.get("description"),
        },
        "alternates": alternates,
        "summary": (
            f"{len(alternates)} alternates for '{item.get('item_name') or 'item'}' "
            f"on '{timeline_name}' (slot {tl_start}-{tl_end})"
        ),
    })
    return {
        "success": True,
        "status": "plan_ready",
        "plan_id": plan["plan_id"],
        "kind": "swap",
        "timeline_name": timeline_name,
        "current_shot": {
            "shot_uuid": shot["shot_uuid"],
            "shot_index": shot["shot_index"],
            "description": shot.get("description"),
        },
        "alternates": alternates,
        "note": (
            "Dry-run plan. Execute with edit_engine(action='execute_swap', "
            "params={plan_id, alternate_index}) — the item is replaced on a "
            "version-archived timeline (lift + positioned append, same slot)."
        ),
    }


# ── transcript-driven editing (word level) ───────────────────────────────────


def rule_of_six_audit(
    *,
    items: Sequence[Dict[str, Any]],
    timeline_name: str,
    timeline_fps: float,
    story_beats: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Audit a timeline against the Rule of Six.

    Computes what is computable (currently rhythm, 10%) and abstains loudly on
    emotion (51%) and story (23%), which are not measurable and never will be.
    Criteria this build does not yet compute report `NOT_IMPLEMENTED` — never a
    pass.
    """
    from src.utils import rhythm_audit as _rhythm
    from src.utils import rule_of_six as _six

    if not items:
        return {"success": False, "error": "No timeline items supplied"}
    fps = float(timeline_fps) if timeline_fps and float(timeline_fps) > 0 else 24.0

    rhythm = _rhythm.assess(items, fps=fps, story_beats=story_beats or [])
    audit = _six.audit(
        timeline_name=timeline_name,
        criterion_results={"rhythm": rhythm},
        findings=rhythm.get("findings") or [],
    )
    audit["rhythm"] = {
        "shot_count": len(rhythm.get("shots") or []),
        "cut_density": rhythm.get("cut_density"),
        "motivated_breaks": rhythm.get("motivated_breaks") or [],
        "beats_supplied": rhythm.get("beats_supplied", 0),
    }
    return audit


def sound_density_audit(
    *,
    track_media: Mapping[str, str],
    stream_limit: Optional[float] = None,
    duration_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """The two-and-a-half rule over a set of audio stems.

    **Honest limit:** this measures the files it is given, so it is only as
    timeline-accurate as those files are. Rendered stems (dialogue / music /
    effects) give a true reading; raw source clips give a reading of the sources,
    which is useful for spotting a crowded mix but is not the timeline. The
    result says which it got.
    """
    from src.utils import sound_density as _density

    if not track_media:
        return {
            "success": False,
            "error": "No audio supplied.",
            "remediation": (
                "Pass track_media as {name: path} — ideally rendered stems "
                "(dialogue/music/effects). Counting tracks without measuring them "
                "cannot tell a competing stream from a bed, and guessing would make "
                "every mixed timeline fail."
            ),
        }

    measured = _density.measure_track_levels(
        dict(track_media), duration_seconds=duration_seconds
    )
    if not measured.get("success"):
        return measured

    kwargs: Dict[str, Any] = {}
    if stream_limit is not None:
        kwargs["stream_limit"] = float(stream_limit)
    result = _density.audit(measured["samples"], **kwargs)
    result["measured_streams"] = sorted(track_media)
    result["source_caveat"] = (
        "Measured from the supplied files. If these are rendered stems this is the "
        "timeline; if they are source clips it is a reading of the sources, not of "
        "the mix."
    )
    return result


def setup_sheet(
    *,
    items: Sequence[Dict[str, Any]],
    timeline_name: str,
    timeline_fps: float,
) -> Dict[str, Any]:
    """One representative frame per camera setup, ordered by first appearance."""
    from src.utils import setup_sheet as _sheet

    fps = float(timeline_fps) if timeline_fps and float(timeline_fps) > 0 else 24.0
    result = _sheet.select_representatives(items, fps=fps)
    result["timeline_name"] = timeline_name
    return result


def split_edit_audit(
    *,
    video_items: Sequence[Dict[str, Any]],
    audio_items: Sequence[Dict[str, Any]],
    timeline_fps: float,
) -> Dict[str, Any]:
    """Sound leads picture: classify every join as L-cut, J-cut or straight."""
    from src.utils import split_edits as _split

    fps = float(timeline_fps) if timeline_fps and float(timeline_fps) > 0 else 24.0
    return _split.audit(video_items, audio_items, fps=fps)


def plan_beat_cuts(
    project_root: str,
    *,
    clip_ref: Any = None,
    media_path: Optional[str] = None,
    timeline_fps: float = 24.0,
    mode: str = "phrase",
    beats_per_bar: int = 4,
    bars_per_phrase: int = 8,
    beat_offset: int = 0,
    min_shot_seconds: float = 0.0,
) -> Dict[str, Any]:
    """Cut points from the music's own pulse, for footage with no speech.

    The speech tools here find edit points in words and pauses. Music has
    neither, and pointing a silence gate at it produces exactly the failure a
    motorsport editor predicted before trying it: engine noise reads as content,
    quiet reads as dead space, and the cuts land nowhere near the music.
    """
    from src.utils import beat_detection as _beats

    path = media_path
    if not path and clip_ref is not None:
        conn = timeline_brain_db.connect(project_root)
        path = _resolve_media_path(conn, {"media_ref": clip_ref, "media_path": clip_ref})
    if not path:
        return {
            "success": False,
            "error": "Supply media_path, or a clip_ref that resolves to readable media.",
        }

    detected = _beats.detect_beats(path)
    if not detected.get("success"):
        return detected

    try:
        plan = _beats.plan_beat_cuts(
            detected["beats"],
            fps=float(timeline_fps) if timeline_fps else 24.0,
            mode=mode,
            beats_per_bar=int(beats_per_bar),
            bars_per_phrase=int(bars_per_phrase),
            beat_offset=int(beat_offset),
            min_shot_seconds=float(min_shot_seconds),
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    plan["media_path"] = path
    plan["tempo_bpm"] = detected["tempo_bpm"]
    plan["detection_confidence"] = detected["confidence"]
    if detected["confidence"]["band"] == "low":
        plan["warning"] = (
            "Beat tracking confidence is LOW — " + detected["confidence"]["reason"]
            + ". Check several cuts against the music before assembling."
        )
    return plan


def plan_prebalance(
    project_root: str,
    *,
    items: Sequence[Dict[str, Any]],
    timeline_name: str,
    timeline_fps: float,
    max_items: int = 200,
) -> Dict[str, Any]:
    """Measure levels per timeline item and propose a neutral pre-balance.

    Grouping proxy: Resolve does not expose "lighting setup", so items are
    grouped by reel name where present and by containing folder otherwise —
    both usually track a camera roll, which usually tracks a setup. It is a
    proxy and the result says so; a colorist regrouping by eye will beat it.
    """
    from src.utils import prebalance as _prebalance

    if not items:
        return {"success": False, "error": "No timeline items supplied"}
    fps = float(timeline_fps) if timeline_fps and float(timeline_fps) > 0 else 24.0
    conn = timeline_brain_db.connect(project_root)

    clips: List[Dict[str, Any]] = []
    unreadable: List[Dict[str, Any]] = []
    for item in items[:max_items]:
        media_path = _resolve_media_path(conn, item)
        name = item.get("item_name") or "(unnamed)"
        start = item.get("timeline_start_frame") or 0
        end = item.get("timeline_end_frame") or start
        duration = max(0.0, (end - start) / fps)
        if not media_path:
            unreadable.append({"clip": name, "reason": "no readable media path — NOT measured"})
            continue
        # Sample the middle of the used range: heads and tails catch fades,
        # slates and handles, none of which represent the shot.
        source_start = float(item.get("source_start_frame") or 0) / fps
        reading = _prebalance.measure_frame_levels(media_path, source_start + duration / 2.0)
        if not reading.get("success"):
            unreadable.append({"clip": name, "reason": reading.get("error") or "levels unreadable"})
            continue
        setup = item.get("reel_name") or os.path.basename(os.path.dirname(media_path)) or "ungrouped"
        clips.append({
            "name": name,
            "duration_seconds": round(duration, 2),
            "setup": setup,
            "levels": reading["levels"],
        })

    if not clips:
        return {
            "success": False,
            "error": "No timeline items could be measured.",
            "unreadable": unreadable,
            "remediation": "Check media is online and ffmpeg is on PATH.",
        }

    result = _prebalance.plan_prebalance(clips)
    result["timeline_name"] = timeline_name
    result["grouping_basis"] = "reel name where present, else containing folder (a PROXY for lighting setup)"
    if unreadable:
        result.setdefault("unanalyzed", []).extend(unreadable)
    if len(items) > max_items:
        result["truncated"] = (
            f"Measured the first {max_items} of {len(items)} items. The remainder "
            "were NOT measured and are not certified balanced — raise max_items."
        )
    return result


def plan_reference_match(
    project_root: str,
    *,
    reference_media: str,
    reference_at_seconds: float = 0.0,
    items: Sequence[Dict[str, Any]],
    timeline_fps: float,
    max_items: int = 200,
) -> Dict[str, Any]:
    """Match timeline clips to a graded reference still.

    Same measurement path as `plan_prebalance`, aimed at a reference instead of
    at neutral. END POINTS ONLY — it does not transfer the reference's grade.
    """
    from src.utils import prebalance as _prebalance
    from src.utils import reference_match as _refmatch

    if not items:
        return {"success": False, "error": "No timeline items supplied"}
    reference = _prebalance.measure_frame_levels(reference_media, reference_at_seconds)
    if not reference.get("success"):
        return {"success": False, "error": f"reference unreadable: {reference.get('error')}"}

    fps = float(timeline_fps) if timeline_fps and float(timeline_fps) > 0 else 24.0
    conn = timeline_brain_db.connect(project_root)
    targets: List[Dict[str, Any]] = []
    for item in items[:max_items]:
        media_path = _resolve_media_path(conn, item)
        name = item.get("item_name") or "(unnamed)"
        if not media_path:
            targets.append({"name": name})
            continue
        start = item.get("timeline_start_frame") or 0
        end = item.get("timeline_end_frame") or start
        source_start = float(item.get("source_start_frame") or 0) / fps
        reading = _prebalance.measure_frame_levels(
            media_path, source_start + max(0.0, (end - start) / fps) / 2.0
        )
        targets.append({"name": name, "levels": reading.get("levels")} if reading.get("success")
                       else {"name": name})

    result = _refmatch.plan_reference_match(
        reference["levels"], targets, reference_name=os.path.basename(reference_media)
    )
    if len(items) > max_items:
        result["truncated"] = (
            f"Measured the first {max_items} of {len(items)} items; the remainder "
            "were NOT matched and are not certified matched."
        )
    return result


def plan_string_out(
    *,
    shots: Sequence[Dict[str, Any]],
    order: str = "chronological",
) -> Dict[str, Any]:
    """String-out for footage with no speech — shots and motion, not silence."""
    from src.utils import shot_assembly as _assembly
    return _assembly.plan_string_out(shots, order=order)


def propose_structure(*, topics: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """No-script mode: propose an order, require approval, cut nothing."""
    from src.utils import shot_assembly as _assembly
    return _assembly.propose_structure(topics)


def plan_broll(
    *,
    beats: Sequence[Dict[str, Any]],
    candidates: Sequence[Dict[str, Any]],
    allow_reuse: bool = False,
) -> Dict[str, Any]:
    """Place B-roll against A-roll beats. Relevance is the caller's, not ours."""
    from src.utils import broll_placement as _broll
    return _broll.place(beats, candidates, allow_reuse=allow_reuse)


def plan_turnover(
    *,
    destinations: Sequence[str],
    contents: Mapping[str, Any],
    version: str = "v01",
    handle_frames: Optional[int] = None,
) -> Dict[str, Any]:
    """Validate turnover manifests against their specs. Exports nothing."""
    from src.utils import turnover as _turnover
    return _turnover.plan_turnover(
        destinations, contents, version=version, handle_frames=handle_frames
    )


def rank_takes(
    project_root: str,
    *,
    clip_refs: Sequence[Any],
    script: Optional[str] = None,
) -> Dict[str, Any]:
    """Rank several clips as takes of the same material, by measurable fluency.

    Clips with no transcript are reported, not silently dropped — "not ranked"
    and "ranked last" are different facts and an editor needs to know which.
    """
    from src.utils import strata as _strata
    from src.utils import take_ranking as _take_ranking

    if not clip_refs:
        return {"success": False, "error": "No clip_refs supplied"}

    takes: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    for ref in clip_refs:
        conn, clip, err = _strata.resolve_clip(project_root, ref, require_media=False)
        if err:
            unavailable.append({"clip_ref": ref, "reason": err.get("error") or "clip not found"})
            continue
        words = _strata.read_words(conn, clip["clip_uuid"])
        if not words:
            unavailable.append({
                "clip_ref": ref,
                "clip_name": clip.get("clip_name"),
                "reason": "no transcript words — NOT ranked (run transcription first)",
            })
            continue
        takes.append({"label": clip.get("clip_name") or str(ref), "words": words})

    if not takes:
        return {
            "success": False,
            "error": "None of the supplied clips have transcript words to rank.",
            "unavailable": unavailable,
            "remediation": (
                "Run media_analysis transcription for these clips, then strata "
                "backfill_transcript_words, before ranking takes."
            ),
        }

    result = _take_ranking.rank_takes(takes, script=script)
    result["unavailable"] = unavailable
    if unavailable:
        result["note"] = (
            f"{len(unavailable)} of {len(clip_refs)} clips could not be ranked "
            "(no transcript) and are listed in `unavailable` — they are absent "
            "from the ranking, not last in it. " + str(result.get("note") or "")
        )
    return result


def plan_transcript_tighten(
    project_root: str,
    *,
    clip_ref: Any,
    remove_fillers: bool = True,
    remove_false_starts: bool = True,
    collapse_pauses: bool = True,
    max_pause: float = _transcript_edit_mod.DEFAULT_MAX_PAUSE_S,
    handle: float = _transcript_edit_mod.DEFAULT_HANDLE_S,
    min_cut: float = _transcript_edit_mod.DEFAULT_MIN_CUT_S,
) -> Dict[str, Any]:
    """Word-level tightening for one clip: fillers, false starts, long pauses.

    Complementary to `plan_silence_ripple`, which is silence-driven and cannot
    touch an audible "um" mid-phrase. Emits `keep_ranges` in the same shape, so
    the existing variant assembler consumes either without changes.
    """
    from src.utils import strata as _strata

    conn, clip, err = _strata.resolve_clip(project_root, clip_ref, require_media=False)
    if err:
        return {"success": False, **err}
    words = _strata.read_words(conn, clip["clip_uuid"])
    if not words:
        return {
            "success": False,
            "error": "No transcript words for this clip.",
            "remediation": (
                "Run media_analysis transcription for the clip, then strata "
                "backfill_transcript_words, before planning a word-level tighten."
            ),
            "clip": {"clip_uuid": clip["clip_uuid"], "clip_name": clip.get("clip_name")},
        }
    plan = _transcript_edit_mod.plan_transcript_cuts(
        words,
        remove_fillers=remove_fillers,
        remove_false_starts=remove_false_starts,
        collapse_pauses=collapse_pauses,
        max_pause=max_pause,
        handle=handle,
        min_cut=min_cut,
    )
    plan["clip"] = {
        "clip_uuid": clip["clip_uuid"],
        "clip_name": clip.get("clip_name"),
        "word_count": len(words),
    }
    plan["basis"] = "transcript_words"
    # I3: a word-level tighten breaks a turnover exactly like a waveform-driven
    # one does. Deciding the cut from a transcript rather than a waveform does
    # not give sound anything to crossfade with.
    duration = clip.get("duration_seconds")
    plan["handle_report"] = _edit_handles_mod.check_seconds_ranges(
        plan.get("keep_ranges") or [],
        source_duration_seconds=float(duration) if isinstance(duration, (int, float)) and duration else None,
    )
    # The class this planner is structurally blind to. Its false-start heuristic
    # only sees restarts the transcript actually reports; an immediate re-read is
    # emitted ONCE with the pause and second take absorbed into one word, so the
    # plan cannot propose removing what it was never told happened (issue #125).
    from src.utils import swallowed_retakes as _swallowed
    plan["possible_swallowed_retakes"] = _swallowed.swallowed_retake_report(words)
    return plan


def search_spoken_content(
    project_root: str,
    *,
    query: str,
    mode: str = "phrase",
    context_seconds: float = 1.5,
    handle_seconds: float = 0.5,
    max_hits: int = 200,
) -> Dict[str, Any]:
    """Search the spoken content of every transcribed clip; build selects.

    A different axis from `find_similar`, which retrieves on semantic-visual
    embedding. This finds *what was said*, which no embedding search surfaces
    reliably, and returns hits in deterministic order (clip name, then time) so
    two identical searches produce identical selects.
    """
    from src.utils import strata as _strata

    conn = timeline_brain_db.connect(project_root)
    rows = conn.execute(
        "SELECT clip_uuid, clip_name, file_path FROM clips ORDER BY clip_name COLLATE NOCASE"
    ).fetchall()
    if not rows:
        return {"success": False, "error": "No clips in the DB — analyze (or db_ingest) first."}

    hits: List[Dict[str, Any]] = []
    searched: List[str] = []
    without_speech: List[Dict[str, str]] = []
    for row in rows:
        clip = dict(row)
        words = _strata.read_words(conn, clip["clip_uuid"])
        if not words:
            without_speech.append({
                "clip_uuid": clip["clip_uuid"],
                "clip_name": clip.get("clip_name"),
                "reason": "no transcript words",
            })
            continue
        searched.append(clip.get("clip_name") or clip["clip_uuid"])
        try:
            found = _transcript_edit_mod.search_words(
                words, query, mode=mode, context_seconds=context_seconds
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        for hit in found:
            hits.append({
                **hit,
                "clip_uuid": clip["clip_uuid"],
                "clip_name": clip.get("clip_name"),
                "file_path": clip.get("file_path"),
            })

    truncated = len(hits) > max_hits
    hits = hits[:max_hits]
    selects = [
        {
            "clip_uuid": hit["clip_uuid"],
            "clip_name": hit["clip_name"],
            "in_seconds": round(max(0.0, hit["start_seconds"] - handle_seconds), 3),
            "out_seconds": round(hit["end_seconds"] + handle_seconds, 3),
            "text": hit["text"],
        }
        for hit in hits
    ]
    return {
        "success": True,
        "query": query,
        "mode": mode,
        "hit_count": len(hits),
        "truncated": truncated,
        "hits": hits,
        "selects": selects,
        "handle_seconds": handle_seconds,
        "clips_searched": searched,
        "clips_without_speech": without_speech,
        "note": (
            "Proposal only — selects are in/out pairs in clip-relative seconds, ordered "
            "by clip name then time so an identical search yields an identical list."
        ),
    }
