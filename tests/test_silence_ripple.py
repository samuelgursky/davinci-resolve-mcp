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


class CalibrationArgsTests(unittest.TestCase):
    """The calibration pass must see the same signal detection will see."""

    def test_astats_pass_merges_streams_exactly_like_detection(self) -> None:
        # A gate measured on stream 0 while detection runs on the merge would be
        # calibrated against the wrong signal — the MXF regression this guards.
        cal = silence_ripple.build_audio_filter_args(
            "/media/a.mxf", 0.0, 20.0, "astats", audio_streams=5
        )
        det = silence_ripple.build_silencedetect_args(
            "/media/a.mxf", 0.0, 20.0,
            threshold_db=-30.0, min_duration_sec=0.4, audio_streams=5,
        )
        cal_graph = cal[cal.index("-filter_complex") + 1]
        det_graph = det[det.index("-filter_complex") + 1]
        merge = "[0:a:0][0:a:1][0:a:2][0:a:3][0:a:4]amerge=inputs=5,"
        self.assertTrue(cal_graph.startswith(merge), cal_graph)
        self.assertTrue(det_graph.startswith(merge), det_graph)

    def test_astats_pass_skips_video_decode(self) -> None:
        args = silence_ripple.build_audio_filter_args("/media/a.mxf", 0.0, 20.0, "astats", audio_streams=1)
        self.assertIn("-vn", args)


class AstatsParsingTests(unittest.TestCase):
    # ffmpeg spells the trough "RMS through". Real output shape.
    SUMMARY = (
        "[Parsed_astats_0 @ 0x1] Overall\n"
        "[Parsed_astats_0 @ 0x1] Peak level dB: -30.060426\n"
        "[Parsed_astats_0 @ 0x1] RMS level dB: -37.017982\n"
        "[Parsed_astats_0 @ 0x1] RMS peak dB: -33.049694\n"
        "[Parsed_astats_0 @ 0x1] RMS through dB: -56.060286\n"
        "[Parsed_astats_0 @ 0x1] Noise floor dB: -57.053577\n"
    )

    def test_parses_trough_and_peak(self) -> None:
        quiet, loud = silence_ripple._parse_astats_levels(self.SUMMARY)
        self.assertAlmostEqual(quiet, -56.060286, places=4)
        self.assertAlmostEqual(loud, -33.049694, places=4)

    def test_accepts_a_corrected_trough_spelling(self) -> None:
        quiet, _ = silence_ripple._parse_astats_levels(
            self.SUMMARY.replace("RMS through", "RMS trough")
        )
        self.assertAlmostEqual(quiet, -56.060286, places=4)

    def test_digital_silence_parses_as_negative_infinity(self) -> None:
        quiet, _ = silence_ripple._parse_astats_levels(
            self.SUMMARY.replace("RMS through dB: -56.060286", "RMS through dB: -inf")
        )
        self.assertEqual(quiet, float("-inf"))

    def test_missing_levels_parse_to_none(self) -> None:
        self.assertEqual(silence_ripple._parse_astats_levels("nothing here"), (None, None))


class GatePolicyTests(unittest.TestCase):
    """Level → gate policy, exercised without ffmpeg."""

    def test_gate_lands_inside_the_measured_working_band(self) -> None:
        # Fixture-measured: silencedetect resolves these correctly across
        # -46..-32 dB. Both readings come from an identical noise bed, so the
        # gate must land in the same place for both.
        for quiet, loud in ((-56.06, -33.05), (-56.12, -33.05)):
            cal = silence_ripple._gate_from_levels(quiet, loud)
            with self.subTest(quiet=quiet):
                self.assertTrue(cal.usable)
                self.assertEqual(cal.basis, "measured_dynamics")
                self.assertGreater(cal.gate_db, -46.0)
                self.assertLess(cal.gate_db, -32.0)

    def test_gate_is_biased_above_the_bracket_midpoint(self) -> None:
        # silencedetect compares instantaneous amplitude, astats windowed RMS —
        # a midpoint gate hugs the bottom of the usable band.
        cal = silence_ripple._gate_from_levels(-60.0, -20.0)
        self.assertGreater(cal.gate_db, (-60.0 + -20.0) / 2)

    def test_unseparated_levels_are_unusable_not_defaulted_into(self) -> None:
        # A constant-level programme: no threshold separates speech from room.
        cal = silence_ripple._gate_from_levels(-33.1, -30.1)
        self.assertFalse(cal.usable)
        self.assertEqual(cal.basis, "fallback_default")
        self.assertIn("apart", cal.reason)

    def test_digital_silence_gates_under_the_programme(self) -> None:
        cal = silence_ripple._gate_from_levels(float("-inf"), -33.05)
        self.assertTrue(cal.usable)
        self.assertEqual(cal.basis, "digital_silence")
        self.assertLess(cal.gate_db, -33.05)

    def test_gate_is_clamped_to_the_credible_band(self) -> None:
        very_quiet = silence_ripple._gate_from_levels(-120.0, -100.0)
        self.assertGreaterEqual(very_quiet.gate_db, silence_ripple.GATE_MIN_DB)
        very_loud = silence_ripple._gate_from_levels(-20.0, 0.0)
        self.assertLessEqual(very_loud.gate_db, silence_ripple.GATE_MAX_DB)

    def test_unmeasurable_levels_fall_back_with_a_reason(self) -> None:
        for quiet, loud in ((None, None), (-56.0, None), (-56.0, float("-inf"))):
            cal = silence_ripple._gate_from_levels(quiet, loud)
            with self.subTest(quiet=quiet, loud=loud):
                self.assertFalse(cal.usable)
                self.assertEqual(cal.gate_db, silence_ripple.DEFAULT_THRESHOLD_DB)
                self.assertTrue(cal.reason)  # a skip is never silent

    def test_every_unusable_outcome_reports_why(self) -> None:
        cal = silence_ripple.calibrate_silence_gate("/nope/missing.wav", 0.0, 10.0)
        self.assertFalse(cal.usable)
        self.assertIn("not readable", cal.reason)
        self.assertFalse(silence_ripple.calibrate_silence_gate("/nope/missing.wav", 5.0, 5.0).usable)

    def test_as_dict_drops_non_finite_values(self) -> None:
        payload = silence_ripple._gate_from_levels(float("-inf"), -33.0).as_dict()
        self.assertIsNone(payload["quiet_rms_db"])
        self.assertTrue(payload["quiet_is_digital_silence"])
        self.assertIsNone(payload["separation_db"])  # inf is not JSON-safe


