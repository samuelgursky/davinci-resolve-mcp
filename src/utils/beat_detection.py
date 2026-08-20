"""Beat detection for music-driven cutting.

The single most-requested missing capability from the first public audience for
this project. Music-video makers, live-music channels and motorsport editors all
asked variants of the same thing, and one put the failure precisely: the tools
here only cut interviews, they do not cut to music. A viewer editing drift
footage predicted the exact consequence of pointing a speech-silence gate at his
material — engine noise and smoke read as "dead space", and the tool cuts in all
the wrong places.

They are right, and the reason is structural. Everything else in this codebase
finds edit points in *speech*: word boundaries, pauses, fillers. Music has none
of those. It has pulse, and pulse is a completely different measurement.

## What this gives you

- **Beats** — the pulse. Cutting on every beat is relentless and usually wrong.
- **Phrases** — beats grouped into bars and bars into phrases (typically 4 or 8
  bars). Music resolves at phrase boundaries, which is where an edit feels
  *inevitable* rather than merely synchronised. This is the one that matters.
- **Frame-snapped cut points**, because a cut two frames off the beat reads as a
  mistake rather than as syncopation.

## Honest limits

Tempo tracking is reliable on steady, percussive material and degrades on rubato,
live performance without a strong downbeat, and anything heavily swung. The
detector reports its own confidence and this module surfaces it rather than
presenting every result as equally solid.

Downbeats are **inferred**, not detected: the first beat is assumed to start a
bar. That assumption is wrong whenever a track has a pickup, and it is the first
thing to check if the cuts feel consistently one beat early. `beat_offset` exists
to correct it.

## Dependency

`librosa` (ISC) is an **optional extra** — it is not in `requirements.txt`, it
pulls a large scientific stack, and this module honest-refuses without it rather
than degrading into a guess. Install with `pip install librosa`.
"""

from __future__ import annotations

import importlib.util
from typing import Any, Dict, List, Sequence

#: Beats per bar. 4/4 covers the overwhelming majority of cuttable music; the
#: parameter exists because 3/4 and 6/8 do turn up and silently forcing them
#: into 4 produces phrase boundaries that land in musically wrong places.
DEFAULT_BEATS_PER_BAR = 4
#: Bars per phrase. 8 bars is the common pop/dance period; 4 suits shorter cuts.
DEFAULT_BARS_PER_PHRASE = 8


def librosa_available() -> bool:
    """Presence check without importing — librosa costs seconds to import."""
    try:
        return importlib.util.find_spec("librosa") is not None
    except (ImportError, ValueError):
        return False


def detect_beats(media_path: str, *, sample_rate: int = 22050) -> Dict[str, Any]:
    """Tempo and beat times for an audio or video file.

    Honest-refuses when librosa is absent. A fabricated tempo would produce cuts
    that are confidently, rhythmically wrong — worse than no feature, because
    the failure looks intentional.
    """
    if not librosa_available():
        return {
            "success": False,
            "error": "librosa is not installed — beat detection is unavailable",
            "remediation": (
                "pip install librosa  (ISC licensed, optional extra; it pulls "
                "numpy/scipy/numba and is deliberately not a core dependency)"
            ),
        }
    import librosa

    try:
        y, sr = librosa.load(media_path, sr=sample_rate, mono=True)
    except Exception as exc:
        return {"success": False, "error": f"could not read audio from {media_path}: {exc}"}
    if y is None or len(y) == 0:
        return {"success": False, "error": "no audio samples decoded — is there an audio track?"}

    try:
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    except Exception as exc:
        return {"success": False, "error": f"beat tracking failed: {exc}"}

    beats = [round(float(t), 4) for t in beat_times]
    tempo_value = float(tempo if not hasattr(tempo, "__len__") else (tempo[0] if len(tempo) else 0.0))
    return {
        "success": True,
        "tempo_bpm": round(tempo_value, 2),
        "beat_count": len(beats),
        "beats": beats,
        "duration_seconds": round(float(len(y)) / sr, 3),
        "confidence": _confidence(beats, onset_env),
    }


