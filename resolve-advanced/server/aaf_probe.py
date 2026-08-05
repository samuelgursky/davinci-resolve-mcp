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
        nxt = None
        for slot in getattr(mob, "slots", None) or []:
            nxt = _find_source_clip(getattr(slot, "segment", None))
            if nxt is not None:
                break
        if nxt is None:
            break
        current = nxt
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
        nxt = None
        for slot in getattr(mob, "slots", None) or []:
            nxt = _find_source_clip(getattr(slot, "segment", None))
            if nxt is not None:
                break
        if nxt is None:
            break
        current = nxt
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


def _pointlist_values(varying):
    """Control-point VALUES of a VaryingValue's point list, or None if unreadable."""
    points = getattr(varying, "pointlist", None)
    if points is None:
        return None
    inner = getattr(points, "value", None)
    if inner is not None:
        points = inner
    try:
        return [float(p.value) for p in points]
    except Exception:
        return None


def _retime_fields(op_group):
    """Extra event fields recovered from a retime OperationGroup's parameters.

    Returns one of:
      {"speedRatio": <play-rate float>, "speed": <int %>, "reverse": <bool>}
      {"speedVarying": True}  — a variable-speed timewarp; no single honest number
      {}                      — nothing recoverable (flag-only, speed stays 100)
    """
    play = None
    speed_map = None
    for param in _op_parameters(op_group):
        cls = type(param).__name__
        if cls == "VaryingValue":
            if _param_name(param) == "PARAM_SPEED_MAP_U":
                speed_map = param
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
    if speed_map is not None:
        values = _pointlist_values(speed_map)
        if values is None:
            # A speed map we cannot read: we can neither call the speed constant
            # nor prove it varies — recover nothing rather than guess.
            return {}
        if len(set(values)) > 1:
            return {"speedVarying": True}
        if play is None and values and values[0]:
            play = values[0]  # a flat map's single value IS the constant play rate
    if not play:
        return {}
    return {
        "speedRatio": round(abs(play), 6),
        "speed": int(round(abs(play) * 100)),
        "reverse": play < 0,
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


def _geometry_fields(op_group, op_name):
    """Recovered geometry for one transform OperationGroup. See the census above."""
    scale = {}
    scalars = {}
    bools = {}
    rects = {}
    varying = set()
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
                varying.add(name)
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
                varying.add(name)
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
        # An animated transform. Named, never reduced to one number.
        geometry["varying"] = sorted(varying)
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
        for inp in getattr(segment, "segments", None) or []:
            _walk_segment(inp, track=track, fps=fps, rec=rec, state=state, depth=depth + 1, transition=transition)
        op_name = _operation_name(segment)
        if op_name in _GEOMETRY_OPS:
            # A transform effect. Clips are commonly wrapped in MORE than one (a
            # SpatialAdapter reformat inside a PaintResize, say), so geometry is a
            # LIST in application order — innermost first, because this walk annotates
            # on the way back out. Collapsing them to one field would silently drop a
            # stage of the transform stack.
            geometry = _geometry_fields(segment, op_name)
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
                pending_transition = {"type": "dissolve", "duration": duration}
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
            state = {"idx": 1, "events": [], "unhandled": {}}
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
