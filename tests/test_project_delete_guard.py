"""Deleting a Resolve project is gated, and the open one is refused by default.

`project_manager delete` permanently deletes a named project through
`delete_project_safely` — a reliability helper that works around DeleteProject's
flakiness and session lock, not a safety guard. It closed and deleted the
project the user had OPEN without asking. And nothing gated it: the tool had no
`@_destructive_op`, `delete` was not registered, and the CRITICAL rule written
for it named `delete_project`, an action no tool dispatches, so it matched
nothing. Safe mode, dry-run refusal and the audit log never saw a project
deletion.

Its sibling `safe_project_delete` already refused the open project unless
`close_current=True`. The raw `delete` now does the same, and both are gated.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from src.utils import destructive_hook
from src.utils.execution_lifecycle import RiskClassificationHook, classify_operation_risk


class _FakeProjectManager:
    def __init__(self, open_name):
        self._open = mock.Mock()
        self._open.GetName.return_value = open_name

    def GetCurrentProject(self):
        return self._open


class ProjectDeleteGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = (destructive_hook._PROVIDER, destructive_hook._PREFERENCE_PROVIDER,
                      destructive_hook._PENDING_CONFIRM_CHECK)
        self.tmp = tempfile.TemporaryDirectory()
        self._prefs(safe_mode=False)
        destructive_hook.register_project_root_provider(lambda: None)

    def tearDown(self) -> None:
        (destructive_hook._PROVIDER, destructive_hook._PREFERENCE_PROVIDER,
         destructive_hook._PENDING_CONFIRM_CHECK) = self.saved
        self.tmp.cleanup()

    def _prefs(self, *, safe_mode: bool) -> None:
        values = {
            "destructive.safe_mode": safe_mode,
            "destructive.audit_log": True,
            "destructive.audit_log_path": os.path.join(self.tmp.name, "audit.jsonl"),
        }
        destructive_hook.register_preference_provider(values.get)

    def _delete(self, open_name, params):
        """Call the real tool against a fake project manager; return (result, deleter)."""
        from src import server

        resolve = mock.Mock()
        resolve.GetProjectManager.return_value = _FakeProjectManager(open_name)
        deleter = mock.Mock(return_value={"success": True, "attempts": 1, "leftover": None})
        with mock.patch.object(server, "get_resolve", return_value=resolve), \
                mock.patch("src.utils.project_cleanup.delete_project_safely", deleter):
            result = server.project_manager("delete", params)
        return result, deleter

    def test_the_raw_delete_refuses_the_open_project(self) -> None:
        """The call that loses a project someone is working in."""
        result, deleter = self._delete("Client Show", {"name": "Client Show"})
        self.assertIn("currently open project", json.dumps(result), result)
        deleter.assert_not_called()

    def test_close_current_true_lets_the_caller_mean_it(self) -> None:
        result, deleter = self._delete("Client Show", {"name": "Client Show", "close_current": True})
        self.assertTrue(result.get("success"), result)
        deleter.assert_called_once()
        self.assertEqual(deleter.call_args.args[1], "Client Show")

    def test_a_project_that_is_not_open_is_deleted_without_ceremony(self) -> None:
        result, deleter = self._delete("Other Show", {"name": "Old Show"})
        self.assertTrue(result.get("success"), result)
        deleter.assert_called_once()

    def test_safe_mode_blocks_the_raw_delete(self) -> None:
        self._prefs(safe_mode=True)
        result, deleter = self._delete("Other Show", {"name": "Old Show"})
        self.assertFalse(result.get("success"), result)
        deleter.assert_not_called()

    def test_a_dry_run_of_the_raw_delete_is_refused_not_executed(self) -> None:
        """`delete` has no native dry run, so an explicit one must be refused —
        a dry run that deletes a project is worse than none, because it is
        trusted."""
        result, deleter = self._delete("Other Show", {"name": "Old Show", "dry_run": True})
        self.assertEqual(result.get("status"), "dry_run_unavailable", result)
        deleter.assert_not_called()

    def test_both_project_deletes_are_rated_and_registered(self) -> None:
        for action, level in (("delete", "critical"), ("safe_project_delete", "high")):
            with self.subTest(action=action):
                risk = classify_operation_risk("project_manager", action, {})
                self.assertEqual(risk.level.value, level)
                self.assertTrue(risk.recognised and risk.destructive, risk)
                self.assertIn(action, destructive_hook.DESTRUCTIVE_ACTIONS_BY_TOOL["project_manager"])
        self.assertNotIn(("project_manager", "delete_project"), RiskClassificationHook._CRITICAL_ACTIONS,
                         "the old rule named an action that no tool dispatches")


if __name__ == "__main__":
    unittest.main()
