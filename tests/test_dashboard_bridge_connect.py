"""The control panel must reach Resolve over the in-app bridge.

The panel is a separate process with its own connector, and that connector
bailed as soon as `import DaVinciResolveScript` failed. On the free edition
that import is exactly what fails — the module ships with the installer, not
the App Store build — so the panel reported "Resolve unavailable" while the
MCP server, which already carries this guard in `_try_connect`, connected over
the same healthy bridge (issue #109).
"""
import sys
import unittest
from unittest import mock

import src.analysis_dashboard as dash


class _ImportBlocker:
    """Make `import DaVinciResolveScript` fail, as it does on the free edition."""

    def find_module(self, name, path=None):  # pragma: no cover - legacy hook
        return None

    def find_spec(self, name, path=None, target=None):
        if name == "DaVinciResolveScript":
            raise ImportError("No module named 'DaVinciResolveScript'")
        return None


class DashboardBridgeConnectTest(unittest.TestCase):
    def setUp(self):
        self._blocker = _ImportBlocker()
        sys.meta_path.insert(0, self._blocker)
        sys.modules.pop("DaVinciResolveScript", None)
        # The env probe is cached per process; start each test from scratch.
        self._env_ready = dash._RESOLVE_ENV_READY
        dash._RESOLVE_ENV_READY = True

    def tearDown(self):
        sys.meta_path.remove(self._blocker)
        dash._RESOLVE_ENV_READY = self._env_ready

    def test_bridge_mode_connects_without_blackmagics_module(self):
        # Driven through the real env var rather than by patching the helper,
        # so this fails against the old connector for the right reason: it
        # returned "scripting API unavailable" with the bridge switched on.
        handle = object()
        with mock.patch.dict("os.environ", {"DAVINCI_RESOLVE_BRIDGE": "1"}), \
             mock.patch.object(dash, "connect_resolve", return_value=handle) as connect:
            resolve, error = dash._connect_resolve_read_only()
        self.assertIsNone(error)
        self.assertIs(resolve, handle)
        # connect_resolve accepts None in bridge mode — that is the whole point.
        connect.assert_called_once_with(None)

    def test_without_the_bridge_the_missing_module_is_still_an_error(self):
        with mock.patch.dict("os.environ", {"DAVINCI_RESOLVE_BRIDGE": "0"}), \
             mock.patch.object(dash, "connect_resolve") as connect:
            resolve, error = dash._connect_resolve_read_only()
        self.assertIsNone(resolve)
        self.assertIn("Resolve scripting API unavailable", error)
        connect.assert_not_called()

    def test_bridge_enabled_but_not_answering_names_the_bridge(self):
        with mock.patch.dict("os.environ", {"DAVINCI_RESOLVE_BRIDGE": "1"}), \
             mock.patch.object(dash, "connect_resolve", return_value=None):
            resolve, error = dash._connect_resolve_read_only()
        self.assertIsNone(resolve)
        self.assertIn("resolve_bridge", error)
        # Launching Resolve cannot start the listener, so it must not be advised.
        self.assertNotIn("Open Resolve Studio", error)

    def test_studio_message_does_not_assume_studio_only(self):
        message = dash._not_connected_message(False)
        self.assertIn("External scripting", message)
        self.assertIn("free edition", message)


if __name__ == "__main__":
    unittest.main()
