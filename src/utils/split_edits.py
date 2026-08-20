"""Split edits — sound leads picture, made measurable.

**The ear is faster than the eye.** Sound arrives at the audience ahead of
picture and is processed ahead of it, which is why the classical advice is to
consider the cut as a sound event first. Sound can pre-lap into the next scene and pull the
audience forward, linger from the previous one and create resonance, or carry
continuity across images that have none.

The split edit is that principle made concrete, and it is one of the few classical
positions that is a straightforward measurement:

| Shape | What happens | Effect |
|---|---|---|
| **L-cut** | Audio from the *outgoing* shot continues under the incoming picture | Lingers; creates resonance and continuity |
| **J-cut** | Audio from the *incoming* shot starts under the outgoing picture | Pre-laps; pulls the audience forward |
| **Straight** | Audio and picture cut together | Neutral, and the NLE default |

## Why the ratio is the finding

A timeline of nothing but straight cuts is worth knowing about. It is what an
NLE produces when nobody has thought about sound: every audio edit sitting
exactly on its picture edit because that is where the software put it. It is
rarely what an editor wants and almost never what a dialogue scene wants.

**There is no correct ratio and this module does not suggest one.** It reports
the distribution. An editor reads that instantly; a prescription would be
nonsense across a montage, a dialogue two-hander and a documentary interview.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

#: Audio and picture edits within this many frames of each other are the same
#: join. Wider than a frame or two because audio edits get nudged by hand and a
#: two-frame offset is not a deliberate split edit.
PAIRING_WINDOW_FRAMES = 48

#: Below this the offset is a nudge, not an intent. A one-frame audio slip is
#: not sound leading picture; it is somebody trimming.
MIN_SPLIT_FRAMES = 3

SHAPE_L = "L-cut"
SHAPE_J = "J-cut"
SHAPE_STRAIGHT = "straight"


def _edit_points(items: Sequence[Mapping[str, Any]]) -> List[int]:
    """Cut points on a track — every boundary where one item meets the next."""
    frames = set()
    for item in items:
        for key in ("timeline_start_frame", "timeline_end_frame"):
            value = item.get(key)
            if value is not None:
                frames.add(int(value))
    return sorted(frames)


def classify_joins(
    video_items: Sequence[Mapping[str, Any]],
    audio_items: Sequence[Mapping[str, Any]],
    *,
    fps: float = 24.0,
    pairing_window: int = PAIRING_WINDOW_FRAMES,
    min_split: int = MIN_SPLIT_FRAMES,
) -> Dict[str, Any]:
    """Pair each picture edit with the nearest audio edit and classify the shape.

    An unpaired picture edit is reported as `unpaired`, **not** as a straight
    cut: no audio edit anywhere near a picture cut usually means the audio runs
    continuously across it, which is a different and much stronger form of sound
    carrying picture than a straight cut is.
    """
    picture = _edit_points(video_items)
    sound = _edit_points(audio_items)
    joins: List[Dict[str, Any]] = []
    unpaired: List[int] = []

    for cut in picture:
        if not sound:
            unpaired.append(cut)
            continue
        nearest = min(sound, key=lambda s: abs(s - cut))
        offset = nearest - cut
        if abs(offset) > pairing_window:
            unpaired.append(cut)
            continue
        if abs(offset) < min_split:
            shape, meaning = SHAPE_STRAIGHT, "audio and picture cut together"
        elif offset > 0:
            # Audio edit is LATER than picture: outgoing sound continues under
            # the incoming image.
            shape, meaning = SHAPE_L, "outgoing audio continues under the new picture — lingers"
        else:
            # Audio edit is EARLIER: incoming sound starts under the outgoing
            # image.
            shape, meaning = SHAPE_J, "incoming audio starts under the old picture — pulls forward"
        joins.append({
            "picture_frame": cut,
            "audio_frame": nearest,
            "offset_frames": offset,
            "offset_seconds": round(offset / fps, 3) if fps else None,
            "shape": shape,
            "meaning": meaning,
        })

    counts = {
        shape: sum(1 for j in joins if j["shape"] == shape)
        for shape in (SHAPE_L, SHAPE_J, SHAPE_STRAIGHT)
    }
    return {
        "joins": joins,
        "counts": counts,
        "unpaired_picture_cuts": unpaired,
        "paired_count": len(joins),
    }


def audit(
    video_items: Sequence[Mapping[str, Any]],
    audio_items: Sequence[Mapping[str, Any]],
    *,
    fps: float = 24.0,
) -> Dict[str, Any]:
    """Report the split-edit distribution across a timeline."""
    if not video_items:
        return {"success": False, "error": "No video items supplied"}
    if not audio_items:
        return {
            "success": False,
            "error": "No audio items supplied — split edits cannot be assessed",
            "remediation": (
                "Pass the timeline's audio track items. Without them this cannot "
                "tell a straight cut from an unexamined one, and reporting 'all "
                "straight' would be a fabrication."
            ),
        }

    result = classify_joins(video_items, audio_items, fps=fps)
    counts = result["counts"]
    splits = counts[SHAPE_L] + counts[SHAPE_J]
    paired = result["paired_count"]
    findings: List[Dict[str, Any]] = []

    if paired >= 8 and splits == 0:
        findings.append({
            "criterion": "rhythm",
            "scope": "sequence",
            "at": result["joins"][0]["picture_frame"] if result["joins"] else 0,
            "summary": f"all {paired} joins are straight cuts — sound never leads picture",
            "detail": (
                "Every audio edit sits on its picture edit, which is where the NLE "
                "puts them by default. The ear is faster than the eye: an L-cut lets "
                "the outgoing line breathe under the new image, a J-cut pulls the "
                "audience into the next scene before they see it. A dialogue "
                "sequence with no split edits anywhere is usually one nobody has "
                "listened to yet."
            ),
        })

    return {
        "success": True,
        "kind": "split_edit_audit",
        "paired_joins": paired,
        "counts": counts,
        "split_ratio": round(splits / paired, 3) if paired else None,
        "unpaired_picture_cuts": len(result["unpaired_picture_cuts"]),
        "joins": result["joins"],
        "findings": findings,
        "note": (
            f"{counts[SHAPE_L]} L-cuts, {counts[SHAPE_J]} J-cuts, "
            f"{counts[SHAPE_STRAIGHT]} straight across {paired} paired joins"
            + (f"; {len(result['unpaired_picture_cuts'])} picture cuts had no audio "
               "edit nearby, which usually means sound runs continuously across them"
               if result["unpaired_picture_cuts"] else "")
            + ". There is NO correct ratio and none is suggested — a montage, a "
            "two-hander and an interview all want different distributions. This is "
            "a reading, not a score."
        ),
    }
