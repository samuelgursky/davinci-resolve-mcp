"""The control panel's request gate, exercised over real HTTP.

Reported privately (2026-08-18): the panel served /api/mcp/status — which
returns the networked-transport bearer token — to anyone who could reach the
port, checked neither Host nor Origin (DNS rebinding + CSRF), accepted POST
bodies of any Content-Type, and let the AI pick the bind address. Chained,
an ordinary web page could take over the whole MCP toolset.

These tests pin the fix: loopback-only Host, loopback-only Origin, JSON-only
POST, per-launch bearer token on every route except the static shell, and an
HttpOnly session cookie so <img> loads work. They boot a real
ThreadingHTTPServer on an ephemeral port; no Resolve, no browser.
"""
from __future__ import annotations

import http.client
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import src.analysis_dashboard as dash
from src import server as mcp_server
from src.utils import private_state


class _PanelServer:
    """Boot the real Handler on 127.0.0.1:0 with a stubbed state + fixed token."""

    def __init__(self, token: str = "test-token-123") -> None:
        self.token = token
        state = mock.MagicMock()
        state.project_name = "Demo"
        state.project_id = "demo"
        state.project_root = "/tmp/demo"
        state.output_root = {"base_root": "/tmp/demo"}
        state.context.return_value = {}
        state.related_project_roots.return_value = []
        state.projects.return_value = {"success": True, "projects": []}
        state.lock = threading.Lock()
        self._orig_state = getattr(dash.Handler, "state", None)
        self._orig_token = dash.Handler.token
        dash.Handler.state = state
        dash.Handler.token = token
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), dash.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        dash.Handler.token = self._orig_token
        if self._orig_state is not None:
            dash.Handler.state = self._orig_state

    def request(self, method: str, path: str, *, headers=None, body=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = {"Host": host if host is not None else f"127.0.0.1:{self.port}"}
        hdrs.update(headers or {})
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in hdrs.items():
            conn.putheader(k, v)
        data = body.encode("utf-8") if isinstance(body, str) else body
        if data is not None:
            conn.putheader("Content-Length", str(len(data)))
        conn.endheaders(data)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            payload = raw
        return resp.status, dict(resp.getheaders()), payload


class PanelGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = _PanelServer()
        cls.bearer = {"Authorization": f"Bearer {cls.panel.token}"}
        # /api/boot pulls in capability probes and Resolve identity; stub them
        # so the test never touches Resolve or the filesystem.
        cls._patches = [
            mock.patch.object(dash, "detect_capabilities", return_value={}),
            mock.patch.object(dash, "_resolve_identity", return_value={}),
            mock.patch.object(dash, "_mcp_status_payload",
                              return_value={"success": True, "transport": {"token": "TRANSPORT-SECRET"}}),
        ]
        for p in cls._patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()
        cls.panel.close()

    # ── static shell is public; the token itself never appears in it ──────
    def test_root_html_is_public_and_does_not_leak_token(self):
        status, _, body = self.panel.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertNotIn(self.panel.token.encode(), body)

    # ── the reported leak: transport token behind auth now ────────────────
    def test_mcp_status_requires_token(self):
        status, _, payload = self.panel.request("GET", "/api/mcp/status")
        self.assertEqual(status, 401)
        self.assertEqual(payload["panel"], "davinci-resolve-mcp")
        self.assertNotIn("TRANSPORT-SECRET", json.dumps(payload))

    def test_mcp_status_with_bearer(self):
        status, _, payload = self.panel.request("GET", "/api/mcp/status", headers=self.bearer)
        self.assertEqual(status, 200)
        self.assertEqual(payload["transport"]["token"], "TRANSPORT-SECRET")

    def test_boot_requires_token(self):
        status, _, _ = self.panel.request("GET", "/api/boot")
        self.assertEqual(status, 401)
        status, _, payload = self.panel.request("GET", "/api/boot", headers=self.bearer)
        self.assertEqual(status, 200)
        self.assertEqual(payload["project_name"], "Demo")

    def test_wrong_token_is_401(self):
        status, _, _ = self.panel.request(
            "GET", "/api/boot", headers={"Authorization": "Bearer nope"})
        self.assertEqual(status, 401)

    # ── DNS rebinding: Host header must be loopback ────────────────────────
    def test_non_loopback_host_header_rejected_even_with_token(self):
        for host in ("evil.example:1234", "10.0.0.5:8765", "", "attacker.local"):
            with self.subTest(host=host):
                status, _, payload = self.panel.request(
                    "GET", "/api/boot", headers=self.bearer, host=host)
                self.assertEqual(status, 403)
                self.assertIn("Host", payload["error"])

    def test_loopback_host_variants_accepted(self):
        for host in (f"localhost:{self.panel.port}", f"[::1]:{self.panel.port}", "127.0.0.1"):
            with self.subTest(host=host):
                status, _, _ = self.panel.request("GET", "/api/boot", headers=self.bearer, host=host)
                self.assertEqual(status, 200)

    # ── CSRF: cross-site Origin rejected; JSON content-type required ───────
    def test_cross_site_origin_rejected(self):
        status, _, payload = self.panel.request(
            "POST", "/api/panel_state",
            headers={**self.bearer, "Origin": "https://evil.example",
                     "Content-Type": "application/json"},
            body="{}")
        self.assertEqual(status, 403)
        self.assertIn("origin", payload["error"].lower())

    def test_loopback_origin_accepted(self):
        status, _, _ = self.panel.request(
            "POST", "/api/session",
            headers={**self.bearer, "Origin": f"http://127.0.0.1:{self.panel.port}",
                     "Content-Type": "application/json"},
            body="{}")
        self.assertEqual(status, 200)

    def test_post_without_json_content_type_rejected(self):
        # A cross-site <form> can only send urlencoded/multipart/text-plain.
        status, _, _ = self.panel.request(
            "POST", "/api/session",
            headers={**self.bearer, "Content-Type": "text/plain"},
            body="{}")
        self.assertEqual(status, 415)
        status, _, _ = self.panel.request(
            "POST", "/api/session", headers=self.bearer, body="{}")
        self.assertEqual(status, 415)

    def test_no_cors_preflight_answer(self):
        # A cross-site fetch with a JSON content-type needs a preflight; the
        # panel never answers one, so the browser blocks the real request.
        status, headers, _ = self.panel.request(
            "OPTIONS", "/api/session",
            headers={"Origin": "https://evil.example",
                     "Access-Control-Request-Method": "POST"})
        self.assertNotEqual(status, 200)
        self.assertNotIn("access-control-allow-origin", {k.lower() for k in headers})

    # ── session cookie: set only via bearer; then accepted on its own ──────
    def test_session_cookie_flow(self):
        status, headers, _ = self.panel.request(
            "POST", "/api/session",
            headers={**self.bearer, "Content-Type": "application/json"}, body="{}")
        self.assertEqual(status, 200)
        cookie = headers.get("Set-Cookie") or headers.get("set-cookie")
        self.assertIsNotNone(cookie)
        self.assertIn(f"{dash.PANEL_COOKIE_NAME}={self.panel.token}", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        # <img> loads carry only the cookie — that must be enough.
        status, _, payload = self.panel.request(
            "GET", "/api/boot", headers={"Cookie": f"{dash.PANEL_COOKIE_NAME}={self.panel.token}"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["project_name"], "Demo")

    def test_session_cookie_not_issued_without_bearer(self):
        status, headers, _ = self.panel.request(
            "POST", "/api/session", headers={"Content-Type": "application/json"}, body="{}")
        self.assertEqual(status, 401)
        self.assertNotIn("set-cookie", {k.lower() for k in headers})

    def test_wrong_cookie_is_401(self):
        status, _, _ = self.panel.request(
            "GET", "/api/boot", headers={"Cookie": f"{dash.PANEL_COOKIE_NAME}=nope"})
        self.assertEqual(status, 401)


class GateHelpersTest(unittest.TestCase):
    def test_host_header_parsing(self):
        self.assertTrue(dash._host_is_loopback("127.0.0.1:8765"))
        self.assertTrue(dash._host_is_loopback("LOCALHOST"))
        self.assertTrue(dash._host_is_loopback("[::1]:8765"))
        self.assertFalse(dash._host_is_loopback("127.0.0.1.evil.com"))
        self.assertFalse(dash._host_is_loopback("localhost.evil.com:80"))
        self.assertFalse(dash._host_is_loopback(None))

    def test_origin_parsing(self):
        self.assertTrue(dash._origin_is_loopback("http://127.0.0.1:8765"))
        self.assertTrue(dash._origin_is_loopback("http://localhost"))
        self.assertTrue(dash._origin_is_loopback("http://[::1]:8765"))
        self.assertFalse(dash._origin_is_loopback("null"))
        self.assertFalse(dash._origin_is_loopback("https://evil.example"))
        self.assertFalse(dash._origin_is_loopback("file://"))
        self.assertFalse(dash._origin_is_loopback("http://127.0.0.1.evil.com"))

    def test_token_from_env_or_generated(self):
        with mock.patch.dict(os.environ, {dash.PANEL_TOKEN_ENV: "pinned"}):
            self.assertEqual(dash.resolve_panel_token(), "pinned")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(dash.PANEL_TOKEN_ENV, None)
            tok = dash.resolve_panel_token()
            self.assertGreaterEqual(len(tok), 32)

    def test_argparse_refuses_non_loopback_host(self):
        import contextlib
        import io
        with mock.patch.object(sys, "argv", ["dash", "--host", "0.0.0.0"]), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                dash.parse_args()
        with mock.patch.object(sys, "argv", ["dash", "--host", "127.0.0.1"]):
            self.assertEqual(dash.parse_args().host, "127.0.0.1")

    def test_launch_url_puts_token_in_fragment_not_query(self):
        # The JS reads #token=…; a ?token=… would land in server logs.
        src = dash.HTML
        self.assertIn("window.location.hash.match(/^#token=", src)
        self.assertIn("'Authorization'", src.replace("Authorization:", "'Authorization'"))


class ProbeRecognises401Test(unittest.TestCase):
    """The launcher must still recognise a live panel it has no token for."""

    def test_401_with_panel_marker_is_dashboard(self):
        import urllib.error
        body = json.dumps({"success": False, "panel": "davinci-resolve-mcp",
                           "mcp_version": "2.97.4"}).encode()
        err = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)
        err.read = lambda: body  # type: ignore[assignment]
        with mock.patch("urllib.request.urlopen", side_effect=err):
            result = mcp_server._control_panel_probe("127.0.0.1", 8765)
        self.assertEqual(result, {"is_dashboard": True, "version": "2.97.4"})

    def test_401_from_other_server_is_not_dashboard(self):
        import urllib.error
        err = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)
        err.read = lambda: b'{"error": "nope"}'  # type: ignore[assignment]
        with mock.patch("urllib.request.urlopen", side_effect=err):
            result = mcp_server._control_panel_probe("127.0.0.1", 8765)
        self.assertEqual(result, {"is_dashboard": False, "version": None})

    def test_probe_sends_bearer_when_token_known(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["auth"] = req.get_header("Authorization")
            raise OSError("stop here")

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            mcp_server._control_panel_probe("127.0.0.1", 8765, token="abc")
        self.assertEqual(captured["auth"], "Bearer abc")


class PrivateStateTest(unittest.TestCase):
    def test_private_json_is_0600_and_not_in_tempdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"DAVINCI_RESOLVE_MCP_STATE_DIR": tmp}):
                d = private_state.private_state_dir()
                self.assertEqual(d, tmp)
                path = os.path.join(d, "x.json")
                # Pre-existing world-readable file must not survive.
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("old")
                os.chmod(path, 0o644)
                private_state.write_private_json(path, {"token": "s"})
                with open(path, encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["token"], "s")
                if sys.platform != "win32":
                    self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_transport_state_path_is_private(self):
        from src.utils import mcp_transport as T
        self.assertNotIn(tempfile.gettempdir(), T.TRANSPORT_STATE_PATH)
        self.assertTrue(T.TRANSPORT_STATE_PATH.endswith("mcp_transport.json"))

    def test_control_panel_pidfile_is_private(self):
        path = mcp_server._control_panel_pidfile()
        self.assertNotIn("Documents", path)
        self.assertTrue(path.endswith("control_panel.json"))


if __name__ == "__main__":
    unittest.main()
