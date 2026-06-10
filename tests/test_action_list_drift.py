"""Static guard: each tool's _unknown(action, [...]) list matches its dispatch.

The valid-actions list in the unknown-action error is what agents read to
recover from a typo, and what tooling parses for discovery. When it drifts
from the real elif chain, implemented actions become invisible (clip_where
and action_help were missing from three tools' lists before this guard) or
phantom actions get advertised.

Checked both directions per tool:
  - every action compared against `action` in the function body must appear
    in the _unknown list (unless it is a documented alias in ALIASES)
  - every listed action must be implemented
"""
from __future__ import annotations

import ast
import pathlib
import unittest

SERVER = pathlib.Path(__file__).resolve().parent.parent / "src" / "server.py"

# Intentional aliases: accepted by dispatch but advertised under their
# canonical name only.
ALIASES = {
    "setup": {"capabilities", "options", "get", "status", "set", "configure", "clear", "reset"},
}


def _module_list_constants(tree):
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                values = [
                    elt.value
                    for elt in node.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                ]
                if len(values) == len(node.value.elts):
                    consts[node.targets[0].id] = values
    return consts


def _implemented_actions(fn):
    found = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "action":
            for comp in node.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    found.add(comp.value)
                elif isinstance(comp, (ast.Set, ast.List, ast.Tuple)):
                    found.update(
                        elt.value
                        for elt in comp.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    )
    return found


def _listed_actions(fn, consts):
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_unknown":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.List):
                listed, resolvable = set(), True
                for elt in node.args[1].elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        listed.add(elt.value)
                    elif isinstance(elt, ast.Starred) and isinstance(elt.value, ast.Name) and elt.value.id in consts:
                        listed.update(consts[elt.value.id])
                    else:
                        resolvable = False
                return listed, resolvable
    return None, False


class ActionListDriftTest(unittest.TestCase):
    def test_unknown_action_lists_match_dispatch(self):
        tree = ast.parse(SERVER.read_text())
        consts = _module_list_constants(tree)
        problems = []
        checked = 0
        for node in tree.body:
            # Async tools (e.g. media_analysis) drifted unchecked for several
            # releases because only FunctionDef was inspected.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            listed, resolvable = _listed_actions(node, consts)
            if listed is None or not resolvable:
                continue
            implemented = _implemented_actions(node)
            if not implemented:
                continue
            checked += 1
            aliases = ALIASES.get(node.name, set())
            missing = sorted(implemented - listed - aliases)
            phantom = sorted(listed - implemented)
            if missing:
                problems.append(f"{node.name}: implemented but not listed: {missing}")
            if phantom:
                problems.append(f"{node.name}: listed but not implemented: {phantom}")
        self.assertGreater(checked, 10, "drift checker found too few tools — parser broken?")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_no_unreachable_actions_inside_membership_blocks(self):
        """An `action == "x"` check nested under `if action in {...}` is dead
        code unless "x" is in the membership set. The V2 correction actions
        (update_shot_field et al.) were unreachable from v2.24.0 to v2.40.0
        because of exactly this — the panel proxied to the helpers directly,
        which masked it. Guard the whole class.
        """
        tree = ast.parse(SERVER.read_text())
        problems = []

        def membership_set(test):
            # Matches: action in {...} / [...] / (...) with string constants.
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "action"
                and len(test.ops) == 1
                and isinstance(test.ops[0], ast.In)
                and isinstance(test.comparators[0], (ast.Set, ast.List, ast.Tuple))
            ):
                elts = test.comparators[0].elts
                values = {
                    elt.value
                    for elt in elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                }
                if len(values) == len(elts):
                    return values
            return None

        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.If):
                    continue
                allowed = membership_set(node.test)
                if allowed is None:
                    continue
                for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if (
                        isinstance(inner, ast.Compare)
                        and isinstance(inner.left, ast.Name)
                        and inner.left.id == "action"
                        and len(inner.ops) == 1
                        and isinstance(inner.ops[0], ast.Eq)
                        and isinstance(inner.comparators[0], ast.Constant)
                        and isinstance(inner.comparators[0].value, str)
                    ):
                        value = inner.comparators[0].value
                        if value not in allowed:
                            problems.append(
                                f"{fn.name}: action == {value!r} at line {inner.lineno} is "
                                f"unreachable — not in the enclosing membership set"
                            )
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
