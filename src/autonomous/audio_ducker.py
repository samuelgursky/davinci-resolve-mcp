# src/autonomous/audio_ducker.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import json
import subprocess


@dataclass
class DuckingConfig:
    duck_db: float = 10.0           # how much to reduce music during speech
    fade_ms: int = 120              # fade in/out for each duck region
    min_gap_ms: int = 200           # merge segments separated by short gaps
    pad_ms: int = 80                # pad speech regions by this much on each side


def load_vad_json(vad_json_path: Path) -> Dict:
    with open(vad_json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _merge_and_pad_segments(
    segments: List[Dict],
    pad_ms: int,
    min_gap_ms: int,
) -> List[Tuple[float, float]]:
    """
    Merge adjacent segments if gap <= min_gap_ms, and pad each side by pad_ms.
    Returns list of (start_s, end_s) sorted, non-overlapping.
    """
    if not segments:
        return []

    # sort
    segs = sorted([(float(s["start"]), float(s["end"])) for s in segments], key=lambda x: x[0])

    pad = pad_ms / 1000.0
    min_gap = min_gap_ms / 1000.0

    merged: List[Tuple[float, float]] = []
    cur_s, cur_e = segs[0]
    cur_s = max(0.0, cur_s - pad)
    cur_e = max(cur_s, cur_e + pad)

    for s, e in segs[1:]:
        s = max(0.0, s - pad)
        e = max(s, e + pad)

        if s - cur_e <= min_gap:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e

    merged.append((cur_s, cur_e))
    return merged


def _ffmpeg_run(cmd: List[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "FFmpeg command failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr:\n{proc.stderr}"
        )


def duck_music_segment_aware(
    music_in: Path,
    vad_json: Path,
    music_out: Path,
    cfg: DuckingConfig = DuckingConfig(),
) -> Dict:
    """
    Create a ducked music file where music level is reduced only during VAD speech segments.
    Returns metadata about the ducking regions.
    """
    vad = load_vad_json(vad_json)
    has_speech = bool(vad.get("has_speech", False))
    segments = vad.get("segments", []) or []

    music_out.parent.mkdir(parents=True, exist_ok=True)

    if not has_speech or not segments:
        # No speech => copy through (no ducking)
        cmd = ["ffmpeg", "-y", "-i", str(music_in), "-c", "copy", str(music_out)]
        _ffmpeg_run(cmd)
        return {"has_speech": False, "regions": [], "mode": "copy-through"}

    regions = _merge_and_pad_segments(
        segments=segments,
        pad_ms=cfg.pad_ms,
        min_gap_ms=cfg.min_gap_ms,
    )

    # Convert dB reduction to linear multiplier
    # volume = 10^(-duck_db/20)
    duck_mult = 10 ** (-cfg.duck_db / 20.0)

    fade = cfg.fade_ms / 1000.0

    # Build a smooth envelope using volume expression:
    # For each region [s,e], apply a trapezoid:
    # - fade down from 1 -> duck_mult over [s, s+fade]
    # - stay at duck_mult over [s+fade, e-fade]
    # - fade up duck_mult -> 1 over [e-fade, e]
    #
    # We combine multiple regions by applying the minimum volume at any time:
    # volume = min(1, region1_curve, region2_curve, ...)
    #
    # FFmpeg expression supports min(), if(), between(), lt(), gt(), etc.
    def region_expr(s: float, e: float) -> str:
        s1 = s
        s2 = s + fade
        e1 = max(s2, e - fade)
        e2 = e

        # piecewise:
        # t < s1 => 1
        # s1<=t<s2 => 1 - (1-duck_mult)*((t-s1)/fade)
        # s2<=t<=e1 => duck_mult
        # e1<t<=e2 => duck_mult + (1-duck_mult)*((t-e1)/fade)
        # t > e2 => 1
        # (Guard: if region too short for fades, it will behave mostly as duck_mult)
        return (
            f"if(lt(t,{s1}),1,"
            f"if(lt(t,{s2}),"
            f"(1-({1.0 - duck_mult})*((t-{s1})/{fade})),"
            f"if(lt(t,{e1}),{duck_mult},"
            f"if(lt(t,{e2}),"
            f"({duck_mult}+({1.0 - duck_mult})*((t-{e1})/{fade})),"
            f"1))))"
        )

    # Combine via min()
    exprs = [region_expr(s, e) for s, e in regions]
    vol_expr = exprs[0]
    for ex in exprs[1:]:
        vol_expr = f"min({vol_expr},{ex})"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(music_in),
        "-af",
        f"volume='{vol_expr}'",
        str(music_out),
    ]
    _ffmpeg_run(cmd)

    return {"has_speech": True, "regions": [{"start": s, "end": e} for s, e in regions], "mode": "segment-aware"}
