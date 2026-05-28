"""Contract tests for B2 — confirm-token gate.

See local/design/agentic-flow-improvements-gameplan.md §3 task B2.
"""
import unittest

import src.server as compound


class ConfirmTokenLifecycleTest(unittest.TestCase):
    def setUp(self):
        compound._CONFIRM_TOKENS.clear()

    def test_fingerprint_stable_across_calls(self):
        fp1 = compound._confirm_token_fingerprint("act", {"path": "/x", "k": 1})
        fp2 = compound._confirm_token_fingerprint("act", {"path": "/x", "k": 1})
        self.assertEqual(fp1, fp2)

    def test_fingerprint_changes_with_params(self):
        fp1 = compound._confirm_token_fingerprint("act", {"path": "/x"})
        fp2 = compound._confirm_token_fingerprint("act", {"path": "/y"})
        self.assertNotEqual(fp1, fp2)

    def test_fingerprint_ignores_confirm_token_itself(self):
        fp1 = compound._confirm_token_fingerprint("act", {"k": 1})
        fp2 = compound._confirm_token_fingerprint("act", {"k": 1, "confirm_token": "abc"})
        self.assertEqual(fp1, fp2)

    def test_issue_returns_pending_user_decision_structured_error(self):
        out = compound._issue_confirm_token(
            action="x", params={"k": 1}, preview={"warning": "boom"},
        )
        self.assertIn("error", out)
        self.assertEqual(out["error"]["category"], "pending_user_decision")
        self.assertEqual(out["error"]["code"], "CONFIRMATION_REQUIRED")
        self.assertIn("confirm_token", out)
        self.assertEqual(out["status"], "confirmation_required")
        self.assertEqual(out["preview"]["warning"], "boom")

    def test_consume_with_no_token_returns_none(self):
        """No token in params + gating on means 'caller should issue one' (not blocked)."""
        result = compound._consume_confirm_token(action="x", params={"k": 1})
        self.assertIsNone(result)

    def test_consume_with_valid_token_proceeds(self):
        issued = compound._issue_confirm_token(action="x", params={"k": 1}, preview={})
        token = issued["confirm_token"]
        result = compound._consume_confirm_token(action="x", params={"k": 1, "confirm_token": token})
        self.assertIsNone(result)

    def test_token_is_single_use(self):
        issued = compound._issue_confirm_token(action="x", params={"k": 1}, preview={})
        token = issued["confirm_token"]
        ok1 = compound._consume_confirm_token(action="x", params={"k": 1, "confirm_token": token})
        self.assertIsNone(ok1)
        ok2 = compound._consume_confirm_token(action="x", params={"k": 1, "confirm_token": token})
        self.assertIsNotNone(ok2)
        self.assertEqual(ok2["error"]["code"], "CONFIRM_TOKEN_INVALID")

    def test_wrong_action_rejected(self):
        issued = compound._issue_confirm_token(action="x", params={"k": 1}, preview={})
        token = issued["confirm_token"]
        blocked = compound._consume_confirm_token(action="y", params={"k": 1, "confirm_token": token})
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["error"]["code"], "CONFIRM_TOKEN_ACTION_MISMATCH")

    def test_changed_params_rejected(self):
        issued = compound._issue_confirm_token(action="x", params={"k": 1}, preview={})
        token = issued["confirm_token"]
        blocked = compound._consume_confirm_token(action="x", params={"k": 2, "confirm_token": token})
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["error"]["code"], "CONFIRM_TOKEN_FINGERPRINT_MISMATCH")

    def test_expired_token_rejected(self):
        issued = compound._issue_confirm_token(action="x", params={"k": 1}, preview={})
        token = issued["confirm_token"]
        # Force expiry
        compound._CONFIRM_TOKENS[token]["expires_at"] = 0
        blocked = compound._consume_confirm_token(action="x", params={"k": 1, "confirm_token": token})
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["error"]["code"], "CONFIRM_TOKEN_INVALID")


if __name__ == "__main__":
    unittest.main()
