"""Unit tests for action-filtering and strict-mode behavior in destructive_hook.

No Resolve required.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from src.utils import destructive_hook
from src.utils.execution_lifecycle import classify_operation_risk, inspect_operation

_SERVER_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "server.py")
_PARAM_NAMES = frozenset({"p", "params"})
_DRY_RUN_KEYS = ("dry_run", "dryRun")


def _scan_native_dry_run_actions() -> set:
    """Registered destructive actions whose handler branch reaches a dry_run
    read with the caller's params flowing into it (see the drift test)."""
    import ast

    with open(_SERVER_PY, encoding="utf-8") as handle:
        src = handle.read()
    tree = ast.parse(src)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def reads_dry_run(nodes) -> bool:
        return any(
            isinstance(c, ast.Constant) and c.value in _DRY_RUN_KEYS
            for n in nodes for c in ast.walk(n)
        )

    def passes_params(call: ast.Call) -> bool:
        for a in list(call.args) + [k.value for k in call.keywords]:
            if isinstance(a, ast.Name) and a.id in _PARAM_NAMES:
                return True
            if isinstance(a, ast.Dict):
                for k, v in zip(a.keys, a.values):
                    if k is None and isinstance(v, ast.Name) and v.id in _PARAM_NAMES:
                        return True  # {**p, ...}
                    if isinstance(k, ast.Constant) and k.value in _DRY_RUN_KEYS:
                        return True
            if (isinstance(a, ast.Call) and getattr(a.func, "id", "") == "dict"
                    and any(isinstance(x, ast.Name) and x.id in _PARAM_NAMES for x in a.args)):
                return True
        return False

    def reaches(nodes, depth=0, seen=None) -> bool:
        seen = set() if seen is None else seen
        if reads_dry_run(nodes):
            return True
        if depth >= 4:
            return False
        for n in nodes:
            for c in ast.walk(n):
                if isinstance(c, ast.Call):
                    name = getattr(c.func, "id", None)
                    if name in funcs and name not in seen and passes_params(c):
                        seen.add(name)
                        if reaches([funcs[name]], depth + 1, seen):
                            return True
        return False

    def action_branches(fn: ast.FunctionDef) -> dict:
        out: dict = {}

        def walk(stmts):
            for s in stmts:
                if isinstance(s, ast.If):
                    names = []
                    for cmp in ast.walk(s.test):
                        if (isinstance(cmp, ast.Compare) and isinstance(cmp.left, ast.Name)
                                and cmp.left.id == "action"):
                            for c in cmp.comparators:
                                if isinstance(c, ast.Constant):
                                    names.append(c.value)
                                elif isinstance(c, (ast.Tuple, ast.Set, ast.List)):
                                    names += [e.value for e in c.elts if isinstance(e, ast.Constant)]
                    for n in names:
                        out.setdefault(n, []).extend(s.body)
                    walk(s.body)
                    walk(s.orelse)
                elif hasattr(s, "body") and not isinstance(s, ast.FunctionDef):
                    walk(s.body)

        walk(fn.body)
        return out

    handlers = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "_destructive_op":
                    handlers[d.args[0].value] = node
    found = set()
    for tool, actions in destructive_hook.DESTRUCTIVE_ACTIONS_BY_TOOL.items():
        branches = action_branches(handlers[tool]) if tool in handlers else {}
        for action in actions:
            if reaches(branches.get(action, [])):
                found.add((tool, action))
    return found


