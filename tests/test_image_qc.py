"""Tests for src/utils/image_qc.py — numeric grade-damage detection.

The flag logic and primitives are tested against synthetic arrays with no
ffmpeg. The discrimination matrix (does a clean grade stay silent, does a
damaged one speak) is ffmpeg-gated and builds its own fixtures, because that
property is the whole point: a QC tool that flags clean work gets ignored.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

from src.utils import image_qc

HAVE_FFMPEG = bool(shutil.which("ffmpeg"))


class WorkingSpaceTests(unittest.TestCase):
    """The ACEScct footgun: these metrics are display-referred only."""

    def test_scene_referred_space_is_refused_not_converted(self) -> None:
        for space in ("acescct", "slog3", "logc", "ACEScc", "rec2020_pq"):
            with self.subTest(space=space):
                with self.assertRaises(image_qc.ImageQcError) as ctx:
                    image_qc._check_working_space([], space)
                self.assertIn("display-referred", str(ctx.exception))

    def test_refusal_names_what_is_accepted(self) -> None:
        with self.assertRaises(image_qc.ImageQcError) as ctx:
            image_qc._check_working_space([], "acescct")
        self.assertIn("rec709", str(ctx.exception))

    def test_display_referred_spaces_pass(self) -> None:
        for space in ("rec709", "sRGB", "Rec-709", "bt709"):
            with self.subTest(space=space):
                self.assertEqual(image_qc._check_working_space([], space), [])

    def test_exactly_one_grade_source_is_required(self) -> None:
        with self.assertRaises(image_qc.ImageQcError):
            image_qc.assess_grade("/x.mov", time_seconds=0.0)  # neither
        with self.assertRaises(image_qc.ImageQcError):
            image_qc.assess_grade("/x.mov", time_seconds=0.0, graded_path="/y.mov", lut_path="/z.cube")


class PrimitiveTests(unittest.TestCase):
    def test_box_blur_preserves_a_flat_field(self) -> None:
        field = np.full((32, 32), 7.5)
        np.testing.assert_allclose(image_qc._box_blur(field, 5), field, atol=1e-9)

    def test_box_blur_averages_a_step(self) -> None:
        field = np.zeros((16, 16))
        field[:, 8:] = 10.0
        blurred = image_qc._box_blur(field, 5)
        self.assertGreater(blurred[8, 8], 0.0)  # the edge is smeared
        self.assertLess(blurred[8, 8], 10.0)

    def test_smooth_mask_finds_a_gradient_and_rejects_noise(self) -> None:
        gradient = np.tile(np.linspace(0.0, 50.0, 128), (128, 1))
        self.assertGreater(image_qc._smooth_mask(gradient).mean(), 0.9)
        rng = np.random.default_rng(0)
        noisy = gradient + rng.normal(0, 8.0, gradient.shape)
        self.assertLess(image_qc._smooth_mask(noisy).mean(), 0.3)

    def test_noise_level_rises_with_added_noise(self) -> None:
        rng = np.random.default_rng(1)
        flat = np.full((128, 128, 3), 0.5)
        noisy = np.clip(flat + rng.normal(0, 0.05, flat.shape), 0, 1)
        self.assertLess(image_qc._noise_level(flat), 1e-9)
        self.assertGreater(image_qc._noise_level(noisy), 0.01)

    def test_level_density_loss_detects_quantisation(self) -> None:
        smooth = np.tile(np.linspace(0.0, 100.0, 256), (256, 1))
        mask = np.ones_like(smooth, dtype=bool)
        self.assertAlmostEqual(image_qc._level_density_loss(smooth, smooth, mask), 0.0, places=6)
        quantised = np.round(smooth / 20.0) * 20.0
        self.assertGreater(image_qc._level_density_loss(smooth, quantised, mask), 0.9)

    def test_level_density_loss_declines_to_answer_on_a_tiny_mask(self) -> None:
        smooth = np.tile(np.linspace(0.0, 100.0, 32), (32, 1))
        mask = np.zeros_like(smooth, dtype=bool)
        mask[:2, :2] = True
        self.assertIsNone(image_qc._level_density_loss(smooth, smooth, mask))

    def test_tonal_stats_on_a_known_ramp(self) -> None:
        lab = np.zeros((100, 100, 3))
        lab[..., 0] = np.tile(np.linspace(0.0, 100.0, 100), (100, 1))
        stats = image_qc._tonal_stats(lab)
        self.assertLess(stats["black_point_L"], 2.0)
        self.assertGreater(stats["white_point_L"], 98.0)
        self.assertAlmostEqual(stats["mean_chroma"], 0.0, places=6)


class FlagLogicTests(unittest.TestCase):
    BASE = {"black_point_L": 4.0, "white_point_L": 92.0, "contrast_L_std": 25.0, "mean_chroma": 30.0}
    CLEAN_NOISE = {"overall_ratio": 1.0, "shadow_ratio": 1.0, "smooth_region_ratio": 1.0, "smooth_region_pixels": 100000}
    CLEAN_DAMAGE = {
        "clipped_fraction_source": 0.001, "clipped_fraction_result": 0.001,
        "highlight_posterization": 0.0, "smooth_region_banding": 0.0,
    }

    def _ids(self, result=None, noise=None, damage=None):
        return [
            f["id"]
            for f in image_qc._flags(
                self.BASE, result or dict(self.BASE), noise or dict(self.CLEAN_NOISE),
                damage or dict(self.CLEAN_DAMAGE),
            )
        ]

    def test_an_unchanged_grade_raises_nothing(self) -> None:
        self.assertEqual(self._ids(), [])

    def test_flat_fires_on_lost_contrast(self) -> None:
        self.assertIn("flat", self._ids(result={**self.BASE, "contrast_L_std": 15.0}))

    def test_milky_fires_on_a_lifted_black_point(self) -> None:
        self.assertIn("milky", self._ids(result={**self.BASE, "black_point_L": 20.0}))

    def test_washed_out_fires_on_chroma_collapse(self) -> None:
        self.assertIn("washed_out", self._ids(result={**self.BASE, "mean_chroma": 5.0}))

    def test_noisy_fires_on_smooth_regions_alone(self) -> None:
        # A large calm area is exactly what a whole-frame average hides.
        noise = {**self.CLEAN_NOISE, "smooth_region_ratio": 2.0}
        self.assertIn("noisy", self._ids(noise=noise))

    def test_clipped_fires_on_growth_not_on_absolute_level(self) -> None:
        # A source that was already clipped must not be blamed on the grade.
        already = {**self.CLEAN_DAMAGE, "clipped_fraction_source": 0.4, "clipped_fraction_result": 0.4}
        self.assertNotIn("clipped", self._ids(damage=already))
        grew = {**self.CLEAN_DAMAGE, "clipped_fraction_result": 0.05}
        self.assertIn("clipped", self._ids(damage=grew))

    def test_banding_and_posterization_are_separate_flags(self) -> None:
        ids = self._ids(damage={**self.CLEAN_DAMAGE, "smooth_region_banding": 0.9})
        self.assertIn("banding", ids)
        self.assertNotIn("posterized", ids)

    def test_none_measurements_do_not_raise_a_flag(self) -> None:
        # An undersized mask returns None; that must read as "not measured".
        damage = {**self.CLEAN_DAMAGE, "smooth_region_banding": None, "highlight_posterization": None}
        self.assertEqual(self._ids(damage=damage), [])

    def test_every_flag_carries_a_remedy(self) -> None:
        flags = image_qc._flags(
            self.BASE,
            {"black_point_L": 25.0, "white_point_L": 99.0, "contrast_L_std": 10.0, "mean_chroma": 2.0},
            {"overall_ratio": 3.0, "shadow_ratio": 3.0, "smooth_region_ratio": 3.0, "smooth_region_pixels": 100000},
            {"clipped_fraction_source": 0.0, "clipped_fraction_result": 0.5,
             "highlight_posterization": 0.9, "smooth_region_banding": 0.9},
        )
        self.assertGreaterEqual(len(flags), 6)
        for entry in flags:
            self.assertTrue(entry["remedy"], entry)
            self.assertTrue(entry["detail"], entry)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not on PATH")
class DiscriminationTests(unittest.TestCase):
    """A clean grade must stay silent, or nobody will trust the flags."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.mkdtemp(prefix="image_qc_")
        sky, ground = os.path.join(cls.tmp, "sky.png"), os.path.join(cls.tmp, "ground.png")
        cls.src = os.path.join(cls.tmp, "src.png")
        # A source with a smooth gradient (banding-prone) and mid-tone texture,
        # deliberately kept clear of white so a gentle grade cannot clip it.
        cls._ff(["-f", "lavfi", "-i", "gradients=s=480x180:c0=0x0d1420:c1=0x7a94b8:x0=0:y0=0:x1=0:y1=180:d=1:n=2",
                 "-frames:v", "1", sky])
        cls._ff(["-f", "lavfi", "-i", "testsrc2=s=480x90:d=1", "-vf",
                 "eq=contrast=0.55:brightness=-0.06,noise=alls=6:allf=t", "-frames:v", "1", ground])
        cls._ff(["-i", sky, "-i", ground, "-filter_complex", "[0:v][1:v]vstack=inputs=2",
                 "-frames:v", "1", cls.src])

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def _ff(args) -> None:
        subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True, timeout=120)

    def _graded(self, name: str, vf: str) -> str:
        path = os.path.join(self.tmp, f"{name}.png")
        self._ff(["-i", self.src, "-vf", vf, path])
        return path

    def _flags_for(self, vf: str, name: str):
        report = image_qc.assess_grade(self.src, graded_path=self._graded(name, vf), time_seconds=0.0)
        return [f["id"] for f in report["flags"]], report

    def test_identity_grade_is_acceptable_with_zero_shift(self) -> None:
        report = image_qc.assess_grade(self.src, graded_path=self.src, time_seconds=0.0)
        self.assertTrue(report["acceptable"], report["flags"])
        self.assertAlmostEqual(report["grade_shift_delta_e2000"], 0.0, places=6)

    def test_gentle_grades_raise_nothing(self) -> None:
        for name, vf in (
            ("warm", "colorbalance=rm=0.04:bm=-0.03,eq=saturation=1.06"),
            ("lift", "eq=gamma=1.06:contrast=1.04"),
        ):
            with self.subTest(grade=name):
                ids, report = self._flags_for(vf, name)
                self.assertEqual(ids, [], report)
                self.assertTrue(report["acceptable"])

    def test_crushing_grade_reports_clipping(self) -> None:
        ids, _ = self._flags_for("eq=contrast=2.8:brightness=0.30", "crushed")
        self.assertIn("clipped", ids)

    def test_quantising_grade_reports_banding(self) -> None:
        ids, _ = self._flags_for(
            "lutrgb=r='bitand(val,224)':g='bitand(val,224)':b='bitand(val,224)'", "banded"
        )
        self.assertIn("banding", ids)

    def test_desaturating_grade_reports_washed_out(self) -> None:
        ids, _ = self._flags_for("eq=saturation=0.15", "grey")
        self.assertIn("washed_out", ids)

    def test_flattening_grade_reports_flat_and_milky(self) -> None:
        ids, _ = self._flags_for(
            "eq=contrast=0.55,colorlevels=rimin=-0.12:gimin=-0.12:bimin=-0.12", "milky"
        )
        self.assertIn("flat", ids)
        self.assertIn("milky", ids)

    def test_measurements_are_stable_across_repeated_runs(self) -> None:
        graded = self._graded("stable", "eq=gamma=1.06")
        first = image_qc.assess_grade(self.src, graded_path=graded, time_seconds=0.0)
        second = image_qc.assess_grade(self.src, graded_path=graded, time_seconds=0.0)
        self.assertEqual(first["source"], second["source"])
        self.assertEqual(first["result"], second["result"])
        self.assertEqual(first["damage"], second["damage"])
        self.assertEqual(first["grade_shift_delta_e2000"], second["grade_shift_delta_e2000"])

    def test_report_says_it_measured_the_real_frame(self) -> None:
        report = image_qc.assess_grade(self.src, graded_path=self.src, time_seconds=0.0)
        self.assertEqual(report["basis"], "rendered_file")
        self.assertIn("not on a simulated", report["measurement"]["note"])

    def test_missing_file_is_refused_clearly(self) -> None:
        with self.assertRaises(image_qc.ImageQcError) as ctx:
            image_qc.assess_grade(self.src, graded_path="/nope/missing.png", time_seconds=0.0)
        self.assertIn("not found", str(ctx.exception))


