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

import re

from src.utils import destructive_hook as dh
from src.utils.api_truth import ACTION_SYMBOLS, API_TRUTH, traps_for

from tests.test_destructive_registry_drift import _destructive_op_tools

SERVER = pathlib.Path(__file__).resolve().parent.parent / "src" / "server.py"


def _handler_source(server_src: str, action: str):
    """Source of the helper an action dispatches to, else its own branch.

    Actions here are dispatched as `elif action == "x": return _helper(...)`, and
    the confirmation logic lives in `_helper`, not at the branch.
    """
    m = re.search(rf'action == "{re.escape(action)}"\s*:\s*\n\s*return (_[a-z0-9_]+)\(',
                  server_src)
    if m:
        fn = m.group(1)
        d = re.search(rf"\ndef {re.escape(fn)}\(", server_src)
        if d:
            nxt = re.search(r"\ndef [a-zA-Z_]", server_src[d.start() + 1:])
            end = d.start() + 1 + (nxt.start() if nxt else len(server_src))
            return server_src[d.start():end]

    # Not every action delegates: `copy_grades` is dispatched inline. Returning
    # None for those made the caller skip them, which quietly excused the single
    # most important action from the guard. Fall back to the branch body.
    b = re.search(rf'action == "{re.escape(action)}"\s*:', server_src)
    if b:
        rest = server_src[b.end():]
        nxt = re.search(r"\n    (?:elif action ==|return _unknown\()", rest)
        return rest[:nxt.start()] if nxt else rest[:4000]
    return None


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

    def test_exempt_actions_really_do_confirm_for_themselves(self):
        """An exemption is only safe while the action's own gate still exists.

        These actions are excused from the refusal because they already make the
        caller confirm. If someone deletes that handler-side gate, the exemption
        silently becomes "no confirmation at all" — so tie the two together.
        """
        server_src = SERVER.read_text(encoding="utf-8")
        for tool, action in sorted(dh.TRAP_REFUSAL_EXEMPT_ACTIONS):
            body = _handler_source(server_src, action)
            self.assertIsNotNone(body, f"no handler found for {tool}.{action}")
            self.assertIn(
                "confirm_token", body,
                f"{tool}.{action} is exempt from the trap refusal because it confirms for "
                "itself, but its handler no longer mentions confirm_token. Either restore "
                "the gate or drop the exemption.",
            )

    def test_refusing_actions_are_not_dry_run_by_default(self):
        """A refusal must never answer for a call that mutates nothing.

        `bulk_match_to_hero` defaulted `dry_run` to True inside its handler, so a
        bare first call was a pure preview — and the guard refused it, demanding
        acknowledgement of a destruction that call was never going to perform.
        The dry-run exemption only sees an EXPLICIT dry_run, so a handler-level
        default has to be caught here instead.
        """
        server_src = SERVER.read_text(encoding="utf-8")
        for (tool, action) in sorted(ACTION_SYMBOLS):
            if not any(e.get("destroys_prior_work") for e in traps_for(tool, action)):
                continue
            if (tool, action) in dh.TRAP_REFUSAL_EXEMPT_ACTIONS:
                continue
            body = _handler_source(server_src, action)
            self.assertIsNotNone(
                body,
                f"could not locate the handler for {tool}.{action}; the guard would "
                "silently skip it, which is how copy_grades went unchecked.",
            )
            self.assertNotRegex(
                body, r"""dry_run["']\s*,\s*True""",
                f"{tool}.{action} refuses on destroys_prior_work but defaults dry_run to "
                "True in its handler, so a first call previews and mutates nothing. Exempt "
                "it, or stop defaulting dry_run.",
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

    def test_exempt_action_is_not_refused_but_still_advised(self):
        """The action that already confirms runs, and keeps the fact attached.

        Refusing here would cost the caller two acknowledgements found serially:
        add acknowledge_trap, retry, then discover a confirm_token is also
        needed. The advisory push is still worth having.
        """
        tool, calls = self._tool()
        out = tool("safe_copy_grade", {})
        self.assertEqual(calls, ["safe_copy_grade"], "an action that self-confirms must not be refused")
        self.assertNotIn("retry_with", out)
        self.assertEqual(out["known_limitation"][0]["symbol"], "TimelineItem.CopyGrades")

    def test_dry_run_by_default_action_is_not_refused_on_a_bare_call(self):
        """A first call to bulk_match_to_hero previews; it must not be refused.

        Its handler defaults dry_run to True, so `{}` mutates nothing — but
        _explicit_dry_run_requested({}) is False, so the dry-run exemption alone
        never covered it.
        """
        self.assertFalse(dh._explicit_dry_run_requested({}))
        tool, calls = self._tool()
        out = tool("bulk_match_to_hero", {})
        self.assertEqual(calls, ["bulk_match_to_hero"])
        self.assertNotIn("retry_with", out)

    def test_unmapped_action_is_untouched(self):
        tool, calls = self._tool()
        out = tool("set_cdl", {})
        self.assertEqual(calls, ["set_cdl"])
        self.assertNotIn("known_limitation", out)


if __name__ == "__main__":
    unittest.main()
