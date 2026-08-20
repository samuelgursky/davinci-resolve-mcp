"""Rhythm — criterion #3 of the Rule of Six, and the largest measurable slice at 10%.

The naive reading of "rhythm" is *consistency*, and a tool built on that reading
would flag every variation and reward metronomic cutting. That is backwards.
An editor of long standing states the actual principle:

    "You set up a rhythm... and then you need to break that rhythm, because
    that's what gets people's attention."

    **The break is where meaning lives.**

So there are two findings here, and they are opposites:

1. **Monotony** — a long metronomic stretch. The pattern was established and
   never broken, so nothing is emphasised and attention drifts.
2. **An unmotivated break** — the pattern broke somewhere nothing was happening.
   A break is an emphasis; emphasising nothing spends the audience's attention
   on noise.

A break that lands on a story beat is neither. It is the craft working, and this
module reports it as a **PASS with evidence**, not as an absence of findings.
Silence about the thing that went right is how a tool teaches people that it
only ever complains.

## On cuts per minute

Dialogue scenes are often observed to land around 14–16 cuts per minute, and the
observation was always **descriptive, not prescriptive**. It is reported here as
a comparison and never as a target. Celebrated features have shipped at well
under a thousand cuts in their entirety — extraordinarily sparse — and are not
wrong. Any reading of this number as something to hit would make the tool
actively harmful.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.utils import rule_of_six as _six

#: Commonly observed density for dialogue scenes. Descriptive, NOT a
#: target — see the module docstring.
DIALOGUE_CPM_RANGE = (14.0, 16.0)

#: Coefficient of variation below which a run of shots reads as metronomic.
#: Deliberately generous: real editing is uneven, and flagging mild regularity
#: would bury the genuinely mechanical stretches.
MONOTONY_CV_THRESHOLD = 0.15
#: Shortest run that can be called monotonous. Four similar shots is a pattern;
#: three is a coincidence.
MONOTONY_MIN_RUN = 6

#: How far a shot length must depart from the local norm to count as a break.
BREAK_RATIO = 1.8
#: How close a break must sit to a story beat to count as motivated, in seconds.
BREAK_BEAT_TOLERANCE_S = 2.0


def shot_lengths(items: Sequence[Mapping[str, Any]], fps: float) -> List[Dict[str, Any]]:
    """Ordered shot durations in seconds, with their timeline positions."""
    rows: List[Dict[str, Any]] = []
    ordered = sorted(
        (i for i in items
         if i.get("timeline_start_frame") is not None
         and i.get("timeline_end_frame") is not None),
        key=lambda i: i["timeline_start_frame"],
    )
    for item in ordered:
        frames = int(item["timeline_end_frame"]) - int(item["timeline_start_frame"])
        if frames <= 0:
            continue
        rows.append({
            "name": item.get("item_name"),
            "start_frame": int(item["timeline_start_frame"]),
            "seconds": round(frames / fps, 3),
        })
    return rows


def _cv(values: Sequence[float]) -> float:
    """Coefficient of variation — spread relative to length, so it is scale-free."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean <= 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return (variance ** 0.5) / mean


