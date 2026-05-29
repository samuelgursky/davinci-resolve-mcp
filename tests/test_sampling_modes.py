"""Unit tests for frame-sampling modes + the first-run "ask" preference flow.

Covers:
  - media_analysis._resolve_sampling_config / normalize_sampling_mode
  - media_analysis._compute_demand_driven_budget across all four modes
  - media_analysis._report_cache_state sampling-mode reuse rank
  - server-side sampling-mode decision (explicit / saved / first-run prompt)
  - server-side preference setter validation + effective-preferences normalization
  - media_analysis entry-point first-run confirmation short-circuit
"""

import asyncio
import os
import tempfile
import unittest

from src.utils import media_analysis as m
from src import server as srv


def _ca(shots, *, flashes=0, cuts=0):
    """Build a synthetic cut_analysis with `shots` 10s shots."""
    return {
        "shot_ranges": [
            {"index": i, "start": i * 10.0, "end": i * 10.0 + 10.0} for i in range(shots)
        ],
        "flash_frame_candidates": [{} for _ in range(flashes)],
        "cut_points": [{} for _ in range(cuts)],
    }


class NormalizeAndResolve(unittest.TestCase):
    def test_aliases_map_to_canonical(self):
        self.assertEqual(m.normalize_sampling_mode("Economy"), "fixed")
        self.assertEqual(m.normalize_sampling_mode("balanced"), "per_minute")
        self.assertEqual(m.normalize_sampling_mode("per-minute"), "per_minute")
        self.assertEqual(m.normalize_sampling_mode("Thorough"), "adaptive_capped")
        self.assertEqual(m.normalize_sampling_mode("thorough (uncapped)"), "adaptive")
        self.assertEqual(m.normalize_sampling_mode("adaptive"), "adaptive")

    def test_unknown_returns_default(self):
        self.assertIsNone(m.normalize_sampling_mode("banana"))
        self.assertEqual(m.normalize_sampling_mode("banana", default="fixed"), "fixed")

    def test_resolve_config_defaults(self):
        cfg = m._resolve_sampling_config(None)
        self.assertEqual(cfg["mode"], m.DEFAULT_SAMPLING_MODE)
        self.assertEqual(cfg["frames_per_minute"], m.DEFAULT_FRAMES_PER_MINUTE)
        self.assertEqual(cfg["frame_floor"], m.DEFAULT_FRAME_FLOOR)
        self.assertEqual(cfg["frame_ceiling"], m.DEFAULT_FRAME_CEILING)

    def test_resolve_config_reads_params_and_aliases(self):
        cfg = m._resolve_sampling_config(
            {"samplingMode": "Thorough", "framesPerMinute": 6, "frameFloor": 5, "frameCeiling": 40}
        )
        self.assertEqual(cfg["mode"], "adaptive_capped")
        self.assertEqual(cfg["frames_per_minute"], 6.0)
        self.assertEqual(cfg["frame_floor"], 5)
        self.assertEqual(cfg["frame_ceiling"], 40)

    def test_resolve_config_ceiling_floored(self):
        cfg = m._resolve_sampling_config({"frame_floor": 50, "frame_ceiling": 10})
        self.assertGreaterEqual(cfg["frame_ceiling"], cfg["frame_floor"])

    def test_resolve_config_rejects_nonpositive(self):
        cfg = m._resolve_sampling_config({"frames_per_minute": 0, "frame_floor": -3})
        self.assertEqual(cfg["frames_per_minute"], m.DEFAULT_FRAMES_PER_MINUTE)
        self.assertEqual(cfg["frame_floor"], m.DEFAULT_FRAME_FLOOR)


