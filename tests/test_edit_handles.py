"""Tests for handle accounting — the media beyond an edit point.

An automatic tighten has no notion of handles: a keep range starting on frame 0
of a clip is, to a silence-removal objective, a perfect result. It is also a
join that cannot be dissolved, slipped or crossfaded, and that fact surfaces
weeks later in someone else's suite, after picture lock.
"""

from __future__ import annotations

import unittest

from src.utils import edit_handles as eh


def rng(clip_id, start, end, track_type="video"):
    return {
        "clip_id": clip_id,
        "start_frame": start,
        "end_frame": end,
        "track_type": track_type,
    }


class HandleFloorTests(unittest.TestCase):
    def test_audio_needs_far_more_than_picture(self) -> None:
        """Crossfades, room tone and dialogue overlap all reach past the cut."""
        self.assertGreater(
            eh.DEFAULT_AUDIO_HANDLE_FRAMES, eh.DEFAULT_PICTURE_HANDLE_FRAMES
        )
        self.assertEqual(eh.handle_floor_for("audio"), eh.DEFAULT_AUDIO_HANDLE_FRAMES)
        self.assertEqual(eh.handle_floor_for("video"), eh.DEFAULT_PICTURE_HANDLE_FRAMES)
        self.assertEqual(eh.handle_floor_for(None), eh.DEFAULT_PICTURE_HANDLE_FRAMES)


class KeepRangeHandleTests(unittest.TestCase):
    BOUNDS = {"A": 1000}

    def test_a_comfortable_range_is_clean(self) -> None:
        out = eh.check_keep_range_handles([rng("A", 100, 900)], source_bounds=self.BOUNDS)
        self.assertTrue(out["clean"])
        self.assertEqual(out["violation_count"], 0)
        self.assertIn("leave usable handles", out["note"])

    def test_a_range_starting_at_frame_zero_is_flagged(self) -> None:
        """The silence-removal objective calls this perfect. Turnover does not."""
        out = eh.check_keep_range_handles([rng("A", 0, 900)], source_bounds=self.BOUNDS)
        self.assertFalse(out["clean"])
        self.assertEqual(out["violations"][0]["short_at"], "head")
        self.assertEqual(out["violations"][0]["head_frames"], 0)

    def test_a_range_running_to_the_last_frame_is_flagged(self) -> None:
        out = eh.check_keep_range_handles([rng("A", 100, 1000)], source_bounds=self.BOUNDS)
        self.assertEqual(out["violations"][0]["short_at"], "tail")

    def test_a_range_using_the_whole_clip_is_short_at_both_ends(self) -> None:
        out = eh.check_keep_range_handles([rng("A", 0, 1000)], source_bounds=self.BOUNDS)
        self.assertEqual(out["violations"][0]["short_at"], "both")

    def test_audio_is_held_to_the_larger_floor(self) -> None:
        """20 frames is fine for picture and nowhere near enough for sound."""
        picture = eh.check_keep_range_handles(
            [rng("A", 20, 980, "video")], source_bounds=self.BOUNDS
        )
        audio = eh.check_keep_range_handles(
            [rng("A", 20, 980, "audio")], source_bounds=self.BOUNDS
        )
        self.assertTrue(picture["clean"])
        self.assertFalse(audio["clean"])
        self.assertEqual(audio["violations"][0]["required_frames"], eh.DEFAULT_AUDIO_HANDLE_FRAMES)

    def test_an_unknown_source_length_is_unverified_not_clean(self) -> None:
        """The whole failure mode is assuming the unmeasured case is fine."""
        out = eh.check_keep_range_handles([rng("MISSING", 100, 200)], source_bounds=self.BOUNDS)
        self.assertFalse(out["clean"])
        self.assertEqual(out["violation_count"], 0, "unverified is not a violation")
        self.assertEqual(len(out["unverified"]), 1)
        self.assertIn("not the same as clean", out["note"])

    def test_malformed_ranges_are_reported_not_skipped(self) -> None:
        out = eh.check_keep_range_handles(
            [{"clip_id": "A", "start_frame": None, "end_frame": 200}],
            source_bounds=self.BOUNDS,
        )
        self.assertFalse(out["clean"])
        self.assertEqual(len(out["unverified"]), 1)

    def test_floors_are_caller_overridable(self) -> None:
        """A show with its own turnover spec must be able to state it."""
        out = eh.check_keep_range_handles(
            [rng("A", 4, 996)], source_bounds=self.BOUNDS, picture_handle_frames=2
        )
        self.assertTrue(out["clean"])

    def test_empty_plan_is_clean_but_says_so_honestly(self) -> None:
        out = eh.check_keep_range_handles([], source_bounds=self.BOUNDS)
        self.assertTrue(out["clean"])
        self.assertEqual(out["checked_range_count"], 0)


class SecondsRangeTests(unittest.TestCase):
    """The word-level cut path works in seconds and needs the same rule.

    Deciding a cut from a transcript rather than a waveform does not give sound
    anything to crossfade with.
    """

    def test_a_comfortable_range_is_clean(self) -> None:
        out = eh.check_seconds_ranges(
            [{"start": 2.0, "end": 8.0}], source_duration_seconds=12.0
        )
        self.assertTrue(out["clean"])

    def test_a_range_starting_at_zero_is_flagged(self) -> None:
        out = eh.check_seconds_ranges(
            [{"start": 0.0, "end": 8.0}], source_duration_seconds=12.0
        )
        self.assertEqual(out["violations"][0]["short_at"], "head")

    def test_a_range_ending_at_the_clip_end_is_flagged(self) -> None:
        out = eh.check_seconds_ranges(
            [{"start": 2.0, "end": 12.0}], source_duration_seconds=12.0
        )
        self.assertEqual(out["violations"][0]["short_at"], "tail")

    def test_an_unknown_duration_is_unverified_not_clean(self) -> None:
        out = eh.check_seconds_ranges(
            [{"start": 2.0, "end": 8.0}], source_duration_seconds=None
        )
        self.assertFalse(out["clean"])
        self.assertTrue(out["unverified"])
        self.assertIn("Unverified is not clean", out["note"])

    def test_the_alternate_key_spelling_is_accepted(self) -> None:
        out = eh.check_seconds_ranges(
            [{"start_seconds": 2.0, "end_seconds": 8.0}], source_duration_seconds=12.0
        )
        self.assertEqual(out["checked_range_count"], 1)


if __name__ == "__main__":
    unittest.main()
