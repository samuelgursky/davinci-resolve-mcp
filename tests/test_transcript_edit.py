"""Tests for src/utils/transcript_edit.py — word-level cut plans and search."""

from __future__ import annotations

import unittest

from src.utils import transcript_edit as te


def words(*spec):
    """(word, start, end) triples → the transcript_words row shape."""
    return [
        {"word": w, "start_seconds": float(s), "end_seconds": float(e)}
        for w, s, e in spec
    ]


class FalseStartTests(unittest.TestCase):
    def test_single_word_stammer_is_found(self) -> None:
        stream = words(("I", 0.0, 0.15), ("I", 0.25, 0.45), ("went", 0.5, 0.9))
        hits = te.detect_false_starts(stream)
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0]["start_seconds"], 0.0)
        self.assertAlmostEqual(hits[0]["end_seconds"], 0.15)  # only the FIRST run

    def test_evenly_spaced_repetition_survives(self) -> None:
        # "no, no, no" as emphasis — spoken with real gaps, must not be cut.
        stream = words(("no", 0.0, 0.4), ("no", 1.2, 1.6), ("no", 2.4, 2.8))
        self.assertEqual(te.detect_false_starts(stream), [])

    def test_multi_word_restart_is_one_hit_not_three(self) -> None:
        stream = words(
            ("I", 0.0, 0.1), ("think", 0.1, 0.3), ("that", 0.3, 0.45),
            ("I", 0.5, 0.6), ("think", 0.6, 0.8), ("that", 0.8, 0.95),
            ("we", 1.0, 1.2),
        )
        hits = te.detect_false_starts(stream)
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0]["words"], "I think that")
        self.assertEqual(hits[0]["confidence"], "medium")

    def test_longest_run_wins_over_nested_repeats(self) -> None:
        stream = words(
            ("we", 0.0, 0.1), ("went", 0.1, 0.3),
            ("we", 0.35, 0.45), ("went", 0.45, 0.65), ("home", 0.7, 1.0),
        )
        hits = te.detect_false_starts(stream)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["words"], "we went")

    def test_punctuation_and_case_do_not_block_a_match(self) -> None:
        stream = words(("The,", 0.0, 0.1), ("the", 0.15, 0.3), ("dog", 0.35, 0.6))
        self.assertEqual(len(te.detect_false_starts(stream)), 1)

    def test_words_without_timings_are_skipped(self) -> None:
        stream = [{"word": "I"}, {"word": "I"}]
        self.assertEqual(te.detect_false_starts(stream), [])


class FillerAndPauseTests(unittest.TestCase):
    def test_fillers_are_found_mid_phrase(self) -> None:
        stream = words(("so", 0.0, 0.2), ("um", 0.3, 0.6), ("anyway", 0.7, 1.2))
        hits = te.detect_fillers(stream)
        self.assertEqual([h["words"] for h in hits], ["um"])

    def test_filler_set_agrees_with_the_strata_analyzer(self) -> None:
        from src.utils.strata_analyzers import HESITATION_WORDS

        self.assertEqual(set(te.FILLER_WORDS), set(HESITATION_WORDS))

    def test_long_pause_is_collapsed_with_handles(self) -> None:
        stream = words(("one", 0.0, 0.5), ("two", 3.0, 3.5))
        hits = te.detect_long_pauses(stream, max_pause=0.6, handle=0.15, min_cut=0.15)
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0]["start_seconds"], 0.65)
        self.assertAlmostEqual(hits[0]["end_seconds"], 2.85)

    def test_short_pause_is_left_alone(self) -> None:
        stream = words(("one", 0.0, 0.5), ("two", 0.9, 1.4))
        self.assertEqual(te.detect_long_pauses(stream, max_pause=0.6, handle=0.15, min_cut=0.15), [])


