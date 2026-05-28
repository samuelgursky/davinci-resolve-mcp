"""Unit tests for the open_control_panel hardening: port-collision guard,
stale-version detection (tracked and untracked), and force_restart path.

No Resolve required; the dashboard launch itself is stubbed.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from src import server


class ControlPanelStaleDetection(unittest.TestCase):
    """When a dashboard is listening on the target port and reports a
    different mcp_version than the live one (or no version at all),
    open_control_panel must surface ``stale_running`` with a remediation
    rather than silently using the stale instance.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pidfile = os.path.join(self.tmp.name, "control_panel.pid")
        self._patches = [
            mock.patch.object(server, "_control_panel_pidfile", return_value=self.pidfile),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _write_state(self, pid: int) -> None:
        with open(self.pidfile, "w", encoding="utf-8") as fh:
            json.dump({
                "pid": pid, "port": 8765, "host": "127.0.0.1",
                "url": "http://127.0.0.1:8765",
            }, fh)

    def test_stale_running_when_remote_version_differs(self) -> None:
        self._write_state(99999)
        with mock.patch.object(server, "_control_panel_pid_alive", return_value=True), \
             mock.patch.object(server, "_port_owner_pid", return_value=99999), \
             mock.patch.object(server, "_control_panel_probe",
                               return_value={"is_dashboard": True, "version": "2.20.0"}), \
             mock.patch.object(server, "VERSION", "2.24.1"):
            result = server._open_control_panel({})
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "stale_running")
        self.assertEqual(result["running_version"], "2.20.0")
        self.assertEqual(result["live_version"], "2.24.1")
        self.assertIn("force_restart=true", result["remediation"])

    def test_already_running_when_versions_match(self) -> None:
        self._write_state(99999)
        with mock.patch.object(server, "_control_panel_pid_alive", return_value=True), \
             mock.patch.object(server, "_port_owner_pid", return_value=99999), \
             mock.patch.object(server, "_control_panel_probe",
                               return_value={"is_dashboard": True, "version": "2.24.1"}), \
             mock.patch.object(server, "VERSION", "2.24.1"):
            result = server._open_control_panel({})
        self.assertEqual(result["status"], "already_running")
        self.assertEqual(result["running_version"], "2.24.1")

    def test_stale_running_when_remote_version_missing(self) -> None:
        # Older dashboards that predate the mcp_version field are stale too —
        # they can't honor newer surfaces, and the caller needs to know.
        self._write_state(99999)
        with mock.patch.object(server, "_control_panel_pid_alive", return_value=True), \
             mock.patch.object(server, "_port_owner_pid", return_value=99999), \
             mock.patch.object(server, "_control_panel_probe",
                               return_value={"is_dashboard": True, "version": None}), \
             mock.patch.object(server, "VERSION", "2.24.1"):
            result = server._open_control_panel({})
        self.assertEqual(result["status"], "stale_running")
        self.assertIsNone(result["running_version"])
        self.assertEqual(result["live_version"], "2.24.1")
        self.assertIn("predates", result["remediation"])

    def test_stale_running_when_untracked_dashboard_owns_port(self) -> None:
        # The real-world bug: pidfile missing (this MCP didn't spawn the
        # listener) but a dashboard from a prior MCP session survived a
        # restart. The freshness check must still fire on the basis of the
        # port-owner probe alone.
        # No _write_state() — pidfile intentionally absent.
        with mock.patch.object(server, "_port_owner_pid", return_value=97877), \
             mock.patch.object(server, "_control_panel_probe",
                               return_value={"is_dashboard": True, "version": "2.24.0"}), \
             mock.patch.object(server, "VERSION", "2.24.1"):
            result = server._open_control_panel({})
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "stale_running")
        self.assertEqual(result["pid"], 97877)
        self.assertEqual(result["running_version"], "2.24.0")
        self.assertEqual(result["live_version"], "2.24.1")


class PortCollisionGuard(unittest.TestCase):
    """When the target port is held by a non-dashboard process,
    open_control_panel must refuse rather than spawn a child that will
    crash silently with `Address already in use`.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pidfile = os.path.join(self.tmp.name, "control_panel.pid")
        self._patches = [
            mock.patch.object(server, "_control_panel_pidfile", return_value=self.pidfile),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_refuses_when_non_dashboard_process_owns_port(self) -> None:
        with mock.patch.object(server, "_port_owner_pid", return_value=12345), \
             mock.patch.object(server, "_control_panel_probe",
                               return_value={"is_dashboard": False, "version": None}):
            result = server._open_control_panel({})
        self.assertFalse(result.get("success"))
        err = result.get("error")
        msg = err.get("message") if isinstance(err, dict) else str(err)
        self.assertIn("12345", msg)
        self.assertIn("not a control panel", msg)
        self.assertIn("force_restart=true", msg)


class ControlPanelProbe(unittest.TestCase):
    """`_control_panel_probe` is the new helper that distinguishes a
    dashboard listener from a non-dashboard squatter, regardless of whether
    the listener exposes the ``mcp_version`` field.
    """

    def test_recognizes_dashboard_with_version(self) -> None:
        payload = {
            "success": True,
            "project_name": "CKY",
            "capabilities": {"mcp_version": "2.24.1"},
        }
        with mock.patch("urllib.request.urlopen") as m:
            ctx = m.return_value.__enter__.return_value
            ctx.read.return_value = json.dumps(payload).encode("utf-8")
            result = server._control_panel_probe("127.0.0.1", 8765)
        self.assertEqual(result, {"is_dashboard": True, "version": "2.24.1"})

    def test_recognizes_dashboard_without_version(self) -> None:
        payload = {"success": True, "project_name": "CKY"}
        with mock.patch("urllib.request.urlopen") as m:
            ctx = m.return_value.__enter__.return_value
            ctx.read.return_value = json.dumps(payload).encode("utf-8")
            result = server._control_panel_probe("127.0.0.1", 8765)
        self.assertEqual(result, {"is_dashboard": True, "version": None})

    def test_non_dashboard_response(self) -> None:
        # Some other HTTP server happens to be on the port.
        with mock.patch("urllib.request.urlopen") as m:
            ctx = m.return_value.__enter__.return_value
            ctx.read.return_value = b'{"some": "other-server"}'
            result = server._control_panel_probe("127.0.0.1", 8765)
        self.assertEqual(result, {"is_dashboard": False, "version": None})

    def test_connection_failure(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = server._control_panel_probe("127.0.0.1", 8765)
        self.assertEqual(result, {"is_dashboard": False, "version": None})


if __name__ == "__main__":
    unittest.main()