class ActionFiltering(unittest.TestCase):
    """is_destructive() consults both the registry AND the no-archive filter."""

    def test_unregistered_action_is_not_destructive(self) -> None:
        self.assertFalse(destructive_hook.is_destructive("timeline", "get_current"))

    def test_registered_action_is_destructive_by_default(self) -> None:
        self.assertTrue(destructive_hook.is_destructive("timeline", "delete_clips"))

    def test_timeline_rename_does_not_archive(self) -> None:
        # Issue #83: renaming a timeline is content-preserving, so it must NOT
        # trigger version-on-mutate (renames were spawning redundant _archived
        # copies, and renaming an archive archived the archive).
        self.assertFalse(
            destructive_hook.is_destructive("timeline", "set_name", {"name": "New Name"})
        )
        # A content-changing timeline edit still archives.
        self.assertTrue(destructive_hook.is_destructive("timeline", "add_track"))

    def test_no_archive_filter_skips_notes_set_property(self) -> None:
        # set_property with key=Notes shouldn't trigger versioning…
        self.assertFalse(destructive_hook.is_destructive(
            "timeline_item", "set_property", {"key": "Notes", "value": "free text"},
        ))
        # …but the same action with key=Name should.
        self.assertTrue(destructive_hook.is_destructive(
            "timeline_item", "set_property", {"key": "Name", "value": "renamed"},
        ))

    def test_no_archive_filter_only_applies_to_registered_keys(self) -> None:
        # Comments isn't in the timeline_item filter set so it does archive.
        self.assertTrue(destructive_hook.is_destructive(
            "timeline_item", "set_property", {"key": "Comments", "value": "x"},
        ))

    def test_set_clip_property_on_timeline_filters_notes_and_comments(self) -> None:
        for key in ("Notes", "Comments"):
            self.assertFalse(
                destructive_hook.is_destructive(
                    "timeline", "set_clip_property", {"key": key, "value": "x"},
                ),
                msg=f"key={key} should be filtered out",
            )

    def test_missing_key_param_falls_through_to_archiving(self) -> None:
        # set_property without key (malformed) should still archive — defaulting
        # to safety, not silently skipping versioning.
        self.assertTrue(destructive_hook.is_destructive(
            "timeline_item", "set_property", {"value": "x"},
        ))


class StrictMode(unittest.TestCase):
    """is_strict_required() flips on for catastrophic ops and explicit opt-in."""

    def test_explicit_strict_param_wins(self) -> None:
        self.assertTrue(destructive_hook.is_strict_required(
            "timeline", "delete_clips", {"strict": True},
        ))

    def test_strict_default_actions(self) -> None:
        self.assertTrue(destructive_hook.is_strict_required(
            "timeline", "delete_track", None,
        ))
        # EX-REG: delete_timelines is a media_pool action now; it is archive +
        # confirm-token gated (EX3) rather than strict.
        self.assertFalse(destructive_hook.is_strict_required(
            "timeline", "delete_timelines", None,
        ))

    def test_ripple_delete_is_strict(self) -> None:
        self.assertTrue(destructive_hook.is_strict_required(
            "timeline", "delete_clips", {"ripple": True, "clip_ids": ["a"]},
        ))
        # Non-ripple delete isn't strict by default.
        self.assertFalse(destructive_hook.is_strict_required(
            "timeline", "delete_clips", {"ripple": False, "clip_ids": ["a"]},
        ))

    def test_routine_action_is_not_strict(self) -> None:
        self.assertFalse(destructive_hook.is_strict_required(
            "timeline_item", "set_property", {"key": "Name", "value": "x"},
        ))


class SecurityPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_provider = destructive_hook._PROVIDER
        self.saved_pref_provider = destructive_hook._PREFERENCE_PROVIDER
        self.saved_pending_check = destructive_hook._PENDING_CONFIRM_CHECK
        self.tmp = tempfile.TemporaryDirectory()
        self.audit_path = os.path.join(self.tmp.name, "security-audit.jsonl")

    def tearDown(self) -> None:
        destructive_hook._PROVIDER = self.saved_provider
        destructive_hook._PREFERENCE_PROVIDER = self.saved_pref_provider
        destructive_hook._PENDING_CONFIRM_CHECK = self.saved_pending_check
        self.tmp.cleanup()

    def _prefs(self, *, safe_mode: bool = False):
        def provider(key: str):
            values = {
                "destructive.safe_mode": safe_mode,
                "destructive.audit_log": True,
                "destructive.audit_log_path": self.audit_path,
            }
            return values.get(key)
        destructive_hook.register_preference_provider(provider)

    def _audit_events(self):
        with open(self.audit_path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_risk_level_classifier_names_low_medium_and_high(self) -> None:
        self.assertEqual(
            destructive_hook.risk_level_for_action("timeline_markers", "add", {}),
            "low",
        )
        self.assertEqual(
            destructive_hook.risk_level_for_action("timeline_item", "set_property", {}),
            "medium",
        )
        self.assertEqual(
            destructive_hook.risk_level_for_action("timeline", "delete_track", {}),
            "high",
        )
        self.assertEqual(
            destructive_hook.risk_level_for_action("media_pool", "delete_clips", {}),
            "critical",
        )
        self.assertEqual(
            destructive_hook.risk_level_for_action("timeline", "delete_clips", {"ripple": True}),
            "high",
        )

    def test_risk_level_comes_from_the_lifecycle_classifier(self) -> None:
        """One classifier, not two.

        A second risk table inside destructive_hook would let the safe-mode gate
        and `inspect_operation` report different levels for the same call — the
        gate refusing what pre-flight inspection had just called reversible.
        """
        for tool, action, params in (
            ("timeline_markers", "add", {}),
            ("timeline", "delete_track", {}),
            ("media_pool", "delete_clips", {}),
            ("timeline", "delete_clips", {"ripple": True}),
            ("timeline_item", "set_property", {}),
            ("timeline_item", "update_sidecar", {}),
        ):
            with self.subTest(action=f"{tool}.{action}"):
                self.assertEqual(
                    destructive_hook.risk_level_for_action(tool, action, params),
                    classify_operation_risk(tool, action, params).level.value,
                )

    def test_unclassified_destructive_actions_report_risk_as_unestablished(self) -> None:
        """`medium` from the name heuristic is a default, not a finding.

        Every registered action is rated now, so this uses a deliberately
        unrated one: the reporting path still has to work for the next action
        somebody registers before rating it, and safe mode still must not block
        on a default it did not actually assess. Using a real action here would
        make the test fail the day that action gets classified, which is how the
        earlier version of it broke.
        """
        self._prefs(safe_mode=True)
        destructive_hook.register_project_root_provider(lambda: None)
        destructive_hook.register_pending_confirm_check(lambda *_args: False)

        unrated = "zz_synthetic_unrated_action"
        self.assertFalse(
            classify_operation_risk("timeline", unrated, {}).recognised,
            "fixture action must be unrated for this test to mean anything",
        )

        @destructive_hook.destructive_op("timeline")
        def fake_timeline(action: str, params=None):
            return {"success": True}

        with mock.patch.object(
            destructive_hook, "is_destructive", lambda *_a, **_k: True
        ):
            result = fake_timeline(unrated, {"trackType": "video"})

        self.assertTrue(result["success"])
        self.assertEqual(result["security"]["risk_level"], "medium")
        self.assertFalse(result["security"]["risk_established"])
        [event] = self._audit_events()
        self.assertEqual(event["status"], "allowed")
        self.assertFalse(event["risk_established"])

    def test_classified_actions_report_risk_as_established(self) -> None:
        self._prefs(safe_mode=False)
        destructive_hook.register_project_root_provider(lambda: None)
        destructive_hook.register_pending_confirm_check(lambda *_args: False)

        @destructive_hook.destructive_op("timeline_markers")
        def fake_markers(action: str, params=None):
            return {"success": True}

        result = fake_markers("add", {"frame": 3})
        self.assertTrue(result["security"]["risk_established"])

    def test_safe_mode_blocks_high_risk_before_handler_runs(self) -> None:
        self._prefs(safe_mode=True)
        destructive_hook.register_project_root_provider(lambda: None)
        calls: list[str] = []

        @destructive_hook.destructive_op("timeline")
        def fake_timeline(action: str, params=None):
            calls.append(action)
            return {"success": True}

        result = fake_timeline("delete_track", {"confirm_token": "secret"})

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SAFE_MODE_BLOCKED")
        self.assertEqual(result["security"]["risk_level"], "high")
        self.assertEqual(calls, [])
        [event] = self._audit_events()
        self.assertEqual(event["status"], "blocked")
        self.assertEqual(event["reason"], "safe_mode")
        self.assertEqual(event["params"]["confirm_token"], "<redacted>")

    def test_safe_mode_allows_low_risk_and_audits(self) -> None:
        self._prefs(safe_mode=True)
        destructive_hook.register_project_root_provider(lambda: None)
        destructive_hook.register_pending_confirm_check(lambda *_args: False)

        @destructive_hook.destructive_op("timeline_markers")
        def fake_markers(action: str, params=None):
            return {"success": True, "added": 1}

        result = fake_markers("add", {"frame": 12})

        self.assertTrue(result["success"])
        self.assertEqual(result["security"]["risk_level"], "low")
        [event] = self._audit_events()
        self.assertEqual(event["status"], "allowed")
        self.assertEqual(event["risk_level"], "low")

    def test_high_risk_can_be_explicitly_allowed_in_safe_mode(self) -> None:
        self._prefs(safe_mode=True)
        destructive_hook.register_project_root_provider(lambda: None)
        calls: list[str] = []

        @destructive_hook.destructive_op("media_pool")
        def fake_media_pool(action: str, params=None):
            calls.append(action)
            return {"success": True}

        result = fake_media_pool(
            "delete_clips",
            {"confirm_token": "secret", "allow_risky_operation": True},
        )

        self.assertTrue(result["success"])
        self.assertEqual(calls, ["delete_clips"])
        self.assertEqual(result["security"]["risk_level"], "critical")
        [event] = self._audit_events()
        self.assertEqual(event["status"], "allowed")

    def test_safe_mode_blocks_broad_raw_graph_lut_mutations(self) -> None:
        self._prefs(safe_mode=True)
        destructive_hook.register_project_root_provider(lambda: None)

        for action, params in (
            ("set_lut", {"node_index": 1, "lut_path": "look.cube"}),
            ("apply_arri_cdl_lut", {}),
            ("set_lut", {"node_index": 1, "lut_path": "look.cube", "source": "color_group_pre"}),
            ("apply_arri_cdl_lut", {"source": "color_group_post"}),
        ):
            calls: list[str] = []

            @destructive_hook.destructive_op("graph")
            def fake_graph(action: str, params=None):
                calls.append(action)
                return {"success": True}

            with self.subTest(action=action):
                result = fake_graph(action, params)
                self.assertFalse(result["success"])
                self.assertEqual(result["error"]["code"], "SAFE_MODE_BLOCKED")
                self.assertEqual(result["security"]["risk_level"], "high")
                self.assertEqual(calls, [])

    def test_safe_mode_allows_item_scoped_raw_graph_lut_mutations(self) -> None:
        self._prefs(safe_mode=True)
        destructive_hook.register_project_root_provider(lambda: None)

        for action, params in (
            ("set_lut", {"node_index": 1, "lut_path": "look.cube", "source": "item"}),
            ("apply_arri_cdl_lut", {"source": "item"}),
        ):
            calls: list[str] = []

            @destructive_hook.destructive_op("graph")
            def fake_graph(action: str, params=None):
                calls.append(action)
                return {"success": True}

            with self.subTest(action=action):
                result = fake_graph(action, params)
                self.assertTrue(result["success"])
                self.assertEqual(result["security"]["risk_level"], "medium")
                self.assertEqual(calls, [action])

    # ── dry_run on actions without a native dry-run path ──────────────────
    #
    # Before v2.211.0 `timeline_markers.add` with dry_run=true added a real
    # marker: the handler never read the flag. The wrapper now refuses an
    # explicit dry-run request on every registered destructive action outside
    # NATIVE_DRY_RUN_ACTIONS — before archive, before state lookup, before the
    # handler — and says that nothing was simulated or executed.

    def test_dry_run_on_action_without_native_support_refuses_before_handler(self) -> None:
        self._prefs(safe_mode=False)

        def failing_provider():
            raise AssertionError("dry-run refusal must not resolve project state")
        destructive_hook.register_project_root_provider(failing_provider)

        calls: list[str] = []

        @destructive_hook.destructive_op("timeline_markers")
        def fake_markers(action: str, params=None):
            calls.append(action)
            return {"success": True}

        result = fake_markers("add", {"frame": 12, "dry_run": True})

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "dry_run_unavailable")
        self.assertEqual(result["error"]["code"], "DRY_RUN_UNAVAILABLE")
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["simulated"])
        self.assertFalse(result["executed"])
        self.assertEqual(result["security"]["policy"], "destructive.dry_run_support")
        self.assertEqual(result["security"]["risk_level"], "low")
        self.assertEqual(calls, [])
        [event] = self._audit_events()
        self.assertEqual(event["status"], "blocked")
        self.assertEqual(event["reason"], "dry_run_unavailable")

    def test_every_registered_destructive_action_without_native_dry_run_refuses(self) -> None:
        """The allowlist is the ONLY way through: no denylist to fall behind."""
        self._prefs(safe_mode=False)
        destructive_hook.register_project_root_provider(lambda: None)
        executed: list[tuple[str, str]] = []
        for tool, actions in sorted(destructive_hook.DESTRUCTIVE_ACTIONS_BY_TOOL.items()):
            @destructive_hook.destructive_op(tool)
            def fake(action: str, params=None, _tool=tool):
                executed.append((_tool, action))
                return {"success": True}
            for action in sorted(actions):
                if (tool, action) in destructive_hook.NATIVE_DRY_RUN_ACTIONS:
                    continue
                result = fake(action, {"dry_run": True})
                self.assertEqual(
                    result.get("error", {}).get("code"), "DRY_RUN_UNAVAILABLE",
                    f"{tool}.{action} with dry_run=true reached its handler: {result}",
                )
        self.assertEqual(executed, [])

    def test_native_dry_run_still_reaches_handler(self) -> None:
        self._prefs(safe_mode=False)
        destructive_hook.register_project_root_provider(lambda: None)
        calls: list[str] = []

        @destructive_hook.destructive_op("timeline")
        def fake_timeline(action: str, params=None):
            calls.append(action)
            return {"success": True, "dry_run": True, "plan": []}

        result = fake_timeline("apply_cuts", {"cuts": [], "dry_run": True})

        self.assertTrue(result["success"])
        self.assertTrue(result["dry_run"])
        self.assertNotIn("simulated", result)
        self.assertEqual(calls, ["apply_cuts"])

    def test_dry_run_false_is_not_a_dry_run_request(self) -> None:
        self._prefs(safe_mode=False)
        destructive_hook.register_project_root_provider(lambda: None)
        calls: list[str] = []

        @destructive_hook.destructive_op("timeline_markers")
        def fake_markers(action: str, params=None):
            calls.append(action)
            return {"success": True}

        result = fake_markers("add", {"frame": 12, "dry_run": False})
        self.assertTrue(result["success"])
        self.assertEqual(calls, ["add"])

    def test_dry_run_on_a_non_destructive_action_is_untouched(self) -> None:
        self._prefs(safe_mode=False)
        calls: list[str] = []

        @destructive_hook.destructive_op("timeline")
        def fake_timeline(action: str, params=None):
            calls.append(action)
            return {"success": True, "items": []}

        result = fake_timeline("get_current", {"dry_run": True})
        self.assertTrue(result["success"])
        self.assertEqual(calls, ["get_current"])

    def test_no_archive_filtered_payload_still_refuses_dry_run(self) -> None:
        """A Notes edit is filtered out of archiving, not out of the registry —
        with dry_run=true it must refuse rather than execute for real."""
        self._prefs(safe_mode=False)
        calls: list[str] = []

        @destructive_hook.destructive_op("timeline_item")
        def fake_item(action: str, params=None):
            calls.append(action)
            return {"success": True}

        result = fake_item("set_property", {"key": "Notes", "value": "x", "dry_run": True})
        self.assertEqual(result["error"]["code"], "DRY_RUN_UNAVAILABLE")
        self.assertEqual(calls, [])


