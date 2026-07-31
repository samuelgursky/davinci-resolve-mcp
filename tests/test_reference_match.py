"""Tests for reference-still matching.

The reference still is how a colorist actually communicates — "make it look like
this one" — and the risk is a tool that appears to answer that and only half
does. Matching end points is not transferring a grade, and most of what is
pinned here is that the tool never lets anyone believe otherwise.
"""

from __future__ import annotations

import unittest

from src.utils import prebalance as pb
from src.utils import reference_match as rm


def levels(black=0.02, white=0.90, b_black=None):
    return pb.channel_levels({
        "r": {"black": black, "white": white},
        "g": {"black": black, "white": white},
        "b": {"black": b_black if b_black is not None else black, "white": white},
    })


class ScopeHonestyTests(unittest.TestCase):
    """A tool that quietly under-delivers on "make it look like this" wastes
    more of a colorist's time than one that refuses."""

    def setUp(self) -> None:
        self.plan = rm.propose_match(levels(), levels(0.10, 0.80), reference_name="hero")

    def test_the_plan_states_it_is_end_points_only(self) -> None:
        self.assertIn("END POINTS ONLY", self.plan["scope"])

    def test_it_says_the_grade_is_not_transferred(self) -> None:
        self.assertIn("does NOT reproduce the reference's grade", self.plan["scope"])
        for word in ("Curves", "vignettes", "secondaries"):
            self.assertIn(word, self.plan["scope"])

    def test_the_node_label_distinguishes_matched_from_balanced(self) -> None:
        self.assertNotEqual(rm.MATCH_NODE_LABEL, pb.BALANCE_NODE_LABEL)


class GuardrailReuseTests(unittest.TestCase):
    def test_it_reuses_the_prebalance_guardrails_rather_than_its_own(self) -> None:
        """Two guardrail implementations would drift; one cannot."""
        plan = rm.propose_match(levels(), levels(0.10, 0.80))
        pb.validate_plan(plan)

    def test_midtones_are_never_touched(self) -> None:
        plan = rm.propose_match(levels(), levels(0.10, 0.80))
        for op in plan["operations"]:
            self.assertNotIn("midtone", op)
            self.assertNotIn("gamma", op)

    def test_the_legal_limiter_travels_with_the_match(self) -> None:
        plan = rm.propose_match(levels(), levels(0.10, 0.80))
        self.assertIn("legal_limit", plan["operations"])


class MatchMathTests(unittest.TestCase):
    def test_a_target_darker_than_the_reference_gets_lifted(self) -> None:
        plan = rm.propose_match(levels(black=0.10), levels(black=0.02))
        self.assertGreater(plan["operations"]["lift"]["r"], 0)

    def test_a_channel_cast_is_corrected_toward_the_reference(self) -> None:
        plan = rm.propose_match(levels(), levels(b_black=0.14))
        self.assertLess(plan["operations"]["lift"]["b"], 0)
        self.assertAlmostEqual(plan["operations"]["lift"]["r"], 0.0, places=3)

    def test_matching_a_shot_to_itself_is_a_no_op(self) -> None:
        same = levels(0.05, 0.85)
        plan = rm.propose_match(same, same)
        for channel in "rgb":
            self.assertAlmostEqual(plan["operations"]["lift"][channel], 0.0, places=4)
            self.assertAlmostEqual(plan["operations"]["gain"][channel], 1.0, places=3)


class ConfidenceTests(unittest.TestCase):
    def test_comparable_images_read_as_high_confidence(self) -> None:
        out = rm.match_confidence(levels(0.02, 0.90), levels(0.06, 0.94))
        self.assertEqual(out["band"], "high")

    def test_very_different_tonal_ranges_read_as_low(self) -> None:
        """Night exterior vs white cyc: the end points are not the same measurement."""
        out = rm.match_confidence(levels(0.02, 0.95), levels(0.40, 0.55))
        self.assertEqual(out["band"], "low")
        self.assertIn("close to meaningless", out["reason"])

    def test_a_flat_image_cannot_be_judged(self) -> None:
        flat = levels(0.5, 0.5)
        self.assertEqual(rm.match_confidence(flat, levels())["band"], "low")


class PlanTests(unittest.TestCase):
    TARGETS = [
        {"name": "A001", "levels": levels(0.10, 0.80)},
        {"name": "A002", "levels": levels(0.40, 0.55)},   # dissimilar
        {"name": "A003"},                                  # unmeasured
    ]

    def setUp(self) -> None:
        self.out = rm.plan_reference_match(levels(), self.TARGETS, reference_name="hero")

    def test_unmeasured_clips_are_not_reported_as_matched(self) -> None:
        self.assertEqual(self.out["matched_count"], 2)
        self.assertIn("not certified matched", self.out["unmatched"][0]["reason"])

    def test_low_confidence_clips_are_named(self) -> None:
        self.assertIn("A002", self.out["low_confidence_clips"])

    def test_the_note_repeats_the_scope_limit(self) -> None:
        self.assertIn("END POINTS ONLY", self.out["note"])

    def test_the_guardrails_are_published_with_the_plan(self) -> None:
        self.assertIn("midtone_neutralize", self.out["guardrails"]["forbidden_operations"])

    def test_no_reference_or_no_targets_is_an_error(self) -> None:
        self.assertFalse(rm.plan_reference_match({}, self.TARGETS)["success"])
        self.assertFalse(rm.plan_reference_match(levels(), [])["success"])


if __name__ == "__main__":
    unittest.main()
