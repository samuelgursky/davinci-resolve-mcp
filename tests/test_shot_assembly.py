"""Tests for speechless assembly and no-script structure.

A viewer predicted the failure this module exists to avoid, before anyone tried
it: point a speech-silence gate at motorsport footage and engine noise reads as
content while a quiet straight reads as dead space. The cuts land nowhere near
the material's actual structure, which is shots and motion.
"""

from __future__ import annotations

import unittest

from src.utils import shot_assembly as sa


def shot(name, start, end, motion=None):
    out = {"name": name, "start_seconds": start, "end_seconds": end}
    if motion is not None:
        out["motion_energy"] = motion
    return out


class ShotRankingTests(unittest.TestCase):
    SHOTS = [
        shot("wide", 0, 12, 0.02),
        shot("action", 12, 18, 0.8),
        shot("flash", 18, 18.2, 0.5),
        shot("unmeasured", 20, 30),
    ]

    def test_flash_frames_are_rejected_with_a_reason(self) -> None:
        out = sa.rank_shots(self.SHOTS)
        self.assertEqual(len(out["rejected"]), 1)
        self.assertIn("flash frame", out["rejected"][0]["reason"])

    def test_the_most_active_shot_ranks_first(self) -> None:
        self.assertEqual(sa.rank_shots(self.SHOTS)["shots"][0]["shot"], "action")

    def test_a_static_shot_is_described_not_penalised(self) -> None:
        wide = next(s for s in sa.rank_shots(self.SHOTS)["shots"] if s["shot"] == "wide")
        self.assertIn("not a fault", wide["character"])

    def test_unmeasured_is_not_treated_as_static(self) -> None:
        """A shot nobody measured is not a static shot."""
        out = sa.rank_shots(self.SHOTS)
        unmeasured = next(s for s in out["shots"] if s["shot"] == "unmeasured")
        self.assertIsNone(unmeasured["motion_energy"])
        self.assertFalse(unmeasured["motion_measured"])
        self.assertIn("not the same as static", unmeasured["character"])

    def test_unmeasured_shots_sort_last_but_are_kept(self) -> None:
        out = sa.rank_shots(self.SHOTS)
        self.assertEqual(out["shots"][-1]["shot"], "unmeasured")
        self.assertEqual(out["unmeasured_count"], 1)


class ClusterTests(unittest.TestCase):
    def test_a_long_gap_starts_a_new_cluster(self) -> None:
        clusters = sa.cluster_shots([
            shot("a", 0, 10), shot("b", 10, 20), shot("c", 300, 310),
        ])
        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0]["shot_count"], 2)

    def test_contiguous_shots_stay_in_one_cluster(self) -> None:
        self.assertEqual(len(sa.cluster_shots([shot("a", 0, 10), shot("b", 10, 20)])), 1)


class StringOutTests(unittest.TestCase):
    SHOTS = [shot("a", 0, 10, 0.1), shot("b", 10, 20, 0.9), shot("c", 20, 30, 0.5)]

    def test_chronological_is_the_default_order(self) -> None:
        out = sa.plan_string_out(self.SHOTS)
        self.assertEqual(out["order"], "chronological")
        self.assertEqual([s["shot"] for s in out["sequence"]], ["a", "b", "c"])

    def test_activity_order_puts_the_movement_first(self) -> None:
        out = sa.plan_string_out(self.SHOTS, order="activity")
        self.assertEqual(out["sequence"][0]["shot"], "b")

    def test_it_never_claims_to_be_a_cut(self) -> None:
        self.assertIn("not a cut", sa.plan_string_out(self.SHOTS)["note"])

    def test_it_says_ranking_by_movement_is_not_an_edit(self) -> None:
        """A locked-off wide may be the most important shot and ranks last."""
        note = sa.plan_string_out(self.SHOTS)["note"]
        self.assertIn("measurement, not an edit", note)
        self.assertIn("locked-off wide", note)

    def test_it_explains_why_silence_is_the_wrong_instrument(self) -> None:
        note = sa.plan_string_out(self.SHOTS)["note"]
        self.assertIn("engine noise", note)

    def test_clustering_declares_itself_a_proxy(self) -> None:
        self.assertIn("PROXY", sa.plan_string_out(self.SHOTS)["clustering_basis"])

    def test_an_unknown_order_is_rejected(self) -> None:
        self.assertFalse(sa.plan_string_out(self.SHOTS, order="vibes")["success"])

    def test_no_shots_and_all_too_short_are_distinct_errors(self) -> None:
        self.assertIn("No shots supplied", sa.plan_string_out([])["error"])
        tiny = sa.plan_string_out([shot("x", 0, 0.2)])
        self.assertIn("long enough", tiny["error"])
        self.assertTrue(tiny["rejected"], "rejected shots must still be reported")


class NoScriptStructureTests(unittest.TestCase):
    TOPICS = [
        {"label": "build", "total_seconds": 300, "clip_count": 12},
        {"label": "interview", "total_seconds": 120, "clip_count": 4},
        {"label": "aside", "total_seconds": 2, "clip_count": 1},
    ]

    def setUp(self) -> None:
        self.out = sa.propose_structure(self.TOPICS)

    def test_approval_is_required_and_flagged(self) -> None:
        self.assertTrue(self.out["requires_approval"])
        self.assertIn("nothing is cut", self.out["note"].lower())

    def test_the_ordering_basis_admits_what_it_measures(self) -> None:
        """Coverage is what was shot, not what matters."""
        self.assertIn("not of what matters", self.out["basis"])

    def test_topics_are_ordered_by_coverage(self) -> None:
        self.assertEqual(self.out["proposed_order"][0]["label"], "build")

    def test_thin_topics_are_set_aside_not_deleted(self) -> None:
        self.assertEqual([t["label"] for t in self.out["thin_topics"]], ["aside"])
        self.assertIn("not deleted", self.out["note"])

    def test_no_topics_is_an_error(self) -> None:
        self.assertFalse(sa.propose_structure([])["success"])


if __name__ == "__main__":
    unittest.main()
