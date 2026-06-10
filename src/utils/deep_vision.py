"""Deep shot-level vision tier (Phase B of the analysis program).

Fills the per-shot Visual / Content / Production / Editorial / Cuttability
field groups (v2 shot schema spec §3.2–3.8) via the same deferred-payload
host-vision pattern as standard analysis: the server prepares frames + a
schema, the host chat reads the frames and commits JSON back.

Two entry points share the schema:

- ``depth="deep"`` on analyze extends the single-pass payload (handled in
  media_analysis.build_host_chat_paths_payload via deep_shot_schema()).
- ``deepen`` is the post-hoc per-clip/per-shot pass for already-analyzed
  clips. It is estimate-first: the first call returns the frame/token cost
  and a confirm_token; the second call (with the token) returns the deferred
  payload. Both paths pass the caps pre-call refusal — confirmation never
  bypasses budgets.

Deep results commit via ``commit_shot_vision``: subjective rows are written
with source ``vision_deep_v1`` (human rows still win), the canonical report
blob is updated, and analysis.json re-exports in lockstep.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from src.utils import analysis_store, timeline_brain_db

DEEP_SHOT_SCHEMA_REFERENCE = "davinci_resolve_mcp.shot_deep_analysis.v1"
DEEP_SOURCE = "vision_deep_v1"

# Threshold above which a shot gets one extra extracted frame for the deep pass.
LONG_SHOT_SECONDS = 15.0

# Per-shot field groups (v2-shot-schema-spec §3.2–3.8). Values are the schema
# template shown to the host chat; enums are listed inline.
DEEP_SHOT_FIELD_GROUPS: Dict[str, Any] = {
    "visual": {
        "shot_size": "wide|medium_wide|medium|medium_close|close|extreme_close|insert|establishing|other",
        "framing": "single|two_shot|group|crowd|empty|insert|establishing|abstract",
        "camera_height": "eye_level|high_angle|low_angle|birds_eye|dutch|unknown",
        "camera_motion": "locked|pan|tilt|dolly|handheld|crane|drone|zoom|composite|other",
        "motion_direction": "left|right|up|down|in|out|clockwise|counter_clockwise|none",
        "depth_of_field": "deep|shallow|rack_focus|unknown",
        "lens_character": "wide|normal|tele|fisheye|unknown",
        "lighting": "natural|high_key|low_key|practical|backlit|silhouette|mixed|unknown",
        "color_mood": "warm|cool|neutral|desaturated|saturated|monochrome|unnatural|unknown",
        "composition_notes": "<short free text>",
    },
    "content": {
        "primary_subject": {
            "type": "person|object|landscape|interior|vehicle|animal|text_graphic|abstract",
            "description": "<one phrase>",
            "performance": "null unless type==person: {eye_line: to_camera|off_left|off_right|down|up|closed|unknown, energy: low|medium|high, emotional_register: <short free text>}",
        },
        "secondary_subjects": ["<[{type, description}]>"],
        "action": "<one sentence — what is happening>",
        "location": "<one sentence — where this is>",
        "visible_text": ["<readable on-screen text>"],
        "objects_of_note": ["<notable props/elements>"],
        "audio_character": "silence|sync_dialogue|vo_dialogue|music|ambient|sfx|mixed|unknown",
    },
    "production": {
        "composite_shot": "<bool — split-screen / PiP / multi-angle composite>",
        "composite_panels": "null unless composite_shot: [{region, primary_subject, action}]",
        "vfx_present": "none|minor|major|unknown",
    },
    "editorial": {
        "editorial_role": "establishing|coverage|reaction|insert|transition|b_roll|montage_element|titles_or_graphics|bumper|other",
        "select_potential": "low|medium|high",
        "best_moment": "null if the shot is a sustained flat beat, else {time_seconds, why}",
        "best_moment_present": "<bool>",
        "pacing": "still|moderate|kinetic|variable",
        "stillness_type": "held_tension|quiet|contemplative|transitional|dead_air|unknown — null unless pacing is still/variable",
        "pacing_note": "<free text or null — only when pacing is still/variable>",
    },
    "cuttability": {
        "cut_in": {"quality": "poor|ok|clean", "notes": "<short>"},
        "cut_out": {"quality": "poor|ok|clean", "notes": "<short>"},
        "match_action_in": "<bool — could receive a match cut>",
        "match_action_out": "<bool — could send a match cut>",
        "cut_compatibility_hints": "<free text>",
    },
    "description": "<1-3 sentences, editorially useful, colleague-style note>",
    "confidence": {
        "visual": "low|medium|high",
        "content": "low|medium|high",
        "audio": "low|medium|high",
        "editorial": "low|medium|high",
        "cuttability": "low|medium|high",
    },
}

DEEP_SHOT_PROMPT = (
    "Deep per-shot editorial analysis. For EACH shot listed in shot_table, look "
    "only at the frames whose indices appear in that shot's frame_indices and "
    "fill every field group in deep_shot_schema (visual, content, production, "
    "editorial, cuttability, description, confidence). Use the enum values "
    "verbatim; use 'unknown' or null when the frames do not support a claim — "
    "hedge identity/intent/value when frame evidence is thin. Return strict "
    "JSON only: {\"shots\": [{\"shot_index\": <int>, ...field groups...}]}."
)


def _ma():
    from src.utils import media_analysis

    return media_analysis


def deep_shot_schema() -> Dict[str, Any]:
    """The per-shot deep field groups (shared by deep-depth analyze + deepen)."""
    return json.loads(json.dumps(DEEP_SHOT_FIELD_GROUPS))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clip_context(project_root: str, clip_ref: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Resolve a clip to (context, error). Auto-ingests the JSON report when
    the DB has no rows yet (pre-v9 analysis roots)."""
    ma = _ma()
    conn = timeline_brain_db.connect(project_root)
    clip_uuid = analysis_store.resolve_clip_uuid(conn, clip_ref)
    if not clip_uuid:
        # Pre-v9 report? Find the analysis.json by walking clips/ and ingest it.
        clips_root = os.path.join(project_root, "clips")
        candidate = str(clip_ref or "")
        if os.path.isdir(clips_root):
            for entry in sorted(os.listdir(clips_root)):
                report_path = os.path.join(clips_root, entry, "analysis.json")
                if not os.path.isfile(report_path):
                    continue
                try:
                    with open(report_path, "r", encoding="utf-8") as handle:
                        report = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    continue
                clip_block = report.get("clip") or {}
                if candidate not in (
                    entry,
                    str(clip_block.get("clip_id") or ""),
                    str(clip_block.get("media_id") or ""),
                    ma.normalize_path(clip_block.get("file_path") or ""),
                ):
                    continue
                ingest = analysis_store.ingest_report(
                    project_root, report, clip_dir=os.path.join(clips_root, entry)
                )
                if ingest.get("success"):
                    clip_uuid = ingest["clip_uuid"]
                break
    if not clip_uuid:
        return None, f"No analyzed clip found for {clip_ref!r} (run db_ingest if this is an older analysis root)"
    clip_row = conn.execute("SELECT * FROM clips WHERE clip_uuid = ?", (clip_uuid,)).fetchone()
    shots = conn.execute(
        "SELECT * FROM shots WHERE clip_uuid = ? ORDER BY shot_index", (clip_uuid,)
    ).fetchall()
    frames = conn.execute(
        "SELECT * FROM frames WHERE clip_uuid = ? ORDER BY frame_index", (clip_uuid,)
    ).fetchall()
    if not shots:
        return None, "Clip has no detected shots — deep shot analysis needs a standard analysis with cut detection first"
    return {
        "clip_uuid": clip_uuid,
        "clip": dict(clip_row) if clip_row else {},
        "shots": [dict(s) for s in shots],
        "frames": [dict(f) for f in frames],
    }, None


