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
        with open(T.TRANSPORT_STATE_PATH, "w") as fh:
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


if __name__ == "__main__":
    unittest.main()
