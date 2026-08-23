"""The retry ladder that lets a grade reject itself.

`image_qc.assess_grade` already measures whether a graded frame carries damage its
source did not — banding in the sky, crushed highlights, amplified shadow grain — and
every flag it raises carries a remedy. Until now nothing consumed that report. The
measurement existed; the loop did not, so the remedy "reduce the strength" was advice
an agent had no way to act on.

This closes it. Given a source and a look LUT, the ladder applies the look, measures the
real decoded result, and on any flag retries with the same look attenuated toward
identity. The first strength that clears every gate wins.

## What it never does

Report a flagged result as acceptable. When the ladder is exhausted the return carries
`needs_human` with the best attempt and its remaining flags — not a quiet success at a
strength that still bands. `acceptable` is derived from the flag list at every rung and
is never assigned.

## Every sampled frame must pass

A grade that is clean on the frame you happened to check and bands two hundred frames
later has not passed anything. `times` accepts several timestamps and a strength is
accepted only when *all* of them clear; the report names the frame that failed, because
"the grade bands" and "the grade bands on the sky at 00:41" are different amounts of
help.

## The best attempt is the gentlest one

When nothing converges, attempts are ranked by flag count and ties broken by the
*smallest* colour shift. A tie on damage means choosing between two equally-flawed
grades, and the one that moved the image less is the one a human has less to undo.

## Cost

The default `cost_tier` here is `numeric` rather than `image_qc`'s own default. The
ladder runs several assessments per clip; escalating each of them to vision would spend
host turns on rungs that exist only to be rejected. Pass a different tier deliberately.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Optional, Sequence

from . import cube_lut, image_qc

# Each rung multiplies the last. Three rungs from 1.0 reach 0.64 — far enough to clear
# most damage, short of the point where a look stops reading as itself.
STRENGTH_DECAY = 0.8
DEFAULT_MAX_TRIES = 3
DEFAULT_STRENGTH_FLOOR = 0.5

# Numeric assessment only. See the module docstring on cost.
DEFAULT_COST_TIER = "numeric"


class GradeLoopError(Exception):
    """Bad inputs. Damage found in the image is a result, not an error."""


def strength_schedule(
    strength: float = 1.0,
    max_tries: int = DEFAULT_MAX_TRIES,
    floor: float = DEFAULT_STRENGTH_FLOOR,
) -> List[float]:
    """Decaying strengths, stopped when the floor makes another rung identical.

    Two consecutive rungs that round to the same value would run the same LUT twice and
    read as two independent failures. One clamped rung is evidence; a repeat of it is
    not, so the schedule ends there.
    """
    start = float(min(1.0, max(0.0, strength)))
    limit = float(min(start, max(0.0, floor)))
    schedule: List[float] = []
    current = start
    for _ in range(max(1, int(max_tries))):
        rung = round(max(current, limit), 4)
        if schedule and schedule[-1] == rung:
            break
        schedule.append(rung)
        current *= STRENGTH_DECAY
    return schedule


def _normalise_times(times: Any, time_seconds: Any) -> List[float]:
    if times is None and time_seconds is None:
        raise GradeLoopError("supply times=[...] or time_seconds=<float>")
    raw = times if times is not None else time_seconds
    if isinstance(raw, (int, float)):
        raw = [raw]
    if not isinstance(raw, (list, tuple)) or not raw:
        raise GradeLoopError("times must be a non-empty list of seconds")
    out: List[float] = []
    for value in raw:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            raise GradeLoopError(f"'{value}' is not a timestamp in seconds")
        if seconds < 0:
            raise GradeLoopError("timestamps must be >= 0")
        out.append(seconds)
    return out


def _flag_ids(report: Dict[str, Any]) -> List[str]:
    return [str(flag.get("id")) for flag in report.get("flags", [])]


def plan(
    source_path: str,
    lut_path: str,
    *,
    times: Optional[Sequence[float]] = None,
    time_seconds: Optional[float] = None,
    strength: float = 1.0,
    max_tries: int = DEFAULT_MAX_TRIES,
    strength_floor: float = DEFAULT_STRENGTH_FLOOR,
    working_space: str = "rec709",
    cost_tier: str = DEFAULT_COST_TIER,
) -> Dict[str, Any]:
    """What the ladder would do, and what it would cost. Touches nothing."""
    sampled = _normalise_times(times, time_seconds)
    schedule = strength_schedule(strength, max_tries, strength_floor)
    for path in (source_path, lut_path):
        if not os.path.isfile(path):
            raise GradeLoopError(f"file not found: {path}")
    return {
        "dry_run": True,
        "source_path": source_path,
        "lut_path": lut_path,
        "times": sampled,
        "strength_schedule": schedule,
        "strength_floor": round(float(min(strength, max(0.0, strength_floor))), 4),
        "working_space": working_space,
        "cost_tier": cost_tier,
        "cost": {
            "max_assessments": len(schedule) * len(sampled),
            # assess_grade decodes the source frame and the LUT-applied frame per call.
            "max_ffmpeg_decodes": 2 * len(schedule) * len(sampled),
            "luts_written": max(0, len(schedule) - (1 if schedule and schedule[0] == 1.0 else 0)),
            "note": (
                "Worst case. The ladder stops at the first strength that clears every "
                "sampled frame, and a frame that fails ends that rung early."
            ),
        },
    }


def run(
    source_path: str,
    lut_path: str,
    *,
    times: Optional[Sequence[float]] = None,
    time_seconds: Optional[float] = None,
    strength: float = 1.0,
    max_tries: int = DEFAULT_MAX_TRIES,
    strength_floor: float = DEFAULT_STRENGTH_FLOOR,
    working_space: str = "rec709",
    cost_tier: str = DEFAULT_COST_TIER,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the ladder. Returns the converged grade, or the best attempt flagged."""
    sampled = _normalise_times(times, time_seconds)
    schedule = strength_schedule(strength, max_tries, strength_floor)
    for path in (source_path, lut_path):
        if not os.path.isfile(path):
            raise GradeLoopError(f"file not found: {path}")

    # Attenuated LUTs are derived artifacts and go to scratch, never beside the source.
    target_dir = output_dir or tempfile.mkdtemp(prefix="grade_loop_")
    os.makedirs(target_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(lut_path))[0]

    attempts: List[Dict[str, Any]] = []
    converged: Optional[Dict[str, Any]] = None

    for rung in schedule:
        if rung >= 1.0:
            candidate = lut_path
        else:
            candidate = os.path.join(target_dir, f"{base}_{int(round(rung * 1000)):04d}.cube")
            cube_lut.attenuate_file(lut_path, rung, candidate)

        frames: List[Dict[str, Any]] = []
        failing_frame: Optional[float] = None
        for seconds in sampled:
            report = image_qc.assess_grade(
                source_path,
                time_seconds=seconds,
                lut_path=candidate,
                working_space=working_space,
                cost_tier=cost_tier,
            )
            frames.append(
                {
                    "time_seconds": seconds,
                    "acceptable": bool(report.get("acceptable")),
                    "flags": _flag_ids(report),
                    "grade_shift_delta_e2000": report.get("grade_shift_delta_e2000"),
                    "report": report,
                }
            )
            if not report.get("acceptable"):
                failing_frame = seconds
                # No point measuring the rest of the frames at a strength already known
                # to fail; the next rung has to run regardless.
                break

        flags = sorted({flag for frame in frames for flag in frame["flags"]})
        shifts = [
            frame["grade_shift_delta_e2000"]
            for frame in frames
            if frame["grade_shift_delta_e2000"] is not None
        ]
        attempt = {
            "strength": rung,
            "lut_path": candidate,
            "acceptable": failing_frame is None,
            "flags": flags,
            "failing_time_seconds": failing_frame,
            "frames_measured": len(frames),
            "frames_total": len(sampled),
            "max_grade_shift_delta_e2000": round(max(shifts), 3) if shifts else None,
            "frames": frames,
        }
        attempts.append(attempt)
        if failing_frame is None:
            converged = attempt
            break

    if converged is not None:
        chosen = converged
    else:
        # Fewest flags first; ties to the gentlest grade. A shift of None sorts last so
        # an unmeasurable attempt never wins on a missing number.
        chosen = min(
            attempts,
            key=lambda item: (
                len(item["flags"]),
                item["max_grade_shift_delta_e2000"]
                if item["max_grade_shift_delta_e2000"] is not None
                else float("inf"),
            ),
        )

    remedies: List[Dict[str, str]] = []
    seen_ids = set()
    for frame in chosen["frames"]:
        for flag in frame["report"].get("flags", []):
            if flag.get("id") not in seen_ids:
                seen_ids.add(flag.get("id"))
                remedies.append(flag)

    return {
        "converged": converged is not None,
        "needs_human": converged is None,
        "acceptable": converged is not None,
        "chosen": {
            "strength": chosen["strength"],
            "lut_path": chosen["lut_path"],
            "flags": chosen["flags"],
            "remedies": remedies,
            "max_grade_shift_delta_e2000": chosen["max_grade_shift_delta_e2000"],
        },
        "attempts": [
            {key: value for key, value in attempt.items() if key != "frames"}
            for attempt in attempts
        ],
        "reports": {
            str(attempt["strength"]): [
                {"time_seconds": frame["time_seconds"], "report": frame["report"]}
                for frame in attempt["frames"]
            ]
            for attempt in attempts
        },
        "strength_schedule": schedule,
        "times": sampled,
        "source_path": source_path,
        "lut_path": lut_path,
        "output_dir": target_dir,
        "working_space": working_space,
        "cost_tier": cost_tier,
        "apply_manifest": _apply_manifest(chosen, converged is not None),
        "summary": _summary(chosen, converged is not None, schedule, attempts),
    }


