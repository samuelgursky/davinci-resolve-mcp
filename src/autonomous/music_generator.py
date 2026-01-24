"""
Music Generator - Suno prompt pack generation.

Generates comprehensive prompt packs for manual use with Suno AI.
NO API CALLS - human-in-the-loop only.
"""

import logging
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger("autonomous.music_generator")


@dataclass
class SectionTiming:
    """Timing suggestion for a music section."""
    name: str
    start_percent: int
    end_percent: int
    description: str
    energy_level: str  # low, medium, high, peak

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "start_percent": self.start_percent,
            "end_percent": self.end_percent,
            "description": self.description,
            "energy_level": self.energy_level,
        }

    def to_time_range(self, total_duration_sec: float) -> str:
        """Convert percentage to time range string."""
        start = int(total_duration_sec * self.start_percent / 100)
        end = int(total_duration_sec * self.end_percent / 100)
        return f"{start}s - {end}s ({self.start_percent}%-{self.end_percent}%)"


@dataclass
class SunoPromptPack:
    """Complete Suno prompt pack for music generation."""

    # Core prompts
    main_prompt: str = ""
    variant_prompts: List[str] = field(default_factory=list)

    # Musical parameters
    bpm_range: str = "80-110"
    target_duration_sec: int = 60
    key_suggestion: str = ""  # e.g., "D minor", "C major"

    # Section timing
    sections: List[SectionTiming] = field(default_factory=list)

    # Constraints
    do_list: List[str] = field(default_factory=list)
    dont_list: List[str] = field(default_factory=list)

    # Context
    mood: str = ""
    genre: str = "cinematic"
    pacing: str = "moderate"  # slow, moderate, fast
    instruments: List[str] = field(default_factory=list)

    # Analysis-derived
    average_motion_score: Optional[float] = None
    scene_count: int = 0
    has_audio_in_source: bool = False

    @property
    def suggested_duration_sec(self) -> int:
        """Alias for target_duration_sec (backward compatibility)."""
        return self.target_duration_sec

    def to_dict(self) -> Dict[str, Any]:
        return {
            "main_prompt": self.main_prompt,
            "variant_prompts": self.variant_prompts,
            "bpm_range": self.bpm_range,
            "target_duration_sec": self.target_duration_sec,
            "key_suggestion": self.key_suggestion,
            "sections": [s.to_dict() for s in self.sections],
            "do_list": self.do_list,
            "dont_list": self.dont_list,
            "mood": self.mood,
            "genre": self.genre,
            "pacing": self.pacing,
            "instruments": self.instruments,
            "analysis_context": {
                "average_motion_score": self.average_motion_score,
                "scene_count": self.scene_count,
                "has_audio_in_source": self.has_audio_in_source,
            },
        }

    def to_markdown(self) -> str:
        """Generate human-readable markdown prompt pack."""
        lines = [
            "# Suno Music Prompt Pack",
            "",
            "> Generated for manual use with Suno AI. No API required.",
            "",
            "---",
            "",
            "## Main Prompt",
            "",
            "```",
            self.main_prompt,
            "```",
            "",
            "## Variant Prompts",
            "",
        ]

        for i, variant in enumerate(self.variant_prompts, 1):
            lines.extend([
                f"### Variant {i}",
                "```",
                variant,
                "```",
                "",
            ])

        lines.extend([
            "---",
            "",
            "## Musical Parameters",
            "",
            f"| Parameter | Value |",
            f"|-----------|-------|",
            f"| **BPM Range** | {self.bpm_range} |",
            f"| **Target Duration** | {self.target_duration_sec} seconds |",
            f"| **Mood** | {self.mood} |",
            f"| **Genre** | {self.genre} |",
            f"| **Pacing** | {self.pacing} |",
        ])

        if self.key_suggestion:
            lines.append(f"| **Suggested Key** | {self.key_suggestion} |")

        lines.append("")

        if self.instruments:
            lines.extend([
                "### Suggested Instruments",
                "",
            ])
            for inst in self.instruments:
                lines.append(f"- {inst}")
            lines.append("")

        if self.sections:
            lines.extend([
                "---",
                "",
                "## Section Timing",
                "",
                "Structure your track with these sections:",
                "",
                "| Section | Time Range | Energy | Description |",
                "|---------|------------|--------|-------------|",
            ])
            for section in self.sections:
                time_range = section.to_time_range(self.target_duration_sec)
                lines.append(
                    f"| **{section.name}** | {time_range} | {section.energy_level} | {section.description} |"
                )
            lines.append("")

        lines.extend([
            "---",
            "",
            "## Constraints",
            "",
            "### DO (Include)",
            "",
        ])
        for item in self.do_list:
            lines.append(f"- ✅ {item}")

        lines.extend([
            "",
            "### DON'T (Avoid)",
            "",
        ])
        for item in self.dont_list:
            lines.append(f"- ❌ {item}")

        if not self.has_audio_in_source:
            lines.extend([
                "",
                "---",
                "",
                "## Note: No Source Audio",
                "",
                "The source video has **no audio track**. The music must:",
                "- Carry all emotional weight and pacing",
                "- Match visual transitions and motion intensity",
                "- Drive the narrative without dialogue support",
                "",
            ])

        lines.extend([
            "---",
            "",
            "## Analysis Context",
            "",
            f"- **Average Motion Score**: {f'{self.average_motion_score:.3f}' if self.average_motion_score is not None else 'N/A'}",
            f"- **Scene Count**: {self.scene_count}",
            f"- **Source Has Audio**: {'Yes' if self.has_audio_in_source else 'No'}",
            "",
        ])

        return "\n".join(lines)

    def save(self, base_path: Path, format: str = "both") -> None:
        """
        Save prompt pack to file(s).

        Args:
            base_path: Base path (without extension)
            format: "markdown", "json", or "both" (default)
        """
        base_path = Path(base_path)
        base_path.parent.mkdir(parents=True, exist_ok=True)

        if format in ("markdown", "both"):
            md_path = base_path.with_suffix(".md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(self.to_markdown())
            logger.info(f"Saved Suno prompt (MD): {md_path}")

        if format in ("json", "both"):
            json_path = base_path.with_suffix(".json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
            logger.info(f"Saved Suno prompt (JSON): {json_path}")


class MusicPromptGenerator:
    """
    Generates Suno prompt packs from video analysis.

    NO API CALLS - generates prompts for manual use only.
    """

    # BPM ranges based on pacing
    BPM_RANGES = {
        "slow": "60-80",
        "moderate": "80-110",
        "fast": "110-140",
        "intense": "130-160",
    }

    # Mood to key suggestions
    MOOD_KEYS = {
        "epic": "D minor",
        "hopeful": "C major",
        "melancholic": "A minor",
        "tense": "E minor",
        "triumphant": "G major",
        "mysterious": "B minor",
        "peaceful": "F major",
        "dark": "C minor",
    }

    def __init__(self):
        pass

    def generate_from_analysis(
        self,
        candidates_data: Dict[str, Any],
        target_duration_sec: int = 60,
        mood_override: Optional[str] = None,
        genre_override: Optional[str] = None,
    ) -> SunoPromptPack:
        """
        Generate a Suno prompt pack from candidates.json analysis data.

        Args:
            candidates_data: Loaded candidates.json data
            target_duration_sec: Target music duration
            mood_override: Override detected mood
            genre_override: Override genre

        Returns:
            SunoPromptPack ready to save
        """
        # Extract analysis data
        summary = candidates_data.get("summary", {})
        clips = candidates_data.get("clips", [])

        total_duration = summary.get("total_duration_sec", 60)
        avg_motion = summary.get("average_motion_score")
        scene_count = summary.get("total_scenes", 1)
        clips_with_audio = summary.get("clips_with_audio", 0)
        has_audio = clips_with_audio > 0

        # Determine pacing from motion score
        pacing = self._motion_to_pacing(avg_motion, scene_count, total_duration)

        # Determine mood (can be overridden)
        mood = mood_override or self._infer_mood(avg_motion, pacing, scene_count)

        # Genre (can be overridden)
        genre = genre_override or "cinematic"

        # Build the prompt pack
        pack = SunoPromptPack(
            target_duration_sec=target_duration_sec,
            mood=mood,
            genre=genre,
            pacing=pacing,
            average_motion_score=avg_motion,
            scene_count=scene_count,
            has_audio_in_source=has_audio,
        )

        # Set BPM range
        pack.bpm_range = self.BPM_RANGES.get(pacing, "80-110")

        # Set key suggestion
        pack.key_suggestion = self.MOOD_KEYS.get(mood.split()[0].lower(), "D minor")

        # Generate prompts
        pack.main_prompt = self._generate_main_prompt(mood, genre, pacing)
        pack.variant_prompts = self._generate_variants(mood, genre, pacing)

        # Set instruments
        pack.instruments = self._suggest_instruments(mood, genre)

        # Set section timing
        pack.sections = self._generate_sections(pacing, mood, target_duration_sec)

        # Set do/don't lists
        pack.do_list, pack.dont_list = self._generate_constraints(
            mood, genre, pacing, has_audio
        )

        return pack

    def _motion_to_pacing(
        self,
        avg_motion: Optional[float],
        scene_count: int,
        total_duration: float,
    ) -> str:
        """Convert motion analysis to pacing suggestion."""
        if avg_motion is None:
            # Default to moderate if no motion data
            return "moderate"

        # Factor in scene density (scenes per minute)
        scene_density = scene_count / max(total_duration / 60, 0.5)

        # Combine motion and scene density
        combined_score = avg_motion * 0.7 + min(scene_density / 10, 0.3) * 0.3

        if combined_score < 0.3:
            return "slow"
        elif combined_score < 0.5:
            return "moderate"
        elif combined_score < 0.7:
            return "fast"
        else:
            return "intense"

    def _infer_mood(
        self,
        avg_motion: Optional[float],
        pacing: str,
        scene_count: int,
    ) -> str:
        """Infer mood from analysis data."""
        if avg_motion is None:
            return "epic cinematic"

        # High motion + fast pacing = epic/intense
        if pacing in ["fast", "intense"]:
            if avg_motion > 0.6:
                return "epic intense"
            else:
                return "epic triumphant"

        # Low motion = more contemplative
        if pacing == "slow":
            if avg_motion < 0.3:
                return "peaceful ambient"
            else:
                return "melancholic reflective"

        # Moderate = versatile
        return "epic cinematic"

    def _generate_main_prompt(self, mood: str, genre: str, pacing: str) -> str:
        """Generate the main Suno prompt."""
        tempo_words = {
            "slow": "slow-building, contemplative",
            "moderate": "measured, evolving",
            "fast": "driving, energetic",
            "intense": "powerful, relentless",
        }

        tempo_desc = tempo_words.get(pacing, "evolving")

        return (
            f"{mood} {genre} score, {tempo_desc}, "
            f"orchestral with modern production, "
            f"cinematic trailer quality, emotional depth, "
            f"professional film soundtrack"
        )

    def _generate_variants(self, mood: str, genre: str, pacing: str) -> List[str]:
        """Generate variant prompts."""
        variants = []

        # Variant 1: More orchestral/traditional
        variants.append(
            f"{mood} orchestral score, full symphony orchestra, "
            f"strings and brass, timpani percussion, "
            f"Hans Zimmer inspired, {genre} epic"
        )

        # Variant 2: Hybrid/modern
        variants.append(
            f"{mood} hybrid {genre} soundtrack, "
            f"orchestral elements with subtle electronic textures, "
            f"modern cinematic, atmospheric pads, "
            f"trailer music production quality"
        )

        return variants

    def _suggest_instruments(self, mood: str, genre: str) -> List[str]:
        """Suggest instruments based on mood and genre."""
        base = ["Orchestral strings (violins, cellos)", "Piano"]

        mood_lower = mood.lower()

        if "epic" in mood_lower or "triumphant" in mood_lower:
            return base + [
                "Brass section (French horns, trumpets)",
                "Timpani and orchestral percussion",
                "Choir (wordless, epic)",
                "Taiko drums",
            ]
        elif "melancholic" in mood_lower or "peaceful" in mood_lower:
            return base + [
                "Solo cello",
                "Soft woodwinds (flute, clarinet)",
                "Harp",
                "Ambient pads",
            ]
        elif "tense" in mood_lower or "dark" in mood_lower:
            return base + [
                "Low brass (trombones, tuba)",
                "Tremolo strings",
                "Synth bass",
                "Prepared piano",
            ]
        else:
            return base + [
                "French horn",
                "Harp",
                "Light percussion",
            ]

    def _generate_sections(
        self,
        pacing: str,
        mood: str,
        duration_sec: int,
    ) -> List[SectionTiming]:
        """Generate section timing suggestions."""
        sections = []

        # Hook/Intro (0-20%)
        sections.append(SectionTiming(
            name="Hook / Intro",
            start_percent=0,
            end_percent=20,
            description="Establish mood, introduce main theme or texture",
            energy_level="low to medium",
        ))

        # Build (20-60%)
        sections.append(SectionTiming(
            name="Build / Development",
            start_percent=20,
            end_percent=60,
            description="Gradually increase intensity, layer instruments",
            energy_level="medium, rising",
        ))

        # Peak/Drop (60-85%)
        if "epic" in mood.lower() or pacing in ["fast", "intense"]:
            sections.append(SectionTiming(
                name="Peak / Climax",
                start_percent=60,
                end_percent=85,
                description="Maximum intensity, full orchestration, emotional peak",
                energy_level="high / peak",
            ))
        else:
            sections.append(SectionTiming(
                name="Emotional Core",
                start_percent=60,
                end_percent=85,
                description="Most emotionally impactful section, melodic focus",
                energy_level="medium-high",
            ))

        # Outro (85-100%)
        sections.append(SectionTiming(
            name="Outro / Resolution",
            start_percent=85,
            end_percent=100,
            description="Wind down, resolve tension, fade or final hit",
            energy_level="descending to low",
        ))

        return sections

    def _generate_constraints(
        self,
        mood: str,
        genre: str,
        pacing: str,
        has_audio: bool,
    ) -> tuple[List[str], List[str]]:
        """Generate do and don't lists."""
        do_list = [
            "Build emotional arc from start to finish",
            "Include dynamic range (quiet to loud sections)",
            "Use professional mixing and mastering quality",
            "Create clear melodic themes that can be remembered",
            f"Match {pacing} pacing throughout",
        ]

        dont_list = [
            "No vocals or lyrics (instrumental only)",
            "No sudden jarring transitions",
            "No overly repetitive loops without variation",
            "No lo-fi or bedroom production quality",
            "No stock music feel - make it unique",
        ]

        # Add context-specific constraints
        if not has_audio:
            do_list.append("Music must carry ALL emotional weight (no dialogue)")
            do_list.append("Sync intensity changes to anticipated visual cuts")

        if "epic" in mood.lower():
            do_list.append("Include triumphant brass moments")
            dont_list.append("No minimalist or sparse arrangements")
        elif "peaceful" in mood.lower() or "ambient" in mood.lower():
            do_list.append("Maintain calm, meditative quality")
            dont_list.append("No aggressive drums or heavy percussion")

        return do_list, dont_list


# Backward-compatible alias for tests
class MusicGenerator:
    """
    Backward-compatible alias for MusicPromptGenerator.

    Provides the interface expected by existing tests.
    """

    def __init__(self, config: Optional[Any] = None):
        self._generator = MusicPromptGenerator()
        self.config = config

    def generate_prompt_pack(
        self,
        mood: str = "epic cinematic",
        duration_sec: int = 60,
        video_themes: Optional[List[str]] = None,
        pacing: str = "moderate",
    ) -> SunoPromptPack:
        """
        Generate a Suno prompt pack.

        Args:
            mood: Overall mood/feeling
            duration_sec: Target duration in seconds
            video_themes: Optional themes from video
            pacing: slow, moderate, fast, intense

        Returns:
            SunoPromptPack
        """
        # Build mock candidates data structure
        candidates_data = {
            "summary": {
                "total_duration_sec": duration_sec,
                "average_motion_score": self._pacing_to_motion(pacing),
                "total_scenes": 5,
                "clips_with_audio": 0,
            },
            "clips": [],
        }

        pack = self._generator.generate_from_analysis(
            candidates_data=candidates_data,
            target_duration_sec=duration_sec,
            mood_override=mood,
        )

        # Override pacing-derived values with explicit pacing
        pack.pacing = pacing
        pack.bpm_range = MusicPromptGenerator.BPM_RANGES.get(pacing, "80-110")

        # Include video themes in prompt if provided
        if video_themes:
            theme_str = ", ".join(video_themes)
            pack.main_prompt = f"{mood}, themes of {theme_str}, " + pack.main_prompt.split(", ", 1)[-1]

        # Regenerate variants with mood
        pack.variant_prompts = self._generator._generate_variants(mood, "cinematic", pacing)

        return pack

    def _pacing_to_motion(self, pacing: str) -> float:
        """Convert pacing to approximate motion score."""
        return {
            "slow": 0.2,
            "moderate": 0.45,
            "fast": 0.65,
            "intense": 0.8,
        }.get(pacing, 0.45)
