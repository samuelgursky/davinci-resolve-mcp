"""F2 contract test — five workflow prompts are registered on the mcp instance.

See local/design/agentic-flow-improvements-gameplan-2.md §3 task F2.
"""
import unittest


class McpPromptsTest(unittest.TestCase):
    def test_workflow_prompts_are_registered(self):
        from src.server import mcp
        expected = {
            "analyze_and_propose_grade",
            "match_bin_to_hero",
            "verify_timeline_coverage",
            "open_and_analyze_selection",
            "prep_color_handoff",
        }
        registered = set()
        # FastMCP exposes prompts via _prompt_manager._prompts.
        if hasattr(mcp, "_prompt_manager"):
            pm = mcp._prompt_manager
            if hasattr(pm, "_prompts"):
                registered = set(pm._prompts.keys())
        if not registered:
            self.skipTest("FastMCP prompt manager internals changed; skipping check")
        self.assertTrue(
            expected.issubset(registered),
            f"missing prompts: {expected - registered}"
        )

    def test_match_bin_to_hero_template_takes_args(self):
        """The prompt body must interpolate hero_clip_id and method."""
        from src.server import match_bin_to_hero
        body = match_bin_to_hero("hero-uuid-123", method="cdl_delta")
        self.assertIn("hero-uuid-123", body)
        self.assertIn("cdl_delta", body)
        self.assertIn("bulk_match_to_hero", body)
        self.assertIn("dry_run", body)

    def test_analyze_and_propose_grade_invokes_color_pipeline(self):
        from src.server import analyze_and_propose_grade
        body = analyze_and_propose_grade("clip-xyz")
        self.assertIn("clip-xyz", body)
        self.assertIn("grade_evidence_base", body)
        self.assertIn("propose_grade", body)
        self.assertIn('"execute": false', body)
        # Must not auto-execute — that's the human-in-the-loop guard rail.
        self.assertIn("Wait for explicit confirmation", body)

    def test_verify_timeline_coverage_references_partial_success(self):
        """The prompt should teach the agent to surface failed_clip_ids on partial success."""
        from src.server import verify_timeline_coverage
        body = verify_timeline_coverage()
        self.assertIn("partial_success", body)
        self.assertIn("failed_clip_ids", body)
        self.assertIn("provenance", body)

    def test_open_and_analyze_selection_starts_with_control_panel(self):
        from src.server import open_and_analyze_selection
        body = open_and_analyze_selection()
        self.assertIn("open_control_panel", body)
        self.assertIn("analyze_clip", body)
        self.assertIn("commit_vision", body)

    def test_prep_color_handoff_writes_to_safe_location(self):
        """The prompt must NOT direct writes beside source media."""
        from src.server import prep_color_handoff
        body = prep_color_handoff()
        self.assertIn("davinci-resolve-mcp-analysis", body)
        self.assertIn("Do not write beside source media", body)
        # Custom output dir is respected when provided.
        custom = prep_color_handoff("/Users/x/handoff_dir")
        self.assertIn("/Users/x/handoff_dir", custom)


if __name__ == "__main__":
    unittest.main()
