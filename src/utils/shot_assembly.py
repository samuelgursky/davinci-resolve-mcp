"""Assembly for footage that does not talk.

Everything else in this codebase finds edit points in speech — word boundaries,
pauses, fillers. Point that at motorsport, a music video, a live performance or
an event recap and it does not degrade, it inverts: engine noise reads as
content, a quiet straight reads as dead space, and the cuts land in all the
wrong places. A viewer predicted exactly that before trying it, and he was
right, because the tool was answering a question his footage never asked.

Speechless footage has its own structure. Not words: **shots and motion**.

- **Shot boundaries** are where the camera or the subject already changed. They
  are the cut points the material is offering.
- **Motion energy** says which of those shots is doing something, and where
  inside a shot the action peaks or resolves.

## What this does not do

It does not decide what the sequence is *about*. Ranking shots by how much is
moving in them is a measurement, not an edit — a static wide of a landscape may
be the most important shot in the piece and will score last on every metric here.
The output is a **string-out in a defensible order with the evidence attached**,
which is what an assistant hands an editor, not a cut.

## No-script mode

The same machinery answers "I have no script, just footage." Cluster what is
there, propose a structure, and **require approval before anything is cut** —
which is what the tutorial author himself concluded after watching an agent
freelance: handhold it, and do not let it cut without permission.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: Shots shorter than this are almost always flash frames or transition
#: artefacts rather than content, and putting them in a string-out is noise.
MIN_USABLE_SECONDS = 0.5

#: Motion energy below this reads as a locked-off or near-static shot. Static is
#: not a defect — it is a fact about the shot, reported rather than penalised.
STATIC_MOTION_THRESHOLD = 0.05

#: Group boundary: a gap between shots larger than this suggests a different
#: setup, location or time, so it starts a new cluster.
CLUSTER_GAP_SECONDS = 30.0


def _duration(shot: Mapping[str, Any]) -> float:
    return max(0.0, float(shot.get("end_seconds", 0)) - float(shot.get("start_seconds", 0)))


def rank_shots(shots: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Order shots by measurable activity, with the measurement attached.

    Each shot: `{"name", "start_seconds", "end_seconds", "motion_energy"?}`.
    `motion_energy` is 0-1; absent means unmeasured, which is reported as such
    and never treated as zero — a shot nobody measured is not a static shot.
    """
    usable, rejected = [], []
    for shot in shots:
        duration = _duration(shot)
        if duration < MIN_USABLE_SECONDS:
            rejected.append({
                "shot": shot.get("name"),
                "reason": f"{duration:.2f}s — under the {MIN_USABLE_SECONDS}s floor; "
                          "almost certainly a flash frame or transition artefact",
            })
            continue
        motion = shot.get("motion_energy")
        usable.append({
            "shot": shot.get("name"),
            "start_seconds": round(float(shot.get("start_seconds", 0)), 3),
            "end_seconds": round(float(shot.get("end_seconds", 0)), 3),
            "duration_seconds": round(duration, 3),
            "motion_energy": round(float(motion), 4) if motion is not None else None,
            "motion_measured": motion is not None,
            "character": _character(motion, duration),
        })
    ranked = sorted(
        usable,
        key=lambda s: (s["motion_energy"] is None, -(s["motion_energy"] or 0.0), -s["duration_seconds"]),
    )
    for position, shot in enumerate(ranked, start=1):
        shot["activity_rank"] = position
    return {
        "shots": ranked,
        "rejected": rejected,
        "unmeasured_count": sum(1 for s in ranked if not s["motion_measured"]),
    }


def _character(motion: Optional[float], duration: float) -> str:
    if motion is None:
        return "unmeasured — not the same as static"
    if float(motion) < STATIC_MOTION_THRESHOLD:
        return "static or locked off — a fact about the shot, not a fault"
    if duration > 10:
        return "sustained action"
    return "action"


def cluster_shots(
    shots: Sequence[Mapping[str, Any]],
    *,
    gap_seconds: float = CLUSTER_GAP_SECONDS,
) -> List[Dict[str, Any]]:
    """Group shots into candidate sequences by temporal proximity.

    A crude proxy for "these belong together" and labelled as one. Real grouping
    is by content and intent; this groups by the clock, which correlates with
    location and setup often enough to be a useful starting point and not often
    enough to be trusted.
    """
    ordered = sorted(shots, key=lambda s: float(s.get("start_seconds", 0)))
    clusters: List[Dict[str, Any]] = []
    current: List[Mapping[str, Any]] = []
    for shot in ordered:
        if current and float(shot.get("start_seconds", 0)) - float(current[-1].get("end_seconds", 0)) > gap_seconds:
            clusters.append(_close_cluster(current, len(clusters) + 1))
            current = []
        current.append(shot)
    if current:
        clusters.append(_close_cluster(current, len(clusters) + 1))
    return clusters


