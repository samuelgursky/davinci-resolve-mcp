"""Tests for the Law of Two-and-a-Half.

The single test that matters most is the music-bed one. The naive version of
this feature counts active tracks, flags every mixed timeline in existence, and
gets closed after one run. Distinguishing streams that *compete* from streams
that merely *play* is the whole feature.
"""

from __future__ import annotations

import unittest

from src.utils import sound_density as sd


def samples(*rows, step=0.5):
    """(dict of stream→dBFS) per row → the sample shape."""
    return [{"time_seconds": i * step, "levels": r} for i, r in enumerate(rows)]


class MomentClassificationTests(unittest.TestCase):
    def test_a_music_bed_under_dialogue_is_one_competitor_plus_texture(self) -> None:
        """The test this feature lives or dies on."""
        out = sd.classify_moment({"dialogue": -12.0, "music": -34.0})
        self.assertEqual(len(out["competitors"]), 1)
        self.assertEqual(out["competitors"][0]["stream"], "dialogue")
        self.assertEqual([b["stream"] for b in out["beds"]], ["music"])

    def test_two_voices_at_the_same_level_are_two_competitors(self) -> None:
        out = sd.classify_moment({"voice_a": -14.0, "voice_b": -15.0})
        self.assertEqual(len(out["competitors"]), 2)

    def test_inaudible_streams_are_not_counted_at_all(self) -> None:
        out = sd.classify_moment({"dialogue": -12.0, "room": -70.0})
        self.assertEqual(len(out["competitors"]) + len(out["beds"]), 1)

    def test_silence_is_reported_as_silence(self) -> None:
        self.assertTrue(sd.classify_moment({"a": -80.0})["silent"])
        self.assertTrue(sd.classify_moment({})["silent"])

    def test_the_bed_margin_is_adjustable(self) -> None:
        levels = {"a": -12.0, "b": -26.0}
        self.assertEqual(len(sd.classify_moment(levels)["competitors"]), 1)
        self.assertEqual(
            len(sd.classify_moment(levels, bed_margin_db=20.0)["competitors"]), 2
        )


class DensityAuditTests(unittest.TestCase):
    def test_a_sustained_pile_up_is_flagged(self) -> None:
        crowded = {"vo": -10.0, "dial": -11.0, "sfx": -12.0, "music": -13.0}
        out = sd.audit(samples(*[crowded] * 8))
        self.assertTrue(out["findings"])
        self.assertEqual(out["peak_competitors"], 4)

    def test_a_momentary_pile_up_is_not_flagged(self) -> None:
        """A hard effect landing over dialogue is normal."""
        calm = {"dial": -12.0}
        crowded = {"vo": -10.0, "dial": -11.0, "sfx": -12.0}
        out = sd.audit(samples(calm, calm, crowded, calm, calm))
        self.assertFalse(out["crowded_stretches"])

    def test_dialogue_over_a_bed_never_flags_however_long(self) -> None:
        """Otherwise the tool fails on every finished sequence ever mixed."""
        mixed = {"dialogue": -12.0, "music": -36.0, "atmos": -44.0}
        out = sd.audit(samples(*[mixed] * 40))
        self.assertEqual(out["peak_competitors"], 1)
        self.assertFalse(out["findings"])

    def test_the_density_curve_separates_competitors_from_beds(self) -> None:
        out = sd.audit(samples({"dialogue": -12.0, "music": -36.0}))
        point = out["density_curve"][0]
        self.assertEqual(point["competitors"], 1)
        self.assertEqual(point["beds"], 1)
        self.assertEqual(point["bed_streams"], ["music"])

    def test_no_samples_is_an_error(self) -> None:
        self.assertFalse(sd.audit([])["success"])

    def test_the_limit_is_a_parameter(self) -> None:
        three = {"a": -10.0, "b": -11.0, "c": -12.0}
        strict = sd.audit(samples(*[three] * 8), stream_limit=2.0)
        loose = sd.audit(samples(*[three] * 8), stream_limit=5.0)
        self.assertTrue(strict["findings"])
        self.assertFalse(loose["findings"])


class HonestyTests(unittest.TestCase):
    def test_the_threshold_declares_it_is_not_physics(self) -> None:
        out = sd.audit(samples({"a": -12.0}))
        self.assertIn("NOT a measured constant", out["threshold_provenance"])
        self.assertIn("Do not cite it as physics", out["threshold_provenance"])

    def test_the_method_declares_itself_a_heuristic(self) -> None:
        out = sd.audit(samples({"a": -12.0}))
        self.assertIn("Heuristic", out["method"])

    def test_the_two_and_a_half_boundary_is_recorded_verbatim(self) -> None:
        self.assertEqual(sd.STREAM_LIMIT, 2.5)

    def test_a_clean_result_says_so_rather_than_going_quiet(self) -> None:
        out = sd.audit(samples({"dialogue": -12.0}))
        self.assertIn("nothing sustained over the limit", out["note"])


class MeasurementTests(unittest.TestCase):
    def test_missing_files_fail_cleanly(self) -> None:
        out = sd.measure_track_levels({"a": "/definitely/not/here.wav"})
        self.assertFalse(out["success"])


if __name__ == "__main__":
    unittest.main()