class CutPlanTests(unittest.TestCase):
    STREAM = words(
        ("So", 0.0, 0.3),
        ("um", 0.4, 0.7),
        ("I", 0.8, 0.9),
        ("I", 1.0, 1.2),
        ("went", 1.3, 1.7),
        ("home", 5.0, 5.5),
    )

    def test_every_removal_states_a_reason(self) -> None:
        plan = te.plan_transcript_cuts(self.STREAM)
        self.assertTrue(plan["success"])
        self.assertTrue(plan["removals"])
        for entry in plan["removals"]:
            self.assertTrue(entry["reasons"], entry)
            for reason in entry["reasons"]:
                self.assertIsInstance(reason, str)
                self.assertTrue(reason.strip())

    def test_all_three_signals_are_counted(self) -> None:
        counts = te.plan_transcript_cuts(self.STREAM)["counts"]
        self.assertEqual(counts["filler"], 1)
        self.assertEqual(counts["false_start"], 1)
        self.assertEqual(counts["pause"], 1)

    def test_keep_ranges_are_ordered_and_non_overlapping(self) -> None:
        keep = te.plan_transcript_cuts(self.STREAM)["keep_ranges"]
        for previous, following in zip(keep, keep[1:]):
            self.assertLessEqual(previous["end"], following["start"])
        for entry in keep:
            self.assertLess(entry["start"], entry["end"])

    def test_arithmetic_is_consistent(self) -> None:
        plan = te.plan_transcript_cuts(self.STREAM)
        kept = sum(r["end"] - r["start"] for r in plan["keep_ranges"])
        self.assertAlmostEqual(kept, plan["tightened_duration_seconds"], places=3)
        self.assertAlmostEqual(
            plan["removed_seconds"] + plan["tightened_duration_seconds"],
            plan["source_duration_seconds"],
            places=3,
        )

    def test_each_signal_can_be_disabled(self) -> None:
        plan = te.plan_transcript_cuts(
            self.STREAM, remove_fillers=False, remove_false_starts=False, collapse_pauses=False
        )
        self.assertEqual(plan["removals"], [])
        self.assertEqual(plan["keep_ranges"], [{"start": 0.0, "end": 5.5}])

    def test_overlapping_removals_merge_and_keep_both_reasons(self) -> None:
        # A filler landing inside a collapsed pause must be one cut, not two.
        stream = words(("a", 0.0, 0.2), ("um", 1.0, 1.4), ("b", 4.0, 4.4))
        plan = te.plan_transcript_cuts(stream, max_pause=0.3, handle=0.05, min_cut=0.05)
        overlapping = [r for r in plan["removals"] if len(r["reasons"]) > 1]
        self.assertTrue(overlapping, plan["removals"])
        self.assertTrue(
            any("filler" in r and "pause" in " ".join(o["reasons"]) for o in overlapping for r in o["reasons"]),
            overlapping,
        )

    def test_slivers_between_cuts_are_bridged_not_kept(self) -> None:
        # Two cuts either side of a 25ms fragment would leave an unusable clip
        # and two extra edit points. The fragment is absorbed instead.
        stream = words(("a", 0.0, 0.2), ("um", 0.3, 0.6), ("b", 4.0, 4.4))
        plan = te.plan_transcript_cuts(stream, max_pause=0.6, handle=0.05, min_cut=0.05)
        self.assertEqual(len(plan["removals"]), 1, plan["removals"])
        self.assertEqual(len(plan["removals"][0]["reasons"]), 2)
        for entry in plan["keep_ranges"]:
            self.assertGreaterEqual(entry["end"] - entry["start"], 0.05, plan["keep_ranges"])

    def test_empty_transcript_refuses_rather_than_returning_an_empty_plan(self) -> None:
        plan = te.plan_transcript_cuts([])
        self.assertFalse(plan["success"])
        self.assertIn("transcription", plan["error"])

    def test_nothing_is_executed(self) -> None:
        self.assertIn("Proposal only", te.plan_transcript_cuts(self.STREAM)["note"])


class SearchTests(unittest.TestCase):
    STREAM = words(
        ("We", 0.0, 0.2), ("shot", 0.3, 0.6), ("the", 0.7, 0.8), ("sunset", 0.9, 1.4),
        ("then", 2.0, 2.3), ("the", 2.4, 2.5), ("sunset", 2.6, 3.0), ("faded", 3.1, 3.6),
    )

    def test_phrase_mode_finds_consecutive_runs(self) -> None:
        hits = te.search_words(self.STREAM, "the sunset", mode="phrase")
        self.assertEqual(len(hits), 2)
        self.assertAlmostEqual(hits[0]["start_seconds"], 0.7)
        self.assertEqual(hits[0]["text"], "the sunset")

    def test_phrase_mode_does_not_match_out_of_order(self) -> None:
        self.assertEqual(te.search_words(self.STREAM, "sunset the", mode="phrase"), [])

    def test_all_words_mode_gates_at_clip_level(self) -> None:
        self.assertTrue(te.search_words(self.STREAM, "shot faded", mode="all_words"))
        # 'helicopter' is absent, so the AND gate yields nothing at all.
        self.assertEqual(te.search_words(self.STREAM, "shot helicopter", mode="all_words"), [])

    def test_regex_mode_maps_back_to_word_timings(self) -> None:
        hits = te.search_words(self.STREAM, r"sun\w+", mode="regex")
        self.assertEqual(len(hits), 2)
        self.assertAlmostEqual(hits[0]["start_seconds"], 0.9)

    def test_search_is_case_and_punctuation_insensitive(self) -> None:
        stream = words(("Sunset,", 0.0, 0.4), ("faded", 0.5, 0.9))
        self.assertEqual(len(te.search_words(stream, "sunset", mode="phrase")), 1)

    def test_context_widens_beyond_the_hit(self) -> None:
        hit = te.search_words(self.STREAM, "sunset", mode="phrase", context_seconds=1.5)[0]
        self.assertLess(hit["context_start_seconds"], hit["start_seconds"])
        self.assertIn("shot", hit["context"])

    def test_unknown_mode_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            te.search_words(self.STREAM, "x", mode="fuzzy")

    def test_empty_query_yields_nothing_rather_than_everything(self) -> None:
        self.assertEqual(te.search_words(self.STREAM, "   ", mode="phrase"), [])
        self.assertEqual(te.search_words(self.STREAM, "   ", mode="all_words"), [])


