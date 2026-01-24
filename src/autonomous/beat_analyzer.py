"""
Beat Analyzer - Extract beat timestamps and BPM from music files.

Milestone 5 implementation.

Uses librosa for beat detection. If librosa is not installed,
beat sync features are disabled gracefully (no failure).
"""

import json
import logging
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("autonomous.beat_analyzer")

# Check for librosa availability
_LIBROSA_AVAILABLE = False
try:
    import librosa
    import numpy as np
    _LIBROSA_AVAILABLE = True
    logger.debug(f"librosa available: {librosa.__version__}")
except ImportError:
    logger.debug("librosa not installed - beat sync disabled")


def is_librosa_available() -> bool:
    """Check if librosa is available for beat analysis."""
    return _LIBROSA_AVAILABLE


@dataclass
class BeatAnalysis:
    """Result of beat analysis on a music file."""

    # Source file
    file_path: str
    duration_sec: float = 0.0

    # BPM
    bpm: float = 120.0
    bpm_confidence: Optional[float] = None

    # Beat timestamps (in seconds)
    beats_sec: List[float] = field(default_factory=list)

    # Downbeats (first beat of each bar) - optional
    downbeats_sec: List[float] = field(default_factory=list)

    # Analysis metadata
    sample_rate: int = 22050
    hop_length: int = 512
    analysis_method: str = "librosa"

    # Timestamps
    analyzed_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "duration_sec": round(self.duration_sec, 3),
            "bpm": round(self.bpm, 2),
            "bpm_confidence": round(self.bpm_confidence, 3) if self.bpm_confidence else None,
            "beats_sec": [round(b, 3) for b in self.beats_sec],
            "downbeats_sec": [round(d, 3) for d in self.downbeats_sec],
            "beat_count": len(self.beats_sec),
            "downbeat_count": len(self.downbeats_sec),
            "sample_rate": self.sample_rate,
            "hop_length": self.hop_length,
            "analysis_method": self.analysis_method,
            "analyzed_at": self.analyzed_at,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: Path) -> None:
        """Save beat analysis to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        logger.info(f"Saved beat analysis to: {path}")

    @classmethod
    def load(cls, path: Path) -> "BeatAnalysis":
        """Load beat analysis from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            file_path=data.get("file_path", ""),
            duration_sec=data.get("duration_sec", 0.0),
            bpm=data.get("bpm", 120.0),
            bpm_confidence=data.get("bpm_confidence"),
            beats_sec=data.get("beats_sec", []),
            downbeats_sec=data.get("downbeats_sec", []),
            sample_rate=data.get("sample_rate", 22050),
            hop_length=data.get("hop_length", 512),
            analysis_method=data.get("analysis_method", "loaded"),
            analyzed_at=data.get("analyzed_at", ""),
        )

    def get_nearest_beat(self, time_sec: float, tolerance_sec: float = 0.1) -> Optional[float]:
        """
        Find the nearest beat to a given time within tolerance.

        Returns the beat time if within tolerance, None otherwise.
        """
        if not self.beats_sec:
            return None

        nearest = min(self.beats_sec, key=lambda b: abs(b - time_sec))
        if abs(nearest - time_sec) <= tolerance_sec:
            return nearest
        return None

    def get_nearest_downbeat(self, time_sec: float, tolerance_sec: float = 0.2) -> Optional[float]:
        """
        Find the nearest downbeat to a given time within tolerance.

        Returns the downbeat time if within tolerance, None otherwise.
        """
        if not self.downbeats_sec:
            return None

        nearest = min(self.downbeats_sec, key=lambda d: abs(d - time_sec))
        if abs(nearest - time_sec) <= tolerance_sec:
            return nearest
        return None


