#!/usr/bin/env python3
"""
aaf_probe — offline AAF (.aaf) reader for the editorial `parse_interchange` /
`list_sequences` picker+preview.

AAF is a binary Structured-Storage container; there is no pure-JS reader worth
trusting, so the Node server shells out to this helper, which uses the pure-Python
`aaf2` library (pyaaf2). It emits ONE JSON object on stdout:

    {
      "ok": true,
      "sequences": [
        { "id": <mob-id str>, "name": <str>, "eventCount": <int>,
          "startTimecode": <"HH:MM:SS:FF"|null>, "startFrame": <int|null>,
          "startTimecodeFps": <int|null>, "startTimecodeDrop": <bool|null>,
          "unhandled": { "<ComponentClass>": <int>, ... },
          "effectsWithoutEvents": { "<OperationName>": <int>, ... },
          "events": [ {normalized-event}, ... ] }
      ]
    }

Normalized event shape mirrors resolve-advanced/server/editorial.mjs `evt()`:
    { index, track, source, srcIn, srcOut, recIn, recOut, speed, reverse, transition, fps }

Retime (motion-effect) events additionally carry `"effect"` and, when the ratio is
recoverable from the OperationGroup's parameters (see _retime_fields):
  * constant ratio  → `"speedRatio"`: play-rate float (1.75 = 175%), `"speed"`:
                      round(playRate*100), `"reverse"`: true for backwards play.
  * variable speed  → `"speedVarying": true` and speed stays 100 — a timewarp has
                      no single honest number, so none is fabricated.
  * unrecoverable   → the flag alone, speed stays 100 (unchanged old contract).
For retimes, srcIn/srcOut are the SOURCE-side range while recIn/recOut span the
OperationGroup's DECLARED (record) length — they differ by the ratio.

KEYFRAMES (U21). A VaryingValue is a curve, and it used to be read for its values
alone — enough to say "this animates", never enough to rebuild it. Curves now ship:
  * transform stages   → `geometry[i].keyframes[<AvidParamName>]`
  * retimes            → `speedCurve.playRate` / `speedCurve.sourceOffset`
each `{ interpolation, domain, effectLength, points: [{t, v, frame}] }`. 🚨 The two
families do NOT share a time domain — `domain` names which one applies:
  * "effectSpan"   → frame = t x (effectLength - 1)   (transform parameters)
  * "effectFrames" → frame = t                        (speed maps, already frames)
Keys outside 0..1 are real (a clip trimmed after it was animated) and are kept, and
a frame may be fractional. A curve with ONE unreadable point is refused whole.
Retimes also carry `"speedRatioFromCurve"` when the offset curve is straight — the
declared SpeedRatio rational is the source span truncated to WHOLE FRAMES and is
wrong by up to 4% on real material, so both numbers ship under their own names.

TRANSFORM OPS WE DO NOT INTERPRET (U22) get a stage marked `"passthrough": true`
whose numbers sit in `"rawParams"`, never `"params"` — the same parameter NAME
carries different units on different operations, so there is nothing to normalize
and nothing a consumer may safely compose. See _PASSTHROUGH_GEOMETRY_OPS.

Honest-refuse discipline (no fake parses):
  * exit 3  → pyaaf2 not installed        (stderr: AAF_PROBE_NO_PYAAF2)
  * exit 4  → file unreadable / not an AAF (stderr: AAF_PROBE_UNREADABLE: <detail>)
  * exit 2  → bad invocation
Per-sequence event extraction is best-effort and defensive: if a component can't
be decoded we still report the sequence with its clip count — we never fabricate.

`unhandled` is the teeth behind that promise. A structural miss (a component class
this walker does not model) used to be swallowed silently, so a whole multi-layer
timeline could come back as `ok:true` with `eventCount: 0` — indistinguishable from
an genuinely empty sequence, and worse than an honest refusal because downstream
consumers gate on `ok`. Every component we skip is now counted by class name and
reported per sequence, so a miss is VISIBLE without changing the exit-code contract.

`effectsWithoutEvents` (U23) closes the hole `unhandled` structurally cannot see.
An effect can be modelled PERFECTLY and still produce nothing: an OperationGroup is
walked, its inputs are walked, and they contain no SourceClip. On the reference
turnover `unhandled` reads `{}` — a complete parse — while 29 SubCap title effects
occupy real record time and reach the consumer as nothing at all. Each such group is
counted once, against the innermost operation that caused it.

Segment model (Avid Media Composer picture turnovers):
  * NestedScope  — a multi-layer video track. Its `.slots` are the layers (V1..Vn);
                   it has NO `.components`. Layers are PARALLEL, so each layer's
                   record position restarts at 0.
  * Sequence     — ordered `.components`, laid end to end.
  * OperationGroup — effect wrapper. Its `.segments` are the effect INPUTS, and the
                   primary input is usually a nested Sequence (not a bare SourceClip).
                   Its `.parameters` carry the retime ratio for motion effects, and
                   its own declared length is the RECORD duration of the effect.
  * Selector     — an enabled/disabled layer variant; the live one is `Selected`.
  * ScopeReference — "show the NestedScope layer beneath me": real record time, no
                   clip of this layer's own. Treated as a gap, like Filler.
  * Transition   — a dissolve/wipe that OVERLAPS its neighbours. It does not occupy
                   record time of its own; it CONSUMES it. See _walk_components.

Retimes additionally carry `"effect"`/`"speedRatio"`; clips wrapped in an Avid transform
effect carry `"geometry"` (see _geometry_fields).
"""

import json
import os
import re
import sys


def _fps_from_edit_rate(edit_rate):
    try:
        return round(float(edit_rate), 6)
    except Exception:
        return None


# How far to chase the mob reference chain looking for a named mob (see _source_name).
_MAX_MOB_CHASE = 8


def _usable_name(obj):
    """A real name, or None. pyaaf2 returns the CLASS NAME for an unset `.name`, so a
    value equal to the object's type name means "absent", not a source called SourceClip."""
    try:
        v = getattr(obj, "name", None)
    except Exception:
        return None
    if not v:
        return None
    text = str(v).strip()
    if not text or text == type(obj).__name__:
        return None
    return text


def _find_source_clip(segment, depth=0):
    """First SourceClip inside an arbitrary segment tree (bounded)."""
    if segment is None or depth > 8:
        return None
    cls = type(segment).__name__
    if cls == "SourceClip":
        return segment
    if cls == "Selector":
        return _find_source_clip(_selector_selected(segment), depth + 1)
    if cls == "Sequence":
        children = getattr(segment, "components", None) or []
    elif cls == "OperationGroup":
        children = getattr(segment, "segments", None) or []
    elif cls == "NestedScope":
        children = _nested_layers(segment)
    else:
        return None
    for child in children:
        found = _find_source_clip(child, depth + 1)
        if found is not None:
            return found
    return None


