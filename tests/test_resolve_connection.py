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


if __name__ == "__main__":
    unittest.main()
