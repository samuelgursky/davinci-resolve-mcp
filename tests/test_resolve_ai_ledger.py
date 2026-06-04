"""Tests for the Resolve 21 AI-ops ledger (src/utils/resolve_ai_ledger.py)."""
import tempfile
import unittest

from src.utils import resolve_ai_ledger as L


class LedgerRecordQueryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_op_meta_classification(self):
        self.assertEqual(L.op_meta("remove_motion_blur")["op_class"], L.OP_CLASS_RENDER)
        self.assertEqual(L.op_meta("generate_speech")["op_class"], L.OP_CLASS_RENDER)
        self.assertEqual(L.op_meta("analyze_for_slate")["op_class"], L.OP_CLASS_ANALYSIS)
        self.assertEqual(L.op_meta("analyze_for_slate")["extra_required"], "AI Slate ID")
        self.assertEqual(L.op_meta("perform_audio_classification")["extra_required"], None)
        # Unknown op falls back to analysis/no-extra.
        self.assertEqual(L.op_meta("nope")["op_class"], L.OP_CLASS_ANALYSIS)

    def test_record_and_get_usage(self):
        rid = L.record_op(project_root=self.root, op="analyze_for_slate", clip_id="c1",
                          session_id="s1", success=True, wall_clock_ms=120)
        self.assertIsNotNone(rid)
        rows = L.get_usage(project_root=self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["op"], "analyze_for_slate")
        self.assertEqual(rows[0]["success"], 1)
        self.assertEqual(rows[0]["op_class"], "analysis")
        self.assertEqual(rows[0]["extra_required"], "AI Slate ID")

    def test_no_project_root_is_noop(self):
        self.assertIsNone(L.record_op(project_root="", op="analyze_for_slate"))
        self.assertEqual(L.get_usage(project_root=""), [])
        self.assertEqual(L.get_summary(project_root="")["totals"]["runs"], 0)

    def test_timed_context_manager_records(self):
        with L.timed(self.root, "perform_audio_classification", clip_id="c1", session_id="s1") as rec:
            rec.success = True
        rows = L.get_usage(project_root=self.root, op="perform_audio_classification")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["success"], 1)

    def test_timed_records_exception_and_reraises(self):
        with self.assertRaises(ValueError):
            with L.timed(self.root, "analyze_for_slate", session_id="s1") as rec:
                raise ValueError("boom")
        rows = L.get_usage(project_root=self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["success"], 0)
        self.assertIn("boom", rows[0]["error"])

    def test_timed_none_root_is_noop(self):
        # Should not raise and should record nothing.
        with L.timed(None, "analyze_for_slate") as rec:
            rec.success = True
        self.assertEqual(L.get_usage(project_root=self.root), [])

    def test_summary_aggregates_files_and_bytes(self):
        L.record_op(project_root=self.root, op="remove_motion_blur", session_id="s1",
                    success=True, wall_clock_ms=5000, output_path="/tmp/a_deblur.mov", output_bytes=2_000_000)
        L.record_op(project_root=self.root, op="remove_motion_blur", session_id="s1",
                    success=True, wall_clock_ms=3000, output_path="/tmp/b_deblur.mov", output_bytes=1_000_000)
        L.record_op(project_root=self.root, op="analyze_for_slate", session_id="s1", success=False, error="no Extra")
        summary = L.get_summary(project_root=self.root)
        totals = summary["totals"]
        self.assertEqual(totals["runs"], 3)
        self.assertEqual(totals["successes"], 2)
        self.assertEqual(totals["failures"], 1)
        self.assertEqual(totals["files_created"], 2)
        self.assertEqual(totals["bytes_created"], 3_000_000)
        self.assertEqual(totals["wall_clock_ms"], 8000)
        deblur = summary["by_op"]["remove_motion_blur"]
        self.assertEqual(deblur["op_class"], "render")
        self.assertEqual(deblur["files_created"], 2)

    def test_session_scoping(self):
        L.record_op(project_root=self.root, op="analyze_for_slate", session_id="s1", success=True)
        L.record_op(project_root=self.root, op="analyze_for_slate", session_id="s2", success=True)
        self.assertEqual(L.get_summary(project_root=self.root, session_id="s1")["totals"]["runs"], 1)
        self.assertEqual(L.get_summary(project_root=self.root)["totals"]["runs"], 2)


if __name__ == "__main__":
    unittest.main()