class WrapperWithProvider(unittest.TestCase):
    """End-to-end: install a synthetic provider and verify the wrapper paths."""

    def setUp(self) -> None:
        self.saved_provider = destructive_hook._PROVIDER

    def tearDown(self) -> None:
        destructive_hook._PROVIDER = self.saved_provider

    def test_strict_refuses_when_provider_returns_none(self) -> None:
        destructive_hook.register_project_root_provider(lambda: None)

        calls: list[str] = []

        @destructive_hook.destructive_op("timeline")
        def fake_timeline(action: str, params=None):
            calls.append(action)
            return {"success": True, "called_through": True}

        # delete_track is strict-default; pass a confirm_token so the pending-confirm
        # gate (delete_track is also token-gated) doesn't pre-empt the archive/strict
        # path we're exercising here.
        result = fake_timeline("delete_track", {"confirm_token": "x"})  # strict-default action
        self.assertFalse(result["success"])
        self.assertIn("strict mode", (result["error"].get("message","") if isinstance(result["error"], dict) else result["error"]))
        self.assertEqual(calls, [], msg="underlying handler should NOT have been called")

    def test_non_strict_runs_handler_when_provider_returns_none(self) -> None:
        destructive_hook.register_project_root_provider(lambda: None)

        calls: list[str] = []

        @destructive_hook.destructive_op("timeline")
        def fake_timeline(action: str, params=None):
            calls.append(action)
            return {"success": True, "called_through": True}

        # A routine destructive op (not in STRICT_DEFAULT_ACTIONS) — should run.
        result = fake_timeline("set_clip_color", {"clip_id": "x", "color": "Red"})
        self.assertTrue(result["called_through"])
        self.assertEqual(calls, ["set_clip_color"])

    def test_filtered_payload_bypasses_versioning(self) -> None:
        # Provider would raise if called — proves the filter short-circuits.
        def failing_provider():
            raise AssertionError("provider should not have been called")
        destructive_hook.register_project_root_provider(failing_provider)

        @destructive_hook.destructive_op("timeline_item")
        def fake_ti(action: str, params=None):
            return {"success": True, "wrote_notes": True}

        result = fake_ti("set_property", {"key": "Notes", "value": "free text"})
        self.assertTrue(result["wrote_notes"])


