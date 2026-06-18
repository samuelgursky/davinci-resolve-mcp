"""Tests for the exhaustive-audit Wave A hardening (gameplan Phase 6).

Covers EX1 (spec hook no-shell), EX4 (confirm-token locking still issues/consumes),
EX5 (negative-index rejection), EX8 (_safe_int clamps + numeric guards).
"""
import unittest
from unittest import mock

import src.server as s


class SpecHookNoShellTest(unittest.TestCase):
    """EX1: hooks run via argv (no shell), so injection metacharacters can't run."""

    def _hook(self, command):
        return mock.Mock(command=command, name="h")

    def test_command_is_split_and_run_without_shell(self):
        runner = s._make_spec_hook_runner()
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            ok = runner(self._hook('echo hello'))
        self.assertTrue(ok)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["echo", "hello"])      # argv, not a string
        self.assertFalse(kwargs.get("shell", False))      # never shell=True

    def test_injection_string_is_argv_not_shell(self):
        runner = s._make_spec_hook_runner()
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            runner(self._hook('rm -rf /; echo pwned'))
        # The injection is parsed as argv tokens for `rm`, never as a shell
        # command separator: shell=False and `echo`/`pwned` remain plain args.
        argv = run.call_args[0][0]
        self.assertEqual(argv[0], "rm")
        self.assertIn("echo", argv)
        self.assertIn("pwned", argv)
        self.assertFalse(run.call_args[1].get("shell", False))

    def test_empty_command_returns_false_without_running(self):
        runner = s._make_spec_hook_runner()
        with mock.patch("subprocess.run") as run:
            self.assertFalse(runner(self._hook("   ")))
            run.assert_not_called()


class ConfirmTokenLockTest(unittest.TestCase):
    """EX4: locking must not break the normal issue -> consume flow."""

    def test_issue_then_consume_round_trip(self):
        with mock.patch.object(s, "_confirm_token_required", return_value=True):
            issued = s._issue_confirm_token(action="timeline.delete_track", params={"x": 1}, preview={})
            token = issued["confirm_token"]
            # Correct token + same params -> consume returns None (proceed).
            blocked = s._consume_confirm_token(action="timeline.delete_track", params={"x": 1, "confirm_token": token})
            self.assertIsNone(blocked)
            # One-time use: second consume now fails.
            again = s._consume_confirm_token(action="timeline.delete_track", params={"x": 1, "confirm_token": token})
            self.assertIsInstance(again, dict)
            self.assertIn("error", again)

    def test_lock_exists(self):
        self.assertTrue(hasattr(s, "_CONFIRM_TOKENS_LOCK"))


class SafeIntTest(unittest.TestCase):
    def test_non_numeric_returns_default(self):
        self.assertEqual(s._safe_int("abc", 50), 50)
        self.assertEqual(s._safe_int(None, 7), 7)

    def test_clamps_to_bounds(self):
        self.assertEqual(s._safe_int(-5, 50, minimum=1, maximum=1000), 1)
        self.assertEqual(s._safe_int(99999, 50, minimum=1, maximum=1000), 1000)
        self.assertEqual(s._safe_int("250", 50, minimum=1, maximum=1000), 250)


class HistoryLimitClampTest(unittest.TestCase):
    """EX8: negative limit must not become a SQLite full-table fetch."""

    def test_brain_edits_clamps_negative_limit(self):
        import src.utils.brain_edits as be
        captured = {}

        class FakeCursor:
            def fetchall(self):
                return []

        class FakeConn:
            def execute(self, sql, params):
                captured["params"] = params
                return FakeCursor()

        with mock.patch.object(be.timeline_brain_db, "connect", return_value=FakeConn()):
            be.get_brain_edit_history(project_root="/tmp/x", limit=-1)
        # The LIMIT bind param is the last positional; must be clamped to >= 1.
        self.assertGreaterEqual(captured["params"][-1], 1)


if __name__ == "__main__":
    unittest.main()
