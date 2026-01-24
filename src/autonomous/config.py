"""
Configuration and feature flags for the autonomous editor.

Default mode is HUMAN-IN-THE-LOOP - generates prompt packs without API calls.
API integrations are optional and gracefully fall back to manual mode.
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
from enum import Enum

logger = logging.getLogger("autonomous.config")


class AudioMode(str, Enum):
    """How to handle music/voiceover generation."""
    MANUAL = "manual"  # Generate prompt packs only (default)
    API = "api"  # Use Suno/ElevenLabs APIs if keys available


def load_env_file(env_path: Optional[Path] = None) -> None:
    """Load environment variables from .env file if it exists."""
    if env_path is None:
        env_path = Path(__file__).parent.parent.parent / ".env"

    if env_path.exists():
        logger.info(f"Loading environment from {env_path}")
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value


def get_optional_api_key(key: str) -> Optional[str]:
    """
    Get an optional API key from environment.
    Returns None if not set (allows graceful fallback to manual mode).
    """
    return os.environ.get(key) or None


@dataclass
class ResolveSettings:
    """Settings for DaVinci Resolve operations."""

    # Timeline creation
    default_timeline_name: str = "AUTO_V1"
    timeline_fps: str = "24"
    timeline_width: int = 1920
    timeline_height: int = 1080
    start_timecode: str = "01:00:00:00"

    # Track configuration
    video_track: int = 1
    music_track: int = 1  # Audio track for music (A1)
    voiceover_track: int = 2  # Audio track for voiceover (A2)

    # Render settings
    render_preset_name: str = "H.264 Master"
    output_directory: Optional[str] = None

    # Source timeline (for duplication mode)
    source_timeline_name: Optional[str] = None
    duplicate_timeline: bool = False

    # Grading (configurable, not hardcoded)
    lut_path: Optional[str] = None
    grade_preset_name: Optional[str] = None


@dataclass
class FeatureFlags:
    """Feature flags to enable/disable functionality per milestone."""

    # Milestone 1 - Core (always enabled)
    create_timeline: bool = True
    append_clips: bool = True

    # Milestone 2 - Planning
    dry_run: bool = False  # Output plan JSON without touching Resolve

    # Milestone 3 - Analysis
    enable_scene_detection: bool = False
    enable_motion_analysis: bool = False
    enable_transcription: bool = False

    # Milestone 4 - Prompt packs (enabled by default)
    generate_music_prompts: bool = True
    generate_voiceover_script: bool = True

    # Milestone 5 - Beat Sync
    beat_sync_enabled: bool = True
    beat_snap_tolerance_sec: float = 0.10
    beat_prefer_downbeats: bool = False

    # Milestone 6 - Audio processing
    ducking_enabled: bool = True
    ducking_db: float = -12.0
    voice_start_sec: float = 0.0

    # Milestone 7 - Decision engine
    min_scene_duration_sec: float = 1.0
    max_scene_duration_sec: float = 8.0
    target_duration_sec: float = 60.0

    # Milestone 8 - Variants
    default_variants: str = "trailer,balanced,atmo"

    # Polish features (future)
    enable_transitions: bool = False
    enable_color_grade: bool = False


@dataclass
class APISettings:
    """
    Optional API settings for music/voiceover generation.
    These are NOT required - system falls back to manual mode if not set.
    """

    # Suno (music generation)
    suno_api_key: Optional[str] = None
    suno_style: str = "cinematic orchestral"
    suno_duration_seconds: int = 60

    # ElevenLabs (voiceover)
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB"  # Adam
    elevenlabs_model_id: str = "eleven_monolingual_v1"

    def load_from_env(self) -> None:
        """Load API keys from environment (optional, won't error if missing)."""
        self.suno_api_key = get_optional_api_key("SUNO_API_KEY")
        self.elevenlabs_api_key = get_optional_api_key("ELEVENLABS_API_KEY")

    @property
    def suno_available(self) -> bool:
        """Check if Suno API is available."""
        return bool(self.suno_api_key)

    @property
    def elevenlabs_available(self) -> bool:
        """Check if ElevenLabs API is available."""
        return bool(self.elevenlabs_api_key)


@dataclass
class AnalysisSettings:
    """Settings for video analysis (Milestone 3)."""

    scene_threshold: float = 30.0
    min_scene_length_sec: float = 1.0
    motion_sample_rate: int = 5  # frames between samples
    whisper_model: str = "base"
    transcription_language: str = "en"


@dataclass
class PipelineConfig:
    """Main configuration for the autonomous editor pipeline."""

    # Core settings
    resolve: ResolveSettings = field(default_factory=ResolveSettings)
    features: FeatureFlags = field(default_factory=FeatureFlags)
    api: APISettings = field(default_factory=APISettings)
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)

    # Mode
    audio_mode: AudioMode = AudioMode.MANUAL

    # Working directories
    work_dir: Path = field(default_factory=lambda: Path("work"))

    # Input files (user-provided)
    music_file_path: Optional[str] = None
    voiceover_file_path: Optional[str] = None
    clip_bin_name: Optional[str] = None  # Specific bin to pull clips from

    def __post_init__(self):
        """Initialize working directories."""
        self.work_dir = Path(self.work_dir)
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create required working directories."""
        dirs = [
            self.work_dir,
            self.work_dir / "plans",
            self.work_dir / "prompts",
            self.work_dir / "analysis",
            self.work_dir / "audio",
            self.work_dir / "variants",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def plan_path(self) -> Path:
        """Path to the plan JSON file."""
        return self.work_dir / "plans" / "plan.json"

    @property
    def candidates_path(self) -> Path:
        """Path to the analysis candidates JSON."""
        return self.work_dir / "analysis" / "candidates.json"

    @property
    def suno_prompt_path(self) -> Path:
        """Path to the Suno prompt pack."""
        return self.work_dir / "prompts" / "suno_prompt.md"

    @property
    def voiceover_script_path(self) -> Path:
        """Path to the voiceover script."""
        return self.work_dir / "prompts" / "voiceover_script.md"

    @property
    def beats_path(self) -> Path:
        """Path to the beat analysis JSON."""
        return self.work_dir / "audio" / "beats.json"

    @property
    def ducked_music_path(self) -> Path:
        """Path to the ducked music file."""
        return self.work_dir / "audio" / "music_ducked.wav"

    @property
    def variants_dir(self) -> Path:
        """Path to the variants directory."""
        return self.work_dir / "variants"

    def variant_dir(self, variant_name: str) -> Path:
        """Get directory for a specific variant."""
        return self.variants_dir / variant_name

    def should_use_api(self, service: str) -> bool:
        """
        Check if we should use an API for a given service.
        Returns False if in manual mode or if API key is missing.
        """
        if self.audio_mode == AudioMode.MANUAL:
            return False

        if service == "suno":
            return self.api.suno_available
        elif service == "elevenlabs":
            return self.api.elevenlabs_available

        return False

    @classmethod
    def from_env(cls, load_dotenv: bool = True) -> "PipelineConfig":
        """Create config from environment variables."""
        if load_dotenv:
            load_env_file()

        config = cls()
        config.api.load_from_env()

        # Override from environment
        if os.environ.get("RENDER_PRESET"):
            config.resolve.render_preset_name = os.environ["RENDER_PRESET"]
        if os.environ.get("OUTPUT_DIR"):
            config.resolve.output_directory = os.environ["OUTPUT_DIR"]
        if os.environ.get("LUT_PATH"):
            config.resolve.lut_path = os.environ["LUT_PATH"]
        if os.environ.get("TIMELINE_FPS"):
            config.resolve.timeline_fps = os.environ["TIMELINE_FPS"]
        if os.environ.get("TIMELINE_WIDTH"):
            config.resolve.timeline_width = int(os.environ["TIMELINE_WIDTH"])
        if os.environ.get("TIMELINE_HEIGHT"):
            config.resolve.timeline_height = int(os.environ["TIMELINE_HEIGHT"])
        if os.environ.get("AUDIO_MODE"):
            config.audio_mode = AudioMode(os.environ["AUDIO_MODE"])

        return config
