"""
Unit tests for Milestones 5-8.

Tests run WITHOUT Resolve and WITHOUT optional dependencies (librosa).
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Import modules under test
from autonomous.beat_analyzer import (
    BeatAnalysis,
    snap_to_beat,
    snap_clip_boundaries,
    is_librosa_available,
)
from autonomous.audio_processor import (
    DuckingConfig,
    DuckingResult,
    AudioProcessor,
    is_ffmpeg_available,
)
from autonomous.decision_engine import (
    DecisionEngine,
    VariantConfig,
    SceneCandidate,
)
from autonomous.cinematic_pipeline import (
    CinematicPipeline,
    VariantOutput,
    PipelineResult,
)


# ============================================================================
# Milestone 5: Beat Analyzer Tests
# ============================================================================

class TestBeatAnalysis:
    """Tests for BeatAnalysis data class."""

    def test_create_beat_analysis(self):
        """Test creating a BeatAnalysis."""
        beats = BeatAnalysis(
            file_path="/test/music.wav",
            duration_sec=60.0,
            bpm=120.0,
            beats_sec=[0.5, 1.0, 1.5, 2.0, 2.5],
        )
        assert beats.bpm == 120.0
        assert len(beats.beats_sec) == 5
        assert beats.duration_sec == 60.0

    def test_to_dict(self):
        """Test serialization."""
        beats = BeatAnalysis(
            file_path="/test/music.wav",
            duration_sec=30.0,
            bpm=90.0,
            beats_sec=[0.0, 0.667, 1.333, 2.0],
            downbeats_sec=[0.0, 2.0],
        )
        d = beats.to_dict()
        assert d["bpm"] == 90.0
        assert d["beat_count"] == 4
        assert d["downbeat_count"] == 2

    def test_save_and_load(self):
        """Test saving and loading beats.json."""
        beats = BeatAnalysis(
            file_path="/test/music.wav",
            duration_sec=30.0,
            bpm=100.0,
            beats_sec=[0.6, 1.2, 1.8, 2.4],
            downbeats_sec=[0.6, 2.4],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "beats.json"
            beats.save(path)

            assert path.exists()

            # Load and verify
            loaded = BeatAnalysis.load(path)
            assert loaded.bpm == 100.0
            assert len(loaded.beats_sec) == 4
            assert len(loaded.downbeats_sec) == 2

    def test_get_nearest_beat(self):
        """Test finding nearest beat."""
        beats = BeatAnalysis(
            file_path="/test/music.wav",
            beats_sec=[0.0, 0.5, 1.0, 1.5, 2.0],
        )

        # Exact match
        assert beats.get_nearest_beat(0.5) == 0.5

        # Within tolerance
        assert beats.get_nearest_beat(0.55, tolerance_sec=0.1) == 0.5
        assert beats.get_nearest_beat(0.45, tolerance_sec=0.1) == 0.5

        # Outside tolerance
        assert beats.get_nearest_beat(0.7, tolerance_sec=0.1) is None

    def test_get_nearest_downbeat(self):
        """Test finding nearest downbeat."""
        beats = BeatAnalysis(
            file_path="/test/music.wav",
            beats_sec=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
            downbeats_sec=[0.0, 2.0],  # Every 4 beats
        )

        assert beats.get_nearest_downbeat(0.1, tolerance_sec=0.2) == 0.0
        assert beats.get_nearest_downbeat(1.9, tolerance_sec=0.2) == 2.0
        assert beats.get_nearest_downbeat(1.0, tolerance_sec=0.2) is None


class TestBeatSnapping:
    """Tests for beat snapping functions."""

    @pytest.fixture
    def sample_beats(self):
        """Create sample beat analysis."""
        return BeatAnalysis(
            file_path="/test/music.wav",
            bpm=120.0,  # 2 beats per second
            beats_sec=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
            downbeats_sec=[0.0, 2.0, 4.0],  # Every 4 beats
        )

    def test_snap_to_beat_exact(self, sample_beats):
        """Test snapping when on a beat."""
        result = snap_to_beat(0.5, sample_beats, tolerance_sec=0.1)
        assert result == 0.5

    def test_snap_to_beat_near(self, sample_beats):
        """Test snapping to nearest beat."""
        result = snap_to_beat(0.55, sample_beats, tolerance_sec=0.1)
        assert result == 0.5

        result = snap_to_beat(0.95, sample_beats, tolerance_sec=0.1)
        assert result == 1.0

    def test_snap_to_beat_no_snap(self, sample_beats):
        """Test no snapping when outside tolerance."""
        result = snap_to_beat(0.25, sample_beats, tolerance_sec=0.1)
        assert result == 0.25  # Original value

    def test_snap_to_beat_prefer_downbeats(self, sample_beats):
        """Test preferring downbeats."""
        # Near both a beat (1.5) and a downbeat (2.0)
        result = snap_to_beat(
            1.85, sample_beats, tolerance_sec=0.2, prefer_downbeats=True
        )
        assert result == 2.0  # Should prefer downbeat

    def test_snap_to_beat_min_time(self, sample_beats):
        """Test minimum time constraint."""
        result = snap_to_beat(
            0.55, sample_beats, tolerance_sec=0.1, min_time_sec=1.0
        )
        # Should not snap to 0.5 because it's below min_time
        assert result == 0.55

    def test_snap_clip_boundaries(self, sample_beats):
        """Test snapping clip boundaries."""
        snapped_in, snapped_out = snap_clip_boundaries(
            clip_in_sec=0.55,
            clip_out_sec=2.05,
            beats=sample_beats,
            tolerance_sec=0.1,
            min_duration_sec=1.0,
        )
        assert snapped_in == 0.5
        assert snapped_out == 2.0

    def test_snap_clip_boundaries_maintains_min_duration(self, sample_beats):
        """Test that snapping maintains minimum duration."""
        snapped_in, snapped_out = snap_clip_boundaries(
            clip_in_sec=0.55,
            clip_out_sec=1.55,  # Would snap to 1.5, giving only 1.0s (at boundary)
            beats=sample_beats,
            tolerance_sec=0.1,
            min_duration_sec=1.0,
        )
        # Should snap but maintain min duration
        assert snapped_in == 0.5
        # OUT should be at least 1.0s after IN
        assert snapped_out >= snapped_in + 1.0

    def test_snap_with_none_beats(self):
        """Test snapping with no beats."""
        result = snap_to_beat(0.55, None, tolerance_sec=0.1)
        assert result == 0.55


# ============================================================================
# Milestone 6: Audio Processor Tests
# ============================================================================

class TestDuckingConfig:
    """Tests for DuckingConfig."""

    def test_defaults(self):
        """Test default values."""
        config = DuckingConfig()
        assert config.ducking_db == -12.0
        assert config.attack_ms == 200.0
        assert config.release_ms == 500.0

    def test_to_dict(self):
        """Test serialization."""
        config = DuckingConfig(ducking_db=-15.0)
        d = config.to_dict()
        assert d["ducking_db"] == -15.0


class TestDuckingResult:
    """Tests for DuckingResult."""

    def test_create_result(self):
        """Test creating a result."""
        config = DuckingConfig()
        result = DuckingResult(
            music_path="/test/music.wav",
            voice_path="/test/voice.wav",
            output_path="/test/output.wav",
            config=config,
            success=True,
        )
        assert result.success
        assert result.music_path == "/test/music.wav"

    def test_save_result(self):
        """Test saving result to JSON."""
        config = DuckingConfig()
        result = DuckingResult(
            music_path="/test/music.wav",
            voice_path="/test/voice.wav",
            output_path="/test/output.wav",
            config=config,
            success=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ducking_result.json"
            result.save(path)

            assert path.exists()
            with open(path) as f:
                data = json.load(f)
            assert data["success"] is True


class TestAudioProcessor:
    """Tests for AudioProcessor."""

    def test_init(self):
        """Test initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = AudioProcessor(work_dir=Path(tmpdir))
            assert processor.work_dir.exists()


