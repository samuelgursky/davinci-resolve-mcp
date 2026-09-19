"""A test that reaches a DaVinci Resolve launcher fails, under either runner.

The offline guard answers both servers' launchers with a stand-in, so a test
that reaches one no longer opens Resolve. But reaching one still means the test
asked for a real connection, and on v4.8.4 that went unnoticed: with the
granular launcher replaced by a counting stub, one full `unittest discover` run
reached it 10 times, all from `test_granular_destructive_op.McpSchema`. Every
`unittest.TestCase` now runs under a check that fails it for that
(`offline_guard._install_launch_check`).

These tests run small inner tests, each reaching a launcher the way a real one
could, and read the inner result. The outer test puts `LAUNCH_ATTEMPTS` back
afterwards, so the deliberate reaches do not show up in the pytest summary.

Nothing here needs, or reaches, a real Resolve: every launcher reached below is
the guard's stand-in.
"""

from __future__ import annotations

import unittest
from unittest import mock

from tests import offline_guard


def _run(*tests) -> unittest.TestResult:
    result = unittest.TestResult()
    unittest.TestSuite(list(tests)).run(result)
    return result


class LaunchCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        reason = offline_guard.SKIPPED_REASON or offline_guard.GRANULAR_SKIPPED_REASON
        if reason:
            self.skipTest(reason)
        saved = list(offline_guard.LAUNCH_ATTEMPTS)

        def restore() -> None:
            offline_guard.LAUNCH_ATTEMPTS[:] = saved

        self.addCleanup(restore)

    def new_attempts(self, before: int) -> list:
        return offline_guard.LAUNCH_ATTEMPTS[before:]

    def test_every_test_case_runs_under_the_check(self) -> None:
        self.assertTrue(
            offline_guard.launch_check_installed(),
            "unittest.TestCase.run is not the offline guard's wrapper",
        )

    def test_a_test_reaching_the_granular_launcher_fails(self) -> None:
        """The v4.8.4 path, with the guard's `get_resolve` put back to the real one."""
        from src.granular import common, media_pool

        class ProbesAProxy(unittest.TestCase):
            def test_probe(self) -> None:
                with mock.patch.object(common, "get_resolve", common._get_resolve_unpatched):
                    # `media_pool.resolve` is a ResolveProxy. Attribute access
                    # asks for a connection, finds none, and falls through to
                    # the launcher, as McpSchema's `hasattr` did.
                    hasattr(media_pool.resolve, "__granular_destructive__")

        before = len(offline_guard.LAUNCH_ATTEMPTS)
        result = _run(ProbesAProxy("test_probe"))

        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.failures), 1)
        message = result.failures[0][1]
        self.assertIn("A DaVinci Resolve launcher was reached", message)
        self.assertIn("ProbesAProxy.test_probe (called from src.granular.common)", message)
        attempts = self.new_attempts(before)
        self.assertEqual(len(attempts), 1)
        self.assertTrue(attempts[0].reported)

    def test_a_test_reaching_the_compound_launcher_fails(self) -> None:
        from src import server

        class NothingAnswers(unittest.TestCase):
            def test_connect(self) -> None:
                # The real `get_resolve` finds no Resolve and, with the guard's
                # `resolve_is_running` saying none is open, reaches for the launcher.
                with mock.patch.object(server, "resolve", None), mock.patch.object(
                    server, "_try_connect", return_value=None
                ):
                    server._get_resolve_unpatched()

        result = _run(NothingAnswers("test_connect"))

        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.failures), 1)
        self.assertIn(
            "NothingAnswers.test_connect (called from src.server)", result.failures[0][1]
        )

    def test_a_launch_outside_a_test_fails_the_next_test_only(self) -> None:
        """A class fixture runs outside any test's `run`. The next test to finish
        answers for it, and only that one."""
        from src.granular import common

        class ReachesInSetUpClass(unittest.TestCase):
            @classmethod
            def setUpClass(cls) -> None:
                common._launch_resolve()

            def test_first(self) -> None:
                pass

            def test_second(self) -> None:
                pass

        result = _run(ReachesInSetUpClass("test_first"), ReachesInSetUpClass("test_second"))

        self.assertEqual(result.testsRun, 2)
        self.assertEqual(result.errors, [])
        self.assertEqual([test.id().rsplit(".", 1)[-1] for test, _ in result.failures], ["test_first"])

    def test_a_test_that_removes_its_deliberate_entry_passes(self) -> None:
        """What `test_offline_guard_granular` does to exercise the stand-in itself."""
        from src.granular import common

        class CallsTheStandIn(unittest.TestCase):
            def test_call(self) -> None:
                before = len(offline_guard.LAUNCH_ATTEMPTS)
                self.assertFalse(common._launch_resolve())
                del offline_guard.LAUNCH_ATTEMPTS[before:]

        result = _run(CallsTheStandIn("test_call"))

        self.assertEqual(result.testsRun, 1)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)

    def test_a_test_that_reaches_nothing_passes(self) -> None:
        class ReachesNothing(unittest.TestCase):
            def test_nothing(self) -> None:
                pass

        result = _run(ReachesNothing("test_nothing"))

        self.assertEqual(result.testsRun, 1)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)


if __name__ == "__main__":
    unittest.main()
