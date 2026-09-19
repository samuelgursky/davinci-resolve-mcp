"""`project_manager.snapshot` is a recognised LOW read, not a name-based MEDIUM.

The action composes existing read helpers and never writes, but its name
carries no read verb, so on the branch that added it (#251) the classifier fell
to the unrecognised default: MEDIUM, `recognised=False`, and a "risk
unestablished" reason on every call. Safe mode would not have blocked it (only
an established HIGH/CRITICAL is blocked), but the one read an agent makes before
planning should not carry that noise. `_READ_ONLY_PAIRS` names it explicitly.
"""
import unittest

from src.utils.execution_lifecycle import RiskClassificationHook, RiskLevel


class SnapshotReadRuleTests(unittest.TestCase):
    def test_snapshot_is_a_recognised_low_read(self):
        a = RiskClassificationHook.classify("project_manager", "snapshot", {})
        self.assertEqual(a.level, RiskLevel.LOW)
        self.assertFalse(a.destructive)
        self.assertTrue(a.recognised)
        self.assertEqual(a.reasons, [])

    def test_the_prior_explicit_read_pair_still_holds(self):
        a = RiskClassificationHook.classify("dctl", "validate_native", {})
        self.assertEqual(a.level, RiskLevel.LOW)
        self.assertTrue(a.recognised)

    def test_an_unknown_verbless_action_is_still_unrecognised(self):
        """The pair table is explicit: it must not widen into a wildcard."""
        a = RiskClassificationHook.classify("project_manager", "sweep", {})
        self.assertFalse(a.recognised)


if __name__ == "__main__":
    unittest.main()