# ============================================================================
# Milestone 7: Decision Engine Tests
# ============================================================================

class TestVariantConfig:
    """Tests for VariantConfig."""

    def test_trailer_preset(self):
        """Test trailer variant preset."""
        config = VariantConfig.trailer(30.0)
        assert config.name == "trailer"
        assert config.target_duration_sec == 30.0
        assert config.pacing == "fast"
        assert config.min_scene_duration_sec < config.max_scene_duration_sec

    def test_balanced_preset(self):
        """Test balanced variant preset."""
        config = VariantConfig.balanced(60.0)
        assert config.name == "balanced"
        assert config.target_duration_sec == 60.0
        assert config.pacing == "balanced"

    def test_atmospheric_preset(self):
        """Test atmospheric variant preset."""
        config = VariantConfig.atmospheric(90.0)
        assert config.name == "atmo"
        assert config.target_duration_sec == 90.0
        assert config.pacing == "slow"

    def test_structure_weights_sum_to_one(self):
        """Test that structure weights sum to 1.0."""
        for factory in [VariantConfig.trailer, VariantConfig.balanced, VariantConfig.atmospheric]:
            config = factory(60.0)
            total = (
                config.hook_weight +
                config.build_weight +
                config.peak_weight +
                config.outro_weight
            )
            assert abs(total - 1.0) < 0.01, f"Weights sum to {total}, not 1.0"

    def test_to_dict(self):
        """Test serialization."""
        config = VariantConfig.balanced(60.0)
        d = config.to_dict()
        assert d["name"] == "balanced"
        assert "structure_weights" in d
        assert "beat_sync" in d


