"""
Voiceover Generator - Script generation for ElevenLabs.

Default mode: Generate voiceover script pack (no API calls).
Optional: Use ElevenLabs API if key is available and mode is "api".
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path
import json

logger = logging.getLogger("autonomous.voiceover_generator")


@dataclass
class VoiceoverScript:
    """A complete voiceover script pack for ElevenLabs."""

    # The script itself
    script_text: str = ""
    script_duration_estimate_sec: float = 0.0  # ~150 words per minute

    # Delivery notes for ElevenLabs
    voice_style: str = "narrative"  # narrative, dramatic, conversational
    pace: str = "measured"  # slow, measured, energetic
    tone: str = "authoritative"  # warm, authoritative, mysterious
    emphasis_words: List[str] = field(default_factory=list)
    pause_markers: List[str] = field(default_factory=list)  # Timestamps for pauses

    # ElevenLabs settings recommendations
    stability: float = 0.5
    similarity_boost: float = 0.75
    recommended_voice_id: str = ""
    recommended_voice_name: str = ""

    # Metadata
    target_duration_sec: float = 30.0
    word_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "script_text": self.script_text,
            "script_duration_estimate_sec": self.script_duration_estimate_sec,
            "voice_style": self.voice_style,
            "pace": self.pace,
            "tone": self.tone,
            "emphasis_words": self.emphasis_words,
            "pause_markers": self.pause_markers,
            "stability": self.stability,
            "similarity_boost": self.similarity_boost,
            "recommended_voice_id": self.recommended_voice_id,
            "recommended_voice_name": self.recommended_voice_name,
            "target_duration_sec": self.target_duration_sec,
            "word_count": self.word_count,
        }

    def to_markdown(self) -> str:
        """Generate human-readable markdown script pack."""
        lines = [
            "# Voiceover Script Pack",
            "",
            "## Script",
            "```",
            self.script_text,
            "```",
            "",
            f"**Word Count:** {self.word_count}",
            f"**Estimated Duration:** {self.script_duration_estimate_sec:.1f} seconds",
            "",
            "## Delivery Notes",
            f"- **Voice Style:** {self.voice_style}",
            f"- **Pace:** {self.pace}",
            f"- **Tone:** {self.tone}",
            "",
        ]

        if self.emphasis_words:
            lines.append("### Words to Emphasize")
            for word in self.emphasis_words:
                lines.append(f"- {word}")
            lines.append("")

        if self.pause_markers:
            lines.append("### Pause Points")
            for marker in self.pause_markers:
                lines.append(f"- {marker}")
            lines.append("")

        lines.extend([
            "## ElevenLabs Settings",
            f"- **Recommended Voice:** {self.recommended_voice_name} (`{self.recommended_voice_id}`)",
            f"- **Stability:** {self.stability}",
            f"- **Similarity Boost:** {self.similarity_boost}",
            "",
            "## Voice Selection Guide",
            "For cinematic narration, consider:",
            "- **Adam** (deep, authoritative) - `pNInz6obpgDQGcFmaJgB`",
            "- **Antoni** (warm, storyteller) - `ErXwobaYiN019PkySvjV`",
            "- **Josh** (young, energetic) - `TxGEqnHWrfWFTfGW9XjX`",
            "- **Rachel** (calm, professional) - `21m00Tcm4TlvDq8ikWAM`",
            "",
        ])

        return "\n".join(lines)

    def save(self, path: Path, format: str = "markdown") -> None:
        """Save script pack to file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if format == "json":
            with open(path.with_suffix(".json"), "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
        else:
            with open(path.with_suffix(".md"), "w", encoding="utf-8") as f:
                f.write(self.to_markdown())

        logger.info(f"Saved voiceover script to: {path}")


class VoiceoverGenerator:
    """
    Generates voiceover script packs for ElevenLabs.

    Default: Human-in-the-loop mode - generates scripts for manual use.
    Optional: API mode if ELEVENLABS_API_KEY is available.
    """

    # Average speaking rate: ~150 words per minute = 2.5 words per second
    WORDS_PER_SECOND = 2.5

    def __init__(self, config: Optional[Any] = None):
        self.config = config

    def generate_script(
        self,
        mood: str = "epic cinematic",
        target_duration_sec: float = 30.0,
        video_themes: Optional[List[str]] = None,
        style: str = "narrative",
    ) -> VoiceoverScript:
        """
        Generate a voiceover script based on video analysis.

        Args:
            mood: Overall mood/feeling
            target_duration_sec: Target duration (20-45 seconds typical)
            video_themes: Themes detected from video analysis
            style: Script style (narrative, dramatic, conversational)

        Returns:
            VoiceoverScript ready for manual use or API submission
        """
        themes = video_themes or ["journey", "discovery", "transformation"]

        # Calculate target word count
        target_words = int(target_duration_sec * self.WORDS_PER_SECOND)

        # Generate script based on mood and themes
        script = self._generate_script_text(mood, themes, target_words, style)

        # Count actual words
        word_count = len(script.split())
        duration_estimate = word_count / self.WORDS_PER_SECOND

        # Determine voice settings based on style
        voice_settings = self._get_voice_settings(style, mood)

        # Extract emphasis words
        emphasis_words = self._extract_emphasis_words(script, themes)

        return VoiceoverScript(
            script_text=script,
            script_duration_estimate_sec=duration_estimate,
            voice_style=style,
            pace=voice_settings["pace"],
            tone=voice_settings["tone"],
            emphasis_words=emphasis_words,
            stability=voice_settings["stability"],
            similarity_boost=voice_settings["similarity_boost"],
            recommended_voice_id=voice_settings["voice_id"],
            recommended_voice_name=voice_settings["voice_name"],
            target_duration_sec=target_duration_sec,
            word_count=word_count,
        )

    def _generate_script_text(
        self,
        mood: str,
        themes: List[str],
        target_words: int,
        style: str,
    ) -> str:
        """Generate script text based on parameters."""
        # This is a template-based generation
        # In a full implementation, this could use LLM for more variety

        mood_lower = mood.lower()

        # Select opening based on mood
        if "epic" in mood_lower:
            opening = "In a world where every moment shapes destiny..."
        elif "melanchol" in mood_lower or "sad" in mood_lower:
            opening = "Some stories are written in silence..."
        elif "hopeful" in mood_lower:
            opening = "There are moments that define who we become..."
        elif "tense" in mood_lower or "suspense" in mood_lower:
            opening = "When darkness falls, heroes rise..."
        else:
            opening = "Every journey begins with a single step..."

        # Build middle based on themes
        theme_sentences = []
        for theme in themes[:3]:  # Use up to 3 themes
            theme_lower = theme.lower()
            if "journey" in theme_lower:
                theme_sentences.append("Through trials and triumph, the path unfolds.")
            elif "discover" in theme_lower:
                theme_sentences.append("What was hidden now reveals itself.")
            elif "transform" in theme_lower:
                theme_sentences.append("Change is not just inevitable—it is essential.")
            elif "nature" in theme_lower:
                theme_sentences.append("The natural world holds secrets beyond imagination.")
            elif "human" in theme_lower:
                theme_sentences.append("In every face, a story waiting to be told.")
            else:
                theme_sentences.append(f"The essence of {theme} lives within us all.")

        middle = " ".join(theme_sentences)

        # Select closing based on style
        if style == "dramatic":
            closing = "This is where legends are born."
        elif style == "conversational":
            closing = "And that changes everything."
        else:  # narrative
            closing = "The story continues."

        # Combine and check word count
        full_script = f"{opening} {middle} {closing}"
        current_words = len(full_script.split())

        # Adjust if needed (simple approach - could be more sophisticated)
        if current_words < target_words * 0.8:
            # Add filler sentence
            full_script = f"{opening} {middle} Every moment matters. {closing}"

        return full_script

    def _get_voice_settings(self, style: str, mood: str) -> Dict[str, Any]:
        """Get recommended voice settings based on style and mood."""
        mood_lower = mood.lower()

        if style == "dramatic" or "epic" in mood_lower:
            return {
                "voice_id": "pNInz6obpgDQGcFmaJgB",
                "voice_name": "Adam",
                "pace": "measured",
                "tone": "authoritative",
                "stability": 0.6,
                "similarity_boost": 0.8,
            }
        elif style == "conversational":
            return {
                "voice_id": "ErXwobaYiN019PkySvjV",
                "voice_name": "Antoni",
                "pace": "natural",
                "tone": "warm",
                "stability": 0.4,
                "similarity_boost": 0.7,
            }
        elif "melanchol" in mood_lower or "sad" in mood_lower:
            return {
                "voice_id": "21m00Tcm4TlvDq8ikWAM",
                "voice_name": "Rachel",
                "pace": "slow",
                "tone": "reflective",
                "stability": 0.7,
                "similarity_boost": 0.6,
            }
        else:  # default narrative
            return {
                "voice_id": "pNInz6obpgDQGcFmaJgB",
                "voice_name": "Adam",
                "pace": "measured",
                "tone": "narrative",
                "stability": 0.5,
                "similarity_boost": 0.75,
            }

    def _extract_emphasis_words(self, script: str, themes: List[str]) -> List[str]:
        """Extract words that should be emphasized in delivery."""
        emphasis = []

        # Add theme-related words
        script_lower = script.lower()
        for theme in themes:
            if theme.lower() in script_lower:
                emphasis.append(theme)

        # Add common emphasis words
        power_words = ["destiny", "legend", "heroes", "essential", "triumph", "secrets"]
        for word in power_words:
            if word in script_lower:
                emphasis.append(word)

        return list(set(emphasis))[:5]  # Limit to 5

    async def generate_with_api(self, script: VoiceoverScript) -> Optional[str]:
        """
        Generate voiceover using ElevenLabs API (if available).

        Returns path to generated audio file, or None if API unavailable.
        """
        if not self.config or not self.config.should_use_api("elevenlabs"):
            logger.info("ElevenLabs API not available - use script manually")
            return None

        # TODO: Implement ElevenLabs API integration in Milestone 4
        logger.warning("ElevenLabs API integration not yet implemented")
        return None
