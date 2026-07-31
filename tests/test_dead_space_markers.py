"""Tests for the dead-space review gate and the tightness control.

Both exist because of the same failure. Asked to "mark all the spots with dead
space with a red marker so I can review and then approve," an agent had no verb
to call: `plan_silence_ripple` produces a tightened variant, and the marker plan
in `media_analysis` marks shots on a clip. So it improvised its own detection,
placed markers on "pretty random spots," missed the obvious gaps, and the editor
cut by hand instead. The detection was never the problem — the calibrated gate
was simply never reached.
"""

from __future__ import annotations

import unittest

from src.utils import edit_engine as ee
from src.utils import silence_ripple as sr


class TightnessTests(unittest.TestCase):
    BASE = dict(
        pre_head_frames=sr.DEFAULT_PRE_HEAD_FRAMES,
        post_tail_frames=sr.DEFAULT_POST_TAIL_FRAMES,
        min_strip_frames=sr.DEFAULT_MIN_STRIP_FRAMES,
    )

    def test_default_is_the_loosest_preset(self) -> None:
        """A first assembly is supposed to be long. The default must reflect that."""
        self.assertEqual(sr.DEFAULT_TIGHTNESS, "generous")
        generous = sr.apply_tightness(tightness=None, **self.BASE)
        balanced = sr.apply_tightness(tightness="balanced", **self.BASE)
        self.assertEqual(generous["tightness"], "generous")
        self.assertGreater(generous["min_strip_frames"], balanced["min_strip_frames"])
        self.assertGreater(generous["post_tail_frames"], balanced["post_tail_frames"])

    def test_tight_removes_more_gaps_but_never_more_speech(self) -> None:
        """The guard floor is not a knob — that is the point of having one."""
        tight = sr.apply_tightness(tightness="tight", **self.BASE)
        balanced = sr.apply_tightness(tightness="balanced", **self.BASE)
        self.assertLess(tight["min_strip_frames"], balanced["min_strip_frames"])
        self.assertGreaterEqual(tight["pre_head_frames"], sr.DEFAULT_PRE_HEAD_FRAMES)
        self.assertGreaterEqual(tight["post_tail_frames"], sr.DEFAULT_POST_TAIL_FRAMES)

    def test_unknown_tightness_is_rejected_not_defaulted(self) -> None:
        """Quietly giving someone 'generous' when they asked for 'aggressive'
        would hand them cuts they did not ask for and tell them nothing."""
        with self.assertRaises(ValueError) as ctx:
            sr.apply_tightness(tightness="aggressive", **self.BASE)
        self.assertIn("aggressive", str(ctx.exception))
        for name in sr.TIGHTNESS_PRESETS:
            self.assertIn(name, str(ctx.exception))

    def test_every_preset_is_orderable(self) -> None:
        seen = [
            sr.apply_tightness(tightness=n, **self.BASE)["min_strip_frames"]
            for n in ("tight", "balanced", "generous")
        ]
        self.assertEqual(seen, sorted(seen), "presets must be monotonic tight→generous")


class MarginalCalibrationTests(unittest.TestCase):
    """Yellow vs red: a usable gate is not automatically a confident one."""

    @staticmethod
    def _cal(separation, usable=True):
        return sr.NoiseCalibration(
            gate_db=-40.0, basis="measured_dynamics", usable=usable,
            separation_db=separation,
        )

    def test_a_gate_barely_over_the_floor_is_marginal(self) -> None:
        self.assertTrue(ee._calibration_is_marginal(self._cal(sr.MIN_SEPARATION_DB + 1.0)))

    def test_a_well_separated_gate_is_confident(self) -> None:
        self.assertFalse(ee._calibration_is_marginal(self._cal(sr.MIN_SEPARATION_DB + 30.0)))

    def test_absent_or_unusable_calibration_is_not_marginal(self) -> None:
        # None == the caller supplied an explicit threshold; nothing was measured,
        # so there is no confidence to report either way.
        self.assertFalse(ee._calibration_is_marginal(None))
        self.assertFalse(ee._calibration_is_marginal(self._cal(13.0, usable=False)))

    def test_non_finite_separation_does_not_crash_or_lie(self) -> None:
        self.assertFalse(ee._calibration_is_marginal(self._cal(float("inf"))))
        self.assertFalse(ee._calibration_is_marginal(self._cal(None)))


class DeadSpaceMarkerContractTests(unittest.TestCase):
    """The parts of the contract that hold without ffmpeg or a live Resolve."""

    def test_no_items_is_an_error_not_an_empty_success(self) -> None:
        """An empty marker list would read as 'this timeline is clean'."""
        out = ee.plan_dead_space_markers(
            "/tmp", items=[], timeline_name="T", timeline_fps=24.0
        )
        self.assertFalse(out["success"])
        self.assertIn("No timeline items", out["error"])

    def test_bad_tightness_fails_before_touching_media(self) -> None:
        out = ee.plan_dead_space_markers(
            "/tmp", items=[{"timeline_start_frame": 0, "timeline_end_frame": 24}],
            timeline_name="T", timeline_fps=24.0, tightness="nope",
        )
        self.assertFalse(out["success"])
        self.assertIn("unknown tightness", out["error"])

    def test_the_planner_is_review_only(self) -> None:
        """It must not expose an execute path — markers are the deliverable."""
        self.assertFalse(hasattr(ee, "execute_dead_space_markers"))

    def test_marker_colors_are_distinct(self) -> None:
        self.assertNotEqual(
            ee.DEAD_SPACE_MARKER_COLOR, ee.DEAD_SPACE_UNCERTAIN_MARKER_COLOR
        )


if __name__ == "__main__":
    unittest.main()