class PendingConfirmCheckBypassesArchive(unittest.TestCase):
    """F4 — when the underlying handler is about to issue a confirm_token (no
    mutation), the wrapper must skip the archive entirely.
    """

    def setUp(self) -> None:
        self.saved_provider = destructive_hook._PROVIDER
        self.saved_check = destructive_hook._PENDING_CONFIRM_CHECK

    def tearDown(self) -> None:
        destructive_hook._PROVIDER = self.saved_provider
        destructive_hook._PENDING_CONFIRM_CHECK = self.saved_check

    def test_pending_check_skips_archive_and_brain_edit(self) -> None:
        # Provider raises if called — proves the wrapper short-circuited
        # before any archive/brain_edit path.
        def failing_provider():
            raise AssertionError("provider should not have been called")
        destructive_hook.register_project_root_provider(failing_provider)
        destructive_hook.register_pending_confirm_check(
            lambda tool, action, params: action == "reset_all_grades"
            and not (params or {}).get("confirm_token")
        )

        @destructive_hook.destructive_op("graph")
        def fake_graph(action: str, params=None):
            return {"error": {"code": "CONFIRMATION_REQUIRED",
                              "category": "pending_user_decision"},
                    "confirm_token": "abc123"}

        result = fake_graph("reset_all_grades", {})
        self.assertIn("confirm_token", result)
        self.assertEqual(result["_versioning"]["archived"], False)
        self.assertEqual(result["_versioning"]["skipped_reason"], "pending_confirm_token")

    def test_pending_check_does_not_fire_when_token_present(self) -> None:
        # When the consume call comes back with the token, archive must run.
        called = {"provider": False}

        def provider():
            called["provider"] = True
            return None  # non-strict path, OK to short-circuit after this.
        destructive_hook.register_project_root_provider(provider)
        destructive_hook.register_pending_confirm_check(
            lambda tool, action, params: action == "reset_all_grades"
            and not (params or {}).get("confirm_token")
        )

        @destructive_hook.destructive_op("graph")
        def fake_graph(action: str, params=None):
            return {"success": True}

        result = fake_graph("reset_all_grades", {"confirm_token": "abc"})
        self.assertTrue(result["success"])
        self.assertTrue(called["provider"],
                        "archive provider must run on the consume call")


