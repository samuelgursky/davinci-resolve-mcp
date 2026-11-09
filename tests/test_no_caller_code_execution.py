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


_HOOK_SPEC = {
    "project": "MCP_QA_spec_hooks",
    "hooks": {"before": [{"name": "pre", "command": "bash -c 'touch /tmp/owned'"}],
              "after": ["echo after"]},
}


class _FakeExecutor:
    """Stands in for _SpecLiveExecutor: every write succeeds, nothing is live."""

    def __init__(self, *_a, **_k):
        pass

    def live_state(self):
        return {"project": "MCP_QA_spec_hooks", "settings": {}, "timelines": []}

    def ensure_project(self, _name):
        return True

    def __getattr__(self, _name):
        return lambda *a, **k: True


class SpecHooksAreNotRunByTheServerTest(unittest.TestCase):
    """GHSA-x2fm-g3cm-6x5w. `apply_spec` used to run each hook in the spec as a
    command line when the same caller set `run_hooks: true`, and it was missing
    from the destructive registry, so safe mode and the audit log never saw it.
    A spec is caller data, so its hooks are caller-supplied code."""

    def test_run_hooks_is_refused_before_the_spec_is_read_or_resolve_touched(self) -> None:
        from src import server

        pm = mock.Mock()
        for flag in (True, "true", 1):
            with self.subTest(run_hooks=flag), \
                 mock.patch("subprocess.run") as run, \
                 mock.patch.object(server, "_make_spec_hook_runner") as runner, \
                 mock.patch.object(server, "_SpecLiveExecutor") as executor, \
                 mock.patch.object(server._project_spec, "load_spec") as load:
                result = server._spec_action(
                    mock.Mock(), pm, "apply_spec",
                    {"spec": _HOOK_SPEC, "spec_path": "/x/project.dvr.yaml", "run_hooks": flag},
                )
                self.assertFalse(result.get("success"), result)
                self.assertEqual(result["error"]["code"], "SPEC_HOOKS_NOT_RUN", result)
                self.assertIn("caller-supplied code", result["error"]["message"])
                run.assert_not_called()
                runner.assert_not_called()
                executor.assert_not_called()
                load.assert_not_called()
        pm.assert_not_called()

    def test_the_tool_entry_point_refuses_too(self) -> None:
        """The decorated tool, not just the helper: this is the call an agent makes."""
        from src import server

        with mock.patch.object(server, "get_resolve", return_value=mock.Mock()), \
             mock.patch("subprocess.run") as run, \
             mock.patch.object(server, "_SpecLiveExecutor") as executor:
            result = server.project_manager("apply_spec", {"spec": _HOOK_SPEC, "run_hooks": True})
        self.assertIn("SPEC_HOOKS_NOT_RUN", json.dumps(result), result)
        run.assert_not_called()
        executor.assert_not_called()

    def test_without_run_hooks_the_hooks_are_reported_not_run(self) -> None:
        from src import server

        with mock.patch("subprocess.run") as run, \
             mock.patch.object(server, "_SpecLiveExecutor", _FakeExecutor):
            result = server._spec_action(mock.Mock(), mock.Mock(), "apply_spec", {"spec": _HOOK_SPEC})
        self.assertTrue(result.get("success"), result)
        self.assertEqual([h["name"] or h["command"] for h in result["hooks_not_run"]], ["pre", "echo after"])
        run.assert_not_called()

    def test_the_terminal_cli_still_runs_hooks_it_was_told_to(self) -> None:
        """`batch apply --run-hooks` is the person at the keyboard choosing a spec
        file and typing the flag; that path keeps working."""
        from src import batch_cli, server

        ran = []
        with mock.patch.object(server, "get_resolve", return_value=mock.Mock()), \
             mock.patch.object(server, "_SpecLiveExecutor", _FakeExecutor), \
             mock.patch.object(server, "_make_spec_hook_runner",
                               return_value=lambda h: ran.append(h.command) or True), \
             mock.patch.object(server._project_spec, "load_spec",
                               return_value=server._project_spec.spec_from_dict(_HOOK_SPEC)):
            result = batch_cli._run_spec_action("apply_spec", {"spec_path": "x.yaml", "run_hooks": True})
        self.assertTrue(result.get("success"), result)
        self.assertEqual(ran, ["bash -c 'touch /tmp/owned'", "echo after"])
        self.assertNotIn("hooks_not_run", result)

    def test_only_the_terminal_cli_may_allow_hooks(self) -> None:
        """A second caller passing allow_hooks=True would reopen the hole."""
        allowed = []
        for path in sorted((REPO_ROOT / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and any(
                    kw.arg == "allow_hooks" and not (
                        isinstance(kw.value, ast.Constant) and kw.value.value is False)
                    for kw in node.keywords
                ):
                    allowed.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(allowed, ["src/batch_cli.py"])

    def test_apply_spec_is_gated_and_rated(self) -> None:
        from src.utils import destructive_hook
        from src.utils.execution_lifecycle import classify_operation_risk

        self.assertIn("apply_spec", destructive_hook.DESTRUCTIVE_ACTIONS_BY_TOOL["project_manager"])
        risk = classify_operation_risk("project_manager", "apply_spec").to_dict()
        self.assertTrue(risk["recognised"], risk)
        self.assertEqual(risk["level"], "medium", risk)


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
