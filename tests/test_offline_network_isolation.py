"""The offline suite must not send requests off this machine.

`install.py` checks GitHub for a newer release, and `test_scripting_lib_discovery`
runs its `main()` in-process. So every `python -m unittest discover -s tests -t .`
sent a live request to
`https://api.github.com/repos/samuelgursky/davinci-resolve-mcp/releases/latest`
and wrote the answer into `logs/update-check.json`. Nothing in the suite said so.
A tripwire around `urllib.request.urlopen` caught it, from
`test_only_the_designated_live_test_touches_a_real_resolve` through
`test_a_failed_verification_exits_non_zero` and `_run_main` into
`update_check._fetch_latest_release`.

`offline_guard` now refuses every `urlopen` that would leave the machine and
records who asked; loopback requests, which the control-panel tests make, go
through. The installer tests also switch the update check off, so a clean run
records no attempt at all. This is the tripwire. It fails if the guard is
missing or was replaced, if it lets a remote URL through or stops a loopback
one, if the update check stops going through it, or if the installer tests
start asking for the network again.
"""

from __future__ import annotations

import http.server
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

# The module, not its classes: a TestCase imported into this namespace would be
# collected and run a second time under this file's name.
import tests.test_scripting_lib_discovery as discovery
from src.utils import update_check
from tests import offline_guard

RELEASES_URL = f"https://api.github.com/repos/{update_check.DEFAULT_REPO}/releases/latest"
THIS_FILE = os.path.join("tests", Path(__file__).name)


