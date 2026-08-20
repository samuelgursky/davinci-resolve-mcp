"""The stretched-word flag for swallowed retakes (issue #125).

The bar is deliberately absolute. Two better-sounding designs were measured and
failed on English material — a chars/s gate (0 of 50 segments) and per-word
self-calibration (missed the swallow, 8 false positives, all function words) —
so these tests pin the shape that survived, including the reasons the others
did not.
"""

import unittest

from src.utils.swallowed_retakes import (
    DEFAULT_MIN_WORD_SECONDS,
    find_swallowed_retake_candidates,
    swallowed_retake_report,
)


def words(*spans):
    """(text, start, end) -> transcript_words-shaped rows."""
    return [
        {"word": text, "start_seconds": start, "end_seconds": end}
        for text, start, end in spans
    ]


class FindCandidatesTest(unittest.TestCase):
    def test_flags_the_stretched_word_only(self):
        rows = words(
            ("the", 0.0, 0.18),
            ("model", 0.18, 0.62),
            ("lives", 0.62, 6.68),  # the swallow: 6.06s on one content word
            ("here", 6.68, 6.95),
        )
        found = find_swallowed_retake_candidates(rows)

        self.assertEqual([c["word"] for c in found], ["lives"])
        self.assertAlmostEqual(found[0]["duration_seconds"], 6.06, places=2)

    def test_ordinary_speech_produces_nothing(self):
        rows = words(*[(f"w{i}", i * 0.3, i * 0.3 + 0.28) for i in range(40)])
        self.assertEqual(find_swallowed_retake_candidates(rows), [])

    def test_bar_is_inclusive_at_the_threshold(self):
        rows = words(("x", 0.0, DEFAULT_MIN_WORD_SECONDS))
        self.assertEqual(len(find_swallowed_retake_candidates(rows)), 1)

        rows = words(("x", 0.0, DEFAULT_MIN_WORD_SECONDS - 0.01))
        self.assertEqual(find_swallowed_retake_candidates(rows), [])

    def test_accepts_raw_whisper_word_shape(self):
        """Words arrive as DB rows or as whisper dicts; both must work."""
        raw = [{"word": "lives", "start": 0.62, "end": 6.68}]
        self.assertEqual(len(find_swallowed_retake_candidates(raw)), 1)

    def test_rows_missing_an_endpoint_are_skipped_not_guessed(self):
        rows = [
            {"word": "a", "start_seconds": 0.0},
            {"word": "b", "end_seconds": 9.0},
            {"word": "c"},
            "not a mapping",
        ]
        self.assertEqual(find_swallowed_retake_candidates(rows), [])

    def test_results_are_time_ordered(self):
        rows = words(("late", 30.0, 33.0), ("early", 2.0, 5.0))
        found = find_swallowed_retake_candidates(rows)
        self.assertEqual([c["word"] for c in found], ["early", "late"])

    def test_language_agnostic_short_text_still_flags(self):
        """A single CJK character spanning 6s must flag.

        This is the case the retired chars/s gate was built for and the case an
        English-tuned rate gate would miss: one character, enormous duration.
        """
        rows = words(("处", 10.0, 16.06))
        self.assertEqual(len(find_swallowed_retake_candidates(rows)), 1)

    def test_repeated_function_words_do_not_flag(self):
        """The false positives self-calibration produced must not appear here.

        Per-word z-scoring flagged 8 function words on prosody variance alone.
        An absolute bar is indifferent to how often a word recurs.
        """
        rows = words(*[("the", i * 0.5, i * 0.5 + 0.4) for i in range(20)])
        self.assertEqual(find_swallowed_retake_candidates(rows), [])


class ReportTest(unittest.TestCase):
    def test_report_carries_the_caveat_both_ways(self):
        empty = swallowed_retake_report(words(("hi", 0.0, 0.3)))
        self.assertEqual(empty["count"], 0)
        self.assertIn("not proof", empty["note"])
        self.assertIn("not a cut point", empty["caveat"])

        hit = swallowed_retake_report(words(("lives", 0.0, 6.0)))
        self.assertEqual(hit["count"], 1)
        self.assertIn("issue #125", hit["note"])

    def test_report_never_emits_a_cut_point(self):
        """A flag, not a fabricated edit — the whole design constraint.

        Checked against the emitted FIELDS, not the prose: the caveat is allowed
        to talk about removal precisely because it is telling a caller not to.
        """
        hit = swallowed_retake_report(words(("lives", 0.0, 6.0)))
        for forbidden in ("keep_ranges", "cut_at", "record_frame", "ranges"):
            self.assertNotIn(forbidden, hit)
        self.assertEqual(
            set(hit["candidates"][0]),
            {"word_index", "word", "start_seconds", "end_seconds",
             "duration_seconds", "reason"},
        )

    def test_threshold_is_overridable(self):
        rows = words(("x", 0.0, 0.9))
        self.assertEqual(swallowed_retake_report(rows)["count"], 0)
        self.assertEqual(
            swallowed_retake_report(rows, min_word_seconds=0.5)["count"], 1
        )


if __name__ == "__main__":
    unittest.main()
