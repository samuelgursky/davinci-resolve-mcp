"""Pre-balance: neutral technical correction, and nothing else.

The assistant colorist's highest-leverage job is having the timeline *balanced*
before the colorist sits down, so expensive creative time is spent on the look
instead of on exposure. The economics are not subtle — a colorist at $400/hour
who spends the first two hours of every session fixing black levels is the most
expensive way in the building to do a job that is almost entirely mechanical.

What makes it automatable is that the craft defines the task **negatively**, and
with unusual precision:

    IS:     neutral technical correction, a consistent starting point,
            scene-to-scene baseline matching, problem identification.
    IS NOT: creative grading, look development, final correction, or guessing
            at the director's intent.

Every "is not" in that list is a guardrail this module enforces in code rather
than in a docstring — see `ALLOWED_OPERATIONS` and `validate_plan`. An agent is
a beginner by default, and the classic beginner failure is exactly the one the
craft warns about: reaching for curves and a look before the image is balanced.

Two specifics that a naive implementation gets backwards:

1. **Black balance first, on the parade.** Align the channel bottoms; blue
   usually needs the most. Then the white point, on the brightest neutral.
2. **Do not neutralize midtones.** Skin is warm. It belongs near 11 o'clock on
   the vectorscope, not at equal RGB. "Make the midtones neutral" is the single
   fastest way to make everyone in the programme look grey, and it is what
   "auto-balance" means to most people writing it for the first time.

**The honest limit:** this has scopes and no eyes. Numeric balance is
defensible — the numbers are the numbers. Look development is not, and this
module will not attempt it. It also cannot know that the dim office was dim on
purpose, which is why every judgement call is flagged for a human instead of
being applied.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: The only grade operations a pre-balance is permitted to propose. Anything
#: outside this set is creative and belongs to the colorist. Enforced by
#: `validate_plan`, which is called before any plan is returned.
ALLOWED_OPERATIONS = frozenset({"lift", "gain", "gamma_master", "legal_limit"})

#: Broadcast-legal limits, 0-1 normalized (Rec.709 10-bit 64-940 → 0.0625-0.918).
#: Present from the first node rather than bolted on at delivery: the craft is
#: blunt that a grade violating legal levels is an instant QC rejection, and a
#: limiter added at the end changes an image someone already approved.
LEGAL_BLACK = 0.0625
LEGAL_WHITE = 0.918

#: Pass depths. Named after the assistant-colorist convention so a colorist can
#: ask for a level and get what they expect. Rates are for planning, not
#: promises — they come from the craft's own published throughput figures.
QUALITY_TIERS = {
    "quick": {
        "level": 1,
        "clips_per_hour": 45,
        "description": "black and white balance only, hero shot per scene, rough match",
    },
    "standard": {
        "level": 2,
        "clips_per_hour": 22,
        "description": "full balance of each shot, scene-to-scene matching, problem flagging",
    },
    "deep": {
        "level": 3,
        "clips_per_hour": 11,
        "description": "complete balance, continuity checking, technical QC, documentation",
    },
}
DEFAULT_TIER = "standard"


def resolve_tier(tier: Optional[str]) -> Dict[str, Any]:
    """Map a tier name to its depth. Unknown names raise rather than default."""
    name = (tier or DEFAULT_TIER).strip().lower()
    if name not in QUALITY_TIERS:
        raise ValueError(
            f"unknown tier {tier!r}; expected one of {', '.join(sorted(QUALITY_TIERS))}"
        )
    return {"tier": name, **QUALITY_TIERS[name]}


def estimate_effort(clip_count: int, tier: Optional[str] = None) -> Dict[str, Any]:
    """Rough hours for a pass at this depth, and what it is worth.

    Estimates and labelled as such. They exist because the assistant's prep has
    to justify itself in the next budget conversation, and a number nobody
    stated is a number nobody credits.
    """
    resolved = resolve_tier(tier)
    rate = float(resolved["clips_per_hour"])
    hours = round(clip_count / rate, 2) if rate else None
    return {
        **resolved,
        "clip_count": clip_count,
        "estimated_hours": hours,
        "basis": (
            f"{resolved['clips_per_hour']} clips/hour at the '{resolved['tier']}' depth. "
            "An ESTIMATE from published assistant-colorist throughput, not a promise."
        ),
    }

#: Explicitly forbidden, with the reason, so a rejection can explain itself.
FORBIDDEN_OPERATIONS = {
    "curves": "curves are look development, not balance",
    "vignette": "a vignette is a creative choice about where the eye goes",
    "saturation": "saturation is taste; balance does not touch it",
    "qualifier": "secondaries are beyond an assistant's technical scope",
    "power_window": "windows are creative isolation, not correction",
    "hue_shift": "shifting hue is grading",
    "midtone_neutralize": (
        "skin is warm and belongs near 11 o'clock on the vectorscope; "
        "neutralizing midtones makes everyone grey"
    ),
}

#: Node label. One node, at the head of the tree, so the colorist can bypass the
#: entire assistant pass with a single keystroke and see the original.
BALANCE_NODE_LABEL = "ASST: Balance"

#: Percentiles used to find the black and white points. Not min/max: a single
#: hot pixel or a dead one would otherwise define the whole correction.
BLACK_POINT_PERCENTILE = 0.5
WHITE_POINT_PERCENTILE = 99.5

#: Targets in 0-1. Not 0.0/1.0 — legal video leaves headroom, and slamming the
#: black point to zero crushes the shadow detail the colorist needs to work in.
TARGET_BLACK = 0.02
TARGET_WHITE = 0.92

#: Above this fraction of pixels at the extremes, the shot has a problem the
#: grade cannot fix and a human should be told rather than have it papered over.
CLIP_WARN_FRACTION = 0.02
CRUSH_WARN_FRACTION = 0.02

#: Corrections smaller than this are noise. Proposing them adds churn to the
#: node tree and tells the colorist nothing.
MIN_MEANINGFUL_ADJUSTMENT = 0.004

#: How close to the targets already counts as "there". Without this, a shot
#: whose white point sits at 0.90 against a 0.92 target gets a 2% gain node it
#: does not need — and a timeline of near-identical corrections is worse than
#: none, because the colorist now has to check every one of them to find the
#: handful that mattered. Being nearly right is the normal state of graded-ish
#: material and should produce silence, not activity.
TARGET_TOLERANCE = 0.03


class GuardrailViolation(Exception):
    """Raised when a plan contains an operation a pre-balance may not make."""


def channel_levels(percentiles: Mapping[str, Mapping[str, float]]) -> Dict[str, Any]:
    """Normalize per-channel percentile readings into a levels report.

    `percentiles`: `{"r": {"black": .., "white": .., "clipped": .., "crushed": ..}, ...}`
    with values in 0-1. Kept as plain numbers so the analysis is testable
    without decoding a frame.
    """
    out: Dict[str, Any] = {}
    for channel in ("r", "g", "b"):
        row = percentiles.get(channel) or {}
        out[channel] = {
            "black": float(row.get("black", 0.0)),
            "white": float(row.get("white", 1.0)),
            "clipped_fraction": float(row.get("clipped", 0.0)),
            "crushed_fraction": float(row.get("crushed", 0.0)),
        }
    blacks = [out[c]["black"] for c in "rgb"]
    whites = [out[c]["white"] for c in "rgb"]
    out["black_spread"] = round(max(blacks) - min(blacks), 5)
    out["white_spread"] = round(max(whites) - min(whites), 5)
    return out


def measure_frame_levels(media_path: str, at_seconds: float = 0.0) -> Dict[str, Any]:
    """Read black/white points off one frame via ffmpeg + numpy.

    Separated from the math above so the analysis stays testable without
    decoding video. Honest-refuses when the tools are absent rather than
    guessing — an invented level would produce a confident, wrong grade.

    Percentiles rather than min/max: one hot pixel or one dead one would
    otherwise define the entire correction for the shot.
    """
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        return {"success": False, "error": "ffmpeg not found on PATH — cannot measure levels"}
    try:
        import numpy as np
    except Exception:
        return {
            "success": False,
            "error": "numpy is required to measure levels",
            "remediation": "pip install numpy",
        }

    width = height = 128  # enough for percentiles, cheap to decode
    cmd = [
        "ffmpeg", "-v", "error", "-ss", str(max(0.0, float(at_seconds))),
        "-i", media_path, "-frames:v", "1",
        "-vf", f"scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"success": False, "error": f"frame extraction failed: {exc}"}
    expected = width * height * 3
    if proc.returncode != 0 or len(proc.stdout) < expected:
        return {
            "success": False,
            "error": (proc.stderr or b"").decode("utf-8", "replace").strip()
                     or "ffmpeg produced no frame at that timestamp",
        }

    frame = np.frombuffer(proc.stdout[:expected], dtype=np.uint8).reshape(height, width, 3)
    readings: Dict[str, Dict[str, float]] = {}
    for index, channel in enumerate("rgb"):
        plane = frame[:, :, index].astype("float32") / 255.0
        readings[channel] = {
            "black": float(np.percentile(plane, BLACK_POINT_PERCENTILE)),
            "white": float(np.percentile(plane, WHITE_POINT_PERCENTILE)),
            "clipped": float((plane >= 0.996).mean()),
            "crushed": float((plane <= 0.004).mean()),
        }
    return {"success": True, "levels": channel_levels(readings), "sampled_at_seconds": at_seconds}


def propose_balance(levels: Mapping[str, Any]) -> Dict[str, Any]:
    """Lift and gain offsets that align the channels and set the end points.

    Black balance first (align the bottoms), then white (align the tops). The
    two interact — moving gain shifts where the blacks sit — so the black
    correction is computed first and the gain is derived from the *corrected*
    range rather than the raw one.
    """
    lift: Dict[str, float] = {}
    gain: Dict[str, float] = {}
    reasons: List[str] = []

    within_tolerance = all(
        abs(float(levels[c]["black"]) - TARGET_BLACK) <= TARGET_TOLERANCE
        and abs(float(levels[c]["white"]) - TARGET_WHITE) <= TARGET_TOLERANCE
        for c in ("r", "g", "b")
    )
    if within_tolerance:
        return {
            "node_label": BALANCE_NODE_LABEL,
            "operations": {"lift": {c: 0.0 for c in "rgb"}, "gain": {c: 1.0 for c in "rgb"}},
            "reasons": [
                "Already balanced within tolerance — no correction proposed. A node "
                "per shot that changes nothing is worse than no node: the colorist "
                "has to check every one to find the few that mattered."
            ],
            "midtones": "untouched — nothing to correct",
            "no_op": True,
        }

    for channel in ("r", "g", "b"):
        black = float(levels[channel]["black"])
        offset = TARGET_BLACK - black
        lift[channel] = round(offset, 5)

    biggest = max(("r", "g", "b"), key=lambda c: abs(lift[c]))
    if abs(lift[biggest]) >= MIN_MEANINGFUL_ADJUSTMENT:
        reasons.append(
            f"Black balance: {biggest.upper()} moved {lift[biggest]:+.3f} to align the "
            f"channel bottoms on the parade (spread was {levels['black_spread']:.3f})."
        )

    for channel in ("r", "g", "b"):
        corrected_black = TARGET_BLACK
        corrected_white = float(levels[channel]["white"]) + lift[channel]
        span = corrected_white - corrected_black
        gain[channel] = round((TARGET_WHITE - corrected_black) / span, 5) if span > 1e-6 else 1.0

    if any(abs(gain[c] - 1.0) >= MIN_MEANINGFUL_ADJUSTMENT for c in "rgb"):
        reasons.append(
            f"White balance: gain set per channel to bring the top of the range to "
            f"{TARGET_WHITE:.2f} without clipping (white spread was {levels['white_spread']:.3f})."
        )

    if not reasons:
        reasons.append("Already balanced within tolerance — no correction proposed.")

    return {
        "node_label": BALANCE_NODE_LABEL,
        "operations": {
            "lift": lift,
            "gain": gain,
            # In the tree from the start, not bolted on at delivery. A limiter
            # added at the end changes an image the colourist already approved,
            # and a grade that violates legal levels is an instant QC rejection.
            "legal_limit": {"black": LEGAL_BLACK, "white": LEGAL_WHITE},
        },
        "reasons": reasons + [
            f"Legal limiter in the tree from the first node ({LEGAL_BLACK:.3f}-"
            f"{LEGAL_WHITE:.3f}), not added at delivery."
        ],
        # Stated explicitly in the output, not just in the docs, because it is
        # the thing most likely to be "improved" by someone later.
        "midtones": (
            "untouched by design — skin is warm and belongs near 11 o'clock on the "
            "vectorscope; neutralizing midtones would make everyone grey"
        ),
    }


def detect_problems(levels: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Things the grade cannot fix. Flag them; never quietly paper over them."""
    problems: List[Dict[str, str]] = []
    for channel in ("r", "g", "b"):
        if levels[channel]["clipped_fraction"] > CLIP_WARN_FRACTION:
            problems.append({
                "type": "TECH",
                "channel": channel,
                "description": (
                    f"{levels[channel]['clipped_fraction'] * 100:.1f}% of the "
                    f"{channel.upper()} channel is clipped at the top — that detail "
                    "is not in the file and no grade recovers it"
                ),
            })
        if levels[channel]["crushed_fraction"] > CRUSH_WARN_FRACTION:
            problems.append({
                "type": "TECH",
                "channel": channel,
                "description": (
                    f"{levels[channel]['crushed_fraction'] * 100:.1f}% of the "
                    f"{channel.upper()} channel is crushed at the bottom"
                ),
            })
    if levels["black_spread"] > 0.08:
        problems.append({
            "type": "CREATIVE",
            "channel": "all",
            "description": (
                f"Black spread is {levels['black_spread']:.3f} — a strong colour cast "
                "in the shadows. Balanced here on the assumption it is unintended; "
                "if the DP asked for it, bypass this node"
            ),
        })
    return problems


