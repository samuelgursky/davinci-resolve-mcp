"""Tests for take ranking.

The dangerous version of this feature ranks takes and calls the top one "best".
Two viewers of the first public tutorial asked for take selection and one
immediately answered himself: "I'd trust it even less to choose the right take."
He is right — fluency is measurable, performance is not, and the take that plays
is regularly the one that stumbles.

So most of what is pinned below is the honesty, not the arithmetic.
"""

from __future__ import annotations

import unittest

from src.utils import take_ranking as tr


def words(*spec):
    return [
        {"word": w, "start_seconds": float(s), "end_seconds": float(e)}
        for w, s, e in spec
    ]


CLEAN = words(
    ("We", 0, .3), ("went", .3, .7), ("to", .7, .9), ("the", .9, 1.1),
    ("harbour", 1.1, 1.8), ("at", 1.8, 2.0), ("dawn.", 2.0, 2.6),
    ("It", 2.6, 2.9), ("was", 2.9, 3.2), ("quiet.", 3.2, 4.0),
)
MESSY = words(
    ("We", 0, .3), ("uh", .4, .7), ("we", .8, 1.0), ("went", 1.0, 1.4),
    ("um", 1.5, 1.9), ("to", 2.0, 2.2), ("the", 2.2, 2.4),
    ("harbour", 2.4, 3.0), ("at", 3.0, 3.2), ("dawn.", 3.2, 4.0),
)
STUB = words(("We", 0, .3), ("went", .3, .7))
SCRIPT = "We went to the harbour at dawn. It was quiet."


class HonestyTests(unittest.TestCase):
    """The parts that stop this being a misleading tool."""

    def test_it_never_claims_a_best_take(self) -> None:
        out = tr.rank_takes([{"label": "A", "words": CLEAN}])
        self.assertEqual(out["ranked_by"], "fluency")
        self.assertIn("most_fluent", out)
        self.assertNotIn("best_take", out)

    def test_the_caveat_is_attached_to_every_ranking(self) -> None:
        out = tr.rank_takes([{"label": "A", "words": CLEAN}])
        self.assertIn("not quality", out["caveat"].lower())
        self.assertIn("performance", out["caveat"].lower())

    def test_the_note_says_fluent_is_not_best(self) -> None:
        out = tr.rank_takes([{"label": "A", "words": CLEAN}])
        self.assertIn("NOT the same as the best", out["note"])

    def test_components_are_published_alongside_the_score(self) -> None:
        """A weighting nobody can read is not reviewable."""
        take = tr.score_take(MESSY, label="A")
        for field in ("filler_count", "false_start_count", "fillers_per_minute",
                      "longest_fluent_run_seconds", "evidence"):
            self.assertIn(field, take)


class ScoringTests(unittest.TestCase):
    def test_a_clean_read_outranks_a_disfluent_one(self) -> None:
        out = tr.rank_takes(
            [{"label": "messy", "words": MESSY}, {"label": "clean", "words": CLEAN}]
        )
        self.assertEqual(out["takes"][0]["label"], "clean")
        self.assertEqual(out["most_fluent"], "clean")

    def test_a_take_too_short_to_measure_is_flagged_not_dropped(self) -> None:
        """Dropping it hides it; scoring it pretends 0.7s means something."""
        out = tr.rank_takes(
            [{"label": "stub", "words": STUB}, {"label": "clean", "words": CLEAN}]
        )
        stub = next(t for t in out["takes"] if t["label"] == "stub")
        self.assertFalse(stub["reliable"])
        self.assertIn("too short", stub["caveat"])
        self.assertEqual(stub["rank"], 2, "unmeasurable sorts last, but is still listed")
        self.assertIn("stub", out["unreliable_takes"])

    def test_script_coverage_is_measured_when_a_script_is_given(self) -> None:
        take = tr.score_take(CLEAN, label="A", script=SCRIPT)
        self.assertEqual(take["script_coverage"]["ratio"], 1.0)

    def test_a_dried_take_shows_low_coverage_and_what_is_missing(self) -> None:
        take = tr.score_take(STUB, label="A", script=SCRIPT)
        self.assertLess(take["script_coverage"]["ratio"], 0.5)
        self.assertIn("harbour", take["script_coverage"]["missing_sample"])

    def test_coverage_is_order_insensitive(self) -> None:
        """Penalising paraphrase would rank a stumbling literal read higher."""
        shuffled = words(
            ("quiet.", 0, .4), ("was", .4, .8), ("It", .8, 1.2), ("dawn.", 1.2, 1.8),
            ("at", 1.8, 2.0), ("harbour", 2.0, 2.6), ("the", 2.6, 2.8),
            ("to", 2.8, 3.0), ("went", 3.0, 3.4), ("We", 3.4, 3.8),
        )
        self.assertEqual(
            tr.score_take(shuffled, label="A", script=SCRIPT)["script_coverage"]["ratio"], 1.0
        )

    def test_no_script_means_no_coverage_claim(self) -> None:
        self.assertIsNone(tr.score_take(CLEAN, label="A")["script_coverage"])

    def test_longest_clean_run_shrinks_when_disfluencies_interrupt(self) -> None:
        self.assertGreater(
            tr.score_take(CLEAN, label="c")["longest_fluent_run_seconds"],
            tr.score_take(MESSY, label="m")["longest_fluent_run_seconds"],
        )


class EdgeCaseTests(unittest.TestCase):
    def test_no_takes_is_an_error(self) -> None:
        self.assertFalse(tr.rank_takes([])["success"])

    def test_an_empty_take_does_not_crash(self) -> None:
        out = tr.rank_takes([{"label": "silent", "words": []}])
        self.assertTrue(out["success"])
        self.assertFalse(out["takes"][0]["reliable"])

    def test_ranks_are_contiguous_from_one(self) -> None:
        out = tr.rank_takes([
            {"label": "a", "words": CLEAN},
            {"label": "b", "words": MESSY},
            {"label": "c", "words": STUB},
        ])
        self.assertEqual([t["rank"] for t in out["takes"]], [1, 2, 3])

    def test_singular_wording_when_one_take_is_unmeasurable(self) -> None:
        out = tr.rank_takes(
            [{"label": "stub", "words": STUB}, {"label": "clean", "words": CLEAN}]
        )
        self.assertIn("1 take was", out["note"])


if __name__ == "__main__":
    unittest.main()
