"""Tests for pre-balance.

Most of these pin the *guardrails* rather than the arithmetic, because the
guardrails are the product. A pre-balance that quietly develops a look has
destroyed the trust that makes a colorist willing to let an assistant near the
timeline at all — and the single most likely way to do that is the one every
first implementation reaches for: neutralize the midtones.
"""

from __future__ import annotations

import unittest

from src.utils import prebalance as pb


def levels(r=(0.02, 0.90), g=(0.02, 0.90), b=(0.02, 0.90), clipped=0.0, crushed=0.0):
    return pb.channel_levels({
        "r": {"black": r[0], "white": r[1], "clipped": clipped, "crushed": crushed},
        "g": {"black": g[0], "white": g[1], "clipped": clipped, "crushed": crushed},
        "b": {"black": b[0], "white": b[1], "clipped": clipped, "crushed": crushed},
    })


class GuardrailTests(unittest.TestCase):
    """The "is not" half of the craft definition, enforced in code."""

    def test_midtone_neutralization_is_forbidden_by_name(self) -> None:
        """Skin is warm. This is the fastest way to make everyone grey."""
        self.assertIn("midtone_neutralize", pb.FORBIDDEN_OPERATIONS)
        with self.assertRaises(pb.GuardrailViolation):
            pb.validate_plan({"operations": {"midtone_neutralize": True}})

    def test_creative_tools_are_refused(self) -> None:
        for op in ("curves", "vignette", "saturation", "qualifier", "power_window"):
            with self.subTest(op=op), self.assertRaises(pb.GuardrailViolation):
                pb.validate_plan({"operations": {op: 1}})

    def test_every_refusal_explains_itself(self) -> None:
        with self.assertRaises(pb.GuardrailViolation) as ctx:
            pb.validate_plan({"operations": {"curves": 1}})
        self.assertIn("look development", str(ctx.exception))

    def test_an_unrecognized_operation_is_refused_not_allowed_through(self) -> None:
        """Default-deny: a new operation is creative until proven otherwise."""
        with self.assertRaises(pb.GuardrailViolation):
            pb.validate_plan({"operations": {"film_emulation": 1}})

    def test_a_normal_balance_passes(self) -> None:
        pb.validate_plan(pb.propose_balance(levels(b=(0.10, 0.88))))


class BalanceMathTests(unittest.TestCase):
    def test_black_balance_lifts_the_channel_that_sits_low(self) -> None:
        """Blue usually needs the most, and here it starts highest."""
        plan = pb.propose_balance(levels(b=(0.12, 0.90)))
        self.assertLess(plan["operations"]["lift"]["b"], 0,
                        "a blue floor above target must come DOWN")
        self.assertAlmostEqual(plan["operations"]["lift"]["r"], 0.0, places=3)

    def test_black_balance_is_reported_before_white(self) -> None:
        plan = pb.propose_balance(levels(b=(0.12, 0.80)))
        self.assertIn("Black balance", plan["reasons"][0])

    def test_midtones_are_never_in_the_operations(self) -> None:
        """Asserts the intent, not an exact set — a legitimate new operation
        (the legal limiter) must not break this, but a midtone one must."""
        plan = pb.propose_balance(levels(b=(0.12, 0.80)))
        for op in plan["operations"]:
            self.assertNotIn("midtone", op)
            self.assertNotIn("gamma", op)
        self.assertIn("warm", plan["midtones"])

    def test_the_legal_limiter_is_in_the_tree_from_the_start(self) -> None:
        """Added at delivery it changes an image the colourist already approved."""
        plan = pb.propose_balance(levels(b=(0.12, 0.80)))
        self.assertIn("legal_limit", plan["operations"])
        self.assertEqual(plan["operations"]["legal_limit"]["black"], pb.LEGAL_BLACK)
        pb.validate_plan(plan)


class QualityTierTests(unittest.TestCase):
    def test_tiers_get_deeper_and_slower(self) -> None:
        rates = [pb.QUALITY_TIERS[t]["clips_per_hour"] for t in ("quick", "standard", "deep")]
        self.assertEqual(rates, sorted(rates, reverse=True))

    def test_an_unknown_tier_raises_rather_than_defaulting(self) -> None:
        with self.assertRaises(ValueError):
            pb.resolve_tier("thorough")

    def test_effort_is_estimated_and_labelled_as_an_estimate(self) -> None:
        out = pb.estimate_effort(100, "standard")
        self.assertGreater(out["estimated_hours"], 0)
        self.assertIn("ESTIMATE", out["basis"])
        self.assertIn("not a promise", out["basis"])

    def test_deeper_tiers_estimate_more_hours(self) -> None:
        self.assertGreater(
            pb.estimate_effort(100, "deep")["estimated_hours"],
            pb.estimate_effort(100, "quick")["estimated_hours"],
        )

    def test_an_already_balanced_shot_gets_no_churn(self) -> None:
        plan = pb.propose_balance(levels())
        self.assertIn("Already balanced", plan["reasons"][0])

    def test_the_node_is_labelled_so_it_can_be_bypassed(self) -> None:
        self.assertEqual(pb.propose_balance(levels())["node_label"], "ASST: Balance")

    def test_end_points_leave_headroom_rather_than_slamming_to_0_and_1(self) -> None:
        self.assertGreater(pb.TARGET_BLACK, 0.0)
        self.assertLess(pb.TARGET_WHITE, 1.0)


