"""
Unit tests for autonomous editor configuration.

Tests configuration loading, API key handling, and feature flags.
"""

import pytest
import os
import tempfile
from pathlib import Path

from autonomous.config import (
    PipelineConfig,
    ResolveSettings,
    FeatureFlags,
    APISettings,
    AudioMode,
    load_env_file,
    get_optional_api_key,
)


class TestAudioMode:
    """Tests for AudioMode enum."""

    def test_manual_is_default(self):
        """Verify manual is the default mode."""
        config = PipelineConfig()
        assert config.audio_mode == AudioMode.MANUAL

    def test_modes_exist(self):
        """Test both modes exist."""
        assert AudioMode.MANUAL == "manual"
        assert AudioMode.API == "api"


class TestAPISettings:
    """Tests for APISettings."""

    def test_no_keys_by_default(self):
        """Test API keys are None by default."""
        settings = APISettings()
        assert settings.suno_api_key is None
        assert settings.elevenlabs_api_key is None

    def test_availability_checks(self):
        """Test availability property checks."""
        settings = APISettings()
        assert settings.suno_available == False
        assert settings.elevenlabs_available == False

        settings.suno_api_key = "test_key"
        assert settings.suno_available == True
        assert settings.elevenlabs_available == False

    def test_load_from_env(self):
        """Test loading from environment."""
        # Save original values
        orig_suno = os.environ.get("SUNO_API_KEY")
        orig_eleven = os.environ.get("ELEVENLABS_API_KEY")

        try:
            os.environ["SUNO_API_KEY"] = "test_suno_key"
            os.environ["ELEVENLABS_API_KEY"] = "test_eleven_key"

            settings = APISettings()
            settings.load_from_env()

            assert settings.suno_api_key == "test_suno_key"
            assert settings.elevenlabs_api_key == "test_eleven_key"
        finally:
            # Restore
            if orig_suno:
                os.environ["SUNO_API_KEY"] = orig_suno
            else:
                os.environ.pop("SUNO_API_KEY", None)
            if orig_eleven:
                os.environ["ELEVENLABS_API_KEY"] = orig_eleven
            else:
                os.environ.pop("ELEVENLABS_API_KEY", None)


class TestFeatureFlags:
    """Tests for FeatureFlags."""

    def test_defaults(self):
        """Test default feature flags."""
        flags = FeatureFlags()

        # Milestone 1 - always on
        assert flags.create_timeline == True
        assert flags.append_clips == True

        # Milestone 2
        assert flags.dry_run == False

        # Milestone 3
        assert flags.enable_scene_detection == False

        # Milestone 4 - prompt packs on by default
        assert flags.generate_music_prompts == True
        assert flags.generate_voiceover_script == True

        # Milestone 5-8
        assert flags.beat_sync_enabled == True  # Now enabled by default
        assert flags.ducking_enabled == True
        assert flags.enable_transitions == False


class TestResolveSettings:
    """Tests for ResolveSettings."""

    def test_defaults(self):
        """Test default resolve settings."""
        settings = ResolveSettings()
        assert settings.default_timeline_name == "AUTO_V1"
        assert settings.timeline_fps == "24"
        assert settings.timeline_width == 1920
        assert settings.timeline_height == 1080
        assert settings.music_track == 1
        assert settings.voiceover_track == 2
        assert settings.render_preset_name == "H.264 Master"

    def test_custom_settings(self):
        """Test custom resolve settings."""
        settings = ResolveSettings(
            default_timeline_name="MY_EDIT",
            timeline_fps="30",
            timeline_width=3840,
            timeline_height=2160,
        )
        assert settings.default_timeline_name == "MY_EDIT"
        assert settings.timeline_fps == "30"


class TestPipelineConfig:
    """Tests for PipelineConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = PipelineConfig()
        assert config.audio_mode == AudioMode.MANUAL
        assert config.features.dry_run == False
        assert config.music_file_path is None
        assert config.voiceover_file_path is None

    def test_work_dir_created(self):
        """Test work directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PipelineConfig(work_dir=Path(tmpdir) / "work")
            assert config.work_dir.exists()
            assert (config.work_dir / "plans").exists()
            assert (config.work_dir / "prompts").exists()

    def test_path_properties(self):
        """Test path property accessors."""
        config = PipelineConfig()
        assert config.plan_path.name == "plan.json"
        assert "plans" in str(config.plan_path)
        assert config.suno_prompt_path.name == "suno_prompt.md"
        assert config.voiceover_script_path.name == "voiceover_script.md"

    def test_should_use_api_manual_mode(self):
        """Test should_use_api in manual mode."""
        config = PipelineConfig()
        config.audio_mode = AudioMode.MANUAL
        config.api.suno_api_key = "test_key"

        # Even with key, manual mode returns False
        assert config.should_use_api("suno") == False
        assert config.should_use_api("elevenlabs") == False

    def test_should_use_api_api_mode(self):
        """Test should_use_api in API mode."""
        config = PipelineConfig()
        config.audio_mode = AudioMode.API
        config.api.suno_api_key = "test_key"

        # With key and API mode, returns True for suno
        assert config.should_use_api("suno") == True
        # But not for elevenlabs (no key)
        assert config.should_use_api("elevenlabs") == False

    def test_no_error_without_keys_in_manual_mode(self):
        """Test that missing API keys don't cause errors in manual mode."""
        # Clear any existing env vars
        orig_suno = os.environ.pop("SUNO_API_KEY", None)
        orig_eleven = os.environ.pop("ELEVENLABS_API_KEY", None)

        try:
            config = PipelineConfig()
            config.api.load_from_env()

            # Should not raise, even without keys
            assert config.api.suno_api_key is None
            assert config.api.elevenlabs_api_key is None

            # should_use_api should return False gracefully
            assert config.should_use_api("suno") == False
            assert config.should_use_api("elevenlabs") == False
        finally:
            # Restore
            if orig_suno:
                os.environ["SUNO_API_KEY"] = orig_suno
            if orig_eleven:
                os.environ["ELEVENLABS_API_KEY"] = orig_eleven


class TestEnvFileLoading:
    """Tests for .env file loading."""

    def test_load_env_file(self):
        """Test loading environment from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("TEST_VAR_123=hello_world\n")

            # Clear if exists
            os.environ.pop("TEST_VAR_123", None)

            load_env_file(env_path)

            assert os.environ.get("TEST_VAR_123") == "hello_world"

            # Cleanup
            os.environ.pop("TEST_VAR_123", None)

    def test_load_env_file_with_quotes(self):
        """Test loading env file handles quoted values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text('TEST_QUOTED="quoted value"\n')

            os.environ.pop("TEST_QUOTED", None)

            load_env_file(env_path)

            # Quotes should be stripped
            assert os.environ.get("TEST_QUOTED") == "quoted value"

            os.environ.pop("TEST_QUOTED", None)

    def test_load_env_skips_comments(self):
        """Test loading env file skips comments."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("# This is a comment\nACTUAL_VAR=value\n")

            os.environ.pop("ACTUAL_VAR", None)

            load_env_file(env_path)

            assert os.environ.get("ACTUAL_VAR") == "value"
            assert "# This is a comment" not in os.environ

            os.environ.pop("ACTUAL_VAR", None)

    def test_get_optional_api_key(self):
        """Test get_optional_api_key returns None for missing keys."""
        os.environ.pop("NONEXISTENT_KEY_12345", None)
        result = get_optional_api_key("NONEXISTENT_KEY_12345")
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
