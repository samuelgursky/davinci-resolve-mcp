"""Waveform silence detection for ripple-delete planning.

Resolve exposes **Clip → Audio Operations → Ripple Delete Silence** in the UI
but not via scripting. This module approximates that workflow using ffmpeg
``silencedetect`` plus the edit-engine keep-range assembler (variant timeline).

Settings map to the Resolve dialog:
  - threshold_db     → Threshold (dB)
  - min_strip_frames → Minimum strip length (frames)
  - pre_head_frames  → Pre-head (frames kept before silence)
  - post_tail_frames → Post-tail (frames kept after silence ends)

## Auto-calibrated threshold

A fixed threshold is the most common way this goes wrong: -30 dB under-detects on
quiet location audio and over-cuts a noisy room. When `threshold_db` is omitted,
`calibrate_silence_gate` measures the file's own noise floor and places the gate
just above it.

The levels come from ffmpeg `astats`, using **`RMS through dB`** (ffmpeg's
spelling of *trough* — the quietest analysis window) and **`RMS peak dB`** (the
loudest). Those two bracket the file's own dynamic range, and the gate is placed
inside that bracket.

Two metrics were measured and rejected on the way here, both worth not
rediscovering:

- `volumedetect`'s **`mean_volume`** tracks `RMS level` almost exactly — it is
  the *programme* level, not a floor. Deriving `mean_volume - 6` reads the
  content and calls it the noise floor.
- `astats`' **`Noise floor dB`** moves with how much of the slice is quiet, not
  with how quiet it is. Two fixtures sharing an identical noise bed measured
  -57.1 and -76.3 purely because one was 60% silent and the other 90%. Calibrated
  against that, the gate lands 19 dB apart on acoustically identical material.
  `RMS through` measured -56.06 and -56.12 on the same pair.

The gate is biased above the midpoint of the trough/peak bracket because
`silencedetect` compares instantaneous amplitude while `astats` reports windowed
RMS: a quiet section's samples peak some way above its own RMS, and a gate at the
exact midpoint sits near the bottom edge of the usable band.

Measuring both ends also makes the failure case detectable: when trough and peak
are not separated, no threshold distinguishes speech from room, and this says so
and falls back to the documented default instead of inventing a number that
finds nothing.
"""

from __future__ import annotations

import math
import os
import re
import shutil
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from src.utils.media_analysis import _parse_silencedetect

DEFAULT_THRESHOLD_DB = -30.0
DEFAULT_MIN_STRIP_FRAMES = 10
DEFAULT_PRE_HEAD_FRAMES = 0
DEFAULT_POST_TAIL_FRAMES = 1

#: Where in the trough→peak bracket the gate sits. Above 0.5 deliberately: see
#: the module docstring — silencedetect compares instantaneous amplitude while
#: astats reports windowed RMS, so a midpoint gate hugs the usable band's floor.
GATE_BIAS = 0.6
#: Trough and peak must differ by at least this for a gate to mean anything.
MIN_SEPARATION_DB = 12.0
#: True digital silence (trough = -inf) admits any gate; sit this far under peak.
DIGITAL_SILENCE_HEADROOM_DB = 24.0
#: Absolute band. Outside it a "calibrated" gate is not credible for dialogue.
GATE_MIN_DB = -60.0
GATE_MAX_DB = -24.0

#: ffmpeg spells the trough "RMS through"; accept a corrected spelling too so a
#: future ffmpeg fixing the typo does not silently drop us to the fallback.
_ASTATS_RMS_TROUGH_RE = re.compile(r"RMS (?:through|trough) dB:\s*(-?[0-9.]+|-?inf)", re.IGNORECASE)
_ASTATS_RMS_PEAK_RE = re.compile(r"RMS peak dB:\s*(-?[0-9.]+|-?inf)", re.IGNORECASE)