class ProblemFlaggingTests(unittest.TestCase):
    def test_clipped_highlights_are_flagged_as_unrecoverable(self) -> None:
        problems = pb.detect_problems(levels(clipped=0.10))
        self.assertTrue(problems)
        self.assertIn("no grade recovers it", problems[0]["description"])

    def test_crushed_shadows_are_flagged(self) -> None:
        self.assertTrue(any("crushed" in p["description"] for p in pb.detect_problems(levels(crushed=0.10))))

    def test_a_strong_shadow_cast_is_flagged_as_possibly_intentional(self) -> None:
        """It cannot know the DP asked for it, so it says so instead of assuming."""
        problems = pb.detect_problems(levels(b=(0.20, 0.90)))
        creative = [p for p in problems if p["type"] == "CREATIVE"]
        self.assertTrue(creative)
        self.assertIn("bypass this node", creative[0]["description"])

    def test_a_clean_shot_raises_nothing(self) -> None:
        self.assertEqual(pb.detect_problems(levels()), [])


class GroupingTests(unittest.TestCase):
    def test_clips_group_by_setup_not_timeline_order(self) -> None:
        groups = pb.group_by_setup([
            {"name": "a", "setup": "INT-KITCHEN"},
            {"name": "b", "setup": "EXT-STREET"},
            {"name": "c", "setup": "INT-KITCHEN"},
        ])
        self.assertEqual(sorted(groups), ["EXT-STREET", "INT-KITCHEN"])
        self.assertEqual(len(groups["INT-KITCHEN"]), 2)

    def test_the_hero_is_the_longest_shot(self) -> None:
        hero = pb.pick_hero([
            {"name": "short", "duration_seconds": 2, "levels": levels()},
            {"name": "long", "duration_seconds": 30, "levels": levels()},
        ])
        self.assertEqual(hero["name"], "long")

    def test_an_empty_group_has_no_hero(self) -> None:
        self.assertIsNone(pb.pick_hero([]))


class PlanTests(unittest.TestCase):
    CLIPS = [
        {"name": "A001", "setup": "INT", "duration_seconds": 30, "levels": levels(b=(0.12, 0.88))},
        {"name": "A002", "setup": "INT", "duration_seconds": 8, "levels": levels()},
        {"name": "A003", "setup": "EXT", "duration_seconds": 12, "levels": levels(clipped=0.09)},
        {"name": "A004", "setup": "EXT", "duration_seconds": 5},  # no levels
    ]

    def setUp(self) -> None:
        self.out = pb.plan_prebalance(self.CLIPS)

    def test_unmeasured_clips_are_not_reported_as_balanced(self) -> None:
        self.assertEqual(len(self.out["unanalyzed"]), 1)
        self.assertIn("not certified balanced", self.out["unanalyzed"][0]["reason"])
        self.assertEqual(self.out["balanced_count"], 3)

    def test_one_hero_per_setup(self) -> None:
        heroes = {p["setup"] for p in self.out["plans"] if p["is_hero"]}
        self.assertEqual(heroes, {"INT", "EXT"})

    def test_problems_become_markers_in_the_house_convention(self) -> None:
        note = self.out["flagged"][0]["marker_note"]
        self.assertTrue(note.startswith("ASST: "))

    def test_the_guardrails_are_published_with_the_plan(self) -> None:
        self.assertIn("midtone_neutralize", self.out["guardrails"]["forbidden_operations"])

    def test_the_note_states_the_scopes_without_eyes_limit(self) -> None:
        self.assertIn("no eyes", self.out["note"])

    def test_no_clips_is_an_error(self) -> None:
        self.assertFalse(pb.plan_prebalance([])["success"])

    def test_every_emitted_plan_passes_its_own_guardrails(self) -> None:
        for plan in self.out["plans"]:
            pb.validate_plan(plan)


if __name__ == "__main__":
    unittest.main()
