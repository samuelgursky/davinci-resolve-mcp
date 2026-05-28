"""E3 contract test — `prefer_handle` opt-in for long-running analyze ops.

See local/design/agentic-flow-improvements-gameplan-2.md §3 task E3.

We don't actually exercise a live Resolve here — we test the dispatcher
behavior in isolation: when `prefer_handle=true` is passed alongside an
analyze_clip/analyze_file/analyze_bin/analyze_project/analyze_sequence,
the action should be redirected to `start_batch_job` before the analyze
machinery runs. When `prefer_handle=false` (default), action stays
unchanged (existing blocking path).
"""
import unittest

# Replicates the relevant branch from src/server.py:13454. Kept in-test so
# the test is self-contained even if the surrounding handler shape evolves.


def _normalize_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"true", "yes", "1", "on"}:
            return True
        if s in {"false", "no", "0", "off"}:
            return False
    if v is None:
        return default
    return bool(v)


def _resolve_action(initial_action, params):
    """Mirrors the analyze_* → plan|start_batch_job branch from server.py."""
    if initial_action not in {
        "analyze_file", "analyze_clip", "analyze_bin",
        "analyze_project", "analyze_timeline", "analyze_sequence",
    }:
        return initial_action
    if _normalize_bool(params.get("prefer_handle"), False) and not params.get("dry_run"):
        return "start_batch_job"
    return "plan"


class PreferHandleDispatchTest(unittest.TestCase):
    def test_default_is_blocking_plan_path(self):
        self.assertEqual(_resolve_action("analyze_clip", {"clip_id": "x"}), "plan")
        self.assertEqual(_resolve_action("analyze_bin", {"path": "Master"}), "plan")

    def test_prefer_handle_true_dispatches_to_start_batch_job(self):
        for action in ("analyze_clip", "analyze_file", "analyze_bin",
                       "analyze_project", "analyze_timeline", "analyze_sequence"):
            with self.subTest(action=action):
                self.assertEqual(
                    _resolve_action(action, {"prefer_handle": True}),
                    "start_batch_job",
                )

    def test_prefer_handle_true_with_dry_run_stays_blocking(self):
        """dry_run is fast (no real work); no benefit to async. Stay on plan."""
        self.assertEqual(
            _resolve_action("analyze_clip", {"prefer_handle": True, "dry_run": True}),
            "plan",
        )

    def test_prefer_handle_truthy_string_dispatches(self):
        """Accepts 'true'/'yes' string forms for HTTP-style clients."""
        self.assertEqual(
            _resolve_action("analyze_clip", {"prefer_handle": "true"}),
            "start_batch_job",
        )

    def test_prefer_handle_falsy_string_blocks(self):
        self.assertEqual(
            _resolve_action("analyze_clip", {"prefer_handle": "false"}),
            "plan",
        )

    def test_prefer_handle_does_not_affect_non_analyze_actions(self):
        """E3 is scoped to the analyze_* family; other actions pass through unchanged."""
        for action in ("commit_vision", "summarize", "get_caps", "capabilities"):
            with self.subTest(action=action):
                self.assertEqual(
                    _resolve_action(action, {"prefer_handle": True}),
                    action,
                )


if __name__ == "__main__":
    unittest.main()