class VisionEscalationTests(unittest.TestCase):
    """The gate that keeps a clean grade free."""

    def _report(self, flags=(), shift=0.0):
        return {"flags": [{"id": f} for f in flags], "grade_shift_delta_e2000": shift}

    def test_numeric_tier_never_escalates(self) -> None:
        for flags, shift in (((), 0.0), (("banding",), 30.0), (("clipped",), 2.0)):
            decision = image_qc.vision_escalation(self._report(flags, shift), cost_tier="numeric")
            self.assertFalse(decision["escalate"])

    def test_vision_always_tier_always_escalates(self) -> None:
        decision = image_qc.vision_escalation(self._report(), cost_tier="vision_always")
        self.assertTrue(decision["escalate"])

    def test_clean_grade_costs_nothing_by_default(self) -> None:
        decision = image_qc.vision_escalation(self._report(shift=1.2))
        self.assertFalse(decision["escalate"])
        self.assertIn("clean grade", decision["reason"])

    def test_unflagged_but_large_move_escalates(self) -> None:
        # "Undamaged" is not "good" — this is the case numbers cannot settle.
        decision = image_qc.vision_escalation(self._report(shift=image_qc.DOUBT_SHIFT_DELTA_E + 1))
        self.assertTrue(decision["escalate"])
        self.assertIn("undamaged is not the same as good", decision["reason"])

    def test_content_dependent_flags_escalate(self) -> None:
        for flag in ("banding", "washed_out", "flat"):
            with self.subTest(flag=flag):
                decision = image_qc.vision_escalation(self._report((flag,)))
                self.assertTrue(decision["escalate"])
                self.assertEqual(decision["triggering_flags"], [flag])

    def test_unambiguous_damage_does_not_buy_a_vision_call(self) -> None:
        # Clipping and posterization are damage wherever they appear.
        for flag in ("clipped", "posterized", "noisy", "milky"):
            with self.subTest(flag=flag):
                decision = image_qc.vision_escalation(self._report((flag,), shift=20.0))
                self.assertFalse(decision["escalate"], decision)

    def test_unknown_tier_is_refused(self) -> None:
        with self.assertRaises(image_qc.ImageQcError):
            image_qc.vision_escalation(self._report(), cost_tier="cheap")

    def test_default_tier_is_the_recommended_one(self) -> None:
        self.assertEqual(image_qc.DEFAULT_COST_TIER, "vision_on_doubt")
        self.assertIn(image_qc.DEFAULT_COST_TIER, image_qc.COST_TIERS)


if __name__ == "__main__":
    unittest.main()
