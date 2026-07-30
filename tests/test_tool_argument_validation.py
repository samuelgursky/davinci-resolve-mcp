"""Every declared action must refuse missing arguments, not leak a KeyError.

Actions reach into `p["track_type"]` directly. When the key is absent that used to
raise a bare `KeyError` that escaped the action, escaped the tool, and reached the
client as `ToolError: Error executing tool timeline: 'track_type'` — no code, no
category, no remediation, nothing an agent can route on. **99 of 512 declared
actions failed that way**, found by walking the surface rather than by reading it.

The walk is the test. Reading the source cannot find these: `p[...]` after a
guard is correct and `p[...]` without one is a bug, and telling them apart means
executing the branch.

## Why a stub Resolve, and why it must be a stub

The failure lives *after* the connection and precondition gates — `get_track_count`
resolves the current timeline before touching `p`. With nothing connected every
action returns "not connected" and the walk passes vacuously, proving nothing. So
`get_resolve` is patched to a permissive stub, which also keeps the walk offline,
deterministic, and incapable of touching a real project.

`_launch_resolve` is patched too, and not defensively: calling it for real spends
60 s per action polling for a Resolve that will never answer, and it opens the
application — during development this test's own ancestor relaunched Resolve
unprompted, which is exactly the behaviour the server was just fixed to avoid.

## What the assertion covers, and what it deliberately does not

Only `KeyError` fails the walk. A stub cannot stand in for Resolve's return values
— actions that return a live object hand the stub straight back to the serializer,
and actions that do arithmetic on one raise TypeError. Those are artefacts of the
instrument, not defects in the code, and failing on them would make the test a
liability. `KeyError` has no such ambiguity: with an empty params dict it means one
thing.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import sys
import tempfile
import unittest
from typing import Any, Dict, List, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


class _Stub:
    """Truthy, callable, chainable — stands in for any Resolve object.

    Returns itself for everything, so actions get past their preconditions and
    reach the argument handling this test is about.
    """

    def __call__(self, *args: Any, **kwargs: Any) -> "_Stub":
        return self

    def __getattr__(self, item: str) -> "_Stub":
        if item.startswith("__"):
            raise AttributeError(item)
        return _Stub()

    def __bool__(self) -> bool:
        return True

    def __iter__(self):
        return iter(())

    def __len__(self) -> int:
        return 0

    def __str__(self) -> str:
        return "stub"

    def __int__(self) -> int:
        return 0

    def __float__(self) -> float:
        return 0.0


def _text_of(result: Any) -> str:
    content = getattr(result, "content", None)
    if content is None and isinstance(result, tuple):
        content = result[0]
    if isinstance(content, list):
        return "".join(getattr(part, "text", "") or "" for part in content)
    return str(result)


def _root_cause(exc: BaseException) -> BaseException:
    cause = exc
    while getattr(cause, "__cause__", None) is not None:
        cause = cause.__cause__
    return cause


class ToolArgumentValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # HOME is redirected before importing the server, so anything that writes
        # state during the walk lands in a scratch dir and not the user's home.
        cls._home = os.environ.get("HOME")
        cls._sandbox = tempfile.mkdtemp(prefix="tool_walk_home_")
        os.environ["HOME"] = cls._sandbox
        cls._bridge = os.environ.pop("DAVINCI_RESOLVE_BRIDGE", None)

        from src import server

        cls.server = server
        cls._real_get_resolve = server.get_resolve
        cls._real_launch = server._launch_resolve
        server.get_resolve = lambda: _Stub()
        server._launch_resolve = lambda: False

        cls.actions = asyncio.run(cls._collect_actions())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.get_resolve = cls._real_get_resolve
        cls.server._launch_resolve = cls._real_launch
        if cls._home is not None:
            os.environ["HOME"] = cls._home
        if cls._bridge is not None:
            os.environ["DAVINCI_RESOLVE_BRIDGE"] = cls._bridge

    @classmethod
    async def _collect_actions(cls) -> List[Tuple[str, str]]:
        """Harvest each tool's action list from its own unknown-action error.

        Asking the server beats maintaining a list here: a new action is covered
        the day it ships, with nothing to keep in sync.
        """
        pairs: List[Tuple[str, str]] = []
        for tool in sorted(t.name for t in await cls.server.mcp.list_tools()):
            try:
                body = _text_of(await cls.server.mcp.call_tool(tool, {"action": "__probe_invalid__"}))
            except Exception:
                continue
            match = re.search(r"Valid actions:\s*([^\"\\}]+)", body)
            if not match:
                continue
            for action in match.group(1).replace("\\n", " ").split(","):
                action = action.strip()
                if action:
                    pairs.append((tool, action))
        return pairs

    def test_the_walk_reaches_a_meaningful_number_of_actions(self) -> None:
        """A harvest that quietly returned nothing would make every test below pass.

        512 actions were reachable when this was written. The floor is loose on
        purpose — it guards against the harvest breaking, not against the surface
        growing or shrinking.
        """
        self.assertGreater(len(self.actions), 400, "action harvest looks broken, not merely changed")
        self.assertGreater(len({tool for tool, _ in self.actions}), 20)

    def test_no_action_leaks_a_keyerror_for_missing_arguments(self) -> None:
        """The regression guard. 99 actions failed this before the params dict
        started raising something the tool boundary can recognise."""
        leaked: List[str] = []
        for tool, action in self.actions:
            try:
                asyncio.run(self.server.mcp.call_tool(tool, {"action": action}))
            except Exception as exc:  # noqa: BLE001 - the exception is the observation
                cause = _root_cause(exc)
                if isinstance(cause, KeyError):
                    leaked.append(f"{tool}.{action} -> KeyError({cause.args[0]!r})")
        self.assertEqual(
            leaked, [],
            "these actions subscript a parameter without the guard reaching it:\n  "
            + "\n  ".join(leaked),
        )

    def test_a_missing_argument_returns_the_structured_envelope(self) -> None:
        """Shape, not just absence of a crash — an agent routes on these fields."""
        for tool, action, expected_code in (
            ("timeline", "get_track_count", "MISSING_TRACK_TYPE"),
            ("graph", "get_lut", "MISSING_NODE_INDEX"),
            ("render", "get_codecs", "MISSING_FORMAT"),
            ("media_storage", "get_files", "MISSING_PATH"),
        ):
            with self.subTest(tool=tool, action=action):
                body = json.loads(_text_of(asyncio.run(
                    self.server.mcp.call_tool(tool, {"action": action})
                )))
                error = body.get("error")
                self.assertIsInstance(error, dict, body)
                self.assertEqual(error["code"], expected_code)
                self.assertEqual(error["category"], "invalid_input")
                # An input error the caller must fix is not retryable; saying it
                # is sends an agent into a loop it cannot win.
                self.assertFalse(error["retryable"])
                self.assertIn("required", error["message"])
                self.assertIn("remediation", error)
                self.assertEqual(error["state"]["action"], action)

    def test_every_tool_carries_the_guard(self) -> None:
        """Drift guard: a new `@mcp.tool()` without it re-opens the whole class."""
        import ast

        source = os.path.join(REPO_ROOT, "src", "server.py")
        with open(source, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read())

        def names(node):
            return {
                d.func.attr if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                else d.attr if isinstance(d, ast.Attribute)
                else d.id if isinstance(d, ast.Name)
                else ""
                for d in node.decorator_list
            }

        unguarded = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and "tool" in names(node)
            and "_guard_missing_params" not in names(node)
        ]
        self.assertEqual(unguarded, [], f"@mcp.tool() functions missing the guard: {unguarded}")

    def test_the_guard_preserves_async_tools(self) -> None:
        """The bug the walk caught while this was being written.

        A synchronous wrapper around `media_analysis` — which is `async` and also
        takes `ctx` — returned an un-awaited coroutine. FastMCP could not use it
        and the tool stopped answering entirely, taking its 71 actions with it.
        """
        guarded = self.server._guard_missing_params

        async def async_tool(action, params=None, ctx=None):
            return {"action": action, "ctx": ctx}

        def sync_tool(action, params=None):
            return {"action": action}

        self.assertTrue(inspect.iscoroutinefunction(guarded(async_tool)))
        self.assertFalse(inspect.iscoroutinefunction(guarded(sync_tool)))
        # And the extra parameter still arrives.
        self.assertEqual(
            asyncio.run(guarded(async_tool)("go", None, "the-context"))["ctx"], "the-context"
        )

    def test_the_guard_only_catches_parameter_misses(self) -> None:
        """A KeyError on some other dict is our bug, and must not be relabelled.

        Reporting an internal lookup failure as "you forgot an argument" sends the
        caller to fix a call that was already correct, and hides the real fault.
        """
        guarded = self.server._guard_missing_params

        def reads_a_parameter(action, params=None):
            return (params or {})["needed"]

        def reads_another_dict(action, params=None):
            from_resolve: Dict[str, Any] = {}
            return from_resolve["SomeResolveKey"]

        # Missing parameter: the guard has to see the raise, so the tool body must
        # use the params dict the server hands it.
        wrapped = guarded(lambda action, params=None: self.server._params(params)["needed"])
        self.assertEqual(wrapped("act")["error"]["code"], "MISSING_NEEDED")

        # A plain dict subscript is still a plain KeyError, and still escapes.
        with self.assertRaises(KeyError):
            guarded(reads_another_dict)("act")
        # Even one on a plain params dict, because only _Params is diagnosable.
        with self.assertRaises(KeyError):
            guarded(reads_a_parameter)("act", {})

    def test_missing_param_is_a_keyerror_subclass(self) -> None:
        """So existing `except KeyError:` blocks keep behaving as they did."""
        self.assertTrue(issubclass(self.server._MissingParam, KeyError))

    def test_an_empty_params_dict_still_gets_the_diagnosable_dict(self) -> None:
        """`p = params or {}` handed back a *plain* dict for empty params, which is
        precisely the no-arguments case this exists to serve."""
        empty = self.server._params(None)
        self.assertIsInstance(empty, self.server._Params)
        self.assertFalse(empty, "an empty _Params must stay falsy like any empty dict")
        with self.assertRaises(self.server._MissingParam):
            empty["anything"]

    def test_no_tool_body_still_unpacks_params_the_old_way(self) -> None:
        """`p = params or {}` bypasses the mechanism entirely."""
        source = os.path.join(REPO_ROOT, "src", "server.py")
        with open(source, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        offenders = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(lines, 1)
            if re.match(r"^\s*p = params or \{\}\s*$", line)
        ]
        self.assertEqual(offenders, [], f"use _params(params) instead:\n  " + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
