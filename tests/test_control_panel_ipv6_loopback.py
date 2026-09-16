"""The control panel on the IPv6 loopback, launched for real.

`::1` is on both loopback allowlists (open_control_panel and the panel's own
--host check, whose refusal names it), yet the panel could never serve there:
ThreadingHTTPServer is AF_INET, so binding `::1` raised gaierror and the child
exited before serving. The URLs were also written `http://::1:<port>/`, which
no browser or urllib accepts. These tests launch the real panel on `::1` and
use the URL it hands back. No Resolve, no browser.
"""
from __future__ import annotations

import http.client
import os
import socket
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlsplit

import src.analysis_dashboard as dash
from src import server


def _ipv6_loopback_port() -> int | None:
    """A free port on ::1, or None when this host has no IPv6 loopback."""
    if not socket.has_ipv6:
        return None
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            sock.bind(("::1", 0))
            return sock.getsockname()[1]
    except OSError:
        return None


class ControlPanelIPv6Loopback(unittest.TestCase):
    def setUp(self) -> None:
        self.port = _ipv6_loopback_port()
        if self.port is None:
            self.skipTest("no IPv6 loopback on this host")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # The launcher writes its log under ~/Documents; keep it in the sandbox.
        env = mock.patch.dict(os.environ, {"HOME": self.tmp.name, "USERPROFILE": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        for target, value in (
            ("_control_panel_pidfile", os.path.join(self.tmp.name, "control_panel.json")),
            ("_port_owner_pid", None),
        ):
            patcher = mock.patch.object(server, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _launch(self) -> dict:
        result = server._open_control_panel({
            "host": "::1",
            "port": self.port,
            "analysis_root": os.path.join(self.tmp.name, "analysis"),
        })
        if result.get("pid"):
            self.addCleanup(self._stop, result["pid"])
        return result

    @staticmethod
    def _stop(pid: int) -> None:
        try:
            os.kill(pid, 15)
        except OSError:
            pass

    def test_panel_serves_on_ipv6_loopback(self) -> None:
        result = self._launch()
        self.assertTrue(result.get("success"), result)
        self.assertEqual(result["status"], "launched")

        conn = http.client.HTTPConnection("::1", self.port, timeout=5)
        try:
            conn.request("GET", "/", headers={"Host": f"[::1]:{self.port}"})
            self.assertEqual(conn.getresponse().status, 200)
        finally:
            conn.close()

    def test_issued_url_is_usable(self) -> None:
        result = self._launch()
        self.assertTrue(result.get("success"), result)
        url = urlsplit(result["url"])
        self.assertEqual(url.netloc, f"[::1]:{self.port}")
        self.assertEqual(url.hostname, "::1")
        self.assertEqual(url.port, self.port)

        token = url.fragment.split("=", 1)[1]
        # First /api/boot is slow (cold inventory warm-up), so be patient.
        probe = server._control_panel_probe("::1", self.port, timeout=30, token=token)
        self.assertTrue(probe["is_dashboard"], probe)


class PanelUrlHost(unittest.TestCase):
    def test_brackets_only_ipv6_literals(self) -> None:
        for host, expected in (
            ("127.0.0.1", "127.0.0.1"),
            ("localhost", "localhost"),
            ("::1", "[::1]"),
            ("[::1]", "[::1]"),
        ):
            self.assertEqual(dash.panel_url_host(host), expected)
        self.assertEqual(server._control_panel_url_host("::1"), "[::1]")
        self.assertEqual(server._control_panel_url_host("127.0.0.1"), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
