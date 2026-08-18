"""Numeric image QC for a grade: does the result carry damage the source didn't?

This answers a different question from `verify_grade`. That one asks *did Resolve
apply what I asked* (intended vs applied `.drx` → landed/drifted/missing). This
asks *is the resulting image any good* — a grade can land perfectly and still be
flat, milky, crunchy, or banded.

The point is to give an agent deterministic grounds to **reject its own grade**
and iterate, instead of shipping the first look that rendered. Flags carry a
remedy, not just a label, and `acceptable` is simply "no flags".

## Measured on the real frame, never on the transform

Every metric is computed from a decoded frame of the *actual* graded result —
either a rendered file or the source pushed through the LUT by ffmpeg. Applying
the transform in numpy and measuring that instead would hide exactly the damage
worth catching: LUT interpolation, encode rounding, and clamping are where
banding and posterization are actually introduced.

## Display-referred only, and it refuses rather than guessing

Every metric here is defined on L*/chroma in CIE Lab derived from an sRGB
transfer function. Log and scene-referred encodings (ACEScct, S-Log3, LogC) run
through the same arithmetic happily and produce numbers that are meaningless:
a log frame's "black point" is nowhere near its actual shadow detail.

So `working_space` must be declared, non-display-referred values are refused, and
the file's own `color_transfer` tag is probed to catch a mis-declaration. This
module will not convert for you — the correct transform depends on the camera
and the project's colour management, which is not knowable from a frame.

## Thresholds are advisory, not standards

Unlike loudness there is no published spec for "too much banding". The numbers
below are chosen so a clean grade raises nothing and obvious damage raises
something; they are tuning, and the report always includes the raw measurements
so a human can disagree with the flag rather than only with the verdict.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger("resolve-mcp.image-qc")

try:  # numpy is present in most installs but is not a hard requirement.
    import numpy as _np
except ImportError:  # pragma: no cover - exercised on minimal installs
    _np = None

from src.utils import colorimetry as _cm

#: Every public entry point calls `_require()` before touching numpy, so the
#: internals below treat `_np` as present. Declared machine-readably rather
#: than left implied — see tests/test_optional_dependency_guards.py.
_OPTIONAL_DEPENDENCY_CONTRACT = (
    "numpy: every public entry point calls _require() first; internals assume it is present"
)

#: Analysis raster. Large enough that smooth-region and banding statistics are
#: meaningful, small enough that a frame decodes in well under a second.
ANALYSIS_WIDTH = 960
ANALYSIS_HEIGHT = 540

#: Encodings these metrics are defined on.
DISPLAY_REFERRED_SPACES = frozenset({"rec709", "srgb", "bt709", "display_p3", "rec1886"})

#: ffprobe `color_transfer` values that mean the frame is NOT display-referred.
#: Presence of any of these contradicts a display-referred declaration.
_NON_DISPLAY_TRANSFERS = frozenset({
    "smpte2084", "arib-std-b67", "log100", "log316", "bt1361e", "smpte428",
})

#: A region counts as "smooth" when it sits this close to its own local mean.
#: Skies, walls and gradients — where amplification and banding show first.
SMOOTH_TOLERANCE_L = 0.8
#: Below this many smooth pixels the statistic is not worth reporting.
MIN_SMOOTH_PIXELS = 2000
#: Shadows, for the shadow-noise ratio.
SHADOW_L_MAX = 30.0
#: Highlights, for the posterization measure.
HIGHLIGHT_L_MIN = 80.0
#: At/above this L* a pixel counts as clipped.
CLIPPED_L = 96.5

# ── Flag thresholds (advisory; see the module docstring) ─────────────────────
NOISE_OVERALL_RATIO = 1.5
NOISE_SHADOW_RATIO = 1.6
NOISE_SMOOTH_RATIO = 1.6
BANDING_LOSS = 0.30
POSTERIZATION_LOSS = 0.25
CLIP_GROWTH = 0.005
FLAT_CONTRAST_RATIO = 0.80
MILKY_BLACK_LIFT_L = 8.0
#: Chroma collapse. A grade that desaturates this far has thrown colour away —
#: "clean" is not the same as "grey", and nothing else here would catch it.
WASHED_OUT_CHROMA_RATIO = 0.60


#: Cost tiers for the vision escalation. `numeric` never spends tokens;
#: `vision_on_doubt` spends only where the numbers cannot settle the question.
COST_TIERS = ("numeric", "vision_on_doubt", "vision_always")
DEFAULT_COST_TIER = "vision_on_doubt"

#: A grade that moved this far without raising a flag is worth a second opinion:
#: the numbers say "undamaged", which is not the same as "good".
DOUBT_SHIFT_DELTA_E = 6.0
#: Flags whose correctness depends on what the frame actually shows. A real sky
#: gradient legitimately has low level density; a face going grey does not.
_CONTENT_DEPENDENT_FLAGS = frozenset({"banding", "washed_out", "flat"})


class ImageQcError(RuntimeError):
    """A refusal — bad inputs or an encoding these metrics do not apply to."""


def capabilities() -> Dict[str, Any]:
    return {
        "numpy": _np is not None,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "analysis_raster": [ANALYSIS_WIDTH, ANALYSIS_HEIGHT],
        "display_referred_spaces": sorted(DISPLAY_REFERRED_SPACES),
    }


def _require() -> None:
    if _np is None:
        raise ImageQcError("numpy is required for image QC")
    if not shutil.which("ffmpeg"):
        raise ImageQcError("ffmpeg not found on PATH")


# ── decode ───────────────────────────────────────────────────────────────────


def _decode_frame(
    path: str,
    time_seconds: float,
    *,
    lut_path: Optional[str] = None,
    width: int = ANALYSIS_WIDTH,
    height: int = ANALYSIS_HEIGHT,
) -> "Optional[_np.ndarray]":
    """One frame → (h, w, 3) float array in [0, 1], optionally through a LUT."""
    # Nearest-neighbour, deliberately. Any averaging rescale (bilinear, bicubic,
    # the ffmpeg default) *invents intermediate values* — it manufactures level
    # density on the way in and hides the exact quantisation the banding and
    # posterization metrics exist to find. Upscaling a quantised frame fabricates
    # levels; downscaling averages them away. Neighbour sampling carries real
    # pixel values through unchanged, and preserves noise amplitude too (an
    # averaging downscale attenuates noise by ~sqrt of the ratio, which would
    # quietly deflate the amplification ratios).
    chain = f"scale={width}:{height}:flags=neighbor"
    if lut_path:
        # ffmpeg filter syntax: ':' and '\' are separators inside a filter arg.
        escaped = lut_path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
        chain += f",lut3d='{escaped}'"
    chain += ",format=rgb24"
    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, float(time_seconds)):.3f}",
        "-i", path,
        "-frames:v", "1",
        "-vf", chain,
        "-f", "rawvideo", "-",
    ]
    try:
        proc = subprocess.run(args, capture_output=True, timeout=120, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("frame decode failed for %s: %s", path, exc)
        return None
    expected = width * height * 3
    if proc.returncode != 0 or len(proc.stdout) < expected:
        return None
    arr = _np.frombuffer(proc.stdout[:expected], dtype=_np.uint8).reshape(height, width, 3)
    return arr.astype(_np.float64) / 255.0


def _probe_color_transfer(path: str) -> Optional[str]:
    if not shutil.which("ffprobe"):
        return None
    args = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=color_transfer", "-of", "default=nw=1:nk=1", path,
    ]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    value = (proc.stdout or "").strip().lower()
    return value or None


def _check_working_space(paths: List[str], working_space: str) -> List[str]:
    """Refuse non-display-referred declarations; warn on a contradicted tag."""
    space = str(working_space or "").strip().lower().replace("-", "").replace(" ", "")
    space = {"bt709": "bt709", "rec709": "rec709", "srgb": "srgb"}.get(space, space)
    if space not in DISPLAY_REFERRED_SPACES:
        raise ImageQcError(
            f"working_space {working_space!r} is not display-referred. These metrics are "
            f"defined on sRGB-encoded L*/chroma; a log or scene-referred frame (ACEScct, "
            f"S-Log3, LogC) produces numbers that look plausible and mean nothing. Convert "
            f"to a display-referred space first, then re-run. Accepted: "
            f"{', '.join(sorted(DISPLAY_REFERRED_SPACES))}."
        )
    warnings: List[str] = []
    for path in paths:
        transfer = _probe_color_transfer(path)
        if transfer and transfer in _NON_DISPLAY_TRANSFERS:
            warnings.append(
                f"{os.path.basename(path)} is tagged color_transfer={transfer}, which "
                f"contradicts working_space={working_space}. The metrics below assume a "
                f"display-referred frame; treat them as unreliable until that is resolved."
            )
    return warnings


# ── primitives ───────────────────────────────────────────────────────────────


def _box_blur(gray: "_np.ndarray", k: int = 5) -> "_np.ndarray":
    """Mean filter via summed-area table — O(1) per pixel, no scipy."""
    pad = k // 2
    padded = _np.pad(gray, pad, mode="edge")
    csum = _np.cumsum(_np.cumsum(padded, axis=0), axis=1)
    csum = _np.pad(csum, ((1, 0), (1, 0)))
    return (csum[k:, k:] - csum[:-k, k:] - csum[k:, :-k] + csum[:-k, :-k]) / float(k * k)


def _smooth_mask(luma: "_np.ndarray", k: int = 7) -> "_np.ndarray":
    """Pixels sitting close to their local mean — skies, walls, gradients."""
    return _np.abs(luma - _box_blur(luma, k)) < SMOOTH_TOLERANCE_L


def _noise_level(rgb: "_np.ndarray", mask: "Optional[_np.ndarray]" = None) -> float:
    """High-frequency residual std — a grain / compression-noise estimate."""
    gray = rgb.mean(axis=-1)
    residual = gray - _box_blur(gray, 5)
    if mask is not None:
        if not mask.any():
            return 0.0
        residual = residual[mask]
    return float(residual.std())


def _level_density_loss(src_l: "_np.ndarray", out_l: "_np.ndarray", mask: "_np.ndarray") -> Optional[float]:
    """Fraction of distinct L* levels the grade collapsed inside `mask`.

    Counting distinct quantised levels is what separates banding from a merely
    darker picture: a healthy grade moves levels, a damaging one merges them.
    """
    if mask.sum() < MIN_SMOOTH_PIXELS:
        return None
    levels_src = len(_np.unique(_np.round(src_l[mask], 1))) or 1
    levels_out = len(_np.unique(_np.round(out_l[mask], 1)))
    return round(max(0.0, 1.0 - levels_out / levels_src), 4)


def _tonal_stats(lab: "_np.ndarray") -> Dict[str, float]:
    flat = lab.reshape(-1, 3)
    luma = flat[:, 0]
    return {
        "black_point_L": round(float(_np.percentile(luma, 0.5)), 2),
        "white_point_L": round(float(_np.percentile(luma, 99.5)), 2),
        "contrast_L_std": round(float(luma.std()), 2),
        "mean_chroma": round(float(_np.hypot(flat[:, 1], flat[:, 2]).mean()), 2),
    }


def _noise_amplification(src_rgb: "_np.ndarray", out_rgb: "_np.ndarray", src_l: "_np.ndarray") -> Dict[str, float]:
    shadows = src_l < SHADOW_L_MAX
    smooth = _smooth_mask(src_l)

    def ratio(mask: "Optional[_np.ndarray]") -> float:
        base = _noise_level(src_rgb, mask)
        if base < 1e-6:
            return 1.0
        return round(_noise_level(out_rgb, mask) / base, 3)

    out = {"overall_ratio": ratio(None), "shadow_ratio": ratio(shadows)}
    out["smooth_region_ratio"] = ratio(smooth) if smooth.sum() >= MIN_SMOOTH_PIXELS else 1.0
    out["smooth_region_pixels"] = int(smooth.sum())
    return out


def _damage(src_lab: "_np.ndarray", out_lab: "_np.ndarray") -> Dict[str, Any]:
    src_l, out_l = src_lab[..., 0], out_lab[..., 0]
    smooth = _smooth_mask(src_l)
    highlights = out_l > HIGHLIGHT_L_MIN
    return {
        "clipped_fraction_source": round(float((src_l > CLIPPED_L).mean()), 5),
        "clipped_fraction_result": round(float((out_l > CLIPPED_L).mean()), 5),
        "highlight_posterization": _level_density_loss(src_l, out_l, highlights),
        "smooth_region_banding": _level_density_loss(src_l, out_l, smooth),
    }


# ── verdict ──────────────────────────────────────────────────────────────────


def _flags(source: Dict[str, float], result: Dict[str, float], noise: Dict[str, float], damage: Dict[str, Any]) -> List[Dict[str, str]]:
    """Every flag carries a remedy — a label alone does not tell an agent what to change."""
    flags: List[Dict[str, str]] = []

    def flag(flag_id: str, detail: str, remedy: str) -> None:
        flags.append({"id": flag_id, "detail": detail, "remedy": remedy})

    if result["contrast_L_std"] < FLAT_CONTRAST_RATIO * source["contrast_L_std"]:
        flag(
            "flat",
            f"contrast fell from {source['contrast_L_std']} to {result['contrast_L_std']} (L* std)",
            "raise contrast or lower the lift; a match on mean colour can still read as flat",
        )
    if result["mean_chroma"] < WASHED_OUT_CHROMA_RATIO * source["mean_chroma"]:
        flag(
            "washed_out",
            f"mean chroma fell from {source['mean_chroma']} to {result['mean_chroma']}",
            "restore saturation; a desaturated image is not the same as a clean one",
        )
    if result["black_point_L"] > source["black_point_L"] + MILKY_BLACK_LIFT_L:
        flag(
            "milky",
            f"black point lifted from {source['black_point_L']} to {result['black_point_L']} L*",
            "bring the black point back down, or reduce the shadow lift",
        )
    if noise["shadow_ratio"] > NOISE_SHADOW_RATIO or noise["overall_ratio"] > NOISE_OVERALL_RATIO or noise["smooth_region_ratio"] > NOISE_SMOOTH_RATIO:
        flag(
            "noisy",
            f"noise ratios overall {noise['overall_ratio']}, shadow {noise['shadow_ratio']}, "
            f"smooth-region {noise['smooth_region_ratio']}",
            "reduce the shadow lift, temper the strength, or denoise before the grade node",
        )
    grew = damage["clipped_fraction_result"] - damage["clipped_fraction_source"]
    if grew > CLIP_GROWTH:
        flag(
            "clipped",
            f"clipped area grew by {round(grew * 100, 2)}% of frame",
            "soften the white point or add a highlight knee",
        )
    if (damage["highlight_posterization"] or 0.0) > POSTERIZATION_LOSS:
        flag(
            "posterized",
            f"{round((damage['highlight_posterization'] or 0) * 100)}% of highlight levels collapsed",
            "reduce the stretch, or grade in higher precision before baking",
        )
    if (damage["smooth_region_banding"] or 0.0) > BANDING_LOSS:
        flag(
            "banding",
            f"{round((damage['smooth_region_banding'] or 0) * 100)}% of smooth-region levels collapsed",
            "soften the curve, reduce strength, or dither/denoise the source",
        )
    return flags


def vision_escalation(report: Dict[str, Any], *, cost_tier: str = DEFAULT_COST_TIER) -> Dict[str, Any]:
    """Decide whether this report warrants spending a vision call.

    The numeric pass is free and deterministic; vision is neither. This is the
    gate that keeps a clean grade from costing anything, and it states its
    reasoning so the spend is never mysterious.

    Escalates on two situations the numbers genuinely cannot settle:

    - **No flags but a large move.** "Undamaged" is not "good". A grade that
      shifted the image a long way while tripping no metric is exactly where a
      look can be wrong in ways no threshold models.
    - **A content-dependent flag.** `banding` on a real sky gradient is correct
      behaviour, not damage; `washed_out` on a deliberately desaturated look is
      the intent. Only the picture can say which.

    Clipping, posterization and noise are *not* content-dependent — they are
    damage wherever they appear, so they never buy a vision call on their own.
    """
    if cost_tier not in COST_TIERS:
        raise ImageQcError(f"unknown cost_tier {cost_tier!r}; valid: {', '.join(COST_TIERS)}")

    flag_ids = [f["id"] for f in report.get("flags", [])]
    shift = float(report.get("grade_shift_delta_e2000") or 0.0)

    if cost_tier == "numeric":
        return {"escalate": False, "cost_tier": cost_tier, "reason": "numeric tier never calls vision"}
    if cost_tier == "vision_always":
        return {"escalate": True, "cost_tier": cost_tier, "reason": "vision_always tier"}

    content_dependent = sorted(set(flag_ids) & _CONTENT_DEPENDENT_FLAGS)
    if content_dependent:
        return {
            "escalate": True,
            "cost_tier": cost_tier,
            "reason": (
                f"flags {content_dependent} depend on what the frame shows — a real gradient "
                "bands legitimately and a deliberate desaturation is not damage"
            ),
            "triggering_flags": content_dependent,
        }
    if not flag_ids and shift >= DOUBT_SHIFT_DELTA_E:
        return {
            "escalate": True,
            "cost_tier": cost_tier,
            "reason": (
                f"no flags, but the grade moved {round(shift, 2)} ΔE2000 "
                f"(>= {DOUBT_SHIFT_DELTA_E}) — undamaged is not the same as good"
            ),
            "grade_shift_delta_e2000": round(shift, 3),
        }
    if flag_ids:
        return {
            "escalate": False,
            "cost_tier": cost_tier,
            "reason": f"flags {sorted(flag_ids)} are damage wherever they appear; no judgement needed",
        }
    return {
        "escalate": False,
        "cost_tier": cost_tier,
        "reason": f"clean grade, {round(shift, 2)} ΔE2000 shift — nothing for vision to settle",
    }


def assess_grade(
    source_path: str,
    *,
    time_seconds: float,
    graded_path: Optional[str] = None,
    lut_path: Optional[str] = None,
    working_space: str = "rec709",
    cost_tier: str = DEFAULT_COST_TIER,
) -> Dict[str, Any]:
    """Compare a graded frame against its source and report measurable damage.

    Supply exactly one of `graded_path` (a rendered result) or `lut_path` (the
    source pushed through a 3D LUT by ffmpeg). Both routes decode a real frame.

    When comparing against a rendered file, the two are sampled at the same
    timestamp — that holds for a render of the same cut and does not hold for a
    re-timed or re-conformed one, in which case the comparison is meaningless.
    """
    _require()
    if bool(graded_path) == bool(lut_path):
        raise ImageQcError("supply exactly one of graded_path or lut_path")
    for path in (source_path, graded_path, lut_path):
        if path and not os.path.isfile(path):
            raise ImageQcError(f"file not found: {path}")

    warnings = _check_working_space([p for p in (source_path, graded_path) if p], working_space)

    src_rgb = _decode_frame(source_path, time_seconds)
    if src_rgb is None:
        raise ImageQcError(f"could not decode a frame from {source_path} at {time_seconds}s")
    if graded_path:
        out_rgb = _decode_frame(graded_path, time_seconds)
        basis = "rendered_file"
    else:
        out_rgb = _decode_frame(source_path, time_seconds, lut_path=lut_path)
        basis = "lut_applied"
    if out_rgb is None:
        raise ImageQcError("could not decode the graded frame")

    src_lab = _cm.srgb_to_lab(src_rgb)
    out_lab = _cm.srgb_to_lab(out_rgb)
    source_stats = _tonal_stats(src_lab)
    result_stats = _tonal_stats(out_lab)
    noise = _noise_amplification(src_rgb, out_rgb, src_lab[..., 0])
    damage = _damage(src_lab, out_lab)
    flags = _flags(source_stats, result_stats, noise, damage)

    # How far the grade moved the image, in a perceptually sane metric. This is
    # a magnitude, not a verdict — a big move is not automatically wrong.
    shift = float(
        _cm.delta_e2000(src_lab.reshape(-1, 3).mean(axis=0), out_lab.reshape(-1, 3).mean(axis=0))
    )

    report: Dict[str, Any] = {
        "acceptable": not flags,
        "flags": flags,
        "basis": basis,
        "working_space": working_space,
        "time_seconds": round(float(time_seconds), 3),
        "grade_shift_delta_e2000": round(shift, 3),
        "source": source_stats,
        "result": result_stats,
        "noise_amplification": noise,
        "damage": damage,
        "warnings": warnings,
        "measurement": {
            "raster": [ANALYSIS_WIDTH, ANALYSIS_HEIGHT],
            "note": (
                "Measured on a decoded frame of the real graded result, not on a simulated "
                "transform — LUT interpolation and encode rounding are where banding is "
                "actually introduced."
            ),
        },
    }
    report["vision"] = vision_escalation(report, cost_tier=cost_tier)
    return report
