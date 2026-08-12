import os
import unittest
from unittest.mock import Mock, patch

from src.utils.resolve_connection import connect_resolve


class ResolveConnectionTests(unittest.TestCase):
    def test_uses_default_discovery_without_host(self):
        dvr_script = Mock()

        with patch.dict(os.environ, {}, clear=True):
            connect_resolve(dvr_script)

        dvr_script.scriptapp.assert_called_once_with("Resolve")

    def test_uses_explicit_host_with_bounded_timeout(self):
        dvr_script = Mock()

        with patch.dict(
            os.environ,
            {"RESOLVE_SCRIPT_HOST": "127.0.0.1"},
            clear=True,
        ):
            connect_resolve(dvr_script)

        dvr_script.scriptapp.assert_called_once_with("Resolve", "127.0.0.1", 5.0)

    def test_uses_configured_network_timeout(self):
        dvr_script = Mock()

        with patch.dict(
            os.environ,
            {
                "RESOLVE_SCRIPT_HOST": "resolve.example.test",
                "RESOLVE_SCRIPT_TIMEOUT": "12.5",
            },
            clear=True,
        ):
            connect_resolve(dvr_script)

        dvr_script.scriptapp.assert_called_once_with(
            "Resolve",
            "resolve.example.test",
            12.5,
        )

    def test_rejects_invalid_network_timeout(self):
        for value in ("forever", "0", "-1", "nan", "inf"):
            with self.subTest(value=value):
                dvr_script = Mock()
                with patch.dict(
                    os.environ,
                    {
                        "RESOLVE_SCRIPT_HOST": "resolve.example.test",
                        "RESOLVE_SCRIPT_TIMEOUT": value,
                    },
                    clear=True,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "RESOLVE_SCRIPT_TIMEOUT must be a positive finite number",
                    ):
                        connect_resolve(dvr_script)

                dvr_script.scriptapp.assert_not_called()


class BridgeFallbackTests(unittest.TestCase):
    """The bridge is used automatically once a direct transport has failed.

    The free edition refuses external scripting outright, so `scriptapp` returns
    None there. Before this fallback that was the end of the road unless the user
    had already set DAVINCI_RESOLVE_BRIDGE=1 — a chicken-and-egg the error message
    had to explain. The env var now only *forces* the bridge.
    """

    def _bridge(self, **kwargs):
        bridge = Mock()
        bridge.ENV_ENABLE = "DAVINCI_RESOLVE_BRIDGE"
        bridge.BridgeUnavailable = _FakeBridgeUnavailable
        bridge.bridge_enabled.return_value = False
        bridge.configure_mock(**kwargs)
        return bridge

    def test_falls_back_to_bridge_when_scriptapp_returns_none(self):
        dvr_script = Mock()
        dvr_script.scriptapp.return_value = None
        proxy = object()
        bridge = self._bridge()
        bridge.connect.return_value = proxy

        with patch.dict(os.environ, {}, clear=True):
            with patch("src.utils.resolve_connection.bridge_client", bridge):
                self.assertIs(connect_resolve(dvr_script), proxy)

        # require_enabled=False is what makes this work without the env var.
        bridge.connect.assert_called_once_with(require_enabled=False)

    def test_falls_back_when_the_blackmagic_module_is_absent(self):
        # The bridge needs no Blackmagic module, so a missing module is a reason
        # to try it rather than to give up.
        proxy = object()
        bridge = self._bridge()
        bridge.connect.return_value = proxy

        with patch.dict(os.environ, {}, clear=True):
            with patch("src.utils.resolve_connection.bridge_client", bridge):
                self.assertIs(connect_resolve(None), proxy)

    def test_returns_none_when_neither_transport_answers(self):
        dvr_script = Mock()
        dvr_script.scriptapp.return_value = None
        bridge = self._bridge()
        bridge.connect.side_effect = _FakeBridgeUnavailable("no bridge")

        with patch.dict(os.environ, {}, clear=True):
            with patch("src.utils.resolve_connection.bridge_client", bridge):
                self.assertIsNone(connect_resolve(dvr_script))

    def test_working_direct_transport_never_touches_the_bridge(self):
        # The Studio path must not pay for a bridge probe.
        dvr_script = Mock()
        handle = object()
        dvr_script.scriptapp.return_value = handle
        bridge = self._bridge()

        with patch.dict(os.environ, {}, clear=True):
            with patch("src.utils.resolve_connection.bridge_client", bridge):
                self.assertIs(connect_resolve(dvr_script), handle)

        bridge.connect.assert_not_called()

    def test_forced_bridge_still_fails_loudly_without_falling_through(self):
        # The whole point of the env var: a bridge the user explicitly required
        # must report its own fault, not silently degrade to another transport.
        dvr_script = Mock()
        bridge = self._bridge()
        bridge.bridge_enabled.return_value = True
        bridge.connect.side_effect = _FakeBridgeUnavailable("bridge is down")

        with patch.dict(os.environ, {"DAVINCI_RESOLVE_BRIDGE": "1"}, clear=True):
            with patch("src.utils.resolve_connection.bridge_client", bridge):
                with self.assertRaisesRegex(_FakeBridgeUnavailable, "bridge is down"):
                    connect_resolve(dvr_script)

        dvr_script.scriptapp.assert_not_called()

    def test_no_bridge_module_installed_is_not_an_error(self):
        dvr_script = Mock()
        dvr_script.scriptapp.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            with patch("src.utils.resolve_connection.bridge_client", None):
                self.assertIsNone(connect_resolve(dvr_script))


