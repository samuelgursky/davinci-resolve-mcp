"""Contract tests for B3 — auto-open brain-edit run on first destructive call.

See local/design/agentic-flow-improvements-gameplan.md §3 task B3.
"""
import os
import tempfile
import time
import unittest

from src.utils import analysis_runs, timeline_brain_db


class AutoRunLifecycleTest(unittest.TestCase):
    def setUp(self):
        analysis_runs._reset_for_test()
        self.tmpdir = tempfile.mkdtemp(prefix="auto-run-")
        # Initialize the DB so begin_run/end_run can insert rows.
        timeline_brain_db.connect(self.tmpdir)

    def tearDown(self):
        analysis_runs._reset_for_test()
        try:
            timeline_brain_db.close_connection(self.tmpdir)
        except Exception:
            pass

    def test_first_destructive_opens_auto_run(self):
        self.assertIsNone(analysis_runs.current_run_id())
        run_id = analysis_runs.ensure_auto_run_for_destructive(
            project_root=self.tmpdir, idle_timeout_seconds=90,
        )
        self.assertTrue(run_id.startswith("run_"))
        self.assertEqual(analysis_runs.current_run_id(), run_id)
        self.assertEqual(analysis_runs.current_run_initiator(), "auto")

    def test_three_calls_within_window_reuse_same_run(self):
        r1 = analysis_runs.ensure_auto_run_for_destructive(
            project_root=self.tmpdir, idle_timeout_seconds=90,
        )
        r2 = analysis_runs.ensure_auto_run_for_destructive(
            project_root=self.tmpdir, idle_timeout_seconds=90,
        )
        r3 = analysis_runs.ensure_auto_run_for_destructive(
            project_root=self.tmpdir, idle_timeout_seconds=90,
        )
        self.assertEqual(r1, r2)
        self.assertEqual(r2, r3)

    def test_idle_timeout_opens_fresh_run(self):
        r1 = analysis_runs.ensure_auto_run_for_destructive(
            project_root=self.tmpdir, idle_timeout_seconds=0.05,
        )
        time.sleep(0.1)
        r2 = analysis_runs.ensure_auto_run_for_destructive(
            project_root=self.tmpdir, idle_timeout_seconds=0.05,
        )
        self.assertNotEqual(r1, r2)
        # The first one was auto-closed; verify by inspecting the row.
        row = analysis_runs.get_run(self.tmpdir, r1)
        self.assertIsNotNone(row)
        self.assertIsNotNone(row["ended_at"])

    def test_explicit_begin_run_overrides_auto(self):
        explicit = analysis_runs.begin_run(
            project_root=self.tmpdir, label="hand-rolled", initiator="user.explicit",
        )["analysis_run_id"]
        # Subsequent auto-run helper should reuse the active explicit run.
        auto = analysis_runs.ensure_auto_run_for_destructive(
            project_root=self.tmpdir, idle_timeout_seconds=90,
        )
        self.assertEqual(explicit, auto)
        self.assertEqual(analysis_runs.current_run_initiator(), "user.explicit")


if __name__ == "__main__":
    unittest.main()