class AutoRunIdleTimeoutPreferenceTest(unittest.TestCase):
    def setUp(self):
        self._orig_pref_provider = destructive_hook._PREFERENCE_PROVIDER

    def tearDown(self):
        destructive_hook._PREFERENCE_PROVIDER = self._orig_pref_provider

    def test_auto_run_honors_idle_timeout_preference(self):
        destructive_hook.register_preference_provider(
            lambda key: 45 if key == "versioning_auto_run_idle_timeout_seconds" else None
        )
        seen = {}

        def fake_ensure(project_root, idle_timeout_seconds):
            seen["timeout"] = idle_timeout_seconds
            return "run-1"

        with mock.patch.object(
            destructive_hook.analysis_runs, "ensure_auto_run_for_destructive", fake_ensure
        ):
            run_id = destructive_hook._extract_analysis_run_id({}, project_root="/tmp/fake-root")

        self.assertEqual(run_id, "run-1")
        self.assertEqual(seen["timeout"], 45.0)

    def test_auto_run_defaults_to_90s_without_preference(self):
        destructive_hook._PREFERENCE_PROVIDER = None
        seen = {}

        def fake_ensure(project_root, idle_timeout_seconds):
            seen["timeout"] = idle_timeout_seconds
            return "run-2"

        with mock.patch.object(
            destructive_hook.analysis_runs, "ensure_auto_run_for_destructive", fake_ensure
        ):
            destructive_hook._extract_analysis_run_id({}, project_root="/tmp/fake-root")

        self.assertEqual(seen["timeout"], 90.0)


