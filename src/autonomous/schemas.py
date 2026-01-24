"""
Schemas for the Edit Decision List (EDL) plan JSON.

These define the structure of the plan that the autonomous editor
generates before executing operations in DaVinci Resolve.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Literal
from enum import Enum
import json
from pathlib import Path
from datetime import datetime


class TrackType(str, Enum):
    """Type of timeline track."""
    VIDEO = "video"
    AUDIO = "audio"


class TransitionType(str, Enum):
    """Available transition types."""
    CUT = "cut"
    DISSOLVE = "dissolve"
    FADE_IN = "fade_in"
    FADE_OUT = "fade_out"


class MarkerColor(str, Enum):
    """Marker colors in DaVinci Resolve."""
    BLUE = "Blue"
    GREEN = "Green"
    YELLOW = "Yellow"
    RED = "Red"
    PURPLE = "Purple"


@dataclass
class ClipReference:
    """Reference to a clip in the media pool."""

    name: str  # Clip name in media pool
    source_path: Optional[str] = None  # Original file path

    # Timing (frames)
    source_in: int = 0
    source_out: Optional[int] = None  # None = full clip

    # Timeline placement
    track: int = 1
    track_type: TrackType = TrackType.VIDEO
    order: int = 0  # Sequence order

    # Metadata from media pool
    duration_frames: Optional[int] = None
    fps: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON."""
        d = asdict(self)
        d["track_type"] = self.track_type.value
        return d


@dataclass
class AudioReference:
    """Reference to an audio file."""

    name: str
    source_path: Optional[str] = None

    # Timing (seconds for easier human editing)
    source_in_sec: float = 0
    source_out_sec: Optional[float] = None

    # Timeline placement
    track: int = 1  # Audio track number
    timeline_position_sec: float = 0

    # Type
    audio_type: Literal["music", "voiceover", "sfx"] = "music"
    volume: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON."""
        return asdict(self)


@dataclass
class MarkerDefinition:
    """Timeline marker definition."""

    frame: int
    color: MarkerColor = MarkerColor.BLUE
    name: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON."""
        d = asdict(self)
        d["color"] = self.color.value
        return d


@dataclass
class TransitionDefinition:
    """Transition between clips."""

    after_clip_order: int  # Transition after this clip
    transition_type: TransitionType = TransitionType.CUT
    duration_frames: int = 24

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON."""
        d = asdict(self)
        d["transition_type"] = self.transition_type.value
        return d


@dataclass
class GradeSettings:
    """Color grading settings."""

    lut_path: Optional[str] = None
    preset_name: Optional[str] = None
    node_index: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON."""
        return asdict(self)


@dataclass
class RenderSettings:
    """Render/export settings."""

    preset_name: str = "H.264 Master"
    output_directory: Optional[str] = None
    output_filename: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON."""
        return asdict(self)


@dataclass
class TimelineSettings:
    """Timeline creation settings."""

    name: str = "AUTO_V1"
    fps: str = "24"
    width: int = 1920
    height: int = 1080
    start_timecode: str = "01:00:00:00"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON."""
        return asdict(self)


