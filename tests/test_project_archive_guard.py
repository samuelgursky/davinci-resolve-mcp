"""Project archive is gated, rated, and never sends a crashing default.

`ProjectManager.ArchiveProject` on Studio 21.1.0.14 either returns False and
writes nothing (source media and proxies off) or crashes Resolve (either on).
The native defaults turn source media on, and both wrappers here inherited
them, so a default call crashed Resolve. Measurements are in
src/utils/archive_guard.py and the api_truth entry.
"""
import unittest
from unittest.mock import patch

import src.server as compound
from src.granular import project as granular
from src.utils import archive_guard, destructive_hook
from src.utils.api_truth import ACTION_SYMBOLS, API_TRUTH, traps_for
from src.utils.execution_lifecycle import classify_operation_risk

ACTIONS = ("archive", "safe_project_archive")


class NativeSpy:
    def __init__(self, returns=False):
        self.calls = []
        self._returns = returns

    def GetProjectManager(self):
        return self

    def ArchiveProject(self, *args):
        self.calls.append(args)
        return self._returns


class GuardTests(unittest.TestCase):
    def test_every_flag_defaults_off(self):
        flags, err = archive_guard.read_flags({})
        self.assertIsNone(err)
        self.assertEqual(flags, {"src_media": False, "render_cache": False, "proxy_media": False})

    def test_non_boolean_flags_are_refused_not_coerced(self):
        for bad in ("false", "true", 1, 0, None, "yes"):
            with self.subTest(bad=bad):
                flags, err = archive_guard.read_flags({"src_media": bad})
                self.assertIsNone(flags)
                self.assertIn("true or false", err)

    def test_only_the_two_crashing_flags_are_refused(self):
        self.assertIsNone(archive_guard.crash_refusal("t", "a", {"render_cache": True}))
        for flag in archive_guard.CRASH_FLAGS:
            with self.subTest(flag=flag):
                refused = archive_guard.crash_refusal("t", "a", {flag: True})
                self.assertFalse(refused["success"])
                self.assertEqual(refused["retry_with"], {"acknowledge_trap": True})
                self.assertIn(flag, refused["crash_flags"])

    def test_outcome_reports_the_native_return_as_observed(self):
        flags = {"src_media": False, "render_cache": False, "proxy_media": False}
        self.assertTrue(archive_guard.outcome(True, flags)["success"])
        false_out = archive_guard.outcome(False, flags)
        self.assertFalse(false_out["success"])
        self.assertIn("wrote nothing", false_out["error"])
        none_out = archive_guard.outcome(None, flags)
        self.assertFalse(none_out["success"])
        self.assertIn("crashed", none_out["error"])
        self.assertIsNone(none_out["native_returned"])


class RegistrationTests(unittest.TestCase):
    def test_both_compound_actions_are_rated_registered_writes(self):
        for action in ACTIONS:
            with self.subTest(action=action):
                self.assertTrue(destructive_hook.is_destructive("project_manager", action))
                risk = classify_operation_risk("project_manager", action, {})
                self.assertTrue(risk.recognised, risk)
                self.assertTrue(risk.destructive, risk)
                self.assertEqual(risk.level.value, "medium")

    def test_safe_archive_is_a_native_dry_run_and_raw_archive_is_not(self):
        self.assertIn(("project_manager", "safe_project_archive"),
                      destructive_hook.NATIVE_DRY_RUN_ACTIONS)
        self.assertNotIn(("project_manager", "archive"), destructive_hook.NATIVE_DRY_RUN_ACTIONS)

    def test_both_actions_carry_the_measured_fact(self):
        entry = next(e for e in API_TRUTH if e["symbol"] == "ProjectManager.ArchiveProject")
        self.assertEqual(entry["verified_on"], "DaVinci Resolve Studio 21.1.0.14")
        self.assertNotIn("destroys_prior_work", entry,
                         "the flag is symbol-level and would refuse the harmless flags-off call")
        for action in ACTIONS:
            with self.subTest(action=action):
                self.assertEqual(ACTION_SYMBOLS[("project_manager", action)],
                                 ["ProjectManager.ArchiveProject"])
                self.assertEqual([t["symbol"] for t in traps_for("project_manager", action)],
                                 ["ProjectManager.ArchiveProject"])


