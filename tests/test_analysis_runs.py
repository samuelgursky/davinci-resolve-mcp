"""Unit tests for src/utils/analysis_runs.py (C6 hardening — run scoping).

No Resolve required.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from src.utils import analysis_runs, brain_edits, timeline_brain_db


class RunScoping(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="analysis_runs_test_")
        self.project_root = os.path.join(self.tmp, "project")
        os.makedirs(self.project_root, exist_ok=True)
        analysis_runs._reset_for_test()

    def tearDown(self) -> None:
        analysis_runs._reset_for_test()
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_begin_run_persists_and_sets_current(self) -> None:
        self.assertIsNone(analysis_runs.current_run_id())
        result = analysis_runs.begin_run(
            project_root=self.project_root,
            label="rough cut tighten",
            initiator="brain.chat",
        )
        self.assertTrue(result["success"])
        run_id = result["analysis_run_id"]
        self.assertEqual(analysis_runs.current_run_id(), run_id)
        self.assertEqual(analysis_runs.current_run_initiator(), "brain.chat")

        # DB row exists.
        run = analysis_runs.get_run(self.project_root, run_id)
        self.assertIsNotNone(run)
        self.assertEqual(run["label"], "rough cut tighten")
        self.assertEqual(run["initiator"], "brain.chat")
        self.assertIsNone(run["ended_at"])

    def test_end_run_aggregates_brain_edits_into_summary(self) -> None:
        opened = analysis_runs.begin_run(
            project_root=self.project_root, label="gap close",
            initiator="brain.chat",
        )
        run_id = opened["analysis_run_id"]
        # Simulate two declared edits under this run with the same metric.
        for before, after in [(120.0, 110.0), (110.0, 100.0)]:
            brain_edits.log_brain_edit(
                project_root=self.project_root,
                analysis_run_id=run_id,
                edit_type="timeline.delete_clips",
                target_metric="duration_seconds",
                before_value=before,
                after_value=after,
                project_name="proj",
            )
        ended = analysis_runs.end_run(project_root=self.project_root)
        self.assertTrue(ended["success"])
        self.assertEqual(ended["analysis_run_id"], run_id)
        summary = ended["summary"]
        self.assertEqual(summary["edit_count"], 2)
        per_metric = summary["per_metric"]
        self.assertIn("duration_seconds", per_metric)
        bucket = per_metric["duration_seconds"]
        self.assertEqual(bucket["edit_count"], 2)
        self.assertEqual(bucket["first_before"], 120.0)
        self.assertEqual(bucket["last_after"], 100.0)
        self.assertEqual(bucket["total_delta"], -20.0)
        # current_run_id cleared after end_run.
        self.assertIsNone(analysis_runs.current_run_id())

    def test_end_run_handles_no_active_run(self) -> None:
        result = analysis_runs.end_run(project_root=self.project_root)
        self.assertFalse(result["success"])
        self.assertIn("no active run", (result["error"].get("message","") if isinstance(result["error"], dict) else result["error"]))

    def test_begin_run_warns_when_replacing_active_run(self) -> None:
        first = analysis_runs.begin_run(project_root=self.project_root, label="first")
        second = analysis_runs.begin_run(project_root=self.project_root, label="second")
        # Both should persist; current_run_id should now point at second.
        self.assertEqual(analysis_runs.current_run_id(), second["analysis_run_id"])
        # First run is still in the DB even though it's no longer active.
        first_row = analysis_runs.get_run(self.project_root, first["analysis_run_id"])
        self.assertIsNotNone(first_row)

    def test_end_run_specific_id_when_not_active(self) -> None:
        opened = analysis_runs.begin_run(project_root=self.project_root)
        run_id = opened["analysis_run_id"]
        analysis_runs._reset_for_test()  # simulate a process restart
        ended = analysis_runs.end_run(
            project_root=self.project_root, analysis_run_id=run_id,
        )
        self.assertTrue(ended["success"])
        self.assertEqual(ended["analysis_run_id"], run_id)

    def test_list_runs_returns_newest_first(self) -> None:
        ids = []
        for label in ("first", "second", "third"):
            ids.append(analysis_runs.begin_run(
                project_root=self.project_root, label=label,
            )["analysis_run_id"])
        rows = analysis_runs.list_runs(self.project_root, limit=10)
        # Newest first.
        self.assertEqual([r["label"] for r in rows][0], "third")
        self.assertEqual(len(rows), 3)


class HookIntegration(unittest.TestCase):
    """Sanity-check that the destructive_hook helpers consult analysis_runs."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="hook_integration_test_")
        self.project_root = os.path.join(self.tmp, "project")
        os.makedirs(self.project_root, exist_ok=True)
        analysis_runs._reset_for_test()

    def tearDown(self) -> None:
        analysis_runs._reset_for_test()
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_extract_analysis_run_id_uses_current_run_when_no_param(self) -> None:
        from src.utils import destructive_hook
        opened = analysis_runs.begin_run(project_root=self.project_root)
        try:
            run_id = destructive_hook._extract_analysis_run_id(None)
            self.assertEqual(run_id, opened["analysis_run_id"])
            # Explicit param wins.
            override = destructive_hook._extract_analysis_run_id({"analysis_run_id": "explicit_xyz"})
            self.assertEqual(override, "explicit_xyz")
        finally:
            analysis_runs.end_run(project_root=self.project_root)

    def test_extract_initiator_uses_current_run_when_no_param(self) -> None:
        from src.utils import destructive_hook
        analysis_runs.begin_run(
            project_root=self.project_root, initiator="brain.chat",
        )
        try:
            self.assertEqual(destructive_hook._extract_initiator(None), "brain.chat")
            self.assertEqual(
                destructive_hook._extract_initiator({"initiator": "user.explicit"}),
                "user.explicit",
            )
        finally:
            analysis_runs.end_run(project_root=self.project_root)


if __name__ == "__main__":
    unittest.main()
