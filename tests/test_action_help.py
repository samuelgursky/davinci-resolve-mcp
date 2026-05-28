"""Contract tests for B4 — action_help pull-on-demand action guidance.

See local/design/agentic-flow-improvements-gameplan.md §3 task B4.
"""
import unittest

import src.server as compound


class ActionHelpTest(unittest.TestCase):
    def test_known_action_returns_summary_params_returns_example(self):
        out = compound._action_help("timeline_item_color", {"name": "safe_set_cdl"})
        self.assertTrue(out.get("success"))
        self.assertEqual(out["action"], "safe_set_cdl")
        self.assertIn("summary", out)
        self.assertIn("params", out)
        self.assertIn("returns", out)
        self.assertIn("example", out)
        # Example block is callable-syntax — at minimum it contains the action name.
        self.assertIn("safe_set_cdl", out["example"])

    def test_unknown_action_returns_structured_error(self):
        out = compound._action_help("timeline_item_color", {"name": "no_such_action"})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["code"], "HELP_NOT_REGISTERED")
        self.assertEqual(out["error"]["category"], "invalid_input")

    def test_no_name_lists_available(self):
        out = compound._action_help("timeline_item_color", {})
        self.assertIn("available", out)
        self.assertIn("safe_set_cdl", out["available"])
        self.assertIn("safe_apply_drx", out["available"])
        self.assertIn("grade_evidence_base", out["available"])

    def test_each_registered_tool_has_at_least_one_action(self):
        for tool_name, catalog in compound._ACTION_HELP.items():
            self.assertGreater(len(catalog), 0, f"empty catalog for {tool_name}")

    def test_dispatch_works_through_timeline_item_color(self):
        # Calling action_help should not require a current timeline/item.
        out = compound.timeline_item_color("action_help", {"name": "safe_apply_drx"})
        self.assertTrue(out.get("success"), out)
        self.assertEqual(out["action"], "safe_apply_drx")


if __name__ == "__main__":
    unittest.main()
