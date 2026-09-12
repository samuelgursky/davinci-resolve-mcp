"""The server does not execute caller-supplied code, in any form.

Maintainer policy, enforced from v3.0.0. `script_plugin` used to expose two
actions that broke it. `run_inline` ran a caller's source: Python as a subprocess
on the host with the user's privileges and a live Resolve handle, or Lua inside
Resolve's Fusion engine with `os` and `io` in scope, so `os.execute` reached the
shell. `execute` ran an installed script, and `install` accepted caller source,
so the two together did the same. Neither passed any gate — the classifier did
not recognise them and `script_plugin` carried no `@_destructive_op` — so safe
mode let arbitrary code through as a read. v3.0.0 removed both. These tests keep
them removed.

Installing a script is still supported, and still gated: Resolve runs it when
the user clicks it in Workspace > Scripts. That is the user's action, not this
server's.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]


class RemovedActionsTest(unittest.TestCase):
    def test_removed_actions_refuse_with_a_migration_pointer(self) -> None:
        """A caller written against v2.x must learn what replaced the action,
        not just that it is unknown."""
        from src import server

        for action, params in (
            ("run_inline", {"source": "print(1)", "language": "py"}),
            ("run_inline", {"source": "return 1", "language": "lua"}),
            ("execute", {"name": "x", "category": "Utility", "language": "py"}),
        ):
            with self.subTest(action=action, language=params.get("language")):
                result = server.script_plugin(action, params)
                message = json.dumps(result)
                self.assertIn("removed in v3.0.0", message, result)
                self.assertIn("Workspace > Scripts", message, result)
                self.assertNotIn("success\": true", message, result)

    def test_removed_actions_are_not_advertised(self) -> None:
        """The unknown-action error is what agents read to recover from a typo;
        advertising a removed action there would invite the call back."""
        from src import server

        message = json.dumps(server.script_plugin("no_such_action", {}))
        self.assertNotIn("run_inline", message)
        self.assertNotIn('"execute"', message)

    def test_the_lifecycle_probe_refuses_execute_before_any_side_effect(self) -> None:
        """Silently ignoring `execute` would report a probe as complete for a
        step it never ran. It must refuse before generating or installing."""
        from src import server

        with mock.patch.object(server, "script_plugin") as dispatch:
            result = server._probe_script_lifecycle(
                {"install": True, "execute": True, "cleanup": True}
            )
        self.assertIn("removed in v3.0.0", json.dumps(result), result)
        dispatch.assert_not_called()


class NoExecutionPrimitivesTest(unittest.TestCase):
    #: Calls that run code handed to them. `Execute`/`RunScript` are Fusion's
    #: string/file execution entry points; `exec`/`eval` are Python's own.
    FORBIDDEN_METHODS = {"RunScript", "Execute"}
    FORBIDDEN_BUILTINS = {"exec", "eval"}
    REMOVED_HELPERS = {
        "_run_inline_python", "_run_inline_lua", "_execute_python_script",
        "_execute_lua_script", "_python_env_for_resolve", "_PY_SCRIPT_EXIT_GUARD",
    }

    def test_no_code_execution_primitive_is_called_anywhere_in_src(self) -> None:
        offenders = []
        for path in sorted((REPO_ROOT / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            rel = path.relative_to(REPO_ROOT).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in self.FORBIDDEN_METHODS:
                    offenders.append(f"{rel}:{node.lineno} .{func.attr}()")
                elif isinstance(func, ast.Name) and func.id in self.FORBIDDEN_BUILTINS:
                    offenders.append(f"{rel}:{node.lineno} {func.id}()")
        self.assertEqual(offenders, [], "the server must not execute caller-supplied code")

    def test_the_removed_executors_stay_removed(self) -> None:
        tree = ast.parse((REPO_ROOT / "src" / "server.py").read_text(encoding="utf-8"))
        defined = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                defined.update(t.id for t in node.targets if isinstance(t, ast.Name))
        self.assertEqual(defined & self.REMOVED_HELPERS, set())


if __name__ == "__main__":
    unittest.main()
