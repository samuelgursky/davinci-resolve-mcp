"""`get_version` reports what the connected build is MISSING, not just its number.

Issue #132: an assistant described a surface that was not on the reporter's
build. The session had every chance to know better — it starts with
`get_version` — but that call answered with a version number and nothing about
what the number rules out, so the knowledge existed and was never in the room.

No Resolve required; the handle is a stub.
"""

from __future__ import annotations

import unittest
from unittest import mock

from src import server
from src.utils.resolve_versions import VERSION_GATES


class FakeResolve:
    def __init__(self, version_string: str):
        self._version_string = version_string

    def GetProductName(self):
        return "DaVinci Resolve Studio"

    def GetVersion(self):
        return [int(part) for part in self._version_string.split(".")] + [""]

    def GetVersionString(self):
        return self._version_string


def _get_version(version_string: str):
    with mock.patch.object(server, "resolve", FakeResolve(version_string)), \
            mock.patch.object(server, "get_resolve", return_value=FakeResolve(version_string)):
        return server.resolve_control(action="get_version")


class GetVersionBuildBlockTest(unittest.TestCase):
    def test_an_old_build_is_told_what_it_cannot_do(self):
        result = _get_version("19.1.3.7")
        missing = {g["symbol"] for g in result["build"]["unavailable_on_this_build"]}
        # Both halves of the registry must reach the preflight: one measured
        # here, one carried up from a call-site guard by issue #132's fix.
        self.assertIn("Resolve.GetFairlightPresets", missing)
        self.assertIn("MediaPoolItem.RemoveMotionBlur", missing)
        self.assertIn("recorded surface", result["build"]["note"])

    def test_a_current_build_is_not_told_everything_exists(self):
        """The empty list is the dangerous one — it reads as a green light."""
        result = _get_version("21.0.4.5")
        self.assertEqual(result["build"]["unavailable_on_this_build"], [])
        note = result["build"]["note"]
        self.assertIn("not a promise", note)
        self.assertIn("check_version_support", note)

    def test_the_patch_level_split_survives_the_round_trip(self):
        """"Resolve 21" is not a usable label; 21.0.2 and 21.0.4 differ."""
        missing = {
            g["symbol"]
            for g in _get_version("21.0.2.4")["build"]["unavailable_on_this_build"]
        }
        self.assertIn("Resolve.GetLayoutPresetList", missing)
        self.assertNotIn("Resolve.GetFairlightPresets", missing)

    def test_the_version_fields_are_unchanged(self):
        """The block is additive; existing readers must not have to change."""
        result = _get_version("19.1.3.7")
        self.assertEqual(result["version_string"], "19.1.3.7")
        self.assertEqual(result["product"], "DaVinci Resolve Studio")
        self.assertIn("version", result["mcp"])
        self.assertEqual(result["build"]["known_gates"], len(VERSION_GATES))


if __name__ == "__main__":
    unittest.main()
