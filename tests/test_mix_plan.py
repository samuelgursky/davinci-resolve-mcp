"""The rough-mix planner, and the claim that makes it worth having: it measures itself.

Gain arithmetic is easy to get right on paper and easy to be wrong about in the file. So
the tests that matter here run real ffmpeg over generated tones and assert the *achieved*
integrated loudness, not the plan's intent — plus the three ways the result is allowed to
be bad (off target, over true peak, clipped) and the guarantee that none of them are
silently corrected.

Fixtures are synthesised in-test: a gated tone standing in for speech with real gaps, and
a continuous tone standing in for a music bed. No media is committed.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import mix_plan  # noqa: E402

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

HAVE_NUMPY = np is not None
HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
REQUIREMENTS = "numpy, ffmpeg and ffprobe required"


class TestParsing(unittest.TestCase):
    SUMMARY = """
[Parsed_ebur128_0 @ 0x1] t: 11.9  TARGET:-23 LUFS  M: -27.8 S: -27.8  I: -27.8 LUFS  LRA: 0.0 LU  TPK: -27.1 -27.1 dBFS
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -19.4 LUFS
    Threshold: -29.4 LUFS

  Loudness range:
    LRA:         3.7 LU

  True peak:
    Peak:      -2.5 dBFS
"""

    # Today's ffmpeg prints the summary last, so a naive "last match wins" parse happens
    # to be right. This fixture puts a progress line AFTER it — the ordering change that
    # would silently turn a delivery measurement into a per-frame reading.
    TRAILING_PROGRESS = SUMMARY + (
        "[Parsed_ebur128_0 @ 0x1] t: 12.0  TARGET:-23 LUFS  M: -40.0 S: -40.0  "
        "I: -40.0 LUFS  LRA: 9.9 LU  TPK: -40.0 -40.0 dBFS\n"
    )

    def test_reads_the_summary_not_the_progress_lines(self):
        """The progress line also carries `I:` and `LRA:` — reading it would be wrong."""
        parsed = mix_plan.parse_loudness(self.SUMMARY)
        self.assertEqual(parsed["integrated_lufs"], -19.4)
        self.assertEqual(parsed["loudness_range_lu"], 3.7)
        self.assertEqual(parsed["true_peak_dbtp"], -2.5)

    def test_a_progress_line_after_the_summary_does_not_win(self):
        parsed = mix_plan.parse_loudness(self.TRAILING_PROGRESS)
        self.assertEqual(parsed["integrated_lufs"], -19.4)
        self.assertEqual(parsed["loudness_range_lu"], 3.7)

    def test_missing_summary_yields_none_rather_than_a_guess(self):
        parsed = mix_plan.parse_loudness("ffmpeg: no audio streams\n")
        self.assertIsNone(parsed["integrated_lufs"])

    def test_agrees_with_the_media_analysis_parser(self):
        """The regexes are duplicated so this module stays light; pin them together."""
        from src.utils import media_analysis

        theirs = media_analysis._parse_loudness(self.SUMMARY)
        mine = mix_plan.parse_loudness(self.SUMMARY)
        for key in ("integrated_lufs", "loudness_range_lu"):
            self.assertEqual(mine[key], theirs[key], key)


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestDuckEnvelope(unittest.TestCase):
    RATE = mix_plan.SAMPLE_RATE

    def test_unity_outside_the_windows(self):
        envelope = mix_plan.duck_envelope(
            self.RATE * 4, [{"start": 1.0, "end": 2.0}],
            duck_db=-6.0, attack_s=0.1, release_s=0.1)
        self.assertAlmostEqual(envelope[0], 1.0)
        self.assertAlmostEqual(envelope[-1], 1.0)

    def test_floor_inside_the_windows(self):
        envelope = mix_plan.duck_envelope(
            self.RATE * 4, [{"start": 1.0, "end": 2.0}],
            duck_db=-6.0, attack_s=0.1, release_s=0.1)
        floor = 10 ** (-6.0 / 20.0)
        middle = envelope[int(1.5 * self.RATE)]
        self.assertAlmostEqual(middle, floor, places=6)

    def test_the_bed_is_already_down_when_the_window_opens(self):
        """Starting the ramp at the window means ducking under the first syllable."""
        envelope = mix_plan.duck_envelope(
            self.RATE * 4, [{"start": 1.0, "end": 2.0}],
            duck_db=-6.0, attack_s=0.2, release_s=0.2)
        floor = 10 ** (-6.0 / 20.0)
        self.assertAlmostEqual(envelope[int(1.0 * self.RATE)], floor, places=5)
        self.assertGreater(envelope[int(0.7 * self.RATE)], floor)

    def test_ramps_are_monotonic(self):
        envelope = mix_plan.duck_envelope(
            self.RATE * 4, [{"start": 1.0, "end": 2.0}],
            duck_db=-9.0, attack_s=0.2, release_s=0.3)
        attack = envelope[int(0.8 * self.RATE):int(1.0 * self.RATE)]
        release = envelope[int(2.0 * self.RATE):int(2.3 * self.RATE)]
        self.assertTrue(np.all(np.diff(attack) <= 1e-9))
        self.assertTrue(np.all(np.diff(release) >= -1e-9))

    def test_zero_duck_is_a_flat_envelope(self):
        envelope = mix_plan.duck_envelope(
            self.RATE, [{"start": 0.1, "end": 0.5}],
            duck_db=0.0, attack_s=0.05, release_s=0.05)
        self.assertAlmostEqual(float(envelope.min()), 1.0)

    def test_windows_outside_the_buffer_do_not_raise(self):
        envelope = mix_plan.duck_envelope(
            self.RATE, [{"start": 5.0, "end": 6.0}],
            duck_db=-6.0, attack_s=0.1, release_s=0.1)
        self.assertEqual(len(envelope), self.RATE)


class TestRegionMerging(unittest.TestCase):
    def test_short_gaps_are_bridged(self):
        merged = mix_plan._merge_regions(
            [{"start": 0.0, "end": 1.0}, {"start": 1.2, "end": 2.0}], hold=0.35)
        self.assertEqual(merged, [{"start": 0.0, "end": 2.0}])

    def test_long_gaps_are_kept(self):
        merged = mix_plan._merge_regions(
            [{"start": 0.0, "end": 1.0}, {"start": 3.0, "end": 4.0}], hold=0.35)
        self.assertEqual(len(merged), 2)

    def test_unsorted_input_is_handled(self):
        merged = mix_plan._merge_regions(
            [{"start": 3.0, "end": 4.0}, {"start": 0.0, "end": 1.0}], hold=0.35)
        self.assertEqual(merged[0]["start"], 0.0)


@unittest.skipUnless(HAVE_FFMPEG and HAVE_NUMPY, REQUIREMENTS)
class TestEndToEnd(unittest.TestCase):
    """Real ffmpeg, real measurement. The plan being right on paper is not the claim."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="mix_plan_test_")
        cls.dialogue = os.path.join(cls.dir, "dialogue.wav")
        cls.music = os.path.join(cls.dir, "music.wav")
        # 1.6s of tone every 3s: four "sentences" with real silence between them.
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             "sine=frequency=220:duration=12:sample_rate=48000",
             "-af", "volume='0.25*between(mod(t,3),0,1.6)':eval=frame",
             "-ac", "2", cls.dialogue],
            check=True, capture_output=True)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=12:sample_rate=48000",
             "-af", "volume=0.5", "-ac", "2", cls.music],
            check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _out(self, name):
        return os.path.join(self.dir, name)

    def test_measure_returns_all_three_numbers(self):
        measured = mix_plan.measure(self.music)
        self.assertIsNotNone(measured["integrated_lufs"])
        self.assertIsNotNone(measured["true_peak_dbtp"])
        self.assertIsNotNone(measured["loudness_range_lu"])

    def test_measure_refuses_a_file_with_no_audio(self):
        empty = self._out("empty.wav")
        pathlib.Path(empty).write_bytes(b"")
        with self.assertRaises(mix_plan.MixPlanError):
            mix_plan.measure(empty)

    def test_dialogue_gain_lands_the_stem_on_target(self):
        planned = mix_plan.plan([self.dialogue], standard="web")
        measured = float(planned["dialogue"]["anchor_measured_lufs"])
        self.assertAlmostEqual(planned["dialogue"]["gain_db"], -16.0 - measured, places=1)

    def test_ducking_windows_follow_the_speech(self):
        planned = mix_plan.plan([self.dialogue], music=[self.music])
        windows = planned["ducking"]["windows"]
        self.assertEqual(len(windows), 4, windows)
        for window in windows:
            self.assertGreater(window["end"] - window["start"], 1.0)
        # The gaps are real silence, not ducked.
        self.assertLess(planned["ducking"]["ducked_fraction"], 0.75)

    def test_plan_renders_nothing(self):
        before = sorted(os.listdir(self.dir))
        result = mix_plan.plan([self.dialogue], music=[self.music])
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["renders"])
        self.assertNotIn("premix_path", result)
        self.assertEqual(sorted(os.listdir(self.dir)), before)

    def test_render_hits_the_target_and_says_so_from_measurement(self):
        result = mix_plan.render([self.dialogue], music=[self.music],
                                 standard="web", output_path=self._out("web.wav"))
        self.assertTrue(os.path.isfile(result["premix_path"]))
        self.assertAlmostEqual(result["achieved"]["integrated_lufs"], -16.0, delta=2.0)
        self.assertEqual(result["flags"], [])
        self.assertTrue(result["on_target"])

    def test_achieved_is_measured_not_derived(self):
        """Re-measuring the written file independently must agree with the report."""
        result = mix_plan.render([self.dialogue], music=[self.music],
                                 standard="web", output_path=self._out("check.wav"))
        independent = mix_plan.measure(result["premix_path"])
        self.assertEqual(independent["integrated_lufs"],
                         result["achieved"]["integrated_lufs"])

    def test_program_trim_lands_a_full_programme_standard(self):
        """A hot bed puts the programme above target; the measured trim brings it back."""
        result = mix_plan.render(
            [self.dialogue], music=[self.music], standard="ebu_r128",
            bed_offset_lu=0.0, duck_db=0.0, output_path=self._out("r128.wav"))
        self.assertTrue(result["program_normalize"]["applied"])
        self.assertNotEqual(result["program_normalize"]["trim_db"], 0.0)
        self.assertAlmostEqual(result["achieved"]["integrated_lufs"], -23.0, delta=0.5)
        self.assertEqual(result["flags"], [])

    def test_dialogue_gated_standard_is_never_programme_trimmed(self):
        """Trimming there would move the dialogue off the figure being graded."""
        result = mix_plan.render(
            [self.dialogue], music=[self.music], standard="ott_dialogue_gated",
            bed_offset_lu=0.0, duck_db=0.0, output_path=self._out("gated.wav"))
        self.assertFalse(result["program_normalize"]["applied"])
        self.assertIn("dialogue-gated", result["program_normalize"]["reason"])

    def test_program_normalize_can_be_turned_off(self):
        result = mix_plan.render(
            [self.dialogue], music=[self.music], standard="ebu_r128",
            bed_offset_lu=0.0, duck_db=0.0, program_normalize=False,
            output_path=self._out("nonorm.wav"))
        self.assertFalse(result["program_normalize"]["applied"])
        self.assertIn("loudness_off_target", [flag["id"] for flag in result["flags"]])

    def test_clipping_is_reported_not_silently_normalised(self):
        result = mix_plan.render(
            [self.dialogue], music=[self.music], target_lufs=6.0,
            bed_offset_lu=0.0, duck_db=0.0, program_normalize=False,
            output_path=self._out("clip.wav"))
        ids = [flag["id"] for flag in result["flags"]]
        self.assertIn("clipped", ids)
        self.assertGreater(result["achieved"]["clipped_samples"], 0)
        self.assertFalse(result["on_target"])

    def test_true_peak_overshoot_is_flagged(self):
        result = mix_plan.render(
            [self.dialogue], music=[self.music], target_lufs=0.0,
            bed_offset_lu=0.0, duck_db=0.0, program_normalize=False,
            output_path=self._out("peak.wav"))
        self.assertIn("true_peak_over", [flag["id"] for flag in result["flags"]])

    def test_every_flag_carries_a_remedy(self):
        result = mix_plan.render(
            [self.dialogue], music=[self.music], target_lufs=6.0,
            bed_offset_lu=0.0, duck_db=0.0, program_normalize=False,
            output_path=self._out("remedy.wav"))
        for flag in result["flags"]:
            self.assertTrue(flag["remedy"].strip(), flag["id"])

    def test_premix_is_not_written_beside_the_source_by_default(self):
        result = mix_plan.render([self.dialogue], music=[self.music])
        self.addCleanup(shutil.rmtree, os.path.dirname(result["premix_path"]),
                        ignore_errors=True)
        self.assertNotEqual(os.path.dirname(result["premix_path"]),
                            os.path.dirname(self.dialogue))

    def test_no_dialogue_is_refused(self):
        with self.assertRaises(mix_plan.MixPlanError) as caught:
            mix_plan.plan([], music=[self.music])
        self.assertIn("anchored", str(caught.exception))

    def test_unknown_standard_lists_the_real_ones(self):
        with self.assertRaises(mix_plan.MixPlanError) as caught:
            mix_plan.plan([self.dialogue], standard="not-a-standard")
        self.assertIn("ebu_r128", str(caught.exception))

    def test_missing_file_is_refused(self):
        with self.assertRaises(mix_plan.MixPlanError):
            mix_plan.plan([os.path.join(self.dir, "nope.wav")])

    def test_the_loudest_dialogue_stem_is_the_anchor(self):
        quiet = self._out("quiet.wav")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", self.dialogue,
             "-af", "volume=-12dB", quiet], check=True, capture_output=True)
        planned = mix_plan.plan([quiet, self.dialogue])
        self.assertEqual(planned["dialogue"]["anchor_path"], self.dialogue)


class TestToolSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import types

        fake = types.ModuleType("DaVinciResolveScript")
        fake.scriptapp = lambda *a, **k: None
        sys.modules.setdefault("DaVinciResolveScript", fake)
        from src import server

        cls.server = server

    def _call(self, **kwargs):
        import asyncio
        import inspect

        result = self.server.media_analysis(**kwargs)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result

    def test_capabilities_lists_the_standards(self):
        result = self._call(action="mix_plan_capabilities")
        self.assertTrue(result["success"])
        self.assertIn("ebu_r128", result["standards"])

    def test_missing_dialogue_is_a_structured_error(self):
        result = self._call(action="mix_plan", params={})
        self.assertEqual(result["error"]["code"], "MIX_PLAN_REFUSED")

    def test_measure_loudness_requires_a_path(self):
        result = self._call(action="measure_loudness", params={})
        self.assertIn("path", result["error"]["message"])

    def test_runs_without_a_resolve_connection(self):
        calls = []
        original = self.server.get_resolve
        self.server.get_resolve = lambda *a, **k: calls.append(1) or None
        try:
            self._call(action="mix_plan_capabilities")
        finally:
            self.server.get_resolve = original
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