class SpeechGuardBandTests(unittest.TestCase):
    """Guards that keep a removed silence from eating the speech on either side.

    These shipped as pre_head=0 / post_tail=1 frame — effectively no guard — and
    nothing asserted them, so the defect was invisible to the suite. Reviewers of
    the first public tutorial for this project heard it directly: "the first
    split seconds of your clips are trimmed so the audio is a bit cut off."

    The mechanism is asymmetric and the tests below pin both halves:
      * pre_head protects the OUTGOING word's decay (silencedetect marks the
        silence start once amplitude drops under the gate, while the tail and
        room reverb are still audible below it).
      * post_tail protects the INCOMING word's onset (silencedetect marks the
        silence end once amplitude climbs back over the gate, which for a soft
        attack happens *after* the word has actually begun).
    """

    FPS = 24.0

    def test_guard_defaults_are_non_zero(self) -> None:
        self.assertGreater(
            silence_ripple.DEFAULT_PRE_HEAD_FRAMES, 0,
            "pre_head of 0 strips a word's decay; the cut sounds abrupt.",
        )
        self.assertGreater(
            silence_ripple.DEFAULT_POST_TAIL_FRAMES, 0,
            "post_tail of 0 strips the next word's attack.",
        )

    def test_onset_guard_is_the_larger_of_the_two(self) -> None:
        """An eaten onset is more audible than an eaten decay — protect it more."""
        self.assertGreaterEqual(
            silence_ripple.DEFAULT_POST_TAIL_FRAMES,
            silence_ripple.DEFAULT_PRE_HEAD_FRAMES,
        )

    def test_defaults_never_reach_the_speech_on_either_side(self) -> None:
        """The exact defect: with the old defaults the strip touched the onset."""
        word_ends, word_starts = 10.0, 12.0  # detected silence == [10.0, 12.0]
        pre = silence_ripple.frames_to_seconds(silence_ripple.DEFAULT_PRE_HEAD_FRAMES, self.FPS)
        post = silence_ripple.frames_to_seconds(silence_ripple.DEFAULT_POST_TAIL_FRAMES, self.FPS)
        strip = silence_ripple.apply_silence_handles(
            [(word_ends, word_starts)],
            pre_head_sec=pre,
            post_tail_sec=post,
            range_start=0.0,
            range_end=20.0,
        )
        self.assertEqual(len(strip), 1)
        strip_start, strip_end = strip[0]
        self.assertGreater(
            strip_start, word_ends,
            "strip begins at the outgoing word's decay — that audio is removed",
        )
        self.assertLess(
            strip_end, word_starts,
            "strip runs up to the incoming word's onset — the attack is clipped",
        )

    def test_guards_survive_into_keep_segments(self) -> None:
        """Guarding the strip is pointless if the keep-segment math undoes it."""
        pre = silence_ripple.frames_to_seconds(silence_ripple.DEFAULT_PRE_HEAD_FRAMES, self.FPS)
        post = silence_ripple.frames_to_seconds(silence_ripple.DEFAULT_POST_TAIL_FRAMES, self.FPS)
        strip = silence_ripple.apply_silence_handles(
            [(10.0, 12.0)], pre_head_sec=pre, post_tail_sec=post,
            range_start=0.0, range_end=20.0,
        )
        keep = silence_ripple.silence_to_keep_segments(0.0, 20.0, strip)
        self.assertEqual(len(keep), 2)
        self.assertGreater(keep[0][1], 10.0, "kept audio must extend past the word's end")
        self.assertLess(keep[1][0], 12.0, "kept audio must start before the next word's onset")

    def test_a_silence_shorter_than_its_guards_is_left_alone(self) -> None:
        """Better to leave a short gap in than to cut into speech on both sides."""
        pre = silence_ripple.frames_to_seconds(silence_ripple.DEFAULT_PRE_HEAD_FRAMES, self.FPS)
        post = silence_ripple.frames_to_seconds(silence_ripple.DEFAULT_POST_TAIL_FRAMES, self.FPS)
        tiny = (10.0, 10.0 + (pre + post) / 2.0)
        strip = silence_ripple.apply_silence_handles(
            [tiny], pre_head_sec=pre, post_tail_sec=post,
            range_start=0.0, range_end=20.0,
        )
        self.assertEqual(strip, [], "guards overlapped; nothing should be removed")


if __name__ == "__main__":
    unittest.main()
