"""Contract tests for the A1 structured error envelope and D1 retryable defaults.

See local/design/agentic-flow-improvements-gameplan.md §3 task A1
and local/design/agentic-flow-improvements-gameplan-2.md §3 task D1.
"""
import unittest

from src.server import _err, ERROR_CATEGORIES, _CATEGORY_RETRYABLE_DEFAULT


class ErrorEnvelopeContractTest(unittest.TestCase):
    def test_default_shape_is_structured(self):
        out = _err("something went wrong")
        self.assertIn("error", out)
        body = out["error"]
        self.assertIsInstance(body, dict)
        self.assertEqual(body["message"], "something went wrong")
        self.assertEqual(body["code"], "UNSPECIFIED")
        self.assertEqual(body["category"], "resolve_api_failed")
        # D1: resolve_api_failed defaults to retryable=True when retryable is omitted.
        self.assertTrue(body["retryable"])
        self.assertNotIn("remediation", body)
        self.assertNotIn("reason", body)

    def test_named_code_category_retryable_remediation(self):
        out = _err(
            "no project",
            code="NO_PROJECT",
            category="precondition",
            retryable=False,
            remediation="open one",
        )
        body = out["error"]
        self.assertEqual(body["code"], "NO_PROJECT")
        self.assertEqual(body["category"], "precondition")
        self.assertFalse(body["retryable"])
        self.assertEqual(body["remediation"], "open one")

    def test_unknown_category_falls_back_to_resolve_api_failed(self):
        out = _err("boom", category="invented_category")
        self.assertEqual(out["error"]["category"], "resolve_api_failed")

    def test_message_is_always_stringified(self):
        out = _err(123)
        self.assertEqual(out["error"]["message"], "123")

    def test_category_enum_locked(self):
        expected = {
            "precondition",
            "not_connected",
            "wrong_page",
            "invalid_input",
            "resolve_api_failed",
            "busy",
            "destructive_blocked",
            "pending_user_decision",
            "unsupported",
            "budget_exhausted",
            "timeout",
            "batch_partial",
        }
        self.assertEqual(set(ERROR_CATEGORIES), expected)

    def test_every_category_has_retryable_default(self):
        """D1: the lookup map must cover every category in ERROR_CATEGORIES."""
        for cat in ERROR_CATEGORIES:
            self.assertIn(cat, _CATEGORY_RETRYABLE_DEFAULT,
                          f"category {cat!r} missing from _CATEGORY_RETRYABLE_DEFAULT")

    def test_retryable_default_per_category(self):
        """D1: lock the per-category default values; downstream agents route on these."""
        cases = {
            "precondition": False,
            "not_connected": True,
            "wrong_page": True,
            "invalid_input": False,
            "resolve_api_failed": True,
            "busy": True,
            "destructive_blocked": False,
            "pending_user_decision": False,
            "unsupported": False,
            "budget_exhausted": False,
            "timeout": True,
            "batch_partial": False,
        }
        for cat, expected_retryable in cases.items():
            with self.subTest(category=cat):
                out = _err("x", category=cat)
                self.assertEqual(out["error"]["retryable"], expected_retryable,
                                 f"category {cat!r} expected retryable={expected_retryable}")

    def test_explicit_retryable_override_wins(self):
        """D1: an explicit retryable= keyword overrides the per-category default."""
        # resolve_api_failed defaults True; force False.
        out = _err("x", category="resolve_api_failed", retryable=False)
        self.assertFalse(out["error"]["retryable"])
        # precondition defaults False; force True.
        out = _err("x", category="precondition", retryable=True)
        self.assertTrue(out["error"]["retryable"])

    def test_reason_field_carried_when_provided(self):
        """D1: optional reason= keyword surfaces in the envelope (matches CAPS_REFUSAL shape)."""
        out = _err("budget gone", category="budget_exhausted",
                   reason="over_day_cap", remediation="raise the cap")
        body = out["error"]
        self.assertEqual(body["reason"], "over_day_cap")
        self.assertFalse(body["retryable"])  # budget_exhausted default
        self.assertEqual(body["remediation"], "raise the cap")

    def test_no_caller_returns_bare_string_error(self):
        """Sanity smoke: the helper itself always wraps in a dict."""
        out = _err("x")
        self.assertNotIsInstance(out["error"], str)

    def test_state_field_carried_when_provided(self):
        """state= surfaces a machine-readable snapshot at failure time."""
        out = _err("no render job", category="resolve_api_failed",
                   state={"queue_size": 0, "format": "mov"})
        self.assertEqual(out["error"]["state"], {"queue_size": 0, "format": "mov"})

    def test_state_omitted_when_empty(self):
        """Empty/None state must not bloat the envelope."""
        self.assertNotIn("state", _err("x")["error"])
        self.assertNotIn("state", _err("x", state={})["error"])

    def test_check_emits_structured_not_connected_when_resolve_absent(self):
        """Integration smoke: _check returns a NOT_CONNECTED error when Resolve is unreachable."""
        import src.server as compound

        original = compound.get_resolve
        compound.get_resolve = lambda: None
        try:
            _, _, err = compound._check()
        finally:
            compound.get_resolve = original

        self.assertIsNotNone(err)
        body = err["error"]
        self.assertEqual(body["code"], "NOT_CONNECTED")
        self.assertEqual(body["category"], "not_connected")
        self.assertTrue(body["retryable"])
        self.assertIn("Resolve", body["message"])
        self.assertIn("remediation", body)

    def test_validate_cdl_payload_returns_invalid_input(self):
        """F1 — caller-side input validation on safe_set_cdl uses invalid_input,
        not the default resolve_api_failed."""
        import src.server as compound

        _, err = compound._validate_cdl_payload("not a dict")
        self.assertIsNotNone(err)
        body = err["error"]
        self.assertEqual(body["code"], "INVALID_CDL")
        self.assertEqual(body["category"], "invalid_input")
        self.assertIn("remediation", body)

    def test_get_tl_emits_no_current_timeline(self):
        """Integration smoke: _get_tl emits a precondition error with NO_CURRENT_TIMELINE code."""
        import src.server as compound

        class _StubProject:
            def GetCurrentTimeline(self):
                return None

        original_check = compound._check
        compound._check = lambda: (object(), _StubProject(), None)
        try:
            _, _, err = compound._get_tl()
        finally:
            compound._check = original_check

        self.assertIsNotNone(err)
        body = err["error"]
        self.assertEqual(body["code"], "NO_CURRENT_TIMELINE")
        self.assertEqual(body["category"], "precondition")


if __name__ == "__main__":
    unittest.main()
