"""The grade retry ladder and the `.cube` arithmetic underneath it.

The ladder's whole value is that it refuses to ship damage, so most of these tests are
about the refusal rather than the success: a flagged result must never come back
acceptable, an exhausted ladder must say `needs_human`, and a strength that passes one
sampled frame must not pass on that alone.

Ladder logic is tested against a stubbed assessor so it runs everywhere and cannot be
fooled by a lucky frame. Two end-to-end cases then run the real ffmpeg path — one that
converges after backing off, one that never converges — because the arithmetic being
right and the pixels agreeing are different claims.
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

from src.utils import cube_lut, grade_loop  # noqa: E402

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

HAVE_NUMPY = np is not None
HAVE_FFMPEG = shutil.which("ffmpeg") is not None


# ── .cube arithmetic ─────────────────────────────────────────────────────────


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestCubeLut(unittest.TestCase):
    SIZE = 13

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cube_test_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.identity = cube_lut.identity_table(self.SIZE)

    def _look(self, gamma=0.8):
        table = self.identity.copy()
        table[:, 0] = np.clip(self.identity[:, 0] ** gamma, 0, 1)
        return table

    def test_round_trip_preserves_values(self):
        path = os.path.join(self.dir, "look.cube")
        cube_lut.write_cube(path, self._look(), self.SIZE, title="Look")
        parsed = cube_lut.read_cube(path)
        self.assertEqual(parsed["size"], self.SIZE)
        self.assertEqual(parsed["title"], "Look")
        self.assertLess(float(np.abs(parsed["table"] - self._look()).max()), 1e-5)

    def test_identity_is_a_no_op_through_the_sampler(self):
        points = np.linspace(0, 1, 40).repeat(3).reshape(-1, 3)
        sampled = cube_lut.sample(self.identity, self.SIZE, points)
        self.assertLess(float(np.abs(sampled - points).max()), 1e-9)

    def test_full_strength_returns_the_table_unchanged(self):
        """Not merely close: a caller asking for no attenuation must get no change."""
        look = self._look()
        self.assertTrue(np.array_equal(
            cube_lut.blend_toward_identity(look, self.SIZE, 1.0), look))

    def test_zero_strength_is_exact_identity(self):
        blended = cube_lut.blend_toward_identity(self._look(), self.SIZE, 0.0)
        self.assertLess(float(np.abs(blended - self.identity).max()), 1e-12)

    def test_half_strength_is_the_midpoint(self):
        look = self._look()
        blended = cube_lut.blend_toward_identity(look, self.SIZE, 0.5)
        self.assertLess(
            float(np.abs(blended - (look + self.identity) / 2).max()), 1e-12)

    def test_strength_is_clamped(self):
        look = self._look()
        self.assertTrue(np.array_equal(
            cube_lut.blend_toward_identity(look, self.SIZE, 5.0), look))
        self.assertLess(float(np.abs(
            cube_lut.blend_toward_identity(look, self.SIZE, -1.0) - self.identity).max()), 1e-12)

    def test_one_dimensional_lut_is_refused_by_name(self):
        path = os.path.join(self.dir, "curve.cube")
        with open(path, "w") as handle:
            handle.write("LUT_1D_SIZE 4\n0 0 0\n0.3 0.3 0.3\n0.6 0.6 0.6\n1 1 1\n")
        with self.assertRaises(cube_lut.CubeLutError) as caught:
            cube_lut.read_cube(path)
        self.assertIn("1D LUT", str(caught.exception))

    def test_truncated_table_is_refused(self):
        path = os.path.join(self.dir, "short.cube")
        with open(path, "w") as handle:
            handle.write("LUT_3D_SIZE 4\n0 0 0\n1 1 1\n")
        with self.assertRaises(cube_lut.CubeLutError):
            cube_lut.read_cube(path)

    def test_non_unit_domain_refuses_attenuation(self):
        """Identity is only identity on 0..1; blending elsewhere is wrong everywhere."""
        path = os.path.join(self.dir, "scaled.cube")
        cube_lut.write_cube(path, self._look(), self.SIZE,
                            domain_min=[0.0, 0.0, 0.0], domain_max=[2.0, 2.0, 2.0])
        with self.assertRaises(cube_lut.CubeLutError) as caught:
            cube_lut.attenuate_file(path, 0.5, os.path.join(self.dir, "out.cube"))
        self.assertIn("domain", str(caught.exception))

    def test_attenuate_file_writes_a_readable_lut(self):
        source = os.path.join(self.dir, "look.cube")
        cube_lut.write_cube(source, self._look(), self.SIZE, title="Look")
        out = os.path.join(self.dir, "look_50.cube")
        info = cube_lut.attenuate_file(source, 0.5, out)
        self.assertEqual(info["strength"], 0.5)
        self.assertTrue(cube_lut.read_cube(out)["title"].startswith("Look"))

    def test_size_mismatch_on_write_is_refused(self):
        with self.assertRaises(cube_lut.CubeLutError):
            cube_lut.write_cube(os.path.join(self.dir, "bad.cube"),
                                self.identity, self.SIZE + 1)


# ── the ladder ───────────────────────────────────────────────────────────────


class TestStrengthSchedule(unittest.TestCase):
    def test_default_ladder(self):
        self.assertEqual(grade_loop.strength_schedule(), [1.0, 0.8, 0.64])

    def test_floor_stops_the_ladder_rather_than_repeating_a_rung(self):
        """A clamped rung is evidence once; running it twice is not two failures."""
        schedule = grade_loop.strength_schedule(1.0, max_tries=8, floor=0.9)
        self.assertEqual(schedule, [1.0, 0.9])

    def test_floor_never_exceeds_the_starting_strength(self):
        self.assertEqual(grade_loop.strength_schedule(0.5, floor=0.9), [0.5])

    def test_max_tries_is_honoured(self):
        self.assertEqual(len(grade_loop.strength_schedule(1.0, max_tries=2, floor=0.1)), 2)


class _StubAssessor:
    """Stands in for image_qc.assess_grade with a scripted verdict per strength."""

    def __init__(self, verdicts, shift_by_strength=None):
        self.verdicts = verdicts
        self.shift_by_strength = shift_by_strength or {}
        self.calls = []

    def __call__(self, source_path, *, time_seconds, lut_path, working_space, cost_tier):
        strength = 1.0 if lut_path.endswith("look.cube") else int(
            os.path.basename(lut_path).rsplit("_", 1)[1].split(".")[0]) / 1000
        self.calls.append((round(strength, 3), time_seconds))
        flags = self.verdicts.get(round(strength, 3), {}).get(time_seconds, [])
        return {
            "acceptable": not flags,
            "flags": [{"id": name, "detail": "d", "remedy": "r"} for name in flags],
            "grade_shift_delta_e2000": self.shift_by_strength.get(round(strength, 3), strength * 10),
        }


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestLadder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ladder_test_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.source = os.path.join(self.dir, "source.mov")
        pathlib.Path(self.source).write_bytes(b"not really a movie")
        self.lut = os.path.join(self.dir, "look.cube")
        cube_lut.write_cube(self.lut, cube_lut.identity_table(9), 9, title="Look")

    def _run(self, verdicts, shifts=None, **kwargs):
        stub = _StubAssessor(verdicts, shifts)
        original = grade_loop.image_qc.assess_grade
        grade_loop.image_qc.assess_grade = stub
        try:
            result = grade_loop.run(self.source, self.lut,
                                    output_dir=os.path.join(self.dir, "out"), **kwargs)
        finally:
            grade_loop.image_qc.assess_grade = original
        return result, stub

    def test_clean_at_full_strength_stops_immediately(self):
        result, stub = self._run({1.0: {0.0: []}}, times=[0.0])
        self.assertTrue(result["converged"])
        self.assertEqual(result["chosen"]["strength"], 1.0)
        self.assertEqual(len(stub.calls), 1)

    def test_backs_off_until_it_clears(self):
        result, _ = self._run(
            {1.0: {0.0: ["banding"]}, 0.8: {0.0: ["banding"]}, 0.64: {0.0: []}},
            times=[0.0])
        self.assertTrue(result["converged"])
        self.assertEqual(result["chosen"]["strength"], 0.64)
        self.assertEqual([a["strength"] for a in result["attempts"]], [1.0, 0.8, 0.64])

    def test_exhausted_ladder_reports_needs_human(self):
        result, _ = self._run(
            {s: {0.0: ["banding"]} for s in (1.0, 0.8, 0.64)}, times=[0.0])
        self.assertTrue(result["needs_human"])
        self.assertFalse(result["converged"])
        self.assertFalse(result["acceptable"])
        self.assertIn("banding", result["chosen"]["flags"])

    def test_a_flagged_result_is_never_acceptable(self):
        """The silent-lie guard: `acceptable` is derived from flags, never assigned."""
        result, _ = self._run(
            {s: {0.0: ["clipped"]} for s in (1.0, 0.8, 0.64)}, times=[0.0])
        self.assertFalse(result["acceptable"])
        for attempt in result["attempts"]:
            self.assertFalse(attempt["acceptable"])
        self.assertFalse(result["apply_manifest"]["safe_to_apply"])
        self.assertIsNotNone(result["apply_manifest"]["blocked_reason"])

    def test_every_sampled_frame_must_pass(self):
        """Clean on frame one and banded on frame two is not a pass."""
        result, _ = self._run(
            {
                1.0: {0.0: [], 5.0: ["banding"]},
                0.8: {0.0: [], 5.0: ["banding"]},
                0.64: {0.0: [], 5.0: []},
            },
            times=[0.0, 5.0])
        self.assertTrue(result["converged"])
        self.assertEqual(result["chosen"]["strength"], 0.64)
        self.assertEqual(result["attempts"][0]["failing_time_seconds"], 5.0)

    def test_the_failing_frame_is_named(self):
        result, _ = self._run(
            {s: {0.0: [], 5.0: ["clipped"]} for s in (1.0, 0.8, 0.64)},
            times=[0.0, 5.0])
        self.assertTrue(result["needs_human"])
        self.assertEqual(result["attempts"][0]["failing_time_seconds"], 5.0)

    def test_a_failing_rung_stops_measuring_further_frames(self):
        _, stub = self._run(
            {s: {0.0: ["banding"], 5.0: [], 9.0: []} for s in (1.0, 0.8, 0.64)},
            times=[0.0, 5.0, 9.0])
        self.assertTrue(all(call[1] == 0.0 for call in stub.calls),
                        "measured frames past a known failure")

    def test_best_attempt_prefers_fewest_flags(self):
        result, _ = self._run(
            {
                1.0: {0.0: ["banding", "clipped"]},
                0.8: {0.0: ["banding"]},
                0.64: {0.0: ["banding", "noisy"]},
            },
            times=[0.0])
        self.assertEqual(result["chosen"]["strength"], 0.8)

    def test_ties_break_to_the_gentlest_grade(self):
        """Equal damage — take the one that moved the image least to undo."""
        result, _ = self._run(
            {s: {0.0: ["banding"]} for s in (1.0, 0.8, 0.64)},
            shifts={1.0: 30.0, 0.8: 20.0, 0.64: 10.0},
            times=[0.0])
        self.assertEqual(result["chosen"]["strength"], 0.64)

    def test_remedies_are_carried_not_just_flag_names(self):
        result, _ = self._run(
            {s: {0.0: ["noisy"]} for s in (1.0, 0.8, 0.64)}, times=[0.0])
        self.assertTrue(result["chosen"]["remedies"])
        self.assertIn("remedy", result["chosen"]["remedies"][0])

    def test_full_strength_reuses_the_original_lut_file(self):
        result, _ = self._run({1.0: {0.0: []}}, times=[0.0])
        self.assertEqual(result["chosen"]["lut_path"], self.lut)

    def test_attenuated_luts_are_written_to_the_output_dir_not_beside_the_source(self):
        result, _ = self._run(
            {1.0: {0.0: ["banding"]}, 0.8: {0.0: []}}, times=[0.0])
        chosen = result["chosen"]["lut_path"]
        self.assertTrue(chosen.startswith(os.path.join(self.dir, "out")))
        self.assertNotEqual(os.path.dirname(chosen), os.path.dirname(self.source))


class TestPlanAndValidation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="plan_test_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.source = os.path.join(self.dir, "source.mov")
        pathlib.Path(self.source).write_bytes(b"x")
        self.lut = os.path.join(self.dir, "look.cube")
        pathlib.Path(self.lut).write_text("LUT_3D_SIZE 2\n" + "0 0 0\n" * 8)

    def test_plan_reports_the_budget_and_touches_nothing(self):
        before = sorted(os.listdir(self.dir))
        plan = grade_loop.plan(self.source, self.lut, times=[0.0, 1.0])
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["cost"]["max_assessments"], 6)
        self.assertEqual(plan["cost"]["max_ffmpeg_decodes"], 12)
        self.assertEqual(plan["cost"]["luts_written"], 2)
        self.assertEqual(sorted(os.listdir(self.dir)), before)

    def test_missing_times_is_refused(self):
        with self.assertRaises(grade_loop.GradeLoopError):
            grade_loop.plan(self.source, self.lut)

    def test_missing_file_is_refused(self):
        with self.assertRaises(grade_loop.GradeLoopError):
            grade_loop.plan(os.path.join(self.dir, "nope.mov"), self.lut, times=[0.0])

    def test_negative_time_is_refused(self):
        with self.assertRaises(grade_loop.GradeLoopError):
            grade_loop.plan(self.source, self.lut, times=[-1.0])

    def test_scalar_time_seconds_is_accepted(self):
        self.assertEqual(grade_loop.plan(self.source, self.lut, time_seconds=2.5)["times"], [2.5])

    def test_capabilities_names_the_unbuilt_live_mode(self):
        """Shipping the offline half is fine; claiming the live half is not."""
        modes = grade_loop.capabilities()["modes"]
        self.assertIn("Not built", modes["live"])
        self.assertIn("offline", modes["lut"])


# ── end to end, real pixels ──────────────────────────────────────────────────


@unittest.skipUnless(HAVE_FFMPEG and HAVE_NUMPY, "ffmpeg and numpy required")
class TestEndToEnd(unittest.TestCase):
    """Real ffmpeg decode through a real LUT. The arithmetic being right and the
    pixels agreeing are different claims, and only this tests the second one."""

    SIZE = 25

    @classmethod
    def setUpClass(cls):
        from src.utils import colorimetry

        cls.dir = tempfile.mkdtemp(prefix="grade_loop_e2e_")
        cls.source = os.path.join(cls.dir, "gradient.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
             "gradients=s=960x540:c0=0x101820:c1=0xD8E8F0:x0=0:y0=0:x1=960:y1=540:d=2:r=24",
             "-frames:v", "48", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
             "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
             cls.source],
            check=True, capture_output=True,
        )
        identity = cube_lut.identity_table(cls.SIZE)

        def desaturate(factor):
            lab = colorimetry.srgb_to_lab(identity.reshape(1, -1, 3))
            lab[..., 1] *= factor
            lab[..., 2] *= factor
            return np.clip(colorimetry.lab_to_srgb(lab).reshape(-1, 3), 0, 1)

        # Chroma survives a blend as (1 - s) + s*factor of the source, so a strong
        # desaturation clears the washed_out gate partway down the ladder and a total
        # one never clears it at all.
        cls.recoverable = os.path.join(cls.dir, "desat45.cube")
        cube_lut.write_cube(cls.recoverable, desaturate(0.45), cls.SIZE, title="Desat45")
        cls.hopeless = os.path.join(cls.dir, "desat00.cube")
        cube_lut.write_cube(cls.hopeless, desaturate(0.0), cls.SIZE, title="Mono")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_converges_after_backing_off(self):
        result = grade_loop.run(self.source, self.recoverable, times=[0.5],
                                output_dir=os.path.join(self.dir, "a"))
        self.assertTrue(result["converged"], result["summary"])
        self.assertLess(result["chosen"]["strength"], 1.0)
        self.assertIn("washed_out", result["attempts"][0]["flags"])
        self.assertEqual(result["chosen"]["flags"], [])
        self.assertTrue(result["apply_manifest"]["safe_to_apply"])

    def test_never_converges_and_says_so(self):
        result = grade_loop.run(self.source, self.hopeless, times=[0.5],
                                output_dir=os.path.join(self.dir, "b"))
        self.assertTrue(result["needs_human"], result["summary"])
        self.assertIn("washed_out", result["chosen"]["flags"])
        self.assertFalse(result["apply_manifest"]["safe_to_apply"])
        self.assertIn("still carries", result["summary"])

    def test_summary_names_what_full_strength_carried(self):
        result = grade_loop.run(self.source, self.recoverable, times=[0.5],
                                output_dir=os.path.join(self.dir, "c"))
        self.assertIn("washed_out", result["summary"])


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

    def test_capabilities_action(self):
        result = self._call(action="grade_loop_capabilities")
        self.assertTrue(result["success"])
        self.assertIn("live", result["modes"])

    def test_missing_lut_path_is_reported(self):
        result = self._call(action="grade_loop", params={"source_path": "/tmp/x.mov"})
        self.assertIn("lut_path", result["error"]["message"])

    def test_dry_run_is_the_default(self):
        directory = tempfile.mkdtemp(prefix="surface_test_")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        source = os.path.join(directory, "s.mov")
        pathlib.Path(source).write_bytes(b"x")
        lut = os.path.join(directory, "l.cube")
        pathlib.Path(lut).write_text("LUT_3D_SIZE 2\n" + "0 0 0\n" * 8)
        result = self._call(action="grade_loop",
                            params={"source_path": source, "lut_path": lut, "times": [0.0]})
        self.assertTrue(result["dry_run"])
        self.assertIn("cost", result)

    def test_runs_without_a_resolve_connection(self):
        """Grade QC is ffmpeg and numpy; reaching for Resolve would be a regression.

        (`grade_loop` is advertised in the action list by `test_action_list_drift`,
        which checks the list against the dispatch chain in both directions.)"""
        calls = []
        original = self.server.get_resolve
        self.server.get_resolve = lambda *a, **k: calls.append(1) or None
        try:
            self._call(action="grade_loop_capabilities")
        finally:
            self.server.get_resolve = original
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