@dataclass(frozen=True)
class NoiseCalibration:
    """Outcome of a level measurement, with the reasoning kept visible.

    **`usable` False means: do not strip this item.** The measurement happened
    and produced no credible gate, so `gate_db` carries `DEFAULT_THRESHOLD_DB`
    only for reporting — detection must be skipped and the item kept whole.

    That is deliberately stronger than "fall back to the default". A fixed
    threshold applied to material it does not suit is not a degraded answer, it
    is a wrong one: a -33 dBFS programme measured against a -30 dB gate reads as
    silent end to end, and the ripple would strip the whole clip. Keeping the
    item whole and surfacing `reason` leaves a human able to set `threshold_db`
    explicitly; cutting on an unvalidated gate does not.

    `reason` is always populated when `usable` is False — a skip is never silent.
    """

    gate_db: float
    basis: str  # measured_dynamics | digital_silence | fallback_default
    usable: bool
    quiet_rms_db: Optional[float] = None
    loud_rms_db: Optional[float] = None
    separation_db: Optional[float] = None
    reason: Optional[str] = None

    def as_dict(self) -> dict:
        def finite(value: Optional[float]) -> Optional[float]:
            if value is None or not math.isfinite(value):
                return None
            return round(value, 2)

        return {
            "gate_db": round(self.gate_db, 2),
            "basis": self.basis,
            "usable": self.usable,
            "quiet_rms_db": finite(self.quiet_rms_db),
            "loud_rms_db": finite(self.loud_rms_db),
            "quiet_is_digital_silence": self.quiet_rms_db == float("-inf"),
            "separation_db": finite(self.separation_db),
            "reason": self.reason,
        }


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def frames_to_seconds(frames: float, fps: float) -> float:
    if fps <= 0:
        fps = 24.0
    return float(frames) / fps


def audio_stream_count(media_path: str) -> int:
    """Number of audio streams in the file (0 when ffprobe fails)."""
    from src.utils.media_analysis import _ffprobe

    probe = _ffprobe(media_path)
    if not probe.get("success"):
        return 0
    streams = (probe.get("raw") or {}).get("streams") or []
    return sum(1 for s in streams if s.get("codec_type") == "audio")


def build_audio_filter_args(
    media_path: str,
    start_sec: float,
    duration: float,
    audio_filter: str,
    *,
    audio_streams: int,
) -> List[str]:
    """ffmpeg argv applying one audio filter over a source slice.

    Multi-stream sources (e.g. production MXF with one mono stream per
    channel) are merged first: silencedetect's default joint mode then only
    triggers when EVERY channel is silent — matching Resolve's dialog, and
    immune to a dead scratch channel reading as all-silence. -vn skips the
    (potentially 4K) video decode entirely.

    Every analysis filter routes through here so the merge and the -vn skip stay
    identical across passes. A calibration measured on stream 0 alone while
    detection ran on the merge would place the gate against the wrong signal.
    """
    args = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-ss", str(start_sec),
        "-i", media_path,
        "-t", str(duration),
        "-vn",
    ]
    if audio_streams > 1:
        inputs = "".join(f"[0:a:{i}]" for i in range(audio_streams))
        args += ["-filter_complex", f"{inputs}amerge=inputs={audio_streams},{audio_filter}"]
    else:
        args += ["-af", audio_filter]
    args += ["-f", "null", "-"]
    return args


def build_silencedetect_args(
    media_path: str,
    start_sec: float,
    duration: float,
    *,
    threshold_db: float,
    min_duration_sec: float,
    audio_streams: int,
) -> List[str]:
    """ffmpeg argv for silence detection over a source slice."""
    return build_audio_filter_args(
        media_path,
        start_sec,
        duration,
        f"silencedetect=noise={threshold_db}dB:d={min_duration_sec}",
        audio_streams=audio_streams,
    )


def _parse_astats_levels(stderr: str) -> Tuple[Optional[float], Optional[float]]:
    """(quiet_rms_db, loud_rms_db) from an astats summary; -inf is preserved.

    -inf is a real measurement, not a parse failure: it means true digital
    silence is present. Collapsing it to None would discard that.
    """

    def grab(pattern: "re.Pattern[str]") -> Optional[float]:
        matches = pattern.findall(stderr)
        if not matches:
            return None
        raw = matches[-1].strip().lower()  # the Overall block prints last
        if raw.endswith("inf"):
            return float("-inf") if raw.startswith("-") else float("inf")
        try:
            return float(raw)
        except ValueError:
            return None

    return grab(_ASTATS_RMS_TROUGH_RE), grab(_ASTATS_RMS_PEAK_RE)