def _close_cluster(shots: Sequence[Mapping[str, Any]], index: int) -> Dict[str, Any]:
    return {
        "cluster": index,
        "shot_count": len(shots),
        "start_seconds": round(float(shots[0].get("start_seconds", 0)), 3),
        "end_seconds": round(float(shots[-1].get("end_seconds", 0)), 3),
        "shots": [s.get("name") for s in shots],
    }


def plan_string_out(
    shots: Sequence[Mapping[str, Any]],
    *,
    order: str = "chronological",
    gap_seconds: float = CLUSTER_GAP_SECONDS,
) -> Dict[str, Any]:
    """A reviewable string-out of speechless footage. Cuts nothing.

    `order`: `chronological` (default — the safest, and what an assistant hands
    over) or `activity` (most movement first, for finding the action in a long
    unstructured shoot).
    """
    if order not in ("chronological", "activity"):
        return {"success": False, "error": f"unknown order {order!r}; expected chronological or activity"}
    if not shots:
        return {"success": False, "error": "No shots supplied"}

    ranked = rank_shots(shots)
    if not ranked["shots"]:
        return {
            "success": False,
            "error": "No shots long enough to use",
            "rejected": ranked["rejected"],
        }

    sequence = (
        sorted(ranked["shots"], key=lambda s: s["start_seconds"])
        if order == "chronological" else ranked["shots"]
    )
    clusters = cluster_shots(shots, gap_seconds=gap_seconds)
    total = sum(s["duration_seconds"] for s in sequence)

    return {
        "success": True,
        "kind": "shot_string_out",
        "order": order,
        "shot_count": len(sequence),
        "total_seconds": round(total, 2),
        "sequence": sequence,
        "clusters": clusters,
        "rejected": ranked["rejected"],
        "unmeasured_motion_count": ranked["unmeasured_count"],
        "clustering_basis": (
            f"temporal proximity, {gap_seconds:g}s gap — a PROXY for 'these belong "
            "together'. Real grouping is by content and intent; this groups by the "
            "clock, which tracks location and setup often enough to be useful and "
            "not often enough to trust."
        ),
        "note": (
            f"A string-out of {len(sequence)} shots in {order} order — **not a cut**. "
            "Speechless footage is cut from shots and motion, not from silence: a "
            "speech gate reads engine noise as content and a quiet straight as dead "
            "space. Ranking by movement is a measurement, not an edit — a locked-off "
            "wide may be the most important shot here and will rank last on every "
            "metric. Decide the order yourself; this hands you the material with the "
            "evidence attached."
            + (f" {ranked['unmeasured_count']} shots have no motion measurement and "
               "sit at the end — unmeasured is not static."
               if ranked["unmeasured_count"] else "")
        ),
    }


# ── no-script mode ───────────────────────────────────────────────────────────


def propose_structure(
    topics: Sequence[Mapping[str, Any]],
    *,
    min_topic_seconds: float = 5.0,
) -> Dict[str, Any]:
    """Propose an order for material that arrived without a script.

    Each topic: `{"label", "total_seconds", "clip_count", "first_seconds"?}` —
    typically the output of clustering transcript content.

    **Requires approval and says so.** The tutorial that prompted this programme
    ended with its author's own conclusion after watching an agent freelance:
    handhold it, and do not let it cut without permission. A structure proposed
    from clustering is a hypothesis about what the piece is, and that is the one
    decision least safe to take silently.
    """
    if not topics:
        return {"success": False, "error": "No topics supplied"}

    usable, thin = [], []
    for topic in topics:
        seconds = float(topic.get("total_seconds") or 0.0)
        record = {
            "label": topic.get("label"),
            "total_seconds": round(seconds, 2),
            "clip_count": int(topic.get("clip_count") or 0),
            "first_seconds": topic.get("first_seconds"),
        }
        (usable if seconds >= min_topic_seconds else thin).append(record)

    ordered = sorted(usable, key=lambda t: -t["total_seconds"])
    for position, topic in enumerate(ordered, start=1):
        topic["proposed_position"] = position

    return {
        "success": True,
        "kind": "proposed_structure",
        "requires_approval": True,
        "topic_count": len(ordered),
        "proposed_order": ordered,
        "thin_topics": thin,
        "basis": (
            "ordered by how much material each topic has — a measure of what was "
            "SHOT, not of what matters. The most-covered subject is frequently not "
            "the point of the piece."
        ),
        "note": (
            f"{len(ordered)} topics proposed in coverage order. **This is a "
            "hypothesis about what the piece is, and nothing is cut.** Approve, "
            "reorder or discard it before any assembly — a structure inferred from "
            "clustering is the single decision least safe to take silently."
            + (f" {len(thin)} topics under {min_topic_seconds:g}s were set aside as "
               "thin, not deleted." if thin else "")
        ),
    }
