"""trackIndex / mediaType validation for AppendToTimeline clipInfo rows.

Resolve takes a trackIndex that names no existing track (0, beyond the track
count) or that is not an int (``"2"``) and places the item on track 1, answering
with the new items as if the request were honoured (issue #370). The server's
own read-back then reports the wrong-track placement as verified. These checks
run before anything reaches AppendToTimeline.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

MEDIA_TYPES = {1: "video", 2: "audio"}

#: Most tracks of one type a new timeline is given to satisfy its rows. A row
#: naming a higher index is far more often a typo (99 for 9) than a build
#: that needs it, and honouring it adds that many empty tracks with success
#: (reported on #370). A build that does need more creates the timeline, adds
#: tracks with timeline add_track, then appends; append_to_timeline checks
#: rows against the tracks that exist.
MAX_NEW_TIMELINE_TRACKS = 32


def _as_int(value: Any) -> Optional[int]:
    """An int from an int, an integral float, or a digit string; else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("+-").isdigit():
            return int(text)
    return None


def coerce_track_index(value: Any, index: int) -> Tuple[Optional[int], Optional[str]]:
    """(track_index, None) or (None, message) for a clipInfo row's trackIndex."""
    ti = _as_int(value)
    if ti is None:
        return None, (
            f"clip_infos[{index}] track_index must be an integer (1-based), got {value!r}"
        )
    if ti < 1:
        return None, f"clip_infos[{index}] track_index must be >= 1 (1-based), got {ti}"
    return ti, None


def coerce_media_type(value: Any, index: int) -> Tuple[Optional[int], Optional[str]]:
    """(media_type, None) or (None, message); None in means None out."""
    if value is None:
        return None, None
    mt = _as_int(value)
    if mt not in MEDIA_TYPES:
        return None, (
            f"clip_infos[{index}] media_type must be 1 (video only) or 2 (audio only), "
            f"got {value!r}"
        )
    return mt, None


def track_count(timeline: Any, track_type: str) -> Optional[int]:
    try:
        return int(timeline.GetTrackCount(track_type) or 0)
    except Exception:
        return None


def track_range_error(timeline: Any, track_index: int, media_type: Optional[int],
                      index: int) -> Optional[dict]:
    """Refusal fields when track_index names no track on `timeline`, else None.

    With media_type set, the index is checked against that track type. Without
    it, Resolve places video on the video track and audio on the audio track of
    that index, and an audio-only or video-only clip uses only one of them, so
    only an index past both counts is refused. An unreadable count is not
    refused here.
    """
    if timeline is None:
        return None
    types = [MEDIA_TYPES[media_type]] if media_type in MEDIA_TYPES else ["video", "audio"]
    counts = {t: track_count(timeline, t) for t in types}
    if any(c is None for c in counts.values()):
        return None
    if any(track_index <= c for c in counts.values()):
        return None
    described = " and ".join(f"{c} {t}" for t, c in counts.items())
    kind = types[0] if len(types) == 1 else "video or audio"
    return {
        "message": (
            f"clip_infos[{index}] track_index {track_index} names no {kind} track: the "
            f"timeline has {described} track(s). Resolve would place the clip on track 1 "
            "and report success; nothing was appended."
        ),
        "code": "TRACK_INDEX_OUT_OF_RANGE",
        "category": "invalid_input",
        "remediation": "Add the track first (timeline add_track), or pass an existing track_index.",
        "state": {"track_index": track_index, "media_type": media_type, "track_counts": counts},
    }


def needed_tracks(rows: Any) -> Tuple[Optional[dict], Optional[str]]:
    """({"video": n, "audio": m}, None) for the tracks `rows` name, or (None, message).

    For building a new timeline from rows: each row's track_index (default 1)
    must be valid, and the timeline then needs that many tracks of the row's
    media type, or of both types when the row sets none. An index above
    MAX_NEW_TIMELINE_TRACKS is refused rather than growing the timeline to it.
    """
    needed = {"video": 1, "audio": 0}
    for i, ci in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(ci, dict):
            continue
        ti, err = coerce_track_index(ci.get("trackIndex", ci.get("track_index", 1)), i)
        if err:
            return None, err
        mt, err = coerce_media_type(ci.get("mediaType", ci.get("media_type")), i)
        if err:
            return None, err
        if ti > MAX_NEW_TIMELINE_TRACKS:
            return None, (
                f"clip_infos[{i}] track_index {ti} would give the new timeline {ti} "
                f"tracks, past the {MAX_NEW_TIMELINE_TRACKS} it adds for its rows; "
                "nothing was created. If the index is intended, create the timeline, "
                "add the tracks with timeline add_track, then use append_to_timeline."
            )
        for track_type in ([MEDIA_TYPES[mt]] if mt else ["video", "audio"]):
            needed[track_type] = max(needed[track_type], ti)
    return needed, None


def ensure_tracks(timeline: Any, needed: dict) -> Optional[str]:
    """Add tracks until `timeline` has `needed` of each type; an error message or None."""
    for track_type, count in needed.items():
        current = track_count(timeline, track_type)
        if current is None:
            return f"GetTrackCount({track_type}) failed"
        while current < count:
            try:
                ok = timeline.AddTrack(track_type)
            except Exception as exc:
                return f"AddTrack({track_type}) failed: {exc}"
            if not ok:
                return f"AddTrack({track_type}) returned false at track {current + 1}"
            current += 1
    return None