def _gate_from_levels(quiet_rms_db: Optional[float], loud_rms_db: Optional[float]) -> NoiseCalibration:
    """Pure level→gate policy, split out so it is testable without ffmpeg."""

    def fallback(reason: str) -> NoiseCalibration:
        return NoiseCalibration(
            gate_db=DEFAULT_THRESHOLD_DB,
            basis="fallback_default",
            usable=False,
            quiet_rms_db=quiet_rms_db,
            loud_rms_db=loud_rms_db,
            reason=reason,
        )

    if quiet_rms_db is None or loud_rms_db is None:
        return fallback("astats reported no usable levels for this slice")
    if not math.isfinite(loud_rms_db):
        return fallback("the slice carries no programme audio to calibrate against")

    if quiet_rms_db == float("-inf"):
        # True digital silence: any gate between -inf and the programme works.
        gate = min(max(loud_rms_db - DIGITAL_SILENCE_HEADROOM_DB, GATE_MIN_DB), GATE_MAX_DB)
        return NoiseCalibration(
            gate_db=gate,
            basis="digital_silence",
            usable=True,
            quiet_rms_db=quiet_rms_db,
            loud_rms_db=loud_rms_db,
            separation_db=float("inf"),
            reason="the slice contains true digital silence; the gate sits well under programme level",
        )

    separation = loud_rms_db - quiet_rms_db
    if separation < MIN_SEPARATION_DB:
        return NoiseCalibration(
            gate_db=DEFAULT_THRESHOLD_DB,
            basis="fallback_default",
            usable=False,
            quiet_rms_db=quiet_rms_db,
            loud_rms_db=loud_rms_db,
            separation_db=separation,
            reason=(
                f"quietest ({quiet_rms_db:.1f} dB) and loudest ({loud_rms_db:.1f} dB) windows are "
                f"only {separation:.1f} dB apart; no threshold separates speech from room here, "
                "so the default is used unchanged"
            ),
        )

    gate = quiet_rms_db + GATE_BIAS * separation
    gate = min(max(gate, GATE_MIN_DB), GATE_MAX_DB)
    return NoiseCalibration(
        gate_db=gate,
        basis="measured_dynamics",
        usable=True,
        quiet_rms_db=quiet_rms_db,
        loud_rms_db=loud_rms_db,
        separation_db=separation,
    )


def calibrate_silence_gate(
    media_path: str,
    start_sec: float,
    end_sec: float,
    *,
    audio_streams: Optional[int] = None,
) -> NoiseCalibration:
    """Measure this slice's noise floor and place a silence gate just above it.

    Falls back to `DEFAULT_THRESHOLD_DB` — always with a stated reason — when the
    file cannot be measured or the floor is not separated from the programme.
    """
    if not media_path or not os.path.isfile(media_path):
        return NoiseCalibration(
            gate_db=DEFAULT_THRESHOLD_DB, basis="fallback_default", usable=False,
            reason="media file is not readable",
        )
    if end_sec <= start_sec:
        return NoiseCalibration(
            gate_db=DEFAULT_THRESHOLD_DB, basis="fallback_default", usable=False,
            reason="empty source range",
        )
    from src.utils.media_analysis import _run_command

    streams = audio_stream_count(media_path) if audio_streams is None else audio_streams
    if streams == 0:
        return NoiseCalibration(
            gate_db=DEFAULT_THRESHOLD_DB, basis="fallback_default", usable=False,
            reason="no audio streams",
        )
    args = build_audio_filter_args(
        media_path, start_sec, end_sec - start_sec, "astats", audio_streams=streams
    )
    code, _, stderr = _run_command(args)
    if code != 0 and streams > 1:
        # Same amerge fallback as detection: mismatched sample rates are refused.
        args = build_audio_filter_args(
            media_path, start_sec, end_sec - start_sec, "astats", audio_streams=1
        )
        code, _, stderr = _run_command(args)
    if code != 0:
        return NoiseCalibration(
            gate_db=DEFAULT_THRESHOLD_DB, basis="fallback_default", usable=False,
            reason="ffmpeg astats failed on this slice",
        )
    return _gate_from_levels(*_parse_astats_levels(stderr))