def _hop_referenced_clip(mob, ref_clip):
    """The next SourceClip down the mob chain — through the slot the REFERENCE
    names, resolved AT the reference's offset. Returns (clip, position_adjust)
    or None; callers accumulating physical position must add `position_adjust`
    after adding the reference's own `start`.

    🚨 A SourceClip carries `slot_id`: which slot of the referenced mob it
    means. A GROUP CLIP (Avid multicam) is an unnamed CompositionMob with one
    slot per camera, and hopping through the first slot returns CAMERA 1's
    chain regardless of which camera the editor selected. Measured on a real
    turnover (CS031, 2026-08-13): ~24 cuts linked a same-day SIBLING camera or
    take — A015C017 built where the editor cut A082C105 — because both the
    name chase and the source-position chase took the first-slot shortcut.
    The wrong name is only the visible half: srcTcFrame accumulated down the
    wrong camera's chain, so the build placed frames of the wrong source and
    called them proven.

    🚨 And the slot is only half the address. A group slot's segment can be a
    SEQUENCE — the camera's whole tape timeline, one component per recording
    with filler between (measured on KBP R2, 2026-08-14: A-cam slot =
    [A008C001, filler, A008C002, filler, A009C001]; the Selector's SourceClip
    entered it at start=123456, inside A008C002, while the first-clip shortcut
    reported A008C001 with a source TC ~6.8s early — the reference burn-in
    proved the picture was A008C002 @ 16:34:56:10). The reference's `start` is
    a position ON that sequence: resolve the covered component, and return the
    component's own sequence offset as a NEGATIVE adjust so the accumulated
    position becomes (ref.start − component_offset) + covered_clip.start.

    Falls back to the first-slot scan only when slot_id is absent or names a
    slot the mob does not have — the pre-fix behavior, kept for tape-style
    single-slot mobs where it was always right.
    """
    slots = getattr(mob, "slots", None) or []
    sid = getattr(ref_clip, "slot_id", None)

    def resolve_at_offset(segment):
        """(clip, adjust) for this slot's content at the reference's offset."""
        if segment is None:
            return None
        if type(segment).__name__ == "Sequence":
            try:
                offset = int(getattr(ref_clip, "start", 0) or 0)
            except Exception:
                offset = 0
            # 🚨 Two offset conventions live in one structure, and only the
            # sequence's SHAPE tells them apart — measured against FOUR
            # independent reference burn-ins (2026-08-14):
            #   KICK wrapper [Filler 1,  SC 118 @1 ] start=42 → truth 42−0
            #   KICK wrapper [Filler 21, SC 150 @21] start=43 → truth 43−20
            #   KBP group A  [SC, Filler, SC, …]     start big → truth raw
            #   KBP group B  [Filler, SC, Filler, …] start big → truth raw
            # A consolidate SUBCLIP WRAPPER (exactly one non-filler component,
            # head filler in front) measures offsets from ONE FRAME INTO the
            # head filler: shift = rawOffset − 1. A GROUP/tape sequence
            # (multiple non-filler components) uses raw coordinates, head
            # filler or not. This is also why the first-clip shortcut mostly
            # worked: wrapper head fillers are usually 1 frame, making its
            # error zero — until a 21-frame filler made it +20. The burn-in is
            # the arbiter here, not the AAF spec — Avid writes what Avid
            # writes. Interior fillers DO count: real dark space on a group's
            # tape timeline.
            comps = getattr(segment, "components", None) or []
            non_filler = sum(1 for c in comps if type(c).__name__ != "Filler")
            pad = (
                1
                if comps and type(comps[0]).__name__ == "Filler" and non_filler == 1
                else 0
            )
            pos = 0
            for comp in comps:
                ln = _length(comp) or 0
                eff = pos - pad
                if eff <= offset < eff + ln:
                    found = _find_source_clip(comp)
                    # A filler here means this angle is dark at the offset —
                    # no source to name; let the caller fall back or stop.
                    return (found, -eff) if found is not None else None
                pos += ln
            # Offset past the sequence end — a malformed reference; the old
            # first-clip answer is the least-wrong fallback, with no adjust.
        found = _find_source_clip(segment)
        return (found, 0) if found is not None else None

    if sid is not None:
        for slot in slots:
            try:
                if getattr(slot, "slot_id", None) == sid:
                    resolved = resolve_at_offset(getattr(slot, "segment", None))
                    if resolved is not None:
                        return resolved
                    break  # the named slot has no SourceClip at the offset — fall back
            except Exception:
                continue
    for slot in slots:
        try:
            resolved = resolve_at_offset(getattr(slot, "segment", None))
        except Exception:
            continue
        if resolved is not None:
            return resolved
    return None


def _source_name(clip):
    """Best-effort human name for a SourceClip: the nearest NAMED mob it references.

    Avid does not point a timeline SourceClip straight at a MasterMob. Subclips, group
    clips and motion-effect sources go through one or more UNNAMED intermediate
    CompositionMobs, so stopping at `clip.mob.name` yields nothing for the majority of
    a real turnover's clips. Chase the reference chain — mob → its slot's SourceClip →
    that clip's mob — until a mob actually carries a name (typically the MasterMob, e.g.
    "A001C001_240101_AB01.new.01"). Bounded and cycle-guarded.
    """
    current = clip
    seen = set()
    for _ in range(_MAX_MOB_CHASE):
        try:
            mob = getattr(current, "mob", None)
        except Exception:
            mob = None
        if mob is None:
            break
        try:
            key = str(getattr(mob, "mob_id", "") or id(mob))
        except Exception:
            key = str(id(mob))
        if key in seen:
            break  # reference cycle — stop rather than spin
        seen.add(key)
        name = _usable_name(mob)
        if name:
            return name
        # Honor the reference's slot_id — group clips have one slot per camera
        # and the first-slot shortcut returns the wrong member (see
        # _hop_referenced_clip).
        hop = _hop_referenced_clip(mob, current)
        if hop is None:
            break
        current = hop[0]
    # No named mob anywhere in the chain — fall back to the clip's own name.
    return _usable_name(clip) or "UNKNOWN"


# ── Physical source position + timecode (the "which frames" question) ─────────
#
# MEASURED 2026-08-05 on a consolidated Avid turnover: a SourceClip's own
# `start` is the offset into whatever mob it references DIRECTLY, and for
# consolidated media that is a per-cut fragment with ~40-frame handles — so 774
# of 878 events reported srcIn <= 45, and takes used several times all reported
# the SAME srcIn with different lengths. Two different cuts of one take cannot
# both begin at frame 42 of that take; those 42s were handles on separate
# fragments.
#
# The real position is the SUM of the `start` offsets down the mob chain, and
# the anchor that survives relinking to different media is the physical source
# TIMECODE: the referenced mob's timecode start plus that accumulated offset.
# A consumer that links camera originals can then place
# `sourceTc - fileStartTc` instead of a fragment-relative number that merely
# FITS inside the file.
#
# Emitted per event as srcPos / srcTcFrame / srcTc / srcTcFps / srcTcDrop, and
# only when actually found — a consumer must be able to tell "this AAF carries
# no source timecode" from "this probe is too old to emit it", which is what
# the per-sequence sourceTimecodeCoverage counters are for.


def _mob_timecode(mob, _cache={}):
    """(startFrame, rate, drop) from a mob's timecode slot, or None."""
    try:
        key = str(getattr(mob, "mob_id", "") or id(mob))
    except Exception:
        key = str(id(mob))
    if key in _cache:
        return _cache[key]
    found = None
    for slot in getattr(mob, "slots", None) or []:
        try:
            if _slot_media_kind(slot) != _TIMECODE_KIND:
                continue
        except Exception:
            continue
        tc = _timecode_component(getattr(slot, "segment", None))
        if tc is None:
            continue
        try:
            start = int(getattr(tc, "start"))
            rate = int(round(float(getattr(tc, "fps", 0) or 0)))
            drop = bool(getattr(tc, "drop", False))
        except Exception:
            continue
        if rate > 0 and start >= 0:
            found = (start, rate, drop)
            break
    _cache[key] = found
    return found


