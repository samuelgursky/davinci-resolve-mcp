"""D3 contract test — partial-success preservation in batch manifests.

See local/design/agentic-flow-improvements-gameplan-2.md §3 task D3.

The helper _annotate_partial_success runs after the per-clip rows are
populated but before the caps-refusal annotator, so it sees the same
{success: bool, vision_status, error, record:{clip_id}} shape every
analyze_* path produces. We test it in isolation here.
"""
import unittest

from src.utils.media_analysis import _annotate_partial_success


def _row(clip_id: str, success: bool, vision_status=None, error=None) -> dict:
    return {
        "success": success,
        "vision_status": vision_status,
        "error": error,
        "record": {"clip_id": clip_id},
    }


class PartialSuccessManifestTest(unittest.TestCase):
    def test_mixed_success_marks_partial_with_lists(self):
        manifest = {
            "clip_count": 4,
            "clips": [
                _row("a", True),
                _row("b", False, error={"code": "X"}),
                _row("c", True),
                _row("d", False, error={"code": "Y"}),
            ],
        }
        _annotate_partial_success(manifest)
        self.assertTrue(manifest["partial_success"])
        self.assertEqual(manifest["completed_clip_ids"], ["a", "c"])
        self.assertEqual(manifest["failed_clip_ids"], ["b", "d"])
        # Aggregate error envelope follows D1 retryable defaults (batch_partial -> False).
        self.assertEqual(manifest["error"]["code"], "PARTIAL_FAILURE")
        self.assertEqual(manifest["error"]["category"], "batch_partial")
        self.assertFalse(manifest["error"]["retryable"])
        self.assertIn("failed_clip_ids", manifest["error"]["remediation"])

    def test_all_success_does_not_mark_partial(self):
        manifest = {
            "clip_count": 2,
            "clips": [_row("a", True), _row("b", True)],
        }
        _annotate_partial_success(manifest)
        self.assertFalse(manifest["partial_success"])
        self.assertEqual(manifest["completed_clip_ids"], ["a", "b"])
        self.assertEqual(manifest["failed_clip_ids"], [])
        self.assertNotIn("error", manifest)

    def test_all_failure_is_not_partial_but_lists_populate(self):
        """All-fail batch: not partial, but failed_clip_ids surfaces explicitly
        and the aggregate error envelope still lands so the caller can route."""
        manifest = {
            "clip_count": 2,
            "clips": [
                _row("a", False, error={"code": "X"}),
                _row("b", False, error={"code": "Y"}),
            ],
        }
        _annotate_partial_success(manifest)
        self.assertFalse(manifest["partial_success"])
        self.assertEqual(manifest["completed_clip_ids"], [])
        self.assertEqual(manifest["failed_clip_ids"], ["a", "b"])
        # Aggregate error not set when not partial (caller may want a more specific one).
        self.assertNotIn("error", manifest)

    def test_pending_vision_is_not_a_failure(self):
        """A clip whose vision is deferred via host_chat_paths is NOT in failed_clip_ids."""
        manifest = {
            "clip_count": 2,
            "clips": [
                _row("a", True),
                _row("b", False, vision_status="pending_host_analysis"),
            ],
        }
        _annotate_partial_success(manifest)
        self.assertFalse(manifest["partial_success"])
        self.assertEqual(manifest["completed_clip_ids"], ["a"])
        self.assertEqual(manifest["failed_clip_ids"], [])

    def test_existing_top_level_error_is_preserved(self):
        """If a more-specific aggregate error (e.g. CAPS_REFUSAL from the caps
        annotator) already landed, _annotate_partial_success must not overwrite it.
        """
        manifest = {
            "clip_count": 2,
            "clips": [
                _row("a", True),
                _row("b", False, error={"code": "CAPS_REFUSAL"}),
            ],
            "error": {"code": "CAPS_REFUSAL", "category": "budget_exhausted",
                      "retryable": False, "message": "preset cap reached"},
        }
        _annotate_partial_success(manifest)
        self.assertTrue(manifest["partial_success"])
        # CAPS_REFUSAL must win over the generic PARTIAL_FAILURE.
        self.assertEqual(manifest["error"]["code"], "CAPS_REFUSAL")

    def test_empty_clip_list_is_noop(self):
        manifest = {"clip_count": 0, "clips": []}
        _annotate_partial_success(manifest)
        # Helper short-circuits; no fields added.
        self.assertNotIn("partial_success", manifest)


if __name__ == "__main__":
    unittest.main()
