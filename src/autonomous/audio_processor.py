"""
Audio Processor - Ducking and audio preprocessing.

Milestone 6 implementation.

Uses ffmpeg for audio ducking (reducing music volume when voiceover plays).
No Resolve audio keyframes - preprocessing only.
"""

import json
import logging
import subprocess
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("autonomous.audio_processor")


def _load_vad(vad_json_path: Path) -> dict:
    with open(vad_json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _merge_and_pad_regions(
    segments: List[Dict[str, float]],
    pad_ms: int = 80,
    min_gap_ms: int = 200,
) -> List[Tuple[float, float]]:
    if not segments:
        return []

    segs = sorted(
        [(float(s["start"]), float(s["end"])) for s in segments],
        key=lambda x: x[0],
    )
    pad = pad_ms / 1000.0
    gap = min_gap_ms / 1000.0

    merged: List[Tuple[float, float]] = []
    cur_s, cur_e = segs[0]
    cur_s = max(0.0, cur_s - pad)
    cur_e = max(cur_s, cur_e + pad)

    for s, e in segs[1:]:
        s = max(0.0, s - pad)
        e = max(s, e + pad)
        if s - cur_e <= gap:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e

    merged.append((cur_s, cur_e))
    return merged


def _build_segment_duck_volume_expr(
    regions: List[Tuple[float, float]],
    duck_db: float,
    fade_ms: int = 120,
) -> str:
    duck_mult = 10 ** (-duck_db / 20.0)
    fade = max(0.01, fade_ms / 1000.0)

    def region_expr(s: float, e: float) -> str:
        s1 = s
        s2 = s + fade
        e1 = max(s2, e - fade)
        e2 = e

        return (
            f"if(lt(t,{s1}),1,"
            f"if(lt(t,{s2}),"
            f"(1-({1.0 - duck_mult})*((t-{s1})/{fade})),"
            f"if(lt(t,{e1}),{duck_mult},"
            f"if(lt(t,{e2}),"
            f"({duck_mult}+({1.0 - duck_mult})*((t-{e1})/{fade})),"
            f"1))))"
        )

    if not regions:
        return "1"

    expr = region_expr(regions[0][0], regions[0][1])
    for s, e in regions[1:]:
        expr = f"min({expr},{region_expr(s,e)})"
    return expr


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg is available."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


@dataclass
class DuckingConfig:
    """Configuration for audio ducking."""

    # Ducking amount (how much to reduce music when voice plays)
    ducking_db: float = -12.0  # dB reduction during voice

    # Voice detection threshold
    voice_threshold_db: float = -30.0

    # Attack/release times for smooth ducking
    attack_ms: float = 200.0
    release_ms: float = 500.0

    # Voice start offset (delay before voice begins)
    voice_start_sec: float = 0.0

    # Output quality
    output_sample_rate: int = 48000
    output_bitrate: str = "320k"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ducking_db": self.ducking_db,
            "voice_threshold_db": self.voice_threshold_db,
            "attack_ms": self.attack_ms,
            "release_ms": self.release_ms,
            "voice_start_sec": self.voice_start_sec,
            "output_sample_rate": self.output_sample_rate,
            "output_bitrate": self.output_bitrate,
        }