def find_monotony(shots: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Runs of near-identical shot lengths — a pattern that never breaks."""
    findings: List[Dict[str, Any]] = []
    start = 0
    while start < len(shots):
        end = start + 1
        while end < len(shots):
            window = [float(s["seconds"]) for s in shots[start:end + 1]]
            if _cv(window) > MONOTONY_CV_THRESHOLD:
                break
            end += 1
        run = shots[start:end]
        if len(run) >= MONOTONY_MIN_RUN:
            lengths = [float(s["seconds"]) for s in run]
            findings.append({
                "criterion": "rhythm",
                "scope": "sequence",
                "at": run[0]["start_frame"],
                "summary": f"{len(run)} consecutive shots of near-identical length",
                "detail": (
                    f"{len(run)} shots averaging {sum(lengths) / len(lengths):.2f}s with "
                    f"almost no variation. A pattern was established and never broken, so "
                    f"nothing in this stretch is emphasised. The break is where meaning "
                    f"lives; there is no break here."
                ),
                "evidence": {"shot_count": len(run), "lengths": [round(x, 2) for x in lengths]},
            })
            start = end
        else:
            start += 1
    return findings


def find_breaks(
    shots: Sequence[Mapping[str, Any]],
    beats: Sequence[float],
    fps: float,
) -> Dict[str, List[Dict[str, Any]]]:
    """Pattern breaks, split by whether anything motivated them.

    `beats` are story-beat times in seconds — sentence boundaries, markers,
    whatever the caller has. A break landing near one is craft.
    """
    motivated: List[Dict[str, Any]] = []
    unmotivated: List[Dict[str, Any]] = []
    for index in range(2, len(shots)):
        prior = [float(s["seconds"]) for s in shots[max(0, index - 4):index]]
        if len(prior) < 2:
            continue
        local_norm = sum(prior) / len(prior)
        length = float(shots[index]["seconds"])
        if local_norm <= 0:
            continue
        ratio = length / local_norm
        if ratio < BREAK_RATIO and ratio > 1.0 / BREAK_RATIO:
            continue
        at_seconds = float(shots[index]["start_frame"]) / fps
        near = [b for b in beats if abs(float(b) - at_seconds) <= BREAK_BEAT_TOLERANCE_S]
        record = {
            "criterion": "rhythm",
            "scope": "scene",
            "at": shots[index]["start_frame"],
            "shot": shots[index]["name"],
            "length_seconds": round(length, 2),
            "local_norm_seconds": round(local_norm, 2),
            "ratio": round(ratio, 2),
            "direction": "longer" if ratio > 1 else "shorter",
        }
        if near:
            record["summary"] = "rhythm break lands on a story beat"
            record["detail"] = (
                f"Shot runs {round(ratio, 1)}x the local norm and coincides with a beat "
                f"at {near[0]:.1f}s. This is the pattern being broken deliberately — "
                "emphasis where something is happening."
            )
            motivated.append(record)
        else:
            record["summary"] = "rhythm break with nothing to emphasise"
            record["detail"] = (
                f"Shot runs {round(ratio, 1)}x the local norm but no story beat sits "
                f"within {BREAK_BEAT_TOLERANCE_S}s. A break is emphasis; emphasising "
                "nothing spends the audience's attention on noise. Check whether this "
                "is a beat we cannot see, or a shot that simply ran long."
            )
            unmotivated.append(record)
    return {"motivated": motivated, "unmotivated": unmotivated}


def cuts_per_minute(shots: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Cut density, reported only ever as a comparison."""
    total = sum(float(s["seconds"]) for s in shots)
    if total <= 0 or len(shots) < 2:
        return None
    cpm = len(shots) / (total / 60.0)
    low, high = DIALOGUE_CPM_RANGE
    if cpm < low:
        relation = "sparser than"
    elif cpm > high:
        relation = "denser than"
    else:
        relation = "within"
    return {
        "cuts_per_minute": round(cpm, 1),
        "observed_dialogue_range": list(DIALOGUE_CPM_RANGE),
        "relation": relation,
        "note": (
            f"{round(cpm, 1)} cuts/min, {relation} the 14-16 commonly observed in "
            "dialogue scenes. That range is DESCRIPTIVE, NOT PRESCRIPTIVE — a comparison, "
            "not a target. Celebrated features have shipped at a small fraction of that "
            "density and are not wrong."
        ),
    }


def assess(
    items: Sequence[Mapping[str, Any]],
    *,
    fps: float,
    story_beats: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Evaluate the rhythm criterion. Returns a `rule_of_six` criterion result."""
    shots = shot_lengths(items, fps)
    if len(shots) < 3:
        return {
            "state": _six.STATE_PASS,
            "detail": "too few shots to have a rhythm — nothing to assess",
            "findings": [],
            "shots": shots,
            "insufficient_data": True,
        }

    beats = list(story_beats or [])
    monotony = find_monotony(shots)
    breaks = find_breaks(shots, beats, fps)
    findings = monotony + breaks["unmotivated"]

    lengths = [float(s["seconds"]) for s in shots]
    detail_bits = [
        f"{len(shots)} shots, {min(lengths):.1f}-{max(lengths):.1f}s, "
        f"variation {_cv(lengths):.2f}"
    ]
    if breaks["motivated"]:
        # Say what went right. A tool that only ever complains teaches its
        # reader that a clean report means it did not look.
        detail_bits.append(
            f"{len(breaks['motivated'])} rhythm breaks land on story beats — "
            "the pattern is being broken deliberately"
        )
    if not beats:
        detail_bits.append(
            "no story beats supplied, so breaks could NOT be judged motivated or not"
        )

    return {
        "state": _six.STATE_FLAG if findings else _six.STATE_PASS,
        "detail": "; ".join(detail_bits),
        "findings": findings,
        "motivated_breaks": breaks["motivated"],
        "shots": shots,
        "cut_density": cuts_per_minute(shots),
        "beats_supplied": len(beats),
    }