def _chase_source_position(clip):
    """Physical source position + timecode for a SourceClip's FIRST frame.

    Walks clip -> referenced mob -> that mob's own SourceClip, accumulating each
    hop's `start`. Returns (position, timecode_or_None) where `timecode` is
    (tc_start, rate, drop, position_at_that_mob) for the NEAREST mob carrying a
    timecode slot. Bounded and cycle-guarded like _source_name.
    """
    current = clip
    position = 0
    timecode = None
    seen = set()
    for _ in range(_MAX_MOB_CHASE):
        try:
            position += int(getattr(current, "start", 0) or 0)
        except Exception:
            pass
        try:
            mob = getattr(current, "mob", None)
        except Exception:
            mob = None
        if mob is None:
            break
        try:
            key = str(getattr(mob, "mob_id", "") or id(mob))
        except Exception:
            key = str(id(mob))
        if key in seen:
            break  # reference cycle — stop rather than spin
        seen.add(key)
        if timecode is None:
            tc = _mob_timecode(mob)
            if tc is not None:
                timecode = (tc[0], tc[1], tc[2], position)
        # Same slot_id discipline as _source_name: the position/timecode chain
        # must descend the SELECTED camera of a group clip, or srcTcFrame is
        # the right frame of the WRONG source. The hop's adjust re-bases a
        # sequence-slot reference onto the covered component (KBP R2 class).
        hop = _hop_referenced_clip(mob, current)
        if hop is None:
            break
        position += hop[1]
        current = hop[0]
    return position, timecode


def _source_position_fields(clip):
    """The srcPos/srcTc* keys for an event. Empty dict when nothing is knowable."""
    try:
        position, timecode = _chase_source_position(clip)
    except Exception:
        return {}
    fields = {}
    try:
        own_start = int(getattr(clip, "start", 0) or 0)
    except Exception:
        own_start = 0
    if position != own_start:
        # Only meaningful when the chain actually went deeper than the clip's
        # own reference — otherwise srcPos would just restate srcIn.
        fields["srcPos"] = position
    if timecode is not None:
        tc_start, rate, drop, at = timecode
        fields.update(
            {
                "srcTcFrame": tc_start + at,
                "srcTc": _frames_to_timecode(tc_start + at, rate, drop),
                "srcTcFps": rate,
                "srcTcDrop": drop,
            }
        )
    return fields


def _emit_source_clip(clip, *, index, track, rec, fps, transition=None):
    """Turn a SourceClip into a normalized event. Returns (event, length)."""
    try:
        length = int(getattr(clip, "length", 0) or 0)
    except Exception:
        length = 0
    try:
        start = int(getattr(clip, "start", 0) or 0)
    except Exception:
        start = 0
    event = {
        "index": index,
        "track": track,
        "source": _source_name(clip),
        "srcIn": start,
        "srcOut": start + length,
        "recIn": rec,
        "recOut": rec + length,
        "speed": 100,
        "reverse": False,
        "transition": transition,
        "fps": fps,
    }
    event.update(_source_position_fields(clip))
    return event, length


# Depth guard: AAF nesting is a graph and a malformed file could cycle. Real Avid
# turnovers nest ~4 deep (NestedScope > Sequence > Selector > OperationGroup > Sequence).
_MAX_DEPTH = 24


def _length(obj):
    try:
        return int(getattr(obj, "length", 0) or 0)
    except Exception:
        return 0


def _note_unhandled(state, cls):
    """Record a component class we could not turn into events. See module docstring."""
    state["unhandled"][cls] = state["unhandled"].get(cls, 0) + 1


def _nested_layers(scope):
    """The parallel layers of a NestedScope.

    pyaaf2 hands back the layer Segments directly for this class, but tolerate a
    slot-like wrapper (`.segment`) too so we work across pyaaf2 versions.
    """
    layers = []
    for item in getattr(scope, "slots", []) or []:
        inner = getattr(item, "segment", None)
        layers.append(inner if inner is not None else item)
    return layers


def _selector_selected(comp):
    """The live variant of a Selector (Avid enabled/disabled layer variants).

    This is the AAF `Selected` PROPERTY — pyaaf2 does not expose it as a `.selected`
    python attribute, so read it via getvalue()/[] first and only then fall back.
    """
    for getter in (
        lambda c: c.getvalue("Selected"),
        lambda c: c["Selected"].value,
        lambda c: getattr(c, "selected", None),
    ):
        try:
            v = getter(comp)
            if v is not None:
                return v
        except Exception:
            pass
    return None


def _operation_name(comp):
    try:
        return str(getattr(getattr(comp, "operation", None), "name", "") or "")
    except Exception:
        return ""


# ── Retime (Motion Control) parameter recovery ─────────────────────────────────
# Avid stores a retime's ratio on the OperationGroup's PARAMETERS. Verified against
# real Media Composer turnovers by cross-checking the inner SourceClip length vs the
# group's declared record length AND the PARAM_SPEED_MAP_U control-point values:
#   * "SpeedRatio" (AAF Edit Protocol ParameterDef, a ConstantValue rational) is the
#     RECORD/SOURCE length ratio — i.e. the INVERSE of the play rate. A 175% fast
#     motion is stored as 4/7 (100 record frames consume 175 source frames); reverse
#     play is a NEGATIVE rational (-1/1 = 100% backwards). Mixed-rate pulldown
#     wrappers appear as 1000/1001.
#   * "PARAM_SPEED_MAP_U" (Avid, a VaryingValue) has control points whose VALUES are
#     play-rate scalars directly (1.75 = 175%, negative = reverse). More than one
#     distinct value means the speed VARIES across the clip.
#   * "PARAM_SPEED_RATIO_U" (Avid, a ConstantValue) belongs to the same *_U family
#     as the speed map, so its value is a play-rate scalar, not a SpeedRatio.

# The AAF Edit Protocol parameter-definition id for SpeedRatio, so a file whose
# dictionary lost the human name still resolves.
_SPEED_RATIO_AUID = "72559a80-24d7-11d3-8a50-0050040ef7d2"


def _op_parameters(op_group):
    """An OperationGroup's Parameter objects; [] when absent or unreadable."""
    try:
        prop = getattr(op_group, "parameters", None)
        if prop is None:
            return []
        value = getattr(prop, "value", None)
        return list(value if value is not None else prop)
    except Exception:
        return []


def _param_name(param):
    try:
        return str(param.name or "")
    except Exception:
        return ""


def _param_is(param, name, auid=None):
    if _param_name(param) == name:
        return True
    if auid:
        try:
            return str(param.auid).lower() == auid
        except Exception:
            return False
    return False


def _pointlist(varying):
    """A VaryingValue's ControlPoint objects, or None if unreadable."""
    points = getattr(varying, "pointlist", None)
    if points is None:
        return None
    inner = getattr(points, "value", None)
    if inner is not None:
        points = inner
    try:
        return list(points)
    except Exception:
        return None


def _pointlist_values(varying):
    """Control-point VALUES of a VaryingValue's point list, or None if unreadable."""
    points = _pointlist(varying)
    if points is None:
        return None
    try:
        return [float(p.value) for p in points]
    except Exception:
        return None


