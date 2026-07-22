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

    def test_build_args_single_stream_uses_af(self) -> None:
        args = silence_ripple.build_silencedetect_args(
            "/media/a.mov", 2.0, 10.0,
            threshold_db=-30.0, min_duration_sec=0.4, audio_streams=1,
        )
        self.assertIn("-af", args)
        self.assertNotIn("-filter_complex", args)
        self.assertIn("-vn", args)
        self.assertIn("silencedetect=noise=-30.0dB:d=0.4", args)

    def test_build_args_multi_stream_merges_all_channels(self) -> None:
        """Production MXF: one mono stream per channel — a dead scratch channel
        must not read as all-silence, so every stream is merged first."""
        args = silence_ripple.build_silencedetect_args(
            "/media/a.mxf", 0.0, 20.0,
            threshold_db=-30.0, min_duration_sec=0.4, audio_streams=5,
        )
        idx = args.index("-filter_complex")
        graph = args[idx + 1]
        self.assertEqual(
            graph,
            "[0:a:0][0:a:1][0:a:2][0:a:3][0:a:4]amerge=inputs=5,"
            "silencedetect=noise=-30.0dB:d=0.4",
        )
        self.assertNotIn("-af", args)


if __name__ == "__main__":
    unittest.main()
