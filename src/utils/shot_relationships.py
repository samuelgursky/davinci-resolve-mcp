"""Cross-shot relationships (spec §4 — pattern recognition only).

Detect → one bounded vision confirm → commit, the Phase D entities pattern:
the cheap part is local (pairwise cosine over the v10 per-shot visual
vectors, plus transcript continuity as a second signal for continues_from);
the expensive part is bounded (the host chat reviews a representative frame
PAIR per candidate). NO editorial suggestions are stored — only the three
spec §4 relationship types:

- same_setup_as  (symmetric)  — same camera + framing of the same action
- alt_take_of    (symmetric)  — different take of the same setup
- continues_from (directional)— the SOURCE shot continues from the TARGET
  shot (target precedes source)

Symmetric rows are stored once with the pair canonically ordered by
(clip_name, shot_index); readers must check both columns. Candidates live
only in the detection-state stash until committed — re-detect overwrites
the stash, so unconfirmed candidates can never linger as ghosts. Commit
supersedes any current machine row for the same (pair, type) before
inserting, so human corrections (a later C4-style author='human' row)
always stay newest.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from src.utils import analysis_memory, embeddings, timeline_brain_db

RELATIONSHIP_VISION_SOURCE = "vision_relationship_v1"
RELATIONSHIP_SCHEMA_REFERENCE = "davinci_resolve_mcp.relationship_confirmation.v1"
RELATIONSHIP_TYPES = ("same_setup_as", "continues_from", "alt_take_of")

# Tuned on the sample root (34-shot montage) during Phase 4 live validation.
DEFAULT_SETUP_THRESHOLD = 0.90      # same-clip non-adjacent or cross-clip: same_setup_as
DEFAULT_ALT_TAKE_THRESHOLD = 0.88   # cross-clip + comparable duration: alt_take_of
DEFAULT_CONTINUES_BAND = (0.70, 0.90)  # adjacent same-clip shots: continues_from
DEFAULT_MAX_CANDIDATES = 24
ALT_TAKE_DURATION_RATIO = 2.0       # durations within 2x of each other

RELATIONSHIP_SCHEMA = {
    "relationships": [
        {
            "candidate_index": "<int — from the payload's candidates list>",
            "verdict": "confirm|reject",
            "relationship_type": "same_setup_as|continues_from|alt_take_of (override the suggestion when the frames say otherwise)",
            "confidence": "low|medium|high",
        }
    ]
}

RELATIONSHIP_PROMPT = (
    "Each candidate below pairs two shots that the local heuristics think are "
    "related. Look at BOTH frames of each pair and judge the suggested "
    "relationship: same_setup_as = same camera setup + framing of the same "
    "action; alt_take_of = a different take of the same setup; continues_from "
    "= the first shot visibly continues the second shot's action across a "
    "cut. Confirm only what the frames actually show — reject lookalikes "
    "(similar palette or subject is NOT the same setup). You may override the "
    "suggested type when the frames support a different one. Return strict "
    "JSON matching `schema`."
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _now_precise() -> str:
    """Microsecond timestamps — `timestamp` is part of the row's UNIQUE key,
    so two commits of the same pair within one second must not collide."""
    now = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int((now % 1) * 1e6):06d}Z"


def _ma():
    from src.utils import media_analysis

    return media_analysis


def _state_path(project_root: str) -> str:
    return os.path.join(analysis_memory.memory_dir(project_root), "relationship_detection_state.json")


def _write_state(project_root: str, token: str, candidates: List[Dict[str, Any]]) -> None:
    analysis_memory.ensure_memory_structure(project_root)
    path = _state_path(project_root)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"vision_token": token, "candidates": candidates, "written_at": _now()}, handle, indent=2)
    os.replace(tmp, path)


def _read_state(project_root: str) -> Optional[Dict[str, Any]]:
    try:
        with open(_state_path(project_root), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _shot_rows(conn) -> Dict[str, Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.shot_uuid, s.clip_uuid, s.shot_index, s.time_seconds_start,
               s.time_seconds_end, s.description, c.clip_name
        FROM shots s LEFT JOIN clips c ON c.clip_uuid = s.clip_uuid
        """
    ).fetchall()
    return {str(r["shot_uuid"]): dict(r) for r in rows}