class CompoundTests(unittest.TestCase):
    def call(self, action, params, native):
        with patch.object(compound, "get_resolve", return_value=native), \
             patch.object(compound, "_check", return_value=(native, native, None)):
            return compound.project_manager(action, params)

    def test_raw_archive_defaults_every_flag_off(self):
        native = NativeSpy(returns=False)
        out = self.call("archive", {"name": "P", "path": "/tmp/x.dra"}, native)
        self.assertEqual(native.calls, [("P", "/tmp/x.dra", False, False, False)])
        self.assertFalse(out["success"])
        self.assertIn("wrote nothing", out["error"])

    def test_raw_archive_refuses_crash_flags_without_acknowledgement(self):
        for flag in ("src_media", "proxy_media"):
            with self.subTest(flag=flag):
                native = NativeSpy()
                out = self.call("archive", {"name": "P", "path": "/tmp/x.dra", flag: True}, native)
                self.assertFalse(out["success"])
                self.assertEqual(native.calls, [])

    def test_acknowledged_crash_flag_is_forwarded(self):
        native = NativeSpy(returns=None)
        out = self.call("archive", {"name": "P", "path": "/tmp/x.dra", "src_media": True,
                                    "acknowledge_trap": True}, native)
        self.assertEqual(native.calls, [("P", "/tmp/x.dra", True, False, False)])
        self.assertIn("crashed", out["error"])

    def test_string_flag_is_refused_before_native(self):
        native = NativeSpy()
        out = self.call("archive", {"name": "P", "path": "/tmp/x.dra", "src_media": "false"}, native)
        self.assertIn("error", out)
        self.assertEqual(native.calls, [])


class GranularTests(unittest.TestCase):
    def call(self, native, **kwargs):
        with patch.object(granular, "get_resolve", return_value=native):
            return granular.archive_project("P", "/tmp/x.dra", **kwargs)

    def test_defaults_are_all_off(self):
        native = NativeSpy(returns=False)
        out = self.call(native)
        self.assertEqual(native.calls, [("P", "/tmp/x.dra", False, False, False)])
        self.assertFalse(out["success"])

    def test_crash_flags_refused_without_acknowledgement(self):
        for kw in ("archive_src_media", "archive_proxy_media"):
            with self.subTest(flag=kw):
                native = NativeSpy()
                out = self.call(native, **{kw: True})
                self.assertFalse(out["success"])
                self.assertEqual(native.calls, [])

    def test_acknowledged_flag_reaches_native(self):
        native = NativeSpy(returns=None)
        self.call(native, archive_src_media=True, acknowledge_trap=True)
        self.assertEqual(native.calls, [("P", "/tmp/x.dra", True, False, False)])

    def test_tool_is_gated_and_labelled_destructive(self):
        """Read the decorators actually applied, the way the ratchet does, rather
        than searching the file for a name that could appear anywhere."""
        import ast
        tree = ast.parse(open(granular.__file__, encoding="utf-8").read())
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "archive_project")
        decorators = [ast.unparse(d) for d in fn.decorator_list]
        self.assertIn("mcp.tool(annotations=DESTRUCTIVE_TOOL)", decorators)
        self.assertIn("granular_destructive_op()", decorators)
        # The hook must sit INSIDE @mcp.tool so the schema FastMCP reads is the wrapper's.
        self.assertLess(decorators.index("mcp.tool(annotations=DESTRUCTIVE_TOOL)"),
                        decorators.index("granular_destructive_op()"))

if __name__ == "__main__":
    unittest.main()