def _select_shots(shots: List[Dict[str, Any]], shot_indices: Optional[List[int]]) -> Tuple[List[Dict[str, Any]], List[int]]:
    if not shot_indices:
        return shots, []
    wanted = {int(i) for i in shot_indices}
    selected = [s for s in shots if int(s["shot_index"]) in wanted]
    missing = sorted(wanted - {int(s["shot_index"]) for s in selected})
    return selected, missing


def _frames_for_shot(shot: Dict[str, Any], frames: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = [f for f in frames if f.get("shot_uuid") == shot["shot_uuid"]]
    if rows:
        return rows
    start, end = shot.get("time_seconds_start"), shot.get("time_seconds_end")
    if start is None or end is None:
        return []
    return [
        f for f in frames
        if f.get("time_seconds") is not None and start <= float(f["time_seconds"]) < end
    ]


def _extract_frame(source: str, time_seconds: float, out_path: str) -> Optional[str]:
    """Extract one frame with ffmpeg (read-only on source). None on failure."""
    ma = _ma()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    code, _out, _err = ma._run_command([
        "ffmpeg", "-y", "-ss", f"{max(0.0, time_seconds):.3f}", "-i", source,
        "-frames:v", "1", "-q:v", "3", out_path,
    ])
    if code != 0 or not os.path.isfile(out_path):
        return None
    try:
        from src.utils import analysis_caps

        caps = ma._resolve_active_caps()
        analysis_caps.downscale_frame_if_needed(out_path, caps.max_frame_dim_pixels)
    except Exception:
        pass
    return out_path


def _confirm_token_for(clip_uuid: str, shot_uuids: List[str]) -> str:
    return _ma().short_hash(f"deepen:{clip_uuid}:{','.join(sorted(shot_uuids))}", 16)


def _vision_token_for(clip_uuid: str, shot_uuids: List[str]) -> str:
    return _ma().short_hash(f"deep_vision:{clip_uuid}:{','.join(sorted(shot_uuids))}", 16)


def deepen_clip(
    project_root: str,
    *,
    clip_ref: Any,
    shot_indices: Optional[List[int]] = None,
    confirm_token: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Estimate-first deep pass over a clip (or selected shots).

    First call (no confirm_token) returns the cost estimate + confirm_token.
    Second call with the token returns the deferred host-vision payload.
    """
    ma = _ma()
    context, err = _clip_context(project_root, clip_ref)
    if err:
        return {"success": False, "error": err}
    clip_uuid = context["clip_uuid"]
    clip = context["clip"]
    shots, missing = _select_shots(context["shots"], shot_indices)
    if missing:
        return {"success": False, "error": f"shot_index not found: {missing}", "available": [s['shot_index'] for s in context['shots']]}
    if not shots:
        return {"success": False, "error": "No shots selected"}

    shot_uuids = [s["shot_uuid"] for s in shots]
    expected_confirm = _confirm_token_for(clip_uuid, shot_uuids)

    # Frame plan: existing on-disk frames per shot; shots with none get
    # extraction placeholders; long shots get one extra mid-late frame.
    source = clip.get("file_path")
    frame_plan: List[Dict[str, Any]] = []
    total_frames = 0
    for shot in shots:
        rows = _frames_for_shot(shot, context["frames"])
        on_disk = [r for r in rows if r.get("frame_path") and os.path.isfile(str(r["frame_path"]))]
        start = float(shot.get("time_seconds_start") or 0.0)
        end = float(shot.get("time_seconds_end") or start)
        duration = max(0.0, end - start)
        to_extract: List[float] = []
        if not on_disk:
            to_extract.append(start + duration / 2.0)
        if duration > LONG_SHOT_SECONDS:
            to_extract.append(start + duration * 2.0 / 3.0)
        count = len(on_disk) + len(to_extract)
        total_frames += count
        frame_plan.append({
            "shot_index": shot["shot_index"],
            "shot_uuid": shot["shot_uuid"],
            "existing_frames": len(on_disk),
            "frames_to_extract": len(to_extract),
            "extract_times": to_extract,
            "rows": on_disk,
        })

    estimated_tokens = total_frames * ma.AVG_VISION_TOKENS_PER_FRAME
    refusal = ma._check_caps_pre_call(
        project_root=project_root,
        estimated_vision_tokens=estimated_tokens,
        clip_id=clip.get("resolve_clip_id") or clip_uuid,
        job_id=job_id,
    )
    if refusal is not None:
        return refusal

    estimate = {
        "clip_uuid": clip_uuid,
        "clip_name": clip.get("clip_name"),
        "shot_count": len(shots),
        "frame_count": total_frames,
        "estimated_vision_tokens": estimated_tokens,
        "tokens_per_frame_assumption": ma.AVG_VISION_TOKENS_PER_FRAME,
    }

    if confirm_token != expected_confirm:
        return {
            "success": True,
            "status": "confirmation_required",
            "estimate": estimate,
            "confirm_token": expected_confirm,
            "note": (
                "Deep shot analysis is opt-in and costs vision tokens. Re-call "
                "media_analysis(action='deepen') with this confirm_token to "
                "proceed. Confirmation does not bypass caps."
            ),
        }

    # Confirmed: materialize missing frames, then build the deferred payload.
    clip_dir_name = clip.get("clip_dir")
    clip_dir = os.path.join(project_root, "clips", clip_dir_name) if clip_dir_name else None
    shot_table: List[Dict[str, Any]] = []
    frame_metadata: List[Dict[str, Any]] = []
    frame_paths: List[str] = []
    synthetic_index = 100000  # extraction-only frames get indices above sampled ones
    for plan in frame_plan:
        indices: List[int] = []
        for row in plan["rows"]:
            path = ma.normalize_path(str(row["frame_path"]))
            if path not in frame_paths:
                frame_paths.append(path)
                frame_metadata.append({
                    "frame_index": int(row["frame_index"]),
                    "frame_path": path,
                    "time_seconds": row.get("time_seconds"),
                    "selection_reason": row.get("selection_reason"),
                    "shot_index": plan["shot_index"],
                })
            indices.append(int(row["frame_index"]))
        for t in plan["extract_times"]:
            if not source or not os.path.isfile(source):
                continue
            if not clip_dir:
                continue
            out_path = os.path.join(clip_dir, "frames", f"deep_shot{int(plan['shot_index']):03d}_{int(t * 1000):08d}.jpg")
            extracted = out_path if os.path.isfile(out_path) else _extract_frame(source, t, out_path)
            if not extracted:
                continue
            synthetic_index += 1
            path = ma.normalize_path(extracted)
            frame_paths.append(path)
            frame_metadata.append({
                "frame_index": synthetic_index,
                "frame_path": path,
                "time_seconds": t,
                "selection_reason": "deep_pass_extraction",
                "shot_index": plan["shot_index"],
            })
            indices.append(synthetic_index)
        shot = next(s for s in shots if s["shot_index"] == plan["shot_index"])
        shot_table.append({
            "shot_index": int(shot["shot_index"]),
            "shot_uuid": shot["shot_uuid"],
            "time_seconds_start": shot.get("time_seconds_start"),
            "time_seconds_end": shot.get("time_seconds_end"),
            "current_description": shot.get("description"),
            "frame_indices": indices,
        })

    vision_token = _vision_token_for(clip_uuid, shot_uuids)
    commit_params: Dict[str, Any] = {
        "vision_token": vision_token,
        "shots": "<host chat: [{shot_index, ...deep_shot_schema groups...}]>",
        "analysis_root": project_root,
    }
    if clip.get("resolve_clip_id"):
        commit_params["clip_id"] = clip["resolve_clip_id"]
    elif clip_dir_name:
        commit_params["clip_dir"] = clip_dir_name

    return {
        "success": True,
        "status": "pending_host_analysis",
        "provider": "host_chat_paths",
        "mode": "deep_shots",
        "vision_token": vision_token,
        "estimate": estimate,
        "clip": {
            "clip_uuid": clip_uuid,
            "clip_id": clip.get("resolve_clip_id"),
            "clip_name": clip.get("clip_name"),
            "file_path": source,
        },
        "frame_count": len(frame_paths),
        "frame_paths": frame_paths,
        "frame_metadata": frame_metadata,
        "shot_table": shot_table,
        "deep_shot_schema": deep_shot_schema(),
        "schema_reference": DEEP_SHOT_SCHEMA_REFERENCE,
        "prompt": DEEP_SHOT_PROMPT,
        "commit_action": {
            "tool": "media_analysis",
            "action": "commit_shot_vision",
            "params": commit_params,
        },
        "instructions": (
            "Read every file under frame_paths as a local image. For each entry in "
            "shot_table, produce one object in `shots` with its shot_index and the "
            "deep_shot_schema field groups, grounded ONLY in the frames listed in "
            "that shot's frame_indices. Then call the tool in commit_action with "
            "`shots` set to that array. Skipping the commit leaves the deep pass "
            "incomplete — surface that rather than silently stopping."
        ),
    }


_DEEP_GROUP_KEYS = ("visual", "content", "production", "editorial", "cuttability")


def commit_shot_vision(
    project_root: str,
    *,
    shots: Any,
    vision_token: Optional[str] = None,
    clip_ref: Any = None,
    author: str = "host_chat",
) -> Dict[str, Any]:
    """Commit a deep per-shot payload: subjective rows (source vision_deep_v1),
    canonical blob update, and lockstep analysis.json re-export."""
    if isinstance(shots, str):
        try:
            shots = json.loads(shots)
        except json.JSONDecodeError as exc:
            return {"success": False, "error": f"shots was a string but not valid JSON: {exc}"}
    if isinstance(shots, dict) and isinstance(shots.get("shots"), list):
        shots = shots["shots"]
    if not isinstance(shots, list) or not shots:
        return {"success": False, "error": "commit_shot_vision requires `shots`: a non-empty array of per-shot objects"}

    context, err = _clip_context(project_root, clip_ref)
    if err:
        return {"success": False, "error": err}
    clip_uuid = context["clip_uuid"]
    db_shots = {int(s["shot_index"]): s for s in context["shots"]}
    by_uuid = {s["shot_uuid"]: s for s in context["shots"]}

    # Token check: recompute over the shots being committed.
    target_uuids = []
    normalized_entries: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []  # (db_shot, payload_entry)
    for entry in shots:
        if not isinstance(entry, dict):
            continue
        db_shot = None
        if entry.get("shot_uuid") and entry["shot_uuid"] in by_uuid:
            db_shot = by_uuid[entry["shot_uuid"]]
        else:
            try:
                db_shot = db_shots.get(int(entry.get("shot_index")))
            except (TypeError, ValueError):
                db_shot = None
        if db_shot is None:
            return {"success": False, "error": f"shot not found for entry: {entry.get('shot_uuid') or entry.get('shot_index')!r}"}
        target_uuids.append(db_shot["shot_uuid"])
        normalized_entries.append((db_shot, entry))
    if not normalized_entries:
        return {"success": False, "error": "No valid shot entries in payload"}
    expected = _vision_token_for(clip_uuid, target_uuids)
    if vision_token and str(vision_token) != expected:
        return {
            "success": False,
            "error": "vision_token mismatch; the clip was re-analyzed or the shot selection changed since the deepen payload was issued.",
            "expected_vision_token": expected,
            "received_vision_token": vision_token,
        }

    ma = _ma()
    conn = timeline_brain_db.connect(project_root)
    report_row = conn.execute(
        "SELECT report_json FROM analysis_reports WHERE clip_uuid = ?", (clip_uuid,)
    ).fetchone()
    if not report_row:
        return {"success": False, "error": "No canonical report for clip — run db_ingest first"}
    report = json.loads(report_row["report_json"])
    visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
    shot_entries = visual.get("shot_descriptions") if isinstance(visual.get("shot_descriptions"), list) else []
    entries_by_index: Dict[int, Dict[str, Any]] = {}
    for se in shot_entries:
        if isinstance(se, dict) and se.get("shot_index") is not None:
            try:
                entries_by_index[int(se["shot_index"])] = se
            except (TypeError, ValueError):
                continue

    updated = 0
    for db_shot, entry in normalized_entries:
        target = entries_by_index.get(int(db_shot["shot_index"]))
        if target is None:
            target = {
                "shot_index": int(db_shot["shot_index"]),
                "time_seconds_start": db_shot.get("time_seconds_start"),
                "time_seconds_end": db_shot.get("time_seconds_end"),
                "description": db_shot.get("description") or "",
                "qc_flags": [],
            }
            shot_entries.append(target)
            entries_by_index[int(db_shot["shot_index"])] = target
        for group in _DEEP_GROUP_KEYS:
            if isinstance(entry.get(group), dict):
                target[group] = entry[group]
        if isinstance(entry.get("confidence"), dict):
            target["confidence"] = entry["confidence"]
        description = entry.get("description")
        if isinstance(description, str) and description.strip():
            target["description"] = description.strip()
        updated += 1

    visual["shot_descriptions"] = shot_entries
    report["visual"] = visual
    report["deep_shots_committed_at"] = _now()

    # Rows first (canonical), deep source label; human rows preserved inside.
    ingest = analysis_store.ingest_report(
        project_root,
        report,
        clip_dir=os.path.join(project_root, "clips", context["clip"].get("clip_dir") or ""),
        author=author,
        source=DEEP_SOURCE,
    )
    if not ingest.get("success"):
        return {"success": False, "error": f"DB ingest failed: {ingest.get('error')}"}

    # Lockstep JSON export.
    export_path = None
    clip_dir_name = context["clip"].get("clip_dir")
    if clip_dir_name:
        candidate = os.path.join(project_root, "clips", clip_dir_name, "analysis.json")
        if os.path.isfile(candidate):
            export_path = analysis_store.export_report_file(project_root, clip_uuid, candidate)

    # Caps usage: frames that fed this pass (frames table rows for the target
    # shots), falling back to one frame per shot when none are recorded.
    placeholders = ",".join("?" for _ in target_uuids)
    frames_seen = int(conn.execute(
        f"SELECT COUNT(*) FROM frames WHERE clip_uuid = ? AND shot_uuid IN ({placeholders})",
        (clip_uuid, *target_uuids),
    ).fetchone()[0]) or len(normalized_entries)
    ma._record_caps_usage(
        project_root=project_root,
        clip_id=context["clip"].get("resolve_clip_id") or clip_uuid,
        vision_tokens=frames_seen * ma.AVG_VISION_TOKENS_PER_FRAME,
        frames_uploaded=frames_seen,
    )

    return {
        "success": True,
        "clip_uuid": clip_uuid,
        "shots_updated": updated,
        "subjective_fields_written": ingest.get("subjective_fields_written"),
        "subjective_fields_preserved_human": ingest.get("subjective_fields_preserved_human"),
        "source": DEEP_SOURCE,
        "analysis_json": export_path,
    }


def vision_pending_sweep(
    project_root: str,
    *,
    expire: bool = False,
    max_age_days: Optional[float] = None,
    reoffer: bool = False,
) -> Dict[str, Any]:
    """List clips stuck in pending_host_analysis; optionally expire or re-offer.

    Re-offer returns each clip's stored deferred payload (report["visual"])
    after verifying its frame files still exist. Expire stamps the report
    ``expired_host_analysis`` so pendings never linger silently.
    """
    ma = _ma()
    root = ma.normalize_path(project_root)
    clips_root = os.path.join(root, "clips")
    now = time.time()
    pending: List[Dict[str, Any]] = []
    expired: List[str] = []
    reoffers: List[Dict[str, Any]] = []
    if os.path.isdir(clips_root):
        for entry in sorted(os.listdir(clips_root)):
            clip_dir = os.path.join(clips_root, entry)
            report_path = os.path.join(clip_dir, "analysis.json")
            if not os.path.isfile(report_path):
                continue
            report = analysis_store.load_db_report(root, clip_dir=entry)
            if report is None:
                try:
                    with open(report_path, "r", encoding="utf-8") as handle:
                        report = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    continue
            if report.get("vision_status") != "pending_host_analysis":
                continue
            analyzed_at = report.get("analyzed_at")
            age_days = None
            ts = ma._timestamp_from_analyzed_at(analyzed_at)
            if ts:
                age_days = round((now - ts) / 86400.0, 2)
            visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
            frame_paths = visual.get("frame_paths") if isinstance(visual.get("frame_paths"), list) else []
            frames_present = sum(1 for p in frame_paths if p and os.path.isfile(str(p)))
            row = {
                "clip_dir": entry,
                "clip_name": (report.get("clip") or {}).get("clip_name"),
                "clip_id": (report.get("clip") or {}).get("clip_id"),
                "analyzed_at": analyzed_at,
                "age_days": age_days,
                "vision_token": report.get("vision_token") or visual.get("vision_token"),
                "frame_count": len(frame_paths),
                "frames_still_on_disk": frames_present,
                "reofferable": frames_present > 0,
            }
            pending.append(row)
            over_age = max_age_days is not None and (age_days or 0) >= float(max_age_days)
            if expire and (max_age_days is None or over_age):
                report["vision_status"] = "expired_host_analysis"
                report["vision_expired_at"] = _now()
                ingest = analysis_store.ingest_report(root, report, clip_dir=clip_dir)
                if ingest.get("success"):
                    analysis_store.export_report_file(root, ingest["clip_uuid"], report_path)
                else:
                    ma._write_json(report_path, report)
                expired.append(entry)
                row["expired"] = True
            elif reoffer and frames_present:
                reoffers.append({
                    "clip_dir": entry,
                    "payload": visual,
                })
    result: Dict[str, Any] = {
        "success": True,
        "project_root": root,
        "pending_count": len(pending),
        "pending": pending,
        "expired": expired,
    }
    if reoffer:
        result["reoffers"] = reoffers
        result["note"] = (
            "Each reoffer.payload is the original deferred host-vision payload; "
            "read its frame_paths and call its commit_action to finish the run."
        )
    return result
