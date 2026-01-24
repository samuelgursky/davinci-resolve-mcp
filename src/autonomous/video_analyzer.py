"""
Video Analyzer - Scene detection, motion analysis, and transcription.

Milestone 3 implementation.

Optional dependencies:
- scenedetect: For scene boundary detection (falls back to simple segmentation)
- opencv-python (cv2): For motion analysis (falls back to length-based proxy)
- faster-whisper: For transcription (only used if explicitly enabled)
"""

import logging
import subprocess
import tempfile
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import json

logger = logging.getLogger("autonomous.video_analyzer")


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class SceneInfo:
    """Information about a detected scene segment."""
    index: int
    start_sec: float
    end_sec: float
    duration_sec: float
    motion_score: Optional[float] = None  # 0-1 scale, None if unavailable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "start_sec": round(self.start_sec, 3),
            "end_sec": round(self.end_sec, 3),
            "duration_sec": round(self.duration_sec, 3),
            "motion_score": round(self.motion_score, 3) if self.motion_score is not None else None,
        }


@dataclass
class ClipAnalysis:
    """Complete analysis result for a single video clip."""

    # Source identification
    clip_name: str
    file_path: Optional[str] = None

    # Basic metadata
    duration_sec: float = 0.0
    fps: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None

    # Audio detection
    has_audio: bool = False

    # Scene breakdown
    scenes: List[SceneInfo] = field(default_factory=list)

    # Optional transcription (only if enabled)
    transcript: Optional[str] = None

    # Analysis metadata
    analysis_method: str = "fallback"  # "scenedetect" or "fallback"
    motion_method: str = "unavailable"  # "opencv", "fallback", or "unavailable"
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "clip_name": self.clip_name,
            "file_path": self.file_path,
            "duration_sec": round(self.duration_sec, 3) if self.duration_sec else 0.0,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "has_audio": self.has_audio,
            "scenes": [s.to_dict() for s in self.scenes],
            "analysis_method": self.analysis_method,
            "motion_method": self.motion_method,
        }
        # Only include transcript if present
        if self.transcript is not None:
            d["transcript"] = self.transcript
        if self.warnings:
            d["warnings"] = self.warnings
        return d


@dataclass
class CandidatesReport:
    """Full candidates.json structure."""
    clips: List[ClipAnalysis] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clips": [c.to_dict() for c in self.clips],
            "summary": self.summary,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        logger.info(f"Saved candidates to: {path}")


# ============================================================================
# Video Analyzer
# ============================================================================

