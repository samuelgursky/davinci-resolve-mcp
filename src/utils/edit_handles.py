"""Handle accounting for cut plans — the media beyond an edit point.

A "handle" is source media that exists either side of what a timeline actually
uses. Nobody sees it in the cut, and that is exactly why it gets forgotten and
why forgetting it is expensive.

Every downstream department needs it:

- **Color** needs room to slip a shot a few frames, and dissolves consume real
  media on both sides of the join.
- **VFX** needs overlap to track into and out of — 8-24 frames is the usual ask.
- **Sound** needs far more, 48-120 frames, because crossfades, room-tone fills
  and dialogue overlaps all reach past the picture cut.

An automatic tighten does not know any of this. It optimizes for removing
silence, and a keep-range that begins on the first frame of a clip is, to that
objective, a perfect result. It is also a turnover that cannot be dissolved,
slipped, or crossfaded — and the discovery happens weeks later, in someone
else's suite, after picture lock, when fixing it is at its most expensive.

So this reports rather than blocks. Cutting to the very head or tail of a clip
is often legitimate and unavoidable — the material simply ends there. What is
not legitimate is finding out about it downstream. The contract is: no plan
silently ships zero handles.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

#: Picture handles. The low end of what VFX and color conventionally ask for;
#: below this a dissolve at the join has nothing to dissolve with.
DEFAULT_PICTURE_HANDLE_FRAMES = 8
#: Audio handles are much larger because crossfades, room tone and dialogue
#: overlap all reach well past the picture cut. 48 frames is 2s at 24fps.
DEFAULT_AUDIO_HANDLE_FRAMES = 48


def handle_floor_for(track_type: Optional[str]) -> int:
    """Frames of source media a keep range should leave spare on each side."""
    if str(track_type or "").strip().lower() == "audio":
        return DEFAULT_AUDIO_HANDLE_FRAMES
    return DEFAULT_PICTURE_HANDLE_FRAMES


def check_keep_range_handles(
    keep_ranges: Iterable[Mapping[str, Any]],
    *,
    source_bounds: Mapping[Any, int],
    picture_handle_frames: int = DEFAULT_PICTURE_HANDLE_FRAMES,
    audio_handle_frames: int = DEFAULT_AUDIO_HANDLE_FRAMES,
) -> Dict[str, Any]:
    """Report keep ranges that leave too little source media either side.

    `source_bounds` maps a clip id to that clip's total length in source frames.
    A clip missing from it is reported as `unknown` rather than assumed fine —
    an unmeasured handle is not a passing handle, and quietly treating it as one
    is how a turnover ships broken.
    """
    violations: List[Dict[str, Any]] = []
    unknown: List[Dict[str, Any]] = []
    checked = 0

    for rng in keep_ranges:
        clip_id = rng.get("clip_id")
        track_type = rng.get("track_type")
        floor = audio_handle_frames if str(track_type or "").lower() == "audio" else picture_handle_frames
        try:
            start = int(rng.get("start_frame"))
            end = int(rng.get("end_frame"))
        except (TypeError, ValueError):
            unknown.append({"clip_id": clip_id, "reason": "keep range has no usable frame bounds"})
            continue

        total = source_bounds.get(clip_id)
        if total is None:
            unknown.append({
                "clip_id": clip_id,
                "track_type": track_type,
                "reason": "source length unknown — handles could NOT be verified",
            })
            continue

        checked += 1
        head = start
        tail = int(total) - end
        if head >= floor and tail >= floor:
            continue
        violations.append({
            "clip_id": clip_id,
            "track_type": track_type,
            "start_frame": start,
            "end_frame": end,
            "head_frames": head,
            "tail_frames": tail,
            "required_frames": floor,
            "short_at": (
                "both" if head < floor and tail < floor
                else "head" if head < floor else "tail"
            ),
        })

    clean = not violations and not unknown
    return {
        "clean": clean,
        "checked_range_count": checked,
        "picture_handle_frames": picture_handle_frames,
        "audio_handle_frames": audio_handle_frames,
        "violation_count": len(violations),
        "violations": violations,
        "unverified": unknown,
        "note": _summarize(violations, unknown, checked),
    }


def check_seconds_ranges(
    keep_ranges: Iterable[Mapping[str, Any]],
    *,
    source_duration_seconds: Optional[float],
    fps: float = 24.0,
    picture_handle_frames: int = DEFAULT_PICTURE_HANDLE_FRAMES,
) -> Dict[str, Any]:
    """Handle check for seconds-based keep ranges (the word-level cut path).

    The transcript planner works in seconds against a single clip rather than in
    frames across many, so it needs its own entry point — but the same rule. A
    word-level tighten that begins on the first syllable of a clip leaves a join
    with nothing behind it, exactly like a silence-driven one does, and the fact
    that it was decided from a transcript rather than a waveform does not give
    sound anything to crossfade with.
    """
    floor_seconds = picture_handle_frames / fps if fps else 0.0
    if source_duration_seconds is None:
        return {
            "clean": False,
            "checked_range_count": 0,
            "violations": [],
            "unverified": [{"reason": "source duration unknown — handles could NOT be verified"}],
            "required_seconds": round(floor_seconds, 3),
            "note": "Source length unknown, so handles were not checked. Unverified is not clean.",
        }

    violations: List[Dict[str, Any]] = []
    checked = 0
    for rng in keep_ranges:
        start = rng.get("start", rng.get("start_seconds"))
        end = rng.get("end", rng.get("end_seconds"))
        if start is None or end is None:
            continue
        checked += 1
        head = float(start)
        tail = float(source_duration_seconds) - float(end)
        if head >= floor_seconds and tail >= floor_seconds:
            continue
        violations.append({
            "start_seconds": round(float(start), 3),
            "end_seconds": round(float(end), 3),
            "head_seconds": round(head, 3),
            "tail_seconds": round(tail, 3),
            "required_seconds": round(floor_seconds, 3),
            "short_at": (
                "both" if head < floor_seconds and tail < floor_seconds
                else "head" if head < floor_seconds else "tail"
            ),
        })
    return {
        "clean": not violations,
        "checked_range_count": checked,
        "violation_count": len(violations),
        "violations": violations,
        "unverified": [],
        "required_seconds": round(floor_seconds, 3),
        "note": (
            f"All {checked} kept ranges leave at least {floor_seconds:.2f}s either side."
            if not violations else
            f"{len(violations)} of {checked} kept ranges sit within {floor_seconds:.2f}s of "
            "the clip edge. Those joins cannot be dissolved or crossfaded. Often "
            "unavoidable at the head or tail of a clip — but it must be known before "
            "turnover, not discovered in the mix."
        ),
    }


def _summarize(violations: List[Dict[str, Any]], unknown: List[Dict[str, Any]], checked: int) -> str:
    if not violations and not unknown:
        return (
            f"All {checked} keep ranges leave usable handles. Dissolves, slips and "
            "audio crossfades have media to work with at every join."
        )
    parts: List[str] = []
    if violations:
        heads = sum(1 for v in violations if v["short_at"] in ("head", "both"))
        tails = sum(1 for v in violations if v["short_at"] in ("tail", "both"))
        parts.append(
            f"{len(violations)} of {checked} keep ranges are short of handles "
            f"({heads} at the head, {tails} at the tail). These joins cannot be "
            "dissolved or slipped downstream, and audio has no room to crossfade. "
            "Often unavoidable when a shot runs to the end of its media — but it "
            "must be known before turnover, not discovered in the mix."
        )
    if unknown:
        parts.append(
            f"{len(unknown)} keep ranges could NOT be checked (source length "
            "unknown). Unverified is not the same as clean."
        )
    return " ".join(parts)
