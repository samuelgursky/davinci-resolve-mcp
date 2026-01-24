"""
Unit tests for autonomous editor schemas.

These tests validate plan generation and serialization WITHOUT requiring DaVinci Resolve.
"""

import pytest
import json
import tempfile
from pathlib import Path

from autonomous.schemas import (
    EditPlan,
    ClipReference,
    AudioReference,
    TimelineSettings,
    RenderSettings,
    GradeSettings,
    MarkerDefinition,
    TransitionDefinition,
    TrackType,
    TransitionType,
    MarkerColor,
)


class TestClipReference:
    """Tests for ClipReference dataclass."""

    def test_create_minimal(self):
        """Test creating clip with minimal data."""
        clip = ClipReference(name="test_clip.mp4")
        assert clip.name == "test_clip.mp4"
        assert clip.order == 0
        assert clip.track == 1
        assert clip.track_type == TrackType.VIDEO

    def test_create_with_all_fields(self):
        """Test creating clip with all fields."""
        clip = ClipReference(
            name="scene_01.mp4",
            source_path="/path/to/scene_01.mp4",
            source_in=100,
            source_out=500,
            track=2,
            track_type=TrackType.VIDEO,
            order=5,
            duration_frames=400,
            fps=24.0,
            width=1920,
            height=1080,
        )
        assert clip.name == "scene_01.mp4"
        assert clip.source_in == 100
        assert clip.source_out == 500
        assert clip.track == 2
        assert clip.order == 5

    def test_to_dict(self):
        """Test serialization to dict."""
        clip = ClipReference(name="test.mp4", order=1)
        d = clip.to_dict()
        assert d["name"] == "test.mp4"
        assert d["track_type"] == "video"
        assert d["order"] == 1


class TestAudioReference:
    """Tests for AudioReference dataclass."""

    def test_create_music(self):
        """Test creating music audio reference."""
        audio = AudioReference(
            name="soundtrack.mp3",
            source_path="/path/to/soundtrack.mp3",
            track=1,
            audio_type="music",
        )
        assert audio.audio_type == "music"
        assert audio.track == 1
        assert audio.volume == 1.0

    def test_create_voiceover(self):
        """Test creating voiceover audio reference."""
        audio = AudioReference(
            name="narration.wav",
            track=2,
            audio_type="voiceover",
            volume=0.8,
        )
        assert audio.audio_type == "voiceover"
        assert audio.track == 2
        assert audio.volume == 0.8


class TestTimelineSettings:
    """Tests for TimelineSettings dataclass."""

    def test_defaults(self):
        """Test default timeline settings."""
        settings = TimelineSettings()
        assert settings.name == "AUTO_V1"
        assert settings.fps == "24"
        assert settings.width == 1920
        assert settings.height == 1080

    def test_custom_settings(self):
        """Test custom timeline settings."""
        settings = TimelineSettings(
            name="MY_TIMELINE",
            fps="30",
            width=3840,
            height=2160,
        )
        assert settings.name == "MY_TIMELINE"
        assert settings.fps == "30"
        assert settings.width == 3840