def _confidence(beats: Sequence[float], onset_env) -> Dict[str, Any]:
    """How regular the detected pulse is.

    A steady grid means the tracker locked on. Wildly varying intervals mean it
    did not, and the caller should be told rather than handed a tidy-looking
    list of times that happens to be wrong.
    """
    if len(beats) < 4:
        return {"band": "low", "reason": "too few beats detected to judge regularity"}
    intervals = [b - a for a, b in zip(beats, beats[1:])]
    mean = sum(intervals) / len(intervals)
    if mean <= 0:
        return {"band": "low", "reason": "degenerate beat spacing"}
    variance = sum((i - mean) ** 2 for i in intervals) / len(intervals)
    jitter = (variance ** 0.5) / mean
    if jitter < 0.05:
        band, reason = "high", "beat spacing is steady — the tracker locked on"
    elif jitter < 0.15:
        band, reason = "medium", "some drift in beat spacing; check a few cuts against the music"
    else:
        band, reason = "low", (
            "beat spacing is irregular — rubato, live playing or a weak downbeat. "
            "Treat these cut points as suggestions"
        )
    return {"band": band, "jitter": round(jitter, 4), "reason": reason}


def group_into_phrases(
    beats: Sequence[float],
    *,
    beats_per_bar: int = DEFAULT_BEATS_PER_BAR,
    bars_per_phrase: int = DEFAULT_BARS_PER_PHRASE,
    beat_offset: int = 0,
) -> Dict[str, Any]:
    """Group beats into bars and phrases. Pure — no librosa needed.

    `beat_offset` shifts which beat is treated as the first of a bar. Downbeats
    are inferred rather than detected, so a track with a pickup will be off by
    one until this is set; that is the first knob to reach for when cuts feel
    consistently early.
    """
    if beats_per_bar < 1 or bars_per_phrase < 1:
        raise ValueError("beats_per_bar and bars_per_phrase must be >= 1")
    ordered = sorted(float(b) for b in beats)
    per_phrase = beats_per_bar * bars_per_phrase
    downbeats: List[float] = []
    phrase_starts: List[float] = []
    for index, time in enumerate(ordered):
        position = index - beat_offset
        if position < 0:
            continue
        if position % beats_per_bar == 0:
            downbeats.append(round(time, 4))
        if position % per_phrase == 0:
            phrase_starts.append(round(time, 4))
    return {
        "beats_per_bar": beats_per_bar,
        "bars_per_phrase": bars_per_phrase,
        "beat_offset": beat_offset,
        "downbeats": downbeats,
        "phrase_starts": phrase_starts,
        "bar_count": len(downbeats),
        "phrase_count": len(phrase_starts),
        "note": (
            "Downbeats are INFERRED — the first beat is assumed to start a bar. "
            "A track with a pickup will be off by one; correct it with beat_offset."
        ),
    }


def snap_to_frames(times: Sequence[float], fps: float) -> List[int]:
    """Times to frame numbers. A cut two frames off the beat reads as a mistake."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    return [int(round(float(t) * fps)) for t in times]


def plan_beat_cuts(
    beats: Sequence[float],
    *,
    fps: float,
    mode: str = "phrase",
    beats_per_bar: int = DEFAULT_BEATS_PER_BAR,
    bars_per_phrase: int = DEFAULT_BARS_PER_PHRASE,
    beat_offset: int = 0,
    min_shot_seconds: float = 0.0,
) -> Dict[str, Any]:
    """Cut points on the beat, the bar, or the phrase. Pure and testable.

    `mode`:
      - `beat`   — every beat. Relentless; suits montage stings, little else.
      - `bar`    — every downbeat.
      - `phrase` — every phrase start (**default**). Music resolves here, which
        is what makes a cut feel inevitable rather than merely synchronised.
    """
    if mode not in ("beat", "bar", "phrase"):
        raise ValueError(f"unknown mode {mode!r}; expected beat, bar or phrase")
    grouped = group_into_phrases(
        beats, beats_per_bar=beats_per_bar,
        bars_per_phrase=bars_per_phrase, beat_offset=beat_offset,
    )
    times = {
        "beat": sorted(float(b) for b in beats),
        "bar": grouped["downbeats"],
        "phrase": grouped["phrase_starts"],
    }[mode]

    dropped = 0
    if min_shot_seconds > 0 and times:
        kept = [times[0]]
        for time in times[1:]:
            if time - kept[-1] >= min_shot_seconds:
                kept.append(time)
            else:
                dropped += 1
        times = kept

    return {
        "success": True,
        "kind": "beat_cuts",
        "mode": mode,
        "cut_count": len(times),
        "cut_times": [round(t, 4) for t in times],
        "cut_frames": snap_to_frames(times, fps),
        "grouping": grouped,
        "dropped_for_min_shot": dropped,
        "note": (
            f"Cut points on every {mode}. "
            + (f"{dropped} were dropped to honour min_shot_seconds={min_shot_seconds}. "
               if dropped else "")
            + "Frame-snapped: a cut two frames off the beat reads as a mistake rather "
            "than syncopation. These are cut POINTS, not an assembly — what goes "
            "between them is yours."
        ),
    }
