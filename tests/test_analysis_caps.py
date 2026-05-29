"""Unit tests for src/utils/analysis_caps.py."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest

from src.utils import analysis_caps, timeline_brain_db


class PresetResolution(unittest.TestCase):
    def test_known_presets_resolve(self) -> None:
        for name in analysis_caps.VALID_PRESETS:
            caps = analysis_caps.resolve_caps(name)
            self.assertEqual(caps.preset, name)

    def test_unknown_preset_falls_back_to_standard(self) -> None:
        caps = analysis_caps.resolve_caps("nope")
        self.assertEqual(caps.preset, analysis_caps.DEFAULT_PRESET)

    def test_unlimited_has_all_none(self) -> None:
        caps = analysis_caps.resolve_caps(analysis_caps.PRESET_UNLIMITED)
        for field in ("response_chars", "vision_tokens_per_clip", "frames_per_clip",
                      "vision_tokens_per_job", "vision_tokens_per_day",
                      "wall_clock_seconds_per_call", "max_frame_dim_pixels"):
            self.assertIsNone(getattr(caps, field), msg=f"{field} should be uncapped")

    def test_overrides_replace_specific_fields(self) -> None:
        caps = analysis_caps.resolve_caps(
            analysis_caps.PRESET_STANDARD,
            {"vision_tokens_per_clip": 12345, "max_frame_dim_pixels": 256},
        )
        self.assertEqual(caps.vision_tokens_per_clip, 12345)
        self.assertEqual(caps.max_frame_dim_pixels, 256)
        # Other fields untouched.
        self.assertEqual(caps.frames_per_clip, 80)

    def test_unlimited_string_override_lifts_cap(self) -> None:
        caps = analysis_caps.resolve_caps(
            analysis_caps.PRESET_MINIMAL,
            {"vision_tokens_per_day": "unlimited"},
        )
        self.assertIsNone(caps.vision_tokens_per_day)

    def test_unknown_override_key_ignored(self) -> None:
        caps = analysis_caps.resolve_caps(
            analysis_caps.PRESET_STANDARD, {"frobnicate": 99},
        )
        # Should silently return the base preset.
        self.assertEqual(caps, analysis_caps.CAP_PRESETS[analysis_caps.PRESET_STANDARD])

    def test_list_presets_returns_all(self) -> None:
        presets = analysis_caps.list_presets()
        self.assertEqual(set(presets), analysis_caps.VALID_PRESETS)
        # Every preset includes the 7 cap dimensions + preset name.
        for name, body in presets.items():
            self.assertEqual(body["preset"], name)
            for field in ("response_chars", "frames_per_clip", "max_frame_dim_pixels"):
                self.assertIn(field, body)


class BudgetEnforcement(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="caps_budget_test_")
        self.project_root = os.path.join(self.tmp, "project")
        os.makedirs(self.project_root, exist_ok=True)

    def tearDown(self) -> None:
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fresh_db_has_zero_usage(self) -> None:
        caps = analysis_caps.resolve_caps(analysis_caps.PRESET_STANDARD)
        decision = analysis_caps.check_budget(
            project_root=self.project_root, caps=caps,
            estimated_vision_tokens=1000, clip_id="c1",
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.current_usage["clip_vision_tokens"], 0)

    def test_unlimited_preset_always_allows(self) -> None:
        caps = analysis_caps.resolve_caps(analysis_caps.PRESET_UNLIMITED)
        # Pretend we've already spent a million tokens on this clip.
        analysis_caps.record_usage(
            project_root=self.project_root, scope=analysis_caps.SCOPE_CLIP,
            scope_key="c1", vision_tokens=10_000_000,
        )
        decision = analysis_caps.check_budget(
            project_root=self.project_root, caps=caps,
            estimated_vision_tokens=10_000_000, clip_id="c1",
        )
        self.assertTrue(decision.allowed)

    def test_per_clip_cap_blocks_when_exceeded(self) -> None:
        caps = analysis_caps.resolve_caps(analysis_caps.PRESET_MINIMAL)
        # minimal.vision_tokens_per_clip = 16000.
        analysis_caps.record_usage(
            project_root=self.project_root, scope=analysis_caps.SCOPE_CLIP,
            scope_key="c1", vision_tokens=15_500,
        )
        # Need 1000 more, only 500 left.
        decision = analysis_caps.check_budget(
            project_root=self.project_root, caps=caps,
            estimated_vision_tokens=1000, clip_id="c1",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "over_clip_cap")
        self.assertEqual(decision.headroom["clip"], 500)

    def test_per_day_cap_blocks_when_exceeded(self) -> None:
        caps = analysis_caps.resolve_caps(analysis_caps.PRESET_MINIMAL)
        # minimal.vision_tokens_per_day = 150_000. Spend 149k under DAY scope.
        analysis_caps.record_usage(
            project_root=self.project_root, scope=analysis_caps.SCOPE_DAY,
            scope_key=None, vision_tokens=149_000,
        )
        # Try to spend 2k — would push to 151k (over day). Pass no clip_id so the
        # check doesn't trip the smaller clip cap first.
        decision = analysis_caps.check_budget(
            project_root=self.project_root, caps=caps,
            estimated_vision_tokens=2_000,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "over_day_cap")

    def test_record_usage_all_scopes_writes_multiple_rows(self) -> None:
        result = analysis_caps.record_usage_all_scopes(
            project_root=self.project_root,
            clip_id="c1", job_id="j1",
            vision_tokens=1234, frames_uploaded=8,
        )
        self.assertEqual(len(result["rows"]), 3)
        conn = timeline_brain_db.connect(self.project_root)
        scopes = conn.execute(
            "SELECT scope FROM analysis_token_usage ORDER BY scope"
        ).fetchall()
        self.assertEqual(sorted({r["scope"] for r in scopes}), ["clip", "day", "job"])

    def test_usage_rollup_percent_consumed(self) -> None:
        caps = analysis_caps.resolve_caps(analysis_caps.PRESET_MINIMAL)
        analysis_caps.record_usage(
            project_root=self.project_root, scope=analysis_caps.SCOPE_DAY,
            scope_key=None, vision_tokens=75_000,
        )
        rollup = analysis_caps.get_usage_rollup(
            project_root=self.project_root, caps=caps,
        )
        # 75000 / 150000 = 50% (minimal.vision_tokens_per_day = 150_000)
        self.assertAlmostEqual(rollup["percent_consumed"]["day"], 50.0)


class ResponseTrimming(unittest.TestCase):
    def test_under_cap_returns_unchanged(self) -> None:
        payload = {"a": 1, "b": "small"}
        out = analysis_caps.trim_response_payload(payload, max_chars=10_000)
        self.assertIs(out, payload)

    def test_uncapped_returns_unchanged(self) -> None:
        payload = {"x": "y" * 100_000}
        self.assertIs(analysis_caps.trim_response_payload(payload, None), payload)

    def test_trims_large_list_fields_first(self) -> None:
        payload = {
            "summary": "concise",
            "transcript_segments": [{"text": "blah"} for _ in range(500)],
        }
        out = analysis_caps.trim_response_payload(payload, max_chars=2000)
        self.assertIn("_trimmed", out)
        # Should have trimmed transcript_segments.
        self.assertTrue(len(out["transcript_segments"]) <= 5)
        # And serialised result fits.
        self.assertLessEqual(len(json.dumps(out, default=str)), 2000)

    def test_falls_back_to_string_truncation(self) -> None:
        payload = {"single_field": "x" * 50_000}
        out = analysis_caps.trim_response_payload(payload, max_chars=1000)
        if isinstance(out, str):
            self.assertLessEqual(len(out), 1000)
        else:
            self.assertLessEqual(len(json.dumps(out, default=str)), 1000)


class WallClockTimeout(unittest.TestCase):
    def test_fast_call_returns(self) -> None:
        result = analysis_caps.run_with_timeout(lambda: 42, 5)
        self.assertEqual(result, 42)

    def test_slow_call_raises(self) -> None:
        # 100ms timeout against a 500ms sleep → should fire.
        with self.assertRaises(analysis_caps.WallClockTimeout):
            analysis_caps.run_with_timeout(lambda: time.sleep(0.5), 0.1)

    def test_timeout_disabled_passthrough(self) -> None:
        # None and 0 both disable.
        self.assertEqual(analysis_caps.run_with_timeout(lambda x: x * 2, None, 21), 42)
        self.assertEqual(analysis_caps.run_with_timeout(lambda x: x * 2, 0, 21), 42)

    def test_function_args_kwargs_passthrough(self) -> None:
        result = analysis_caps.run_with_timeout(
            lambda a, b=0: a + b, 2, 10, b=32,
        )
        self.assertEqual(result, 42)


if __name__ == "__main__":
    unittest.main()
