"""Cross-clip entities (Phase D of the analysis program).

Recurring people/places/props across a project's analyzed media. The cheap
part is local: union-find clustering over the v10 CLIP frame vectors with a
cosine threshold. The expensive part is bounded: ONE host-vision call per
cluster representative (the deferred-payload pattern), committed via
``commit_entities`` with kind/label/description per cluster — conservative
labels, per the trust-by-default rule (hedge identity when evidence is thin).

Bin briefing v2 rides the same pattern at bin level: ``prepare_bin_briefing``
returns entities + per-clip summaries for the host chat to synthesize, and
``commit_bin_summary`` writes the result into memory/bin_summary.md (the v2.0
aggregate stays below as an appendix).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.utils import analysis_memory, embeddings, timeline_brain_db

ENTITY_VISION_SOURCE = "vision_entity_v1"
ENTITY_SCHEMA_REFERENCE = "davinci_resolve_mcp.entity_confirmation.v1"
DEFAULT_CLUSTER_THRESHOLD = 0.78
DEFAULT_MIN_CLUSTER_SIZE = 2

ENTITY_SCHEMA = {
    "entities": [
        {
            "entity_index": "<int — from the payload's clusters list>",
            "entity_uuid": "<echo the cluster's entity_uuid when convenient>",
            "kind": "person|place|object|unknown",
            "label": "<short conservative label — 'man in dark hooded jacket', not a name unless visibly slated>",
            "description": "<1-2 sentences of what recurs across these frames>",
            "confidence": "low|medium|high",
            "merge_with": "<optional int entity_index this duplicates, else omit>",
        }
    ]
}

ENTITY_PROMPT = (
    "Each cluster below groups frames that look visually similar across the "
    "project's clips. Look at each cluster's representative frame and decide "
    "what recurring entity it shows (a person, place, or object). Use "
    "conservative labels — describe what is visible, never guess identity or "
    "names unless text on screen states them. If two clusters clearly show "
    "the same entity, point the duplicate at the original with merge_with. "
    "Return strict JSON matching `schema`."
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ma():
    from src.utils import media_analysis

    return media_analysis


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _cluster_vectors(
    vectors: List[List[float]], threshold: float
) -> List[List[int]]:
    """Union-find over pairwise cosine similarity. O(n²) — fine at this scale."""
    n = len(vectors)
    uf = _UnionFind(n)
    try:
        import numpy as np

        matrix = np.asarray(vectors, dtype="float32")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = matrix / norms
        sims = normalized @ normalized.T
        for i in range(n):
            row = sims[i]
            for j in range(i + 1, n):
                if row[j] >= threshold:
                    uf.union(i, j)
    except ImportError:
        for i in range(n):
            for j in range(i + 1, n):
                if embeddings.cosine_similarity(vectors[i], vectors[j]) >= threshold:
                    uf.union(i, j)
    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)
    return sorted(groups.values(), key=len, reverse=True)


def _representative(vectors: List[List[float]], members: List[int]) -> Tuple[int, Dict[int, float]]:
    """Member with the highest mean similarity to its cluster, plus each
    member's similarity to that representative."""
    best_index = members[0]
    best_mean = -1.0
    for i in members:
        mean = sum(embeddings.cosine_similarity(vectors[i], vectors[j]) for j in members if j != i)
        mean = mean / max(1, len(members) - 1)
        if mean > best_mean:
            best_mean, best_index = mean, i
    sims = {
        j: (1.0 if j == best_index else embeddings.cosine_similarity(vectors[best_index], vectors[j]))
        for j in members
    }
    return best_index, sims


def _entity_uuid_for(frame_refs: Sequence[str]) -> str:
    return _ma().short_hash("entity:" + ",".join(sorted(frame_refs)), 12)


def _detection_state_path(project_root: str) -> str:
    return os.path.join(analysis_memory.memory_dir(project_root), "entity_detection_state.json")


