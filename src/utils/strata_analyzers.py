"""Perception-strata analyzers — local track writers (no cloud, no Resolve).

Each analyzer reads a clip's media file (via ffmpeg) and/or its existing
strata rows, computes timecoded tracks, and writes them through
src/utils/strata. All are optional-capability: they self-describe what they
need (ffmpeg, numpy, a transcript) and refuse honestly instead of degrading
silently.

Analyzers here are deliberately dependency-light: numpy + ffmpeg only.
Nothing imports librosa/mediapipe — heavier analyzers (face/blink) live
behind their own capability gate in strata_faces.py.

Compute functions are pure (arrays in, tracks out) so they are unit-testable
on synthetic signals; the run_* wrappers handle clip resolution, decoding,
and DB writes.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.utils import strata, timeline_brain_db

logger = logging.getLogger("resolve-mcp.strata-analyzers")

try:  # numpy is present in most installs but is not a hard requirement.
    import numpy as _np
except ImportError:  # pragma: no cover - exercised on minimal installs
    _np = None

PROSODY_SOURCE = "prosody_v1"
PROSODY_VERSION = "1.0.0"
BEATGRID_SOURCE = "beatgrid_v1"
BEATGRID_VERSION = "1.0.0"
MOTION_SOURCE = "motion_v1"
MOTION_VERSION = "1.0.0"

AUDIO_SAMPLE_RATE = 16000
FRAME_SECONDS = 0.040   # analysis window
HOP_SECONDS = 0.010     # 100 Hz curve rate
CURVE_RATE = 1.0 / HOP_SECONDS

# Word-gap thresholds (seconds). A gap shorter than PAUSE_MIN is articulation,
# not a pause; longer than PAUSE_MAX it is silence/room, not a beat the editor
# cuts on — still recorded, capped payload marks it.
PAUSE_MIN_SECONDS = 0.35
HESITATION_WORDS = {"uh", "um", "er", "erm", "uhm", "hmm", "mm", "mhm", "ah", "eh"}

PITCH_MIN_HZ = 60.0
PITCH_MAX_HZ = 400.0

MOTION_CURVE_RATE = 10.0  # Hz


def capabilities() -> Dict[str, Any]:
    """What the local analyzers can run on this machine."""
    ffmpeg = shutil.which("ffmpeg")
    return {
        "ffmpeg": {"available": bool(ffmpeg), "path": ffmpeg},
        "numpy": {"available": _np is not None},
        "analyzers": {
            "prosody": {
                "available": bool(ffmpeg) and _np is not None,
                "requires": ["ffmpeg", "numpy"],
                "writes": {
                    "curves": ["pitch", "vocal_energy", "speech_rate"],
                    "events": ["pause", "breath", "hesitation"],
                },
            },
            "beat_grid": {
                "available": bool(ffmpeg) and _np is not None,
                "requires": ["ffmpeg", "numpy"],
                "writes": {"events": ["beat", "downbeat"]},
            },
            "motion_energy": {
                "available": bool(ffmpeg),
                "requires": ["ffmpeg"],
                "writes": {"curves": ["motion_energy"]},
            },
        },
    }


def _require(*needs: str) -> Optional[Dict[str, Any]]:
    if "numpy" in needs and _np is None:
        return {"success": False, "error": "numpy is required for this analyzer", "missing": "numpy"}
    if "ffmpeg" in needs and not shutil.which("ffmpeg"):
        return {"success": False, "error": "ffmpeg not found on PATH", "missing": "ffmpeg"}
    return None


# ── clip resolution ──────────────────────────────────────────────────────────


def _clip_row(project_root: str, clip_ref: Any) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Resolve a clip ref to {clip_uuid, file_path, duration_seconds, fps}."""
    from src.utils import analysis_store

    conn = timeline_brain_db.connect(project_root)
    clip_uuid = analysis_store.resolve_clip_uuid(conn, clip_ref)
    if not clip_uuid:
        return None, {"success": False, "error": f"Unknown clip ref: {clip_ref!r}"}
    row = conn.execute("SELECT * FROM clips WHERE clip_uuid = ?", (clip_uuid,)).fetchone()
    if row is None:
        return None, {"success": False, "error": f"No clips row for {clip_uuid}"}
    file_path = row["file_path"]
    if not file_path or not os.path.isfile(file_path):
        return None, {
            "success": False,
            "error": f"Media file not accessible for clip {row['clip_name']!r}: {file_path!r}",
            "clip_uuid": clip_uuid,
        }
    return (
        {
            "clip_uuid": clip_uuid,
            "clip_name": row["clip_name"],
            "file_path": file_path,
            "duration_seconds": row["duration_seconds"],
            "fps": row["fps"],
        },
        None,
    )


