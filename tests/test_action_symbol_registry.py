"""Guards for the action→symbol registry behind trap push.

The registry maps a compound (tool, action) to the Resolve symbols it really
calls, so a verified fact reaches the caller at the callsite instead of waiting
for someone to think to query api_truth. Three ways that can rot:

  * a mapped symbol stops matching an API_TRUTH entry (renamed, removed) — the
    push silently degrades to nothing;
  * a mapped action is not a real handler — same silent nothing, which is the
    EX2 bug that let catastrophic deletes skip archiving;
  * an entry declares `destroys_prior_work` but no action maps to it, so the
    refusal it exists to trigger can never fire.

Each is a silent failure, so each gets a guard.
"""
from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from src.utils import destructive_hook as dh
from src.utils.api_truth import ACTION_SYMBOLS, API_TRUTH, traps_for

from tests.test_destructive_registry_drift import _destructive_op_tools


class RegistryIntegrity(unittest.TestCase):
    def test_every_mapped_symbol_is_a_real_entry(self):
        known = {e.get("symbol") for e in API_TRUTH}
        for (tool, action), symbols in ACTION_SYMBOLS.items():
            for symbol in symbols:
                self.assertIn(
                    symbol, known,
                    f"ACTION_SYMBOLS[{tool!r}, {action!r}] names {symbol!r}, "
                    "which is not an API_TRUTH symbol — the push would be silently empty.",
                )

    def test_every_mapped_action_is_a_real_handler(self):
        tools = _destructive_op_tools()
        for (tool, action) in ACTION_SYMBOLS:
            self.assertIn(tool, tools, f"{tool!r} is not an @_destructive_op tool")
            self.assertIn(
                action, tools[tool],
                f"ACTION_SYMBOLS names {tool}.{action}, which is not a real handler.",
            )

    def test_work_destroying_entries_are_reachable(self):
        mapped = {s for symbols in ACTION_SYMBOLS.values() for s in symbols}
        for entry in API_TRUTH:
            if entry.get("destroys_prior_work"):
                self.assertIn(
                    entry["symbol"], mapped,
                    f"{entry['symbol']} destroys unrecoverable work but no action maps "
                    "to it, so the refusal can never fire.",
                )

    def test_work_destroying_entries_have_a_live_probe(self):
        """A fact strong enough to refuse a call must be re-measurable.

        `destroys_prior_work` turns a verified fact into a hard refusal. If the
        behaviour it describes ever changes and nothing re-measures it, the
        refusal becomes a superstition that blocks legitimate work. So every such
        entry must be named by some live probe.
        """
        probes = list(pathlib.Path("src/utils").glob("*_live_probe.py"))
        self.assertTrue(probes, "no live probe modules found")
        corpus = "\n".join(f.read_text(encoding="utf-8") for f in probes)
        for entry in API_TRUTH:
            if not entry.get("destroys_prior_work"):
                continue
            method = entry["symbol"].split(".")[-1]
            self.assertIn(
                method, corpus,
                f"{entry['symbol']} carries destroys_prior_work (it refuses calls) but no "
                "live probe re-measures it. Add one, or drop the flag.",
            )

    def test_unmapped_action_returns_nothing(self):
        # Never guess. An unmapped action gets no fact rather than a nearby one.
        self.assertEqual(traps_for("timeline_item_color", "no_such_action_zzz"), [])
        self.assertEqual(traps_for("no_such_tool_zzz", "copy_grades"), [])


class GuardBehaviour(unittest.TestCase):
    """End-to-end through the real decorator, with a stub handler."""

    def _tool(self):
        calls = []

        @dh.destructive_op("timeline_item_color")
        def timeline_item_color(action, params=None, *a, **k):
            calls.append(action)
            return {"success": True}

        return timeline_item_color, calls

    def test_work_destroying_action_is_refused_and_handler_never_runs(self):
        tool, calls = self._tool()
        out = tool("copy_grades", {})
        self.assertFalse(out["success"])
        self.assertEqual(calls, [], "the handler ran despite the refusal")
        self.assertTrue(out["known_limitation"])
        self.assertEqual(out["retry_with"], {"acknowledge_trap": True})
        self.assertIn("CopyGrades", out["known_limitation"][0]["symbol"])

    def test_acknowledged_call_proceeds(self):
        tool, calls = self._tool()
        out = tool("copy_grades", {"acknowledge_trap": True})
        self.assertEqual(calls, ["copy_grades"])
        self.assertTrue(out["success"])

    def test_env_override_disables_the_refusal(self):
        tool, calls = self._tool()
        with mock.patch.dict("os.environ", {dh.TRAP_GUARD_ENV: "1"}):
            out = tool("copy_grades", {})
        self.assertEqual(calls, ["copy_grades"])
        self.assertTrue(out["success"])

    def test_informational_trap_rides_along_without_blocking(self):
        tool, calls = self._tool()
        out = tool("export_lut", {})
        self.assertEqual(calls, ["export_lut"], "an advisory trap must not block")
        self.assertTrue(out["success"])
        notice = out["known_limitation"][0]
        self.assertEqual(notice["symbol"], "TimelineItem.ExportLUT")
        self.assertIn("color", notice["reality"].lower())

    def test_push_is_compact(self):
        # Response weight is a real cost on long sessions; the push is 3 fields.
        tool, _ = self._tool()
        out = tool("export_lut", {})
        self.assertEqual(sorted(out["known_limitation"][0]), ["reality", "recommended", "symbol"])

    def test_dry_run_is_not_preempted_by_the_refusal(self):
        """A preview destroys nothing, so the guard must not answer for it.

        The refusal originally ran first and swallowed DRY_RUN_UNAVAILABLE,
        which is the more useful answer: it says the action cannot be previewed
        at all, rather than asking the caller to acknowledge a destruction that
        a dry run was never going to perform.
        """
        tool, _ = self._tool()
        out = tool("copy_grades", {"dry_run": True})
        self.assertEqual(out.get("error", {}).get("code"), "DRY_RUN_UNAVAILABLE")

    def test_unmapped_action_is_untouched(self):
        tool, calls = self._tool()
        out = tool("set_cdl", {})
        self.assertEqual(calls, ["set_cdl"])
        self.assertNotIn("known_limitation", out)


if __name__ == "__main__":
    unittest.main()
