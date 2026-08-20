"""Conform lint — the problems an online editor finds the hard way.

Conforming is where every organizational mistake made upstream finally surfaces,
usually in someone else's suite, usually after picture lock, and always at the
point when fixing it is most expensive. The failures are well known and boringly
repetitive; online editors have been writing the same list for years:

- seven stacked video layers with unused footage buried underneath, tripling the
  media the conform has to carry
- cards misnamed on set, so two different shots claim the same source timecode
  and nothing relinks
- plug-ins and NLE-specific effects that silently do not survive XML or AAF
- effects baked in so hard the online editor can no longer improve them
- Premiere's "Scale to Frame Size", whose sizing data does not travel into
  Resolve at all — every scaled shot has to be redone by hand
- dissolves with no handles behind them
- a frame rate that disagrees with the timeline it is sitting in

None of this needs a running Resolve to detect. It needs the timeline read once
and checked against a list, which is exactly the sort of thing a human stops
doing carefully at 2am on the fourth reel.

So this is a pure function over a **timeline snapshot** — a plain dict, no
Resolve object, no I/O — which is what makes it testable and what lets it run
against a snapshot captured earlier.

**It reports; it does not fix.** Most findings here are legitimate some of the
time: a shot really can run to the end of its media, a stack really can be an
intentional composite. The failure is not that these exist, it is that nobody
knew about them before turnover.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence

#: Severities. `blocker` means a turnover built on this will not conform.
SEVERITY_BLOCKER = "blocker"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

_SEVERITY_RANK = {SEVERITY_BLOCKER: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}

#: Frame-rate equality tolerance. 23.976 and 24 are *different* rates and a
#: 0.1% drift over a two-hour programme is several seconds of sync — but float
#: noise from three different APIs should not read as a mismatch.
FPS_EPSILON = 0.01

#: Effects known not to survive interchange, lowercased substrings.
_FRAGILE_EFFECT_HINTS = (
    "scale to frame size",
    "set to frame size",
    "warp stabilizer",
    "morph cut",
    "lumetri",
    "neat video",
    "sapphire",
    "red giant",
    "magic bullet",
)


def _finding(
    code: str, severity: str, summary: str, *, detail: str, items: Optional[Sequence[Any]] = None
) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "summary": summary,
        "detail": detail,
        "items": list(items or []),
    }


def _name(item: Mapping[str, Any]) -> str:
    return str(item.get("item_name") or item.get("clip_name") or "(unnamed)")


# ── individual checks ────────────────────────────────────────────────────────


def check_frame_rates(items: Sequence[Mapping[str, Any]], timeline_fps: float) -> List[Dict[str, Any]]:
    """A clip whose rate disagrees with the timeline will drift against sound."""
    offenders = []
    for item in items:
        fps = item.get("clip_fps")
        if isinstance(fps, (int, float)) and fps > 0 and abs(float(fps) - timeline_fps) > FPS_EPSILON:
            offenders.append({"item": _name(item), "clip_fps": round(float(fps), 3)})
    if not offenders:
        return []
    return [_finding(
        "FPS_MISMATCH", SEVERITY_BLOCKER,
        f"{len(offenders)} clips do not match the timeline rate ({timeline_fps})",
        detail=(
            "23.976 and 24 are different rates. Over a feature-length programme the "
            "0.1% difference is several seconds of drift against the mix, and it is "
            "usually found at the end, in the theatre. Confirm the intended rate "
            "before conforming."
        ),
        items=offenders,
    )]


def check_offline_media(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    offenders = [{"item": _name(i)} for i in items if not i.get("media_path") and not i.get("media_ref")]
    if not offenders:
        return []
    return [_finding(
        "OFFLINE_MEDIA", SEVERITY_BLOCKER,
        f"{len(offenders)} items have no media reference",
        detail=(
            "These cannot be conformed or relinked because there is nothing to "
            "relink to. Generators and titles legitimately appear here — check the "
            "list before treating it as an error."
        ),
        items=offenders,
    )]


def check_duplicate_source_timecode(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Two different sources claiming the same timecode = misnamed cards.

    This is the single most common reason a conform will not relink, and it is
    created on set, weeks before anyone finds out.
    """
    by_tc: Dict[Any, set] = defaultdict(set)
    for item in items:
        tc = item.get("source_start_timecode")
        ref = item.get("media_path") or item.get("media_ref")
        if tc and ref:
            by_tc[tc].add(ref)
    clashes = [
        {"source_timecode": tc, "distinct_sources": sorted(str(r) for r in refs)}
        for tc, refs in sorted(by_tc.items(), key=lambda kv: str(kv[0]))
        if len(refs) > 1
    ]
    if not clashes:
        return []
    return [_finding(
        "DUPLICATE_SOURCE_TC", SEVERITY_BLOCKER,
        f"{len(clashes)} source timecodes are claimed by more than one file",
        detail=(
            "Repeating timecode across differently-named sources means cards were "
            "misnamed or the camera clock was reset. A timecode-based relink cannot "
            "choose between them and will pick wrong, silently."
        ),
        items=clashes,
    )]


