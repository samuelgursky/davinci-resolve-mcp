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
    """Lay a Sequence's components end to end. Returns the record length consumed."""
    start = rec
    pending_transition = transition
    components = getattr(sequence, "components", None)
    if components is None:
        components = [sequence]
    for comp in components:
        cls = type(comp).__name__
        try:
            if cls == "Transition":
                # A transition overlaps its neighbours; it does not advance rec itself.
                pending_transition = {"type": "dissolve", "duration": _length(comp)}
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
            for slot in getattr(mob, "slots", []) or []:
                seg = getattr(slot, "segment", None)
                if seg is None:
                    continue
                # Skip non-editorial slots by MEDIA KIND (timecode/edgecode/descriptive
                # metadata/sound master) — see _NON_EDITORIAL_KINDS.
                if not _is_editorial_slot(slot):
                    continue
                _walk_slot(
                    seg,
                    prefix=_media_kind_to_track(slot),
                    fps=_fps_from_edit_rate(getattr(slot, "edit_rate", None)),
                    state=state,
                )
            events = state["events"]
            sequences.append(
                {
                    "id": mob_id or (str(name) if name else f"seq{len(sequences) + 1}"),
                    "name": str(name) if name else f"Sequence {len(sequences) + 1}",
                    "eventCount": len(events),
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
