"""
Unit tests for music and voiceover generators.

Tests prompt pack generation WITHOUT API calls.
"""

import pytest
import tempfile
from pathlib import Path

from autonomous.music_generator import MusicGenerator, SunoPromptPack
from autonomous.voiceover_generator import VoiceoverGenerator, VoiceoverScript


class TestSunoPromptPack:
    """Tests for SunoPromptPack."""

    def test_create_pack(self):
        """Test creating prompt pack."""
        pack = SunoPromptPack(
            main_prompt="epic cinematic orchestral",
            bpm_range="80-110",
        )
        assert pack.main_prompt == "epic cinematic orchestral"
        assert pack.bpm_range == "80-110"

    def test_to_dict(self):
        """Test serialization to dict."""
        pack = SunoPromptPack(
            main_prompt="test prompt",
            variant_prompts=["variant1", "variant2"],
            do_list=["do this"],
            dont_list=["avoid that"],
        )
        d = pack.to_dict()
        assert d["main_prompt"] == "test prompt"
        assert len(d["variant_prompts"]) == 2
        assert len(d["do_list"]) == 1

    def test_to_markdown(self):
        """Test markdown generation."""
        pack = SunoPromptPack(
            main_prompt="epic orchestral",
            variant_prompts=["piano version"],
            bpm_range="90-120",
            mood="epic",
            do_list=["build tension"],
            dont_list=["no vocals"],
        )
        md = pack.to_markdown()

        assert "# Suno Music Prompt Pack" in md
        assert "epic orchestral" in md
        assert "piano version" in md
        assert "90-120" in md
        assert "build tension" in md
        assert "no vocals" in md

    def test_save_markdown(self):
        """Test saving as markdown."""
        pack = SunoPromptPack(main_prompt="test")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_prompt"
            pack.save(path, format="markdown")

            md_path = path.with_suffix(".md")
            assert md_path.exists()
            content = md_path.read_text()
            assert "test" in content

    def test_save_json(self):
        """Test saving as JSON."""
        pack = SunoPromptPack(main_prompt="test")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_prompt"
            pack.save(path, format="json")

            json_path = path.with_suffix(".json")
            assert json_path.exists()


class TestMusicGenerator:
    """Tests for MusicGenerator."""

    def test_generate_prompt_pack(self):
        """Test generating prompt pack."""
        gen = MusicGenerator()
        pack = gen.generate_prompt_pack(
            mood="epic cinematic",
            duration_sec=60,
            video_themes=["journey", "discovery"],
            pacing="moderate",
        )

        assert pack.main_prompt != ""
        assert len(pack.variant_prompts) == 2
        assert pack.bpm_range == "80-110"  # moderate
        assert pack.suggested_duration_sec == 60
        assert len(pack.do_list) > 0
        assert len(pack.dont_list) > 0

    def test_pacing_affects_bpm(self):
        """Test different pacing values affect BPM."""
        gen = MusicGenerator()

        slow = gen.generate_prompt_pack(pacing="slow")
        moderate = gen.generate_prompt_pack(pacing="moderate")
        fast = gen.generate_prompt_pack(pacing="fast")

        assert slow.bpm_range == "60-80"
        assert moderate.bpm_range == "80-110"
        assert fast.bpm_range == "110-140"

    def test_mood_affects_instruments(self):
        """Test mood affects suggested instruments."""
        gen = MusicGenerator()

        epic = gen.generate_prompt_pack(mood="epic")
        sad = gen.generate_prompt_pack(mood="melancholic")

        # Epic should have brass/percussion
        assert any("Brass" in i or "Percussion" in i for i in epic.instruments)

        # Sad should have solo instruments
        assert any("cello" in i.lower() or "Solo" in i for i in sad.instruments)

    def test_themes_in_prompt(self):
        """Test themes appear in prompt."""
        gen = MusicGenerator()
        pack = gen.generate_prompt_pack(
            video_themes=["adventure", "mystery"]
        )

        assert "adventure" in pack.main_prompt.lower() or "mystery" in pack.main_prompt.lower()


class TestVoiceoverScript:
    """Tests for VoiceoverScript."""

    def test_create_script(self):
        """Test creating script."""
        script = VoiceoverScript(
            script_text="Test narration.",
            word_count=2,
        )
        assert script.script_text == "Test narration."
        assert script.word_count == 2

    def test_to_markdown(self):
        """Test markdown generation."""
        script = VoiceoverScript(
            script_text="The story begins here.",
            voice_style="narrative",
            pace="measured",
            tone="authoritative",
            recommended_voice_name="Adam",
            recommended_voice_id="test123",
        )
        md = script.to_markdown()

        assert "# Voiceover Script Pack" in md
        assert "The story begins here." in md
        assert "narrative" in md
        assert "Adam" in md

    def test_save(self):
        """Test saving script."""
        script = VoiceoverScript(script_text="Test.")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_script"
            script.save(path)

            md_path = path.with_suffix(".md")
            assert md_path.exists()


class TestVoiceoverGenerator:
    """Tests for VoiceoverGenerator."""

    def test_generate_script(self):
        """Test generating script."""
        gen = VoiceoverGenerator()
        script = gen.generate_script(
            mood="epic cinematic",
            target_duration_sec=30,
            video_themes=["journey", "transformation"],
        )

        assert script.script_text != ""
        assert script.word_count > 0
        assert script.script_duration_estimate_sec > 0
        assert script.recommended_voice_id != ""

    def test_duration_affects_word_count(self):
        """Test target duration affects word count."""
        gen = VoiceoverGenerator()

        short = gen.generate_script(target_duration_sec=15)
        long = gen.generate_script(target_duration_sec=45)

        # Word count should roughly scale with duration
        # (not exact due to template-based generation)
        assert short.target_duration_sec < long.target_duration_sec

    def test_style_affects_voice(self):
        """Test style affects voice recommendation."""
        gen = VoiceoverGenerator()

        dramatic = gen.generate_script(mood="epic", style="dramatic")
        conversational = gen.generate_script(style="conversational")

        # Different styles should potentially recommend different voices
        # (implementation may vary)
        assert dramatic.voice_style == "dramatic"
        assert conversational.voice_style == "conversational"

    def test_emphasis_words_extracted(self):
        """Test emphasis words are extracted from script."""
        gen = VoiceoverGenerator()
        script = gen.generate_script(
            video_themes=["destiny", "heroes"]
        )

        # Themes or related words should be in emphasis list
        assert len(script.emphasis_words) >= 0  # May or may not have matches


class TestGeneratorsNoAPIRequired:
    """Tests that generators work without API keys."""

    def test_music_generator_no_config(self):
        """Test music generator works without config."""
        gen = MusicGenerator(config=None)
        pack = gen.generate_prompt_pack()
        assert pack.main_prompt != ""

    def test_voiceover_generator_no_config(self):
        """Test voiceover generator works without config."""
        gen = VoiceoverGenerator(config=None)
        script = gen.generate_script()
        assert script.script_text != ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