# ── decoding ─────────────────────────────────────────────────────────────────


def decode_audio(path: str, sample_rate: int = AUDIO_SAMPLE_RATE, timeout: int = 600) -> "Any":
    """Decode a media file's audio to mono float32 PCM via ffmpeg."""
    cmd = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-v", "error",
        "-i", path,
        "-map", "0:a:0",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-f", "f32le",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg audio decode failed: {proc.stderr.decode('utf-8', 'replace')[:500]}")
    return _np.frombuffer(proc.stdout, dtype=_np.float32)


# ── prosody: pure compute ────────────────────────────────────────────────────


def _frame_signal(samples: "Any", sample_rate: int) -> Tuple["Any", int, int]:
    frame_len = int(sample_rate * FRAME_SECONDS)
    hop_len = int(sample_rate * HOP_SECONDS)
    if len(samples) < frame_len:
        return _np.empty((0, frame_len), dtype=_np.float32), frame_len, hop_len
    n_frames = 1 + (len(samples) - frame_len) // hop_len
    idx = _np.arange(frame_len)[None, :] + hop_len * _np.arange(n_frames)[:, None]
    return samples[idx], frame_len, hop_len


def compute_energy_curve(samples: "Any", sample_rate: int = AUDIO_SAMPLE_RATE) -> List[float]:
    """Per-frame RMS, normalized to the clip's 95th percentile (0..~1)."""
    frames, _, _ = _frame_signal(samples, sample_rate)
    if frames.shape[0] == 0:
        return []
    rms = _np.sqrt(_np.mean(frames.astype(_np.float64) ** 2, axis=1))
    scale = float(_np.percentile(rms, 95)) or 1.0
    if scale <= 0:
        scale = 1.0
    return [float(v) for v in _np.clip(rms / scale, 0.0, 4.0)]


def compute_pitch_curve(
    samples: "Any",
    sample_rate: int = AUDIO_SAMPLE_RATE,
    energy: Optional[Sequence[float]] = None,
    voiced_threshold: float = 0.10,
) -> List[float]:
    """Autocorrelation pitch (Hz) per frame; NaN where unvoiced/silent.

    Deliberately simple (no pYIN): good enough to carry contour direction,
    range, and tremor for take comparison — not for music transcription.
    """
    frames, frame_len, _ = _frame_signal(samples, sample_rate)
    if frames.shape[0] == 0:
        return []
    if energy is None:
        energy = compute_energy_curve(samples, sample_rate)
    lag_min = int(sample_rate / PITCH_MAX_HZ)
    lag_max = min(int(sample_rate / PITCH_MIN_HZ), frame_len - 1)
    out: List[float] = []
    hann = _np.hanning(frame_len)
    for i in range(frames.shape[0]):
        if i >= len(energy) or energy[i] < voiced_threshold:
            out.append(float("nan"))
            continue
        frame = frames[i].astype(_np.float64) * hann
        frame = frame - frame.mean()
        # FFT autocorrelation
        spec = _np.fft.rfft(frame, n=2 * frame_len)
        ac = _np.fft.irfft(spec * _np.conj(spec))[:frame_len]
        if ac[0] <= 0:
            out.append(float("nan"))
            continue
        ac = ac / ac[0]
        window = ac[lag_min:lag_max]
        if window.size == 0:
            out.append(float("nan"))
            continue
        peak = int(_np.argmax(window)) + lag_min
        # Voicing gate: the autocorrelation peak must be strong.
        if ac[peak] < 0.30:
            out.append(float("nan"))
            continue
        out.append(float(sample_rate / peak))
    return out