# ── Keyframes (VaryingValue control points) ───────────────────────────────────
# A VaryingValue is a CURVE, and until now the probe read only its values, and only
# to answer "is this one number or more than one". The times were never asked for,
# so an animated reframe reached a consumer as the bare word "varying" — enough to
# refuse the clip, never enough to rebuild it.
#
# `ControlPoint.time` is readable. It is NOT one domain, and that is the whole trap
# here — measured over all 2047 control points of a real 878-event Avid turnover:
#
#   * TRANSFORM parameters (AFX_*, DVE_*) are normalized over the effect span, with
#     the endpoint INCLUSIVE:  frame = time x (length - 1).
#     1243 of 1254 points land exactly on an integer frame under (length - 1); only
#     278 also do under (length), so the two are distinguishable and (length - 1)
#     is the rule. The 11 that land on neither are ONE keyframe of one clip at
#     frame 125.5 — a legitimate half-frame key, which (length - 1) renders exactly.
#   * SPEED maps are already in effect FRAMES: PARAM_SPEED_OFFSET_MAP_U spans
#     exactly 0..length on every one of the 11 retimes carrying it.
#
# So a single "convert to frames" rule would be wrong by the effect's whole length
# on one of the two families. The domain is therefore NAMED in the output and the
# raw stored `t` travels next to the derived `frame`, so a consumer that disagrees
# with our arithmetic can redo it. Same discipline as the raw AFX_* passthrough:
# a stored number keeps its own name until its semantics are measured.
#
# Keyframes outside 0..1 are REAL and are kept: 107 of 1254 sit before the effect's
# first frame or after its last, which is what Avid leaves behind when a clip is
# trimmed after it was animated. Clamping them would silently move the animation.

_DOMAIN_EFFECT_SPAN = "effectSpan"  # frame = t x (length - 1)
_DOMAIN_EFFECT_FRAMES = "effectFrames"  # frame = t


def _interpolation_name(varying):
    try:
        return str(varying.interpolationdef.name or "") or None
    except Exception:
        return None


def _keyframes(varying, *, length, domain):
    """One VaryingValue as an explicit curve, or None if its points are unreadable.

    Shape: {"interpolation", "domain", "effectLength", "points": [{"t","frame","v"}]}
    `frame` is omitted when the effect length is unknown, because there is nothing
    to normalize against and a fabricated frame number is worse than none.
    """
    points = _pointlist(varying)
    if not points:
        return None
    span = None
    if isinstance(length, int) and length > 1 and domain == _DOMAIN_EFFECT_SPAN:
        span = length - 1
    out = []
    for p in points:
        try:
            t = float(p.time)
            v = float(p.value)
        except Exception:
            # A point we cannot read makes the CURVE untrustworthy, not just the
            # point — an animation with a hole in it would interpolate straight
            # through the missing key. Refuse the whole parameter.
            return None
        point = {"t": round(t, 9), "v": round(v, 6)}
        if domain == _DOMAIN_EFFECT_FRAMES:
            point["frame"] = round(t, 6)
        elif span:
            point["frame"] = round(t * span, 6)
        out.append(point)
    curve = {"domain": domain, "points": out}
    interp = _interpolation_name(varying)
    if interp:
        curve["interpolation"] = interp
    if isinstance(length, int) and length > 0:
        curve["effectLength"] = length
    return curve


def _rate_from_offset_curve(curve):
    """The play rate the source-offset curve ITSELF implies, or None.

    Only returned when that curve is straight — every interior point on the line
    through its endpoints, to within a tenth of a frame. A dense VARYING map is not
    one rate and must not be averaged into one, so colinearity is the test that
    separates the two rather than a flag we would have to trust.

    🚨 Why this exists: the declared `SpeedRatio` rational is the source span
    TRUNCATED TO WHOLE FRAMES over the record length, and the curve is exact.
    Measured on the fixture, 6 of 18 constant retimes disagree —

        L=112   curve span 201.600   rate 1.80   declared 201/112 = 1.794643
        L= 71   curve span 142.000   rate 2.00   declared 141/71  = 1.985915
        L= 19   curve span  32.300   rate 1.70   declared  31/19  = 1.631579  ← 4%

    — and every curve slope lands on a number an editor would actually dial (1.7,
    1.8, 2.0, 0.75) while every declared value is that number spoiled by a rounding.
    A consumer handing 1.631579 to an operator to type in has handed them a visibly
    wrong speed. Both numbers are reported under their own names; neither is
    silently substituted for the other.
    """
    if not curve:
        return None
    points = curve.get("points") or []
    if len(points) < 2:
        return None
    first, last = points[0], points[-1]
    try:
        run = float(last["frame"]) - float(first["frame"])
        rise = float(last["v"]) - float(first["v"])
    except (KeyError, TypeError, ValueError):
        return None
    if abs(run) < 1e-9:
        return None
    slope = rise / run
    for p in points[1:-1]:
        try:
            expected = float(first["v"]) + (float(p["frame"]) - float(first["frame"])) * slope
        except (KeyError, TypeError, ValueError):
            return None
        if abs(float(p["v"]) - expected) > 0.1:
            return None  # a real timewarp — no single rate describes it
    return slope


def _retime_fields(op_group):
    """Extra event fields recovered from a retime OperationGroup's parameters.

    Returns one of:
      {"speedRatio": <play-rate float>, "speed": <int %>, "reverse": <bool>}
      {"speedVarying": True}  — a variable-speed timewarp; no single honest number
      {}                      — nothing recoverable (flag-only, speed stays 100)

    Any of those may additionally carry "speedCurve" — the retime's own keyframes.
    A variable timewarp used to reach a consumer as the single word `speedVarying`,
    which is enough to REFUSE the clip and never enough to rebuild it. Two curves
    are emitted when present, under Avid's own parameter names:

      playRate      PARAM_SPEED_MAP_U — sparse play-rate keys (AvidCubicInterpolator
                    on every one measured), keys freely outside the trimmed range.
      sourceOffset  PARAM_SPEED_OFFSET_MAP_U — a DENSE source-position curve, linear,
                    spanning exactly 0..length (up to 387 points at half-frame steps
                    on the fixture). Its slope reproduces the constant ratios exactly
                    — 0.75 → 175.75 over 100 frames is the 1.75 the SpeedRatio
                    declares — so it is the same quantity measured a second way, and
                    for a VARYING timewarp it is the only complete description of
                    where each record frame reads from.
    """
    play = None
    speed_map = None
    offset_map = None
    length = _length(op_group)
    for param in _op_parameters(op_group):
        cls = type(param).__name__
        if cls == "VaryingValue":
            name = _param_name(param)
            if name == "PARAM_SPEED_MAP_U":
                speed_map = param
            elif name == "PARAM_SPEED_OFFSET_MAP_U":
                offset_map = param
            continue
        if cls != "ConstantValue":
            continue
        if _param_is(param, "SpeedRatio", _SPEED_RATIO_AUID):
            try:
                value = param.value
                num = int(value.numerator)
                den = int(value.denominator)
            except Exception:
                continue
            if num:
                play = den / num  # stored record/source → play rate is the inverse
        elif _param_name(param) == "PARAM_SPEED_RATIO_U" and play is None:
            try:
                value = float(param.value)
            except Exception:
                continue
            if value:
                play = value  # *_U family stores the play rate directly
    curve = {}
    for key, param in (("playRate", speed_map), ("sourceOffset", offset_map)):
        if param is None:
            continue
        # Both live in the effect's own FRAME domain — measured, see _keyframes.
        got = _keyframes(param, length=length, domain=_DOMAIN_EFFECT_FRAMES)
        if got:
            got["parameter"] = _param_name(param)
            curve[key] = got
    extra = {"speedCurve": curve} if curve else {}
    measured = _rate_from_offset_curve(curve.get("sourceOffset"))
    if measured is not None:
        extra["speedRatioFromCurve"] = round(abs(measured), 6)
        if measured < 0:
            extra["reverseFromCurve"] = True

    if speed_map is not None:
        values = _pointlist_values(speed_map)
        if values is None:
            # A speed map we cannot read: we can neither call the speed constant
            # nor prove it varies — recover nothing rather than guess. The offset
            # curve, if it read cleanly, still ships: it is an independent
            # parameter and its unreadable sibling says nothing about it.
            return extra
        if len(set(values)) > 1:
            return {"speedVarying": True, **extra}
        if play is None and values and values[0]:
            play = values[0]  # a flat map's single value IS the constant play rate
    if not play:
        return extra
    return {
        "speedRatio": round(abs(play), 6),
        "speed": int(round(abs(play) * 100)),
        "reverse": play < 0,
        **extra,
    }