class TestSceneCandidate:
    """Tests for SceneCandidate."""

    def test_create_candidate(self):
        """Test creating a scene candidate."""
        scene = SceneCandidate(
            clip_name="test_clip.mp4",
            clip_path="/test/test_clip.mp4",
            scene_index=0,
            start_sec=0.0,
            end_sec=3.0,
            duration_sec=3.0,
            motion_score=0.5,
        )
        assert scene.clip_name == "test_clip.mp4"
        assert scene.duration_sec == 3.0

    def test_to_dict(self):
        """Test serialization."""
        scene = SceneCandidate(
            clip_name="test.mp4",
            clip_path=None,
            scene_index=1,
            start_sec=3.0,
            end_sec=6.0,
            duration_sec=3.0,
            motion_score=0.7,
            bucket="peak",
            selected=True,
        )
        d = scene.to_dict()
        assert d["bucket"] == "peak"
        assert d["selected"] is True


class TestDecisionEngine:
    """Tests for DecisionEngine."""

    @pytest.fixture
    def sample_candidates(self):
        """Create sample candidates data."""
        return {
            "clips": [
                {
                    "clip_name": "test_clip.mp4",
                    "file_path": "/test/test_clip.mp4",
                    "duration_sec": 30.0,
                    "scenes": [
                        {"index": 0, "start_sec": 0, "end_sec": 5, "duration_sec": 5, "motion_score": 0.3},
                        {"index": 1, "start_sec": 5, "end_sec": 10, "duration_sec": 5, "motion_score": 0.5},
                        {"index": 2, "start_sec": 10, "end_sec": 15, "duration_sec": 5, "motion_score": 0.7},
                        {"index": 3, "start_sec": 15, "end_sec": 20, "duration_sec": 5, "motion_score": 0.8},
                        {"index": 4, "start_sec": 20, "end_sec": 25, "duration_sec": 5, "motion_score": 0.4},
                        {"index": 5, "start_sec": 25, "end_sec": 30, "duration_sec": 5, "motion_score": 0.2},
                    ],
                }
            ],
            "summary": {
                "total_clips": 1,
                "total_duration_sec": 30.0,
                "total_scenes": 6,
                "average_motion_score": 0.48,
            },
        }

    def test_extract_scenes(self, sample_candidates):
        """Test extracting scenes from candidates."""
        engine = DecisionEngine()
        scenes = engine.extract_scenes(sample_candidates)

        assert len(scenes) == 6
        assert scenes[0].clip_name == "test_clip.mp4"
        assert scenes[2].motion_score == 0.7

    def test_categorize_by_motion(self, sample_candidates):
        """Test motion categorization."""
        engine = DecisionEngine()
        scenes = engine.extract_scenes(sample_candidates)
        categories = engine.categorize_by_motion(scenes)

        assert "low" in categories
        assert "medium" in categories
        assert "high" in categories

        # Check categorization makes sense
        for scene in categories["low"]:
            assert scene.motion_score is None or scene.motion_score < 0.35
        for scene in categories["high"]:
            assert scene.motion_score is None or scene.motion_score >= 0.6

    def test_generate_plan(self, sample_candidates):
        """Test plan generation."""
        engine = DecisionEngine()
        config = VariantConfig.balanced(15.0)  # Short duration

        plan = engine.generate_plan(
            candidates=sample_candidates,
            config=config,
        )

        assert plan is not None
        assert len(plan.clips) > 0
        assert plan.timeline.name.startswith("AUTO_")

    def test_generate_plan_with_beats(self):
        """Test plan generation with beat snapping."""
        # Create candidates with shorter scenes that fit trailer constraints
        candidates = {
            "clips": [
                {
                    "clip_name": "test_clip.mp4",
                    "file_path": "/test/test_clip.mp4",
                    "duration_sec": 30.0,
                    "scenes": [
                        {"index": 0, "start_sec": 0, "end_sec": 2, "duration_sec": 2, "motion_score": 0.6},
                        {"index": 1, "start_sec": 2, "end_sec": 5, "duration_sec": 3, "motion_score": 0.7},
                        {"index": 2, "start_sec": 5, "end_sec": 8, "duration_sec": 3, "motion_score": 0.8},
                        {"index": 3, "start_sec": 8, "end_sec": 11, "duration_sec": 3, "motion_score": 0.5},
                        {"index": 4, "start_sec": 11, "end_sec": 14, "duration_sec": 3, "motion_score": 0.4},
                        {"index": 5, "start_sec": 14, "end_sec": 17, "duration_sec": 3, "motion_score": 0.3},
                    ],
                }
            ],
            "summary": {
                "total_clips": 1,
                "total_duration_sec": 17.0,
                "total_scenes": 6,
                "average_motion_score": 0.55,
            },
        }

        engine = DecisionEngine()
        config = VariantConfig.trailer(15.0)

        # Create mock beats
        beats = BeatAnalysis(
            file_path="/test/music.wav",
            bpm=120.0,
            beats_sec=[i * 0.5 for i in range(60)],  # Beat every 0.5s
        )

        plan = engine.generate_plan(
            candidates=candidates,
            config=config,
            beats=beats,
        )

        assert plan is not None
        # Clips should exist
        assert len(plan.clips) > 0