def _rep_frame_path(conn, shot_uuid: str) -> Optional[str]:
    """The shot's MIDDLE sampled frame — first/last frames often catch fades
    or transition black, which makes pair review impossible."""
    rows = conn.execute(
        """
        SELECT frame_path FROM frames
        WHERE shot_uuid = ? AND frame_path IS NOT NULL
        ORDER BY frame_index
        """,
        (str(shot_uuid),),
    ).fetchall()
    if not rows:
        return None
    return str(rows[len(rows) // 2]["frame_path"])


def _transcript_spans_boundary(conn, clip_uuid: str, boundary_seconds: float) -> bool:
    """A transcript segment spanning the cut boundary is continuity evidence."""
    row = conn.execute(
        """
        SELECT 1 FROM transcript_segments
        WHERE clip_uuid = ? AND start_seconds < ? AND end_seconds > ?
        LIMIT 1
        """,
        (clip_uuid, float(boundary_seconds), float(boundary_seconds)),
    ).fetchone()
    return row is not None


def _canonical_pair(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    key = lambda s: (str(s.get("clip_name") or ""), int(s.get("shot_index") or 0))  # noqa: E731
    return (a, b) if key(a) <= key(b) else (b, a)


def detect_shot_relationships(
    project_root: str,
    *,
    setup_threshold: float = DEFAULT_SETUP_THRESHOLD,
    alt_take_threshold: float = DEFAULT_ALT_TAKE_THRESHOLD,
    continues_band: Tuple[float, float] = DEFAULT_CONTINUES_BAND,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Pairwise heuristics over per-shot visual vectors → deferred
    confirmation payload with a representative frame PAIR per candidate."""
    ma = _ma()
    conn = timeline_brain_db.connect(project_root)
    vec_rows = conn.execute(
        """
        SELECT entity_uuid, vector FROM embeddings
        WHERE embedding_kind = 'visual' AND entity_type = 'shot'
        """
    ).fetchall()
    if not vec_rows:
        return {
            "success": False,
            "error": (
                "No per-shot visual embeddings yet — run "
                "media_analysis(action='build_embeddings', params={'kinds': ['visual']}) first."
            ),
        }
    shots = _shot_rows(conn)
    uuids = [str(r["entity_uuid"]) for r in vec_rows if str(r["entity_uuid"]) in shots]
    vectors = {u: embeddings.unpack_vector(r["vector"]) for u, r in zip(
        [str(r["entity_uuid"]) for r in vec_rows], vec_rows) if u in shots}

    low_cont, high_cont = float(continues_band[0]), float(continues_band[1])
    candidates: List[Dict[str, Any]] = []
    for i in range(len(uuids)):
        for j in range(i + 1, len(uuids)):
            a, b = shots[uuids[i]], shots[uuids[j]]
            sim = embeddings.cosine_similarity(vectors[uuids[i]], vectors[uuids[j]])
            same_clip = a["clip_uuid"] == b["clip_uuid"]
            suggestion = None
            evidence: List[str] = []
            if same_clip:
                index_gap = abs(int(a["shot_index"]) - int(b["shot_index"]))
                if index_gap == 1 and low_cont <= sim < high_cont:
                    suggestion = "continues_from"
                    earlier, later = (a, b) if int(a["shot_index"]) < int(b["shot_index"]) else (b, a)
                    boundary = earlier.get("time_seconds_end")
                    if boundary is not None and _transcript_spans_boundary(
                        conn, str(a["clip_uuid"]), float(boundary)
                    ):
                        evidence.append("a transcript segment spans the cut boundary")
                elif index_gap > 1 and sim >= float(setup_threshold):
                    suggestion = "same_setup_as"
            else:
                dur_a = (a.get("time_seconds_end") or 0) - (a.get("time_seconds_start") or 0)
                dur_b = (b.get("time_seconds_end") or 0) - (b.get("time_seconds_start") or 0)
                comparable = (
                    dur_a > 0 and dur_b > 0
                    and max(dur_a, dur_b) / max(min(dur_a, dur_b), 0.001) <= ALT_TAKE_DURATION_RATIO
                )
                if sim >= float(alt_take_threshold) and comparable:
                    suggestion = "alt_take_of"
                elif sim >= float(setup_threshold):
                    suggestion = "same_setup_as"
            if not suggestion:
                continue
            evidence.insert(0, f"visual cosine {round(float(sim), 3)} between per-shot vectors")
            if suggestion == "continues_from":
                # Directional: the LATER shot continues from the EARLIER one.
                earlier, later = (a, b) if int(a["shot_index"]) < int(b["shot_index"]) else (b, a)
                source, target = later, earlier
            else:
                source, target = _canonical_pair(a, b)
            candidates.append({
                "source_shot_uuid": source["shot_uuid"],
                "target_shot_uuid": target["shot_uuid"],
                "suggested_type": suggestion,
                "similarity": round(float(sim), 4),
                "evidence": evidence,
                "_sim": float(sim),
            })

    candidates.sort(key=lambda c: -c["_sim"])
    candidates = candidates[: max(1, int(max_candidates))]
    for candidate in candidates:
        candidate.pop("_sim", None)
    if not candidates:
        return {
            "success": True,
            "status": "no_candidates",
            "shot_count": len(uuids),
            "note": (
                f"No relationship candidates at setup>={setup_threshold}, "
                f"alt_take>={alt_take_threshold}, continues {continues_band}."
            ),
        }

    # Caps: two frames per candidate go to the host.
    estimated_tokens = len(candidates) * 2 * ma.AVG_VISION_TOKENS_PER_FRAME
    refusal = ma._check_caps_pre_call(
        project_root=project_root,
        estimated_vision_tokens=estimated_tokens,
        clip_id=None,
        job_id=job_id,
    )
    if refusal is not None:
        return refusal

    payload: List[Dict[str, Any]] = []
    state_rows: List[Dict[str, Any]] = []
    for index, candidate in enumerate(candidates, 1):
        src = shots[candidate["source_shot_uuid"]]
        dst = shots[candidate["target_shot_uuid"]]
        src_frame = _rep_frame_path(conn, candidate["source_shot_uuid"])
        dst_frame = _rep_frame_path(conn, candidate["target_shot_uuid"])
        payload.append({
            "candidate_index": index,
            "suggested_type": candidate["suggested_type"],
            "similarity": candidate["similarity"],
            "evidence": candidate["evidence"],
            "source_shot": {
                "clip_name": src.get("clip_name"), "shot_index": src.get("shot_index"),
                "description": src.get("description"), "frame_path": src_frame,
            },
            "target_shot": {
                "clip_name": dst.get("clip_name"), "shot_index": dst.get("shot_index"),
                "description": dst.get("description"), "frame_path": dst_frame,
            },
        })
        state_rows.append({
            "candidate_index": index,
            "source_shot_uuid": candidate["source_shot_uuid"],
            "target_shot_uuid": candidate["target_shot_uuid"],
            "suggested_type": candidate["suggested_type"],
            "similarity": candidate["similarity"],
        })

    vision_token = ma.short_hash(
        "relationships:" + ",".join(f"{r['source_shot_uuid']}>{r['target_shot_uuid']}" for r in state_rows), 16,
    )
    # Candidates live ONLY here until committed — re-detect overwrites the
    # stash, so unconfirmed candidates never linger as ghost rows.
    _write_state(project_root, vision_token, state_rows)
    frame_paths = [
        p for c in payload for p in (c["source_shot"]["frame_path"], c["target_shot"]["frame_path"]) if p
    ]
    return {
        "success": True,
        "status": "pending_host_analysis",
        "provider": "host_chat_paths",
        "mode": "relationship_confirmation",
        "vision_token": vision_token,
        "candidate_count": len(payload),
        "estimate": {
            "frames_to_review": len(frame_paths),
            "estimated_vision_tokens": estimated_tokens,
        },
        "thresholds": {
            "setup_threshold": setup_threshold,
            "alt_take_threshold": alt_take_threshold,
            "continues_band": list(continues_band),
        },
        "candidates": payload,
        "frame_paths": frame_paths,
        "schema": json.loads(json.dumps(RELATIONSHIP_SCHEMA)),
        "schema_reference": RELATIONSHIP_SCHEMA_REFERENCE,
        "prompt": RELATIONSHIP_PROMPT,
        "commit_action": {
            "tool": "media_analysis",
            "action": "commit_shot_relationships",
            "params": {
                "vision_token": vision_token,
                "relationships": "<host chat: fill per `schema`>",
                "analysis_root": project_root,
            },
        },
        "instructions": (
            "For each candidate read BOTH frame paths as local images, judge "
            "the suggested relationship, and return one entry per "
            "candidate_index in `relationships` per the schema. Then call the "
            "tool in commit_action. Reject anything the frames don't support."
        ),
    }


def commit_shot_relationships(
    project_root: str,
    *,
    relationships_payload: Any,
    vision_token: Optional[str] = None,
    author: str = "host_chat",
) -> Dict[str, Any]:
    """Write vision-confirmed relationship rows (machine source label).

    Supersedes any current machine row for the same (pair, type) first, so
    re-running the pass never duplicates and never outranks human rows added
    later (human edits ride the same supersede semantics with author='human')."""
    if isinstance(relationships_payload, str):
        try:
            relationships_payload = json.loads(relationships_payload)
        except json.JSONDecodeError as exc:
            return {"success": False, "error": f"relationships was a string but not valid JSON: {exc}"}
    if isinstance(relationships_payload, dict) and isinstance(relationships_payload.get("relationships"), list):
        relationships_payload = relationships_payload["relationships"]
    if not isinstance(relationships_payload, list) or not relationships_payload:
        return {"success": False, "error": "commit_shot_relationships requires `relationships`: a non-empty array"}

    state = _read_state(project_root)
    if not state:
        return {"success": False, "error": "No relationship-detection state — run detect_shot_relationships first"}
    expected = str(state.get("vision_token") or "")
    if vision_token and str(vision_token) != expected:
        return {
            "success": False,
            "error": (
                "vision_token mismatch; candidates changed since the payload was "
                "issued (re-run detect_shot_relationships)."
            ),
            "expected_vision_token": expected,
        }
    by_index = {int(c["candidate_index"]): c for c in state.get("candidates") or []}

    now = _now_precise()
    confirmed = 0
    rejected = 0
    skipped: List[Dict[str, Any]] = []
    frames_reviewed = len(by_index) * 2
    with timeline_brain_db.transaction(project_root) as txn:
        for entry in relationships_payload:
            if not isinstance(entry, dict):
                continue
            try:
                candidate = by_index.get(int(entry.get("candidate_index")))
            except (TypeError, ValueError):
                candidate = None
            if candidate is None:
                skipped.append({"entry": entry, "reason": "unknown candidate_index"})
                continue
            verdict = str(entry.get("verdict") or "").strip().lower()
            if verdict != "confirm":
                rejected += 1
                continue
            rel_type = str(entry.get("relationship_type") or candidate["suggested_type"])
            if rel_type not in RELATIONSHIP_TYPES:
                skipped.append({"entry": entry, "reason": f"invalid relationship_type {rel_type!r}"})
                continue
            source_uuid = str(candidate["source_shot_uuid"])
            target_uuid = str(candidate["target_shot_uuid"])
            txn.execute(
                """
                UPDATE shot_relationships SET superseded_at = ?
                WHERE relationship_type = ? AND superseded_at IS NULL
                  AND source = ?
                  AND ((source_shot_uuid = ? AND target_shot_uuid = ?)
                       OR (source_shot_uuid = ? AND target_shot_uuid = ?))
                """,
                (now, rel_type, RELATIONSHIP_VISION_SOURCE,
                 source_uuid, target_uuid, target_uuid, source_uuid),
            )
            txn.execute(
                """
                INSERT INTO shot_relationships
                    (source_shot_uuid, target_shot_uuid, relationship_type,
                     confidence, source, author, timestamp, superseded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    source_uuid,
                    target_uuid,
                    rel_type,
                    entry.get("confidence"),
                    RELATIONSHIP_VISION_SOURCE if author == "host_chat" else "human",
                    author,
                    now,
                ),
            )
            confirmed += 1

    ma = _ma()
    ma._record_caps_usage(
        project_root=project_root,
        clip_id=None,
        vision_tokens=frames_reviewed * ma.AVG_VISION_TOKENS_PER_FRAME,
        frames_uploaded=frames_reviewed,
    )
    return {
        "success": True,
        "confirmed": confirmed,
        "rejected": rejected,
        "skipped": skipped,
    }


def list_shot_relationships(
    project_root: str,
    *,
    clip_ref: Optional[str] = None,
    shot_uuid: Optional[str] = None,
    relationship_type: Optional[str] = None,
    include_superseded: bool = False,
) -> Dict[str, Any]:
    """Current relationship rows, hydrated with clip/shot context on both ends."""
    conn = timeline_brain_db.connect(project_root)
    where = [] if include_superseded else ["r.superseded_at IS NULL"]
    args: List[Any] = []
    if relationship_type:
        where.append("r.relationship_type = ?")
        args.append(relationship_type)
    if shot_uuid:
        where.append("(r.source_shot_uuid = ? OR r.target_shot_uuid = ?)")
        args.extend([str(shot_uuid), str(shot_uuid)])
    if clip_ref:
        from src.utils import analysis_store

        clip_uuid = analysis_store.resolve_clip_uuid(conn, clip_ref)
        if not clip_uuid:
            return {"success": False, "error": f"No analyzed clip found for {clip_ref!r}"}
        where.append(
            "(src.clip_uuid = ? OR dst.clip_uuid = ?)"
        )
        args.extend([clip_uuid, clip_uuid])
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"""
        SELECT r.*, src.clip_uuid AS source_clip_uuid, src.shot_index AS source_shot_index,
               sc.clip_name AS source_clip_name,
               dst.clip_uuid AS target_clip_uuid, dst.shot_index AS target_shot_index,
               dc.clip_name AS target_clip_name
        FROM shot_relationships r
        LEFT JOIN shots src ON src.shot_uuid = r.source_shot_uuid
        LEFT JOIN clips sc ON sc.clip_uuid = src.clip_uuid
        LEFT JOIN shots dst ON dst.shot_uuid = r.target_shot_uuid
        LEFT JOIN clips dc ON dc.clip_uuid = dst.clip_uuid
        {where_sql}
        ORDER BY r.relationship_type, r.id
        """,
        args,
    ).fetchall()
    return {"success": True, "count": len(rows), "relationships": [dict(r) for r in rows]}


def relationships_for_shot(conn, shot_uuid: str) -> Dict[str, List[str]]:
    """Panel block for one shot: {type: ["Clip · shot N", ...]} from current
    rows, reading both directions of the symmetric types. continues_from is
    shown only on the SOURCE shot (the one that continues)."""
    out: Dict[str, List[str]] = {}
    rows = conn.execute(
        """
        SELECT r.relationship_type, r.source_shot_uuid, r.target_shot_uuid,
               src.shot_index AS source_shot_index, sc.clip_name AS source_clip_name,
               src.clip_uuid AS source_clip_uuid,
               dst.shot_index AS target_shot_index, dc.clip_name AS target_clip_name,
               dst.clip_uuid AS target_clip_uuid
        FROM shot_relationships r
        LEFT JOIN shots src ON src.shot_uuid = r.source_shot_uuid
        LEFT JOIN clips sc ON sc.clip_uuid = src.clip_uuid
        LEFT JOIN shots dst ON dst.shot_uuid = r.target_shot_uuid
        LEFT JOIN clips dc ON dc.clip_uuid = dst.clip_uuid
        WHERE r.superseded_at IS NULL
          AND (r.source_shot_uuid = ? OR r.target_shot_uuid = ?)
        """,
        (str(shot_uuid), str(shot_uuid)),
    ).fetchall()
    me = str(shot_uuid)
    for row in rows:
        rel_type = str(row["relationship_type"])
        is_source = str(row["source_shot_uuid"]) == me
        if rel_type == "continues_from" and not is_source:
            continue  # shown on the continuing shot only
        other_index = row["target_shot_index"] if is_source else row["source_shot_index"]
        other_clip = row["target_clip_name"] if is_source else row["source_clip_name"]
        same_clip = (row["source_clip_uuid"] == row["target_clip_uuid"])
        label = f"shot {other_index}" if same_clip else f"{other_clip} · shot {other_index}"
        out.setdefault(rel_type, []).append(label)
    return out


def confirmed_alt_take_shot_uuids(conn, shot_uuid: str) -> List[str]:
    """Shot uuids confirmed as alt takes of `shot_uuid` (either direction)."""
    rows = conn.execute(
        """
        SELECT source_shot_uuid, target_shot_uuid FROM shot_relationships
        WHERE relationship_type = 'alt_take_of' AND superseded_at IS NULL
          AND (source_shot_uuid = ? OR target_shot_uuid = ?)
        """,
        (str(shot_uuid), str(shot_uuid)),
    ).fetchall()
    me = str(shot_uuid)
    out: List[str] = []
    for row in rows:
        other = str(row["target_shot_uuid"]) if str(row["source_shot_uuid"]) == me else str(row["source_shot_uuid"])
        if other != me and other not in out:
            out.append(other)
    return out
