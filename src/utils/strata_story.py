"""Story beats — units of meaning over the transcript (host-LLM pass).

Follows the host_chat_paths contract used by the vision passes: the server
never calls an LLM itself. ``plan_story_beats`` assembles a timecoded digest
(transcript + prosody evidence + known entities) plus a JSON schema and
instructions; the host chat model produces the beats; ``commit_story_beats``
validates and persists them.

Persistence mirrors subjective_fields: append-only with supersede semantics.
A machine commit supersedes only prior machine rows for that clip; rows with
source='human' are never touched and always win.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from src.utils import strata, timeline_brain_db

STORY_SOURCE = "story_v1"
STORY_VERSION = "1.0.0"

BEAT_TYPES = ("topic", "claim", "revelation", "emotional", "anecdote", "question", "callback")

STORY_BEAT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["beats"],
    "properties": {
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["start_seconds", "end_seconds", "beat_type", "label", "summary"],
                "properties": {
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                    "beat_type": {"type": "string", "enum": list(BEAT_TYPES)},
                    "label": {"type": "string", "description": "3-6 word handle, e.g. 'father built the house'"},
                    "summary": {"type": "string", "description": "1-2 sentences: what this span IS, not a paraphrase"},
                    "entity_labels": {"type": "array", "items": {"type": "string"}},
                    "links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["kind", "label"],
                            "properties": {
                                "kind": {"type": "string", "enum": ["callback_to", "contradicts", "answers", "sets_up"]},
                                "label": {"type": "string", "description": "label of the related beat"},
                            },
                        },
                    },
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        }
    },
}

STORY_BEAT_INSTRUCTIONS = (
    "Segment this clip's transcript into story beats — units of MEANING, not "
    "paragraphs. A beat boundary is where the subject changes what they are "
    "doing narratively: a new topic, a claim, a revelation, an emotional turn, "
    "an anecdote, a question. Use the pause/hesitation/energy evidence: long "
    "pauses and energy shifts often mark real boundaries. Label beats with "
    "short handles; link beats that call back to, contradict, set up, or "
    "answer one another (within this clip). Do not invent content that is not "
    "in the transcript; when the evidence is thin, say confidence=low. Cover "
    "the spoken regions; leave silence uncovered."
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _beat_uuid() -> str:
    # Random, not content-derived: every commit inserts fresh rows, so prior
    # rows (machine or human) can only be superseded, never replaced through
    # a primary-key collision.
    return uuid.uuid4().hex[:12]


def _resolve(project_root: str, clip_ref: Any):
    conn, clip, err = strata.resolve_clip(project_root, clip_ref)
    if err:
        return None, None, err
    return conn, clip["clip_uuid"], None


def plan_story_beats(project_root: str, clip_ref: Any) -> Dict[str, Any]:
    """Digest + schema for the host model. No LLM call happens here."""
    conn, clip_uuid, err = _resolve(project_root, clip_ref)
    if err:
        return err

    segments = conn.execute(
        "SELECT segment_index, start_seconds, end_seconds, text, speaker_id "
        "FROM transcript_segments WHERE clip_uuid = ? ORDER BY segment_index",
        (clip_uuid,),
    ).fetchall()
    if not segments:
        return {
            "success": False,
            "error": "clip has no transcript segments — run transcription first",
            "clip_uuid": clip_uuid,
        }

    pauses = strata.read_events(conn, clip_uuid, "pause")
    hesitations = strata.read_events(conn, clip_uuid, "hesitation")
    energy = strata.read_curve(conn, clip_uuid, "vocal_energy")

    digest_segments: List[Dict[str, Any]] = []
    for seg in segments:
        start = seg["start_seconds"]
        end = seg["end_seconds"]
        entry: Dict[str, Any] = {
            "start_seconds": start,
            "end_seconds": end,
            "text": seg["text"],
        }
        if seg["speaker_id"]:
            entry["speaker"] = seg["speaker_id"]
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            seg_pauses = [
                {"at": p["time_seconds"], "seconds": p["duration_seconds"]}
                for p in pauses
                if start <= p["time_seconds"] < end
            ]
            if seg_pauses:
                entry["pauses"] = seg_pauses
            n_hes = sum(1 for h in hesitations if start <= h["time_seconds"] < end)
            if n_hes:
                entry["hesitations"] = n_hes
            if energy:
                values = [
                    v for v in (
                        strata.curve_value_at(energy, start + i * 0.5)
                        for i in range(int(max(0.0, (end - start)) / 0.5) + 1)
                    )
                    if v is not None
                ]
                if values:
                    entry["energy_mean"] = round(sum(values) / len(values), 3)
        digest_segments.append(entry)

    entity_rows = conn.execute(
        """
        SELECT DISTINCT e.label FROM entities e
        JOIN entity_appearances a ON a.entity_uuid = e.entity_uuid
        WHERE a.clip_uuid = ? AND e.label IS NOT NULL
        """,
        (clip_uuid,),
    ).fetchall()

    current = list_story_beats(project_root, clip_uuid)
    return {
        "success": True,
        "status": "pending_host_story_beats",
        "clip_uuid": clip_uuid,
        "digest": {
            "segments": digest_segments,
            "known_entities": [r["label"] for r in entity_rows],
            "pause_count": len(pauses),
        },
        "schema": STORY_BEAT_SCHEMA,
        "instructions": STORY_BEAT_INSTRUCTIONS,
        "commit_action": {"tool": "media_analysis", "action": "commit_story_beats"},
        "existing_beats": current.get("beats", []),
    }


def commit_story_beats(
    project_root: str,
    clip_ref: Any,
    beats: Any,
    *,
    source_model: Optional[str] = None,
    author: str = "host",
) -> Dict[str, Any]:
    """Validate + persist host-produced beats. Machine rows supersede machine
    rows; human rows are untouched."""
    conn, clip_uuid, err = _resolve(project_root, clip_ref)
    if err:
        return err
    if isinstance(beats, dict):
        beats = beats.get("beats")
    if not isinstance(beats, list):
        return {"success": False, "error": "beats must be a list (or {beats: [...]})"}

    validated: List[Dict[str, Any]] = []
    problems: List[str] = []
    seen_spans: set = set()
    for i, beat in enumerate(beats):
        if not isinstance(beat, dict):
            problems.append(f"beats[{i}] is not an object")
            continue
        start = beat.get("start_seconds")
        end = beat.get("end_seconds")
        label = str(beat.get("label") or "").strip()
        summary = str(beat.get("summary") or "").strip()
        beat_type = str(beat.get("beat_type") or "").strip()
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            problems.append(f"beats[{i}] has invalid start/end")
            continue
        if beat_type not in BEAT_TYPES:
            problems.append(f"beats[{i}] beat_type {beat_type!r} not in {BEAT_TYPES}")
            continue
        if not label or not summary:
            problems.append(f"beats[{i}] needs label and summary")
            continue
        span_key = (round(float(start), 3), round(float(end), 3), label)
        if span_key in seen_spans:
            problems.append(f"beats[{i}] duplicates an earlier beat in this commit; skipped")
            continue
        seen_spans.add(span_key)
        links = beat.get("links") if isinstance(beat.get("links"), list) else []
        entity_labels = beat.get("entity_labels") if isinstance(beat.get("entity_labels"), list) else []
        validated.append(
            {
                "start_seconds": float(start),
                "end_seconds": float(end),
                "beat_type": beat_type,
                "label": label,
                "summary": summary,
                "links": links,
                "entity_labels": entity_labels,
                "confidence": beat.get("confidence") if beat.get("confidence") in ("low", "medium", "high") else None,
            }
        )
    if not validated:
        return {"success": False, "error": "no valid beats to commit", "problems": problems}

    now = _now()
    source = STORY_SOURCE
    with timeline_brain_db.transaction(project_root) as txn:
        txn.execute(
            "UPDATE story_beats SET superseded_at = ? "
            "WHERE clip_uuid = ? AND source != ? AND superseded_at IS NULL",
            (now, clip_uuid, strata.HUMAN_SOURCE),
        )
        for beat in validated:
            txn.execute(
                """
                INSERT INTO story_beats
                    (beat_uuid, clip_uuid, start_seconds, end_seconds, beat_type,
                     label, summary, entities_json, links_json, confidence,
                     source, author, timestamp, superseded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    _beat_uuid(),
                    clip_uuid,
                    beat["start_seconds"],
                    beat["end_seconds"],
                    beat["beat_type"],
                    beat["label"],
                    beat["summary"],
                    json.dumps(beat["entity_labels"]) if beat["entity_labels"] else None,
                    json.dumps(beat["links"]) if beat["links"] else None,
                    beat["confidence"],
                    source,
                    f"{author}:{source_model}" if source_model else author,
                    now,
                ),
            )
    return {
        "success": True,
        "clip_uuid": clip_uuid,
        "beats_committed": len(validated),
        "problems": problems,
    }


def list_story_beats(project_root: str, clip_ref: Any) -> Dict[str, Any]:
    conn, clip_uuid, err = _resolve(project_root, clip_ref)
    if err:
        return err
    rows = conn.execute(
        "SELECT * FROM story_beats WHERE clip_uuid = ? AND superseded_at IS NULL "
        "ORDER BY start_seconds",
        (clip_uuid,),
    ).fetchall()
    beats = []
    for row in rows:
        beat = {
            "beat_uuid": row["beat_uuid"],
            "start_seconds": row["start_seconds"],
            "end_seconds": row["end_seconds"],
            "beat_type": row["beat_type"],
            "label": row["label"],
            "summary": row["summary"],
            "confidence": row["confidence"],
            "source": row["source"],
        }
        for key, column in (("entity_labels", "entities_json"), ("links", "links_json")):
            if row[column]:
                try:
                    beat[key] = json.loads(row[column])
                except (TypeError, ValueError):
                    pass
        beats.append(beat)
    return {"success": True, "clip_uuid": clip_uuid, "beats": beats}
