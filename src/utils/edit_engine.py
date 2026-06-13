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
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.utils import analysis_memory, analysis_store, timeline_brain_db

PLAN_DIR_NAME = "edit_plans"
DEFAULT_HANDLE_SECONDS = 0.25
DEFAULT_MIN_PAUSE_SECONDS = 1.5

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
        end_frame = max(start_frame + 1, int(round(src_end * fps)) - 1)
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
            end_frame = max(start_frame + 1, int(round(seg_end * clip_fps)) - 1)
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
        end_frame = start_frame + int(round(needed_seconds * alt_fps)) - 1
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