# ============================================================================
# Milestone 8: Pipeline Tests
# ============================================================================

class TestVariantOutput:
    """Tests for VariantOutput."""

    def test_create_output(self):
        """Test creating variant output."""
        output = VariantOutput(
            variant_name="trailer",
            output_dir=Path("/test/work/variants/trailer"),
            success=True,
        )
        assert output.variant_name == "trailer"
        assert output.success

    def test_to_dict(self):
        """Test serialization."""
        output = VariantOutput(
            variant_name="balanced",
            output_dir=Path("/test/work/variants/balanced"),
            plan_path=Path("/test/plan.json"),
            success=True,
        )
        d = output.to_dict()
        assert d["variant_name"] == "balanced"
        assert d["success"] is True


class TestPipelineResult:
    """Tests for PipelineResult."""

    def test_create_result(self):
        """Test creating pipeline result."""
        result = PipelineResult(
            success=True,
            variants_generated=["trailer", "balanced"],
        )
        assert result.success
        assert len(result.variants_generated) == 2

    def test_to_dict(self):
        """Test serialization."""
        result = PipelineResult(
            success=True,
            variants_generated=["trailer"],
            errors=["test error"],
        )
        d = result.to_dict()
        assert d["success"] is True
        assert "test error" in d["errors"]


class TestCinematicPipeline:
    """Tests for CinematicPipeline (without Resolve)."""

    def test_init(self):
        """Test pipeline initialization."""
        pipeline = CinematicPipeline()
        assert pipeline.config is not None
        assert pipeline.decision_engine is not None
        assert pipeline.prompt_generator is not None

    def test_variant_presets(self):
        """Test variant presets exist."""
        assert "trailer" in CinematicPipeline.VARIANT_PRESETS
        assert "balanced" in CinematicPipeline.VARIANT_PRESETS
        assert "atmo" in CinematicPipeline.VARIANT_PRESETS

    def test_run_all_without_candidates(self):
        """Test run_all fails gracefully without candidates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from autonomous.config import PipelineConfig
            config = PipelineConfig()
            config.work_dir = Path(tmpdir)
            config._ensure_directories()

            pipeline = CinematicPipeline(config=config)
            result = pipeline.run_all(variants=["trailer"])

            assert not result.success
            assert any("Candidates not found" in e for e in result.errors)

    def test_run_all_with_mock_candidates(self):
        """Test run_all with mock candidates file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from autonomous.config import PipelineConfig
            config = PipelineConfig()
            config.work_dir = Path(tmpdir)
            config._ensure_directories()

            # Create mock candidates
            candidates = {
                "clips": [
                    {
                        "clip_name": "test.mp4",
                        "file_path": "/test/test.mp4",
                        "duration_sec": 30.0,
                        "scenes": [
                            {"index": 0, "start_sec": 0, "end_sec": 10, "duration_sec": 10, "motion_score": 0.5},
                            {"index": 1, "start_sec": 10, "end_sec": 20, "duration_sec": 10, "motion_score": 0.6},
                            {"index": 2, "start_sec": 20, "end_sec": 30, "duration_sec": 10, "motion_score": 0.4},
                        ],
                    }
                ],
                "summary": {
                    "total_clips": 1,
                    "total_duration_sec": 30.0,
                    "total_scenes": 3,
                    "average_motion_score": 0.5,
                },
            }

            candidates_path = config.candidates_path
            with open(candidates_path, "w") as f:
                json.dump(candidates, f)

            pipeline = CinematicPipeline(config=config)
            result = pipeline.run_all(
                variants=["trailer", "balanced"],
                execute=False,  # Don't try to connect to Resolve
            )

            # Should succeed in generating variants
            assert result.success
            assert "trailer" in result.variants_generated
            assert "balanced" in result.variants_generated

            # Check outputs exist
            for variant in ["trailer", "balanced"]:
                variant_dir = config.variant_dir(variant)
                assert variant_dir.exists()
                assert (variant_dir / "plan.json").exists()
                assert (variant_dir / "prompts" / "suno_prompt.md").exists()
                assert (variant_dir / "prompts" / "voiceover_script.md").exists()


