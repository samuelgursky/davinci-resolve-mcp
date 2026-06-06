"""Tests for dashboard transport status/start/stop helpers."""
import unittest

import src.analysis_dashboard as dash
from src.utils import mcp_transport as T


class DashboardTransportTest(unittest.TestCase):
    def tearDown(self):
        T.clear_transport_state()

    def test_status_local_when_no_state(self):
        T.clear_transport_state()
        st = dash._transport_status()
        self.assertFalse(st["networked"])
        self.assertIn("stdio", st["mode"])

    def test_status_networked_from_state(self):
        T.write_transport_state("streamable-http", "127.0.0.1", 8799, "tok")
        st = dash._transport_status()
        self.assertTrue(st["networked"])
        self.assertTrue(st["loopback"])
        self.assertEqual(st["url"], "http://127.0.0.1:8799")
        self.assertTrue(st["has_token"])

    def test_start_refuses_when_already_running(self):
        # Our own live pid keeps the state "alive", so start must refuse.
        import os
        T.write_transport_state("streamable-http", "127.0.0.1", 8799, "tok")
        # ensure the state pid is this (alive) process so read_transport_state keeps it
        import json
        with open(T.TRANSPORT_STATE_PATH, "w") as fh:
            json.dump({"transport": "streamable-http", "host": "127.0.0.1", "port": 8799,
                       "url": "http://127.0.0.1:8799", "token": "tok", "loopback": True,
                       "pid": os.getpid()}, fh)
        out = dash._transport_start()
        self.assertFalse(out["success"])
        self.assertIn("already running", out["error"])

    def test_stop_noop_when_not_running(self):
        T.clear_transport_state()
        out = dash._transport_stop()
        self.assertTrue(out["success"])


if __name__ == "__main__":
    unittest.main()
