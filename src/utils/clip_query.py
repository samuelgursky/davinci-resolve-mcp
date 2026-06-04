"""Safe declarative clip-query DSL.

The agent-facing way to ask "which clips match X?" without enumerating a whole
timeline call-by-call. Named filters only — no arbitrary lambdas/code cross the
tool boundary (the brain gets a closed vocabulary, not `eval`).

Pure: `filter_clips` takes a list of plain clip dicts + a filter dict and returns
the matching subset. The live MCP adapter gathers clip dicts from the timeline
and calls this.

Each clip dict is expected to carry (best-effort; missing keys are tolerated):
    name, track_type, track_index, duration (frames), in_frame, out_frame,
    clip_id / media_pool_item_id, clip_hash, marker_color, analyzed (bool),
    has_transcription (bool), shot_type (str).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Supported filter keys and a one-line description (also used to validate input
# and to document the surface in the tool docstring).
SUPPORTED_FILTERS: Dict[str, str] = {
    "track_type": "exact match: 'video' | 'audio' | 'subtitle'",
    "track_index": "exact 1-based track index",
    "name_contains": "case-insensitive substring of the clip name",
    "duration_lt": "duration (frames) strictly less than",
    "duration_gt": "duration (frames) strictly greater than",
    "marker_color": "exact clip marker/flag color",
    "shot_type": "exact analyzed shot_type",
    "analyzed": "bool — clip has an analysis record",
    "has_transcription": "bool — clip has transcription",
}


def validate_filters(filters: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return (ok, unknown_keys). Unknown filter keys are rejected, not ignored,
    so a typo never silently widens the match set."""
    unknown = [k for k in filters if k not in SUPPORTED_FILTERS]
    return (not unknown, unknown)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _matches(clip: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    if "track_type" in filters and clip.get("track_type") != filters["track_type"]:
        return False
    if "track_index" in filters and clip.get("track_index") != int(filters["track_index"]):
        return False
    if "name_contains" in filters:
        needle = str(filters["name_contains"]).lower()
        if needle not in str(clip.get("name") or "").lower():
            return False
    dur = clip.get("duration")
    if "duration_lt" in filters:
        if dur is None or not (dur < float(filters["duration_lt"])):
            return False
    if "duration_gt" in filters:
        if dur is None or not (dur > float(filters["duration_gt"])):
            return False
    if "marker_color" in filters and clip.get("marker_color") != filters["marker_color"]:
        return False
    if "shot_type" in filters and clip.get("shot_type") != filters["shot_type"]:
        return False
    if "analyzed" in filters and bool(clip.get("analyzed")) != _as_bool(filters["analyzed"]):
        return False
    if "has_transcription" in filters and bool(clip.get("has_transcription")) != _as_bool(
        filters["has_transcription"]
    ):
        return False
    return True


def filter_clips(clips: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the subset of `clips` matching every supplied filter (AND semantics).

    Empty/None filter values are skipped so callers can pass a sparse dict.
    """
    active = {k: v for k, v in (filters or {}).items() if v is not None and v != ""}
    return [c for c in clips if _matches(c, active)]