# ── Per-clip geometry (Avid transform OperationGroups) ────────────────────────
# The data behind Resolve's "Use sizing information" AAF import option. Census of a
# real 878-event Avid picture turnover — the parameters that are actually present,
# by operation:
#
#   PaintResize_v2 (285)  AFX_SCALE_X_U / AFX_SCALE_Y_U       percent, 100 = identity
#                         AFX_POS_X_U / AFX_POS_Y_U           Avid position units
#                         AFX_CROP_{LEFT,RIGHT,TOP,BOTTOM}_U  Avid crop units
#                         AFX_FIXED_ASPECT_U                  bool (aspect locked)
#   SpatialAdapter (90)   AFX_SPATIAL_SOURCE_{WID,HEI}_{NUM,DEN}   source rectangle
#                         AFX_SPATIAL_FRAMING_{WID,HEI}_{NUM,DEN}  framing rectangle
#                         AFX_SPATIAL_REFORMAT, AFX_SCALE_{X,Y}_U
#   FlipHoriz_2 (10)      a horizontal flip; carries no geometry parameters of its own
#
# What the fixture PROVES, and is therefore emitted as a named field:
#   * scale is a PERCENT — 212 of 285 PaintResize groups sit at exactly 100, i.e.
#     identity, which pins the unit without needing a reference render.
#   * the source and framing rectangles share ONE unit, so their RATIO is unit-free.
#     `reformatScaleX/Y` is that ratio (a 5120/3 x 900 source into a 1200 x 900
#     framing is the 2.39:1-into-16:9 letterbox the reference showed).
#
# What it does NOT prove, and is therefore passed through RAW under Avid's own
# parameter names in `params` rather than reinterpreted into a normalized field:
# the unit of POS_*/CROP_*, and the ABSOLUTE unit of the rectangles. This is the
# SpeedRatio lesson applied ahead of time — that one was stored as the INVERSE of
# play rate, and a normalized-looking field would have shipped the inversion. A
# stored Avid number keeps its own name until its semantics are measured.

_GEOMETRY_OPS = frozenset({"PaintResize_v2", "SpatialAdapter", "FlipHoriz_2"})

# ── Transform-bearing operations we do NOT interpret (U22) ────────────────────
# Widening _GEOMETRY_OPS is the wrong fix for these. Census of the same turnover:
#
#   SBlend_v2 (18 groups over 12 clips)  DVE_SCALE_X/Y_U 103, 123, 110→120 ·
#                                        DVE_POS_X_U -60, -315 · DVE_ROT_Z_U 3, 1
#   Stabilize_2 (5)                      DVE_SCALE_X/Y_U 102.52, 101.96 (a
#                                        stabiliser's zoom-in) · DVE_POS_X_U 1.54
#   MaskImage_2 (1), 2DMatteKey_2 (1)    AFX_POS/AFX_SCALE
#
# 🚨 The same parameter NAME does not mean the same unit: SBlend's DVE_POS_X_U runs
# to -315 while Stabilize's runs to -0.92 on the same show. Two ops, one name, two
# units — so there is nothing here to normalize, and `scalePercent*` on these would
# be composed into the applied zoom by a consumer that has no way to know better.
#
# 🚨 And they cannot ride in `params` either: 2DMatteKey_2 carries AFX_POS_X_U 500.0,
# which is a name an existing consumer already has a CALIBRATED rule for — it would
# be silently applied as a ~960px reposition of a clip nobody repositioned. So the
# numbers travel under their own key, `rawParams`, which no consumer reads yet, next
# to `passthrough: true`. Reported, never silently dropped; never silently applied.
_PASSTHROUGH_GEOMETRY_OPS = frozenset({"SBlend_v2", "Stabilize_2", "MaskImage_2", "2DMatteKey_2"})

_PASSTHROUGH_PARAM_RE = re.compile(
    r"(?:^|_)(?:POS|SCALE|CROP|ROT|SKEW|SIZE|OPACITY|ASPECT)(?:_|$)|CORNER_PIN|ENABLED"
)

_GEOMETRY_SCALARS = frozenset(
    {
        "AFX_POS_X_U",
        "AFX_POS_Y_U",
        "AFX_CROP_LEFT_U",
        "AFX_CROP_RIGHT_U",
        "AFX_CROP_TOP_U",
        "AFX_CROP_BOTTOM_U",
        "AFX_SPATIAL_REFORMAT",
    }
)
_GEOMETRY_BOOLS = frozenset({"AFX_FIXED_ASPECT_U", "AFX_SPATIAL_LOCK_ASPECT"})
# Rectangles arrive split across a <base>_NUM / <base>_DEN rational pair.
_GEOMETRY_RECTS = frozenset(
    {
        "AFX_SPATIAL_SOURCE_WID",
        "AFX_SPATIAL_SOURCE_HEI",
        "AFX_SPATIAL_FRAMING_WID",
        "AFX_SPATIAL_FRAMING_HEI",
    }
)


def _param_number(param):
    """A Parameter's ConstantValue as a float (AAFRational, int, bool all convert)."""
    try:
        return round(float(param.value), 6)
    except Exception:
        return None


def _geometry_scalar(param):
    """(value, is_varying) for one geometry parameter, or (None, False) if unreadable.

    A VaryingValue whose control points all carry the SAME value is a constant — the
    same rule the speed map uses. More than one distinct value is an animated
    transform, and no single number for it would be honest.
    """
    if type(param).__name__ == "VaryingValue":
        values = _pointlist_values(param)
        if values is None:
            return None, False
        if len(set(values)) > 1:
            return None, True
        return (round(float(values[0]), 6) if values else None), False
    return _param_number(param), False


def _geometry_keyframes(param, length):
    """The curve behind an ANIMATED geometry parameter, in the effect-span domain."""
    return _keyframes(param, length=length, domain=_DOMAIN_EFFECT_SPAN)


def _passthrough_geometry(op_group, op_name):
    """A transform op we do not interpret, reported rather than dropped (U22).

    Everything geometry-shaped, under Avid's own names, in `rawParams` — plus the
    curve for any of them that animates. No normalized field is emitted and no
    `params` key is used, so this can be composed by nobody and misread by nobody.
    Returns None when the group carries nothing geometry-shaped at all.
    """
    length = _length(op_group)
    raw = {}
    keyframes = {}
    for param in _op_parameters(op_group):
        name = _param_name(param)
        if not name or not _PASSTHROUGH_PARAM_RE.search(name):
            continue
        if type(param).__name__ == "VaryingValue":
            values = _pointlist_values(param)
            if values is None:
                continue
            if len(set(values)) > 1:
                curve = _keyframes(param, length=length, domain=_DOMAIN_EFFECT_SPAN)
                if curve:
                    keyframes[name] = curve
                continue
            if values:
                raw[name] = round(float(values[0]), 6)
            continue
        value = _param_number(param)
        if value is not None:
            raw[name] = value
    if not raw and not keyframes:
        return None
    out = {"effect": op_name, "passthrough": True}
    if raw:
        out["rawParams"] = dict(sorted(raw.items()))
    if keyframes:
        out["keyframes"] = dict(sorted(keyframes.items()))
        out["varying"] = sorted(keyframes)
    return out


