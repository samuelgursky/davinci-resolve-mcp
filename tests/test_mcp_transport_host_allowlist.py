"""A non-loopback bind must be reachable at its own address (issue #241).

`src/server.py` builds `FastMCP(...)` without a host, so the SDK auto-enables
DNS-rebinding protection pinned to loopback. `run_networked` then moved
`settings.host` to the LAN address but left `settings.transport_security`
alone, so the streamable-http app answered every request to that address with
HTTP 421 — after the bearer check, so a wrong token still got 401 and the bind
looked healthy. Reproduced on v4.7.3 with the real SDK app before the fix.
"""
import os
import unittest
from unittest import mock

from src.utils import mcp_transport as T

INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "c", "version": "0"}},
}
ACCEPT = "application/json, text/event-stream"


class AllowlistPolicyTests(unittest.TestCase):
    def test_loopback_bind_leaves_the_sdk_default_alone(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            with self.subTest(host=host):
                self.assertIsNone(T.transport_security_for(host))

    def test_lan_bind_allows_its_own_host_and_loopback_with_protection_on(self):
        sec = T.transport_security_for("192.168.1.50")
        self.assertTrue(sec.enable_dns_rebinding_protection)
        self.assertIn("192.168.1.50:*", sec.allowed_hosts)
        for name in ("127.0.0.1:*", "localhost:*", "[::1]:*"):
            self.assertIn(name, sec.allowed_hosts)
        self.assertIn("http://192.168.1.50:*", sec.allowed_origins)

    def test_extra_names_join_the_allowlist(self):
        sec = T.transport_security_for("192.168.1.50", ["studio-mac.local", "studio"])
        self.assertIn("studio-mac.local:*", sec.allowed_hosts)
        self.assertIn("studio:*", sec.allowed_hosts)
        self.assertIn("http://studio:*", sec.allowed_origins)

    def test_ipv6_bind_is_bracketed(self):
        sec = T.transport_security_for("fd00::5")
        self.assertIn("[fd00::5]:*", sec.allowed_hosts)

    def test_wildcard_bind_without_names_turns_protection_off(self):
        sec = T.transport_security_for("0.0.0.0")
        self.assertFalse(sec.enable_dns_rebinding_protection)
        self.assertEqual(sec.allowed_hosts, [])

    def test_wildcard_bind_with_names_keeps_protection_on(self):
        sec = T.transport_security_for("0.0.0.0", ["studio.lan"])
        self.assertTrue(sec.enable_dns_rebinding_protection)
        self.assertIn("studio.lan:*", sec.allowed_hosts)
        self.assertNotIn("0.0.0.0:*", sec.allowed_hosts)

    def test_env_list_is_split_stripped_and_deduped(self):
        env = {T.ALLOWED_HOSTS_ENV: " a.lan, b.lan ,a.lan,, "}
        self.assertEqual(T.extra_allowed_hosts(env), ["a.lan", "b.lan"])
        self.assertEqual(T.extra_allowed_hosts({}), [])


class RealAppTests(unittest.TestCase):
    """Drive the real FastMCP streamable-http app through run_networked."""

    def setUp(self):
        self._env = {k: os.environ.get(k) for k in
                     ("DAVINCI_MCP_HOST", "DAVINCI_MCP_PORT", "DAVINCI_MCP_TOKEN",
                      T.ALLOWED_HOSTS_ENV)}
        os.environ["DAVINCI_MCP_TOKEN"] = "secret"
        os.environ["DAVINCI_MCP_PORT"] = "8000"
        os.environ.pop(T.ALLOWED_HOSTS_ENV, None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        T.clear_transport_state()

    def _app_for(self, host):
        from mcp.server.fastmcp import FastMCP
        mcp = FastMCP("allowlist-test")  # no host, exactly like src/server.py
        os.environ["DAVINCI_MCP_HOST"] = host
        built = {}
        real = mcp.streamable_http_app

        def capture():
            built["app"] = real()
            return built["app"]

        with mock.patch("uvicorn.run"), \
                mock.patch.object(mcp, "streamable_http_app", capture):
            T.run_networked(mcp, "streamable-http")
        return mcp, built["app"]

    @staticmethod
    def _post(client, host_header, token="secret"):
        return client.post("/mcp", json=INIT, headers={
            "Authorization": f"Bearer {token}", "Accept": ACCEPT, "Host": host_header,
        })

    def test_lan_bind_serves_initialize_at_its_own_address(self):
        from starlette.testclient import TestClient
        mcp, app = self._app_for("192.168.1.50")
        self.assertIn("192.168.1.50:*", mcp.settings.transport_security.allowed_hosts)
        with TestClient(app) as c:
            self.assertEqual(self._post(c, "192.168.1.50:8000").status_code, 200)
            # The bearer check still runs first, and loopback still works.
            self.assertEqual(self._post(c, "192.168.1.50:8000", token="wrong").status_code, 401)
            self.assertEqual(self._post(c, "127.0.0.1:8000").status_code, 200)
            # DNS-rebinding protection is still on: a foreign Host is refused.
            self.assertEqual(self._post(c, "evil.example:8000").status_code, 421)

    def test_loopback_bind_is_unchanged(self):
        from starlette.testclient import TestClient
        mcp, app = self._app_for("127.0.0.1")
        self.assertEqual(mcp.settings.transport_security.allowed_hosts,
                         ["127.0.0.1:*", "localhost:*", "[::1]:*"])
        with TestClient(app) as c:
            self.assertEqual(self._post(c, "127.0.0.1:8000").status_code, 200)
            self.assertEqual(self._post(c, "192.168.1.50:8000").status_code, 421)


if __name__ == "__main__":
    unittest.main()