class BeatAnalyzer:
    """
    Analyzes music files to extract beats and BPM.

    Requires librosa. If not installed, returns None gracefully.
    """

    DEFAULT_SAMPLE_RATE = 22050
    DEFAULT_HOP_LENGTH = 512

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        hop_length: int = DEFAULT_HOP_LENGTH,
    ):
        self.sample_rate = sample_rate
        self.hop_length = hop_length

        if not _LIBROSA_AVAILABLE:
            logger.warning(
                "librosa not installed - beat analysis unavailable. "
                "Install with: pip install librosa"
            )

    def analyze(self, file_path: str) -> Optional[BeatAnalysis]:
        """
        Analyze a music file for beats and BPM.

        Args:
            file_path: Path to audio file (WAV, MP3, etc.)

        Returns:
            BeatAnalysis with beat timestamps, or None if librosa unavailable
        """
        if not _LIBROSA_AVAILABLE:
            logger.warning("Cannot analyze beats - librosa not installed")
            return None

        file_path = str(file_path)

        if not Path(file_path).exists():
            logger.error(f"Audio file not found: {file_path}")
            return None

        try:
            logger.info(f"Analyzing beats: {file_path}")

            # Load audio
            y, sr = librosa.load(file_path, sr=self.sample_rate)
            duration_sec = librosa.get_duration(y=y, sr=sr)

            # Get tempo and beat frames
            tempo, beat_frames = librosa.beat.beat_track(
                y=y, sr=sr, hop_length=self.hop_length
            )

            # Handle tempo as array (newer librosa versions)
            if hasattr(tempo, '__len__'):
                bpm = float(tempo[0]) if len(tempo) > 0 else 120.0
            else:
                bpm = float(tempo)

            # Convert frames to time
            beats_sec = librosa.frames_to_time(
                beat_frames, sr=sr, hop_length=self.hop_length
            ).tolist()

            # Try to detect downbeats (bar starts)
            downbeats_sec = self._detect_downbeats(y, sr, beats_sec, bpm)

            # Estimate tempo confidence using tempogram
            bpm_confidence = self._estimate_tempo_confidence(y, sr, bpm)

            result = BeatAnalysis(
                file_path=file_path,
                duration_sec=duration_sec,
                bpm=bpm,
                bpm_confidence=bpm_confidence,
                beats_sec=beats_sec,
                downbeats_sec=downbeats_sec,
                sample_rate=sr,
                hop_length=self.hop_length,
                analysis_method="librosa",
            )

            logger.info(
                f"Beat analysis complete: {bpm:.1f} BPM, "
                f"{len(beats_sec)} beats, {len(downbeats_sec)} downbeats, "
                f"{duration_sec:.1f}s duration"
            )

            return result

        except Exception as e:
            logger.error(f"Beat analysis failed: {e}")
            return None

    def _detect_downbeats(
        self,
        y: "np.ndarray",
        sr: int,
        beats_sec: List[float],
        bpm: float,
    ) -> List[float]:
        """
        Attempt to detect downbeats (first beat of each bar).

        Simple approach: assume 4/4 time signature and pick every 4th beat.
        """
        if len(beats_sec) < 4:
            return beats_sec[:1] if beats_sec else []

        # Simple: every 4th beat is a downbeat (4/4 time)
        downbeats = beats_sec[::4]

        return downbeats

    def _estimate_tempo_confidence(
        self,
        y: "np.ndarray",
        sr: int,
        detected_bpm: float,
    ) -> Optional[float]:
        """
        Estimate confidence in detected BPM using onset strength.

        Returns a value 0-1, or None if can't compute.
        """
        try:
            # Get onset envelope
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)

            # Get tempogram
            tempogram = librosa.feature.tempogram(
                onset_envelope=onset_env, sr=sr
            )

            # Find strength at detected tempo
            # Map BPM to tempogram index
            bpm_range = librosa.tempo_frequencies(tempogram.shape[0], sr=sr)

            # Find closest BPM in range
            bpm_idx = np.argmin(np.abs(bpm_range - detected_bpm))

            # Confidence is relative strength at that tempo
            tempo_strength = np.mean(tempogram[bpm_idx, :])
            max_strength = np.max(np.mean(tempogram, axis=1))

            if max_strength > 0:
                confidence = tempo_strength / max_strength
                return min(1.0, max(0.0, confidence))

            return None

        except Exception:
            return None


def snap_to_beat(
    time_sec: float,
    beats: BeatAnalysis,
    tolerance_sec: float = 0.1,
    prefer_downbeats: bool = False,
    min_time_sec: float = 0.0,
) -> float:
    """
    Snap a time to the nearest beat within tolerance.

    Args:
        time_sec: Time to snap
        beats: Beat analysis result
        tolerance_sec: Maximum distance to snap
        prefer_downbeats: If True, prefer downbeats over regular beats
        min_time_sec: Minimum allowed time (won't snap below this)

    Returns:
        Snapped time, or original time if no beat nearby
    """
    if not beats or not beats.beats_sec:
        return time_sec

    result = time_sec

    # Try downbeats first if preferred
    if prefer_downbeats and beats.downbeats_sec:
        nearest_downbeat = beats.get_nearest_downbeat(time_sec, tolerance_sec * 2)
        if nearest_downbeat is not None and nearest_downbeat >= min_time_sec:
            result = nearest_downbeat
            return result

    # Try regular beats
    nearest_beat = beats.get_nearest_beat(time_sec, tolerance_sec)
    if nearest_beat is not None and nearest_beat >= min_time_sec:
        result = nearest_beat

    return result


def snap_clip_boundaries(
    clip_in_sec: float,
    clip_out_sec: float,
    beats: BeatAnalysis,
    tolerance_sec: float = 0.1,
    prefer_downbeats: bool = False,
    min_duration_sec: float = 1.0,
) -> Tuple[float, float]:
    """
    Snap clip IN and OUT points to beats while respecting minimum duration.

    Args:
        clip_in_sec: Clip start time
        clip_out_sec: Clip end time
        beats: Beat analysis result
        tolerance_sec: Maximum snap distance
        prefer_downbeats: Prefer downbeats for snapping
        min_duration_sec: Minimum clip duration

    Returns:
        Tuple of (snapped_in, snapped_out)
    """
    if not beats or not beats.beats_sec:
        return clip_in_sec, clip_out_sec

    # Snap IN point
    snapped_in = snap_to_beat(
        clip_in_sec, beats, tolerance_sec, prefer_downbeats, min_time_sec=0.0
    )

    # Calculate minimum OUT based on snapped IN
    min_out = snapped_in + min_duration_sec

    # Snap OUT point (must be >= min_out)
    snapped_out = snap_to_beat(
        clip_out_sec, beats, tolerance_sec, prefer_downbeats, min_time_sec=min_out
    )

    # Ensure OUT > IN + min_duration
    if snapped_out < snapped_in + min_duration_sec:
        snapped_out = clip_out_sec  # Revert to original if snapping violates constraint

    return snapped_in, snapped_out


def analyze_music(
    file_path: str,
    output_path: Optional[Path] = None,
) -> Optional[BeatAnalysis]:
    """
    Convenience function to analyze music and optionally save results.

    Args:
        file_path: Path to music file
        output_path: Optional path to save beats.json

    Returns:
        BeatAnalysis or None if analysis unavailable
    """
    analyzer = BeatAnalyzer()
    result = analyzer.analyze(file_path)

    if result and output_path:
        result.save(output_path)

    return result