def compute_speech_rate_curve(
    words: Sequence[Dict[str, Any]],
    duration_seconds: float,
    window_seconds: float = 2.0,
    rate_hz: float = 10.0,
) -> List[float]:
    """Words/second in a centered sliding window, sampled at rate_hz."""
    n = max(1, int(math.ceil(duration_seconds * rate_hz)))
    starts = [w.get("start_seconds") for w in words if isinstance(w.get("start_seconds"), (int, float))]
    out = []
    half = window_seconds / 2.0
    for i in range(n):
        t = i / rate_hz
        lo, hi = t - half, t + half
        count = sum(1 for s in starts if lo <= s < hi)
        out.append(count / window_seconds)
    return out


def detect_pauses(
    words: Sequence[Dict[str, Any]],
    min_gap_seconds: float = PAUSE_MIN_SECONDS,
) -> List[Dict[str, Any]]:
    """Word-gap pauses inside the spoken region. Gap = prev.end → next.start."""
    timed = [
        w for w in words
        if isinstance(w.get("start_seconds"), (int, float)) and isinstance(w.get("end_seconds"), (int, float))
    ]
    timed.sort(key=lambda w: (w["start_seconds"], w["end_seconds"]))
    pauses = []
    for prev, nxt in zip(timed, timed[1:]):
        gap_start = float(prev["end_seconds"])
        gap = float(nxt["start_seconds"]) - gap_start
        if gap >= min_gap_seconds:
            pauses.append(
                {
                    "time_seconds": gap_start,
                    "duration_seconds": gap,
                    "payload": {
                        "before_word": prev.get("word"),
                        "after_word": nxt.get("word"),
                    },
                }
            )
    return pauses


