"""Tests for B-roll placement.

The line that must hold: this places, it does not judge. Whether a shot
illustrates a line is not something the module can see, so relevance is whatever
the caller's matcher said and is never re-scored — a tool that quietly reorders
a human's choices by its own opinion is worse than one that places them in the
order it was handed.
"""

from __future__ import annotations

import unittest

from src.utils import broll_placement as bp


def beat(start, end, text="line", protected=False):
    out = {"start_seconds": start, "end_seconds": end, "text": text}
    if protected:
        out["protected"] = True
    return out


def cand(name, duration, relevance=None, beat_index=None):
    out = {"name": name, "duration_seconds": duration}
    if relevance is not None:
        out["relevance"] = relevance
    if beat_index is not None:
        out["beat_index"] = beat_index
    return out


BEATS = [beat(0, 5, "intro"), beat(5, 10, "middle"), beat(10, 15, "end")]


class WindowTests(unittest.TestCase):
    def test_a_protected_beat_is_never_covered(self) -> None:
        """That is how a caller says the audience needs to see them say it."""
        out = bp.placeable_beats([beat(0, 5), beat(5, 10, protected=True)])
        self.assertEqual(len(out["windows"]), 1)
        self.assertIn("must-see on camera", out["skipped"][0]["reason"])

    def test_a_beat_too_short_for_a_cutaway_is_skipped_with_a_reason(self) -> None:
        out = bp.placeable_beats([beat(0, 0.9)])
        self.assertFalse(out["windows"])
        self.assertIn("read as a flash", out["skipped"][0]["reason"])

    def test_windows_sit_inside_the_beat_not_across_it(self) -> None:
        window = bp.placeable_beats([beat(0, 5)])["windows"][0]
        self.assertGreater(window["start_seconds"], 0)
        self.assertLess(window["end_seconds"], 5)


class PlacementTests(unittest.TestCase):
    def test_candidates_fill_windows_in_order(self) -> None:
        out = bp.place(BEATS, [cand("b1", 3), cand("b2", 3)])
        self.assertEqual(out["placement_count"], 2)
        self.assertEqual([p["beat_index"] for p in out["placements"]], [0, 1])

    def test_an_over_long_candidate_is_trimmed_to_the_window(self) -> None:
        out = bp.place(BEATS, [cand("long", 60)])
        placement = out["placements"][0]
        self.assertTrue(placement["trimmed"])
        self.assertLessEqual(placement["length_seconds"], 5)

    def test_an_explicit_beat_choice_is_honoured(self) -> None:
        out = bp.place(BEATS, [cand("pick", 3, beat_index=2)])
        self.assertEqual(out["placements"][0]["beat_index"], 2)

    def test_an_explicit_choice_is_never_silently_moved(self) -> None:
        """Placed where asked or not at all."""
        beats = [beat(0, 5), beat(5, 10, protected=True)]
        out = bp.place(beats, [cand("pick", 3, beat_index=1)])
        self.assertEqual(out["placement_count"], 0)
        self.assertIn("never moved somewhere it fits better", out["unplaced"][0]["reason"])

    def test_a_weak_match_is_refused_rather_than_laundered(self) -> None:
        out = bp.place(BEATS, [cand("weak", 3, relevance=0.1)])
        self.assertEqual(out["placement_count"], 0)
        self.assertIn("launder a weak match", out["unplaced"][0]["reason"])

    def test_relevance_is_reported_as_the_callers_not_ours(self) -> None:
        out = bp.place(BEATS, [cand("b1", 3, relevance=0.9)])
        self.assertIn("not re-scored here", out["placements"][0]["relevance_source"])

    def test_a_candidate_with_no_relevance_is_still_placed(self) -> None:
        """A human's explicit pick has no score and must not need one."""
        out = bp.place(BEATS, [cand("b1", 3)])
        self.assertEqual(out["placement_count"], 1)
        self.assertIsNone(out["placements"][0]["relevance"])

    def test_reuse_is_off_by_default_and_can_be_enabled(self) -> None:
        pair = [cand("same", 3), cand("same", 3)]
        self.assertEqual(bp.place(BEATS, pair)["placement_count"], 1)
        self.assertEqual(bp.place(BEATS, pair, allow_reuse=True)["placement_count"], 2)

    def test_a_too_short_candidate_is_refused(self) -> None:
        out = bp.place(BEATS, [cand("flash", 0.2)])
        self.assertIn("under the", out["unplaced"][0]["reason"])

    def test_running_out_of_windows_is_reported_not_silent(self) -> None:
        out = bp.place([beat(0, 5)], [cand("a", 3), cand("b", 3)])
        self.assertEqual(out["placement_count"], 1)
        self.assertIn("no uncovered window", out["unplaced"][0]["reason"])


class ReportingTests(unittest.TestCase):
    def test_uncovered_windows_are_surfaced(self) -> None:
        out = bp.place(BEATS, [cand("b1", 3)])
        self.assertEqual(len(out["uncovered_windows"]), 2)

    def test_the_note_states_it_does_not_judge_relevance(self) -> None:
        note = bp.place(BEATS, [cand("b1", 3)])["note"]
        self.assertIn("not re-scored here", note)
        self.assertIn("Nothing is cut", note)

    def test_empty_inputs_are_distinct_errors(self) -> None:
        self.assertIn("beats", bp.place([], [cand("a", 3)])["error"])
        self.assertIn("candidates", bp.place(BEATS, [])["error"])


if __name__ == "__main__":
    unittest.main()
