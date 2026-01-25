#!/usr/bin/env python3
"""
Scene Detection Module for DaVinci Resolve MCP Server

Uses PySceneDetect to detect scene boundaries in video files.
Can add markers at scene changes or split videos automatically.

Install: pip install scenedetect[opencv]
"""

import logging
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("autonomous.scene_detector")

# Check for scenedetect availability
_SCENEDETECT_AVAILABLE = False
try:
    from scenedetect import detect, AdaptiveDetector, ContentDetector, ThresholdDetector
    from scenedetect.scene_manager import SceneManager
    from scenedetect.video_splitter import split_video_ffmpeg
    _SCENEDETECT_AVAILABLE = True
    logger.debug("PySceneDetect available")
except ImportError:
    logger.debug("PySceneDetect not installed - scene detection disabled")


def is_scenedetect_available() -> bool:
    """Check if PySceneDetect is available."""
    return _SCENEDETECT_AVAILABLE


@dataclass
class SceneInfo:
    """Information about a detected scene."""
    index: int
    start_time: float  # seconds
    end_time: float    # seconds
    start_frame: int
    end_frame: int
    duration: float    # seconds
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'start_time': round(self.start_time, 3),
            'end_time': round(self.end_time, 3),
            'start_frame': self.start_frame,
            'end_frame': self.end_frame,
            'duration': round(self.duration, 3)
        }


@dataclass
class SceneAnalysis:
    """Result of scene detection analysis."""
    file_path: str
    total_scenes: int
    video_duration: float
    fps: float
    scenes: List[SceneInfo] = field(default_factory=list)
    detection_method: str = "adaptive"
    analyzed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'file_path': self.file_path,
            'total_scenes': self.total_scenes,
            'video_duration': round(self.video_duration, 3),
            'fps': self.fps,
            'scenes': [s.to_dict() for s in self.scenes],
            'detection_method': self.detection_method,
            'analyzed_at': self.analyzed_at
        }
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
    
    def save(self, path: Path) -> None:
        """Save scene analysis to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())
        logger.info(f"Saved scene analysis to: {path}")


class SceneDetector:
    """
    Detects scene changes in video files using PySceneDetect.
    """
    
    def __init__(
        self,
        method: str = "adaptive",
        threshold: float = None,
        min_scene_len: int = 15  # minimum frames per scene
    ):
        """
        Initialize the scene detector.
        
        Args:
            method: Detection method - 'adaptive', 'content', or 'threshold'
            threshold: Detection sensitivity (method-specific)
            min_scene_len: Minimum scene length in frames
        """
        self.method = method
        self.threshold = threshold
        self.min_scene_len = min_scene_len
        
        if not _SCENEDETECT_AVAILABLE:
            logger.warning(
                "PySceneDetect not installed - scene detection unavailable. "
                "Install with: pip install scenedetect[opencv]"
            )
    
    def analyze(self, video_path: str) -> Optional[SceneAnalysis]:
        """
        Analyze a video file for scene changes.
        
        Args:
            video_path: Path to video file
            
        Returns:
            SceneAnalysis with detected scenes, or None if unavailable
        """
        if not _SCENEDETECT_AVAILABLE:
            logger.warning("Cannot analyze scenes - PySceneDetect not installed")
            return None
        
        video_path = str(video_path)
        
        if not Path(video_path).exists():
            logger.error(f"Video file not found: {video_path}")
            return None
        
        try:
            logger.info(f"Analyzing scenes: {video_path} (method: {self.method})")
            
            # Select detector based on method
            if self.method == "adaptive":
                detector = AdaptiveDetector(
                    adaptive_threshold=self.threshold or 3.0,
                    min_scene_len=self.min_scene_len
                )
            elif self.method == "content":
                detector = ContentDetector(
                    threshold=self.threshold or 27.0,
                    min_scene_len=self.min_scene_len
                )
            elif self.method == "threshold":
                detector = ThresholdDetector(
                    threshold=self.threshold or 12.0,
                    min_scene_len=self.min_scene_len
                )
            else:
                detector = AdaptiveDetector(min_scene_len=self.min_scene_len)
            
            # Detect scenes
            scene_list = detect(video_path, detector)
            
            if not scene_list:
                logger.info(f"No scene changes detected in: {video_path}")
                return SceneAnalysis(
                    file_path=video_path,
                    total_scenes=1,
                    video_duration=0,
                    fps=24,
                    scenes=[],
                    detection_method=self.method
                )
            
            # Get video info from first scene
            fps = scene_list[0][0].get_framerate()
            
            # Convert to SceneInfo objects
            scenes = []
            for i, (start, end) in enumerate(scene_list):
                scene = SceneInfo(
                    index=i + 1,
                    start_time=start.get_seconds(),
                    end_time=end.get_seconds(),
                    start_frame=start.get_frames(),
                    end_frame=end.get_frames(),
                    duration=end.get_seconds() - start.get_seconds()
                )
                scenes.append(scene)
            
            # Calculate total duration
            total_duration = scenes[-1].end_time if scenes else 0
            
            result = SceneAnalysis(
                file_path=video_path,
                total_scenes=len(scenes),
                video_duration=total_duration,
                fps=fps,
                scenes=scenes,
                detection_method=self.method
            )
            
            logger.info(
                f"Scene analysis complete: {len(scenes)} scenes detected, "
                f"{total_duration:.1f}s duration"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Scene analysis failed: {e}")
            return None
    
    def get_scene_timestamps(self, video_path: str) -> List[float]:
        """
        Get just the timestamps (in seconds) where scenes start.
        
        Args:
            video_path: Path to video file
            
        Returns:
            List of scene start times in seconds
        """
        analysis = self.analyze(video_path)
        if analysis is None:
            return []
        
        return [scene.start_time for scene in analysis.scenes]
    
    def get_scene_frames(self, video_path: str, fps: float = 24.0) -> List[int]:
        """
        Get frame numbers where scenes start.
        
        Args:
            video_path: Path to video file
            fps: Frames per second (for conversion if needed)
            
        Returns:
            List of scene start frame numbers
        """
        analysis = self.analyze(video_path)
        if analysis is None:
            return []
        
        return [scene.start_frame for scene in analysis.scenes]


def analyze_video_scenes(
    video_path: str,
    method: str = "adaptive",
    threshold: float = None,
    output_path: Optional[Path] = None
) -> Optional[SceneAnalysis]:
    """
    Convenience function to analyze video scenes.
    
    Args:
        video_path: Path to video file
        method: Detection method ('adaptive', 'content', 'threshold')
        threshold: Detection sensitivity
        output_path: Optional path to save results JSON
        
    Returns:
        SceneAnalysis or None if analysis unavailable
    """
    detector = SceneDetector(method=method, threshold=threshold)
    result = detector.analyze(video_path)
    
    if result and output_path:
        result.save(output_path)
    
    return result
