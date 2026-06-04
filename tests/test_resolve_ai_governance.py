"""Tests for the Resolve 21 AI-ops governance tiers (advisory soft limits)."""
import tempfile
import unittest

from src.utils import resolve_ai_governance as G
from src.utils import resolve_ai_ledger as L


class GovernanceTierResolutionTest(unittest.TestCase):
    def test_known_tiers_present(self):
        self.assertEqual(G.VALID_TIERS, frozenset({"off", "lenient", "standard", "strict"}))
        self.assertEqual(G.DEFAULT_TIER, "standard")

    def test_resolve_unknown_falls_back_to_default(self):
        self.assertEqual(G.resolve_tier("bogus")["preset"], "standard")

    def test_overrides_applied(self):
        r = G.resolve_tier("standard", {"deblur_runs": 3, "render_bytes": "unlimited"})
        self.assertEqual(r["thresholds"]["deblur_runs"], 3)
        self.assertIsNone(r["thresholds"]["render_bytes"])

    def test_off_tier_is_all_uncapped(self):
        th = G.resolve_tier("off")["thresholds"]
        self.assertTrue(all(v is None for v in th.values()))


class GovernanceCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _record_deblur(self, n, *, bytes_each=0, ms_each=0, session="s1"):
        for i in range(n):
            L.record_op(project_root=self.root, op="remove_motion_blur", session_id=session,
                        success=True, wall_clock_ms=ms_each, output_path=f"/d{i}.mov", output_bytes=bytes_each)

    def test_analysis_op_not_governed(self):
        out = G.check(project_root=self.root, session_id="s1", op="analyze_for_slate", preset="strict")
        self.assertFalse(out["applies"])
        self.assertEqual(out["warnings"], [])

    def test_within_tier_no_warnings(self):
        self._record_deblur(1)
        out = G.check(project_root=self.root, session_id="s1", op="remove_motion_blur", preset="standard")
        self.assertTrue(out["applies"])
        self.assertFalse(out["exceeded"])
        self.assertEqual(out["projected"]["deblur_runs"], 2)

    def test_exceeds_run_cap(self):
        self._record_deblur(5)  # strict cap = 5; next run projects to 6
        out = G.check(project_root=self.root, session_id="s1", op="remove_motion_blur", preset="strict")
        self.assertTrue(out["exceeded"])
        self.assertTrue(any("Runs this session" in w for w in out["warnings"]))

    def test_near_threshold_warns(self):
        self._record_deblur(11)  # standard cap 15; 12 projected = 80%
        out = G.check(project_root=self.root, session_id="s1", op="remove_motion_blur", preset="standard")
        self.assertTrue(out["near"] or out["exceeded"])

    def test_off_tier_never_warns(self):
        self._record_deblur(100, bytes_each=10**9, ms_each=10**6)
        out = G.check(project_root=self.root, session_id="s1", op="remove_motion_blur", preset="off")
        self.assertFalse(out["exceeded"])
        self.assertEqual(out["warnings"], [])

    def test_bytes_and_time_dimensions(self):
        self._record_deblur(2, bytes_each=2 * (1024 ** 3), ms_each=4 * 60 * 1000)  # 4 GB, 8 min
        out = G.check(project_root=self.root, session_id="s1", op="remove_motion_blur", preset="strict")
        # strict: render_bytes 2GB, render_wall_clock_ms 5min — both exceeded
        self.assertTrue(out["exceeded"])
        joined = " ".join(out["warnings"])
        self.assertIn("Media created this session", joined)
        self.assertIn("Render time this session", joined)

    def test_no_project_root_does_not_apply(self):
        out = G.check(project_root=None, session_id="s1", op="remove_motion_blur", preset="strict")
        self.assertFalse(out["applies"])

    def test_status_reports_usage_and_thresholds(self):
        self._record_deblur(3, bytes_each=1024 ** 3)
        st = G.status(project_root=self.root, session_id="s1", preset="standard")
        self.assertEqual(st["tier"], "standard")
        self.assertEqual(st["usage"]["deblur_runs"], 3)
        self.assertEqual(st["thresholds"]["deblur_runs"], 15)
        self.assertIn("strict", st["tiers_available"])


if __name__ == "__main__":
    unittest.main()
