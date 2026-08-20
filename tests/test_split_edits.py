"""Tests for split-edit detection — sound leads picture.

The direction convention is the part worth pinning, because it is easy to get
backwards and impossible to notice once it is:

  L-cut: audio edit LATER than picture  → outgoing sound continues → lingers
  J-cut: audio edit EARLIER than picture → incoming sound arrives  → pulls forward
"""

from __future__ import annotations

import unittest

from src.utils import split_edits as se


def track(*boundaries):
    """Boundary frames → contiguous items on one track."""
    return [
        {"timeline_start_frame": a, "timeline_end_frame": b}
        for a, b in zip(boundaries, boundaries[1:])
    ]


class DirectionTests(unittest.TestCase):
    def test_audio_edit_later_than_picture_is_an_l_cut(self) -> None:
        out = se.classify_joins(track(0, 100, 200), track(0, 112, 200))
        join = next(j for j in out["joins"] if j["picture_frame"] == 100)
        self.assertEqual(join["shape"], se.SHAPE_L)
        self.assertEqual(join["offset_frames"], 12)
        self.assertIn("continues", join["meaning"])

    def test_audio_edit_earlier_than_picture_is_a_j_cut(self) -> None:
        out = se.classify_joins(track(0, 100, 200), track(0, 88, 200))
        join = next(j for j in out["joins"] if j["picture_frame"] == 100)
        self.assertEqual(join["shape"], se.SHAPE_J)
        self.assertEqual(join["offset_frames"], -12)
        self.assertIn("pulls forward", join["meaning"])

    def test_coincident_edits_are_a_straight_cut(self) -> None:
        out = se.classify_joins(track(0, 100, 200), track(0, 100, 200))
        self.assertTrue(all(j["shape"] == se.SHAPE_STRAIGHT for j in out["joins"]))


class ThresholdTests(unittest.TestCase):
    def test_a_one_frame_nudge_is_not_a_split_edit(self) -> None:
        """Somebody trimming audio is not sound leading picture."""
        out = se.classify_joins(track(0, 100, 200), track(0, 101, 200))
        join = next(j for j in out["joins"] if j["picture_frame"] == 100)
        self.assertEqual(join["shape"], se.SHAPE_STRAIGHT)

    def test_a_distant_audio_edit_is_unpaired_not_straight(self) -> None:
        """No audio edit near a picture cut means sound runs across it — a
        stronger form of sound carrying picture, and a different fact."""
        out = se.classify_joins(track(0, 100, 400), track(0, 300, 400))
        self.assertIn(100, out["unpaired_picture_cuts"])
        self.assertFalse(any(j["picture_frame"] == 100 for j in out["joins"]))


class AuditTests(unittest.TestCase):
    def test_an_all_straight_timeline_is_flagged(self) -> None:
        boundaries = list(range(0, 1100, 100))
        out = se.audit(track(*boundaries), track(*boundaries))
        self.assertTrue(out["findings"])
        self.assertIn("sound never leads picture", out["findings"][0]["summary"])

    def test_a_short_all_straight_timeline_is_not_flagged(self) -> None:
        """Three straight cuts is not evidence of anything."""
        boundaries = [0, 100, 200, 300]
        out = se.audit(track(*boundaries), track(*boundaries))
        self.assertFalse(out["findings"])

    def test_a_mixed_timeline_is_reported_without_a_finding(self) -> None:
        pic = list(range(0, 1100, 100))
        aud = [0, 112, 188, 300, 412, 500, 588, 700, 812, 900, 1000]
        out = se.audit(track(*pic), track(*aud))
        self.assertGreater(out["counts"][se.SHAPE_L], 0)
        self.assertGreater(out["counts"][se.SHAPE_J], 0)
        self.assertFalse(out["findings"])

    def test_no_correct_ratio_is_suggested(self) -> None:
        boundaries = list(range(0, 600, 100))
        note = se.audit(track(*boundaries), track(*boundaries))["note"]
        self.assertIn("NO correct ratio", note)
        self.assertIn("not a score", note)

    def test_missing_audio_refuses_rather_than_reporting_all_straight(self) -> None:
        """Reporting 'all straight' with no audio supplied would be a fabrication."""
        out = se.audit(track(0, 100, 200), [])
        self.assertFalse(out["success"])
        self.assertIn("fabrication", out["remediation"])

    def test_no_video_is_an_error(self) -> None:
        self.assertFalse(se.audit([], track(0, 100))["success"])

    def test_offsets_are_reported_in_seconds_too(self) -> None:
        out = se.audit(track(0, 100, 200), track(0, 112, 200), fps=24.0)
        join = next(j for j in out["joins"] if j["picture_frame"] == 100)
        self.assertAlmostEqual(join["offset_seconds"], 0.5, places=3)


if __name__ == "__main__":
    unittest.main()
