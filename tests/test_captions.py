"""Tests for src/utils/captions.py — broadcast caption rules.

The caps are the contract. A caption file that violates them fails QC, so these
assert the invariants hold for generated output rather than checking a golden
string that would need rewriting on every tuning change.
"""

from __future__ import annotations

import re
import unittest

from src.utils import captions


def speak(text: str, *, start: float = 0.0, rate: float = 0.35, gap_after: dict | None = None):
    """Lay words out at a steady rate; `gap_after` injects pauses by index."""
    gap_after = gap_after or {}
    words, cursor = [], start
    for index, token in enumerate(text.split()):
        words.append({"word": token, "start_seconds": round(cursor, 3), "end_seconds": round(cursor + rate * 0.8, 3)})
        cursor += rate + gap_after.get(index, 0.0)
    return words


LONG = (
    "The harbour was quiet that morning, and the boats had not yet gone out. "
    "We waited on the wall until the light came up over the far headland. "
    "Nobody spoke for a while. Then the first engine started somewhere behind us."
)


class BlockRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blocks = captions.build_blocks(speak(LONG))

    def test_no_line_exceeds_the_character_cap(self) -> None:
        for block in self.blocks:
            for line in block["lines"]:
                self.assertLessEqual(len(line), captions.DEFAULT_MAX_CHARS_PER_LINE, line)

    def test_no_block_exceeds_the_line_cap(self) -> None:
        for block in self.blocks:
            self.assertLessEqual(len(block["lines"]), captions.DEFAULT_MAX_LINES, block)

    def test_no_block_exceeds_the_duration_cap(self) -> None:
        for block in self.blocks:
            self.assertLessEqual(block["duration_seconds"], captions.DEFAULT_MAX_BLOCK_SECONDS + 0.01, block)

    def test_blocks_are_ordered_and_never_overlap(self) -> None:
        for previous, following in zip(self.blocks, self.blocks[1:]):
            self.assertLessEqual(previous["end_seconds"], following["start_seconds"], (previous, following))

    def test_minimum_gap_is_respected(self) -> None:
        for previous, following in zip(self.blocks, self.blocks[1:]):
            gap = following["start_seconds"] - previous["end_seconds"]
            self.assertGreaterEqual(round(gap, 3), captions.DEFAULT_MIN_GAP_SECONDS - 1e-6)

    def test_every_block_has_positive_duration(self) -> None:
        for block in self.blocks:
            self.assertGreater(block["duration_seconds"], 0.0, block)

    def test_no_words_are_dropped(self) -> None:
        spoken = " ".join(w["word"] for w in speak(LONG))
        captioned = " ".join(" ".join(b["lines"]) for b in self.blocks)
        self.assertEqual(captioned.split(), spoken.split())

    def test_timings_come_from_the_words_not_interpolation(self) -> None:
        words = speak(LONG)
        starts = {w["start_seconds"] for w in words}
        for block in self.blocks:
            self.assertIn(block["start_seconds"], starts, block)

    def test_a_short_utterance_is_extended_to_a_readable_minimum(self) -> None:
        blocks = captions.build_blocks(speak("Yes.", rate=0.12))
        self.assertGreaterEqual(blocks[0]["duration_seconds"], captions.DEFAULT_MIN_BLOCK_SECONDS - 1e-6)

    def test_a_long_pause_forces_a_break(self) -> None:
        words = speak("one two three four five six", gap_after={2: 2.0})
        blocks = captions.build_blocks(words, max_chars_per_line=60, max_lines=2)
        self.assertGreater(len(blocks), 1)
        self.assertEqual(blocks[0]["lines"][-1].split()[-1], "three")

    def test_sentence_end_breaks_even_when_short(self) -> None:
        blocks = captions.build_blocks(speak("Stop. Now we go on to the next thing"))
        self.assertEqual(blocks[0]["lines"][0], "Stop.")

    def test_no_single_word_orphan_line(self) -> None:
        for block in captions.build_blocks(speak(LONG), max_chars_per_line=20):
            if len(block["lines"]) > 1 and len(" ".join(block["lines"]).split()) > 3:
                self.assertGreater(len(block["lines"][-1].split()), 1, block)

    def test_untimed_and_empty_words_are_skipped(self) -> None:
        words = [{"word": "hello", "start_seconds": 0.0, "end_seconds": 0.4},
                 {"word": "x"}, {"word": "   ", "start_seconds": 1.0}]
        blocks = captions.build_blocks(words)
        self.assertEqual(" ".join(blocks[0]["lines"]), "hello")

    def test_empty_input_yields_no_blocks(self) -> None:
        self.assertEqual(captions.build_blocks([]), [])