@dataclass
class EditPlan:
    """
    Complete edit decision plan (EDL-like).

    This is the main schema representing all editing operations.
    """

    # Metadata
    plan_version: str = "1.0.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    description: str = ""

    # Project info
    project_name: Optional[str] = None
    source_timeline_name: Optional[str] = None  # If duplicating

    # Timeline settings
    timeline: TimelineSettings = field(default_factory=TimelineSettings)

    # Content
    clips: List[ClipReference] = field(default_factory=list)
    audio: List[AudioReference] = field(default_factory=list)
    markers: List[MarkerDefinition] = field(default_factory=list)
    transitions: List[TransitionDefinition] = field(default_factory=list)

    # Optional processing
    grade: Optional[GradeSettings] = None
    render: Optional[RenderSettings] = None

    # Execution tracking
    executed: bool = False
    execution_log: List[str] = field(default_factory=list)

    def add_clip(self, name: str, **kwargs) -> "EditPlan":
        """Add a clip. Returns self for chaining."""
        order = kwargs.pop("order", len(self.clips))
        clip = ClipReference(name=name, order=order, **kwargs)
        self.clips.append(clip)
        return self

    def add_audio(self, name: str, **kwargs) -> "EditPlan":
        """Add audio. Returns self for chaining."""
        audio = AudioReference(name=name, **kwargs)
        self.audio.append(audio)
        return self

    def add_marker(self, frame: int, **kwargs) -> "EditPlan":
        """Add a marker. Returns self for chaining."""
        marker = MarkerDefinition(frame=frame, **kwargs)
        self.markers.append(marker)
        return self

    def set_render(self, preset_name: str, **kwargs) -> "EditPlan":
        """Set render settings. Returns self for chaining."""
        self.render = RenderSettings(preset_name=preset_name, **kwargs)
        return self

    def set_grade(self, **kwargs) -> "EditPlan":
        """Set grade settings. Returns self for chaining."""
        self.grade = GradeSettings(**kwargs)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert entire plan to dictionary."""
        return {
            "plan_version": self.plan_version,
            "created_at": self.created_at,
            "description": self.description,
            "project_name": self.project_name,
            "source_timeline_name": self.source_timeline_name,
            "timeline": self.timeline.to_dict(),
            "clips": [c.to_dict() for c in self.clips],
            "audio": [a.to_dict() for a in self.audio],
            "markers": [m.to_dict() for m in self.markers],
            "transitions": [t.to_dict() for t in self.transitions],
            "grade": self.grade.to_dict() if self.grade else None,
            "render": self.render.to_dict() if self.render else None,
            "executed": self.executed,
            "execution_log": self.execution_log,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: Path) -> None:
        """Save plan to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def load(cls, path: Path) -> "EditPlan":
        """Load plan from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EditPlan":
        """Create EditPlan from dictionary."""
        plan = cls()
        plan.plan_version = data.get("plan_version", "1.0.0")
        plan.created_at = data.get("created_at", datetime.now().isoformat())
        plan.description = data.get("description", "")
        plan.project_name = data.get("project_name")
        plan.source_timeline_name = data.get("source_timeline_name")

        if "timeline" in data:
            plan.timeline = TimelineSettings(**data["timeline"])

        for clip_data in data.get("clips", []):
            clip_data["track_type"] = TrackType(clip_data.get("track_type", "video"))
            plan.clips.append(ClipReference(**clip_data))

        for audio_data in data.get("audio", []):
            plan.audio.append(AudioReference(**audio_data))

        for marker_data in data.get("markers", []):
            marker_data["color"] = MarkerColor(marker_data.get("color", "Blue"))
            plan.markers.append(MarkerDefinition(**marker_data))

        for trans_data in data.get("transitions", []):
            trans_data["transition_type"] = TransitionType(
                trans_data.get("transition_type", "cut")
            )
            plan.transitions.append(TransitionDefinition(**trans_data))

        if data.get("grade"):
            plan.grade = GradeSettings(**data["grade"])

        if data.get("render"):
            plan.render = RenderSettings(**data["render"])

        plan.executed = data.get("executed", False)
        plan.execution_log = data.get("execution_log", [])

        return plan

    def validate(self) -> List[str]:
        """Validate plan. Returns list of issues (empty = valid)."""
        issues = []

        if not self.timeline.name:
            issues.append("Timeline name is required")

        if not self.clips and not self.audio:
            issues.append("Plan must have at least one clip or audio reference")

        # Check for duplicate orders
        orders = [c.order for c in self.clips]
        if len(orders) != len(set(orders)):
            issues.append("Duplicate clip order values found")

        for i, clip in enumerate(self.clips):
            if not clip.name:
                issues.append(f"Clip at index {i} has no name")

        if self.render and not self.render.preset_name:
            issues.append("Render preset name required when render settings specified")

        return issues

    def log(self, message: str) -> None:
        """Add message to execution log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.execution_log.append(f"[{timestamp}] {message}")
