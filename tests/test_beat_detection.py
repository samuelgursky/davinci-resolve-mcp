"""Tests for beat detection and beat-driven cut planning.

The grouping and cut-planning layers are pure, so they are tested without
librosa. The detector itself is exercised only for its refusal path, because a
real tempo track needs real audio and this suite runs offline.
"""

from __future__ import annotations

import unittest

from src.utils import beat_detection as bd

#: A clean 120 BPM grid: one beat every 0.5s, 32 beats = 8 bars of 4.
GRID = [round(i * 0.5, 4) for i in range(32)]


class GroupingTests(unittest.TestCase):
    def test_bars_fall_every_four_beats(self) -> None:
        out = bd.group_into_phrases(GRID)
        self.assertEqual(out["downbeats"][:3], [0.0, 2.0, 4.0])
        self.assertEqual(out["bar_count"], 8)

    def test_a_phrase_is_eight_bars_by_default(self) -> None:
        out = bd.group_into_phrases(GRID)
        self.assertEqual(out["phrase_starts"], [0.0])
        self.assertEqual(out["phrase_count"], 1)

    def test_shorter_phrases_produce_more_boundaries(self) -> None:
        out = bd.group_into_phrases(GRID, bars_per_phrase=2)
        self.assertEqual(out["phrase_starts"], [0.0, 4.0, 8.0, 12.0])

    def test_three_four_time_is_respected(self) -> None:
        """Silently forcing 3/4 into 4 puts phrase boundaries in wrong places."""
        out = bd.group_into_phrases(GRID, beats_per_bar=3)
        self.assertEqual(out["downbeats"][:3], [0.0, 1.5, 3.0])

    def test_beat_offset_shifts_the_downbeat_for_a_pickup(self) -> None:
        out = bd.group_into_phrases(GRID, beat_offset=1)
        self.assertEqual(out["downbeats"][:3], [0.5, 2.5, 4.5])

    def test_the_inference_is_declared_not_hidden(self) -> None:
        self.assertIn("INFERRED", bd.group_into_phrases(GRID)["note"])

    def test_unsorted_input_is_handled(self) -> None:
        out = bd.group_into_phrases(list(reversed(GRID)))
        self.assertEqual(out["downbeats"][:2], [0.0, 2.0])

    def test_nonsense_meters_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            bd.group_into_phrases(GRID, beats_per_bar=0)


class CutPlanTests(unittest.TestCase):
    def test_phrase_is_the_default_mode(self) -> None:
        """Music resolves at phrase boundaries; that is where a cut feels inevitable."""
        self.assertEqual(bd.plan_beat_cuts(GRID, fps=24)["mode"], "phrase")

    def test_beat_mode_cuts_on_every_beat(self) -> None:
        self.assertEqual(bd.plan_beat_cuts(GRID, fps=24, mode="beat")["cut_count"], 32)

    def test_bar_mode_cuts_on_downbeats(self) -> None:
        self.assertEqual(bd.plan_beat_cuts(GRID, fps=24, mode="bar")["cut_count"], 8)

    def test_cuts_are_snapped_to_whole_frames(self) -> None:
        frames = bd.plan_beat_cuts(GRID, fps=24, mode="beat")["cut_frames"]
        self.assertTrue(all(isinstance(f, int) for f in frames))
        self.assertEqual(frames[:3], [0, 12, 24])  # 0.5s @ 24fps = 12 frames

    def test_snapping_is_correct_at_a_fractional_rate(self) -> None:
        self.assertEqual(bd.snap_to_frames([1.0], 23.976), [24])

    def test_min_shot_drops_cuts_and_says_how_many(self) -> None:
        """Silent truncation would read as 'that is the whole grid'."""
        out = bd.plan_beat_cuts(GRID, fps=24, mode="beat", min_shot_seconds=1.0)
        self.assertEqual(out["cut_count"], 16)
        self.assertEqual(out["dropped_for_min_shot"], 16)
        self.assertIn("dropped", out["note"])

    def test_an_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            bd.plan_beat_cuts(GRID, fps=24, mode="vibes")

    def test_a_zero_fps_is_rejected_rather_than_dividing_by_zero(self) -> None:
        with self.assertRaises(ValueError):
            bd.snap_to_frames([1.0], 0)

    def test_the_output_does_not_claim_to_be_an_assembly(self) -> None:
        self.assertIn("not an assembly", bd.plan_beat_cuts(GRID, fps=24)["note"])


class ConfidenceTests(unittest.TestCase):
    def test_a_steady_grid_reads_as_high_confidence(self) -> None:
        self.assertEqual(bd._confidence(GRID, None)["band"], "high")

    def test_an_irregular_pulse_reads_as_low_and_says_why(self) -> None:
        ragged = [0.0, 0.5, 1.9, 2.0, 3.7, 4.0, 6.2]
        out = bd._confidence(ragged, None)
        self.assertEqual(out["band"], "low")
        self.assertIn("irregular", out["reason"])

    def test_too_few_beats_is_low_confidence_not_high(self) -> None:
        self.assertEqual(bd._confidence([0.0, 0.5], None)["band"], "low")


class DependencyTests(unittest.TestCase):
    def test_absence_of_librosa_is_an_honest_refusal(self) -> None:
        """A fabricated tempo produces cuts that are confidently, rhythmically
        wrong — worse than no feature, because the failure looks intentional."""
        real = bd.librosa_available
        bd.librosa_available = lambda: False
        try:
            out = bd.detect_beats("/nonexistent.wav")
        finally:
            bd.librosa_available = real
        self.assertFalse(out["success"])
        self.assertIn("librosa", out["error"])
        self.assertIn("pip install librosa", out["remediation"])

    def test_a_missing_file_fails_cleanly_when_librosa_is_present(self) -> None:
        if not bd.librosa_available():
            self.skipTest("librosa not installed")
        out = bd.detect_beats("/definitely/not/here.wav")
        self.assertFalse(out["success"])


if __name__ == "__main__":
    unittest.main()
