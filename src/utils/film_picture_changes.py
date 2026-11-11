"""Pure film-cues/v1 comparison. No application access, reconform or file writes."""
from __future__ import annotations

from copy import deepcopy
from bisect import bisect_right
from fractions import Fraction
import hashlib
import json
import math

_MAX_INTEGER = 2**53 - 1
_TIMING_FIELDS = {"id", "start_frame", "duration_frames", "start_seconds", "duration_seconds"}


def _integer(value, field, minimum=0):
    # Unlike Resolve API values, interchange coordinates must already be JSON integers.
    if type(value) is not int or not minimum <= value <= _MAX_INTEGER:
        raise ValueError(f"{field} must be an integer in [{minimum}, {_MAX_INTEGER}]")
    return value


def _json_value(value, depth=0):
    if depth > 64:
        raise ValueError("Cue sheet JSON nesting exceeds 64")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("Cue sheet JSON object keys must be strings")
            _json_value(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _json_value(child, depth + 1)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ValueError("Cue sheets must contain only JSON values")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Cue sheet numbers must be finite")


def _validate(document, label):
    if not isinstance(document, dict) or document.get("schema") != "film-cues/v1":
        raise ValueError(f"{label} must be a film-cues/v1 object")
    _json_value(document)
    rate = document.get("frame_rate")
    if not isinstance(rate, dict):
        raise ValueError(f"{label}.frame_rate must be a rational object")
    rate = Fraction(_integer(rate.get("numerator"), "frame_rate.numerator", 1),
                    _integer(rate.get("denominator"), "frame_rate.denominator", 1))
    if rate > 1000:
        raise ValueError("Frame rate must not exceed 1000 fps")
    timeline = document.get("timeline")
    if not isinstance(timeline, dict):
        raise ValueError(f"{label}.timeline must be an object")
    _integer(timeline.get("start_frame"), "timeline.start_frame")
    if any(not isinstance(timeline.get(k), str) for k in ("name", "start_timecode")):
        raise ValueError("timeline.name and start_timecode must be strings")
    cues = document.get("cues")
    if not isinstance(cues, list) or len(cues) > 10000:
        raise ValueError("cues must be a list of at most 10000 objects")
    indexed = {}
    for cue in cues:
        if not isinstance(cue, dict):
            raise ValueError("Each cue must be an object")
        identity = cue.get("id")
        if not isinstance(identity, str) or not identity.strip() or identity in indexed:
            raise ValueError("Cue IDs must be nonempty, unique strings")
        start = _integer(cue.get("start_frame"), "cue.start_frame")
        duration = _integer(cue.get("duration_frames"), "cue.duration_frames", 1)
        _integer(start + duration, "cue exclusive end frame")
        if identity.startswith("marker:") and identity != f"marker:{start}":
            raise ValueError("Position-based marker ID must agree with its start_frame")
        if not isinstance(cue.get("name"), str):
            raise ValueError("cue.name must be a string")
        for field in ("note", "color", "custom_data"):
            if field in cue and not isinstance(cue[field], str):
                raise ValueError(f"cue.{field} must be a string")
        for field in ("start_seconds", "duration_seconds"):
            if field in cue and (type(cue[field]) not in (int, float) or cue[field] < 0):
                raise ValueError(f"cue.{field} must be a nonnegative finite number")
        indexed[identity] = cue
    try:
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Cue sheet cannot be represented as canonical JSON") from exc
    if len(encoded) > 8 * 1024 * 1024:
        raise ValueError("Cue sheet exceeds 8 MiB canonical JSON limit")
    snapshot = {"timeline": deepcopy(timeline), "frame_rate": _rational(rate),
                "fingerprint_sha256": hashlib.sha256(encoded).hexdigest()}
    return rate, indexed, snapshot


def _rational(value):
    return {"numerator": value.numerator, "denominator": value.denominator}


def _range(cue, rate):
    if cue is None:
        return None
    start = cue["start_frame"]
    end = start + cue["duration_frames"]
    return {"start_frame": start, "end_frame": end,
            "start_seconds": _rational(Fraction(start) / rate),
            "end_seconds": _rational(Fraction(end) / rate)}


def _metadata(cue):
    return {k: v for k, v in cue.items() if k not in _TIMING_FIELDS}


def compare_film_cues(before: dict, after: dict,
                      identity_map: dict[str, str] | None = None) -> dict:
    """Compare immutable cue sheets; raise ValueError for invalid input/mappings.

    Explicit mappings run before stable-ID matches. Unmapped ``marker:<frame>``
    IDs are not stable: identical records at the same clock position are only
    observations; changed records remain removals/additions requiring review.
    All ranges are half-open and relative to each sheet's picture origin.
    """
    old_rate, old, old_picture = _validate(before, "before")
    new_rate, new, new_picture = _validate(after, "after")
    compatible = old_rate == new_rate
    mapping = {} if identity_map is None else identity_map
    if not isinstance(mapping, dict):
        raise ValueError("identity_map must be an object of before IDs to after IDs")
    matches, used = {}, set()
    for source, target in mapping.items():
        if (not isinstance(source, str) or not isinstance(target, str)
                or source not in old or target not in new or target in used):
            raise ValueError("identity_map must reference existing IDs one-to-one")
        matches[source] = (target, "explicit_mapping")
        used.add(target)
    for identity in sorted(old.keys() & new.keys()):
        if identity in matches or identity.startswith("marker:"):
            continue
        if identity in used:
            raise ValueError("Explicit mapping conflicts with an implicit stable-ID match")
        matches[identity] = (identity, "stable_id")
        used.add(identity)
    position_only = []
    for identity in sorted(old.keys() & new.keys()):
        if (identity.startswith("marker:") and identity not in matches and identity not in used
                and compatible and old[identity]["start_frame"] == new[identity]["start_frame"]
                and old[identity]["duration_frames"] == new[identity]["duration_frames"]
                and _metadata(old[identity]) == _metadata(new[identity])):
            matches[identity] = (identity, "same_position_observation")
            used.add(identity)
            position_only.append(identity)
    changes, unchanged = [], 0
    for identity in sorted(old):
        previous = old[identity]
        matched = matches.get(identity)
        if matched is None:
            changes.append({"before_id": identity, "after_id": None,
                            "kinds": ["removed"], "match_basis": "unmatched",
                            "before_range": _range(previous, old_rate), "after_range": None,
                            "before_cue": deepcopy(previous), "after_cue": None})
            continue
        target, basis = matched
        current = new[target]
        frame_delta, second_delta = {}, {}
        for field, a, b in (("start", previous["start_frame"], current["start_frame"]),
                            ("end", previous["start_frame"] + previous["duration_frames"],
                             current["start_frame"] + current["duration_frames"]),
                            ("duration", previous["duration_frames"], current["duration_frames"])):
            frame_delta[field] = b - a
            second_delta[field] = Fraction(b) / new_rate - Fraction(a) / old_rate
        a_meta, b_meta = _metadata(previous), _metadata(current)
        metadata_changes = {}
        for key in sorted(a_meta.keys() | b_meta.keys()):
            if key not in a_meta or key not in b_meta or a_meta[key] != b_meta[key]:
                edit = {"before": deepcopy(a_meta.get(key)), "after": deepcopy(b_meta.get(key))}
                if key not in a_meta or key not in b_meta:
                    edit.update(before_present=key in a_meta, after_present=key in b_meta)
                metadata_changes[key] = edit
        kinds = []
        if second_delta["start"]:
            kinds.append("moved")
        if second_delta["duration"]:
            kinds.append("resized")
        if metadata_changes:
            kinds.append("metadata_edited")
        if not kinds:
            unchanged += 1
            continue
        changes.append({"before_id": identity, "after_id": target, "match_basis": basis,
                        "kinds": kinds, "delta_frames": frame_delta if compatible else None,
                        "delta_seconds": {k: _rational(v) for k, v in second_delta.items()},
                        "metadata_changes": metadata_changes,
                        "before_range": _range(previous, old_rate),
                        "after_range": _range(current, new_rate)})
    for identity in sorted(new.keys() - used):
        changes.append({"before_id": None, "after_id": identity,
                        "kinds": ["added"], "match_basis": "unmatched",
                        "before_range": None, "after_range": _range(new[identity], new_rate),
                        "before_cue": None, "after_cue": deepcopy(new[identity])})
    picture_changed = before["timeline"] != after["timeline"]
    unmatched = any(c["match_basis"] == "unmatched" for c in changes)
    return {"schema": "film-picture-changes/v1",
            "status": "compared" if compatible else "incompatible_frame_rates",
            "frame_rates_compatible": compatible, "before": old_picture, "after": new_picture,
            "picture_metadata_changed": picture_changed,
            "identity_map": deepcopy(mapping), "changes": changes, "unchanged_count": unchanged,
            "position_only_unchanged": position_only,
            "requires_human_review": bool(not compatible or picture_changed or unmatched or position_only),
            "range_basis": "half-open frames relative to each picture origin; timeline start is metadata",
            "identity_basis": "caller-stable IDs or explicit mapping; position IDs are not persistent",
            "fingerprint_basis": "SHA-256 of sorted-key compact ASCII JSON documents, not picture media",
            "media_identity_verified": False, "automatic_reconform": False}


def _picture_snapshot(snapshot, document, side, unknowns):
    if not isinstance(snapshot, dict):
        raise ValueError(f"{side}_snapshot must be an object")
    _json_value(snapshot)
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    if len(encoded) > 8 * 1024 * 1024:
        raise ValueError("Snapshot exceeds 8 MiB canonical JSON limit")
    fingerprint = hashlib.sha256(encoded).hexdigest()
    origin = snapshot.get("start_frame")
    uncertain = False

    def unknown(reason):
        nonlocal uncertain
        uncertain = True
        unknowns.append({"side": side, "reason": reason})

    try:
        _integer(origin, "snapshot.start_frame")
    except ValueError:
        origin = None
        unknown("Snapshot origin is unavailable")
    if origin is not None and origin != document["timeline"]["start_frame"]:
        raise ValueError(f"{side} cue sheet/snapshot origins differ")
    if snapshot.get("name") is not None and snapshot["name"] != document["timeline"]["name"]:
        raise ValueError(f"{side} cue sheet/snapshot names differ")
    tracks = snapshot.get("tracks")
    video = tracks.get("video") if isinstance(tracks, dict) else None
    if not isinstance(video, dict) or not isinstance(video.get("tracks"), list):
        unknown("Video track enumeration is unavailable")
        return {}, origin, fingerprint, uncertain
    if type(video.get("track_count")) is not int or video["track_count"] != len(video["tracks"]):
        unknown("Video track count is missing or inconsistent")
    indexed, total = {}, 0
    for track in video["tracks"]:
        if not isinstance(track, dict):
            unknown("Video track is unreadable")
            continue
        index = _integer(track.get("track_index"), "video.track_index", 1)
        if index in indexed:
            raise ValueError("Duplicate video track index")
        items = track.get("items")
        if not isinstance(items, list):
            unknown(f"Video track {index} item enumeration is unavailable")
            items = []
        if type(track.get("item_count")) is not int or track["item_count"] != len(items):
            unknown(f"Video track {index} item count is missing or inconsistent")
        total += len(items)
        if total > 10000:
            raise ValueError("Snapshot exceeds 10000 video items")
        indexed[index] = items
    return indexed, origin, fingerprint, uncertain


def _picture_item(item, origin):
    """Return relative span/signature and evidence completeness, without matching."""
    if not isinstance(item, dict):
        return None, None, True
    try:
        start = _integer(item.get("start"), "video item start")
        end = _integer(item.get("end"), "video item end")
        if origin is None or end <= start:
            raise ValueError("Unknown video interval")
        span = (start - origin, end - origin)
    except ValueError:
        span = None
    incomplete = span is None
    for key in ("source_start", "source_end", "source_fps"):
        value = item.get(key)
        if (type(value) not in (int, float) or not math.isfinite(value)
                or (key == "source_fps" and value <= 0)):
            incomplete = True
    if not isinstance(item.get("file_path"), str) or not item["file_path"]:
        incomplete = True
    # Duplicating timelines or reimporting media regenerates object IDs. They
    # are not picture content; array position already supplies enumeration.
    ignored = {"timeline_item_id", "item_index"}
    if isinstance(item.get("file_path"), str) and item["file_path"]:
        ignored.add("media_pool_item_id")
    # Keep the path itself: ignoring a pool ID never equates different paths.
    signature = {key: value for key, value in item.items() if key not in ignored}
    if span is not None:
        signature.update(start=span[0], end=span[1])
    return span, signature, incomplete


def _impacted_cues(cues, spans, unlocated):
    if unlocated:
        return sorted(cues)
    # Merge only for intersection lookup; the report retains every changed slot.
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    ends = [end for _, end in merged]
    affected = []
    for identity, cue in sorted(cues.items()):
        index = bisect_right(ends, cue["start_frame"])
        if index < len(merged) and merged[index][0] < cue["start_frame"] + cue["duration_frames"]:
            affected.append(identity)
    return affected


def compare_picture_impact(before: dict, after: dict, before_snapshot: dict,
                           after_snapshot: dict, editorial_comparison: dict) -> dict:
    """Conservative structural impact by track/array slot, never clip identity.

    Main supplies the existing conform comparison. Unknown unlocatable spans
    make every cue on that side potentially affected; unknown source coordinates
    with known timeline spans mark just those spans. No application calls occur.
    """
    old_rate, old_cues, _ = _validate(before, "before")
    new_rate, new_cues, _ = _validate(after, "after")
    if not isinstance(editorial_comparison, dict):
        raise ValueError("editorial_comparison must be an object")
    _json_value(editorial_comparison)
    unknowns = []
    old, old_origin, old_hash, old_uncertain = _picture_snapshot(before_snapshot, before, "before", unknowns)
    new, new_origin, new_hash, new_uncertain = _picture_snapshot(after_snapshot, after, "after", unknowns)
    compatible = old_rate == new_rate
    ranges, spans = [], {"before": [], "after": []}
    unlocated = {"before": old_uncertain, "after": new_uncertain}
    for track in sorted(old.keys() | new.keys()):
        a_items, b_items = old.get(track, []), new.get(track, [])
        for index in range(max(len(a_items), len(b_items))):
            entries = []
            for side, items, origin, rate in (("before", a_items, old_origin, old_rate),
                                              ("after", b_items, new_origin, new_rate)):
                if index >= len(items):
                    entries.append(None)
                    continue
                span, signature, incomplete = _picture_item(items[index], origin)
                entries.append((span, signature, incomplete, side, rate))
                if incomplete:
                    unknowns.append({"side": side, "track_index": track, "item_index": index,
                                     "reason": "Video item has unknown timeline/source coordinates or media path"})
                if span is None:
                    unlocated[side] = True
            left, right = entries
            changed = (left is None or right is None or not compatible
                       or left[2] or right[2] or left[1] != right[1])
            if not changed:
                continue
            for entry in entries:
                if entry is None or entry[0] is None:
                    continue
                (start, end), _, incomplete, side, rate = entry
                spans[side].append((start, end))
                ranges.append({"side": side, "track_index": track, "item_index": index,
                               "start_frame": start, "end_frame": end,
                               "start_seconds": _rational(Fraction(start) / rate),
                               "end_seconds": _rational(Fraction(end) / rate),
                               "evidence_status": "unknown" if incomplete else "structural_change"})
    return {"schema": "film-picture-impact/v1",
            "status": "unknown" if unknowns else "compared" if compatible else "incompatible_frame_rates",
            "frame_rates_compatible": compatible,
            "before_affected_cue_ids": _impacted_cues(old_cues, spans["before"], unlocated["before"]),
            "after_affected_cue_ids": _impacted_cues(new_cues, spans["after"], unlocated["after"]),
            "changed_ranges": ranges, "unknowns": unknowns,
            "unlocated_impact": unlocated,
            "before_snapshot_fingerprint": old_hash, "after_snapshot_fingerprint": new_hash,
            "editorial_comparison": deepcopy(editorial_comparison),
            "requires_human_review": bool(ranges or unknowns or not compatible),
            "comparison_basis": "video track index and array position only; both sides of changed slots",
            "range_basis": "half-open frames relative to each snapshot origin, intersected with that version's cues",
            "fingerprint_basis": "SHA-256 of complete sorted-key compact ASCII JSON snapshots, not media bytes",
            "structural_only": True, "media_identity_verified": False,
            "grade_effects_verified": False, "clip_correspondence_inferred": False,
            "automatic_reconform": False}
