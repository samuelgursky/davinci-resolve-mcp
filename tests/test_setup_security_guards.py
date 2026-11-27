"""GHSA-3rvw-8897-xq63: `setup` could point the audit log at a shell startup
file and switch every guard off.

The audit and operation logs append caller params verbatim, so a log path the
caller controls is a write primitive (a `"$(cmd)"` line in ~/.bashrc runs at
the next shell). And `set_defaults` is not behind `@_destructive_op`, so it is
also the one place that can drop safe mode, the confirm token and the audit
trail for every later call. These tests pin both halves shut.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from src.utils.mcp_import_stubs import install_mcp_stubs

install_mcp_stubs()

import src.server as server  # noqa: E402
from src.utils import destructive_hook, log_paths, operation_log, update_check  # noqa: E402


class _Sandbox(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.prefs = os.path.join(self.tmp.name, "prefs.json")
        self.env = mock.patch.dict(os.environ, {
            "DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS": self.prefs,
            update_check.ENV_STATE_PATH: os.path.join(self.tmp.name, "update-state.json"),
        })
        self.env.start()
        os.environ.pop("RESOLVE_MCP_AUDIT_LOG_FILE", None)
        os.environ.pop("RESOLVE_MCP_OPERATION_LOG_FILE", None)

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def _prefs_on_disk(self):
        if not os.path.exists(self.prefs):
            return {}
        with open(self.prefs, encoding="utf-8") as fh:
            return json.load(fh)

    def _write_prefs(self, data) -> None:
        with open(self.prefs, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def assertRefused(self, result, code) -> None:
        self.assertIsInstance(result.get("error"), dict, result)
        self.assertEqual(result["error"].get("code"), code, result)


class LogPathConfinement(_Sandbox):
    def test_reporter_poc_shell_rc_is_refused(self) -> None:
        fake_rc = os.path.join(self.tmp.name, "fake_bashrc")
        for key in ("audit_log_path", "operation_log_path"):
            with self.subTest(key=key):
                result = server.setup("set_defaults", {"destructive": {key: fake_rc}})
                self.assertRefused(result, "LOG_PATH_NOT_ALLOWED")
        self.assertEqual(self._prefs_on_disk(), {})

    def test_paths_outside_the_allowed_roots_or_suffixes_are_refused(self) -> None:
        home_jsonl = os.path.join(os.path.expanduser("~"), "mcp-audit-probe.jsonl")
        for bad in (os.path.expanduser("~/.bashrc"), os.path.expanduser("~/.zshrc"), home_jsonl,
                    os.path.join(self.tmp.name, "x.sh"), os.path.join(self.tmp.name, "x.jsonl.sh"),
                    self.tmp.name, "", 42):
            with self.subTest(path=bad):
                self.assertIsNotNone(log_paths.log_path_problem(bad))
                if bad != "":  # an empty value means "reset to the default" in setup
                    self.assertRefused(server.setup("set_defaults", {"audit_log_path": bad}), "LOG_PATH_NOT_ALLOWED")
        self.assertFalse(os.path.exists(home_jsonl))

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_a_symlinked_log_is_refused_and_never_followed(self) -> None:
        victim = os.path.join(self.tmp.name, "victim.txt")
        with open(victim, "w", encoding="utf-8") as fh:
            fh.write("original\n")
        link = os.path.join(self.tmp.name, "audit.jsonl")
        os.symlink(victim, link)
        self.assertRefused(server.setup("set_defaults", {"audit_log_path": link}), "LOG_PATH_NOT_ALLOWED")
        with self.assertRaises(OSError):
            log_paths.append_line(link, "{}\n")
        with open(victim, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "original\n")

    def test_temp_and_server_log_dir_paths_are_accepted(self) -> None:
        good = os.path.join(self.tmp.name, "security-audit.jsonl")
        result = server.setup("set_defaults", {"audit_log_path": good})
        self.assertNotIn("error", result, result)
        self.assertEqual(self._prefs_on_disk()["destructive"]["audit_log_path"], os.path.realpath(good))
        self.assertIsNone(log_paths.log_path_problem(os.path.join(log_paths.server_log_dir(), "x.log")))

    def test_a_poisoned_preference_from_an_older_version_is_ignored(self) -> None:
        fake_rc = os.path.expanduser("~/.bashrc")
        values = {"destructive.audit_log": True, "destructive.audit_log_path": fake_rc,
                  "destructive.operation_log": True, "destructive.operation_log_path": fake_rc}
        saved = (destructive_hook._PREFERENCE_PROVIDER, operation_log._PREFERENCE_PROVIDER)
        destructive_hook.register_preference_provider(values.get)
        operation_log.register_preference_provider(values.get)
        # offline_guard swaps the path functions for temp redirects; test the real ones.
        try:
            audit = _real(destructive_hook, "_audit_log_path")()
            op = _real(operation_log, "operation_log_path")()
        finally:
            destructive_hook._PREFERENCE_PROVIDER, operation_log._PREFERENCE_PROVIDER = saved
        self.assertEqual(audit, os.path.join(log_paths.server_log_dir(), "security-audit.jsonl"))
        self.assertTrue(op.endswith(os.path.join("logs", "operation-log.jsonl")), op)

    def test_the_operator_environment_can_still_send_logs_anywhere(self) -> None:
        target = os.path.join(self.tmp.name, "elsewhere", "audit.out")
        with mock.patch.dict(os.environ, {"RESOLVE_MCP_AUDIT_LOG_FILE": target}):
            self.assertEqual(_real(destructive_hook, "_audit_log_path")(), os.path.realpath(target))


def _real(module, name):
    """The original function, even while tests/offline_guard has it redirected."""
    from tests import offline_guard
    return offline_guard._originals.get(name) or getattr(module, name)


class SecuritySettingsAreOperatorOnlyToLower(_Sandbox):
    LOWERING = {
        "safe_mode": {"safe_mode": False},
        "require_confirm_token": {"confirm_token": False},
        "audit_log": {"audit_log": "no"},
        "operation_log": {"destructive": {"operationLog": False}},
    }

    def _turn_everything_on(self) -> None:
        self._write_prefs({"destructive": {"safe_mode": True, "require_confirm_token": True,
                                           "audit_log": True, "operation_log": True}})

    def test_each_guard_can_be_switched_on_but_not_off(self) -> None:
        self.assertNotIn("error", server.setup("set_defaults", {"safe_mode": True}))
        self._turn_everything_on()
        before = self._prefs_on_disk()
        for key, params in self.LOWERING.items():
            with self.subTest(key=key):
                self.assertRefused(server.setup("set_defaults", params), "SECURITY_SETTING_OPERATOR_ONLY")
                self.assertRefused(server.setup("set_defaults", {**params, "dry_run": True}),
                                   "SECURITY_SETTING_OPERATOR_ONLY")
        self.assertEqual(self._prefs_on_disk(), before)

    def test_a_refused_call_changes_no_other_section(self) -> None:
        self._turn_everything_on()
        before = self._prefs_on_disk()
        result = server.setup("set_defaults", {"result_envelope": "pure", "safe_mode": False,
                                               "audit_log_path": os.path.join(self.tmp.name, "a.jsonl")})
        self.assertRefused(result, "SECURITY_SETTING_OPERATOR_ONLY")
        self.assertEqual(self._prefs_on_disk(), before)

    def test_clearing_safe_mode_is_refused_and_a_full_reset_keeps_it_on(self) -> None:
        self._turn_everything_on()
        for params in ({"destructive": {"safe_mode": "clear"}}, {"safe_mode": None}):
            with self.subTest(params=params):
                self.assertRefused(server.setup("set_defaults", params), "SECURITY_SETTING_OPERATOR_ONLY")
        self.assertRefused(server.setup("clear_defaults", {"keys": ["destructive.safe_mode"]}),
                           "SECURITY_SETTING_OPERATOR_ONLY")
        reset = server.setup("clear_defaults", {"keys": "destructive"})
        self.assertNotIn("error", reset, reset)
        self.assertEqual(reset.get("kept"), ["destructive.safe_mode"])
        self.assertTrue(self._prefs_on_disk()["destructive"]["safe_mode"])

    def test_automatic_updates_cannot_be_switched_on_from_mcp(self) -> None:
        for params in ({"update_mode": "auto"}, {"updates": {"mode": "auto-update"}}):
            with self.subTest(params=params):
                self.assertRefused(server.setup("set_defaults", params), "SECURITY_SETTING_OPERATOR_ONLY")
        self.assertNotEqual(update_check.get_update_mode(server.project_dir, server._setup_update_env()), "auto")
        self.assertNotIn("error", server.setup("set_defaults", {"update_mode": "notify"}))

    def test_the_audited_carrier_call_never_reaches_a_refused_path(self) -> None:
        """End-to-end form of the report: the path is refused, so a later
        audited call cannot land a `$(...)` line in the fake rc file."""
        fake_rc = os.path.join(self.tmp.name, "fake_bashrc")
        server.setup("set_defaults", {"destructive": {"audit_log_path": fake_rc}})
        destructive_hook._audit_security_event(
            operation_id="op", tool_name="fuse_plugin", action="install", risk_level="medium",
            status="allowed", params={"note": "$(touch PWNED)"})
        self.assertFalse(os.path.exists(fake_rc))


if __name__ == "__main__":
    unittest.main()
