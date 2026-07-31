"""One frame per setup — the cutting-room wall of stills.

The practice is to pin a representative frame from every setup around the
cutting room, so
the whole film is visible at a glance rather than only through the keyhole of a
timeline. It is a different way of seeing the same material: scale and shape
become obvious, repetition becomes obvious, and a sequence that is all one size
becomes obvious in a way scrubbing never makes it.

`timeline.thumbnail_contact_sheet` already renders frames — but per **shot**,
which on a 200-shot timeline produces 200 thumbnails and reproduces the keyhole
at higher resolution. The practice is per **setup**: one frame for each
distinct camera position, so twenty images stand for the whole film.

## Two decisions worth stating

**Which frame.** From the middle of the *longest* usage of that setup. Heads and
tails catch fades, slates and handles; the longest usage is the one the audience
spends most time in, so it is the one that should represent it.

**What order.** By first appearance, so the sheet reads in the same direction
the film does. Sorting alphabetically or by duration would produce a tidier grid
that tells you nothing about shape.

## The grouping is a proxy and says so

Resolve does not expose "lighting setup". Reel name is used where present and
the containing folder otherwise — both usually track a camera roll, which
usually tracks a setup. Usually. An editor regrouping by eye will beat this, and
the output says so rather than presenting the grouping as fact.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Sequence


def setup_key(item: Mapping[str, Any]) -> str:
    """Best available proxy for "which camera setup is this"."""
    reel = item.get("reel_name")
    if reel:
        return str(reel)
    path = item.get("media_path")
    if path:
        folder = os.path.basename(os.path.dirname(str(path)))
        if folder:
            return folder
    return "ungrouped"


def select_representatives(
    items: Sequence[Mapping[str, Any]],
    *,
    fps: float = 24.0,
) -> Dict[str, Any]:
    """One representative frame per setup, ordered by first appearance."""
    if not items:
        return {"success": False, "error": "No timeline items supplied"}

    groups: Dict[str, List[Mapping[str, Any]]] = {}
    unusable: List[Dict[str, Any]] = []
    for item in items:
        start = item.get("timeline_start_frame")
        end = item.get("timeline_end_frame")
        if start is None or end is None or int(end) <= int(start):
            unusable.append({
                "item": item.get("item_name"),
                "reason": "no usable timeline range — NOT represented on the sheet",
            })
            continue
        groups.setdefault(setup_key(item), []).append(item)

    representatives: List[Dict[str, Any]] = []
    for setup, members in groups.items():
        longest = max(
            members,
            key=lambda i: int(i["timeline_end_frame"]) - int(i["timeline_start_frame"]),
        )
        start = int(longest["timeline_start_frame"])
        end = int(longest["timeline_end_frame"])
        # Middle of the longest usage: heads and tails catch fades, slates and
        # handles, none of which represent the shot.
        middle = start + (end - start) // 2
        source_start = int(longest.get("source_start_frame") or 0)
        first_appearance = min(int(m["timeline_start_frame"]) for m in members)
        representatives.append({
            "setup": setup,
            "item_name": longest.get("item_name"),
            "media_path": longest.get("media_path"),
            "timeline_frame": middle,
            "source_frame": source_start + (middle - start),
            "source_seconds": round((source_start + (middle - start)) / fps, 3) if fps else None,
            "shot_count": len(members),
            "first_appearance_frame": first_appearance,
            "longest_usage_frames": end - start,
        })

    representatives.sort(key=lambda r: r["first_appearance_frame"])
    return {
        "success": True,
        "kind": "setup_sheet",
        "setup_count": len(representatives),
        "shot_count": sum(r["shot_count"] for r in representatives),
        "representatives": representatives,
        "unusable": unusable,
        "grouping_basis": (
            "reel name where present, else containing folder — a PROXY for lighting "
            "setup. Resolve does not expose setup directly. An editor regrouping by "
            "eye will beat this."
        ),
        "note": (
            f"{len(representatives)} setups standing for "
            f"{sum(r['shot_count'] for r in representatives)} shots, ordered by first "
            "appearance so the sheet reads in the direction the film does. Each frame "
            "comes from the middle of that setup's longest usage — heads and tails "
            "catch fades, slates and handles."
            + (f" {len(unusable)} items had no usable range and are NOT on the sheet."
               if unusable else "")
        ),
    }