class _Hello(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"loopback ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


class _IPv6Server(http.server.ThreadingHTTPServer):
    address_family = socket.AF_INET6


class OfflineNetworkIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        # Checked before any test here opens a URL, so a missing guard fails the
        # test instead of letting it send the request it exists to stop.
        if not offline_guard.network_guard_installed():
            self.fail(
                "urllib.request.urlopen is not the offline guard: install() did not "
                "run, or a test replaced urlopen without putting it back"
            )
        # The attempts made here on purpose are removed again, so they do not
        # show up in the pytest summary next to real leaks.
        self._mark = len(offline_guard.NETWORK_ATTEMPTS)
        self.addCleanup(offline_guard.NETWORK_ATTEMPTS.__delitem__, slice(self._mark, None))

    def _new_attempts(self) -> list:
        return offline_guard.NETWORK_ATTEMPTS[self._mark:]

    def _serve(self, server_class, host: str) -> int:
        server = server_class((host, 0), _Hello)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def _spy_downstream(self) -> mock.Mock:
        """Stand in for whatever the guard wraps, so a wrong verdict cannot go out."""
        downstream = mock.Mock(side_effect=AssertionError("the guard let the request through"))
        patcher = mock.patch.object(urllib.request.urlopen, "__wrapped__", downstream)
        patcher.start()
        self.addCleanup(patcher.stop)
        return downstream

    def test_a_request_off_this_machine_is_refused_and_named(self) -> None:
        downstream = self._spy_downstream()
        for url in (RELEASES_URL, urllib.request.Request(RELEASES_URL)):
            with self.subTest(type(url).__name__):
                with self.assertRaises(offline_guard.NetworkRefused) as caught:
                    urllib.request.urlopen(url, timeout=1)
                # A URLError, so callers take the path they take with no network.
                self.assertIsInstance(caught.exception, urllib.error.URLError)
        downstream.assert_not_called()

        attempts = self._new_attempts()
        self.assertEqual([a["url"] for a in attempts], [RELEASES_URL, RELEASES_URL])
        for attempt in attempts:
            self.assertTrue(attempt["caller"].startswith(THIS_FILE + ":"), attempt)
            self.assertTrue(
                attempt["test"].endswith("in test_a_request_off_this_machine_is_refused_and_named"),
                attempt,
            )

    def test_what_counts_as_this_machine(self) -> None:
        local = (
            "http://127.0.0.1:8765/api/boot",
            "http://127.8.9.10/",
            "http://localhost:8765/",
            "http://LOCALHOST./",
            "http://[::1]:8765/api/boot",
            "file:///tmp/update-check.json",
            "data:,hello",
        )
        remote = (
            RELEASES_URL,
            f"https://api.github.com/repos/{update_check.DEFAULT_REPO}/releases?per_page=10",
            "http://localhost.evil.example/",
            "http://127.0.0.1.evil.example/",
            "http://10.0.0.1/",
            "http://[2001:db8::1]/",
            "http://ollama.example:11434/api/tags",
            "http:///no-host",
            "not a url",
        )
        for url in local:
            with self.subTest(url=url):
                self.assertTrue(offline_guard.stays_on_this_machine(url))
        for url in remote:
            with self.subTest(url=url):
                self.assertFalse(offline_guard.stays_on_this_machine(url))

    def test_loopback_requests_still_go_through(self) -> None:
        """The control-panel tests serve and probe a real panel on loopback."""
        port = self._serve(http.server.ThreadingHTTPServer, "127.0.0.1")
        for url in (f"http://127.0.0.1:{port}/", f"http://localhost:{port}/"):
            with self.subTest(url=url):
                with urllib.request.urlopen(url, timeout=5) as response:
                    self.assertEqual(response.read(), b"loopback ok")
        self.assertEqual(self._new_attempts(), [])

    def test_the_ipv6_loopback_still_goes_through(self) -> None:
        try:
            port = self._serve(_IPv6Server, "::1")
        except OSError:
            self.skipTest("no IPv6 loopback on this host")
        with urllib.request.urlopen(f"http://[::1]:{port}/", timeout=5) as response:
            self.assertEqual(response.read(), b"loopback ok")
        self.assertEqual(self._new_attempts(), [])

    def test_the_update_check_stops_at_the_guard(self) -> None:
        """The call that was caught, with the update check's own defaults."""
        downstream = self._spy_downstream()
        # check_for_updates also sets the process-wide cached status; hand the
        # next test back the one it would have seen.
        self.addCleanup(update_check._set_cached_status, dict(update_check._cached_status))
        with tempfile.TemporaryDirectory() as tmp:
            result = update_check.check_for_updates(
                "0.0.1",
                tmp,
                env={update_check.ENV_STATE_PATH: os.path.join(tmp, "update-check.json")},
                timeout=1.0,
                force=True,
            )
        downstream.assert_not_called()
        self.assertEqual(result["status"], "error", result)
        self.assertIn("refused an outbound request", result["error"])

        [attempt] = self._new_attempts()
        self.assertEqual(attempt["url"], RELEASES_URL)
        self.assertTrue(
            attempt["caller"].startswith(os.path.join("src", "utils", "update_check.py") + ":"),
            attempt,
        )
        self.assertTrue(attempt["caller"].endswith("in _fetch_latest_release"), attempt)

    def test_the_installer_tests_do_not_ask_for_the_network(self) -> None:
        """`_run_main` is where the request was recorded, with `--clients manual`."""
        for clients in ("manual", ""):
            with self.subTest(clients=clients):
                code, out = discovery.SetupExitStatusTests._run_main(
                    clients=clients, healthy=False, verification=(False, "pinned: no probe")
                )
                self.assertEqual(code, 1, out)
        self.assertEqual(
            self._new_attempts(),
            [],
            "running install.py's main() in-process reached for the network again",
        )

    def test_installing_again_changes_nothing(self) -> None:
        guard = urllib.request.urlopen
        self.assertFalse(offline_guard.install())
        self.assertIs(urllib.request.urlopen, guard)
        self.assertFalse(
            getattr(guard.__wrapped__, offline_guard._NETWORK_FLAG, False),
            "the guard wraps another copy of itself",
        )

    def test_uninstall_puts_the_original_back(self) -> None:
        guard = urllib.request.urlopen
        self.addCleanup(offline_guard.install)
        # Only the network half: the Resolve swap stays for the rest of the run.
        with mock.patch.object(offline_guard, "_import_server", return_value=None):
            offline_guard.uninstall()
        self.assertIs(urllib.request.urlopen, guard.__wrapped__)
        self.assertFalse(offline_guard.network_guard_installed())


if __name__ == "__main__":
    unittest.main()
