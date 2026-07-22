"""Waveform silence detection for ripple-delete planning.

Resolve exposes **Clip → Audio Operations → Ripple Delete Silence** in the UI
but not via scripting. This module approximates that workflow using ffmpeg
``silencedetect`` plus the edit-engine keep-range assembler (variant timeline).

Settings map to the Resolve dialog:
  - threshold_db     → Threshold (dB)
  - min_strip_frames → Minimum strip length (frames)
  - pre_head_frames  → Pre-head (frames kept before silence)
  - post_tail_frames → Post-tail (frames kept after silence ends)
"""

from __future__ import annotations

import os
import shutil
from typing import List, Sequence, Tuple

from src.utils.media_analysis import _parse_silencedetect

DEFAULT_THRESHOLD_DB = -30.0
DEFAULT_MIN_STRIP_FRAMES = 10
DEFAULT_PRE_HEAD_FRAMES = 0
DEFAULT_POST_TAIL_FRAMES = 1


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def frames_to_seconds(frames: float, fps: float) -> float:
    if fps <= 0:
        fps = 24.0
    return float(frames) / fps


def detect_silence_in_range(
    media_path: str,
    start_sec: float,
    end_sec: float,
    *,
    threshold_db: float = DEFAULT_THRESHOLD_DB,
    min_duration_sec: float,
) -> List[Tuple[float, float]]:
    """Return absolute-file silence intervals within [start_sec, end_sec).

    Uses ffmpeg silencedetect on the trimmed slice. Timestamps are converted
    back to absolute source-file seconds.
    """
    if not media_path or not os.path.isfile(media_path):
        return []
    if end_sec <= start_sec:
        return []
    duration = end_sec - start_sec
    audio_filter = f"silencedetect=noise={threshold_db}dB:d={min_duration_sec}"
    from src.utils.media_analysis import _run_command

    args = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-ss", str(start_sec),
        "-i", media_path,
        "-t", str(duration),
        "-af", audio_filter,
        "-f", "null", "-",
    ]
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
