"""Placing B-roll against an A-roll spine.

Asked for repeatedly, and the clearest version came from someone making recipe
videos: *could it find the one second where I am putting the spoon in my mouth?*
That is a `find_similar` query against visual strata pointed at a specific
moment in a voiceover, and the machinery for both halves already exists — it has
simply never been joined up.

## The shape of the problem

An A-roll spine (a voiceover or a talking head) has **beats**: sentences,
clauses, topic shifts. B-roll goes over some of them. Which B-roll goes where is
a content question, answered by whatever similarity the caller supplies; this
module answers the *placement* question, which is different and mechanical:

- **Where can B-roll go at all** — over a beat, not across one. Cutting away
  mid-sentence and back is a specific effect, not a default.
- **How long can it stay** — bounded by the beat, and by how long the candidate
  actually is.
- **What must not happen** — no gaps left uncovered that the caller thought were
  covered, and no B-roll placed over a moment where the speaker is on camera
  making a point the audience needs to see.

## The judgement this refuses to make

Whether a shot *illustrates* a line is not measurable here. The caller supplies
candidates with a relevance score from whatever matched them — semantic
similarity, a keyword hit, a human's choice — and this module places them and
reports the score it was given. **It does not invent relevance and it does not
re-rank on anything it cannot see.** A tool that quietly reorders a human's
choices by its own opinion of relevance is worse than one that places them in
the order it was handed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

#: A B-roll shot shorter than this reads as a flash rather than a cutaway.
MIN_BROLL_SECONDS = 0.8

#: Leave this much of a beat uncovered at each end so the cutaway sits inside
#: the thought rather than straddling its edges.
BEAT_INSET_SECONDS = 0.15

#: Below this the caller's own matcher was not confident, and placing it anyway
#: would launder a weak match into a decision.
MIN_RELEVANCE = 0.35


def placeable_beats(
    beats: Sequence[Mapping[str, Any]],
    *,
    min_seconds: float = MIN_BROLL_SECONDS,
    inset: float = BEAT_INSET_SECONDS,
) -> Dict[str, Any]:
    """Windows inside the A-roll where a cutaway can sit without straddling a beat.

    Each beat: `{"start_seconds", "end_seconds", "text"?, "protected"?}`.
    A beat marked `protected` is never covered — that is how a caller says "the
    speaker is making a point here and the audience needs to see them say it".
    """
    windows: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for index, beat in enumerate(beats):
        start = float(beat.get("start_seconds", 0)) + inset
        end = float(beat.get("end_seconds", 0)) - inset
        available = end - start
        if beat.get("protected"):
            skipped.append({
                "beat_index": index,
                "text": beat.get("text"),
                "reason": "protected — the caller marked this as must-see on camera",
            })
            continue
        if available < min_seconds:
            skipped.append({
                "beat_index": index,
                "text": beat.get("text"),
                "reason": f"only {max(0.0, available):.2f}s of usable window — under the "
                          f"{min_seconds}s floor, a cutaway here would read as a flash",
            })
            continue
        windows.append({
            "beat_index": index,
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "available_seconds": round(available, 3),
            "text": beat.get("text"),
        })
    return {"windows": windows, "skipped": skipped}


def place(
    beats: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    *,
    min_relevance: float = MIN_RELEVANCE,
    min_seconds: float = MIN_BROLL_SECONDS,
    allow_reuse: bool = False,
) -> Dict[str, Any]:
    """Place B-roll candidates into A-roll windows, in the order supplied.

    Each candidate: `{"name", "duration_seconds", "relevance"?, "beat_index"?}`.
    A candidate carrying `beat_index` is a caller's explicit choice and is placed
    there or not at all — never silently moved somewhere it fits better.
    """
    if not beats:
        return {"success": False, "error": "No A-roll beats supplied"}
    if not candidates:
        return {"success": False, "error": "No B-roll candidates supplied"}

    available = placeable_beats(beats, min_seconds=min_seconds)
    windows = {w["beat_index"]: w for w in available["windows"]}
    used_windows: set = set()
    used_clips: set = set()

    placements: List[Dict[str, Any]] = []
    unplaced: List[Dict[str, Any]] = []

    for candidate in candidates:
        name = candidate.get("name")
        relevance = candidate.get("relevance")
        if relevance is not None and float(relevance) < min_relevance:
            unplaced.append({
                "clip": name,
                "reason": f"relevance {float(relevance):.2f} is below {min_relevance} — "
                          "the matcher that produced it was not confident, and placing "
                          "it anyway would launder a weak match into a decision",
            })
            continue
        if not allow_reuse and name in used_clips:
            unplaced.append({"clip": name, "reason": "already placed; allow_reuse is off"})
            continue

        requested = candidate.get("beat_index")
        if requested is not None:
            window = windows.get(int(requested))
            if window is None:
                unplaced.append({
                    "clip": name,
                    "reason": f"beat {requested} is not placeable (protected, too short, "
                              "or out of range) — an explicit choice is placed there or "
                              "not at all, never moved somewhere it fits better",
                })
                continue
            if int(requested) in used_windows:
                unplaced.append({"clip": name, "reason": f"beat {requested} already covered"})
                continue
            target = window
        else:
            free = [w for i, w in sorted(windows.items()) if i not in used_windows]
            if not free:
                unplaced.append({"clip": name, "reason": "no uncovered window left"})
                continue
            target = free[0]

        duration = float(candidate.get("duration_seconds") or 0.0)
        if duration < min_seconds:
            unplaced.append({
                "clip": name,
                "reason": f"{duration:.2f}s of media — under the {min_seconds}s floor",
            })
            continue
        length = min(duration, target["available_seconds"])
        used_windows.add(target["beat_index"])
        used_clips.add(name)
        placements.append({
            "clip": name,
            "beat_index": target["beat_index"],
            "over_text": target["text"],
            "start_seconds": target["start_seconds"],
            "end_seconds": round(target["start_seconds"] + length, 3),
            "length_seconds": round(length, 3),
            "trimmed": length < duration,
            "relevance": float(relevance) if relevance is not None else None,
            "relevance_source": (
                "supplied by the caller's matcher; not re-scored here"
                if relevance is not None else "not supplied"
            ),
        })

    uncovered = [w for i, w in sorted(windows.items()) if i not in used_windows]
    return {
        "success": True,
        "kind": "broll_placement",
        "placement_count": len(placements),
        "placements": placements,
        "unplaced": unplaced,
        "uncovered_windows": uncovered,
        "unusable_beats": available["skipped"],
        "note": (
            f"{len(placements)} cutaways placed over {len(windows)} usable windows; "
            f"{len(uncovered)} windows left uncovered and "
            f"{len(available['skipped'])} beats were not usable at all. Placement is "
            "mechanical — **relevance is whatever your matcher said it was and is not "
            "re-scored here**, because whether a shot illustrates a line is not "
            "something this can see. Cutaways sit inside a beat rather than straddling "
            "one; protected beats are never covered. Nothing is cut."
        ),
    }