def _apply_manifest(chosen: Dict[str, Any], converged: bool) -> Dict[str, Any]:
    """How to put the chosen LUT into Resolve, and whether it should be put there yet.

    The ladder does not touch the project. Applying a grade is a separate, versioned,
    confirm-gated operation, and a result carrying unresolved flags should reach a human
    before it reaches a timeline.
    """
    return {
        "lut_path": chosen["lut_path"],
        "strength": chosen["strength"],
        "safe_to_apply": converged,
        "apply_with": (
            "timeline_item_color(action='apply_lut', params={'lut_path': ..., "
            "'clip_index': ...}) — create or switch to a recoverable grade version first"
        ),
        "blocked_reason": None if converged else (
            "The grade still carries measured damage at every strength tried. Read the "
            "remedies, adjust the look, or accept it deliberately — do not apply on the "
            "strength of this report alone."
        ),
    }


def _summary(
    chosen: Dict[str, Any],
    converged: bool,
    schedule: List[float],
    attempts: List[Dict[str, Any]],
) -> str:
    if converged:
        if chosen["strength"] >= 1.0:
            return "Clean at full strength; no attenuation needed."
        # What the FIRST rung carried is the interesting part — the chosen rung is
        # clean by definition, so quoting its (empty) flag list says nothing.
        first = ", ".join(attempts[0]["flags"]) or "damage"
        return (
            f"Converged at strength {chosen['strength']}; "
            f"strength {attempts[0]['strength']} carried {first}."
        )
    return (
        f"No strength cleared every gate across {len(schedule)} attempts "
        f"({schedule[0]} down to {schedule[-1]}). Best attempt {chosen['strength']} "
        f"still carries: {', '.join(chosen['flags'])}."
    )


def capabilities() -> Dict[str, Any]:
    report = dict(image_qc.capabilities())
    report.update(
        {
            "cube_lut": cube_lut.capabilities(),
            "default_cost_tier": DEFAULT_COST_TIER,
            "cost_tiers": list(image_qc.COST_TIERS),
            "strength_decay": STRENGTH_DECAY,
            "default_max_tries": DEFAULT_MAX_TRIES,
            "default_strength_floor": DEFAULT_STRENGTH_FLOOR,
            "modes": {
                "lut": "Built and validated offline: attenuate a .cube and measure the real decoded result.",
                "live": (
                    "Not built. Applying inside the loop needs a per-rung single-frame "
                    "render from Resolve; until that is live-validated the loop returns "
                    "an apply manifest instead of driving the project."
                ),
            },
        }
    )
    return report
