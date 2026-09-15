"""A token handed back as `confirmToken` has to be redeemable.

The gate accepts either spelling: `consume` reads the token from `confirm_token`
or `confirmToken`, and twenty-eight gated actions in the compound server treat
either as "the caller already holds a token" and skip re-issuing. But the
fingerprint stripped only the snake_case key, so the camelCase spelling stayed in
the params and changed the hash of the request between issuance and redemption.

The result was that a client using camelCase could never execute a confirm-gated
action at all: redemption failed with CONFIRM_TOKEN_FINGERPRINT_MISMATCH, and
because the token is popped before that check it was already spent, so the retry
the remediation asks for reported CONFIRM_TOKEN_INVALID instead.
"""
import unittest

import src.server as compound
from src.utils.confirm_tokens import ConfirmTokenStore, plain_error


class CamelCaseConfirmTokenTests(unittest.TestCase):
    def setUp(self):
        compound._CONFIRM_TOKENS.clear()

    def test_fingerprint_ignores_the_camel_case_token(self):
        bare = compound._confirm_token_fingerprint("act", {"k": 1})
        echoed = compound._confirm_token_fingerprint("act", {"k": 1, "confirmToken": "abc"})
        self.assertEqual(bare, echoed)

    def test_both_spellings_fingerprint_alike(self):
        snake = compound._confirm_token_fingerprint("act", {"k": 1, "confirm_token": "abc"})
        camel = compound._confirm_token_fingerprint("act", {"k": 1, "confirmToken": "abc"})
        self.assertEqual(snake, camel)

    def test_camel_case_token_is_redeemed(self):
        params = {"clip_id": "abc"}
        issued = compound._issue_confirm_token(
            action="timeline_item.copy_grades", params=params, preview={},
        )
        token = issued["confirm_token"]
        result = compound._consume_confirm_token(
            action="timeline_item.copy_grades",
            params={**params, "confirmToken": token},
        )
        self.assertIsNone(result)

    def test_camel_case_token_still_binds_to_its_params(self):
        """Stripping the key must not loosen the gate: other params still count."""
        issued = compound._issue_confirm_token(
            action="timeline_item.copy_grades", params={"clip_id": "abc"}, preview={},
        )
        blocked = compound._consume_confirm_token(
            action="timeline_item.copy_grades",
            params={"clip_id": "SOMETHING-ELSE", "confirmToken": issued["confirm_token"]},
        )
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["error"]["code"], "CONFIRM_TOKEN_FINGERPRINT_MISMATCH")

    def test_camel_case_token_is_single_use(self):
        issued = compound._issue_confirm_token(
            action="timeline_item.copy_grades", params={"clip_id": "abc"}, preview={},
        )
        token = issued["confirm_token"]
        first = compound._consume_confirm_token(
            action="timeline_item.copy_grades",
            params={"clip_id": "abc", "confirmToken": token},
        )
        self.assertIsNone(first)
        second = compound._consume_confirm_token(
            action="timeline_item.copy_grades",
            params={"clip_id": "abc", "confirmToken": token},
        )
        self.assertIsNotNone(second)
        self.assertEqual(second["error"]["code"], "CONFIRM_TOKEN_INVALID")

    def test_shared_store_redeems_camel_case_for_the_granular_surface_too(self):
        """The granular server holds its own store of the same class."""
        store = ConfirmTokenStore(err=plain_error)
        params = {"clip_id": "abc"}
        token = store.issue(action="ti_copy_grades", params=params, preview={})["confirm_token"]
        self.assertIsNone(
            store.consume(action="ti_copy_grades", params={**params, "confirmToken": token})
        )


if __name__ == "__main__":
    unittest.main()