def detect_silence_in_range(
    media_path: str,
    start_sec: float,
    end_sec: float,
    *,
    threshold_db: float = DEFAULT_THRESHOLD_DB,
    min_duration_sec: float,
) -> List[Tuple[float, float]]:
    """Return absolute-file silence intervals within [start_sec, end_sec).

    Uses ffmpeg silencedetect on the trimmed slice (all audio streams merged).
    Timestamps are converted back to absolute source-file seconds.
    """
    if not media_path or not os.path.isfile(media_path):
        return []
    if end_sec <= start_sec:
        return []
    duration = end_sec - start_sec
    from src.utils.media_analysis import _run_command

    streams = audio_stream_count(media_path)
    if streams == 0:
        return []
    args = build_silencedetect_args(
        media_path, start_sec, duration,
        threshold_db=threshold_db, min_duration_sec=min_duration_sec,
        audio_streams=streams,
    )
    code, _, stderr = _run_command(args)
    if code != 0 and streams > 1:
        # amerge can refuse mismatched sample rates — fall back to the
        # default single-stream selection rather than dropping evidence.
        args = build_silencedetect_args(
            media_path, start_sec, duration,
            threshold_db=threshold_db, min_duration_sec=min_duration_sec,
            audio_streams=1,
        )
        code, _, stderr = _run_command(args)
    if code != 0:
        return []
    parsed = _parse_silencedetect(stderr)
    out: List[Tuple[float, float]] = []
    for row in parsed:
        rel_start = row.get("start")
        rel_end = row.get("end")
        if rel_start is None:
            continue
        abs_start = start_sec + float(rel_start)
        abs_end = start_sec + float(rel_end) if rel_end is not None else end_sec
        abs_end = min(abs_end, end_sec)
        if abs_end - abs_start >= min_duration_sec * 0.9:
            out.append((abs_start, abs_end))
    return out


def apply_silence_handles(
    silences: Sequence[Tuple[float, float]],
    *,
    pre_head_sec: float,
    post_tail_sec: float,
    range_start: float,
    range_end: float,
) -> List[Tuple[float, float]]:
    """Expand/shrink silence regions per Resolve pre-head / post-tail handles."""
    strip: List[Tuple[float, float]] = []
    for s, e in silences:
        s = max(range_start, s + pre_head_sec)
        e = min(range_end, e - post_tail_sec)
        if e > s + 0.001:
            strip.append((s, e))
    return strip


def silence_to_keep_segments(
    range_start: float,
    range_end: float,
    strip_regions: Sequence[Tuple[float, float]],
    *,
    min_keep_sec: float = 0.05,
) -> List[Tuple[float, float]]:
    """Complement of strip regions → speech/keep segments in source time."""
    segments: List[Tuple[float, float]] = []
    cursor = range_start
    for s, e in sorted(strip_regions):
        s, e = max(s, range_start), min(e, range_end)
        if s - cursor >= min_keep_sec:
            segments.append((cursor, s))
        cursor = max(cursor, e)
    if range_end - cursor >= min_keep_sec:
        segments.append((cursor, range_end))
    return segments


def plan_item_silence_strips(
    media_path: str,
    src_start_sec: float,
    src_end_sec: float,
    *,
    threshold_db: float,
    min_strip_sec: float,
    pre_head_sec: float,
    post_tail_sec: float,
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """Detect silences and return (strip_regions, keep_segments) in source seconds."""
    raw = detect_silence_in_range(
        media_path,
        src_start_sec,
        src_end_sec,
        threshold_db=threshold_db,
        min_duration_sec=min_strip_sec,
    )
    strip = apply_silence_handles(
        raw,
        pre_head_sec=pre_head_sec,
        post_tail_sec=post_tail_sec,
        range_start=src_start_sec,
        range_end=src_end_sec,
    )
    keep = silence_to_keep_segments(src_start_sec, src_end_sec, strip)
    return strip, keep
