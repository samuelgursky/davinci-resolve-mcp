"""Turnover packages — what leaves the cutting room, and what it must contain.

A turnover is the moment the edit stops being one person's problem. Sound, VFX
and colour each need a different package, each has a specification that has been
stable for decades, and each fails in the same way: something obvious is
missing, nobody notices until the receiving facility has started, and the fix
costs a day of somebody else's schedule.

The specifications are not subtle. Sound wants an AAF with generous handles and
a picture reference with burned-in timecode. VFX wants plates with handles, a
burn, and a shot list. Colour wants the conform, the camera-original paths, and
whatever CDL or LUT the look was built on. All of it is checkable in advance.

## Manifests, not exports

This builds and validates the **manifest** — what belongs in the package, what
the handle requirement is, what is missing. It does not render or export;
that needs a live Resolve, and pretending otherwise would produce a package
nobody could deliver. The manifest is the useful half anyway: an export that
runs perfectly and omits the textless is still a failed turnover.

## The advice this exists to enforce

The single loudest instruction in the online-editing craft is about the picture
reference: *never, ever, EVER forget to send an output of your picture-locked
sequence with timecode burn.* Without it the receiving editor has no way to
verify anything against your intent. It is required in every package type here,
and its absence is a **blocker**, not a warning.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

#: Handle requirements by destination, in frames. Sound is far larger because
#: crossfades, room tone and dialogue overlap all reach past the picture cut.
HANDLE_REQUIREMENTS = {
    "sound": {"frames": 48, "note": "48-120 frames; crossfades and room tone reach past the cut"},
    "vfx": {"frames": 8, "note": "8-24 frames; tracking needs to run in and out of the shot"},
    "color": {"frames": 8, "note": "8-24 frames; room to slip a shot and to dissolve"},
}

#: What each package must contain. `required` absences are blockers.
PACKAGE_SPECS: Dict[str, Dict[str, Any]] = {
    "sound": {
        "required": ["aaf", "picture_reference_with_burn", "handles"],
        "recommended": ["session_notes", "adr_list", "temp_music_notes"],
        "audio": {"sample_rate": "48kHz", "bit_depth": 24, "channels": "split stereo to dual mono"},
    },
    "vfx": {
        "required": ["plates", "picture_reference_with_burn", "shot_list", "handles"],
        "recommended": ["clean_plates", "roto_reference", "camera_metadata", "reference_grade"],
    },
    "color": {
        "required": ["conform", "camera_original_paths", "picture_reference_with_burn"],
        "recommended": ["cdl", "show_lut", "dailies_lut", "scene_notes"],
    },
}

#: Burn-in fields for the picture reference. Source timecode and record timecode
#: are both required: one identifies the material, the other identifies the
#: position in the cut, and a reference carrying only one of them cannot settle
#: the argument it exists to settle.
BURN_IN_FIELDS = ("source_timecode", "record_timecode", "clip_name", "frame_count", "version")


def burn_in_spec(*, version: str, extra_fields: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The timecode-burn picture reference spec.

    Rendering it needs a live Resolve; this is the specification the render must
    satisfy, which is the half that gets forgotten.
    """
    fields = list(BURN_IN_FIELDS) + [f for f in (extra_fields or []) if f not in BURN_IN_FIELDS]
    return {
        "kind": "burn_in_spec",
        "fields": fields,
        "version": version,
        "codec": "H.264 or ProRes 422 Proxy — this is a reference, not a master",
        "requirement": (
            "Both source AND record timecode. One identifies the material, the other "
            "the position in the cut; a reference carrying only one cannot settle the "
            "argument it exists to settle."
        ),
        "note": (
            "Rendering needs a live Resolve — this is the spec that render must meet. "
            "The loudest instruction in online editing is to never send a turnover "
            "without one of these: without it the receiving editor cannot verify "
            "anything against your intent."
        ),
    }


def validate_package(
    destination: str,
    contents: Mapping[str, Any],
    *,
    handle_frames: Optional[int] = None,
) -> Dict[str, Any]:
    """Check a proposed turnover against its specification.

    `contents` maps a spec item to whatever represents it — a path, True, a
    count. A falsy or absent value counts as missing.
    """
    key = str(destination or "").strip().lower()
    if key not in PACKAGE_SPECS:
        return {
            "success": False,
            "error": f"unknown destination {destination!r}; expected one of "
                     f"{', '.join(sorted(PACKAGE_SPECS))}",
        }
    spec = PACKAGE_SPECS[key]
    required_handles = HANDLE_REQUIREMENTS[key]

    missing = [item for item in spec["required"] if not contents.get(item)]
    absent_recommended = [item for item in spec["recommended"] if not contents.get(item)]

    handle_finding = None
    if handle_frames is not None and handle_frames < required_handles["frames"]:
        handle_finding = (
            f"handles are {handle_frames} frames; {key} needs at least "
            f"{required_handles['frames']} — {required_handles['note']}"
        )
        if "handles" not in missing:
            missing.append("handles")

    return {
        "success": True,
        "kind": "turnover_manifest",
        "destination": key,
        "complete": not missing,
        "missing_required": missing,
        "missing_recommended": absent_recommended,
        "handle_requirement": required_handles,
        "handle_finding": handle_finding,
        "audio_spec": spec.get("audio"),
        "burn_in_required": True,
        "note": (
            f"{key} turnover is COMPLETE against spec."
            if not missing else
            f"{key} turnover is INCOMPLETE — missing: {', '.join(missing)}. "
            "These are blockers: a package that ships without them fails at the "
            "receiving facility, after they have started, and the fix costs a day "
            "of someone else's schedule."
        ) + (
            f" Also absent (recommended, not blocking): {', '.join(absent_recommended)}."
            if absent_recommended else ""
        ),
    }


def plan_turnover(
    destinations: Sequence[str],
    contents: Mapping[str, Any],
    *,
    version: str = "v01",
    handle_frames: Optional[int] = None,
) -> Dict[str, Any]:
    """Validate one set of contents against several destinations at once."""
    if not destinations:
        return {"success": False, "error": "No destinations supplied"}
    packages = []
    for destination in destinations:
        result = validate_package(destination, contents, handle_frames=handle_frames)
        if not result.get("success"):
            return result
        packages.append(result)

    incomplete = [p["destination"] for p in packages if not p["complete"]]
    return {
        "success": True,
        "kind": "turnover_plan",
        "version": version,
        "packages": packages,
        "burn_in_spec": burn_in_spec(version=version),
        "incomplete_destinations": incomplete,
        "all_complete": not incomplete,
        "note": (
            "All packages complete against spec."
            if not incomplete else
            f"{len(incomplete)} of {len(packages)} packages incomplete: "
            f"{', '.join(incomplete)}."
        ) + (
            " Manifests only — nothing is exported. An export that runs perfectly "
            "and omits the textless is still a failed turnover, so the checking is "
            "the useful half; rendering needs a live Resolve."
        ),
    }