# ============================================================================
# Integration Tests
# ============================================================================

class TestDurationConstraints:
    """Test that plans respect duration constraints."""

    @pytest.fixture
    def long_candidates(self):
        """Create candidates with many scenes."""
        scenes = []
        for i in range(20):
            scenes.append({
                "index": i,
                "start_sec": i * 5,
                "end_sec": (i + 1) * 5,
                "duration_sec": 5,
                "motion_score": 0.3 + (i % 5) * 0.15,
            })

        return {
            "clips": [
                {
                    "clip_name": "long_clip.mp4",
                    "file_path": "/test/long_clip.mp4",
                    "duration_sec": 100.0,
                    "scenes": scenes,
                }
            ],
            "summary": {
                "total_clips": 1,
                "total_duration_sec": 100.0,
                "total_scenes": 20,
                "average_motion_score": 0.5,
            },
        }

    def test_trailer_respects_duration(self, long_candidates):
        """Test trailer variant respects target duration."""
        engine = DecisionEngine()
        config = VariantConfig.trailer(30.0)

        plan = engine.generate_plan(long_candidates, config)

        # Calculate actual duration
        total_frames = sum(c.duration_frames or 0 for c in plan.clips)
        actual_duration = total_frames / 24.0

        # Should be close to target (within 50% tolerance for small targets)
        assert actual_duration <= 30.0 * 1.5, f"Duration {actual_duration}s exceeds target"

    def test_scene_duration_bounds(self, long_candidates):
        """Test that selected scenes respect min/max bounds."""
        engine = DecisionEngine()
        config = VariantConfig.balanced(45.0)
        config.min_scene_duration_sec = 2.0
        config.max_scene_duration_sec = 8.0

        plan = engine.generate_plan(long_candidates, config)

        for clip in plan.clips:
            if clip.duration_frames:
                duration = clip.duration_frames / 24.0
                # Allow some tolerance for beat snapping
                assert duration >= config.min_scene_duration_sec * 0.5
                assert duration <= config.max_scene_duration_sec * 1.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