def check_reel_names(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    missing = [{"item": _name(i)} for i in items if i.get("media_path") and not i.get("reel_name")]
    findings: List[Dict[str, Any]] = []
    if missing:
        findings.append(_finding(
            "MISSING_REEL_NAME", SEVERITY_WARNING,
            f"{len(missing)} items carry no reel name",
            detail=(
                "EDL-based conforms match on reel name plus timecode exclusively. "
                "XML and AAF can fall back to filenames, so this is survivable — "
                "until someone downstream needs an EDL."
            ),
            items=missing,
        ))
    overlong = [
        {"item": _name(i), "reel_name": str(i["reel_name"])}
        for i in items if i.get("reel_name") and len(str(i["reel_name"])) > 8
    ]
    if overlong:
        findings.append(_finding(
            "REEL_NAME_TOO_LONG", SEVERITY_INFO,
            f"{len(overlong)} reel names exceed the 8-character CMX 3600 limit",
            detail="Fine for XML/AAF. A CMX 3600 EDL will truncate them, and truncation can collide.",
            items=overlong,
        ))
    return findings


def check_stacked_layers(items: Sequence[Mapping[str, Any]], *, max_expected_tracks: int = 3) -> List[Dict[str, Any]]:
    """Video layers fully hidden behind opaque layers above them."""
    findings: List[Dict[str, Any]] = []
    tracks = sorted({int(i.get("track_index") or 1) for i in items})
    if len(tracks) > max_expected_tracks:
        findings.append(_finding(
            "MANY_VIDEO_TRACKS", SEVERITY_INFO,
            f"{len(tracks)} video tracks in use",
            detail=(
                "Not wrong, but every layer is media the conform has to carry and "
                "the online editor has to account for. Worth confirming each one is "
                "meant to be there."
            ),
            items=[{"track_index": t} for t in tracks],
        ))

    buried: List[Dict[str, Any]] = []
    for item in items:
        idx = int(item.get("track_index") or 1)
        start, end = item.get("timeline_start_frame"), item.get("timeline_end_frame")
        if start is None or end is None:
            continue
        for other in items:
            if int(other.get("track_index") or 1) <= idx:
                continue
            if other.get("opacity") is not None and float(other["opacity"]) < 100:
                continue
            o_start, o_end = other.get("timeline_start_frame"), other.get("timeline_end_frame")
            if o_start is None or o_end is None:
                continue
            if o_start <= start and o_end >= end:
                buried.append({
                    "item": _name(item), "track_index": idx,
                    "covered_by": _name(other), "covering_track": int(other.get("track_index") or 1),
                })
                break
    if buried:
        findings.append(_finding(
            "BURIED_ITEM", SEVERITY_WARNING,
            f"{len(buried)} items are completely covered by an opaque layer above",
            detail=(
                "Invisible in the cut, but still conformed, still relinked, still "
                "carried through every turnover. Usually leftovers from an earlier "
                "version that were never cleaned up."
            ),
            items=buried,
        ))
    return findings


def check_gaps_and_overlaps(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    by_track: Dict[int, List[Mapping[str, Any]]] = defaultdict(list)
    for item in items:
        if item.get("timeline_start_frame") is None or item.get("timeline_end_frame") is None:
            continue
        by_track[int(item.get("track_index") or 1)].append(item)

    overlaps: List[Dict[str, Any]] = []
    for track, entries in sorted(by_track.items()):
        ordered = sorted(entries, key=lambda i: i["timeline_start_frame"])
        for prev, nxt in zip(ordered, ordered[1:]):
            if nxt["timeline_start_frame"] < prev["timeline_end_frame"]:
                overlaps.append({
                    "track_index": track,
                    "first": _name(prev), "second": _name(nxt),
                    "overlap_frames": prev["timeline_end_frame"] - nxt["timeline_start_frame"],
                })
    if overlaps:
        findings.append(_finding(
            "TRACK_OVERLAP", SEVERITY_WARNING,
            f"{len(overlaps)} overlapping items on the same track",
            detail=(
                "Legitimate for a dissolve, and a sign of a bad edit otherwise. "
                "Either way the overlap consumes real media on both sides — see "
                "handle checks."
            ),
            items=overlaps,
        ))
    return findings


def check_fragile_effects(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Effects that will not survive XML/AAF, or that are already baked in."""
    offenders: List[Dict[str, Any]] = []
    for item in items:
        names = item.get("effects") or []
        if isinstance(names, str):
            names = [names]
        for effect in names:
            low = str(effect).lower()
            for hint in _FRAGILE_EFFECT_HINTS:
                if hint in low:
                    offenders.append({"item": _name(item), "effect": str(effect)})
                    break
    if not offenders:
        return []
    return [_finding(
        "FRAGILE_EFFECT", SEVERITY_WARNING,
        f"{len(offenders)} effects may not survive interchange",
        detail=(
            "NLE-specific effects and plug-ins do not travel through XML or AAF. "
            "Premiere's 'Scale to Frame Size' is the classic: its sizing data does "
            "not reach Resolve at all, so every scaled shot is silently full-frame "
            "and has to be redone by hand. Decide per effect whether to bake it or "
            "hand it over as a note — but decide before turnover, not after."
        ),
        items=offenders,
    )]


def check_source_start_at_zero(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Shots starting on the first frame of their media have no head handle."""
    offenders = [
        {"item": _name(i)} for i in items
        if i.get("source_start_frame") == 0 and (i.get("media_path") or i.get("media_ref"))
    ]
    if not offenders:
        return []
    return [_finding(
        "NO_HEAD_HANDLE", SEVERITY_INFO,
        f"{len(offenders)} items start on the first frame of their source",
        detail=(
            "No media in front of the cut, so the join cannot be dissolved or "
            "slipped and audio has nothing to crossfade with. Often unavoidable — "
            "the material simply starts there — but it must be known before "
            "turnover rather than discovered in the mix."
        ),
        items=offenders,
    )]


def check_duplicate_usage(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The same source range used more than once.

    NLEs call this dupe detection and it is deliberately *not* an error — reuse
    is legitimate constantly: a recurring motif, a flashback, a montage callback.
    The editorial value is awareness. As the practice puts it: if the same moment
    serves two scenes, maybe one of the scenes does not need it.

    Only *overlapping* source ranges count. Two adjacent, non-overlapping pulls
    from one clip are simply two shots, and flagging them would make the check
    fire on every multi-take scene in existence.
    """
    by_source: Dict[Any, List[Mapping[str, Any]]] = defaultdict(list)
    for item in items:
        ref = item.get("media_path") or item.get("media_ref")
        if ref and item.get("source_start_frame") is not None:
            by_source[ref].append(item)

    dupes: List[Dict[str, Any]] = []
    for ref, entries in sorted(by_source.items(), key=lambda kv: str(kv[0])):
        spans = []
        for entry in entries:
            start = int(entry.get("source_start_frame") or 0)
            length = 0
            if entry.get("timeline_start_frame") is not None and entry.get("timeline_end_frame") is not None:
                length = int(entry["timeline_end_frame"]) - int(entry["timeline_start_frame"])
            spans.append((start, start + max(0, length), _name(entry)))
        spans.sort()
        for (a_start, a_end, a_name), (b_start, b_end, b_name) in zip(spans, spans[1:]):
            if b_start < a_end:
                dupes.append({
                    "source": str(ref),
                    "first": a_name,
                    "second": b_name,
                    "overlap_frames": min(a_end, b_end) - b_start,
                })
    if not dupes:
        return []
    return [_finding(
        "DUPLICATE_USAGE", SEVERITY_INFO,
        f"{len(dupes)} source ranges are used more than once",
        detail=(
            "Not a rule violation — just awareness. Reuse is legitimate for a "
            "recurring motif, a flashback or a montage callback. But if the same "
            "moment is serving two scenes, it is worth asking whether one of the "
            "scenes needs it."
        ),
        items=dupes,
    )]


#: Every check, in the order a human would work through them.
CHECKS = (
    check_duplicate_usage,
    check_offline_media,
    check_duplicate_source_timecode,
    check_fragile_effects,
    check_gaps_and_overlaps,
    check_reel_names,
    check_source_start_at_zero,
)


def lint_timeline(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Run every conform check over a timeline snapshot.

    `snapshot`: `{"timeline_name", "timeline_fps", "items": [...]}` where each
    item may carry `track_index`, `item_name`, `timeline_start_frame`,
    `timeline_end_frame`, `source_start_frame`, `source_start_timecode`,
    `clip_fps`, `media_path`/`media_ref`, `reel_name`, `effects`, `opacity`.

    Fields that are absent are **not checked**, and the result says which — a
    check that could not run is not a check that passed, and a lint that quietly
    skipped half its rules while reporting "clean" is worse than no lint.
    """
    items = list(snapshot.get("items") or [])
    timeline_fps = float(snapshot.get("timeline_fps") or 0) or None

    findings: List[Dict[str, Any]] = []
    if timeline_fps:
        findings.extend(check_frame_rates(items, timeline_fps))
    for check in CHECKS:
        findings.extend(check(items))
    findings.extend(check_stacked_layers(items))

    findings.sort(key=lambda f: (_SEVERITY_RANK.get(f["severity"], 9), f["code"]))
    counts = {
        severity: sum(1 for f in findings if f["severity"] == severity)
        for severity in (SEVERITY_BLOCKER, SEVERITY_WARNING, SEVERITY_INFO)
    }

    return {
        "success": True,
        "kind": "conform_lint",
        "timeline_name": snapshot.get("timeline_name"),
        "item_count": len(items),
        "finding_count": len(findings),
        "counts": counts,
        "findings": findings,
        "not_checked": _unchecked(items, timeline_fps),
        "clean": not findings,
        "note": (
            "Reports; does not fix. Most findings here are legitimate some of the "
            "time — a shot really can run to the end of its media, a stack really "
            "can be an intentional composite. The failure mode is not that they "
            "exist, it is finding out about them after picture lock."
        ),
    }


def _unchecked(items: Sequence[Mapping[str, Any]], timeline_fps: Optional[float]) -> List[str]:
    """Name the checks that could not run for want of data."""
    gaps: List[str] = []
    if not items:
        return ["every check — the snapshot contains no items"]
    if timeline_fps is None:
        gaps.append("frame-rate mismatch (no timeline_fps in the snapshot)")
    if not any(i.get("source_start_timecode") for i in items):
        gaps.append("duplicate source timecode (no source_start_timecode captured)")
    if not any(i.get("reel_name") for i in items):
        gaps.append("reel-name consistency (no reel_name captured)")
    if not any(i.get("effects") for i in items):
        gaps.append("fragile effects (no effect list captured)")
    if not any(i.get("clip_fps") for i in items):
        gaps.append("per-clip frame rates (no clip_fps captured)")
    return gaps