@dataclass
class DuckingResult:
    """Result of audio ducking operation."""

    # Input files
    music_path: str
    voice_path: str

    # Output file
    output_path: str

    # Configuration used
    config: DuckingConfig

    # Status
    success: bool = False
    error_message: Optional[str] = None

    # Metadata
    music_duration_sec: Optional[float] = None
    voice_duration_sec: Optional[float] = None
    output_duration_sec: Optional[float] = None
    processed_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "music_path": self.music_path,
            "voice_path": self.voice_path,
            "output_path": self.output_path,
            "config": self.config.to_dict(),
            "success": self.success,
            "error_message": self.error_message,
            "music_duration_sec": self.music_duration_sec,
            "voice_duration_sec": self.voice_duration_sec,
            "output_duration_sec": self.output_duration_sec,
            "processed_at": self.processed_at,
        }

    def save(self, path: Path) -> None:
        """Save ducking result to JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)


class AudioProcessor:
    """
    Processes audio files for video editing.

    Primary feature: Ducking (reducing music volume during voiceover).
    Uses ffmpeg for all processing.
    """

    def __init__(self, work_dir: Optional[Path] = None):
        self.work_dir = Path(work_dir) if work_dir else Path("work/audio")
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self._ffmpeg_available = is_ffmpeg_available()
        if not self._ffmpeg_available:
            logger.warning("ffmpeg not available - audio processing disabled")

    def get_audio_duration(self, file_path: str) -> Optional[float]:
        """Get duration of an audio file using ffprobe."""
        try:
            cmd = [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                data = json.loads(result.stdout)
                return float(data.get("format", {}).get("duration", 0))
        except Exception as e:
            logger.warning(f"Could not get duration for {file_path}: {e}")

        return None

    def create_ducked_music(
        self,
        music_path: str,
        voice_path: str,
        output_path: Optional[str] = None,
        config: Optional[DuckingConfig] = None,
    ) -> DuckingResult:
        """
        Create a ducked version of music that reduces volume during voiceover.

        Uses ffmpeg's sidechaincompress filter for smooth ducking.

        Args:
            music_path: Path to music file
            voice_path: Path to voiceover file
            output_path: Output path (default: work/audio/music_ducked.wav)
            config: Ducking configuration

        Returns:
            DuckingResult with success status and output path
        """
        config = config or DuckingConfig()

        if output_path is None:
            output_path = str(self.work_dir / "music_ducked.wav")

        result = DuckingResult(
            music_path=music_path,
            voice_path=voice_path,
            output_path=output_path,
            config=config,
        )

        # Check ffmpeg
        if not self._ffmpeg_available:
            result.error_message = "ffmpeg not available"
            logger.error(result.error_message)
            return result

        # Check input files
        if not Path(music_path).exists():
            result.error_message = f"Music file not found: {music_path}"
            logger.error(result.error_message)
            return result

        if not Path(voice_path).exists():
            result.error_message = f"Voice file not found: {voice_path}"
            logger.error(result.error_message)
            return result

        # Get durations
        result.music_duration_sec = self.get_audio_duration(music_path)
        result.voice_duration_sec = self.get_audio_duration(voice_path)

        try:
            logger.info(f"Creating ducked music: {music_path}")
            logger.info(f"  Voice: {voice_path}")
            logger.info(f"  Ducking: {config.ducking_db}dB")

            # Ensure output directory exists
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            # Build ffmpeg command for sidechain compression ducking
            # This uses the voice as a sidechain to compress (duck) the music
            #
            # Method: Use sidechaincompress filter
            # - Voice triggers compression on music
            # - When voice is present, music volume is reduced
            #
            # Alternative simpler method: create ducked mix
            # - Normalize voice, reduce music volume during voice sections

            # Calculate compression ratio from ducking dB
            # -12dB ducking means we want output at ~25% volume when voice present
            ratio = 10 ** (-config.ducking_db / 20)  # Convert dB to ratio

            # Build filter complex for sidechaincompress
            # [0] = music, [1] = voice (sidechain input)
            filter_complex = (
                f"[1:a]aformat=sample_fmts=fltp:sample_rates={config.output_sample_rate}:channel_layouts=stereo[voice];"
                f"[0:a]aformat=sample_fmts=fltp:sample_rates={config.output_sample_rate}:channel_layouts=stereo[music];"
                f"[music][voice]sidechaincompress="
                f"threshold={config.voice_threshold_db}dB:"
                f"ratio={ratio:.1f}:"
                f"attack={config.attack_ms}:"
                f"release={config.release_ms}:"
                f"level_sc=1[ducked]"
            )

            cmd = [
                "ffmpeg", "-y",
                "-i", music_path,
                "-i", voice_path,
                "-filter_complex", filter_complex,
                "-map", "[ducked]",
                "-ar", str(config.output_sample_rate),
                "-c:a", "pcm_s16le",  # WAV output
                output_path,
            ]

            logger.debug(f"ffmpeg command: {' '.join(cmd)}")

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if proc.returncode != 0:
                # Try simpler fallback method
                logger.warning("Sidechaincompress failed, trying fallback method")
                result = self._create_ducked_music_fallback(
                    music_path, voice_path, output_path, config, result
                )
            else:
                result.success = True
                result.output_duration_sec = self.get_audio_duration(output_path)
                logger.info(f"Ducked music created: {output_path}")

        except subprocess.TimeoutExpired:
            result.error_message = "ffmpeg timed out"
            logger.error(result.error_message)
        except Exception as e:
            result.error_message = str(e)
            logger.error(f"Ducking failed: {e}")

        return result

    def create_ducked_music_segment_aware(
        self,
        music_path: Path,
        vad_json_path: Path,
        output_path: Path,
        duck_db: float = 10.0,
        fade_ms: int = 120,
        pad_ms: int = 80,
        min_gap_ms: int = 200,
    ) -> DuckingResult:
        """
        Segment-aware ducking: reduce music only during VAD speech segments.
        Produces output_path.
        """
        # Create config from parameters
        config = DuckingConfig(ducking_db=-duck_db)  # Convert positive duck_db to negative dB
        
        # Initialize result with required fields
        result = DuckingResult(
            music_path=str(music_path),
            voice_path=str(vad_json_path),  # Use vad_json_path as voice_path since no voice file is used
            output_path=str(output_path),
            config=config,
        )
        
        try:
            if not vad_json_path.exists():
                result.error_message = f"vad.json not found: {vad_json_path}"
                return result

            vad = _load_vad(vad_json_path)
            segments = vad.get("segments") or []
            has_speech = bool(vad.get("has_speech", False)) and len(segments) > 0

            output_path.parent.mkdir(parents=True, exist_ok=True)

            if not has_speech:
                cmd = ["ffmpeg", "-y", "-i", str(music_path), "-c", "copy", str(output_path)]
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if proc.returncode != 0:
                    result.error_message = proc.stderr
                    return result
                result.success = True
                result.output_duration_sec = self.get_audio_duration(str(output_path))
                return result

            regions = _merge_and_pad_regions(segments, pad_ms=pad_ms, min_gap_ms=min_gap_ms)
            vol_expr = _build_segment_duck_volume_expr(regions, duck_db=duck_db, fade_ms=fade_ms)

            cmd = ["ffmpeg", "-y", "-i", str(music_path), "-af", f"volume='{vol_expr}'", str(output_path)]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if proc.returncode != 0:
                result.error_message = proc.stderr
                return result

            result.success = True
            result.output_duration_sec = self.get_audio_duration(str(output_path))
            return result

        except Exception as e:
            result.error_message = str(e)
            return result

    def _create_ducked_music_fallback(
        self,
        music_path: str,
        voice_path: str,
        output_path: str,
        config: DuckingConfig,
        result: DuckingResult,
    ) -> DuckingResult:
        """
        Fallback ducking method: Simple volume reduction on music.

        This is less dynamic but more compatible.
        """
        try:
            # Simple approach: reduce music volume globally
            # (not as good as sidechain but works everywhere)
            volume_reduction = config.ducking_db / 2  # Half the ducking for constant reduction

            cmd = [
                "ffmpeg", "-y",
                "-i", music_path,
                "-af", f"volume={volume_reduction}dB",
                "-ar", str(config.output_sample_rate),
                "-c:a", "pcm_s16le",
                output_path,
            ]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )

            if proc.returncode == 0:
                result.success = True
                result.output_duration_sec = self.get_audio_duration(output_path)
                logger.info(f"Ducked music created (fallback method): {output_path}")
            else:
                result.error_message = f"ffmpeg error: {proc.stderr[:200]}"
                logger.error(result.error_message)

        except Exception as e:
            result.error_message = str(e)
            logger.error(f"Fallback ducking failed: {e}")

        return result

    def mix_audio_tracks(
        self,
        tracks: List[Dict[str, Any]],
        output_path: str,
        total_duration_sec: Optional[float] = None,
    ) -> bool:
        """
        Mix multiple audio tracks into a single file.

        Args:
            tracks: List of dicts with 'path', 'start_sec', 'volume' (0-1)
            output_path: Output file path
            total_duration_sec: Optional total duration

        Returns:
            True if successful
        """
        if not self._ffmpeg_available:
            logger.error("ffmpeg not available")
            return False

        if not tracks:
            logger.error("No tracks to mix")
            return False

        try:
            # Build ffmpeg filter for mixing
            inputs = []
            filter_parts = []
            mix_inputs = []

            for i, track in enumerate(tracks):
                path = track.get("path")
                start_sec = track.get("start_sec", 0)
                volume = track.get("volume", 1.0)

                if not path or not Path(path).exists():
                    logger.warning(f"Track not found: {path}")
                    continue

                inputs.extend(["-i", path])

                # Delay and volume adjust
                delay_ms = int(start_sec * 1000)
                filter_parts.append(
                    f"[{i}:a]adelay={delay_ms}|{delay_ms},volume={volume}[a{i}]"
                )
                mix_inputs.append(f"[a{i}]")

            if not mix_inputs:
                logger.error("No valid tracks to mix")
                return False

            # Combine all tracks
            filter_complex = ";".join(filter_parts)
            filter_complex += f";{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=longest[out]"

            cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-c:a", "pcm_s16le",
                output_path,
            ]

            if total_duration_sec:
                cmd.extend(["-t", str(total_duration_sec)])

            proc = subprocess.run(cmd, capture_output=True, timeout=300)
            return proc.returncode == 0

        except Exception as e:
            logger.error(f"Audio mixing failed: {e}")
            return False


def create_ducked_music(
    music_path: str,
    voice_path: str,
    output_path: Optional[str] = None,
    ducking_db: float = -12.0,
    voice_start_sec: float = 0.0,
    work_dir: Optional[Path] = None,
) -> Optional[str]:
    """
    Convenience function to create ducked music.

    Args:
        music_path: Path to music file
        voice_path: Path to voiceover file
        output_path: Output path (default: work/audio/music_ducked.wav)
        ducking_db: Amount to reduce music in dB
        voice_start_sec: Delay before voice starts
        work_dir: Working directory

    Returns:
        Path to ducked audio file, or None if failed
    """
    processor = AudioProcessor(work_dir=work_dir)

    config = DuckingConfig(
        ducking_db=ducking_db,
        voice_start_sec=voice_start_sec,
    )

    result = processor.create_ducked_music(
        music_path=music_path,
        voice_path=voice_path,
        output_path=output_path,
        config=config,
    )

    if result.success:
        return result.output_path
    return None