class VideoAnalyzer:
    """
    Analyzes video clips for scene detection, motion, and audio.

    Gracefully handles missing dependencies with fallbacks.
    """

    # Default scene segment length for fallback (seconds)
    DEFAULT_SEGMENT_LENGTH = 3.0

    def __init__(
        self,
        enable_transcription: bool = False,
        work_dir: Optional[Path] = None,
    ):
        self.enable_transcription = enable_transcription
        self.work_dir = Path(work_dir) if work_dir else Path("work/analysis")
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Check dependencies
        self._cv2_available = self._check_opencv()
        self._scenedetect_available = self._check_scenedetect()
        self._whisper_available = self._check_whisper()
        self._ffprobe_available = self._check_ffprobe()

        # Validate transcription request
        if enable_transcription and not self._whisper_available:
            raise ImportError(
                "Transcription enabled but faster-whisper is not installed.\n"
                "Install it with: pip install faster-whisper\n"
                "Or disable transcription: enable_transcription=False"
            )

    def _check_opencv(self) -> bool:
        """Check if OpenCV is available."""
        try:
            import cv2
            logger.debug(f"OpenCV available: {cv2.__version__}")
            return True
        except ImportError:
            logger.debug("OpenCV not installed - motion analysis will use fallback")
            return False

    def _check_scenedetect(self) -> bool:
        """Check if PySceneDetect is available."""
        try:
            from scenedetect import detect, ContentDetector
            logger.debug("PySceneDetect available")
            return True
        except ImportError:
            logger.debug("PySceneDetect not installed - using simple segmentation")
            return False

    def _check_whisper(self) -> bool:
        """Check if faster-whisper is available."""
        try:
            from faster_whisper import WhisperModel
            logger.debug("faster-whisper available")
            return True
        except ImportError:
            logger.debug("faster-whisper not installed")
            return False

    def _check_ffprobe(self) -> bool:
        """Check if ffprobe is available for metadata extraction."""
        try:
            result = subprocess.run(
                ["ffprobe", "-version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.debug("ffprobe not available - using fallback metadata extraction")
            return False

    # ========================================================================
    # Metadata Extraction
    # ========================================================================

    def _get_video_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        Extract video metadata (duration, fps, resolution, has_audio).

        Tries ffprobe first, then OpenCV as fallback.
        """
        metadata = {
            "duration_sec": 0.0,
            "fps": None,
            "width": None,
            "height": None,
            "has_audio": False,
        }

        if self._ffprobe_available:
            metadata = self._get_metadata_ffprobe(file_path, metadata)
        elif self._cv2_available:
            metadata = self._get_metadata_opencv(file_path, metadata)
        else:
            logger.warning(f"No metadata extraction available for: {file_path}")

        return metadata

    def _get_metadata_ffprobe(self, file_path: str, metadata: Dict) -> Dict[str, Any]:
        """Extract metadata using ffprobe."""
        try:
            # Get video stream info
            cmd = [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                data = json.loads(result.stdout)

                # Duration from format
                if "format" in data:
                    duration = data["format"].get("duration")
                    if duration:
                        metadata["duration_sec"] = float(duration)

                # Find video and audio streams
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        metadata["width"] = stream.get("width")
                        metadata["height"] = stream.get("height")

                        # Parse fps from r_frame_rate (e.g., "24000/1001")
                        fps_str = stream.get("r_frame_rate", "")
                        if "/" in fps_str:
                            num, den = fps_str.split("/")
                            if float(den) > 0:
                                metadata["fps"] = round(float(num) / float(den), 3)
                        elif fps_str:
                            metadata["fps"] = float(fps_str)

                    elif stream.get("codec_type") == "audio":
                        metadata["has_audio"] = True

        except (subprocess.SubprocessError, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"ffprobe metadata extraction failed: {e}")

        return metadata

    def _get_metadata_opencv(self, file_path: str, metadata: Dict) -> Dict[str, Any]:
        """Extract metadata using OpenCV."""
        try:
            import cv2
            cap = cv2.VideoCapture(file_path)

            if cap.isOpened():
                metadata["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                metadata["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                metadata["fps"] = cap.get(cv2.CAP_PROP_FPS)

                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if metadata["fps"] and metadata["fps"] > 0:
                    metadata["duration_sec"] = frame_count / metadata["fps"]

            cap.release()
        except Exception as e:
            logger.warning(f"OpenCV metadata extraction failed: {e}")

        return metadata

    # ========================================================================
    # Scene Detection
    # ========================================================================

    def _detect_scenes(self, file_path: str, duration_sec: float) -> Tuple[List[Tuple[float, float]], str]:
        """
        Detect scene boundaries in a video.

        Returns:
            Tuple of (list of (start_sec, end_sec) tuples, method_used)
        """
        if self._scenedetect_available:
            scenes = self._detect_scenes_pyscenedetect(file_path, duration_sec)
            if scenes:
                return scenes, "scenedetect"

        # Fallback: simple fixed-length segmentation
        return self._segment_by_duration(duration_sec), "fallback"

    def _detect_scenes_pyscenedetect(
        self,
        file_path: str,
        duration_sec: float,
    ) -> List[Tuple[float, float]]:
        """Detect scenes using PySceneDetect."""
        try:
            from scenedetect import detect, ContentDetector

            # Detect scene boundaries
            scene_list = detect(file_path, ContentDetector(threshold=27.0))

            if not scene_list:
                # No cuts detected - treat entire video as one scene
                return [(0.0, duration_sec)]

            scenes = []
            for scene in scene_list:
                start_sec = scene[0].get_seconds()
                end_sec = scene[1].get_seconds()
                scenes.append((start_sec, end_sec))

            return scenes

        except Exception as e:
            logger.warning(f"PySceneDetect failed: {e}")
            return []

    def _segment_by_duration(
        self,
        duration_sec: float,
        segment_length: float = None,
    ) -> List[Tuple[float, float]]:
        """
        Simple fallback: divide video into fixed-length segments.
        """
        segment_length = segment_length or self.DEFAULT_SEGMENT_LENGTH

        if duration_sec <= 0:
            return [(0.0, 0.0)]

        scenes = []
        current = 0.0
        while current < duration_sec:
            end = min(current + segment_length, duration_sec)
            scenes.append((current, end))
            current = end

        return scenes

    # ========================================================================
    # Motion Analysis
    # ========================================================================

    def _compute_motion_scores(
        self,
        file_path: str,
        scenes: List[Tuple[float, float]],
        fps: Optional[float],
    ) -> Tuple[List[Optional[float]], str]:
        """
        Compute motion score for each scene segment.

        Returns:
            Tuple of (list of motion scores, method_used)
        """
        if self._cv2_available and fps and fps > 0:
            scores = self._compute_motion_opencv(file_path, scenes, fps)
            if scores and any(s is not None for s in scores):
                return scores, "opencv"

        # Fallback: use scene duration as proxy (longer = potentially lower motion)
        return self._compute_motion_fallback(scenes), "fallback"

    def _compute_motion_opencv(
        self,
        file_path: str,
        scenes: List[Tuple[float, float]],
        fps: float,
        sample_interval: int = 5,  # Sample every N frames
    ) -> List[Optional[float]]:
        """
        Compute motion score using frame differencing.

        Motion score is normalized average frame difference (0-1 scale).
        """
        try:
            import cv2
            import numpy as np

            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return [None] * len(scenes)

            scores = []

            for start_sec, end_sec in scenes:
                start_frame = int(start_sec * fps)
                end_frame = int(end_sec * fps)

                # Skip to start frame
                cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

                frame_diffs = []
                prev_gray = None
                frame_idx = start_frame

                while frame_idx < end_frame:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    # Convert to grayscale and resize for speed
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    gray = cv2.resize(gray, (160, 90))  # Small size for speed

                    if prev_gray is not None:
                        # Compute absolute difference
                        diff = cv2.absdiff(gray, prev_gray)
                        mean_diff = np.mean(diff) / 255.0  # Normalize to 0-1
                        frame_diffs.append(mean_diff)

                    prev_gray = gray
                    frame_idx += sample_interval

                    # Skip frames for sampling
                    if sample_interval > 1:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)

                # Compute average motion for this scene
                if frame_diffs:
                    # Scale up since typical motion values are small
                    avg_motion = min(1.0, np.mean(frame_diffs) * 10)
                    scores.append(avg_motion)
                else:
                    scores.append(None)

            cap.release()
            return scores

        except Exception as e:
            logger.warning(f"OpenCV motion analysis failed: {e}")
            return [None] * len(scenes)

    def _compute_motion_fallback(
        self,
        scenes: List[Tuple[float, float]],
    ) -> List[Optional[float]]:
        """
        Fallback motion proxy: return None with warning.
        """
        logger.warning("Motion analysis unavailable - install opencv-python for motion scores")
        return [None] * len(scenes)

    # ========================================================================
    # Transcription
    # ========================================================================

    def _transcribe_audio(self, file_path: str) -> Optional[str]:
        """
        Transcribe audio from video using faster-whisper.
        """
        if not self.enable_transcription:
            return None

        if not self._whisper_available:
            return None

        try:
            from faster_whisper import WhisperModel

            # Extract audio to temp file (faster-whisper needs audio file)
            audio_path = self._extract_audio(file_path)
            if not audio_path:
                return None

            # Load model (base is a good balance of speed/accuracy)
            model = WhisperModel("base", device="cpu", compute_type="int8")

            # Transcribe
            segments, info = model.transcribe(audio_path, beam_size=5)

            # Combine segments into full transcript
            transcript_parts = []
            for segment in segments:
                transcript_parts.append(segment.text.strip())

            # Cleanup temp audio
            try:
                os.remove(audio_path)
            except:
                pass

            return " ".join(transcript_parts) if transcript_parts else None

        except Exception as e:
            logger.warning(f"Transcription failed: {e}")
            return None

    def _extract_audio(self, video_path: str) -> Optional[str]:
        """Extract audio track to temp WAV file."""
        if not self._ffprobe_available:
            # ffmpeg is usually installed alongside ffprobe
            return None

        try:
            temp_audio = tempfile.NamedTemporaryFile(
                suffix=".wav",
                dir=str(self.work_dir),
                delete=False,
            )
            temp_audio.close()

            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vn", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1",
                temp_audio.name
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=120,
            )

            if result.returncode == 0 and os.path.exists(temp_audio.name):
                return temp_audio.name
            else:
                return None

        except Exception as e:
            logger.warning(f"Audio extraction failed: {e}")
            return None

    # ========================================================================
    # Main Analysis
    # ========================================================================

    def analyze_clip(self, clip_name: str, file_path: str) -> ClipAnalysis:
        """
        Analyze a single video clip.

        Args:
            clip_name: Display name for the clip
            file_path: Path to the video file

        Returns:
            ClipAnalysis with scene and motion data
        """
        logger.info(f"Analyzing: {clip_name}")

        result = ClipAnalysis(
            clip_name=clip_name,
            file_path=file_path,
        )

        # Check file exists
        if not file_path or not os.path.exists(file_path):
            result.warnings.append(f"File not found: {file_path}")
            logger.warning(f"File not found: {file_path}")
            return result

        # Extract metadata
        metadata = self._get_video_metadata(file_path)
        result.duration_sec = metadata["duration_sec"]
        result.fps = metadata["fps"]
        result.width = metadata["width"]
        result.height = metadata["height"]
        result.has_audio = metadata["has_audio"]

        if result.duration_sec <= 0:
            result.warnings.append("Could not determine video duration")
            return result

        # Detect scenes
        scene_bounds, scene_method = self._detect_scenes(file_path, result.duration_sec)
        result.analysis_method = scene_method

        # Compute motion scores
        motion_scores, motion_method = self._compute_motion_scores(
            file_path, scene_bounds, result.fps
        )
        result.motion_method = motion_method

        # Build scene info list
        for i, ((start, end), motion) in enumerate(zip(scene_bounds, motion_scores)):
            scene = SceneInfo(
                index=i,
                start_sec=start,
                end_sec=end,
                duration_sec=end - start,
                motion_score=motion,
            )
            result.scenes.append(scene)

        # Transcription (if enabled and has audio)
        if self.enable_transcription and result.has_audio:
            result.transcript = self._transcribe_audio(file_path)

        logger.info(
            f"  -> {len(result.scenes)} scenes, "
            f"duration={result.duration_sec:.1f}s, "
            f"has_audio={result.has_audio}, "
            f"method={scene_method}/{motion_method}"
        )

        return result

    def analyze_clips(
        self,
        clips: List[Dict[str, Any]],
    ) -> CandidatesReport:
        """
        Analyze multiple clips and generate candidates report.

        Args:
            clips: List of dicts with 'name' and 'file_path' keys

        Returns:
            CandidatesReport ready to save
        """
        report = CandidatesReport()

        for clip_info in clips:
            name = clip_info.get("name", "unknown")
            path = clip_info.get("file_path") or clip_info.get("source_path")

            analysis = self.analyze_clip(name, path)
            report.clips.append(analysis)

        # Build summary
        total_duration = sum(c.duration_sec for c in report.clips)
        clips_with_audio = sum(1 for c in report.clips if c.has_audio)
        total_scenes = sum(len(c.scenes) for c in report.clips)

        # Average motion (excluding None values)
        motion_values = [
            s.motion_score
            for c in report.clips
            for s in c.scenes
            if s.motion_score is not None
        ]
        avg_motion = sum(motion_values) / len(motion_values) if motion_values else None

        report.summary = {
            "total_clips": len(report.clips),
            "total_duration_sec": round(total_duration, 2),
            "total_scenes": total_scenes,
            "clips_with_audio": clips_with_audio,
            "average_motion_score": round(avg_motion, 3) if avg_motion is not None else None,
            "analysis_methods_used": list(set(c.analysis_method for c in report.clips)),
            "motion_methods_used": list(set(c.motion_method for c in report.clips)),
        }

        return report


# ============================================================================
# Convenience function
# ============================================================================

def analyze_media_pool_clips(
    clips: List[Dict[str, Any]],
    output_path: Path,
    enable_transcription: bool = False,
    work_dir: Optional[Path] = None,
) -> CandidatesReport:
    """
    Convenience function to analyze clips and save candidates.json.

    Args:
        clips: List of clip info dicts from media pool
        output_path: Where to save candidates.json
        enable_transcription: Whether to transcribe audio
        work_dir: Working directory for intermediate files

    Returns:
        CandidatesReport
    """
    analyzer = VideoAnalyzer(
        enable_transcription=enable_transcription,
        work_dir=work_dir,
    )

    report = analyzer.analyze_clips(clips)
    report.save(output_path)

    return report
