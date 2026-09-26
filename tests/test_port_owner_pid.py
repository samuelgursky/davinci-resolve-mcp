"""`_port_owner_pid` must come back within its deadline even when lsof cannot
be killed.

On macOS, lsof wedges in uninterruptible kernel wait (state ``U``) when a
network mount is stale, and a process in that state ignores SIGKILL. The
previous ``subprocess.run(timeout=3)`` form killed the child on expiry and
then waited for it, so the caller hung with the child: on 2026-09-26 the
offline suite sat in this function for 13 minutes behind 489 wedged lsof
processes. The function now polls to a deadline and abandons the child.

No Resolve required.
"""

from __future__ import annotations

import io
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

from src import server


class _StuckPopen:
    """A child that never exits and whose kill() does nothing, like lsof in U."""

    instances: list["_StuckPopen"] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.stdout = io.BytesIO(b"")
        self.kill_calls = 0
        self.wait_calls = 0
        self.communicate_calls = 0
        _StuckPopen.instances.append(self)

    def poll(self):
        return None

    def kill(self):
        self.kill_calls += 1

    def wait(self, *a, **k):
        self.wait_calls += 1
        raise AssertionError("wait() joins an unkillable child")

    def communicate(self, *a, **k):
        self.communicate_calls += 1
        raise AssertionError("communicate() joins an unkillable child")


class _ExitedPopen(_StuckPopen):
    """A child that already exited and printed one PID."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stdout = io.BytesIO(b"4242\n")
        self.returncode = 0

    def poll(self):
        return 0


class FakeChildTests(unittest.TestCase):
    def setUp(self) -> None:
        _StuckPopen.instances.clear()

    def test_returns_none_at_the_deadline_without_joining_the_child(self) -> None:
        with mock.patch.object(subprocess, "Popen", _StuckPopen):
            t0 = time.monotonic()
            got = server._port_owner_pid("127.0.0.1", 8765, timeout=0.5)
            elapsed = time.monotonic() - t0
        self.assertIsNone(got)
        self.assertLess(elapsed, 1.5, f"took {elapsed:.2f}s against a 0.5s deadline")
        (child,) = _StuckPopen.instances
        self.assertEqual(child.kill_calls, 1)
        self.assertEqual(child.wait_calls, 0)
        self.assertEqual(child.communicate_calls, 0)
        self.assertTrue(child.stdout.closed, "stdout pipe must be closed on the way out")

    def test_child_is_started_in_its_own_session(self) -> None:
        with mock.patch.object(subprocess, "Popen", _StuckPopen):
            server._port_owner_pid("127.0.0.1", 8765, timeout=0.05)
        (child,) = _StuckPopen.instances
        self.assertTrue(child.kwargs.get("start_new_session"))
        self.assertEqual(child.args[0][:2], ["lsof", "-nP"])
        self.assertIn("-iTCP:8765", child.args[0])

    def test_an_exited_child_still_yields_its_pid(self) -> None:
        with mock.patch.object(subprocess, "Popen", _ExitedPopen):
            self.assertEqual(server._port_owner_pid("127.0.0.1", 8765, timeout=0.5), 4242)
        (child,) = _StuckPopen.instances
        self.assertEqual(child.kill_calls, 0)
        self.assertTrue(child.stdout.closed)

    def test_missing_lsof_is_none_not_an_exception(self) -> None:
        with mock.patch.object(subprocess, "Popen", side_effect=FileNotFoundError("lsof")):
            self.assertIsNone(server._port_owner_pid("127.0.0.1", 8765, timeout=0.5))


class RealChildTests(unittest.TestCase):
    """A real subprocess that ignores SIGTERM and sleeps, with kill() disabled
    so it behaves like a child SIGKILL cannot reach. Exercises the actual
    Popen/pipe plumbing rather than the fake above."""

    def test_deadline_holds_against_a_live_child(self) -> None:
        real_popen = subprocess.Popen
        spawned: list[subprocess.Popen] = []

        def sleeper_popen(argv, **kwargs):
            proc = real_popen(
                [sys.executable, "-c",
                 "import signal, time\n"
                 "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                 "time.sleep(30)\n"],
                **kwargs,
            )
            spawned.append(proc)
            return proc

        def cleanup():
            for proc in spawned:
                try:
                    proc.send_signal(signal.SIGKILL)
                    proc.wait(timeout=5)
                except Exception:
                    pass
                for stream in (proc.stdout, proc.stderr, proc.stdin):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass
        self.addCleanup(cleanup)

        with mock.patch.object(subprocess, "Popen", sleeper_popen), \
             mock.patch.object(real_popen, "kill", lambda self: None):
            t0 = time.monotonic()
            got = server._port_owner_pid("127.0.0.1", 8765, timeout=0.5)
            elapsed = time.monotonic() - t0

        self.assertIsNone(got)
        self.assertLess(elapsed, 1.5, f"took {elapsed:.2f}s against a 0.5s deadline")
        (proc,) = spawned
        self.assertIsNone(proc.poll(), "the child was left running, not joined")


if __name__ == "__main__":
    unittest.main()