def _write_detection_state(project_root: str, token: str, ordering: List[str]) -> None:
    analysis_memory.ensure_memory_structure(project_root)
    path = _detection_state_path(project_root)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"vision_token": token, "ordering": ordering, "written_at": _now()}, handle, indent=2)
    os.replace(tmp, path)


def _read_detection_state(project_root: str) -> Optional[Dict[str, Any]]:
    try:
        with open(_detection_state_path(project_root), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def detect_entities(
    project_root: str,
    *,
    threshold: float = DEFAULT_CLUSTER_THRESHOLD,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    max_clusters: int = 24,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cluster visual frame vectors into provisional entities and return the
    deferred host-vision confirmation payload (one frame per cluster)."""
    ma = _ma()
    conn = timeline_brain_db.connect(project_root)
    rows = conn.execute(
        """
        SELECT entity_uuid, vector FROM embeddings
        WHERE embedding_kind = 'visual' AND entity_type = 'frame'
        """
    ).fetchall()
    if not rows:
        return {
            "success": False,
            "error": (
                "No visual frame embeddings yet — run "
                "media_analysis(action='build_embeddings', params={'kinds': ['visual']}) first."
            ),
        }
    frame_refs = [str(r["entity_uuid"]) for r in rows]
    vectors = [embeddings.unpack_vector(r["vector"]) for r in rows]

    clusters = [
        members for members in _cluster_vectors(vectors, float(threshold))
        if len(members) >= int(min_cluster_size)
    ][: int(max_clusters)]
    if not clusters:
        return {
            "success": True,
            "status": "no_clusters",
            "frame_count": len(rows),
            "note": f"No clusters of size >= {min_cluster_size} at threshold {threshold}.",
        }

    # Hydrate frame rows once: frame_ref -> (clip_uuid, frame_index, path, shot_uuid).
    frame_info: Dict[str, Dict[str, Any]] = {}
    for ref in frame_refs:
        clip_uuid, _, frame_index = ref.rpartition(":")
        row = conn.execute(
            "SELECT frame_path, shot_uuid FROM frames WHERE clip_uuid = ? AND frame_index = ?",
            (clip_uuid, int(frame_index) if frame_index.lstrip("-").isdigit() else -1),
        ).fetchone()
        frame_info[ref] = {
            "clip_uuid": clip_uuid,
            "frame_index": frame_index,
            "frame_path": str(row["frame_path"]) if row and row["frame_path"] else None,
            "shot_uuid": str(row["shot_uuid"]) if row and row["shot_uuid"] else None,
        }

    # Caps: one frame per cluster goes to the host.
    estimated_tokens = len(clusters) * ma.AVG_VISION_TOKENS_PER_FRAME
    refusal = ma._check_caps_pre_call(
        project_root=project_root,
        estimated_vision_tokens=estimated_tokens,
        clip_id=None,
        job_id=job_id,
    )
    if refusal is not None:
        return refusal

    now = _now()
    cluster_payload: List[Dict[str, Any]] = []
    entity_uuids: List[str] = []
    with timeline_brain_db.transaction(project_root) as txn:
        for index, members in enumerate(clusters, 1):
            refs = [frame_refs[i] for i in members]
            rep_i, sims = _representative(vectors, members)
            rep_ref = frame_refs[rep_i]
            rep = frame_info[rep_ref]
            entity_uuid = _entity_uuid_for(refs)
            entity_uuids.append(entity_uuid)
            existing = txn.execute(
                "SELECT created_at, kind, label, description, confidence, source FROM entities WHERE entity_uuid = ?",
                (entity_uuid,),
            ).fetchone()
            txn.execute(
                """
                INSERT OR REPLACE INTO entities
                    (entity_uuid, kind, label, description, confidence, source,
                     representative_frame_ref, representative_frame_path,
                     cluster_size, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_uuid,
                    existing["kind"] if existing else "unknown",
                    existing["label"] if existing else None,
                    existing["description"] if existing else None,
                    existing["confidence"] if existing else None,
                    existing["source"] if existing else "clustering",
                    rep_ref,
                    rep["frame_path"],
                    len(members),
                    str(existing["created_at"]) if existing else now,
                    now,
                ),
            )
            txn.execute("DELETE FROM entity_appearances WHERE entity_uuid = ?", (entity_uuid,))
            for i in members:
                ref = frame_refs[i]
                info = frame_info[ref]
                txn.execute(
                    """
                    INSERT OR IGNORE INTO entity_appearances
                        (entity_uuid, clip_uuid, shot_uuid, frame_ref, similarity)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (entity_uuid, info["clip_uuid"], info["shot_uuid"], ref, round(float(sims[i]), 4)),
                )
            clip_count = len({frame_info[r]["clip_uuid"] for r in refs})
            shot_count = len({frame_info[r]["shot_uuid"] for r in refs if frame_info[r]["shot_uuid"]})
            cluster_payload.append({
                "entity_index": index,
                "entity_uuid": entity_uuid,
                "frame_count": len(members),
                "clip_count": clip_count,
                "shot_count": shot_count,
                "already_labeled": bool(existing and existing["label"]),
                "current_label": existing["label"] if existing else None,
                "representative_frame_path": rep["frame_path"],
            })

    # Prune unlabeled provisional ghosts from earlier runs (a different
    # threshold re-shapes clusters → new uuids). Labeled entities persist.
    with timeline_brain_db.transaction(project_root) as txn:
        placeholders = ",".join("?" for _ in entity_uuids)
        txn.execute(
            f"""
            DELETE FROM entity_appearances WHERE entity_uuid IN (
                SELECT entity_uuid FROM entities
                WHERE source = 'clustering' AND label IS NULL
                  AND entity_uuid NOT IN ({placeholders})
            )
            """,
            entity_uuids,
        )
        txn.execute(
            f"""
            DELETE FROM entities
            WHERE source = 'clustering' AND label IS NULL
              AND entity_uuid NOT IN ({placeholders})
            """,
            entity_uuids,
        )

    vision_token = _ma().short_hash("entities:" + ",".join(sorted(entity_uuids)), 16)
    _write_detection_state(project_root, vision_token, entity_uuids)
    return {
        "success": True,
        "status": "pending_host_analysis",
        "provider": "host_chat_paths",
        "mode": "entity_confirmation",
        "vision_token": vision_token,
        "threshold": threshold,
        "frame_count": len(rows),
        "cluster_count": len(clusters),
        "estimate": {
            "frames_to_review": len(clusters),
            "estimated_vision_tokens": estimated_tokens,
        },
        "clusters": cluster_payload,
        "frame_paths": [c["representative_frame_path"] for c in cluster_payload if c["representative_frame_path"]],
        "schema": json.loads(json.dumps(ENTITY_SCHEMA)),
        "schema_reference": ENTITY_SCHEMA_REFERENCE,
        "prompt": ENTITY_PROMPT,
        "commit_action": {
            "tool": "media_analysis",
            "action": "commit_entities",
            "params": {
                "vision_token": vision_token,
                "entities": "<host chat: fill per `schema`>",
                "analysis_root": project_root,
            },
        },
        "instructions": (
            "Read each cluster's representative_frame_path as a local image and "
            "produce one entry per entity_index in `entities` per the schema. "
            "Then call the tool in commit_action. Clusters marked "
            "already_labeled keep their label unless you provide a better one."
        ),
    }


def commit_entities(
    project_root: str,
    *,
    entities_payload: Any,
    vision_token: Optional[str] = None,
    author: str = "host_chat",
) -> Dict[str, Any]:
    """Apply host-vision labels to provisional entity clusters."""
    if isinstance(entities_payload, str):
        try:
            entities_payload = json.loads(entities_payload)
        except json.JSONDecodeError as exc:
            return {"success": False, "error": f"entities was a string but not valid JSON: {exc}"}
    if isinstance(entities_payload, dict) and isinstance(entities_payload.get("entities"), list):
        entities_payload = entities_payload["entities"]
    if not isinstance(entities_payload, list) or not entities_payload:
        return {"success": False, "error": "commit_entities requires `entities`: a non-empty array"}

    state = _read_detection_state(project_root)
    if not state:
        return {"success": False, "error": "No entity-detection state — run detect_entities first"}
    expected = str(state.get("vision_token") or "")
    if vision_token and str(vision_token) != expected:
        return {
            "success": False,
            "error": "vision_token mismatch; entity clusters changed since the payload was issued (re-run detect_entities).",
            "expected_vision_token": expected,
        }

    # entity_index resolution uses the exact ordering detect_entities issued.
    by_index = {i + 1: uuid for i, uuid in enumerate(state.get("ordering") or [])}
    now = _now()
    updated = 0
    merged = 0
    with timeline_brain_db.transaction(project_root) as txn:
        merges: List[Tuple[str, str]] = []
        for entry in entities_payload:
            if not isinstance(entry, dict):
                continue
            uuid = entry.get("entity_uuid") or by_index.get(_safe_int(entry.get("entity_index")))
            if not uuid:
                continue
            merge_target = entry.get("merge_with")
            if merge_target is not None:
                target_uuid = by_index.get(_safe_int(merge_target))
                if target_uuid and target_uuid != uuid:
                    merges.append((str(uuid), target_uuid))
                    continue
            txn.execute(
                """
                UPDATE entities
                SET kind = ?, label = ?, description = ?, confidence = ?,
                    source = ?, updated_at = ?
                WHERE entity_uuid = ?
                """,
                (
                    str(entry.get("kind") or "unknown"),
                    entry.get("label"),
                    entry.get("description"),
                    entry.get("confidence"),
                    ENTITY_VISION_SOURCE if author == "host_chat" else "human",
                    now,
                    str(uuid),
                ),
            )
            updated += 1
        for duplicate, target in merges:
            txn.execute(
                "UPDATE OR IGNORE entity_appearances SET entity_uuid = ? WHERE entity_uuid = ?",
                (target, duplicate),
            )
            txn.execute("DELETE FROM entity_appearances WHERE entity_uuid = ?", (duplicate,))
            txn.execute("DELETE FROM entities WHERE entity_uuid = ?", (duplicate,))
            size = txn.execute(
                "SELECT COUNT(*) FROM entity_appearances WHERE entity_uuid = ?", (target,)
            ).fetchone()[0]
            txn.execute(
                "UPDATE entities SET cluster_size = ?, updated_at = ? WHERE entity_uuid = ?",
                (int(size), now, target),
            )
            merged += 1

    ma = _ma()
    ma._record_caps_usage(
        project_root=project_root,
        clip_id=None,
        vision_tokens=updated * ma.AVG_VISION_TOKENS_PER_FRAME,
        frames_uploaded=updated,
    )
    return {"success": True, "entities_updated": updated, "entities_merged": merged}


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def list_entities(project_root: str, *, kind: Optional[str] = None) -> Dict[str, Any]:
    conn = timeline_brain_db.connect(project_root)
    where = " WHERE kind = ?" if kind else ""
    args: Tuple[Any, ...] = (kind,) if kind else ()
    rows = conn.execute(
        f"SELECT * FROM entities{where} ORDER BY cluster_size DESC, label", args
    ).fetchall()
    entities: List[Dict[str, Any]] = []
    for row in rows:
        entity = dict(row)
        appearances = conn.execute(
            """
            SELECT a.clip_uuid, c.clip_name, a.shot_uuid, s.shot_index, a.frame_ref, a.similarity
            FROM entity_appearances a
            LEFT JOIN clips c ON c.clip_uuid = a.clip_uuid
            LEFT JOIN shots s ON s.shot_uuid = a.shot_uuid
            WHERE a.entity_uuid = ?
            ORDER BY a.clip_uuid, s.shot_index
            """,
            (entity["entity_uuid"],),
        ).fetchall()
        entity["appearances"] = [dict(a) for a in appearances]
        entity["clip_count"] = len({a["clip_uuid"] for a in appearances})
        entity["shot_count"] = len({a["shot_uuid"] for a in appearances if a["shot_uuid"]})
        entities.append(entity)
    return {"success": True, "count": len(entities), "entities": entities}


# ── bin briefing v2 ──────────────────────────────────────────────────────────


def prepare_bin_briefing(project_root: str) -> Dict[str, Any]:
    """Deferred payload for a host-synthesized bin briefing: labeled entities
    + per-clip summaries. Text-only — no frames, no vision cost."""
    conn = timeline_brain_db.connect(project_root)
    clips = [dict(r) for r in conn.execute(
        "SELECT clip_uuid, clip_name, summary, duration_seconds, shot_count, overall_motion_level FROM clips ORDER BY clip_name"
    ).fetchall()]
    if not clips:
        return {"success": False, "error": "No analyzed clips in the DB — analyze (or db_ingest) first."}
    for clip in clips:
        row = conn.execute(
            """
            SELECT value_json FROM subjective_fields
            WHERE entity_type='clip' AND entity_uuid=? AND field_path='clip_summary'
              AND superseded_at IS NULL
            """,
            (clip["clip_uuid"],),
        ).fetchone()
        if row:
            try:
                clip["clip_summary"] = json.loads(row["value_json"])
            except (TypeError, ValueError):
                pass
    listed = list_entities(project_root)
    entity_lines = [
        {
            "label": e.get("label") or "(unlabeled cluster)",
            "kind": e.get("kind"),
            "description": e.get("description"),
            "clip_count": e.get("clip_count"),
            "shot_count": e.get("shot_count"),
            "frame_count": e.get("cluster_size"),
        }
        for e in listed.get("entities") or []
    ]
    token = _ma().short_hash(
        "briefing:" + ",".join(sorted(c["clip_uuid"] for c in clips)), 16
    )
    return {
        "success": True,
        "status": "pending_host_synthesis",
        "briefing_token": token,
        "clips": clips,
        "entities": entity_lines,
        "prompt": (
            "Write a colleague-style bin briefing in markdown: 2-4 paragraphs "
            "covering what this media is, who/what recurs (use the entities "
            "list), the strongest material, and anything an editor should know "
            "before cutting. Conservative claims only — describe, don't guess. "
            "Then call the tool in commit_action with `briefing` set to the markdown."
        ),
        "commit_action": {
            "tool": "media_analysis",
            "action": "commit_bin_summary",
            "params": {
                "briefing": "<host chat: markdown briefing>",
                "briefing_token": token,
                "analysis_root": project_root,
            },
        },
    }


def commit_bin_summary(
    project_root: str,
    *,
    briefing: Any,
    briefing_token: Optional[str] = None,
    author: str = "host_chat",
) -> Dict[str, Any]:
    """Write the host-synthesized briefing above the v2.0 aggregate."""
    if not isinstance(briefing, str) or not briefing.strip():
        return {"success": False, "error": "commit_bin_summary requires `briefing` (markdown text)"}
    conn = timeline_brain_db.connect(project_root)
    clips = [str(r["clip_uuid"]) for r in conn.execute("SELECT clip_uuid FROM clips ORDER BY clip_name").fetchall()]
    expected = _ma().short_hash("briefing:" + ",".join(sorted(clips)), 16)
    if briefing_token and str(briefing_token) != expected:
        return {
            "success": False,
            "error": "briefing_token mismatch; the clip set changed since the payload was issued (re-run prepare_bin_briefing).",
        }
    analysis_memory.ensure_memory_structure(project_root)
    path = analysis_memory.bin_summary_path(project_root)
    appendix = ""
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                existing = handle.read()
            # Keep only the aggregate section as an appendix (drop a previous
            # synthesized briefing if present).
            marker = "# Bin summary —"
            idx = existing.find(marker)
            if idx >= 0:
                appendix = existing[idx:]
        except OSError:
            appendix = ""
    content = (
        f"# Bin briefing\n\n_Synthesized {_now()} by {author} "
        f"(entities + per-clip summaries)._\n\n{briefing.strip()}\n"
    )
    if appendix:
        content += f"\n\n---\n\n{appendix}"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp, path)
    return {"success": True, "path": path, "bytes": len(content)}
