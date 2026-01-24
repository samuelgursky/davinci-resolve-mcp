"""
Decision Engine - Intelligent scene selection and edit plan generation.

Milestone 7 implementation.

Turns candidates.json analysis into an EditPlan with scene-level subclips.
Uses deterministic heuristics (no LLM required):
- Structure buckets (hook/build/peak/outro)
- Motion score diversity
- Target duration constraints
- Beat snapping integration
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from .schemas import EditPlan, ClipReference, TimelineSettings, TrackType
from .beat_analyzer import BeatAnalysis, snap_clip_boundaries

logger = logging.getLogger("autonomous.decision_engine")


@dataclass
class SceneCandidate:
    """A scene candidate for selection."""

    clip_name: str
    clip_path: Optional[str]
    scene_index: int

    start_sec: float
    end_sec: float
    duration_sec: float

    motion_score: Optional[float]

    # Selection metadata
    bucket: str = ""  # hook, build, peak, outro
    selected: bool = False
    priority_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_name": self.clip_name,
            "scene_index": self.scene_index,
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "duration_sec": self.duration_sec,
            "motion_score": self.motion_score,
            "bucket": self.bucket,
            "selected": self.selected,
            "priority_score": self.priority_score,
        }


@dataclass
class VariantConfig:
    """Configuration for an edit variant."""

    name: str
    target_duration_sec: float

    # Pacing
    pacing: str = "balanced"  # slow, balanced, fast

    # Scene duration constraints
    min_scene_duration_sec: float = 1.0
    max_scene_duration_sec: float = 8.0

    # Structure weights (how much of total duration for each bucket)
    hook_weight: float = 0.20   # 0-20%
    build_weight: float = 0.40  # 20-60%
    peak_weight: float = 0.25   # 60-85%
    outro_weight: float = 0.15  # 85-100%

    # Motion preferences by bucket
    hook_motion: str = "medium"   # low, medium, high, any
    build_motion: str = "rising"  # low, medium, high, rising, any
    peak_motion: str = "high"
    outro_motion: str = "low"

    # Beat sync
    beat_sync_enabled: bool = True
    beat_snap_tolerance_sec: float = 0.10
    beat_prefer_downbeats: bool = False

    @classmethod
    def trailer(cls, target_duration_sec: float = 30.0) -> "VariantConfig":
        """Fast-paced trailer variant."""
        return cls(
            name="trailer",
            target_duration_sec=target_duration_sec,
            pacing="fast",
            min_scene_duration_sec=0.5,
            max_scene_duration_sec=4.0,
            hook_weight=0.15,
            build_weight=0.35,
            peak_weight=0.35,
            outro_weight=0.15,
            hook_motion="high",
            build_motion="rising",
            peak_motion="high",
            outro_motion="medium",
        )

    @classmethod
    def balanced(cls, target_duration_sec: float = 60.0) -> "VariantConfig":
        """Balanced cinematic variant."""
        return cls(
            name="balanced",
            target_duration_sec=target_duration_sec,
            pacing="balanced",
            min_scene_duration_sec=1.5,
            max_scene_duration_sec=6.0,
            hook_weight=0.20,
            build_weight=0.40,
            peak_weight=0.25,
            outro_weight=0.15,
            hook_motion="medium",
            build_motion="rising",
            peak_motion="high",
            outro_motion="low",
        )

    @classmethod
    def atmospheric(cls, target_duration_sec: float = 90.0) -> "VariantConfig":
        """Slow atmospheric variant."""
        return cls(
            name="atmo",
            target_duration_sec=target_duration_sec,
            pacing="slow",
            min_scene_duration_sec=2.0,
            max_scene_duration_sec=10.0,
            hook_weight=0.25,
            build_weight=0.35,
            peak_weight=0.20,
            outro_weight=0.20,
            hook_motion="low",
            build_motion="any",
            peak_motion="medium",
            outro_motion="low",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "target_duration_sec": self.target_duration_sec,
            "pacing": self.pacing,
            "min_scene_duration_sec": self.min_scene_duration_sec,
            "max_scene_duration_sec": self.max_scene_duration_sec,
            "structure_weights": {
                "hook": self.hook_weight,
                "build": self.build_weight,
                "peak": self.peak_weight,
                "outro": self.outro_weight,
            },
            "beat_sync": {
                "enabled": self.beat_sync_enabled,
                "snap_tolerance_sec": self.beat_snap_tolerance_sec,
                "prefer_downbeats": self.beat_prefer_downbeats,
            },
        }


class DecisionEngine:
    """
    Generates edit plans from video analysis using deterministic heuristics.

    Selection strategy:
    1. Categorize scenes into structure buckets (hook/build/peak/outro)
    2. Score scenes by motion and diversity
    3. Select scenes to fill target duration
    4. Apply beat snapping if music is provided
    """

    def __init__(self, work_dir: Optional[Path] = None):
        self.work_dir = Path(work_dir) if work_dir else Path("work")

    def load_candidates(self, path: Optional[Path] = None) -> Dict[str, Any]:
        """Load candidates.json analysis data."""
        if path is None:
            path = self.work_dir / "analysis" / "candidates.json"

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Candidates not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_beats(self, path: Optional[Path] = None) -> Optional[BeatAnalysis]:
        """Load beats.json if available."""
        if path is None:
            path = self.work_dir / "audio" / "beats.json"

        path = Path(path)
        if not path.exists():
            return None

        try:
            return BeatAnalysis.load(path)
        except Exception as e:
            logger.warning(f"Could not load beats: {e}")
            return None

    def extract_scenes(self, candidates: Dict[str, Any]) -> List[SceneCandidate]:
        """Extract all scenes from candidates into a flat list."""
        scenes = []

        for clip in candidates.get("clips", []):
            clip_name = clip.get("clip_name", "unknown")
            clip_path = clip.get("file_path")

            for scene in clip.get("scenes", []):
                # Skip very short scenes (likely artifacts)
                duration = scene.get("duration_sec", 0)
                if duration < 0.5:
                    continue

                scenes.append(SceneCandidate(
                    clip_name=clip_name,
                    clip_path=clip_path,
                    scene_index=scene.get("index", 0),
                    start_sec=scene.get("start_sec", 0),
                    end_sec=scene.get("end_sec", 0),
                    duration_sec=duration,
                    motion_score=scene.get("motion_score"),
                ))

        return scenes

    def categorize_by_motion(
        self,
        scenes: List[SceneCandidate],
    ) -> Dict[str, List[SceneCandidate]]:
        """Categorize scenes by motion level."""
        categories = {
            "low": [],
            "medium": [],
            "high": [],
        }

        for scene in scenes:
            if scene.motion_score is None:
                categories["medium"].append(scene)
            elif scene.motion_score < 0.35:
                categories["low"].append(scene)
            elif scene.motion_score < 0.6:
                categories["medium"].append(scene)
            else:
                categories["high"].append(scene)

        return categories

    def select_scenes_for_bucket(
        self,
        scenes: List[SceneCandidate],
        motion_categories: Dict[str, List[SceneCandidate]],
        bucket: str,
        target_duration: float,
        motion_pref: str,
        min_scene_dur: float,
        max_scene_dur: float,
        used_scenes: set,
    ) -> List[SceneCandidate]:
        """
        Select scenes for a structure bucket.

        Args:
            scenes: All available scenes
            motion_categories: Scenes categorized by motion
            bucket: Bucket name (hook/build/peak/outro)
            target_duration: Target duration for this bucket
            motion_pref: Motion preference (low/medium/high/rising/any)
            min_scene_dur: Minimum scene duration
            max_scene_dur: Maximum scene duration
            used_scenes: Set of already used scene IDs

        Returns:
            List of selected scenes
        """
        selected = []
        current_duration = 0.0

        # Determine which motion categories to prioritize
        if motion_pref == "low":
            priority_order = ["low", "medium", "high"]
        elif motion_pref == "high":
            priority_order = ["high", "medium", "low"]
        elif motion_pref == "rising":
            # For build sections, want variety
            priority_order = ["medium", "low", "high"]
        else:  # medium or any
            priority_order = ["medium", "low", "high"]

        # Get candidate pool
        pool = []
        for cat in priority_order:
            for scene in motion_categories.get(cat, []):
                scene_id = f"{scene.clip_name}_{scene.scene_index}"
                if scene_id not in used_scenes:
                    if min_scene_dur <= scene.duration_sec <= max_scene_dur:
                        pool.append(scene)

        # Sort by motion score (descending for high pref, ascending for low)
        if motion_pref == "high":
            pool.sort(key=lambda s: s.motion_score or 0.5, reverse=True)
        elif motion_pref == "low":
            pool.sort(key=lambda s: s.motion_score or 0.5)
        # For rising/balanced, keep some diversity
        else:
            # Interleave low and high motion
            pool.sort(key=lambda s: abs((s.motion_score or 0.5) - 0.5))

        # Select scenes until we hit target duration
        for scene in pool:
            if current_duration >= target_duration:
                break

            scene_id = f"{scene.clip_name}_{scene.scene_index}"
            if scene_id in used_scenes:
                continue

            # Check if adding this scene would exceed target too much
            if current_duration + scene.duration_sec > target_duration * 1.3:
                # Try to find a shorter scene
                continue

            scene.bucket = bucket
            scene.selected = True
            selected.append(scene)
            used_scenes.add(scene_id)
            current_duration += scene.duration_sec

        return selected

    def generate_plan(
        self,
        candidates: Dict[str, Any],
        config: VariantConfig,
        beats: Optional[BeatAnalysis] = None,
        timeline_name: Optional[str] = None,
    ) -> EditPlan:
        """
        Generate an edit plan from candidates.

        Args:
            candidates: Loaded candidates.json data
            config: Variant configuration
            beats: Optional beat analysis for snapping
            timeline_name: Optional timeline name override

        Returns:
            EditPlan with selected clips
        """
        logger.info(f"Generating plan: {config.name}, target={config.target_duration_sec}s")

        # Extract all scenes
        all_scenes = self.extract_scenes(candidates)
        if not all_scenes:
            logger.warning("No scenes found in candidates")
            return self._create_empty_plan(config, timeline_name)

        # Categorize by motion
        motion_cats = self.categorize_by_motion(all_scenes)
        logger.debug(
            f"Motion categories: low={len(motion_cats['low'])}, "
            f"medium={len(motion_cats['medium'])}, high={len(motion_cats['high'])}"
        )

        # Calculate bucket durations
        bucket_durations = {
            "hook": config.target_duration_sec * config.hook_weight,
            "build": config.target_duration_sec * config.build_weight,
            "peak": config.target_duration_sec * config.peak_weight,
            "outro": config.target_duration_sec * config.outro_weight,
        }

        bucket_motion_prefs = {
            "hook": config.hook_motion,
            "build": config.build_motion,
            "peak": config.peak_motion,
            "outro": config.outro_motion,
        }

        # Select scenes for each bucket
        used_scenes = set()
        selected_scenes = []

        for bucket in ["hook", "build", "peak", "outro"]:
            bucket_scenes = self.select_scenes_for_bucket(
                scenes=all_scenes,
                motion_categories=motion_cats,
                bucket=bucket,
                target_duration=bucket_durations[bucket],
                motion_pref=bucket_motion_prefs[bucket],
                min_scene_dur=config.min_scene_duration_sec,
                max_scene_dur=config.max_scene_duration_sec,
                used_scenes=used_scenes,
            )
            selected_scenes.extend(bucket_scenes)
            logger.debug(f"Bucket {bucket}: {len(bucket_scenes)} scenes")

        # Apply beat snapping if enabled
        if beats and config.beat_sync_enabled:
            selected_scenes = self._apply_beat_snapping(
                selected_scenes, beats, config
            )

        # Build edit plan
        plan = self._build_plan(selected_scenes, config, timeline_name)

        logger.info(
            f"Plan generated: {len(plan.clips)} clips, "
            f"total duration ~{sum(c.duration_frames or 0 for c in plan.clips) / 24:.1f}s"
        )

        return plan

    def _apply_beat_snapping(
        self,
        scenes: List[SceneCandidate],
        beats: BeatAnalysis,
        config: VariantConfig,
    ) -> List[SceneCandidate]:
        """Apply beat snapping to scene boundaries."""
        logger.debug("Applying beat snapping")

        for scene in scenes:
            snapped_in, snapped_out = snap_clip_boundaries(
                clip_in_sec=scene.start_sec,
                clip_out_sec=scene.end_sec,
                beats=beats,
                tolerance_sec=config.beat_snap_tolerance_sec,
                prefer_downbeats=config.beat_prefer_downbeats,
                min_duration_sec=config.min_scene_duration_sec,
            )

            # Update scene times
            scene.start_sec = snapped_in
            scene.end_sec = snapped_out
            scene.duration_sec = snapped_out - snapped_in

        return scenes

    def _build_plan(
        self,
        scenes: List[SceneCandidate],
        config: VariantConfig,
        timeline_name: Optional[str] = None,
    ) -> EditPlan:
        """Build an EditPlan from selected scenes."""
        plan = EditPlan(
            description=f"Auto-generated {config.name} variant",
            timeline=TimelineSettings(
                name=timeline_name or f"AUTO_{config.name.upper()}",
                fps="24",
                width=1920,
                height=1080,
            ),
        )

        # Add clips in order
        fps = 24.0
        for i, scene in enumerate(scenes):
            # Convert seconds to frames
            source_in = int(scene.start_sec * fps)
            source_out = int(scene.end_sec * fps)
            duration_frames = source_out - source_in

            clip = ClipReference(
                name=scene.clip_name,
                source_path=scene.clip_path,
                source_in=source_in,
                source_out=source_out,
                track=1,
                track_type=TrackType.VIDEO,
                order=i,
                duration_frames=duration_frames,
                fps=fps,
            )
            plan.clips.append(clip)

        return plan

    def _create_empty_plan(
        self,
        config: VariantConfig,
        timeline_name: Optional[str] = None,
    ) -> EditPlan:
        """Create an empty plan when no scenes available."""
        return EditPlan(
            description=f"Empty {config.name} variant - no scenes available",
            timeline=TimelineSettings(
                name=timeline_name or f"AUTO_{config.name.upper()}",
            ),
        )


def generate_edit_plan(
    candidates_path: Path,
    variant: str = "balanced",
    target_duration_sec: float = 60.0,
    beats_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    timeline_name: Optional[str] = None,
) -> EditPlan:
    """
    Convenience function to generate an edit plan.

    Args:
        candidates_path: Path to candidates.json
        variant: Variant type (trailer/balanced/atmo)
        target_duration_sec: Target duration
        beats_path: Optional path to beats.json
        output_path: Optional path to save plan
        timeline_name: Optional timeline name

    Returns:
        Generated EditPlan
    """
    engine = DecisionEngine(work_dir=candidates_path.parent.parent)

    # Load candidates
    candidates = engine.load_candidates(candidates_path)

    # Load beats if available
    beats = None
    if beats_path and beats_path.exists():
        beats = BeatAnalysis.load(beats_path)

    # Get variant config
    if variant == "trailer":
        config = VariantConfig.trailer(target_duration_sec)
    elif variant == "atmo" or variant == "atmospheric":
        config = VariantConfig.atmospheric(target_duration_sec)
    else:
        config = VariantConfig.balanced(target_duration_sec)

    # Override timeline name
    if timeline_name:
        config.name = timeline_name

    # Generate plan
    plan = engine.generate_plan(candidates, config, beats, timeline_name)

    # Save if path provided
    if output_path:
        plan.save(output_path)
        logger.info(f"Saved plan to: {output_path}")

    return plan
