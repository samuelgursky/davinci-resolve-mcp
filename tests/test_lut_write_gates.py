"""LUT file writes are gated like the plugin-folder writes they sit beside.

`lut install`, `remove` and `attenuate` create, replace and delete files under
Resolve's master LUT root — the folder Resolve loads LUTs from. Following the
v3.0.0 precedent for dctl / fuse_plugin / script_plugin, every gate must see
them as writes: recognised and rated by the classifier, registered in the
destructive registry, exempt from timeline archiving because they never touch
the project, and blocked by safe mode when they delete.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from src.utils import destructive_hook, lut_files
from src.utils.execution_lifecycle import classify_operation_risk

LUT_WRITES = {
    ("lut", "install"): "medium",
    ("lut", "attenuate"): "medium",
    ("lut", "remove"): "high",
}
LUT_READS = ("path", "list", "read", "capabilities")


class _HookState(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_provider = destructive_hook._PROVIDER
        self.saved_pref_provider = destructive_hook._PREFERENCE_PROVIDER
        self.saved_pending_check = destructive_hook._PENDING_CONFIRM_CHECK
        self.tmp = tempfile.TemporaryDirectory()
        self.audit_path = os.path.join(self.tmp.name, "security-audit.jsonl")

    def tearDown(self) -> None:
        destructive_hook._PROVIDER = self.saved_provider
        destructive_hook._PREFERENCE_PROVIDER = self.saved_pref_provider
        destructive_hook._PENDING_CONFIRM_CHECK = self.saved_pending_check
        self.tmp.cleanup()

    def _prefs(self, *, safe_mode: bool = False) -> None:
        values = {
            "destructive.safe_mode": safe_mode,
            "destructive.audit_log": True,
            "destructive.audit_log_path": self.audit_path,
        }
        destructive_hook.register_preference_provider(values.get)

    def _audit_events(self):
        if not os.path.exists(self.audit_path):
            return []
        with open(self.audit_path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


class LutWritesAreRatedWritesTest(unittest.TestCase):
    def test_every_lut_write_is_recognised_destructive_and_rated(self) -> None:
        for (tool, action), level in LUT_WRITES.items():
            with self.subTest(action=action):
                self.assertTrue(destructive_hook.is_destructive(tool, action))
                risk = classify_operation_risk(tool, action, {})
                self.assertTrue(risk.recognised, risk)
                self.assertTrue(risk.destructive, risk)
                self.assertEqual(risk.level.value, level)

    def test_lut_reads_are_not_registered_as_writes(self) -> None:
        for action in LUT_READS:
            with self.subTest(action=action):
                self.assertFalse(destructive_hook.is_destructive("lut", action))
                self.assertFalse(classify_operation_risk("lut", action, {}).destructive)

    def test_lut_is_a_non_timeline_write_tool(self) -> None:
        self.assertIn("lut", destructive_hook.NON_TIMELINE_WRITE_TOOLS)


class LutWritesSkipTimelineArchivingTest(_HookState):
    def test_a_lut_write_neither_archives_nor_resolves_the_version_context(self) -> None:
        """Installing a LUT must not snapshot the open timeline, and must not
        reach Resolve to find a project root in the first place."""
        self._prefs()
        provider_calls: list = []
        destructive_hook.register_project_root_provider(lambda: provider_calls.append(1))
        for tool, action in LUT_WRITES:
            with self.subTest(action=action):
                @destructive_hook.destructive_op(tool)
                def handler(action, params=None):
                    return {"success": True}

                result = handler(action, {})
                self.assertTrue(result["success"], result)
                self.assertFalse(result["_versioning"]["archived"], result)
                self.assertEqual(result["_versioning"]["skipped_reason"],
                                 "not_a_timeline_mutation", result)
        self.assertEqual(provider_calls, [], "a LUT write reached the version provider")
        reasons = {event.get("reason") for event in self._audit_events()}
        self.assertIn("not_a_timeline_mutation", reasons, "LUT writes must still be audited")


class SafeModeTest(_HookState):
    def test_safe_mode_blocks_lut_removal_and_lets_installs_through(self) -> None:
        self._prefs(safe_mode=True)
        destructive_hook.register_project_root_provider(lambda: None)
        ran: list = []
        for (tool, action), level in LUT_WRITES.items():
            with self.subTest(action=action):
                @destructive_hook.destructive_op(tool)
                def handler(action, params=None, _key=(tool, action)):
                    ran.append(_key)
                    return {"success": True}

                result = handler(action, {})
                if level == "high":
                    self.assertNotIn((tool, action), ran, result)
                    self.assertFalse(result.get("success"), result)
                else:
                    self.assertIn((tool, action), ran, result)


class NativeDryRunIsHonestTest(_HookState):
    """`lut` honours dry_run itself and writes nothing, so its writes are listed
    in NATIVE_DRY_RUN_ACTIONS and must reach the handler rather than be refused."""

    def setUp(self) -> None:
        super().setUp()
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        patcher = patch.object(lut_files, "master_lut_dir", return_value=self.root.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _count(self) -> int:
        return lut_files.list_luts()["count"]

    def test_dry_runs_reach_the_handler_and_write_nothing(self) -> None:
        from src import server

        self._prefs()
        destructive_hook.register_project_root_provider(lambda: None)
        cube = "LUT_3D_SIZE 2\n" + "0 0 0\n" * 8
        cases = (
            ("install", {"name": "dry.cube", "source": cube}, "would_install"),
            ("remove", {"name": "dry.cube"}, "would_remove"),
            ("attenuate", {"source": "x.cube", "strength": 0.5, "name": "y.cube"}, "would_write"),
        )
        for action, params, key in cases:
            with self.subTest(action=action):
                result = server.lut(action, dict(params, dry_run=True))
                self.assertNotEqual(result.get("status"), "dry_run_unavailable", result)
                self.assertIn(key, result, result)
                self.assertEqual(self._count(), 0)


if __name__ == "__main__":
    unittest.main()
