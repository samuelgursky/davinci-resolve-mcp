"""Plugin-folder writes are gated like every other write.

`dctl`, `fuse_plugin` and `script_plugin` install, replace and delete files that
Resolve and Fusion later load and run: a Fuse registers on the next restart, a
Resolve-page script runs when clicked. Until these tests existed none of those
actions was in either write table. The classifier returned recognised=False, the
destructive registry had no entry, and `fuse_plugin` / `script_plugin` carried no
`@_destructive_op` at all. So every gate — safe mode, dry-run refusal, the audit
log — read them as reads, and a dry run of `install` wrote the file for real.
"""

from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

from src.utils import destructive_hook
from src.utils.execution_lifecycle import classify_operation_risk

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Installs are MEDIUM: audited and dry-run-honest, but not blocked by safe mode,
#: like the other create-style writes. Deletes are HIGH, matching the `remove_*`
#: prefix rule that the bare `remove` these tools use never matched.
PLUGIN_WRITES = {
    ("dctl", "install"): "medium",
    ("fuse_plugin", "install"): "medium",
    ("script_plugin", "install"): "medium",
    ("script_plugin", "safe_install_extension"): "medium",
    ("dctl", "remove"): "high",
    ("fuse_plugin", "remove"): "high",
    ("script_plugin", "remove"): "high",
    ("script_plugin", "safe_remove_extension"): "high",
    ("dctl", "encrypt_native"): "low",
}


class _HookState(unittest.TestCase):
    """Isolates the hook's module globals and routes the audit log to a temp file."""

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


class PluginWritesAreRatedWritesTest(unittest.TestCase):
    def test_every_plugin_write_is_recognised_destructive_and_rated(self) -> None:
        for (tool, action), level in PLUGIN_WRITES.items():
            with self.subTest(tool=tool, action=action):
                self.assertTrue(destructive_hook.is_destructive(tool, action))
                risk = classify_operation_risk(tool, action, {})
                self.assertTrue(risk.recognised, risk)
                self.assertTrue(risk.destructive, risk)
                self.assertEqual(risk.level.value, level)


class DryRunIsRefusedNotExecutedTest(_HookState):
    def test_a_dry_run_install_or_remove_is_refused_before_the_handler(self) -> None:
        """Before the fix, `dry_run=true` on these was ignored and the file was
        written or deleted anyway — a dry run that executes is worse than none,
        because it is trusted."""
        from src import server

        self._prefs()
        destructive_hook.register_project_root_provider(lambda: None)
        tools = (
            (server.dctl, {"name": "GateProbe", "source": "__DEVICE__ float3 x"}),
            (server.fuse_plugin, {"name": "GateProbe", "source": "-- probe"}),
            (server.script_plugin, {"name": "GateProbe", "source": "print(1)",
                                    "category": "Utility"}),
        )
        for tool, params in tools:
            for action in ("install", "remove"):
                with self.subTest(tool=tool.__name__, action=action):
                    result = tool(action, dict(params, dry_run=True))
                    self.assertEqual(result.get("status"), "dry_run_unavailable", result)
                    self.assertFalse(result.get("executed"), result)

    def test_the_safe_install_dry_run_still_reaches_its_own_handler(self) -> None:
        """`safe_install_extension` honours dry_run itself, so it is listed in
        NATIVE_DRY_RUN_ACTIONS; registering it must not start refusing it."""
        from src import server

        self._prefs()
        destructive_hook.register_project_root_provider(lambda: None)
        result = server.script_plugin("safe_install_extension", {
            "extension_type": "fuse", "name": "_mcp_gate_probe", "source": "-- @mcp-fuse\n-- probe",
            "dry_run": True,
        })
        self.assertNotEqual(result.get("status"), "dry_run_unavailable", result)
        self.assertTrue(result.get("would_install"), result)


class PluginWritesSkipTimelineArchivingTest(_HookState):
    def test_a_plugin_write_neither_archives_nor_resolves_the_version_context(self) -> None:
        """Installing a shader must not snapshot the open timeline, and must not
        reach Resolve to find a project root in the first place. `encrypt_native`
        was already registered and did both on every call until this fix."""
        self._prefs()
        provider_calls: list = []
        destructive_hook.register_project_root_provider(lambda: provider_calls.append(1))
        for tool, action in PLUGIN_WRITES:
            with self.subTest(tool=tool, action=action):
                @destructive_hook.destructive_op(tool)
                def handler(action, params=None):
                    return {"success": True}

                result = handler(action, {})
                self.assertTrue(result["success"], result)
                self.assertFalse(result["_versioning"]["archived"], result)
                self.assertEqual(
                    result["_versioning"]["skipped_reason"], "not_a_timeline_mutation", result
                )
        self.assertEqual(provider_calls, [], "a plugin write reached the version provider")
        reasons = {event.get("reason") for event in self._audit_events()}
        self.assertIn("not_a_timeline_mutation", reasons, "plugin writes must still be audited")


class SafeModeTest(_HookState):
    def test_safe_mode_blocks_plugin_deletes_and_lets_installs_through(self) -> None:
        self._prefs(safe_mode=True)
        destructive_hook.register_project_root_provider(lambda: None)
        ran: list = []
        for (tool, action), level in PLUGIN_WRITES.items():
            with self.subTest(tool=tool, action=action):
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


class ProbesGoThroughTheGateTest(unittest.TestCase):
    def test_only_the_dispatcher_calls_the_raw_safe_helpers(self) -> None:
        """The lifecycle probes install, execute and clean up. They used to call
        `_safe_install_extension` / `_safe_remove_extension` directly, and the
        remove helper unlinks the file itself, so their deletes reached disk
        without passing any gate. Every caller other than the `script_plugin`
        dispatcher must go through `script_plugin(...)`, whose decorator reads
        the registry."""
        tree = ast.parse((REPO_ROOT / "src" / "server.py").read_text(encoding="utf-8"))
        callers: dict = {}
        for fn in tree.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                name = getattr(getattr(node, "func", None), "id", None)
                if isinstance(node, ast.Call) and name in (
                    "_safe_install_extension", "_safe_remove_extension",
                ):
                    callers.setdefault(name, set()).add(fn.name)
        self.assertEqual(callers, {
            "_safe_install_extension": {"script_plugin"},
            "_safe_remove_extension": {"script_plugin"},
        })


if __name__ == "__main__":
    unittest.main()