def _geometry_fields(op_group, op_name):
    """Recovered geometry for one transform OperationGroup. See the census above."""
    scale = {}
    scalars = {}
    bools = {}
    rects = {}
    varying = set()
    keyframes = {}
    length = _length(op_group)

    def note_varying(param, name):
        """Name the animated parameter AND keep its curve."""
        varying.add(name)
        curve = _geometry_keyframes(param, length)
        if curve:
            keyframes[name] = curve

    for param in _op_parameters(op_group):
        name = _param_name(param)
        base, _, suffix = name.rpartition("_")
        if suffix in ("NUM", "DEN") and base in _GEOMETRY_RECTS:
            value = _param_number(param)
            if value is not None:
                rects.setdefault(base, {})[suffix] = value
            continue
        if name in ("AFX_SCALE_X_U", "AFX_SCALE_Y_U"):
            value, is_varying = _geometry_scalar(param)
            if is_varying:
                note_varying(param, name)
            elif value is not None:
                scale[name] = value
            continue
        if name in _GEOMETRY_BOOLS:
            value = _param_number(param)
            if value is not None:
                bools[name] = bool(value)
            continue
        if name in _GEOMETRY_SCALARS:
            value, is_varying = _geometry_scalar(param)
            if is_varying:
                note_varying(param, name)
            elif value is not None:
                scalars[name] = value
    geometry = {"effect": op_name}
    if op_name == "FlipHoriz_2":
        geometry["flipHorizontal"] = True
    if "AFX_SCALE_X_U" in scale:
        geometry["scalePercentX"] = scale["AFX_SCALE_X_U"]
    if "AFX_SCALE_Y_U" in scale:
        geometry["scalePercentY"] = scale["AFX_SCALE_Y_U"]
    sizes = {}
    for base, parts in rects.items():
        num, den = parts.get("NUM"), parts.get("DEN")
        if num is None or not den:
            continue
        sizes[base] = round(num / den, 6)
    if sizes:
        geometry["rect"] = dict(sorted(sizes.items()))
        # The one unit-free quantity the rectangles yield: framing over source.
        for axis, src, framing in (
            ("X", "AFX_SPATIAL_SOURCE_WID", "AFX_SPATIAL_FRAMING_WID"),
            ("Y", "AFX_SPATIAL_SOURCE_HEI", "AFX_SPATIAL_FRAMING_HEI"),
        ):
            if sizes.get(src) and sizes.get(framing) is not None:
                geometry[f"reformatScale{axis}"] = round(sizes[framing] / sizes[src], 6)
    if varying:
        # An animated transform. Named, never reduced to one number — and, since
        # U21, never reduced to the NAME either: `keyframes` carries the curve.
        # `varying` stays exactly as it was, because consumers gate on it.
        geometry["varying"] = sorted(varying)
    if keyframes:
        geometry["keyframes"] = dict(sorted(keyframes.items()))
    params = dict(sorted({**scalars, **bools}.items()))
    if params:
        geometry["params"] = params
    return geometry


def _walk_segment(segment, *, track, fps, rec, state, depth=0, transition=None):
    """
    Emit normalized events for ONE segment placed at record position `rec`.

    Appends to `state["events"]` (indices from the monotonic `state["idx"]`) and
    counts anything it cannot model into `state["unhandled"]`.

    Returns the number of RECORD frames this segment occupies, so a caller laying
    components end to end can advance. Container classes return their own declared
    length rather than the sum of what we managed to decode — a partial decode must
    not silently slide every later clip earlier on the timeline.
    """
    cls = type(segment).__name__
    declared = _length(segment)

    if depth > _MAX_DEPTH:
        _note_unhandled(state, cls)
        return declared

    if cls == "SourceClip":
        ev, length = _emit_source_clip(
            segment, index=state["idx"], track=track, rec=rec, fps=fps, transition=transition
        )
        state["events"].append(ev)
        state["idx"] += 1
        return length

    if cls in ("Filler", "ScopeReference"):
        # Filler = a real gap. ScopeReference = "the NestedScope layer beneath shows
        # through here" — real record time, but no clip of THIS layer's own.
        return declared

    if cls == "Sequence":
        return _walk_components(segment, track=track, fps=fps, rec=rec, state=state, depth=depth + 1, transition=transition)

    if cls == "NestedScope":
        # Layers are parallel in time: every one starts at this segment's own rec.
        for layer in _nested_layers(segment):
            _walk_segment(layer, track=track, fps=fps, rec=rec, state=state, depth=depth + 1, transition=transition)
        return declared

    if cls == "Selector":
        selected = _selector_selected(segment)
        if selected is None:
            _note_unhandled(state, cls)
        else:
            _walk_segment(selected, track=track, fps=fps, rec=rec, state=state, depth=depth + 1, transition=transition)
        return declared

    if cls == "OperationGroup":
        # Effect wrapper (retime, paint, resize, blend, matte key...). Its `.segments`
        # are the effect INPUTS, and the primary is usually a nested Sequence, NOT a
        # bare SourceClip — only descending to a direct SourceClip finds nothing.
        #
        # EVERY input is walked, not just the primary: an SBlend B-side or a matte
        # key's fill/key are real referenced media that a conform has to relink, and
        # dropping them is the same data loss this walker exists to prevent. They share
        # the primary's record span (that is what a blend IS), so they intentionally
        # overlap it on the same track label. Callers already cannot assume events are
        # non-overlapping — parallel NestedScope layers overlap by construction.
        before = len(state["events"])
        charges_before = state.get("_emptyEffectCharges", 0)
        for inp in getattr(segment, "segments", None) or []:
            _walk_segment(inp, track=track, fps=fps, rec=rec, state=state, depth=depth + 1, transition=transition)
        op_name = _operation_name(segment)

        if op_name and declared > 0 and len(state["events"]) == before:
            # Walked cleanly, emitted nothing, and still consumed record time. See the
            # "effectsWithoutEvents" note in probe(). Only the INNERMOST such group is
            # charged — an outer wrapper around an empty effect is empty for the same
            # one reason, and charging both would report one title as two.
            if state.get("_emptyEffectCharges", 0) == charges_before:
                bucket = state.setdefault("effectsWithoutEvents", {})
                bucket[op_name] = bucket.get(op_name, 0) + 1
                state["_emptyEffectCharges"] = charges_before + 1

        if op_name in _GEOMETRY_OPS:
            # A transform effect. Clips are commonly wrapped in MORE than one (a
            # SpatialAdapter reformat inside a PaintResize, say), so geometry is a
            # LIST in application order — innermost first, because this walk annotates
            # on the way back out. Collapsing them to one field would silently drop a
            # stage of the transform stack.
            geometry = _geometry_fields(segment, op_name)
            for ev in state["events"][before:]:
                ev.setdefault("geometry", []).append(geometry)
        elif op_name in _PASSTHROUGH_GEOMETRY_OPS:
            # Carries a transform whose units we have not measured. It joins the same
            # ordered stack so its PLACE in the chain survives, marked passthrough so
            # no consumer composes it. See _PASSTHROUGH_GEOMETRY_OPS.
            geometry = _passthrough_geometry(segment, op_name)
            if geometry:
                for ev in state["events"][before:]:
                    ev.setdefault("geometry", []).append(geometry)
        if op_name and ("speed" in op_name.lower() or "motion" in op_name.lower()):
            # A retime. Its ratio is recoverable from the group's PARAMETERS (see
            # _retime_fields): a constant ratio updates speed/speedRatio so
            # consumers reading only `speed` are no longer told 100; a variable
            # timewarp is reported as speedVarying: true; an unreadable one keeps
            # the old flag-only contract. A number is never fabricated.
            extra = _retime_fields(segment)
            for ev in state["events"][before:]:
                ev["effect"] = op_name
                ev.update(extra)
                # The group's DECLARED length is the RECORD duration; the inner
                # SourceClip's length is the SOURCE-side range — under a retime
                # they differ by the ratio, so an event whose recOut was advanced
                # by the source length inflates (fast motion) or undershoots
                # (slow motion) its real record span. The container declared-
                # length rule (this file's convention for rec advancement)
                # applies to the events too.
                if declared > 0:
                    ev["recOut"] = max(ev["recIn"], rec + declared)
        return declared

    # Unknown component — advance by its declared length, don't fake an event, and
    # make the miss loud so it cannot masquerade as an empty timeline.
    _note_unhandled(state, cls)
    return declared


