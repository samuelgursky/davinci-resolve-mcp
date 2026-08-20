"""Tests for plan reports.

The point of a report is that someone who did not watch the operation can tell
what was decided. Everything below is a property a reader depends on, not a
formatting preference — most of all the ones about what the report is *not*
allowed to leave out.
"""

from __future__ import annotations

import unittest

from src.utils import edit_report as er

PLAN = {
    "kind": "dead_space_markers",
    "timeline_name": "EP01 v3",
    "timeline_fps": 24.0,
    "tightness": "generous",
    "marker_count": 2,
    "total_dead_seconds": 6.0,
    "markers": [
        {"timeline_start_frame": 240, "duration_frames": 48,
         "note": "2.0s below -38.2 dB in A001.", "confidence": "high"},
        {"timeline_start_frame": 1440, "duration_frames": 96,
         "note": "4.0s below -38.2 dB in A001.", "confidence": "low"},
    ],
    "skipped": [{"item": "C003 graphics", "reason": "no readable media path — NOT analyzed"}],
    "handle_report": {
        "violation_count": 2,
        "unverified": [{"clip_id": "D004", "reason": "source length unknown"}],
        "note": "2 of 40 keep ranges are short of handles.",
    },
    "note": "Review-only.",
}


class ConfidenceBandTests(unittest.TestCase):
    def test_subsystem_vocabularies_collapse_to_one_scale(self) -> None:
        """Gate calibration, pause classification and heuristics each have their
        own word for this. A reader cares about one scale, not three."""
        self.assertEqual(er.confidence_band("computed"), "high")
        self.assertEqual(er.confidence_band("heuristic"), "low")
        self.assertEqual(er.confidence_band("marginal"), "medium")

    def test_an_unrecognised_word_is_unknown_not_high(self) -> None:
        """Defaulting an unrecognised confidence to 'high' would launder it."""
        self.assertEqual(er.confidence_band("banana"), "unknown")
        self.assertEqual(er.confidence_band(None), "unknown")


class ReportContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = er.render_plan_report(PLAN)

    def test_it_reports_in_timecode_not_frame_numbers(self) -> None:
        self.assertIn("00:00:10:00", self.text)   # frame 240 @ 24fps
        self.assertIn("00:01:00:00", self.text)   # frame 1440 @ 24fps

    def test_every_change_carries_its_reason(self) -> None:
        for marker in PLAN["markers"]:
            self.assertIn(marker["note"], self.text)

    def test_unanalyzed_items_are_never_folded_into_clean(self) -> None:
        self.assertIn("C003 graphics", self.text)
        self.assertIn("not the same as clean", self.text)

    def test_handle_shortfalls_reach_the_needs_a_human_section(self) -> None:
        human = self.text.split("### Needs a human", 1)[1]
        self.assertIn("Handles", human)

    def test_low_confidence_calls_are_surfaced_for_review(self) -> None:
        human = self.text.split("### Needs a human", 1)[1]
        self.assertIn("low-confidence call", human)

    def test_what_was_left_alone_is_stated(self) -> None:
        """A beat correctly preserved is invisible; say it was a choice."""
        self.assertIn("Deliberately left alone", self.text)
        self.assertIn("tightness", self.text)

    def test_singular_counts_read_correctly(self) -> None:
        self.assertIn("1 low-confidence call", self.text)
        self.assertNotIn("1 low-confidence calls", self.text)
        self.assertNotIn("1 items", self.text)


class RobustnessTests(unittest.TestCase):
    def test_an_unknown_plan_kind_still_renders(self) -> None:
        """A report that refuses to render sends the reader back to raw JSON."""
        text = er.render_plan_report({"kind": "something_new", "timeline_fps": 25})
        self.assertIn("Something New", text)

    def test_an_empty_plan_does_not_crash(self) -> None:
        self.assertTrue(er.render_plan_report({}).strip())

    def test_long_plans_are_truncated_with_the_remainder_declared(self) -> None:
        """Silent truncation would read as 'that was all of them'."""
        big = dict(PLAN, markers=[
            {"timeline_start_frame": i * 100, "duration_frames": 24, "note": f"gap {i}"}
            for i in range(60)
        ])
        text = er.render_plan_report(big, max_detail_rows=10)
        self.assertIn("more not shown", text)

    def test_pipes_in_a_reason_cannot_break_the_table(self) -> None:
        text = er.render_plan_report(dict(PLAN, markers=[
            {"timeline_start_frame": 0, "duration_frames": 24, "note": "a | b | c"}
        ]))
        for line in text.splitlines():
            if line.startswith("| `00:"):
                self.assertEqual(line.count("|"), 5)


