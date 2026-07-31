"""Tests for the Rule of Six audit frame and the rhythm criterion.

Most of what is pinned here is the *honesty* of the frame rather than any
arithmetic. The weighting is inverted against measurability — everything
computable is the bottom 26% — so the design rests entirely on the reader being
shown the 74% that was not looked at. Every guard below protects that.
"""

from __future__ import annotations

import unittest

from src.utils import rhythm_audit as ra
from src.utils import rule_of_six as six


def item(name, start, end):
    return {"item_name": name, "timeline_start_frame": start, "timeline_end_frame": end}


def metronomic(count=8, shot_frames=48, start=0):
    items, frame = [], start
    for i in range(count):
        items.append(item(f"m{i}", frame, frame + shot_frames))
        frame += shot_frames
    return items, frame


class AbstentionTests(unittest.TestCase):
    """The 74%. If these break, the tool has started lying."""

    def test_emotion_and_story_are_always_present(self) -> None:
        names = [r["criterion"] for r in six.audit()["criteria"]]
        self.assertIn("emotion", names)
        self.assertIn("story", names)

    def test_they_carry_their_weights_so_the_stakes_are_visible(self) -> None:
        rows = {r["criterion"]: r for r in six.audit()["criteria"]}
        self.assertEqual(rows["emotion"]["weight"], 0.51)
        self.assertEqual(rows["story"]["weight"], 0.23)

    def test_they_are_not_assessed_and_stay_that_way(self) -> None:
        rows = {r["criterion"]: r for r in six.audit()["criteria"]}
        for name in six.UNMEASURABLE:
            self.assertEqual(rows[name]["state"], six.STATE_NOT_ASSESSED)

    def test_a_computed_criterion_cannot_claim_to_be_emotion(self) -> None:
        """Nothing may fill the 51% slot, including a future contributor."""
        rows = {r["criterion"]: r for r in six.audit(
            criterion_results={"emotion": {"state": "PASS", "detail": "vibes"}}
        )["criteria"]}
        self.assertEqual(rows["emotion"]["state"], six.STATE_NOT_ASSESSED)

    def test_the_abstention_explains_why_not_just_that(self) -> None:
        rows = {r["criterion"]: r for r in six.audit()["criteria"]}
        self.assertIn("not measurable", rows["emotion"]["detail"])


class StateSeparationTests(unittest.TestCase):
    def test_unassessed_and_unimplemented_are_different_states(self) -> None:
        """Collapsing them lets the tool get quieter as it gets more capable."""
        rows = {r["criterion"]: r for r in six.audit()["criteria"]}
        self.assertEqual(rows["emotion"]["state"], six.STATE_NOT_ASSESSED)
        self.assertEqual(rows["eye_trace"]["state"], six.STATE_NOT_IMPLEMENTED)
        self.assertNotEqual(rows["emotion"]["state"], rows["eye_trace"]["state"])

    def test_an_uncomputed_criterion_is_never_a_pass(self) -> None:
        for row in six.audit()["criteria"]:
            self.assertNotEqual(row["state"], six.STATE_PASS)

    def test_a_computed_criterion_must_return_pass_or_flag(self) -> None:
        with self.assertRaises(ValueError):
            six.audit(criterion_results={"rhythm": {"state": "PROBABLY_FINE"}})


class NoCompositeScoreTests(unittest.TestCase):
    def test_no_field_could_be_mistaken_for_an_overall_score(self) -> None:
        """26% averaged into one number implies it describes the cut."""
        result = six.audit(criterion_results={"rhythm": {"state": "PASS", "detail": "x"}})
        banned = ("score", "grade", "rating", "quality", "overall", "total_score")
        for key in result:
            self.assertFalse(
                any(b in key.lower() for b in banned),
                f"{key!r} could be read as a composite score",
            )

    def test_coverage_is_stated_as_a_fraction_of_the_decision(self) -> None:
        result = six.audit(criterion_results={"rhythm": {"state": "PASS", "detail": "x"}})
        self.assertEqual(result["coverage"]["weight_assessed"], 0.10)
        self.assertIn("10% of the decision", result["coverage"]["statement"])

    def test_an_empty_audit_honestly_reports_zero_coverage(self) -> None:
        self.assertEqual(six.audit()["coverage"]["weight_assessed"], 0.0)


