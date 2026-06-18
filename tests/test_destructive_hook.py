"""Unit tests for action-filtering and strict-mode behavior in destructive_hook.

No Resolve required.
"""

from __future__ import annotations

import unittest
from unittest import mock

from src.utils import destructive_hook


class ActionFiltering(unittest.TestCase):
    """is_destructive() consults both the registry AND the no-archive filter."""

    def test_unregistered_action_is_not_destructive(self) -> None:
        self.assertFalse(destructive_hook.is_destructive("timeline", "get_current"))

    def test_registered_action_is_destructive_by_default(self) -> None:
        self.assertTrue(destructive_hook.is_destructive("timeline", "delete_clips"))

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


if __name__ == "__main__":
    unittest.main()