class SecurityAuditLogIsolation(unittest.TestCase):
    """The suite must not write into the operator's real audit trail.

    Running the tests once appended 24 fabricated destructive-op records to
    `logs/security-audit.jsonl`; repeated runs accumulated 216. Entries in a
    security log are read as a record of what happened, so synthetic ones are
    not merely untidy — they are indistinguishable from real events at the
    moment someone needs to trust the file. `tests/offline_guard` redirects the
    path for the whole run; this pins that it stays redirected.
    """

    def test_audit_path_is_not_inside_the_repository(self) -> None:
        repo_logs = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
        )
        path = os.path.abspath(destructive_hook._audit_log_path())
        self.assertFalse(
            path.startswith(os.path.abspath(repo_logs)),
            f"suite would write audit records into the real trail at {path}",
        )


class EveryDestructiveActionIsClassified(unittest.TestCase):
    """No registered destructive action may fall through to the name heuristic.

    The heuristic's `else` branch returns MEDIUM with `recognised=False`, which
    is honest but useless to a gate: safe mode blocks established HIGH and
    CRITICAL, so an unrated action is simply not gated. That is how 80 of 108
    actions came to be ungated in v2.209.0 — each was registered as destructive
    without anyone rating it, and nothing failed.

    Registering a destructive action and rating it are now the same commit.
    """

    def test_no_registered_destructive_action_is_unrated(self) -> None:
        unrated = sorted(
            f"{tool}.{action}"
            for tool, actions in destructive_hook.DESTRUCTIVE_ACTIONS_BY_TOOL.items()
            for action in actions
            if not classify_operation_risk(tool, action, {}).recognised
        )
        self.assertEqual(
            unrated,
            [],
            "these destructive actions have no risk rule, so safe mode cannot "
            "gate them — add each to _CRITICAL_ACTIONS, _HIGH_RISK_ACTIONS, "
            "_MEDIUM_RISK_ACTIONS or _LOW_RISK_ACTIONS in execution_lifecycle "
            "after reading its handler:\n  " + "\n  ".join(unrated),
        )

    def test_native_dry_run_actions_are_registered_destructive_actions(self) -> None:
        stray = sorted(
            f"{tool}.{action}"
            for tool, action in destructive_hook.NATIVE_DRY_RUN_ACTIONS
            if action not in destructive_hook.DESTRUCTIVE_ACTIONS_BY_TOOL.get(tool, frozenset())
        )
        self.assertEqual(stray, [], "NATIVE_DRY_RUN_ACTIONS entries that are not "
                         "registered destructive actions:\n  " + "\n  ".join(stray))

    def test_native_dry_run_allowlist_matches_the_handlers(self) -> None:
        """Static drift guard: the allowlist equals the set of registered
        destructive actions whose dispatch branch reaches a `dry_run` read with
        the caller's params object actually flowing into it.

        Following calls only when they pass `p`/`params` (or a dict carrying a
        dry_run key) matters: `edit_engine.execute_tighten` calls a helper that
        reads dry_run, but hands it a fresh dict without the flag, so the
        caller's dry_run is ignored — a naive reachability scan lists it and a
        dry-run request would execute for real.
        """
        found = _scan_native_dry_run_actions()
        listed = set(destructive_hook.NATIVE_DRY_RUN_ACTIONS)
        missing = sorted(f"{t}.{a}" for t, a in found - listed)
        stale = sorted(f"{t}.{a}" for t, a in listed - found)
        self.assertEqual(
            (missing, stale), ([], []),
            "NATIVE_DRY_RUN_ACTIONS drifted from src/server.py.\n"
            "  handlers with a native dry_run path not listed (add them): "
            + (", ".join(missing) or "none") + "\n"
            "  listed actions whose handler ignores dry_run (remove them): "
            + (", ".join(stale) or "none"),
        )

    def test_a_rated_action_reports_the_same_level_to_both_surfaces(self) -> None:
        """`inspect_operation` and the safe-mode gate must not diverge.

        They read the same classifier now; this pins that they keep doing so,
        since the failure mode is silent — the gate refusing a call that
        pre-flight inspection had just described as reversible.
        """
        for tool, actions in destructive_hook.DESTRUCTIVE_ACTIONS_BY_TOOL.items():
            for action in sorted(actions):
                with self.subTest(action=f"{tool}.{action}"):
                    self.assertEqual(
                        destructive_hook.risk_level_for_action(tool, action, {}),
                        inspect_operation(tool, action, {})["risk"]["level"],
                    )


class PreferenceIsolation(unittest.TestCase):
    """The operator's saved `setup` defaults must not decide what the suite does.

    `logs/media-analysis-preferences.json` holds real defaults including
    `destructive.safe_mode`. With it left true on this machine, seventeen tests
    failed with "Safe mode blocked critical-risk action" — a red suite produced
    by a setting rather than by the code. `tests/offline_guard` redirects the
    path; these pin that it is redirected and that it names the variable the
    server actually reads.
    """

    def test_guard_env_name_matches_the_server(self) -> None:
        import src.server as server

        from tests import offline_guard

        self.assertEqual(offline_guard._PREFS_ENV, server._MEDIA_ANALYSIS_PREFS_ENV)

    def test_preferences_path_is_not_the_operators_file(self) -> None:
        import src.server as server

        repo_logs = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
        )
        path = os.path.abspath(server._media_analysis_preferences_path())
        self.assertFalse(
            path.startswith(os.path.abspath(repo_logs)),
            f"suite would read/write the operator's real preferences at {path}",
        )


if __name__ == "__main__":
    unittest.main()