class ChatSummaryTests(unittest.TestCase):
    def test_the_one_liner_leads_with_the_number_that_matters(self) -> None:
        self.assertTrue(er.summarize_for_chat(PLAN).startswith("2 dead-space markers"))

    def test_caveats_ride_along_rather_than_being_dropped(self) -> None:
        summary = er.summarize_for_chat(PLAN)
        self.assertIn("not analyzed", summary)
        self.assertIn("short of handles", summary)

    def test_a_clean_plan_carries_no_false_caveats(self) -> None:
        summary = er.summarize_for_chat(
            {"kind": "tighten", "lift_count": 3, "estimated_removed_seconds": 9.0}
        )
        self.assertNotIn("—", summary)


AUDIT = {
    "kind": "rule_of_six_audit",
    "timeline_name": "EP01",
    "coverage": {"statement": "1 of 6 criteria assessed, covering 10% of the decision."},
    "criteria": [
        {"criterion": "emotion", "label": "Emotion — x", "weight": 0.51,
         "state": "NOT_ASSESSED", "detail": "not measurable"},
        {"criterion": "rhythm", "label": "Rhythm — x", "weight": 0.10,
         "state": "FLAG", "detail": "metronomic"},
        {"criterion": "eye_trace", "label": "Eye-trace — x", "weight": 0.07,
         "state": "NOT_IMPLEMENTED", "detail": "not computed"},
    ],
    "findings": [{"criterion": "rhythm", "summary": "8 identical shots",
                  "detail": "no break anywhere"}],
    "note": "no overall score",
}


class AuditReportTests(unittest.TestCase):
    """Invariant I5: an audit a human cannot read is one they will redo by hand."""

    def setUp(self) -> None:
        self.text = er.render_audit_report(AUDIT)

    def test_coverage_leads_the_report(self) -> None:
        self.assertIn("covering 10% of the decision", self.text)

    def test_abstentions_are_rendered_with_their_weight(self) -> None:
        self.assertIn("51%", self.text)
        self.assertIn("NOT_ASSESSED", self.text)

    def test_uncomputed_criteria_reach_the_not_checked_section(self) -> None:
        section = self.text.split("### Not checked", 1)[1]
        self.assertIn("eye_trace", section)

    def test_the_not_checked_section_says_it_is_not_clean(self) -> None:
        self.assertIn("Not looked at is not the same as clean", self.text)

    def test_findings_carry_their_detail(self) -> None:
        self.assertIn("no break anywhere", self.text)

    def test_lint_style_audits_render_too(self) -> None:
        text = er.render_audit_report({
            "kind": "conform_lint",
            "findings": [{"code": "FPS_MISMATCH", "severity": "blocker",
                          "summary": "rate mismatch", "detail": "drift"}],
            "not_checked": ["reel names (not captured)"],
        })
        self.assertIn("rate mismatch", text)
        self.assertIn("reel names", text)

    def test_render_any_routes_audits_and_plans_correctly(self) -> None:
        self.assertIn("Criteria", er.render_any(AUDIT))
        self.assertIn("What would change", er.render_any(PLAN))

    def test_provenance_lines_survive_into_the_report(self) -> None:
        """A threshold's provenance is useless if the readable form drops it."""
        text = er.render_audit_report({
            "kind": "sound_density_audit",
            "threshold_provenance": "2.5 is an observation, NOT a constant",
            "method": "Heuristic.",
        })
        self.assertIn("NOT a constant", text)
        self.assertIn("Heuristic", text)


if __name__ == "__main__":
    unittest.main()