class BreathingRoomTests(unittest.TestCase):
    """A pause is craft or noise depending on where it sits, not how long it is.

    Acoustically these are identical, which is why a silence gate cannot tell
    them apart and why an automated tighten built on one reads as machine-made:

      "...and that changed everything."  [900 ms]  "The thing is..."
      "...the thing is"                  [900 ms]  "we had to leave"

    The first is the beat that lets the line land. The second is a stumble.
    """

    PAUSE = dict(max_pause=0.6, handle=0.15, min_cut=0.15)

    def _beat_and_stumble(self):
        # 0.9 s gap after a full stop, and a 0.9 s gap mid-phrase.
        return words(
            ("everything.", 0.0, 1.0),
            ("The", 1.9, 2.1),
            ("thing", 2.1, 2.5),
            ("is", 2.5, 2.7),
            ("we", 3.6, 3.8),
            ("left", 3.8, 4.2),
        )

    def test_a_beat_after_a_full_stop_is_preserved(self) -> None:
        cuts = te.detect_long_pauses(self._beat_and_stumble(), **self.PAUSE)
        positions = [c["pause_position"] for c in cuts]
        self.assertNotIn("sentence_final", positions)

    def test_the_same_gap_mid_phrase_is_removed(self) -> None:
        cuts = te.detect_long_pauses(self._beat_and_stumble(), **self.PAUSE)
        self.assertEqual([c["pause_position"] for c in cuts], ["intra_clause"])

    def test_old_behaviour_removes_both_indiscriminately(self) -> None:
        """Pins what preserve_breathing_room=False means, and what we moved off."""
        cuts = te.detect_long_pauses(
            self._beat_and_stumble(), preserve_breathing_room=False, **self.PAUSE
        )
        self.assertEqual(len(cuts), 2)

    def test_a_genuinely_dead_hole_after_a_full_stop_is_still_cut(self) -> None:
        """Breathing room is a longer threshold, not an exemption."""
        stream = words(("everything.", 0.0, 1.0), ("Then", 5.0, 5.4))
        cuts = te.detect_long_pauses(stream, **self.PAUSE)
        self.assertEqual(len(cuts), 1)
        self.assertEqual(cuts[0]["pause_position"], "sentence_final")

    def test_clause_breaks_sit_between_the_two(self) -> None:
        self.assertLess(
            te.CLAUSE_PAUSE_MULTIPLIER, te.BREATHING_ROOM_MULTIPLIER
        )
        self.assertGreater(te.CLAUSE_PAUSE_MULTIPLIER, 1.0)
        self.assertEqual(
            te.classify_pause({"word": "however,"}, None)["position"], "clause_final"
        )

    def test_unpunctuated_transcript_is_flagged_not_silently_stripped(self) -> None:
        """Without punctuation every pause looks intra-clause. Say so."""
        stream = words(("the", 0.0, 0.3), ("thing", 1.5, 1.9))
        self.assertFalse(te.transcript_is_punctuated(stream))
        cuts = te.detect_long_pauses(stream, **self.PAUSE)
        self.assertEqual(cuts[0]["pause_position"], "unpunctuated")
        self.assertEqual(cuts[0]["confidence"], "low")
        self.assertIn("review", cuts[0]["classification_reason"])

    def test_every_pause_carries_a_reason(self) -> None:
        """Reason-per-cut is the house contract; classification must honour it."""
        for cut in te.detect_long_pauses(self._beat_and_stumble(), **self.PAUSE):
            self.assertTrue(cut["classification_reason"].strip())
            self.assertIn("threshold_seconds", cut)


if __name__ == "__main__":
    unittest.main()
