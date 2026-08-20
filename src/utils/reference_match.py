"""Matching a shot to a graded reference still.

A colorist's most common instruction to an assistant is not a set of numbers,
it is a picture: *make it look like this one*. The reference still is the
shared language — the craft is explicit that stills and printed references are
how a DP and a colorist agree what they are aiming at, because the words for
colour are unreliable and the picture is not.

One of the users who prompted this whole programme was already doing it by hand:
grading a hero shot, saving it, and applying it as a power grade to get close on
the rest. That is exactly the right instinct and it should not require doing it
manually on every shot.

## What this is, and what it very much is not

It is **the same neutral technical correction as `prebalance`**, aimed at a
different target. Pre-balance moves a shot's black and white points to fixed
neutral targets; this moves them to *the reference's* black and white points.
Identical machinery, identical guardrails — `validate_plan` from `prebalance` is
reused rather than reimplemented, so it is impossible for this path to permit an
operation the pre-balance path forbids.

It is **not** a look transfer. Matching end points gets two shots into the same
tonal neighbourhood; it does not reproduce a grade. A reference with a heavy
creative curve, a vignette, or a qualifier-driven secondary will not be matched
by this and must not appear to be. The result says so, every time, because a
tool that quietly under-delivers on "make it look like this" wastes more of a
colorist's time than one that refuses.

## The one genuinely hard case, stated rather than hidden

If the reference and the target are of **different subject matter**, matching
their black and white points is close to meaningless — the darkest thing in a
night exterior and the darkest thing in a white-cyc interior are not the same
kind of measurement. A confidence signal is derived from how similar the two
level distributions are, and a poor match is reported as such instead of being
delivered with a straight face.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from src.utils import prebalance as _pb

#: Node label. Distinct from `ASST: Balance` so a colorist can see at a glance
#: which shots were matched to a reference and which were balanced to neutral.
MATCH_NODE_LABEL = "ASST: Match to ref"

#: Level distributions further apart than this suggest the two shots are not
#: comparable material, whatever the numbers say.
DISSIMILARITY_WARN = 0.25


def _spread(levels: Mapping[str, Any]) -> float:
    return max(
        float(levels[c]["white"]) - float(levels[c]["black"]) for c in ("r", "g", "b")
    )


def match_confidence(reference: Mapping[str, Any], target: Mapping[str, Any]) -> Dict[str, Any]:
    """How comparable these two images are, before any correction is proposed.

    Compares the *shape* of the two level distributions rather than their
    position: two shots of the same scene at different exposures are highly
    comparable, while a night exterior and a white-cyc interior are not, even if
    their end points happen to be close.
    """
    ref_spread, tgt_spread = _spread(reference), _spread(target)
    if ref_spread <= 0 or tgt_spread <= 0:
        return {"band": "low", "dissimilarity": None,
                "reason": "one of the images has no usable tonal range"}
    ratio = min(ref_spread, tgt_spread) / max(ref_spread, tgt_spread)
    dissimilarity = round(1.0 - ratio, 3)
    if dissimilarity <= 0.10:
        band, reason = "high", "the two images have comparable tonal range"
    elif dissimilarity <= DISSIMILARITY_WARN:
        band, reason = "medium", "tonal ranges differ noticeably; check the match by eye"
    else:
        band, reason = "low", (
            "the two images have very different tonal ranges — matching end points "
            "across dissimilar subject matter is close to meaningless. Treat this "
            "as a starting point only"
        )
    return {"band": band, "dissimilarity": dissimilarity, "reason": reason}


def propose_match(
    reference: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    reference_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Lift and gain that bring the target's end points to the reference's.

    Same order of operations as a pre-balance: black point first, then the gain
    derived from the *corrected* range rather than the raw one.
    """
    lift: Dict[str, float] = {}
    gain: Dict[str, float] = {}
    for channel in ("r", "g", "b"):
        ref_black = float(reference[channel]["black"])
        tgt_black = float(target[channel]["black"])
        lift[channel] = round(ref_black - tgt_black, 5)

    for channel in ("r", "g", "b"):
        ref_black = float(reference[channel]["black"])
        ref_white = float(reference[channel]["white"])
        corrected_white = float(target[channel]["white"]) + lift[channel]
        span = corrected_white - ref_black
        gain[channel] = round((ref_white - ref_black) / span, 5) if span > 1e-6 else 1.0

    confidence = match_confidence(reference, target)
    plan = {
        "node_label": MATCH_NODE_LABEL,
        "reference": reference_name,
        "operations": {
            "lift": lift,
            "gain": gain,
            "legal_limit": {"black": _pb.LEGAL_BLACK, "white": _pb.LEGAL_WHITE},
        },
        "confidence": confidence,
        "reasons": [
            f"Black points moved to the reference's ({reference_name or 'reference'}).",
            "Gain derived from the corrected range so the white point lands with it.",
            f"Legal limiter in the tree from the first node "
            f"({_pb.LEGAL_BLACK:.3f}-{_pb.LEGAL_WHITE:.3f}).",
        ],
        "midtones": (
            "untouched, as in a pre-balance — skin is warm and belongs near "
            "11 o'clock on the vectorscope"
        ),
        "scope": (
            "END POINTS ONLY. This puts the shot in the reference's tonal "
            "neighbourhood; it does NOT reproduce the reference's grade. Curves, "
            "vignettes and secondaries in the reference are not transferred and "
            "cannot be — copy the grade itself for that."
        ),
    }
    # Reuse the pre-balance guardrails rather than reimplementing them, so this
    # path cannot permit an operation the neutral path forbids.
    _pb.validate_plan(plan)
    return plan


def plan_reference_match(
    reference: Mapping[str, Any],
    targets: List[Mapping[str, Any]],
    *,
    reference_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Match a set of clips to one reference still.

    Each target: `{"name": str, "levels": {...}}` from `prebalance.channel_levels`.
    Targets without levels are reported as **not matched**, never as matched.
    """
    if not reference:
        return {"success": False, "error": "No reference levels supplied"}
    if not targets:
        return {"success": False, "error": "No target clips supplied"}

    plans: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, Any]] = []
    poor: List[str] = []
    for clip in targets:
        if not clip.get("levels"):
            unmatched.append({
                "clip": clip.get("name"),
                "reason": "no levels measured — NOT matched, and not certified matched",
            })
            continue
        plan = propose_match(reference, clip["levels"], reference_name=reference_name)
        plan["clip"] = clip.get("name")
        if plan["confidence"]["band"] == "low":
            poor.append(str(clip.get("name")))
        plans.append(plan)

    return {
        "success": True,
        "kind": "reference_match",
        "reference": reference_name,
        "matched_count": len(plans),
        "plans": plans,
        "unmatched": unmatched,
        "low_confidence_clips": poor,
        "guardrails": {
            "allowed_operations": sorted(_pb.ALLOWED_OPERATIONS),
            "forbidden_operations": _pb.FORBIDDEN_OPERATIONS,
            "node_label": MATCH_NODE_LABEL,
        },
        "note": (
            f"{len(plans)} clips matched to {reference_name or 'the reference'} on "
            "END POINTS ONLY — same neutral machinery and the same guardrails as a "
            "pre-balance, aimed at the reference instead of at neutral. It does NOT "
            "transfer the reference's grade; curves, vignettes and secondaries stay "
            "where they are."
            + (f" {len(poor)} clips are LOW confidence — very different tonal range "
               "from the reference, where matching end points means little: "
               + ", ".join(poor) + "." if poor else "")
            + (f" {len(unmatched)} clips had no measured levels and were not matched."
               if unmatched else "")
        ),
    }