class BridgeMessagingDriftTests(unittest.TestCase):
    """User-facing text must not contradict `connect_resolve`.

    When the fallback was added, four surfaces still described the env var as
    required — `scripts/doctor.py` went as far as "the bridge is installed but
    will not be used", the exact opposite of the behaviour, in the one tool
    people run *because* they are confused. Prose drifts from behaviour silently;
    this fails the build instead.
    """

    #: Every surface that explains the variable to a human.
    SURFACES = (
        "scripts/doctor.py",
        "scripts/resolve_bridge_launcher.py",
        "install.py",
        "src/server.py",
        "src/analysis_dashboard.py",
        "src/utils/resolve_bridge_client.py",
        "README.md",
        "docs/SKILL.md",
    )

    #: Phrasings that assert the bridge is unusable without the env var.
    CONTRADICTIONS = (
        "will not be used",
        "connects with DAVINCI_RESOLVE_BRIDGE=1",
        "and set DAVINCI_RESOLVE_BRIDGE=1",
        "set DAVINCI_RESOLVE_BRIDGE=1 to use it",
    )

    def _repo_root(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_no_surface_claims_the_variable_is_required(self):
        root = self._repo_root()
        for rel in self.SURFACES:
            path = os.path.join(root, rel)
            if not os.path.exists(path):  # pragma: no cover - layout guard
                continue
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            for phrase in self.CONTRADICTIONS:
                with self.subTest(surface=rel, phrase=phrase):
                    self.assertNotIn(
                        phrase, text,
                        f"{rel} tells the reader the bridge needs "
                        f"DAVINCI_RESOLVE_BRIDGE, but connect_resolve falls back to "
                        f"it automatically. Update the text or the connector.",
                    )

    def test_surfaces_that_name_the_variable_explain_it_forces(self):
        # Naming the variable without saying what it does is how the previous
        # wording survived: technically true, read as "required".
        root = self._repo_root()
        for rel in self.SURFACES:
            path = os.path.join(root, rel)
            if not os.path.exists(path):  # pragma: no cover - layout guard
                continue
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            if "DAVINCI_RESOLVE_BRIDGE" not in text:
                continue
            with self.subTest(surface=rel):
                self.assertRegex(
                    text, r"(?i)\b(force|forces|forcing|only transport)\b",
                    f"{rel} mentions DAVINCI_RESOLVE_BRIDGE without saying it FORCES "
                    f"the bridge; readers default to assuming it is required.",
                )


class _FakeBridgeUnavailable(RuntimeError):
    """Stands in for resolve_bridge_client.BridgeUnavailable."""


if __name__ == "__main__":
    unittest.main()