class BudgetByMode(unittest.TestCase):
    def _budget(self, mode, requested, ca, dur, **over):
        cfg = m._resolve_sampling_config({"sampling_mode": mode, **over})
        return m._compute_demand_driven_budget(requested, ca, dur, sampling=cfg)

    def test_fixed_is_duration_independent(self):
        ca = _ca(6, flashes=2, cuts=5)
        self.assertEqual(self._budget("fixed", 8, ca, 60.0), 8)
        self.assertEqual(self._budget("fixed", 8, ca, 3600.0), 8)
        self.assertEqual(self._budget("fixed", 24, ca, 15.0), 24)

    def test_per_minute_scales_linearly_and_clamps(self):
        # 1 min @ 4/min = 4; 10 min = 40; 30 min = 80 (ceiling); 5s -> floor.
        self.assertEqual(self._budget("per_minute", 8, _ca(1), 60.0), 4)
        self.assertEqual(self._budget("per_minute", 8, _ca(1), 600.0), 40)
        self.assertEqual(self._budget("per_minute", 8, _ca(1), 1800.0), 80)
        self.assertEqual(self._budget("per_minute", 8, _ca(1), 5.0), m.DEFAULT_FRAME_FLOOR)

    def test_adaptive_capped_follows_demand_bounded_by_ceiling(self):
        ca = _ca(6, flashes=2, cuts=5)
        demand = m._demand_frame_count(ca, 60.0)
        got = self._budget("adaptive_capped", 8, ca, 60.0)
        self.assertEqual(got, min(demand, m.DEFAULT_FRAME_CEILING))
        # A heavy clip is clamped to the ceiling.
        heavy = _ca(90, flashes=10, cuts=89)
        self.assertEqual(self._budget("adaptive_capped", 8, heavy, 1800.0), m.DEFAULT_FRAME_CEILING)

    def test_adaptive_uncapped_exceeds_ceiling(self):
        heavy = _ca(90, flashes=10, cuts=89)
        got = self._budget("adaptive", 8, heavy, 1800.0)
        self.assertGreater(got, m.DEFAULT_FRAME_CEILING)
        self.assertLessEqual(got, m.HARD_FRAME_CAP)

    def test_floor_applies_to_adaptive_modes(self):
        tiny = _ca(1)
        self.assertGreaterEqual(self._budget("adaptive_capped", 1, tiny, 5.0), m.DEFAULT_FRAME_FLOOR)

    def test_legacy_default_without_config(self):
        # No sampling config → legacy demand-driven (adaptive) behaviour.
        ca = _ca(6, flashes=2, cuts=5)
        legacy = m._compute_demand_driven_budget(8, ca, 60.0)
        adaptive = self._budget("adaptive", 8, ca, 60.0)
        self.assertEqual(legacy, adaptive)

    def test_no_cut_analysis_fixed_and_adaptive(self):
        self.assertEqual(
            m._compute_demand_driven_budget(8, None, 60.0, sampling=m._resolve_sampling_config({"sampling_mode": "fixed"})),
            8,
        )
        # legacy adaptive with no cut analysis falls back to requested.
        self.assertEqual(m._compute_demand_driven_budget(8, None, 60.0), 8)


class SampleTimesByMode(unittest.TestCase):
    """Economy/Balanced must be content-blind (exactly `budget` even-interval
    frames); Thorough must be demand-driven (covers shot structure). Regression
    guard for the live-test finding that reservations were overriding the budget
    in the content-blind modes."""

    def setUp(self):
        # 3 shots in a 52s clip — enough that demand-driven > a small fixed budget.
        self.ca = {
            "shot_ranges": [
                {"index": 0, "start": 0.0, "end": 11.0},
                {"index": 1, "start": 11.0, "end": 31.0},
                {"index": 2, "start": 31.0, "end": 52.0},
            ],
            "flash_frame_candidates": [],
            "cut_points": [{"time": 11.0}, {"time": 31.0}],
        }
        self.dur = 52.0

    def _times(self, mode, budget):
        cfg = m._resolve_sampling_config({"sampling_mode": mode})
        return m._sample_times(self.dur, [], budget, fps=25.0, cut_analysis=self.ca, sampling=cfg)

    def test_fixed_is_exactly_budget_and_interval_only(self):
        times = self._times("fixed", 8)
        self.assertEqual(len(times), 8)
        self.assertEqual({t["selection_reason"] for t in times}, {"interval"})

    def test_per_minute_is_exactly_budget(self):
        times = self._times("per_minute", 3)
        self.assertEqual(len(times), 3)
        self.assertEqual({t["selection_reason"] for t in times}, {"interval"})

    def test_thorough_is_demand_driven_and_covers_shots(self):
        times = self._times("adaptive_capped", 8)
        # Demand-driven: more than the raw 8 "budget", and covers every shot.
        self.assertGreater(len(times), 8)
        reps = [t for t in times if t["selection_reason"] == "shot_representative"]
        self.assertEqual(len(reps), 3)


class CacheReuseRank(unittest.TestCase):
    def _state(self, report_mode, request_mode):
        report = {
            "analysis_signature": {
                "analysis_version": m.ANALYSIS_VERSION,
                "analysis_keyframe_budget": 8,
                "source_file": {"path": "/x.mov", "size_bytes": 1, "mtime_ns": 1},
                "analysis_sampling": {"mode": report_mode},
            }
        }
        request_sig = {
            "analysis_version": m.ANALYSIS_VERSION,
            "analysis_keyframe_budget": 8,
            "source_file": {"path": "/x.mov", "size_bytes": 1, "mtime_ns": 1},
            "analysis_sampling": {"mode": request_mode},
        }
        return m._report_cache_state(report, request_sig)

    def test_increasing_thoroughness_invalidates(self):
        issues, _ = self._state("fixed", "adaptive_capped")
        self.assertIn("sampling_mode_increased", issues)

    def test_decreasing_thoroughness_reuses(self):
        issues, _ = self._state("adaptive", "fixed")
        self.assertNotIn("sampling_mode_increased", issues)

    def test_same_mode_reuses(self):
        issues, _ = self._state("adaptive_capped", "adaptive_capped")
        self.assertNotIn("sampling_mode_increased", issues)


