"""A rough mix that reports what it actually achieved, not what it intended.

The pieces for this have been here for a while: `media_analysis` measures EBU R128
loudness and detects silence, `delivery_targets` holds the standards, and the advanced
server's `loudness_qc` grades a finished file against a target. What was missing is the
step between measuring and grading — deciding the gains.

`plan()` derives the dialogue-normalisation gain, the music-bed level relative to it,
and the ducking windows the dialogue itself implies. `render()` mixes them
sample-accurately and then **measures the result**, so what comes back is the achieved
integrated loudness, true peak, and range — not the arithmetic that was supposed to
produce them. A plan that hits its target on paper and clips on true peak is a failed
plan, and only measuring the render can tell you which one you have.

## Measuring an isolated dialogue stem is already dialogue-gated

`ffmpeg`'s `ebur128` measures full program. That is why `delivery_targets` refuses to
assert a dialogue-gated integrated figure against a whole-mix measurement. Here the
dialogue stem is measured *alone*, which is the closest thing to a gated measurement
there is — so a dialogue-gated standard applies to the stem, and the module says so
rather than silently reusing a full-program number.

## Two things can be at the target, and they are not the same thing

Anchoring dialogue at the target is right for a dialogue-gated standard. For a
full-programme standard like R128 it is wrong the moment a bed is added: dialogue sits at
target, the music sits on top, and the programme lands above it. Anchoring the programme
is right there, and wrong for dialogue-gated.

So the mix is built dialogue-anchored, and for a non-dialogue-gated standard a single
**measured** programme trim is then applied to everything equally — preserving the
dialogue-to-bed relationship — and the result is measured again. `program_trim_db` and
both measurements are reported. This is a declared step with its own number, not a quiet
correction: `program_normalize=false` turns it off, and it never runs on a dialogue-gated
standard.

## Nothing else is silently fixed

If the mix overshoots true peak, that is reported with its remedy. Pulling the whole mix
down to fix it would move the integrated loudness off the target it just hit, and
reporting the pre-trim number would then be a lie. The caller decides which constraint
gives.

## Everything lands in scratch

Premixes are derived audio and go to an explicit output path or a temp directory —
never beside the source stems.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import delivery_targets

try:
    import numpy as _np
except ImportError:  # pragma: no cover - guarded by capabilities()
    _np = None  # type: ignore

#: Every entry point that touches an array calls `_require()` first, so the mixing
#: arithmetic treats `_np` as present. See tests/test_optional_dependency_guards.py.
_OPTIONAL_DEPENDENCY_CONTRACT = (
    "numpy: every mixing entry point calls _require() first; internals assume it is present"
)

SAMPLE_RATE = 48000
CHANNELS = 2

#: How far under dialogue a music bed sits by default, in LU. Named rather than buried:
#: it is the single number most likely to be argued with, and a caller who disagrees
#: should be able to find and change it.
DEFAULT_BED_OFFSET_LU = -12.0

#: Ducking shape. Attack is short enough that the bed is already down under the first
#: syllable; release is long enough that it does not pump between words.
DEFAULT_DUCK_DB = -6.0
DEFAULT_ATTACK_S = 0.15
DEFAULT_RELEASE_S = 0.40
#: Gaps shorter than this between speech regions are bridged rather than ducked out of
#: and back into — a bed that lifts for half a second between sentences is a distraction.
DEFAULT_HOLD_S = 0.35

#: Silence detection on the dialogue stem. -40 dB is below room tone on a normalised
#: stem but above the noise floor of a clean recording.
SILENCE_NOISE_DB = -40.0
SILENCE_MIN_S = 0.30

DEFAULT_STANDARD = "web"


class MixPlanError(Exception):
    """Bad inputs or a missing tool. A mix that misses its target is a result."""


def _require() -> None:
    if _np is None:
        raise MixPlanError("numpy is required for mixing (pip install numpy)")
    if not shutil.which("ffmpeg"):
        raise MixPlanError("ffmpeg is required for loudness measurement and rendering")


# ── measurement ──────────────────────────────────────────────────────────────

# These patterns mirror `media_analysis._parse_loudness`. The duplication is deliberate
# — this module stays importable without pulling in the analysis engine — and a test
# asserts both parsers agree on the same ffmpeg output, so the copy cannot drift.
_INTEGRATED_RE = r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS"
_LRA_RE = r"LRA:\s*(-?\d+(?:\.\d+)?)\s*LU"
_PEAK_RE = r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS"


def parse_loudness(stderr: str) -> Dict[str, Optional[float]]:
    """Pull the ebur128 summary out of ffmpeg's stderr.

    Scoped to the text after `Summary:`, with ebur128's per-frame progress lines removed.
    Both steps are needed and neither is enough alone: the progress line carries its own
    `I:` and `LRA:`, so a plain last-match-wins parse is right only because the summary
    happens to print last, and scoping to the summary still swallows any progress line
    that prints after it. Progress lines are identified by the `TARGET:` field, which
    appears on every one of them and on nothing in the summary block.
    """
    marker = stderr.rfind("Summary:")
    scope = "\n".join(
        line for line in (stderr[marker:] if marker >= 0 else stderr).splitlines()
        if "TARGET:" not in line
    )

    def latest(pattern: str) -> Optional[float]:
        matches = re.findall(pattern, scope)
        return float(matches[-1]) if matches else None

    return {
        "integrated_lufs": latest(_INTEGRATED_RE),
        "loudness_range_lu": latest(_LRA_RE),
        "true_peak_dbtp": latest(_PEAK_RE),
    }


def _run(args: Sequence[str], *, stdin_bytes: Optional[bytes] = None) -> Tuple[int, bytes, str]:
    process = subprocess.run(
        list(args), input=stdin_bytes, capture_output=True, check=False, timeout=600
    )
    return process.returncode, process.stdout, process.stderr.decode("utf-8", "replace")


def measure(path: str) -> Dict[str, Any]:
    """Integrated LUFS, loudness range, and true peak for one file."""
    _require()
    if not os.path.isfile(path):
        raise MixPlanError(f"file not found: {path}")
    code, _, stderr = _run(
        ["ffmpeg", "-v", "info", "-nostats", "-i", path,
         "-filter_complex", "ebur128=peak=true", "-f", "null", "-"]
    )
    parsed = parse_loudness(stderr)
    if parsed["integrated_lufs"] is None:
        raise MixPlanError(
            f"could not measure loudness of {os.path.basename(path)} "
            f"(no audio stream, or ffmpeg produced no ebur128 summary; exit {code})"
        )
    return {"path": path, **parsed}


def _speech_regions(path: str, duration: float) -> List[Dict[str, float]]:
    """Regions where the dialogue stem is NOT silent — the complement of silencedetect."""
    _, _, stderr = _run(
        ["ffmpeg", "-v", "info", "-nostats", "-i", path, "-af",
         f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_S}", "-f", "null", "-"]
    )
    starts = [float(value) for value in re.findall(r"silence_start:\s*(-?[0-9.]+)", stderr)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", stderr)]

    silences: List[Tuple[float, float]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else duration
        silences.append((max(0.0, start), min(duration, end)))

    regions: List[Dict[str, float]] = []
    cursor = 0.0
    for start, end in silences:
        if start > cursor:
            regions.append({"start": round(cursor, 3), "end": round(start, 3)})
        cursor = max(cursor, end)
    if cursor < duration:
        regions.append({"start": round(cursor, 3), "end": round(duration, 3)})
    return [region for region in regions if region["end"] > region["start"]]


def _merge_regions(regions: Sequence[Dict[str, float]], hold: float) -> List[Dict[str, float]]:
    """Bridge gaps shorter than `hold` so the bed does not pump between sentences."""
    merged: List[Dict[str, float]] = []
    for region in sorted(regions, key=lambda item: item["start"]):
        if merged and region["start"] - merged[-1]["end"] <= hold:
            merged[-1]["end"] = max(merged[-1]["end"], region["end"])
        else:
            merged.append(dict(region))
    return [{"start": round(r["start"], 3), "end": round(r["end"], 3)} for r in merged]


def probe_duration(path: str) -> float:
    """Duration in seconds via ffprobe, or 0.0 when it cannot be read."""
    if not shutil.which("ffprobe"):
        raise MixPlanError("ffprobe is required to read stem durations")
    code, stdout, _ = _run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path]
    )
    try:
        return float(stdout.decode("utf-8", "replace").strip())
    except (TypeError, ValueError):
        return 0.0


# ── planning ─────────────────────────────────────────────────────────────────


def _standard(name: Any) -> Any:
    key = delivery_targets.normalize_loudness_standard(name or DEFAULT_STANDARD)
    if key is None:
        raise MixPlanError(
            f"unknown loudness standard '{name}'. Known: "
            f"{', '.join(sorted(delivery_targets.LOUDNESS_STANDARDS))}"
        )
    return delivery_targets.LOUDNESS_STANDARDS[key]


def plan(
    dialogue: Sequence[str],
    *,
    music: Optional[Sequence[str]] = None,
    sfx: Optional[Sequence[str]] = None,
    standard: str = DEFAULT_STANDARD,
    target_lufs: Optional[float] = None,
    bed_offset_lu: float = DEFAULT_BED_OFFSET_LU,
    duck_db: float = DEFAULT_DUCK_DB,
    attack_s: float = DEFAULT_ATTACK_S,
    release_s: float = DEFAULT_RELEASE_S,
    hold_s: float = DEFAULT_HOLD_S,
) -> Dict[str, Any]:
    """Measure the stems and derive the gains. Renders nothing."""
    _require()
    dialogue_paths = [str(path) for path in (dialogue or [])]
    music_paths = [str(path) for path in (music or [])]
    sfx_paths = [str(path) for path in (sfx or [])]
    if not dialogue_paths:
        raise MixPlanError("supply at least one dialogue stem — the mix is anchored to it")
    for path in dialogue_paths + music_paths + sfx_paths:
        if not os.path.isfile(path):
            raise MixPlanError(f"file not found: {path}")

    spec = _standard(standard)
    target = float(target_lufs) if target_lufs is not None else float(spec.integrated)

    dialogue_measurements = [measure(path) for path in dialogue_paths]
    music_measurements = [measure(path) for path in music_paths]
    sfx_measurements = [measure(path) for path in sfx_paths]

    # The anchor is the loudest dialogue stem: normalising to the quietest would push
    # the others past the target, and normalising to an average leaves both wrong.
    anchor = max(dialogue_measurements, key=lambda item: item["integrated_lufs"])
    dialogue_gain_db = round(target - float(anchor["integrated_lufs"]), 2)

    bed_target = target + float(bed_offset_lu)
    music_gains = [
        {
            "path": item["path"],
            "measured_lufs": item["integrated_lufs"],
            "gain_db": round(bed_target - float(item["integrated_lufs"]), 2),
        }
        for item in music_measurements
    ]
    # Effects sit with dialogue rather than under it — they are events, not a bed.
    sfx_gains = [
        {
            "path": item["path"],
            "measured_lufs": item["integrated_lufs"],
            "gain_db": round(target - float(item["integrated_lufs"]), 2),
        }
        for item in sfx_measurements
    ]

    duration = max(probe_duration(path) for path in dialogue_paths + music_paths + sfx_paths)
    speech: List[Dict[str, float]] = []
    for path in dialogue_paths:
        speech.extend(_speech_regions(path, probe_duration(path)))
    duck_windows = _merge_regions(speech, hold_s)

    ducked_seconds = sum(window["end"] - window["start"] for window in duck_windows)
    return {
        "dry_run": True,
        "standard": {
            "id": spec.id,
            "label": spec.label,
            "integrated_lufs": spec.integrated,
            "tolerance_lu": spec.tolerance_lu,
            "true_peak_max_dbtp": spec.true_peak_max_dbtp,
            "dialogue_gated": bool(getattr(spec, "dialogue_gated", False)),
            "source": spec.source,
        },
        "target_lufs": target,
        "dialogue": {
            "stems": dialogue_measurements,
            "anchor_path": anchor["path"],
            "anchor_measured_lufs": anchor["integrated_lufs"],
            "gain_db": dialogue_gain_db,
            "note": (
                "Measured on the isolated dialogue stem, which is the closest thing to a "
                "dialogue-gated measurement available here."
            ),
        },
        "music": {
            "stems": music_gains,
            "bed_offset_lu": float(bed_offset_lu),
            "bed_target_lufs": round(bed_target, 2),
        },
        "sfx": {"stems": sfx_gains},
        "ducking": {
            "duck_db": float(duck_db),
            "attack_s": float(attack_s),
            "release_s": float(release_s),
            "hold_s": float(hold_s),
            "windows": duck_windows,
            "window_count": len(duck_windows),
            "ducked_seconds": round(ducked_seconds, 2),
            "ducked_fraction": round(ducked_seconds / duration, 4) if duration else 0.0,
            "note": (
                "Derived from silence detection on the dialogue stem, so the bed follows "
                "the words rather than a hand-placed envelope."
            ),
        },
        "duration_seconds": round(duration, 3),
        "renders": False,
        "next": (
            "Re-run with dry_run=false to render the premix and report the achieved "
            "loudness. Nothing is written until then."
        ),
    }


# ── rendering ────────────────────────────────────────────────────────────────


def _decode(path: str) -> "Any":
    """Decode to float32 interleaved stereo at SAMPLE_RATE. Shape (n, CHANNELS)."""
    code, raw, stderr = _run(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0",
         "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE),
         "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"]
    )
    if code != 0 or not raw:
        raise MixPlanError(
            f"could not decode audio from {os.path.basename(path)}: {stderr[-300:]}"
        )
    samples = _np.frombuffer(raw, dtype=_np.float32).astype(_np.float64)
    usable = (samples.size // CHANNELS) * CHANNELS
    return samples[:usable].reshape(-1, CHANNELS)


def _pad_to(block: "Any", length: int) -> "Any":
    if block.shape[0] >= length:
        return block[:length]
    return _np.vstack([block, _np.zeros((length - block.shape[0], CHANNELS))])


def duck_envelope(
    length: int,
    windows: Sequence[Dict[str, float]],
    *,
    duck_db: float,
    attack_s: float,
    release_s: float,
) -> "Any":
    """A gain envelope that is 1.0 outside the windows and `duck_db` inside them.

    Ramps are linear in gain across the attack and release, placed so the bed is already
    down at the window's start rather than beginning to move there.
    """
    _require()
    envelope = _np.ones(length, dtype=_np.float64)
    floor = float(10.0 ** (float(duck_db) / 20.0))
    attack = max(1, int(round(float(attack_s) * SAMPLE_RATE)))
    release = max(1, int(round(float(release_s) * SAMPLE_RATE)))

    for window in windows:
        start = int(round(float(window["start"]) * SAMPLE_RATE))
        end = int(round(float(window["end"]) * SAMPLE_RATE))
        start, end = max(0, start), min(length, end)
        if end <= start:
            continue
        ramp_in_from = max(0, start - attack)
        if start > ramp_in_from:
            envelope[ramp_in_from:start] = _np.minimum(
                envelope[ramp_in_from:start],
                _np.linspace(1.0, floor, start - ramp_in_from),
            )
        envelope[start:end] = _np.minimum(envelope[start:end], floor)
        ramp_out_to = min(length, end + release)
        if ramp_out_to > end:
            envelope[end:ramp_out_to] = _np.minimum(
                envelope[end:ramp_out_to],
                _np.linspace(floor, 1.0, ramp_out_to - end),
            )
    return envelope


def _write_wav(path: str, mix: "Any") -> str:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    payload = _np.clip(mix, -1.0, 1.0).astype(_np.float32).tobytes()
    code, _, stderr = _run(
        ["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SAMPLE_RATE),
         "-ac", str(CHANNELS), "-i", "pipe:0", "-c:a", "pcm_s24le", path],
        stdin_bytes=payload,
    )
    if code != 0:
        raise MixPlanError(f"could not write premix: {stderr[-300:]}")
    return path


def render(
    dialogue: Sequence[str],
    *,
    music: Optional[Sequence[str]] = None,
    sfx: Optional[Sequence[str]] = None,
    output_path: Optional[str] = None,
    standard: str = DEFAULT_STANDARD,
    target_lufs: Optional[float] = None,
    bed_offset_lu: float = DEFAULT_BED_OFFSET_LU,
    duck_db: float = DEFAULT_DUCK_DB,
    attack_s: float = DEFAULT_ATTACK_S,
    release_s: float = DEFAULT_RELEASE_S,
    hold_s: float = DEFAULT_HOLD_S,
    program_normalize: Optional[bool] = None,
) -> Dict[str, Any]:
    """Render the planned premix and report the loudness it actually achieved."""
    plan_result = plan(
        dialogue, music=music, sfx=sfx, standard=standard, target_lufs=target_lufs,
        bed_offset_lu=bed_offset_lu, duck_db=duck_db, attack_s=attack_s,
        release_s=release_s, hold_s=hold_s,
    )

    target = plan_result["target_lufs"]
    dialogue_blocks = [_decode(item["path"]) for item in plan_result["dialogue"]["stems"]]
    music_blocks = [(_decode(item["path"]), item["gain_db"]) for item in plan_result["music"]["stems"]]
    sfx_blocks = [(_decode(item["path"]), item["gain_db"]) for item in plan_result["sfx"]["stems"]]

    length = max(
        [block.shape[0] for block in dialogue_blocks]
        + [block.shape[0] for block, _ in music_blocks]
        + [block.shape[0] for block, _ in sfx_blocks]
    )
    mix = _np.zeros((length, CHANNELS), dtype=_np.float64)

    dialogue_gain = 10.0 ** (plan_result["dialogue"]["gain_db"] / 20.0)
    for block in dialogue_blocks:
        mix += _pad_to(block, length) * dialogue_gain
    for block, gain_db in sfx_blocks:
        mix += _pad_to(block, length) * (10.0 ** (gain_db / 20.0))

    envelope = duck_envelope(
        length, plan_result["ducking"]["windows"],
        duck_db=duck_db, attack_s=attack_s, release_s=release_s,
    )
    for block, gain_db in music_blocks:
        mix += _pad_to(block, length) * (10.0 ** (gain_db / 20.0)) * envelope[:, None]

    peak_before_clip = float(_np.abs(mix).max()) if mix.size else 0.0
    clipped_samples = int((_np.abs(mix) > 1.0).sum())

    destination = output_path or os.path.join(
        tempfile.mkdtemp(prefix="mix_plan_"), "premix.wav"
    )
    _write_wav(destination, mix)
    achieved = measure(destination)

    spec = plan_result["standard"]
    # Dialogue-anchored mixing puts dialogue at target; adding a bed puts the PROGRAMME
    # above it. For a full-programme standard that is a miss, so trim once — measured,
    # applied to everything equally so the dialogue-to-bed relationship survives — and
    # measure again. Never on a dialogue-gated standard, where dialogue is the thing
    # being graded.
    normalize = (
        (not spec["dialogue_gated"]) if program_normalize is None else bool(program_normalize)
    )
    dialogue_anchored = dict(achieved)
    program_trim_db = 0.0
    if normalize and not spec["dialogue_gated"] and achieved["integrated_lufs"] is not None:
        program_trim_db = round(target - float(achieved["integrated_lufs"]), 2)
        if abs(program_trim_db) >= 0.1:
            mix = mix * (10.0 ** (program_trim_db / 20.0))
            peak_before_clip = float(_np.abs(mix).max()) if mix.size else 0.0
            clipped_samples = int((_np.abs(mix) > 1.0).sum())
            _write_wav(destination, mix)
            achieved = measure(destination)
        else:
            program_trim_db = 0.0

    flags = _flags(achieved, target, spec, clipped_samples, peak_before_clip)
    return {
        **plan_result,
        "dry_run": False,
        "renders": True,
        "premix_path": destination,
        "program_normalize": {
            "applied": bool(program_trim_db),
            "trim_db": program_trim_db,
            "reason": (
                "dialogue-gated standard: dialogue stays the anchor, the programme is not trimmed"
                if spec["dialogue_gated"] else
                "full-programme standard: the whole mix was trimmed equally so the "
                "programme hits the target and the dialogue-to-bed relationship survives"
                if program_trim_db else
                "no trim needed" if normalize else "disabled by program_normalize=false"
            ),
            "dialogue_anchored_lufs": dialogue_anchored["integrated_lufs"],
        },
        "achieved": {
            "integrated_lufs": achieved["integrated_lufs"],
            "true_peak_dbtp": achieved["true_peak_dbtp"],
            "loudness_range_lu": achieved["loudness_range_lu"],
            "delta_from_target_lu": (
                round(float(achieved["integrated_lufs"]) - target, 2)
                if achieved["integrated_lufs"] is not None else None
            ),
            "peak_before_clip": round(peak_before_clip, 4),
            "clipped_samples": clipped_samples,
        },
        "flags": flags,
        "on_target": not flags,
        "next": (
            "Measured on the rendered premix, not derived from the plan. "
            + ("Nothing to correct." if not flags else "Read the remedies before delivering.")
        ),
    }


def _flags(
    achieved: Dict[str, Any],
    target: float,
    spec: Dict[str, Any],
    clipped_samples: int,
    peak_before_clip: float,
) -> List[Dict[str, str]]:
    """Every flag carries a remedy. Nothing here is corrected automatically."""
    flags: List[Dict[str, str]] = []

    def flag(flag_id: str, detail: str, remedy: str) -> None:
        flags.append({"id": flag_id, "detail": detail, "remedy": remedy})

    integrated = achieved.get("integrated_lufs")
    tolerance = float(spec.get("tolerance_lu") or 0.0)
    if integrated is None:
        flag("unmeasurable", "the rendered premix produced no ebur128 summary",
             "check the stems carry audio; do not deliver on the plan's arithmetic alone")
    elif abs(float(integrated) - target) > tolerance:
        flag(
            "loudness_off_target",
            f"achieved {integrated} LUFS against a target of {target} "
            f"+/-{tolerance} LU",
            "a stem shorter than the programme drags the integrated figure; check stem "
            "lengths, or set target_lufs deliberately",
        )

    peak_max = spec.get("true_peak_max_dbtp")
    true_peak = achieved.get("true_peak_dbtp")
    if peak_max is not None and true_peak is not None and float(true_peak) > float(peak_max):
        flag(
            "true_peak_over",
            f"true peak {true_peak} dBTP exceeds {peak_max} dBTP for {spec.get('id')}",
            "lower the bed or the effects rather than the whole mix — trimming the mix "
            "moves the integrated loudness off the target it just hit",
        )
    if clipped_samples:
        flag(
            "clipped",
            f"{clipped_samples} samples exceeded full scale before the write "
            f"(peak {round(peak_before_clip, 3)})",
            "reduce the loudest stem's gain; the premix was written clipped, not "
            "silently normalised",
        )
    return flags


def capabilities() -> Dict[str, Any]:
    return {
        "numpy_available": _np is not None,
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "ffprobe_available": shutil.which("ffprobe") is not None,
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "standards": sorted(delivery_targets.LOUDNESS_STANDARDS),
        "defaults": {
            "standard": DEFAULT_STANDARD,
            "bed_offset_lu": DEFAULT_BED_OFFSET_LU,
            "duck_db": DEFAULT_DUCK_DB,
            "attack_s": DEFAULT_ATTACK_S,
            "release_s": DEFAULT_RELEASE_S,
            "hold_s": DEFAULT_HOLD_S,
        },
        "note": (
            "Rough mix only: gain staging, a music bed, and dialogue-following ducking, "
            "measured after rendering. It does not EQ, compress, de-ess, or limit, and "
            "it never corrects a flagged result automatically."
        ),
    }