def validate_plan(plan: Mapping[str, Any]) -> None:
    """Refuse any plan that strays outside neutral technical correction.

    A test, not a guideline. The guardrails are the product: a pre-balance that
    quietly develops a look has destroyed exactly the trust that makes a
    colorist willing to let an assistant near the timeline at all.
    """
    operations = plan.get("operations") or {}
    for name in operations:
        if name in FORBIDDEN_OPERATIONS:
            raise GuardrailViolation(
                f"pre-balance may not use {name!r}: {FORBIDDEN_OPERATIONS[name]}"
            )
        if name not in ALLOWED_OPERATIONS:
            raise GuardrailViolation(
                f"pre-balance proposed an unrecognized operation {name!r}; "
                f"allowed: {', '.join(sorted(ALLOWED_OPERATIONS))}"
            )


def group_by_setup(clips: Sequence[Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    """Group clips by lighting setup rather than timeline order.

    Balancing in timeline order means re-deriving the same correction for every
    angle of the same setup and getting slightly different answers each time —
    which is precisely the scene-to-scene inconsistency the pass exists to
    prevent. Group first, balance the hero, match the rest to it.
    """
    groups: Dict[str, List[Mapping[str, Any]]] = {}
    for clip in clips:
        key = str(clip.get("setup") or clip.get("scene") or "ungrouped")
        groups.setdefault(key, []).append(clip)
    return groups


def pick_hero(group: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """The clip the rest of a setup is matched to.

    Longest on screen, tie-broken by the widest usable range — the shot with
    most screen time carries the audience's sense of what the scene looks like,
    and a well-exposed one gives the match something honest to aim at.
    """
    if not group:
        return None
    def score(clip: Mapping[str, Any]):
        levels = clip.get("levels") or {}
        span = 0.0
        if levels:
            span = max(
                (float(levels[c]["white"]) - float(levels[c]["black"])) for c in "rgb"
            )
        return (float(clip.get("duration_seconds") or 0.0), span)
    return max(group, key=score)


def plan_prebalance(clips: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build a per-clip pre-balance plan, grouped by setup, hero-matched.

    Each clip: `{"name", "duration_seconds", "setup"|"scene", "levels"}` where
    `levels` came from `channel_levels`. Clips with no levels are reported as
    **not analyzed**, never as balanced.
    """
    if not clips:
        return {"success": False, "error": "No clips supplied"}

    groups = group_by_setup(clips)
    plans: List[Dict[str, Any]] = []
    unanalyzed: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []

    for setup, group in sorted(groups.items()):
        measured = [c for c in group if c.get("levels")]
        for clip in group:
            if not clip.get("levels"):
                unanalyzed.append({
                    "clip": clip.get("name"),
                    "setup": setup,
                    "reason": "no levels measured — NOT balanced, and not certified balanced",
                })
        hero = pick_hero(measured)
        for clip in measured:
            balance = propose_balance(clip["levels"])
            validate_plan(balance)
            problems = detect_problems(clip["levels"])
            for problem in problems:
                flags.append({
                    "clip": clip.get("name"),
                    "marker_note": f"ASST: {problem['type']} - {problem['description']}",
                    **problem,
                })
            plans.append({
                "clip": clip.get("name"),
                "setup": setup,
                "is_hero": hero is not None and clip is hero,
                **balance,
                "problems": problems,
            })

    return {
        "success": True,
        "kind": "prebalance",
        "clip_count": len(clips),
        "balanced_count": len(plans),
        "setup_count": len(groups),
        "plans": plans,
        "flagged": flags,
        "unanalyzed": unanalyzed,
        "guardrails": {
            "allowed_operations": sorted(ALLOWED_OPERATIONS),
            "forbidden_operations": FORBIDDEN_OPERATIONS,
            "node_label": BALANCE_NODE_LABEL,
        },
        "note": (
            f"Neutral technical correction only, as one bypassable "
            f"'{BALANCE_NODE_LABEL}' node at the head of each tree. No curves, no "
            "vignettes, no saturation, no secondaries, and midtones deliberately "
            "left warm. This is a starting point for the colorist, not a look — "
            "it has scopes and no eyes, and it cannot know that the dim shot was "
            "dim on purpose. Problems are flagged for a human, never silently fixed."
        ),
    }
