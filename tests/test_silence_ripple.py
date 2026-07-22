"""Unit tests for src/utils/silence_ripple.py (waveform ripple-delete helpers)."""

from __future__ import annotations

import unittest

from src.utils import silence_ripple


class SilenceRippleLogicTests(unittest.TestCase):
    def test_apply_handles_shrink_strip_region(self) -> None:
        silences = [(10.0, 12.0)]
        strip = silence_ripple.apply_silence_handles(
            silences,
            pre_head_sec=0.0,
            post_tail_sec=1 / 30.0,
            range_start=0.0,
            range_end=20.0,
        )
        self.assertEqual(len(strip), 1)
        self.assertAlmostEqual(strip[0][0], 10.0)
        self.assertAlmostEqual(strip[0][1], 12.0 - 1 / 30.0, places=5)

    def test_silence_to_keep_segments(self) -> None:
        keep = silence_ripple.silence_to_keep_segments(
            0.0, 20.0, [(9.5, 19.75)], min_keep_sec=0.05
        )
        self.assertEqual(keep, [(0.0, 9.5), (19.75, 20.0)])

    def test_frames_to_seconds(self) -> None:
        self.assertAlmostEqual(silence_ripple.frames_to_seconds(10, 30.0), 1 / 3.0)


if __name__ == "__main__":
    unittest.main()
