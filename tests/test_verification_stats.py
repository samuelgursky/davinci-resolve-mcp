"""Tests for readback verification stats + the resolve_control verification_stats action."""
import unittest

import src.server as s
from src.utils import readback
from src.utils.readback import verify_by_readback, reset_verification_stats


class VerificationStatsTest(unittest.TestCase):
    def setUp(self):
        reset_verification_stats()

    def test_counts_outcomes(self):
        verify_by_readback(mutate=lambda: True, observe=lambda: "ok")      # verified
        verify_by_readback(mutate=lambda: True, observe=lambda: None)      # contradicted
        verify_by_readback(mutate=lambda: False, observe=lambda: None)     # unverified
        st = readback.verification_stats()
        self.assertEqual(st["total"], 3)
        self.assertEqual(st["verified"], 1)
        self.assertEqual(st["contradicted"], 1)
        self.assertEqual(st["unverified"], 1)

    def test_action_no_connection(self):
        reset_verification_stats()
        verify_by_readback(mutate=lambda: True, observe=lambda: "ok")
        out = s.resolve_control("verification_stats", {})
        self.assertEqual(out["stats"]["verified"], 1)
        self.assertIn("note", out)


if __name__ == "__main__":
    unittest.main()
