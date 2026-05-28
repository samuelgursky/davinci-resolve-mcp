"""E2 contract test — repeated-failure escalation tracker.

See local/design/agentic-flow-improvements-gameplan-2.md §3 task E2.
"""
import unittest

from src.utils import failure_tracker as ft


class FailureTrackerTest(unittest.TestCase):
    def setUp(self):
        ft.reset_all()

    def tearDown(self):
        ft.reset_all()

    def test_three_failures_in_window_returns_escalation(self):
        # Same scope, same action, 3 failures within window.
        t0 = 1000.0
        for offset in (0, 10, 20):
            ft.record_failure("clip-a", "analyze_clip", now=t0 + offset)
        out = ft.build_escalation_block("clip-a", "analyze_clip",
                                         error_category="resolve_api_failed",
                                         now=t0 + 21)
        self.assertIsNotNone(out)
        self.assertTrue(out["recommended"])
        self.assertEqual(out["reason"], "repeated_failure")
        self.assertEqual(out["failure_count"], 3)
        self.assertIn("analyze_clip", out["suggested_action"])
        self.assertIn("clip-a", out["suggested_action"])

    def test_two_failures_then_success_clears_counter(self):
        t0 = 1000.0
        ft.record_failure("clip-a", "analyze_clip", now=t0)
        ft.record_failure("clip-a", "analyze_clip", now=t0 + 5)
        ft.record_success("clip-a", "analyze_clip")
        ft.record_failure("clip-a", "analyze_clip", now=t0 + 10)
        # Only the post-success failure should count → no escalation.
        out = ft.build_escalation_block("clip-a", "analyze_clip",
                                         error_category="resolve_api_failed",
                                         now=t0 + 11)
        self.assertIsNone(out)

    def test_failures_spread_beyond_window_do_not_escalate(self):
        # 3 failures spaced > window → only the most recent stays in.
        for offset in (0, 1000, 2000):
            ft.record_failure("clip-a", "analyze_clip", now=offset, window_seconds=600)
        out = ft.build_escalation_block("clip-a", "analyze_clip",
                                         error_category="resolve_api_failed",
                                         now=2100, window_seconds=600)
        self.assertIsNone(out)

    def test_different_scope_keys_are_independent(self):
        t0 = 1000.0
        for offset in (0, 10, 20):
            ft.record_failure("clip-a", "analyze_clip", now=t0 + offset)
        # 3 failures on clip-a, 0 failures on clip-b.
        self.assertIsNotNone(ft.build_escalation_block("clip-a", "analyze_clip",
                                                        error_category="x", now=t0 + 21))
        self.assertIsNone(ft.build_escalation_block("clip-b", "analyze_clip",
                                                     error_category="x", now=t0 + 21))

    def test_different_actions_on_same_scope_are_independent(self):
        t0 = 1000.0
        for offset in (0, 10, 20):
            ft.record_failure("clip-a", "analyze_clip", now=t0 + offset)
        # analyze_clip escalates; commit_vision (no failures) does not.
        self.assertIsNotNone(ft.build_escalation_block("clip-a", "analyze_clip",
                                                        error_category="x", now=t0 + 21))
        self.assertIsNone(ft.build_escalation_block("clip-a", "commit_vision",
                                                     error_category="x", now=t0 + 21))

    def test_no_scope_sentinel_groups_failures_correctly(self):
        """Calls with no scope_key (None) collapse into a shared bucket."""
        t0 = 1000.0
        for offset in (0, 10, 20):
            ft.record_failure(None, "open_control_panel", now=t0 + offset)
        out = ft.build_escalation_block(None, "open_control_panel",
                                         error_category="resolve_api_failed",
                                         now=t0 + 21)
        self.assertIsNotNone(out)
        self.assertEqual(out["failure_count"], 3)

    def test_get_failure_state_does_not_record(self):
        """Pure read; shouldn't increment counters or trigger escalation."""
        state1 = ft.get_failure_state("clip-a", "analyze_clip")
        state2 = ft.get_failure_state("clip-a", "analyze_clip")
        self.assertEqual(state1["failure_count"], 0)
        self.assertEqual(state2["failure_count"], 0)

    def test_threshold_is_configurable(self):
        t0 = 1000.0
        ft.record_failure("clip-a", "x", now=t0)
        ft.record_failure("clip-a", "x", now=t0 + 1)
        # threshold=2 → escalate at 2 failures.
        out = ft.build_escalation_block("clip-a", "x", error_category="z",
                                         threshold=2, now=t0 + 2)
        self.assertIsNotNone(out)
        self.assertEqual(out["failure_count"], 2)


if __name__ == "__main__":
    unittest.main()