def _walk_components(sequence, *, track, fps, rec, state, depth, transition=None):
    """Lay a Sequence's components end to end. Returns the record length consumed.

    Transitions SUBTRACT. This is the dual of the declared-length rule above, and it
    is the AAF Edit Protocol's definition rather than a heuristic: a Transition is not
    a component that occupies record time, it is an OVERLAP of the two components
    around it, so

        sequence length == sum(component lengths) - sum(transition lengths)

    and the component after a transition starts `duration` frames EARLIER than the
    previous one ended. Annotating the following clip (which this walker already did)
    without rewinding `rec` left every later event on that track late by the CUMULATIVE
    transition time — silent, track-local, and invisible on any timeline without a
    dissolve. Measured on a real Avid turnover: V1's single 59-frame dissolve put every
    subsequent V1 cut 59 frames past Resolve's own native import of the same file, and
    each layer's walked length overshot its DECLARED length by exactly the sum of that
    layer's transitions (V1 +59, V6 +77, every dissolve-free layer +0). The declared
    length is the cross-check — with the subtraction, walked == declared on every layer.
    """
    start = rec
    pending_transition = transition
    components = getattr(sequence, "components", None)
    if components is None:
        components = [sequence]
    for comp in components:
        cls = type(comp).__name__
        try:
            if cls == "Transition":
                duration = _length(comp)
                # alignment 'start': after the rewind, the incoming clip's recIn IS the
                # overlap start, so the transition span is [recIn, recIn+duration) — and
                # the bridge's boundary-shift lands the notional cut at recIn+duration/2,
                # exactly the AAF CutPoint default (centered in the overlap). The old
                # centered-on-recIn placement put HALF the blend before the overlap began.
                pending_transition = {"type": "dissolve", "duration": duration, "alignment": "start"}
                # CutPoint (optional): where the notional cut sits WITHIN the
                # overlap. The bridge shifts the reshaped clip boundary there
                # instead of the centered default, preserving Avid's intent.
                try:
                    cut_point = comp["CutPoint"].value
                    if cut_point is not None:
                        pending_transition["cutPoint"] = int(cut_point)
                except (KeyError, AttributeError, TypeError, ValueError):
                    pass
                # Rewind: the next component overlaps the previous one by `duration`.
                # Clamped at this sequence's own start — a leading transition has no
                # preceding material to overlap, and a negative record position would
                # be a worse lie than the malformed AAF that produced it.
                rec = max(start, rec - duration)
                continue
            rec += _walk_segment(
                comp, track=track, fps=fps, rec=rec, state=state, depth=depth, transition=pending_transition
            )
            pending_transition = None
        except Exception:
            # Never let one bad component abort the whole sequence — but say so.
            _note_unhandled(state, cls)
            pending_transition = None
            continue
    return rec - start


def _walk_slot(segment, *, prefix, fps, state):
    """
    Walk one mob slot's top-level segment into `state`.

    A NestedScope slot is a multi-layer track: each layer gets its own numbered label
    (V1..Vn / A1..An) and restarts at record 0, because layers are parallel, not
    sequential. A plain (single-layer) slot keeps the flat "V"/"A" label.
    """
    if type(segment).__name__ == "NestedScope":
        for n, layer in enumerate(_nested_layers(segment), start=1):
            _walk_segment(layer, track=f"{prefix}{n}", fps=fps, rec=0, state=state, depth=1)
        return
    _walk_segment(segment, track=prefix, fps=fps, rec=0, state=state, depth=0)


# Slot media kinds that carry no editorial cuts. Matched on MEDIA KIND, not on the
# segment's class name: Avid wraps timecode slots in a Pulldown (segment class
# "Pulldown", media_kind "Timecode"), so a class-name-only skip let them through and
# they polluted both the events and the unhandled counter.
_NON_EDITORIAL_KINDS = frozenset(
    {"timecode", "edgecode", "descriptivemetadata", "soundmastertrack"}
)


def _norm_kind(value):
    try:
        return "".join(str(value or "").split()).lower()
    except Exception:
        return ""


def _slot_media_kind(slot):
    """Media kind of a slot, falling back to its segment's."""
    for owner in (slot, getattr(slot, "segment", None)):
        kind = _norm_kind(getattr(owner, "media_kind", None))
        if kind:
            return kind
    return ""


def _is_editorial_slot(slot):
    return _slot_media_kind(slot) not in _NON_EDITORIAL_KINDS


def _media_kind_to_track(slot):
    return "A" if _slot_media_kind(slot).startswith("sound") else "V"


# ── Sequence start timecode ───────────────────────────────────────────────────
# A composition does NOT have one timecode slot. Avid writes several — one per common
# timecode rate — all naming the same wall-clock start. A real turnover carried seven:
#
#     start 86160 @24     start 89750 @25     start 107592 @30 drop
#     start 107700 @30    start 215400 @60    (and duplicates)
#
# Every one of those is 00:59:50:00. They agree on the STRING and disagree on the
# FRAME NUMBER, so "read the first timecode slot" hands back a frame count in a rate
# the rest of the parse never uses — a 10%-off offset that looks plausible. Pick the
# slot whose rate matches the EDITORIAL edit rate, and always report the rate the
# frame number is expressed in so a mismatch can't hide.
#
# This mattered: a consumer built its conform timeline at Resolve's default
# 01:00:00:00 while the AAF started at 00:59:50:00, mis-aligning the linked picture
# reference by ten seconds until it was hand-fixed.

_TIMECODE_KIND = "timecode"