class ParameterRefusalTests(unittest.TestCase):
    def test_absurd_line_cap_is_refused(self) -> None:
        with self.assertRaises(captions.CaptionError):
            captions.build_blocks(speak("a b c"), max_chars_per_line=4)

    def test_zero_lines_is_refused(self) -> None:
        with self.assertRaises(captions.CaptionError):
            captions.build_blocks(speak("a b c"), max_lines=0)

    def test_inverted_duration_bounds_are_refused(self) -> None:
        with self.assertRaises(captions.CaptionError):
            captions.build_blocks(speak("a b c"), min_block_seconds=9.0, max_block_seconds=2.0)

    def test_unknown_format_is_refused(self) -> None:
        with self.assertRaises(captions.CaptionError):
            captions.render([], "ass")


class SerialisationTests(unittest.TestCase):
    SRT_CUE = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}$")
    VTT_CUE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}$")

    def setUp(self) -> None:
        self.blocks = captions.build_blocks(speak(LONG))

    def test_srt_is_numbered_from_one_with_comma_timestamps(self) -> None:
        lines = captions.to_srt(self.blocks).splitlines()
        self.assertEqual(lines[0], "1")
        self.assertTrue(self.SRT_CUE.match(lines[1]), lines[1])
        indices = [int(l) for l in lines if l.isdigit() and lines[lines.index(l) + 1].count("-->")]
        self.assertEqual(indices, list(range(1, len(self.blocks) + 1)))

    def test_vtt_has_the_required_header_and_dot_timestamps(self) -> None:
        lines = captions.to_vtt(self.blocks).splitlines()
        self.assertEqual(lines[0], "WEBVTT")
        cues = [l for l in lines if "-->" in l]
        self.assertTrue(all(self.VTT_CUE.match(c) for c in cues), cues[:2])
        self.assertEqual(len(cues), len(self.blocks))

    def test_timestamp_formatting_over_an_hour(self) -> None:
        self.assertEqual(captions._timestamp(3661.5, comma=True), "01:01:01,500")
        self.assertEqual(captions._timestamp(3661.5, comma=False), "01:01:01.500")

    def test_timestamp_rounding_does_not_emit_1000_millis(self) -> None:
        self.assertEqual(captions._timestamp(1.9999, comma=True), "00:00:02,000")

    def test_negative_time_clamps_to_zero(self) -> None:
        self.assertEqual(captions._timestamp(-5.0, comma=True), "00:00:00,000")


class ChapterTests(unittest.TestCase):
    def test_chapters_always_start_at_zero(self) -> None:
        words = speak(LONG, gap_after={12: 40.0, 24: 40.0})
        chapters = captions.chapters_from_blocks(captions.build_blocks(words))
        self.assertEqual(chapters[0]["start_seconds"], 0.0)

    def test_minimum_spacing_is_respected(self) -> None:
        words = speak(LONG, gap_after={4: 40.0, 6: 40.0})
        chapters = captions.chapters_from_blocks(captions.build_blocks(words), min_spacing_seconds=30.0)
        for previous, following in zip(chapters, chapters[1:]):
            self.assertGreaterEqual(following["start_seconds"] - previous["start_seconds"], 30.0)

    def test_youtube_text_starts_at_zero_zero(self) -> None:
        words = speak(LONG, gap_after={12: 40.0})
        text = captions.chapters_to_youtube(
            captions.chapters_from_blocks(captions.build_blocks(words))
        )
        self.assertTrue(text.startswith("0:00 "), text[:40])

    def test_youtube_stamps_gain_an_hour_field_past_3600s(self) -> None:
        text = captions.chapters_to_youtube([
            {"start_seconds": 0.0, "title": "start"},
            {"start_seconds": 3725.0, "title": "later"},
        ])
        self.assertIn("1:02:05 later", text)

    def test_no_blocks_yields_no_chapters(self) -> None:
        self.assertEqual(captions.chapters_from_blocks([]), [])


class GenerateTests(unittest.TestCase):
    def test_generate_returns_text_and_blocks(self) -> None:
        result = captions.generate(speak(LONG), fmt="srt")
        self.assertTrue(result["success"])
        self.assertEqual(result["block_count"], len(result["blocks"]))
        self.assertIn("-->", result["text"])

    def test_generate_with_chapters(self) -> None:
        result = captions.generate(speak(LONG, gap_after={12: 40.0}), with_chapters=True)
        self.assertTrue(result["chapters"])
        self.assertTrue(result["chapters_youtube"].startswith("0:00"))

    def test_generate_refuses_an_empty_transcript_with_remediation(self) -> None:
        result = captions.generate([])
        self.assertFalse(result["success"])
        self.assertIn("transcription", result["remediation"])

    def test_generate_passes_options_through(self) -> None:
        result = captions.generate(speak(LONG), max_chars_per_line=20)
        for block in result["blocks"]:
            for line in block["lines"]:
                self.assertLessEqual(len(line), 20)


if __name__ == "__main__":
    unittest.main()
