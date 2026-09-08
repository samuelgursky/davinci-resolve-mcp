"""Tests for networked transport helpers + bearer-auth middleware."""
import os
import unittest

from src.utils import mcp_transport as T


class TokenTest(unittest.TestCase):
    def test_env_token_honored(self):
        os.environ["DAVINCI_MCP_TOKEN"] = "fixed-tok"
        try:
            tok, gen = T.resolve_token()
            self.assertEqual(tok, "fixed-tok")
            self.assertFalse(gen)
        finally:
            del os.environ["DAVINCI_MCP_TOKEN"]

    def test_generated_token(self):
        os.environ.pop("DAVINCI_MCP_TOKEN", None)
        tok, gen = T.resolve_token()
        self.assertTrue(gen)
        self.assertTrue(len(tok) >= 16)


class StateFileTest(unittest.TestCase):
    def tearDown(self):
        T.clear_transport_state()

    def test_roundtrip(self):
        T.write_transport_state("streamable-http", "127.0.0.1", 8765, "tok")
        st = T.read_transport_state()
        self.assertEqual(st["transport"], "streamable-http")
        self.assertEqual(st["port"], 8765)
        self.assertTrue(st["loopback"])
        self.assertEqual(st["url"], "http://127.0.0.1:8765")

    def test_stale_pid_treated_as_gone(self):
        import json
        with open(T.TRANSPORT_STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"pid": 2 ** 31 - 1, "transport": "sse"}, fh)  # nonexistent pid
        self.assertIsNone(T.read_transport_state())


class AuthMiddlewareTest(unittest.TestCase):
    def _client(self, token):
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        async def ok(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/", ok)])
        app.add_middleware(T._auth_middleware_cls(token))
        return TestClient(app)

    def test_rejects_missing_token(self):
        c = self._client("secret")
        self.assertEqual(c.get("/").status_code, 401)

    def test_rejects_wrong_token(self):
        c = self._client("secret")
        self.assertEqual(c.get("/", headers={"Authorization": "Bearer nope"}).status_code, 401)

    def test_accepts_correct_token(self):
        c = self._client("secret")
        r = c.get("/", headers={"Authorization": "Bearer secret"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "ok")


class GeneratedTokenNeverLoggedTest(unittest.TestCase):
    """The generated token is the transport's only access control.

    src/server.py configures the ROOT logger with a FileHandler on
    logs/server.log (default file mode, appended, never cleared), and the
    transport logger has no handler of its own, so anything it logs lands in
    that file. The token must therefore never pass through logging at all —
    only the 0600 state file (cleared at shutdown) and, when a person is
    watching, an interactive stderr.
    """

    class _FakeMCP:
        class settings:
            host = "127.0.0.1"
            port = 8123

        def sse_app(self):
            from starlette.applications import Starlette
            return Starlette()

        def streamable_http_app(self):
            return self.sse_app()

    def setUp(self):
        os.environ.pop("DAVINCI_MCP_TOKEN", None)

    def tearDown(self):
        T.clear_transport_state()

    def _run(self, stderr):
        """Run the real run_networked with uvicorn stubbed; return (token, log text)."""
        import io
        import logging
        import tempfile
        from unittest import mock

        captured = {}

        def fake_write(transport, host, port, token):
            captured["token"] = token
            return real_write(transport, host, port, token)

        real_write = T.write_transport_state
        root = logging.getLogger()
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "server.log")
            handler = logging.FileHandler(log_path)
            handler.setLevel(logging.DEBUG)
            root.addHandler(handler)
            previous = root.level
            root.setLevel(logging.DEBUG)
            try:
                with mock.patch("uvicorn.run"), \
                        mock.patch.object(T, "write_transport_state", fake_write), \
                        mock.patch("sys.stderr", stderr):
                    T.run_networked(self._FakeMCP(), "streamable-http")
            finally:
                root.setLevel(previous)
                root.removeHandler(handler)
                handler.close()
            with open(log_path, encoding="utf-8") as fh:
                log_text = fh.read()
        return captured["token"], log_text

    def test_token_absent_from_root_file_handler(self):
        import io

        class _Quiet(io.StringIO):
            def isatty(self):
                return False

        stderr = _Quiet()
        token, log_text = self._run(stderr)
        self.assertTrue(token)
        self.assertNotIn(token, log_text)
        self.assertIn(T.TRANSPORT_STATE_PATH, log_text)
        self.assertIn("DAVINCI_MCP_TOKEN", log_text)
        # Redirected stderr is a file too: no token there either.
        self.assertNotIn(token, stderr.getvalue())
        # The state file (0600, cleared at shutdown) was the copy that carried it.
        self.assertIsNone(T.read_transport_state())

    def test_token_echoed_once_to_interactive_stderr(self):
        import io

        class _Tty(io.StringIO):
            def isatty(self):
                return True

        stderr = _Tty()
        token, log_text = self._run(stderr)
        self.assertNotIn(token, log_text)
        self.assertEqual(stderr.getvalue().count(token), 1)

    def test_pinned_token_not_echoed_anywhere(self):
        import io

        class _Tty(io.StringIO):
            def isatty(self):
                return True

        os.environ["DAVINCI_MCP_TOKEN"] = "pinned-by-operator"
        try:
            stderr = _Tty()
            token, log_text = self._run(stderr)
        finally:
            del os.environ["DAVINCI_MCP_TOKEN"]
        self.assertEqual(token, "pinned-by-operator")
        self.assertNotIn(token, log_text)
        self.assertNotIn(token, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
