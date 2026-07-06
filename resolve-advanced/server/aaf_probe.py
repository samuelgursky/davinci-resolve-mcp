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
          "events": [ {normalized-event}, ... ] }
      ]
    }

Normalized event shape mirrors resolve-advanced/server/editorial.mjs `evt()`:
    { index, track, source, srcIn, srcOut, recIn, recOut, speed, reverse, transition, fps }

Honest-refuse discipline (no fake parses):
  * exit 3  → pyaaf2 not installed        (stderr: AAF_PROBE_NO_PYAAF2)
  * exit 4  → file unreadable / not an AAF (stderr: AAF_PROBE_UNREADABLE: <detail>)
  * exit 2  → bad invocation
Per-sequence event extraction is best-effort and defensive: if a component can't
be decoded we still report the sequence with its clip count — we never fabricate.
"""

import json
import os
import sys


def _fps_from_edit_rate(edit_rate):
    try:
        return round(float(edit_rate), 6)
    except Exception:
        return None


def _source_name(clip):
    """Best-effort human name for a SourceClip: referenced mob name, else clip name.

    pyaaf2 returns the class name (e.g. "SourceClip") for an unset `.name`, so treat a value
    equal to the object's type name as absent rather than reporting it as a real source.
    """
    cls = type(clip).__name__
    for getter in (
        lambda c: getattr(c, "mob", None) and c.mob.name,
        lambda c: getattr(c, "name", None),
    ):
        try:
            v = getter(clip)
            if v and str(v) != cls:
                return str(v)
        except Exception:
            pass
    return "UNKNOWN"


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


def _walk_sequence(segment, *, track, fps, start_index):
    """
    Walk a Sequence's components into normalized events. Handles SourceClip,
    Filler (gap), Transition (annotates the following clip), and OperationGroup
    (effect wrapper — descends to the inner source clip, flags a possible retime).
    """
    import aaf2  # noqa: F401  (guaranteed present by the caller)

    events = []
    rec = 0
    idx = start_index
    pending_transition = None

    components = getattr(segment, "components", None)
    if components is None:
        # Not a sequence (e.g. a lone SourceClip filling the whole slot).
        components = [segment]

    for comp in components:
        cls = type(comp).__name__
        try:
            if cls == "Transition":
                dur = int(getattr(comp, "length", 0) or 0)
                pending_transition = {"type": "dissolve", "duration": dur}
                # A transition overlaps neighbours; it does not advance rec on its own.
                continue
            if cls == "Filler":
                rec += int(getattr(comp, "length", 0) or 0)
                pending_transition = None
                continue
            if cls == "OperationGroup":
                # Effect wrapper (speed, etc.). Descend to the first inner SourceClip.
                inner = None
                for seg in getattr(comp, "segments", []) or []:
                    if type(seg).__name__ == "SourceClip":
                        inner = seg
                        break
                op_name = ""
                try:
                    op_name = str(getattr(getattr(comp, "operation", None), "name", "") or "")
                except Exception:
                    op_name = ""
                if inner is not None:
                    ev, length = _emit_source_clip(
                        inner, index=idx, track=track, rec=rec, fps=fps, transition=pending_transition
                    )
                    # We can detect that an effect is present but not reliably its ratio
                    # offline; flag it honestly rather than fake a speed number.
                    if "speed" in op_name.lower() or "motion" in op_name.lower():
                        ev["effect"] = op_name or "OperationGroup"
                    events.append(ev)
                    rec += length
                    idx += 1
                else:
                    rec += int(getattr(comp, "length", 0) or 0)
                pending_transition = None
                continue
            if cls == "SourceClip":
                ev, length = _emit_source_clip(
                    comp, index=idx, track=track, rec=rec, fps=fps, transition=pending_transition
                )
                events.append(ev)
                rec += length
                idx += 1
                pending_transition = None
                continue
            # Unknown component — advance by its length if it has one, don't fake an event.
            rec += int(getattr(comp, "length", 0) or 0)
            pending_transition = None
        except Exception:
            # Never let one bad component abort the whole sequence; skip it honestly.
            pending_transition = None
            continue
    return events


def _media_kind_to_track(slot):
    kind = ""
    try:
        kind = str(getattr(slot, "media_kind", "") or "")
    except Exception:
        kind = ""
    return "A" if kind.lower().startswith("sound") else "V"


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
            events = []
            idx = 1
            for slot in getattr(mob, "slots", []) or []:
                # Skip non-editorial slots (timecode / edgecode) — count only picture/sound.
                seg = getattr(slot, "segment", None)
                if seg is None:
                    continue
                seg_cls = type(seg).__name__
                if seg_cls in ("Timecode", "EdgeCode"):
                    continue
                track = _media_kind_to_track(slot)
                fps = _fps_from_edit_rate(getattr(slot, "edit_rate", None))
                slot_events = _walk_sequence(seg, track=track, fps=fps, start_index=idx)
                events.extend(slot_events)
                idx += len(slot_events)
            sequences.append(
                {
                    "id": mob_id or (str(name) if name else f"seq{len(sequences) + 1}"),
                    "name": str(name) if name else f"Sequence {len(sequences) + 1}",
                    "eventCount": len(events),
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
