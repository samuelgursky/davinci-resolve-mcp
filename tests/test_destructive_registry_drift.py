"""Static guard: destructive-action registry strings must be REAL handlers.

The EX2 bug: DESTRUCTIVE_ACTIONS_BY_TOOL["media_pool"] listed granular function
names (delete_media_pool_clips, …) that the compound media_pool tool never
dispatches, so is_destructive() returned False and catastrophic deletes silently
skipped version-on-mutate archiving. This guard fails CI if any registry or
token-gated action string is not an actual `action == "…"` branch in the tool
function decorated with @_destructive_op("<tool>").
"""
from __future__ import annotations

import ast
import pathlib
import unittest

from src.utils.destructive_hook import DESTRUCTIVE_ACTIONS_BY_TOOL

import src.server as s

SERVER = pathlib.Path(__file__).resolve().parent.parent / "src" / "server.py"


def _implemented_actions(fn):
    """Actions a tool function handles: `action ==` branches plus the actions it
    advertises in its _unknown(action, [...]) list (which includes actions it
    dispatches via delegated helpers)."""
    found = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "action":
            for comp in node.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    found.add(comp.value)
                elif isinstance(comp, (ast.Set, ast.List, ast.Tuple)):
                    found.update(
                        elt.value for elt in comp.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_unknown":
            for arg in node.args:
                if isinstance(arg, (ast.List, ast.Tuple)):
                    found.update(
                        elt.value for elt in arg.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    )
    return found


def _destructive_op_tools():
    """Map @_destructive_op("tool") -> set of implemented action strings."""
    tree = ast.parse(SERVER.read_text())
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Name)
                and dec.func.id == "_destructive_op"
                and dec.args
                and isinstance(dec.args[0], ast.Constant)
            ):
                out[dec.args[0].value] = _implemented_actions(node)
    return out


class RegistryDriftTest(unittest.TestCase):
    def setUp(self):
        self.tools = _destructive_op_tools()
        self.assertIn("media_pool", self.tools, "expected @_destructive_op('media_pool')")

    def test_registry_actions_are_real_handlers(self):
        # EX-REG: every registry action must be a real handler for its tool (impl
        # `action ==` branch or advertised in the tool's _unknown list). Tools not
        # wrapped with @_destructive_op have inert entries; none should remain.
        for tool, actions in DESTRUCTIVE_ACTIONS_BY_TOOL.items():
            impl = self.tools.get(tool)
            self.assertIsNotNone(
                impl, f"DESTRUCTIVE_ACTIONS_BY_TOOL has tool {tool!r} that is not @_destructive_op-wrapped"
            )
            for action in actions:
                self.assertIn(
                    action, impl,
                    f"DESTRUCTIVE_ACTIONS_BY_TOOL[{tool!r}] lists {action!r}, but it is not a "
                    f"real action of the {tool} tool (registry drift — governance would not fire).",
                )

    def test_token_gated_actions_are_real_handlers(self):
        for tool, action in s._TOKEN_GATED_DESTRUCTIVE_ACTIONS:
            impl = self.tools.get(tool)
            if impl is None:
                continue
            self.assertIn(
                action, impl,
                f"_TOKEN_GATED_DESTRUCTIVE_ACTIONS has ({tool!r}, {action!r}) "
                f"but it is not a real handler in the {tool} tool.",
            )

    def test_media_pool_catastrophic_deletes_registered_and_gated(self):
        # Lock in EX2/EX3 specifically.
        mp = DESTRUCTIVE_ACTIONS_BY_TOOL["media_pool"]
        for action in ("delete_clips", "delete_folders", "delete_timelines"):
            self.assertIn(action, mp)
            self.assertIn(("media_pool", action), s._TOKEN_GATED_DESTRUCTIVE_ACTIONS)


if __name__ == "__main__":
    unittest.main()