class TestEditPlan:
    """Tests for EditPlan dataclass."""

    def test_create_empty(self):
        """Test creating empty plan."""
        plan = EditPlan()
        assert plan.plan_version == "1.0.0"
        assert len(plan.clips) == 0
        assert len(plan.audio) == 0
        assert plan.executed == False

    def test_add_clip_chaining(self):
        """Test add_clip returns self for chaining."""
        plan = EditPlan()
        result = plan.add_clip("clip1.mp4").add_clip("clip2.mp4")
        assert result is plan
        assert len(plan.clips) == 2
        assert plan.clips[0].order == 0
        assert plan.clips[1].order == 1

    def test_add_audio_chaining(self):
        """Test add_audio returns self for chaining."""
        plan = EditPlan()
        result = plan.add_audio("music.mp3", audio_type="music")
        assert result is plan
        assert len(plan.audio) == 1

    def test_set_render(self):
        """Test setting render settings."""
        plan = EditPlan()
        plan.set_render("H.264 Master", output_directory="/output")
        assert plan.render is not None
        assert plan.render.preset_name == "H.264 Master"
        assert plan.render.output_directory == "/output"

    def test_validate_empty_plan(self):
        """Test validation catches empty plan."""
        plan = EditPlan()
        issues = plan.validate()
        assert len(issues) > 0
        assert any("at least one clip" in i for i in issues)

    def test_validate_no_timeline_name(self):
        """Test validation catches missing timeline name."""
        plan = EditPlan()
        plan.timeline.name = ""
        plan.add_clip("test.mp4")
        issues = plan.validate()
        assert any("Timeline name" in i for i in issues)

    def test_validate_duplicate_orders(self):
        """Test validation catches duplicate clip orders."""
        plan = EditPlan()
        plan.clips.append(ClipReference(name="clip1.mp4", order=0))
        plan.clips.append(ClipReference(name="clip2.mp4", order=0))  # Same order
        issues = plan.validate()
        assert any("Duplicate" in i for i in issues)

    def test_validate_valid_plan(self):
        """Test valid plan passes validation."""
        plan = EditPlan()
        plan.add_clip("clip1.mp4")
        plan.add_clip("clip2.mp4")
        plan.set_render("H.264 Master")
        issues = plan.validate()
        assert len(issues) == 0

    def test_to_json(self):
        """Test JSON serialization."""
        plan = EditPlan()
        plan.description = "Test plan"
        plan.add_clip("test.mp4")
        plan.add_audio("music.mp3", audio_type="music")

        json_str = plan.to_json()
        parsed = json.loads(json_str)

        assert parsed["description"] == "Test plan"
        assert len(parsed["clips"]) == 1
        assert len(parsed["audio"]) == 1
        assert parsed["clips"][0]["name"] == "test.mp4"

    def test_save_and_load(self):
        """Test saving and loading plan."""
        plan = EditPlan()
        plan.description = "Save/load test"
        plan.add_clip("clip1.mp4")
        plan.add_clip("clip2.mp4")
        plan.add_audio("music.mp3", track=1, audio_type="music")
        plan.set_render("Test Preset")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_plan.json"
            plan.save(path)

            loaded = EditPlan.load(path)

            assert loaded.description == "Save/load test"
            assert len(loaded.clips) == 2
            assert len(loaded.audio) == 1
            assert loaded.render.preset_name == "Test Preset"

    def test_from_dict(self):
        """Test creating plan from dictionary."""
        data = {
            "plan_version": "1.0.0",
            "description": "From dict test",
            "timeline": {
                "name": "TEST_TL",
                "fps": "30",
                "width": 1920,
                "height": 1080,
                "start_timecode": "00:00:00:00",
            },
            "clips": [
                {"name": "clip1.mp4", "order": 0, "track": 1, "track_type": "video"},
            ],
            "audio": [
                {"name": "music.mp3", "track": 1, "audio_type": "music"},
            ],
            "markers": [],
            "transitions": [],
            "render": {"preset_name": "H.264"},
        }

        plan = EditPlan.from_dict(data)

        assert plan.description == "From dict test"
        assert plan.timeline.name == "TEST_TL"
        assert plan.timeline.fps == "30"
        assert len(plan.clips) == 1
        assert plan.clips[0].name == "clip1.mp4"
        assert plan.render.preset_name == "H.264"

    def test_execution_log(self):
        """Test execution logging."""
        plan = EditPlan()
        plan.log("Step 1")
        plan.log("Step 2")

        assert len(plan.execution_log) == 2
        assert "Step 1" in plan.execution_log[0]
        assert "Step 2" in plan.execution_log[1]


class TestMarkerDefinition:
    """Tests for MarkerDefinition."""

    def test_create_marker(self):
        """Test creating marker."""
        marker = MarkerDefinition(
            frame=100,
            color=MarkerColor.RED,
            name="Important",
            note="This is important",
        )
        assert marker.frame == 100
        assert marker.color == MarkerColor.RED

    def test_to_dict(self):
        """Test marker serialization."""
        marker = MarkerDefinition(frame=50, color=MarkerColor.BLUE)
        d = marker.to_dict()
        assert d["frame"] == 50
        assert d["color"] == "Blue"


class TestTransitionDefinition:
    """Tests for TransitionDefinition."""

    def test_create_transition(self):
        """Test creating transition."""
        trans = TransitionDefinition(
            after_clip_order=0,
            transition_type=TransitionType.DISSOLVE,
            duration_frames=24,
        )
        assert trans.after_clip_order == 0
        assert trans.transition_type == TransitionType.DISSOLVE

    def test_to_dict(self):
        """Test transition serialization."""
        trans = TransitionDefinition(
            after_clip_order=1,
            transition_type=TransitionType.FADE_OUT,
        )
        d = trans.to_dict()
        assert d["transition_type"] == "fade_out"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
