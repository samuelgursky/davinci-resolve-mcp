"""Tests for the verify_by_readback verification primitive."""
import unittest

from src.utils.readback import verify_by_readback


class VerifyByReadbackTest(unittest.TestCase):
    def test_default_verified_is_truthy_observed(self):
        out = verify_by_readback(mutate=lambda: True, observe=lambda: "linked")
        self.assertTrue(out["success_raw"])
        self.assertTrue(out["verified"])
        self.assertFalse(out["contradiction"])

    def test_default_verified_false_on_empty_observe(self):
        out = verify_by_readback(mutate=lambda: True, observe=lambda: "")
        self.assertTrue(out["success_raw"])
        self.assertFalse(out["verified"])

    def test_contradiction_flagged(self):
        # API lies: reports success but the readback shows nothing happened.
        out = verify_by_readback(
            mutate=lambda: True, observe=lambda: None, label="lying_op"
        )
        self.assertTrue(out["success_raw"])
        self.assertFalse(out["verified"])
        self.assertTrue(out["contradiction"])

    def test_no_contradiction_when_both_false(self):
        out = verify_by_readback(mutate=lambda: False, observe=lambda: None)
        self.assertFalse(out["success_raw"])
        self.assertFalse(out["verified"])
        self.assertFalse(out["contradiction"])

    def test_snapshot_passed_to_compare_as_before(self):
        seen = {}

        def cmp(before, observed):
            seen["before"] = before
            seen["observed"] = observed
            return {"verified": observed > before}

        out = verify_by_readback(
            mutate=lambda: True,
            observe=lambda: 10,
            snapshot=lambda: 3,
            compare=cmp,
        )
        self.assertEqual(seen["before"], 3)
        self.assertEqual(seen["observed"], 10)
        self.assertTrue(out["verified"])

    def test_compare_fields_merged(self):
        out = verify_by_readback(
            mutate=lambda: True,
            observe=lambda: ["a"],
            compare=lambda before, obs: {"verified": True, "linked": obs},
        )
        self.assertEqual(out["linked"], ["a"])

    def test_intent_included(self):
        out = verify_by_readback(
            mutate=lambda: True, observe=lambda: 1, intent={"k": "v"}
        )
        self.assertEqual(out["intent"], {"k": "v"})

    def test_mutate_runs_before_observe(self):
        order = []
        verify_by_readback(
            mutate=lambda: order.append("mutate"),
            observe=lambda: order.append("observe") or True,
            snapshot=lambda: order.append("snapshot"),
        )
        self.assertEqual(order, ["snapshot", "mutate", "observe"])


if __name__ == "__main__":
    unittest.main()