class _PrefsIsolated(unittest.TestCase):
    """Base that points the media-analysis prefs file at a temp location."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="sampling_prefs_")
        self._prev = os.environ.get("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS")
        os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = os.path.join(self._tmp, "prefs.json")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS", None)
        else:
            os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = self._prev
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


class SamplingModeDecision(_PrefsIsolated):
    def test_first_run_prompts(self):
        d = srv._media_analysis_sampling_mode_decision({})
        self.assertTrue(d["prompt_required"])
        self.assertEqual(d["mode"], m.RECOMMENDED_SAMPLING_MODE)

    def test_explicit_one_off_does_not_persist(self):
        d = srv._media_analysis_sampling_mode_decision({"sampling_mode": "balanced"})
        self.assertFalse(d["prompt_required"])
        self.assertEqual(d["mode"], "per_minute")
        self.assertEqual(d["source"], "explicit")
        # Nothing written to disk.
        self.assertFalse(os.path.exists(os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"]))

    def test_save_default_persists_and_silences_prompt(self):
        d = srv._media_analysis_sampling_mode_decision(
            {"sampling_mode": "thorough", "save_sampling_default": True}
        )
        self.assertEqual(d["mode"], "adaptive_capped")
        self.assertEqual(d["source"], "saved_default")
        # Subsequent call uses the saved default with no prompt.
        d2 = srv._media_analysis_sampling_mode_decision({})
        self.assertFalse(d2["prompt_required"])
        self.assertEqual(d2["mode"], "adaptive_capped")
        self.assertEqual(srv._media_analysis_effective_preferences()["sampling_mode_default"], "adaptive_capped")

    def test_apply_setup_defaults_injects_mode_and_tunables(self):
        out = srv._media_analysis_apply_setup_defaults("analyze_clip", {"clip_id": "c1"})
        self.assertEqual(out["sampling_mode"], m.RECOMMENDED_SAMPLING_MODE)
        self.assertTrue(out["_sampling_mode_decision"]["prompt_required"])
        self.assertEqual(out["frames_per_minute"], m.DEFAULT_FRAMES_PER_MINUTE)
        self.assertEqual(out["frame_floor"], m.DEFAULT_FRAME_FLOOR)
        self.assertEqual(out["frame_ceiling"], m.DEFAULT_FRAME_CEILING)


class SamplingModeEntryShortCircuit(_PrefsIsolated):
    def test_first_analysis_returns_confirmation(self):
        resp = asyncio.run(srv.media_analysis("analyze_clip", {"clip_id": "c1"}))
        self.assertTrue(resp.get("confirmation_required"))
        self.assertEqual(resp.get("status"), "confirmation_required")
        self.assertIn("sampling_mode_prompt", resp)
        ids = {o["id"] for o in resp["sampling_mode_prompt"]["options"]}
        self.assertEqual(ids, {"fixed", "per_minute", "adaptive_capped", "adaptive"})

    def test_explicit_mode_skips_confirmation(self):
        # With an explicit mode the sampling prompt must not block; the call
        # proceeds past the short-circuit (and fails later for lack of a real
        # Resolve clip, which is fine — we only assert it isn't the sampling prompt).
        resp = asyncio.run(srv.media_analysis("analyze_clip", {"clip_id": "c1", "sampling_mode": "fixed"}))
        self.assertNotIn("sampling_mode_prompt", resp)


class SamplingModeSetter(_PrefsIsolated):
    def test_setter_persists_canonical_mode(self):
        srv._setup_set_media_analysis_defaults({"sampling_mode_default": "balanced"}, dry_run=False)
        self.assertEqual(srv._media_analysis_effective_preferences()["sampling_mode_default"], "per_minute")

    def test_ask_resets_to_unset(self):
        srv._setup_set_media_analysis_defaults({"sampling_mode_default": "thorough"}, dry_run=False)
        srv._setup_set_media_analysis_defaults({"sampling_mode_default": "ask"}, dry_run=False)
        self.assertIsNone(srv._media_analysis_effective_preferences()["sampling_mode_default"])

    def test_invalid_mode_rejected(self):
        res = srv._setup_set_media_analysis_defaults({"sampling_mode_default": "banana"}, dry_run=False)
        self.assertTrue(res.get("error") or res.get("success") is False)

    def test_tunables_persist(self):
        srv._setup_set_media_analysis_defaults(
            {"sampling_frames_per_minute": 6, "sampling_frame_ceiling": 120}, dry_run=False
        )
        eff = srv._media_analysis_effective_preferences()
        self.assertEqual(eff["sampling_frames_per_minute"], 6.0)
        self.assertEqual(eff["sampling_frame_ceiling"], 120)

    def test_negative_tunable_rejected(self):
        res = srv._setup_set_media_analysis_defaults({"sampling_frame_floor": -2}, dry_run=False)
        self.assertTrue(res.get("error") or res.get("success") is False)


if __name__ == "__main__":
    unittest.main()
