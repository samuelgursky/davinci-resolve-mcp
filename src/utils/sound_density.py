"""The Law of Two-and-a-Half — how much sound an audience can actually follow.

A long-standing observation in sound editing: an audience can follow roughly **two
and a half simultaneous streams** of sound before the remainder stops being
distinguishable and becomes texture. Past that point the mix is not richer, it
is just louder — the extra elements are present, paid for, mixed, and not heard.

This is the only principle in the classical set that is *fully* measurable, and
nothing in this
codebase touched sound as more than a track to mirror picture cuts onto.

## The distinction that makes or breaks it

The naive implementation counts active tracks and flags every mixed timeline in
existence, because almost every finished sequence has music under dialogue under
atmos. That tool is useless on its first run.

The real question is not how many streams are *playing*, it is how many are
**competing for the same attention**. A music bed sitting well under dialogue is
one stream plus texture. Two overlapping voices at the same level are two
streams, and adding a third is where the boundary bites.

So each active stream at each moment is classified against the loudest one:

- Within `BED_MARGIN_DB` of the loudest → **competitor**. Same attentional
  foreground.
- Further below → **bed**. Present, felt, not competing.

That is a heuristic and it is stated as one. It is also the difference between a
tool an editor uses twice and one they keep.

## On the threshold

Two-and-a-half is **an observation, not a measured constant**. It is a soft
boundary that varies with material, mix and audience. It is a parameter here,
and its provenance travels with every result — nobody should cite a number this
module returns as though it were physics.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: The two-and-a-half boundary. A soft observation, not a constant,
#: and a parameter everywhere it is used.
STREAM_LIMIT = 2.5

#: A stream this far below the loudest active one reads as underneath it rather
#: than alongside it — a bed, not a competitor. 12 dB is roughly the point where
#: an element stops pulling focus and starts supporting.
BED_MARGIN_DB = 12.0

#: Below this a stream is not audibly present at all.
AUDIBILITY_FLOOR_DB = -50.0

#: Shortest overcrowded stretch worth reporting. A momentary pile-up on a hard
#: effect is normal; a sustained one is a mix problem.
MIN_CROWDED_SECONDS = 1.5


def classify_moment(
    levels: Mapping[str, float],
    *,
    bed_margin_db: float = BED_MARGIN_DB,
    audibility_floor_db: float = AUDIBILITY_FLOOR_DB,
) -> Dict[str, Any]:
    """Split the streams audible at one moment into competitors and beds.

    `levels` maps a stream name to its level in dBFS at this moment.
    """
    audible = {k: float(v) for k, v in levels.items() if float(v) > audibility_floor_db}
    if not audible:
        return {"competitors": [], "beds": [], "silent": True, "loudest_db": None}
    loudest = max(audible.values())
    competitors, beds = [], []
    for name, level in sorted(audible.items(), key=lambda kv: -kv[1]):
        (competitors if level >= loudest - bed_margin_db else beds).append(
            {"stream": name, "level_db": round(level, 1)}
        )
    return {
        "competitors": competitors,
        "beds": beds,
        "silent": False,
        "loudest_db": round(loudest, 1),
    }


def audit(
    samples: Sequence[Mapping[str, Any]],
    *,
    stream_limit: float = STREAM_LIMIT,
    bed_margin_db: float = BED_MARGIN_DB,
    min_crowded_seconds: float = MIN_CROWDED_SECONDS,
) -> Dict[str, Any]:
    """Report attentional density over time.

    `samples`: `[{"time_seconds": float, "levels": {stream: dBFS}}, ...]`,
    ordered. Kept as plain numbers so the analysis is testable without decoding
    audio.
    """
    if not samples:
        return {"success": False, "error": "No audio samples supplied"}

    curve: List[Dict[str, Any]] = []
    for sample in samples:
        moment = classify_moment(
            sample.get("levels") or {}, bed_margin_db=bed_margin_db
        )
        curve.append({
            "time_seconds": round(float(sample.get("time_seconds") or 0.0), 3),
            "competitors": len(moment["competitors"]),
            "beds": len(moment["beds"]),
            "competing_streams": [c["stream"] for c in moment["competitors"]],
            "bed_streams": [b["stream"] for b in moment["beds"]],
        })

    # Contiguous stretches over the limit.
    crowded: List[Dict[str, Any]] = []
    run_start: Optional[float] = None
    run_peak = 0
    for index, point in enumerate(curve):
        over = point["competitors"] > stream_limit
        if over and run_start is None:
            run_start, run_peak = point["time_seconds"], point["competitors"]
        elif over:
            run_peak = max(run_peak, point["competitors"])
        elif run_start is not None:
            _close_run(crowded, run_start, point["time_seconds"], run_peak, min_crowded_seconds)
            run_start, run_peak = None, 0
    if run_start is not None:
        _close_run(crowded, run_start, curve[-1]["time_seconds"], run_peak, min_crowded_seconds)

    peak = max((p["competitors"] for p in curve), default=0)
    findings = [{
        "criterion": "rhythm",
        "scope": "scene",
        "at": run["start_seconds"],
        "summary": (
            f"{run['peak_competitors']} sounds competing for "
            f"{run['duration_seconds']}s"
        ),
        "detail": (
            f"From {run['start_seconds']}s to {run['end_seconds']}s, up to "
            f"{run['peak_competitors']} streams sit within {bed_margin_db:.0f} dB of "
            "each other, so they are all asking for the same attention. An audience "
            "follows about two and a half streams at once; past that the extra elements "
            "are mixed, paid for, and not heard. Either duck something or lose it."
        ),
    } for run in crowded]

    return {
        "success": True,
        "kind": "sound_density_audit",
        "sample_count": len(curve),
        "peak_competitors": peak,
        "stream_limit": stream_limit,
        "crowded_stretch_count": len(crowded),
        "crowded_stretches": crowded,
        "density_curve": curve,
        "findings": findings,
        "threshold_provenance": (
            f"{stream_limit} comes from a long-standing observation in sound editing "
            "about how many simultaneous streams an audience can follow. It is NOT a "
            "measured constant — it is a soft boundary that moves with material, mix and "
            "audience, and it is a parameter here. Do not cite it as physics."
        ),
        "method": (
            f"A stream within {bed_margin_db:.0f} dB of the loudest active one counts as "
            "competing; anything further under counts as a bed. That is what stops a "
            "music bed under dialogue reading as two competitors — it is one stream "
            "plus texture. Heuristic, and deliberately so."
        ),
        "note": (
            f"Peak of {peak} competing streams across {len(curve)} samples; "
            + (f"{len(crowded)} stretches over the limit." if crowded
               else "nothing sustained over the limit.")
        ),
    }


def _close_run(
    out: List[Dict[str, Any]], start: float, end: float, peak: int, minimum: float
) -> None:
    duration = end - start
    if duration >= minimum:
        out.append({
            "start_seconds": round(start, 2),
            "end_seconds": round(end, 2),
            "duration_seconds": round(duration, 2),
            "peak_competitors": peak,
        })


def measure_track_levels(
    media_paths: Mapping[str, str],
    *,
    window_seconds: float = 0.5,
    duration_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Sample per-stream levels from files via ffmpeg. Honest-refuses if absent.

    Separated from the analysis so the classification above stays testable
    without decoding audio.
    """
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        return {"success": False, "error": "ffmpeg not found on PATH — cannot measure levels"}
    try:
        import numpy as np
    except Exception:
        return {"success": False, "error": "numpy is required", "remediation": "pip install numpy"}

    rate = 8000  # plenty for an energy envelope
    per_stream: Dict[str, Any] = {}
    length = 0
    for name, path in media_paths.items():
        cmd = ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1",
               "-ar", str(rate), "-f", "f32le", "-"]
        if duration_seconds:
            cmd[4:4] = ["-t", str(duration_seconds)]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=120)
        except (subprocess.SubprocessError, OSError) as exc:
            return {"success": False, "error": f"decode failed for {name}: {exc}"}
        if proc.returncode != 0 or not proc.stdout:
            return {
                "success": False,
                "error": (proc.stderr or b"").decode("utf-8", "replace").strip()
                         or f"no audio decoded from {name}",
            }
        signal = np.frombuffer(proc.stdout, dtype="<f4")
        step = max(1, int(rate * window_seconds))
        windows = signal[: len(signal) // step * step].reshape(-1, step)
        rms = np.sqrt((windows.astype("float64") ** 2).mean(axis=1))
        with np.errstate(divide="ignore"):
            db = 20.0 * np.log10(np.maximum(rms, 1e-9))
        per_stream[name] = db
        length = max(length, len(db))

    samples = [
        {
            "time_seconds": index * window_seconds,
            "levels": {
                name: float(values[index])
                for name, values in per_stream.items()
                if index < len(values)
            },
        }
        for index in range(length)
    ]
    return {"success": True, "samples": samples, "window_seconds": window_seconds}