def _timecode_component(segment, depth=0):
    """The Timecode component inside a timecode slot's segment, or None.

    Avid wraps it in a Pulldown (the rate conversion that makes a 30-drop view of a
    23.976 sequence), sometimes inside a Sequence, so the slot segment's own class
    name is not enough to find it.
    """
    if segment is None or depth > 8:
        return None
    cls = type(segment).__name__
    if cls == "Timecode":
        return segment
    children = []
    if cls == "Sequence":
        children = list(getattr(segment, "components", None) or [])
    elif cls == "Pulldown":
        # pyaaf2 exposes the wrapped segment as the InputSegment PROPERTY, not an
        # attribute — same access pattern as Selector's `Selected`.
        for getter in (
            lambda s: s["InputSegment"].value,
            lambda s: s.getvalue("InputSegment"),
            lambda s: getattr(s, "input_segment", None),
        ):
            try:
                inner = getter(segment)
            except Exception:
                inner = None
            if inner is not None:
                children = [inner]
                break
    for child in children:
        found = _timecode_component(child, depth + 1)
        if found is not None:
            return found
    return None


def _frames_to_timecode(frames, rate, drop):
    """SMPTE timecode string for a frame count at an INTEGER timecode rate.

    Drop-frame (`;` separator) skips two frame NUMBERS — four at the 60-family rate —
    at the top of every minute except every tenth. It renumbers; it never drops a
    picture frame, which is why the conversion is a renumbering pass and not a
    rescaling of `frames`.
    """
    try:
        frames = int(frames)
        rate = int(round(float(rate)))
    except Exception:
        return None
    if rate <= 0 or frames < 0:
        return None
    sep = ":"
    if drop and rate % 30 == 0:
        dropped = 2 * (rate // 30)
        per_10min = rate * 600 - dropped * 9
        per_min = rate * 60 - dropped
        tens, rem = divmod(frames, per_10min)
        frames += dropped * 9 * tens
        if rem > dropped:
            frames += dropped * ((rem - dropped) // per_min)
        sep = ";"
    total_seconds, ff = divmod(frames, rate)
    hh, rem_seconds = divmod(total_seconds, 3600)
    mm, ss = divmod(rem_seconds, 60)
    return f"{hh % 24:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"


# Absent-timecode sequences report these as null rather than omitting them: an explicit
# null is a readable "this AAF carries no start timecode", where a missing key is
# indistinguishable from an older probe that never emitted one.
_NO_START_TIMECODE = {
    "startTimecode": None,
    "startFrame": None,
    "startTimecodeFps": None,
    "startTimecodeDrop": None,
}


def _sequence_start_timecode(mob, edit_fps):
    """Start-timecode fields for a composition mob. Never guesses — see _NO_START_TIMECODE.

    `startFrame` is expressed at `startTimecodeFps`, which is the rate of the slot we
    picked; it equals the editorial edit rate whenever a matching slot exists.
    """
    candidates = []
    for slot in getattr(mob, "slots", []) or []:
        if _slot_media_kind(slot) != _TIMECODE_KIND:
            continue
        tc = _timecode_component(getattr(slot, "segment", None))
        if tc is None:
            continue
        try:
            start = int(getattr(tc, "start", None))
            rate = int(round(float(getattr(tc, "fps", 0) or 0)))
        except Exception:
            continue
        if rate <= 0 or start < 0:
            continue
        try:
            drop = bool(getattr(tc, "drop", False))
        except Exception:
            drop = False
        candidates.append((start, rate, drop))
    if not candidates:
        return dict(_NO_START_TIMECODE)
    wanted = int(round(edit_fps)) if edit_fps else None
    chosen = None
    if wanted:
        chosen = next((c for c in candidates if c[1] == wanted), None)
    if chosen is None:
        chosen = candidates[0]
    start, rate, drop = chosen
    return {
        "startTimecode": _frames_to_timecode(start, rate, drop),
        "startFrame": start,
        "startTimecodeFps": rate,
        "startTimecodeDrop": drop,
    }


def probe(path):
    import aaf2

    sequences = []
    with aaf2.open(path, "r") as f:
        toplevel = list(f.content.toplevel())
        # Fall back to all composition mobs if no explicit top-level usage is set.
        if not toplevel:
            try:
                toplevel = [m for m in f.content.mobs if type(m).__name__ == "CompositionMob"]
            except Exception:
                toplevel = []
        for mob in toplevel:
            try:
                mob_id = str(getattr(mob, "mob_id", "") or "")
            except Exception:
                mob_id = ""
            name = None
            try:
                name = getattr(mob, "name", None)
            except Exception:
                name = None
            # `idx` is monotonic across the WHOLE mob, every slot and every nested layer.
            state = {"idx": 1, "events": [], "unhandled": {}, "effectsWithoutEvents": {}}
            edit_fps = None
            for slot in getattr(mob, "slots", []) or []:
                seg = getattr(slot, "segment", None)
                if seg is None:
                    continue
                # Skip non-editorial slots by MEDIA KIND (timecode/edgecode/descriptive
                # metadata/sound master) — see _NON_EDITORIAL_KINDS.
                if not _is_editorial_slot(slot):
                    continue
                fps = _fps_from_edit_rate(getattr(slot, "edit_rate", None))
                if edit_fps is None:
                    edit_fps = fps  # picks the timecode slot to trust — see above
                _walk_slot(seg, prefix=_media_kind_to_track(slot), fps=fps, state=state)
            events = state["events"]
            sequences.append(
                {
                    "id": mob_id or (str(name) if name else f"seq{len(sequences) + 1}"),
                    "name": str(name) if name else f"Sequence {len(sequences) + 1}",
                    "eventCount": len(events),
                    **_sequence_start_timecode(mob, edit_fps),
                    # How much of this sequence carries a physical source position
                    # / timecode. Always present, so a consumer can tell "this AAF
                    # has none" (zeros) from "this probe is too old to emit it"
                    # (key absent) — the same reasoning as _NO_START_TIMECODE.
                    "sourcePositionCoverage": {
                        "events": len(events),
                        "withSourcePosition": sum(1 for e in events if "srcPos" in e),
                        "withSourceTimecode": sum(1 for e in events if "srcTcFrame" in e),
                    },
                    # Component classes we could not model, by name+count. Empty {} means
                    # a structurally complete read; non-empty means events are INCOMPLETE.
                    "unhandled": dict(sorted(state["unhandled"].items())),
                    # 🚨 Effects that OCCUPY RECORD TIME and produce no event (U23).
                    # `unhandled` cannot see these: it counts component classes the
                    # walker does not model, and these are modeled fine — an
                    # OperationGroup is walked, its inputs are walked, and they simply
                    # contain no SourceClip. On the reference turnover `unhandled` reads
                    # {} — a structurally complete parse — while 29 SubCap title effects
                    # occupy real record time and reach the consumer as nothing at all.
                    # A conform that silently loses 29 titles looks exactly like a
                    # conform that had none. Counted by operation name so it cannot.
                    "effectsWithoutEvents": dict(sorted(state.get("effectsWithoutEvents", {}).items())),
                    "events": events,
                }
            )
    return sequences


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("AAF_PROBE_USAGE: aaf_probe.py <path.aaf>\n")
        return 2
    path = argv[1]
    if not os.path.exists(path):
        sys.stderr.write(f"AAF_PROBE_UNREADABLE: no such file: {path}\n")
        return 4
    try:
        import aaf2  # noqa: F401
    except Exception:
        sys.stderr.write(
            "AAF_PROBE_NO_PYAAF2: the pure-Python 'aaf2' package (pyaaf2) is not installed\n"
        )
        return 3
    try:
        sequences = probe(path)
    except Exception as e:  # unreadable / not an AAF / decode failure
        sys.stderr.write(f"AAF_PROBE_UNREADABLE: {type(e).__name__}: {e}\n")
        return 4
    json.dump({"ok": True, "sequences": sequences}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
