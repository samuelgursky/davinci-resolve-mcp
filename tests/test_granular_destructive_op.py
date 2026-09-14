"""The granular enforcement hook refuses, audits, and changes nothing else.

`@granular_destructive_op()` is the granular server's whole safety surface: for
four releases there was none, and the first draft of this one was cosmetic — it
rated verbs "HIGH" while the safe-mode gate holds `RiskLevel.HIGH.value == "high"`,
so nothing ever matched and a HIGH tool ran with safe mode on. Every test here
was written against a probe that FAILED first.

What the hook does: refuse a HIGH/CRITICAL call while `destructive.safe_mode` is
on unless the call passes `allow_risky_operation=true`; write an audit row for
every call; annotate a dict result. What it does NOT do: archive. A granular
write cannot be recovered after it runs, and nothing here pretends otherwise.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import tempfile
import unittest
from unittest import mock

import src.granular.timeline_item as ti
from src.granular.common import mcp
from src.utils import destructive_hook as dh
from src.utils.execution_lifecycle import RiskLevel


def _probe(name: str, returns):
    """A decorated function named like a granular tool, recording its calls."""
    calls = []

    def fn(color: str = "", item_index: int = 0):
        calls.append({"color": color, "item_index": item_index})
        return returns() if callable(returns) else returns

    fn.__name__ = name
    return dh.granular_destructive_op()(fn), calls


class RiskVocabulary(unittest.TestCase):
    def test_verb_ratings_are_risk_level_values(self):
        valid = {level.value for level in RiskLevel}
        self.assertTrue(set(dh.GRANULAR_RISK_BY_VERB.values()) <= valid,
                        sorted(set(dh.GRANULAR_RISK_BY_VERB.values()) - valid))

    def test_high_verbs_are_ones_safe_mode_refuses(self):
        # If nothing in the verb table is blockable, safe mode is cosmetic again.
        high = {verb for verb, level in dh.GRANULAR_RISK_BY_VERB.items()
                if level in dh.SAFE_MODE_BLOCKED_RISK_LEVELS}
        self.assertIn("delete", high)
        self.assertIn("clear", high)
        self.assertNotIn("set", high)

    def test_namespace_is_stripped_before_the_verb_is_read(self):
        self.assertEqual(dh.granular_risk_level("ti_clear_flags"), RiskLevel.HIGH.value)
        self.assertEqual(dh.granular_risk_level("timeline_delete_track"), RiskLevel.HIGH.value)
        self.assertEqual(dh.granular_risk_level("graph_set_lut"), RiskLevel.MEDIUM.value)
        self.assertEqual(dh.granular_risk_level("set_clip_color"), RiskLevel.MEDIUM.value)

    def test_unknown_verbs_are_medium_never_high(self):
        self.assertEqual(dh.granular_risk_level("ti_frobnicate_thing"), RiskLevel.MEDIUM.value)

    def test_the_ledger_outranks_the_verb(self):
        """`copy` is in no table, so by verb ti_copy_grades is MEDIUM. It reaches
        `TimelineItem.CopyGrades`, which the ledger marks destroys_prior_work, so
        the hook rates it HIGH — from the ledger, mechanically."""
        self.assertEqual(dh.granular_risk_level("ti_copy_grades"), RiskLevel.MEDIUM.value)
        self.assertEqual(dh.granular_risk_level("ti_copy_grades", ti.ti_copy_grades.__wrapped__),
                         RiskLevel.HIGH.value)
        self.assertEqual(ti.ti_copy_grades.__granular_destructive__[1], RiskLevel.HIGH.value)


class SafeModeRefusal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = os.path.join(self.tmp.name, "audit.jsonl")
        for patcher in (mock.patch.object(dh, "_audit_log_path", lambda: self.audit),
                        mock.patch.object(dh, "_safe_mode_enabled", lambda: True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _rows(self):
        with open(self.audit, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_high_tool_is_refused_and_never_runs(self):
        tool, calls = _probe("ti_clear_flags_probe", {"success": True})
        result = tool(color="Blue")
        self.assertEqual(calls, [], "the body ran despite safe mode")
        self.assertEqual(result["status"], "blocked_by_security_policy")
        self.assertEqual(result["error"]["code"], "SAFE_MODE_BLOCKED")
        self.assertEqual(result["security"]["risk_level"], RiskLevel.HIGH.value)
        # The remediation names the granular argument, not the compound `params.` path.
        self.assertIn("allow_risky_operation=true", result["error"]["message"])
        self.assertNotIn("params.allow_risky_operation", result["error"]["message"])
        (row,) = self._rows()
        self.assertEqual((row["tool"], row["action"], row["status"], row["reason"], row["risk_level"]),
                         ("granular", "ti_clear_flags_probe", "blocked", "safe_mode", "high"))

    def test_override_lets_one_call_through(self):
        tool, calls = _probe("ti_clear_flags_probe", {"success": True})
        result = tool(color="Blue", allow_risky_operation=True)
        self.assertEqual(calls, [{"color": "Blue", "item_index": 0}])
        self.assertTrue(result["success"])
        self.assertEqual(result["security"]["risk_level"], RiskLevel.HIGH.value)
        self.assertFalse(result["security"]["blocked"])
        (row,) = self._rows()
        self.assertEqual(row["status"], "allowed")
        self.assertIs(row["params"]["allow_risky_operation"], True)

    def test_override_must_be_a_real_true(self):
        tool, calls = _probe("ti_clear_flags_probe", {"success": True})
        self.assertEqual(tool(color="Blue", allow_risky_operation="maybe")["status"],
                         "blocked_by_security_policy")
        self.assertEqual(calls, [])

    def test_medium_tool_runs_with_safe_mode_on(self):
        tool, calls = _probe("ti_set_clip_color_probe", {"success": True})
        result = tool(color="Blue")
        self.assertEqual(len(calls), 1)
        self.assertTrue(result["success"])
        self.assertEqual(result["security"]["risk_level"], RiskLevel.MEDIUM.value)

    def test_registered_high_tool_is_refused_before_touching_resolve(self):
        """Not a probe: the real `ti_clear_flags`, as FastMCP registered it."""
        never = mock.Mock(side_effect=AssertionError("reached Resolve"))
        with mock.patch.object(ti, "_get_timeline_item", never), \
             mock.patch.object(ti, "_get_timeline", never), \
             mock.patch.object(ti, "get_current_project", never), \
             mock.patch.object(ti, "get_resolve", never):
            result = ti.ti_clear_flags(color="Blue")
        self.assertEqual(result["status"], "blocked_by_security_policy")
        never.assert_not_called()

    def test_no_archive_is_taken(self):
        """The decision: safe-mode refusal + audit only. An archive around a
        clip-colour change would bury a project in versions."""
        tool, _calls = _probe("ti_set_clip_color_probe", {"success": True})
        result = tool(color="Blue")
        self.assertNotIn("_versioning", result)
        (row,) = self._rows()
        self.assertEqual(row["reason"], "no_archive_on_granular")


class SafeModeOff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = os.path.join(self.tmp.name, "audit.jsonl")
        for patcher in (mock.patch.object(dh, "_audit_log_path", lambda: self.audit),
                        mock.patch.object(dh, "_safe_mode_enabled", lambda: False)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_high_tool_runs_and_is_audited(self):
        tool, calls = _probe("ti_delete_marker_probe", {"success": True})
        result = tool(color="Blue")
        self.assertEqual(len(calls), 1)
        self.assertTrue(result["success"])
        self.assertTrue(result["operation_id"].startswith("op_"))
        self.assertEqual(result["security"]["risk_level"], RiskLevel.HIGH.value)
        self.assertFalse(result["security"]["safe_mode"])
        with open(self.audit, encoding="utf-8") as handle:
            (row,) = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual((row["tool"], row["status"], row["params"]["color"]),
                         ("granular", "allowed", "Blue"))

    def test_list_results_pass_through_untouched(self):
        """Several granular tools return lists. `_annotate_security` uses setdefault,
        which only a dict has — a list must come back as the same object, unchanged."""
        payload = [{"name": "TL 1"}, {"name": "TL 2"}]
        tool, _calls = _probe("ti_delete_marker_probe", lambda: payload)
        result = tool()
        self.assertIs(result, payload)
        self.assertEqual(result, [{"name": "TL 1"}, {"name": "TL 2"}])

    def test_scalar_results_pass_through_untouched(self):
        tool, _calls = _probe("ti_delete_marker_probe", True)
        self.assertIs(tool(), True)

    def test_positional_arguments_are_audited_by_name(self):
        tool, _calls = _probe("ti_delete_marker_probe", {"success": True})
        tool("Red", 3)
        with open(self.audit, encoding="utf-8") as handle:
            (row,) = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(row["params"], {"color": "Red", "item_index": 3,
                                         "allow_risky_operation": False})

    def test_unwritable_audit_path_cannot_break_the_call(self):
        blocker = os.path.join(self.tmp.name, "not-a-dir")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("x")
        with mock.patch.object(dh, "_audit_log_path", lambda: os.path.join(blocker, "audit.jsonl")):
            tool, calls = _probe("ti_delete_marker_probe", {"success": True})
            with self.assertLogs("resolve-mcp.destructive-hook", level="WARNING"):
                result = tool(color="Blue")
        self.assertEqual(len(calls), 1)
        self.assertTrue(result["success"])

    def test_body_exception_propagates_unchanged(self):
        def boom():
            raise ValueError("resolve said no")
        tool, _calls = _probe("ti_delete_marker_probe", boom)
        with self.assertRaisesRegex(ValueError, "resolve said no"):
            tool()


class RefusalMatchesTheDeclaredReturnType(unittest.TestCase):
    """A refusal the client cannot receive is not a refusal.

    FastMCP builds an output schema from the return annotation and validates
    against it, so returning the block dict from a tool annotated `-> str` raised
    `ToolError` and the caller got a generic execution error carrying none of the
    SAFE_MODE_BLOCKED code or remediation. The gate fired correctly and its answer
    was destroyed on the way out. 27 granular tools declare `-> str`, and the
    HIGH-risk ones among them are exactly the calls safe mode exists to stop —
    `clear_folder_transcription`, `unlink_proxy_media`, `replace_clip`.
    """

    def _str_tool(self):
        def fn(folder_name: str = "") -> str:
            return "did the thing"
        fn.__name__ = "clear_str_probe"
        return dh.granular_destructive_op()(fn)

    def _dict_tool(self):
        def fn(folder_name: str = "") -> dict:
            return {"success": True}
        fn.__name__ = "clear_dict_probe"
        return dh.granular_destructive_op()(fn)

    def test_a_string_tool_is_refused_as_a_string(self):
        with mock.patch.object(dh, "_safe_mode_enabled", lambda: True):
            out = self._str_tool()(folder_name="x")

        self.assertIsInstance(out, str)
        self.assertIn("SAFE_MODE_BLOCKED", out)

    def test_the_string_refusal_still_says_how_to_proceed(self):
        """The machine-readable code is lost to the schema; the guidance must not be."""
        with mock.patch.object(dh, "_safe_mode_enabled", lambda: True):
            out = self._str_tool()(folder_name="x")

        self.assertIn("allow_risky_operation", out)
        self.assertIn("safe_mode", out)

    def test_a_dict_tool_keeps_the_structured_envelope(self):
        with mock.patch.object(dh, "_safe_mode_enabled", lambda: True):
            out = self._dict_tool()(folder_name="x")

        self.assertIsInstance(out, dict)
        self.assertEqual(out["error"]["code"], "SAFE_MODE_BLOCKED")
        self.assertEqual(out["status"], "blocked_by_security_policy")

    def test_the_string_path_does_not_swallow_a_permitted_call(self):
        with mock.patch.object(dh, "_safe_mode_enabled", lambda: True):
            out = self._str_tool()(folder_name="x", allow_risky_operation=True)

        self.assertEqual(out, "did the thing")

    def test_no_shipped_tool_is_left_returning_a_dict_it_cannot_declare(self):
        """The end-to-end shape, through the real registry rather than a probe.

        Every destructive-decorated tool annotated `-> str` must hand back a string
        when blocked, or FastMCP refuses it on the way out.
        """
        import ast
        import pathlib

        offenders = []
        granular = pathlib.Path(__file__).resolve().parent.parent / "src" / "granular"
        for path in sorted(granular.glob("*.py")):
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if not isinstance(node, ast.FunctionDef) or not node.returns:
                    continue
                decorators = [ast.unparse(d) for d in node.decorator_list]
                if not any("granular_destructive_op" in d for d in decorators):
                    continue
                if ast.unparse(node.returns) != "str":
                    continue
                fn = getattr(__import__(f"src.granular.{path.stem}", fromlist=["x"]),
                             node.name, None)
                if fn is None:
                    continue
                inner = getattr(fn, "__wrapped__", fn)
                if not dh._returns_plain_string(inner):
                    offenders.append(f"{path.name}:{node.name}")
        self.assertEqual(offenders, [], "annotated -> str but the hook would return a dict")


class McpSchema(unittest.TestCase):
    """`functools.wraps` plus `__signature__`: FastMCP sees the tool's own
    parameters and exactly one addition."""

    @classmethod
    def setUpClass(cls):
        cls.tools = {t.name: t for t in asyncio.run(mcp.list_tools())}

    def test_every_hooked_tool_advertises_the_override_and_nothing_else_new(self):
        import importlib
        import pathlib
        hooked = 0
        for path in sorted((pathlib.Path(__file__).resolve().parent.parent / "src" / "granular").glob("*.py")):
            module = importlib.import_module(f"src.granular.{path.stem}")
            for name, fn in vars(module).items():
                if not hasattr(fn, "__granular_destructive__") or name not in self.tools:
                    continue
                hooked += 1
                original = set(inspect.signature(fn.__wrapped__).parameters)
                advertised = set(self.tools[name].inputSchema["properties"])
                with self.subTest(tool=name):
                    self.assertEqual(advertised, original | {dh.GRANULAR_OVERRIDE_PARAM})
                    self.assertTrue(self.tools[name].annotations.destructiveHint)
        self.assertGreater(hooked, 100, "the hook is not on the tools FastMCP registered")

    def test_readers_and_plain_writes_do_not_carry_the_override(self):
        for name in ("ti_get_info", "timeline_get_track_name", "add_marker" if "add_marker" in self.tools else "ti_get_markers"):
            with self.subTest(tool=name):
                self.assertNotIn(dh.GRANULAR_OVERRIDE_PARAM, self.tools[name].inputSchema["properties"])

    def test_the_override_reaches_the_hook_through_fastmcp(self):
        """End to end: a client passing allow_risky_operation through MCP."""
        async def call():
            never = mock.Mock(side_effect=AssertionError("reached Resolve"))
            with mock.patch.object(dh, "_safe_mode_enabled", lambda: True), \
                 mock.patch.object(dh, "_audit_enabled", lambda: False), \
                 mock.patch.object(ti, "_get_timeline_item", never), \
                 mock.patch.object(ti, "_get_timeline", never), \
                 mock.patch.object(ti, "get_current_project", never), \
                 mock.patch.object(ti, "get_resolve", never):
                blocked = await mcp.call_tool("ti_clear_flags", {"color": "Blue"})
                with mock.patch.object(ti, "_get_timeline_item",
                                       return_value=(None, {"error": "stub"})):
                    allowed = await mcp.call_tool(
                        "ti_clear_flags", {"color": "Blue", "allow_risky_operation": True})
            return blocked, allowed
        blocked, allowed = asyncio.run(call())
        self.assertIn("SAFE_MODE_BLOCKED", str(blocked))
        self.assertNotIn("SAFE_MODE_BLOCKED", str(allowed))


if __name__ == "__main__":
    unittest.main()
