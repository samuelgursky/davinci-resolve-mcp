"""resolve_headless.py recovery paths (issue #172).

A -nogui instance that never becomes scriptable holds the one-per-machine
singleton, so the GUI cannot start either. The script must therefore
(a) clean up an instance IT started when the readiness check fails, and
(b) offer stop --force as an escalation for an unanswering instance —
the refusal default is right for a working session, wrong for a wedged one.

All mocked; no live Resolve is touched.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "resolve_headless.py"
_spec = importlib.util.spec_from_file_location("resolve_headless_script", _SCRIPT)
rh = importlib.util.module_from_spec(_spec)
sys.modules["resolve_headless_script"] = rh
_spec.loader.exec_module(rh)


class StopEscalation(unittest.TestCase):
    def test_stop_without_force_refuses_unanswering_instance(self):
        with mock.patch.object(rh.rr, "runtime_mode", return_value={"running": True}), \
             mock.patch.object(rh, "_connect", return_value=None), \
             mock.patch.object(rh, "_force_stop") as force:
            self.assertEqual(rh.stop(1.0), 5)
        force.assert_not_called()

    def test_stop_force_escalates_when_unanswering(self):
        with mock.patch.object(rh.rr, "runtime_mode", return_value={"running": True}), \
             mock.patch.object(rh, "_connect", return_value=None), \
             mock.patch.object(rh, "_force_stop", return_value=0) as force:
            self.assertEqual(rh.stop(1.0, force=True), 0)
        force.assert_called_once()

    def test_stop_force_escalates_when_quit_hangs(self):
        resolve = mock.Mock()
        with mock.patch.object(rh.rr, "runtime_mode", return_value={"running": True}), \
             mock.patch.object(rh, "_connect", return_value=resolve), \
             mock.patch.object(rh.rr, "resolve_processes", return_value=["Resolve -nogui"]), \
             mock.patch.object(rh, "_force_stop", return_value=0) as force, \
             mock.patch.object(rh.time, "sleep"):
            self.assertEqual(rh.stop(0.1, force=True), 0)
        resolve.Quit.assert_called_once()
        force.assert_called_once()


class StartCleanup(unittest.TestCase):
    def test_failed_start_kills_the_instance_it_spawned(self):
        proc = mock.Mock()
        proc.pid = 4242
        with mock.patch.object(rh, "cmd_guard", return_value=0), \
             mock.patch.object(rh.rr, "launch_command", return_value=["/x/Resolve", "-nogui"]), \
             mock.patch.object(rh.subprocess, "Popen", return_value=proc), \
             mock.patch.object(rh, "wait_until_scriptable", return_value=None), \
             mock.patch.object(rh, "_kill_process", return_value=True) as killer:
            self.assertEqual(rh.start(0.1), 4)
        killer.assert_called_once_with(proc)

    def test_successful_start_does_not_kill(self):
        proc = mock.Mock()
        with mock.patch.object(rh, "cmd_guard", return_value=0), \
             mock.patch.object(rh.rr, "launch_command", return_value=["/x/Resolve", "-nogui"]), \
             mock.patch.object(rh.subprocess, "Popen", return_value=proc), \
             mock.patch.object(rh, "wait_until_scriptable", return_value=object()), \
             mock.patch.object(rh, "_kill_process") as killer:
            self.assertEqual(rh.start(0.1), 0)
        killer.assert_not_called()


class KillProcess(unittest.TestCase):
    def test_term_then_kill_escalation(self):
        proc = mock.Mock()
        proc.wait.side_effect = [rh.subprocess.TimeoutExpired(cmd="x", timeout=1), None]
        self.assertTrue(rh._kill_process(proc, grace=0.01))
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