class OrderingTests(unittest.TestCase):
    """The iron rule: sacrifice lower priorities to preserve higher ones."""

    def test_rhythm_outranks_screen_geography(self) -> None:
        ordered = six.sort_findings([
            {"criterion": "two_d_plane", "scope": "moment", "at": 1},
            {"criterion": "rhythm", "scope": "moment", "at": 2},
        ])
        self.assertEqual(ordered[0]["criterion"], "rhythm")

    def test_scope_outranks_criterion_weight(self) -> None:
        """The scope axis: movie first, scene second, moment third."""
        ordered = six.sort_findings([
            {"criterion": "rhythm", "scope": "moment", "at": 1},
            {"criterion": "three_d_space", "scope": "sequence", "at": 2},
        ])
        self.assertEqual(ordered[0]["scope"], "sequence")

    def test_ordering_is_not_by_volume(self) -> None:
        """Fifty continuity nits must not bury one rhythm problem."""
        findings = [{"criterion": "three_d_space", "scope": "moment", "at": i} for i in range(50)]
        findings.append({"criterion": "rhythm", "scope": "moment", "at": 99})
        self.assertEqual(six.sort_findings(findings)[0]["criterion"], "rhythm")

    def test_criteria_rows_are_listed_in_weighted_order(self) -> None:
        weights = [r["weight"] for r in six.audit()["criteria"]]
        self.assertEqual(weights, sorted(weights, reverse=True))


class RhythmTests(unittest.TestCase):
    def test_a_metronomic_run_is_flagged(self) -> None:
        """A pattern established and never broken emphasises nothing."""
        items, _ = metronomic(8)
        out = ra.assess(items, fps=24.0)
        self.assertEqual(out["state"], six.STATE_FLAG)
        self.assertTrue(any("near-identical" in f["summary"] for f in out["findings"]))

    def test_a_break_on_a_story_beat_is_not_a_finding(self) -> None:
        """That is the craft working — the break is where meaning lives."""
        items, frame = metronomic(8)
        items.append(item("hold", frame, frame + 192))  # 8s at 16.0s
        out = ra.assess(items, fps=24.0, story_beats=[16.0])
        self.assertTrue(out["motivated_breaks"])
        self.assertFalse(any("nothing to emphasise" in f["summary"] for f in out["findings"]))

    def test_a_break_on_nothing_is_a_finding(self) -> None:
        items, frame = metronomic(8)
        items.append(item("orphan", frame, frame + 192))
        out = ra.assess(items, fps=24.0, story_beats=[])
        self.assertTrue(any("nothing to emphasise" in f["summary"] for f in out["findings"]))

    def test_what_went_right_is_said_out_loud(self) -> None:
        """A tool that only ever complains teaches that clean means it didn't look."""
        items, frame = metronomic(8)
        items.append(item("hold", frame, frame + 192))
        out = ra.assess(items, fps=24.0, story_beats=[16.0])
        self.assertIn("deliberately", out["detail"])

    def test_missing_beats_are_declared_not_assumed(self) -> None:
        items, _ = metronomic(8)
        out = ra.assess(items, fps=24.0)
        self.assertIn("could NOT be judged", out["detail"])

    def test_too_few_shots_is_not_a_rhythm_failure(self) -> None:
        out = ra.assess([item("a", 0, 48), item("b", 48, 96)], fps=24.0)
        self.assertEqual(out["state"], six.STATE_PASS)
        self.assertTrue(out["insufficient_data"])

    def test_varied_cutting_is_not_flagged_as_monotony(self) -> None:
        items, frame = [], 0
        for length in (24, 96, 48, 200, 36, 120, 60, 150):
            items.append(item(f"s{frame}", frame, frame + length))
            frame += length
        out = ra.assess(items, fps=24.0, story_beats=[])
        self.assertFalse(any("near-identical" in f["summary"] for f in out["findings"]))


class CutDensityTests(unittest.TestCase):
    def test_density_is_reported_as_a_comparison_never_a_target(self) -> None:
        items, _ = metronomic(20)
        note = ra.assess(items, fps=24.0)["cut_density"]["note"]
        self.assertIn("DESCRIPTIVE, NOT PRESCRIPTIVE", note)
        self.assertIn("not a target", note)
        # The counterexample matters more than the number: very sparse cutting is
        # not a defect. Kept unattributed in runtime output by policy — see
        # tests/test_attribution_drift.py.
        self.assertIn("fraction of that density and are not wrong", note)

    def test_the_observed_dialogue_range_is_recorded_verbatim(self) -> None:
        self.assertEqual(ra.DIALOGUE_CPM_RANGE, (14.0, 16.0))

    def test_sparse_cutting_is_described_not_penalised(self) -> None:
        items, frame = [], 0
        for _ in range(4):
            items.append(item(f"long{frame}", frame, frame + 24 * 30))
            frame += 24 * 30
        density = ra.assess(items, fps=24.0)["cut_density"]
        self.assertEqual(density["relation"], "sparser than")


if __name__ == "__main__":
    unittest.main()
