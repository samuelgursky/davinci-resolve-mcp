"""Issue #327: the bridge client reuses one connection instead of one per call.

A new TCP connection per proxied call cost a handshake and a TIME_WAIT socket
each time: 20-30x slower than direct scripting on Windows, and a read-only
suite left ~1,200 sockets in TIME_WAIT, enough at sustained load to exhaust a
narrow ephemeral port range. Each request is still signed with its own nonce;
only the TCP connection is shared.
"""

from __future__ import annotations

import socket
import tempfile
import time
import unittest
from unittest import mock

from src.utils import resolve_bridge as rb
from src.utils import resolve_bridge_client as rbc
from src.utils import resolve_bridge_ops as rbo
from tests.test_resolve_bridge import TOKEN, FakeResolve


class KeepAliveTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.mkdtemp(prefix="keepalive_")
        fake = FakeResolve()
        ops = rbo.ResolveOperations(fake, media_roots=[root], output_roots=[root])
        config = {"host": "127.0.0.1", "port": 0, "token": TOKEN, "auth_clock_skew_seconds": 60}
        self.bridge = rb.Bridge(fake, config, rbo.make_dispatch(ops)).start()
        self.addCleanup(self.bridge.stop)
        self.transport = rbc.BridgeTransport({**config, "port": self.bridge.port}, timeout=5.0)
        self.addCleanup(self.transport.close)
        real = socket.create_connection
        self.connects = []

        def counting(*args, **kwargs):
            self.connects.append(args)
            return real(*args, **kwargs)

        patcher = mock.patch("socket.create_connection", side_effect=counting)
        patcher.start()
        self.addCleanup(patcher.stop)

    def health(self):
        return self.transport.request("health", {})

    def test_consecutive_requests_share_one_connection(self):
        for _ in range(5):
            self.assertTrue(self.health()["connected"])
        self.assertEqual(len(self.connects), 1)

    def test_an_idle_connection_is_retired_before_the_bridge_would_close_it(self):
        self.health()
        self.transport._idle_since = time.monotonic() - rbc.KEEPALIVE_REUSE_S - 1
        self.health()
        self.assertEqual(len(self.connects), 2)
        self.assertLess(rbc.KEEPALIVE_REUSE_S, rb.KEEPALIVE_IDLE_S)

    def test_a_connection_the_bridge_closed_is_replaced_transparently(self):
        self.health()
        self.bridge._close_connections()
        time.sleep(0.05)
        self.assertTrue(self.health()["connected"])
        self.assertEqual(len(self.connects), 2)

    def test_a_bridge_without_keep_alive_gets_one_connection_per_call(self):
        # A bridge that is stopping (as an older bridge always does) never
        # sends keep_alive, and the client must not reuse the socket.
        self.bridge._stop_mode = "exit"
        self.health()
        self.health()
        self.assertEqual(len(self.connects), 2)

    def test_an_unauthenticated_request_closes_the_connection(self):
        bad = rbc.BridgeTransport(
            {"host": "127.0.0.1", "port": self.bridge.port, "token": "x" * 48, "auth_clock_skew_seconds": 60},
            timeout=5.0,
        )
        self.addCleanup(bad.close)
        with self.assertRaises(rbc.BridgeCallError):
            bad.request("health", {})
        self.assertIsNone(bad._sock)

    def test_drain_does_not_wait_on_an_idle_kept_alive_connection(self):
        self.health()
        started = time.monotonic()
        self.assertTrue(self.bridge._drain(2.0))
        self.assertLess(time.monotonic() - started, 0.5)

    def test_stop_releases_kept_alive_connections(self):
        self.health()
        self.bridge.stop()
        with self.assertRaises(rbc.BridgeUnavailable):
            self.health()


if __name__ == "__main__":
    unittest.main()