def detect_hesitations(words: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for w in words:
        token = str(w.get("word") or "").strip().lower().strip(".,!?;:")
        if token in HESITATION_WORDS and isinstance(w.get("start_seconds"), (int, float)):
            end = w.get("end_seconds")
            out.append(
                {
                    "time_seconds": float(w["start_seconds"]),
                    "duration_seconds": (float(end) - float(w["start_seconds"])) if isinstance(end, (int, float)) else None,
                    "payload": {"word": w.get("word")},
                }
            )
    return out


def detect_breaths(
    energy: Sequence[float],
    pauses: Sequence[Dict[str, Any]],
    curve_rate: float = CURVE_RATE,
) -> List[Dict[str, Any]]:
    """Breath candidates: a sub-speech energy bump inside a word gap.

    Honest heuristic (flagged low-confidence): within each pause, look for a
    local energy peak that clears the pause's own floor but stays well under
    speech level. Catches on-mic inhales; misses quiet ones.
    """
    if not len(energy):
        return []
    arr = _np.asarray(energy, dtype=_np.float64) if _np is not None else None
    breaths: List[Dict[str, Any]] = []
    for pause in pauses:
        start = float(pause["time_seconds"])
        dur = float(pause.get("duration_seconds") or 0.0)
        lo = int(start * curve_rate)
        hi = min(int((start + dur) * curve_rate), len(energy))
        if hi - lo < 3:
            continue
        seg = arr[lo:hi] if arr is not None else energy[lo:hi]
        floor = float(_np.percentile(seg, 20)) if arr is not None else min(seg)
        peak_idx = int(_np.argmax(seg)) if arr is not None else max(range(len(seg)), key=lambda i: seg[i])
        peak = float(seg[peak_idx])
        # Bump: clearly above the gap floor, clearly below speech (~1.0 scale).
        if peak >= floor + 0.05 and peak <= 0.5:
            breaths.append(
                {
                    "time_seconds": (lo + peak_idx) / curve_rate,
                    "duration_seconds": None,
                    "payload": {"confidence": "low", "peak_energy": round(peak, 4)},
                }
            )
    return breaths


# ── prosody: runner ──────────────────────────────────────────────────────────


def run_prosody(project_root: str, clip_ref: Any) -> Dict[str, Any]:
    """Compute + persist prosody strata for one clip.

    Writes curves pitch / vocal_energy / speech_rate and events pause /
    breath / hesitation. Requires the clip's media file, ffmpeg, numpy, and
    (for word-derived tracks) transcript_words rows.
    """
    missing = _require("ffmpeg", "numpy")
    if missing:
        return missing
    clip, err = _clip_row(project_root, clip_ref)
    if err:
        return err
    conn = timeline_brain_db.connect(project_root)
    words = strata.read_words(conn, clip["clip_uuid"])

    try:
        samples = decode_audio(clip["file_path"])
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        return {"success": False, "error": str(exc), "clip_uuid": clip["clip_uuid"]}
    if samples.size == 0:
        return {"success": False, "error": "clip has no decodable audio", "clip_uuid": clip["clip_uuid"]}

    duration = clip["duration_seconds"] or (samples.size / AUDIO_SAMPLE_RATE)
    energy = compute_energy_curve(samples)
    pitch = compute_pitch_curve(samples, energy=energy)
    pauses = detect_pauses(words)
    hesitations = detect_hesitations(words)
    breaths = detect_breaths(energy, pauses)
    speech_rate = compute_speech_rate_curve(words, float(duration)) if words else []

    with timeline_brain_db.transaction(project_root) as txn:
        strata.write_curve(
            txn, clip["clip_uuid"], "vocal_energy", energy,
            sample_rate=CURVE_RATE, source=PROSODY_SOURCE, analyzer_version=PROSODY_VERSION,
        )
        strata.write_curve(
            txn, clip["clip_uuid"], "pitch", pitch,
            sample_rate=CURVE_RATE, source=PROSODY_SOURCE, analyzer_version=PROSODY_VERSION,
        )
        if speech_rate:
            strata.write_curve(
                txn, clip["clip_uuid"], "speech_rate", speech_rate,
                sample_rate=10.0, source=PROSODY_SOURCE, analyzer_version=PROSODY_VERSION,
            )
        strata.replace_track_events(
            txn, clip["clip_uuid"], "pause", pauses,
            source=PROSODY_SOURCE, analyzer_version=PROSODY_VERSION,
        )
        strata.replace_track_events(
            txn, clip["clip_uuid"], "hesitation", hesitations,
            source=PROSODY_SOURCE, analyzer_version=PROSODY_VERSION,
        )
        strata.replace_track_events(
            txn, clip["clip_uuid"], "breath", breaths,
            source=PROSODY_SOURCE, analyzer_version=PROSODY_VERSION,
        )

    return {
        "success": True,
        "clip_uuid": clip["clip_uuid"],
        "clip_name": clip["clip_name"],
        "curves": {
            "vocal_energy": len(energy),
            "pitch": len(pitch),
            "speech_rate": len(speech_rate),
        },
        "events": {
            "pause": len(pauses),
            "hesitation": len(hesitations),
            "breath": len(breaths),
        },
        "had_words": bool(words),
        "analyzer_version": PROSODY_VERSION,
    }


# ── musical beat grid ────────────────────────────────────────────────────────


def compute_beat_grid(
    samples: "Any",
    sample_rate: int = AUDIO_SAMPLE_RATE,
    tempo_min: float = 60.0,
    tempo_max: float = 200.0,
) -> Dict[str, Any]:
    """Onset-envelope beat tracking: spectral flux → tempo via autocorrelation
    → beat placement by phase search. numpy-only; no ML.

    Returns {tempo_bpm, beats: [seconds], downbeats: [seconds], confidence}.
    Downbeats are a phase-of-strongest-onset estimate every 4 beats —
    explicitly low-confidence (no meter detection).
    """
    hop = int(sample_rate * HOP_SECONDS)
    win = int(sample_rate * FRAME_SECONDS)
    frames, _, _ = _frame_signal(samples, sample_rate)
    if frames.shape[0] < 16:
        return {"tempo_bpm": None, "beats": [], "downbeats": [], "confidence": 0.0}
    hann = _np.hanning(win)
    mags = _np.abs(_np.fft.rfft(frames * hann, axis=1))
    flux = _np.diff(mags, axis=0)
    flux[flux < 0] = 0.0
    onset = flux.sum(axis=1)
    if onset.max() <= 0:
        return {"tempo_bpm": None, "beats": [], "downbeats": [], "confidence": 0.0}
    onset = onset / onset.max()
    onset = onset - onset.mean()

    # Tempo: autocorrelation peak in the plausible lag range.
    ac = _np.correlate(onset, onset, mode="full")[len(onset) - 1:]
    if ac[0] <= 0:
        return {"tempo_bpm": None, "beats": [], "downbeats": [], "confidence": 0.0}
    ac = ac / ac[0]
    frame_rate = 1.0 / HOP_SECONDS
    lag_min = max(1, int(frame_rate * 60.0 / tempo_max))
    lag_max = min(len(ac) - 1, int(frame_rate * 60.0 / tempo_min))
    if lag_max <= lag_min:
        return {"tempo_bpm": None, "beats": [], "downbeats": [], "confidence": 0.0}
    lag = int(_np.argmax(ac[lag_min:lag_max])) + lag_min
    tempo_bpm = 60.0 * frame_rate / lag
    confidence = float(ac[lag])

    # Phase: shift the beat comb to maximize onset energy under it.
    best_phase, best_score = 0, -1.0
    for phase in range(lag):
        score = float(onset[phase::lag].sum())
        if score > best_score:
            best_score, best_phase = score, phase
    beat_frames = list(range(best_phase, len(onset), lag))
    beats = [(f + 1) * HOP_SECONDS for f in beat_frames]  # +1: flux is a diff

    # Downbeat guess: strongest onset among the first 4 beats sets bar phase.
    downbeats = []
    if len(beat_frames) >= 4:
        first_bar = beat_frames[:4]
        strongest = max(range(len(first_bar)), key=lambda i: onset[first_bar[i]])
        downbeats = beats[strongest::4]

    return {
        "tempo_bpm": round(tempo_bpm, 2),
        "beats": beats,
        "downbeats": downbeats,
        "confidence": round(confidence, 3),
    }


def run_beat_grid(project_root: str, clip_ref: Any) -> Dict[str, Any]:
    """Compute + persist the musical beat grid for one clip."""
    missing = _require("ffmpeg", "numpy")
    if missing:
        return missing
    clip, err = _clip_row(project_root, clip_ref)
    if err:
        return err
    try:
        samples = decode_audio(clip["file_path"])
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        return {"success": False, "error": str(exc), "clip_uuid": clip["clip_uuid"]}
    if samples.size == 0:
        return {"success": False, "error": "clip has no decodable audio", "clip_uuid": clip["clip_uuid"]}

    grid = compute_beat_grid(samples)
    beat_events = [
        {"time_seconds": t, "payload": {"tempo_bpm": grid["tempo_bpm"], "confidence": grid["confidence"]}}
        for t in grid["beats"]
    ]
    downbeat_events = [
        {"time_seconds": t, "payload": {"confidence": "low"}} for t in grid["downbeats"]
    ]
    with timeline_brain_db.transaction(project_root) as txn:
        strata.replace_track_events(
            txn, clip["clip_uuid"], "beat", beat_events,
            source=BEATGRID_SOURCE, analyzer_version=BEATGRID_VERSION,
        )
        strata.replace_track_events(
            txn, clip["clip_uuid"], "downbeat", downbeat_events,
            source=BEATGRID_SOURCE, analyzer_version=BEATGRID_VERSION,
        )
    return {
        "success": True,
        "clip_uuid": clip["clip_uuid"],
        "clip_name": clip["clip_name"],
        "tempo_bpm": grid["tempo_bpm"],
        "beat_count": len(beat_events),
        "downbeat_count": len(downbeat_events),
        "confidence": grid["confidence"],
        "analyzer_version": BEATGRID_VERSION,
    }


# ── motion energy ────────────────────────────────────────────────────────────


def run_motion_energy(project_root: str, clip_ref: Any, timeout: int = 1800) -> Dict[str, Any]:
    """Per-frame luma difference (ffmpeg signalstats YDIF) → motion_energy curve.

    Downsampled to MOTION_CURVE_RATE by mean-pooling so an hour of footage is
    ~140 KB. 0 = static, higher = more inter-frame change; normalized 0..1
    against the clip's own 98th percentile.
    """
    missing = _require("ffmpeg")
    if missing:
        return missing
    clip, err = _clip_row(project_root, clip_ref)
    if err:
        return err

    cmd = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-v", "error",
        "-i", clip["file_path"],
        "-map", "0:v:0",
        "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YDIF:file=-",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "motion analysis timed out", "clip_uuid": clip["clip_uuid"]}
    if proc.returncode != 0:
        return {
            "success": False,
            "error": f"ffmpeg signalstats failed: {proc.stderr.decode('utf-8', 'replace')[:500]}",
            "clip_uuid": clip["clip_uuid"],
        }

    times: List[float] = []
    ydifs: List[float] = []
    pending_time: Optional[float] = None
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            # e.g. "frame:12   pts:6006    pts_time:0.25025"
            for token in line.split():
                if token.startswith("pts_time:"):
                    try:
                        pending_time = float(token.split(":", 1)[1])
                    except ValueError:
                        pending_time = None
        elif line.startswith("lavfi.signalstats.YDIF=") and pending_time is not None:
            try:
                ydifs.append(float(line.split("=", 1)[1]))
                times.append(pending_time)
            except ValueError:
                pass
            pending_time = None

    if not ydifs:
        return {"success": False, "error": "no video frames analyzed", "clip_uuid": clip["clip_uuid"]}

    duration = times[-1] if times else (clip["duration_seconds"] or 0.0)
    n_out = max(1, int(math.ceil((duration or 1.0) * MOTION_CURVE_RATE)))
    buckets: List[List[float]] = [[] for _ in range(n_out)]
    for t, v in zip(times, ydifs):
        idx = min(int(t * MOTION_CURVE_RATE), n_out - 1)
        buckets[idx].append(v)
    pooled = [sum(b) / len(b) if b else float("nan") for b in buckets]
    finite = sorted(v for v in pooled if not math.isnan(v))
    if finite:
        scale = finite[min(len(finite) - 1, int(len(finite) * 0.98))] or 1.0
        if scale <= 0:
            scale = 1.0
        pooled = [min(v / scale, 4.0) if not math.isnan(v) else v for v in pooled]

    with timeline_brain_db.transaction(project_root) as txn:
        strata.write_curve(
            txn, clip["clip_uuid"], "motion_energy", pooled,
            sample_rate=MOTION_CURVE_RATE, source=MOTION_SOURCE, analyzer_version=MOTION_VERSION,
        )
    return {
        "success": True,
        "clip_uuid": clip["clip_uuid"],
        "clip_name": clip["clip_name"],
        "frames_analyzed": len(ydifs),
        "samples": len(pooled),
        "analyzer_version": MOTION_VERSION,
    }


# ── dispatcher ───────────────────────────────────────────────────────────────

ANALYZERS = {
    "prosody": run_prosody,
    "beat_grid": run_beat_grid,
    "motion_energy": run_motion_energy,
}


def run_analyzers(
    project_root: str,
    clip_ref: Any,
    analyzers: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Run one or more analyzers on a clip; per-analyzer honest results."""
    names = list(analyzers) if analyzers else list(ANALYZERS)
    unknown = [n for n in names if n not in ANALYZERS]
    if unknown:
        return {
            "success": False,
            "error": f"Unknown analyzer(s): {', '.join(unknown)}",
            "available": sorted(ANALYZERS),
        }
    results = {name: ANALYZERS[name](project_root, clip_ref) for name in names}
    return {
        "success": all(r.get("success") for r in results.values()),
        "results": results,
    }
