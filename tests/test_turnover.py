"""Tests for turnover manifests.

Turnovers fail the same way every time: something obvious is missing, nobody
notices until the receiving facility has started, and the fix costs a day of
somebody else's schedule. All of it is checkable in advance, which is what this
module is for.
"""

from __future__ import annotations

import unittest

from src.utils import turnover as tv

FULL_SOUND = {
    "aaf": "/turnover/EP01.aaf",
    "picture_reference_with_burn": "/turnover/EP01_ref.mov",
    "handles": True,
    "session_notes": "/turnover/notes.pdf",
    "adr_list": "/turnover/adr.csv",
    "temp_music_notes": "/turnover/temp.txt",
}


class SpecTests(unittest.TestCase):
    def test_sound_needs_far_more_handles_than_picture_departments(self) -> None:
        self.assertGreater(
            tv.HANDLE_REQUIREMENTS["sound"]["frames"],
            tv.HANDLE_REQUIREMENTS["vfx"]["frames"],
        )

    def test_every_destination_requires_the_burned_in_reference(self) -> None:
        """The loudest instruction in online editing, enforced everywhere."""
        for spec in tv.PACKAGE_SPECS.values():
            self.assertIn("picture_reference_with_burn", spec["required"])

    def test_an_unknown_destination_is_rejected(self) -> None:
        out = tv.validate_package("marketing", {})
        self.assertFalse(out["success"])
        self.assertIn("sound", out["error"])


class ValidationTests(unittest.TestCase):
    def test_a_complete_package_passes(self) -> None:
        out = tv.validate_package("sound", FULL_SOUND)
        self.assertTrue(out["complete"])
        self.assertIn("COMPLETE", out["note"])

    def test_a_missing_required_item_blocks(self) -> None:
        contents = dict(FULL_SOUND)
        del contents["aaf"]
        out = tv.validate_package("sound", contents)
        self.assertFalse(out["complete"])
        self.assertIn("aaf", out["missing_required"])
        self.assertIn("blockers", out["note"])

    def test_a_missing_reference_blocks_rather_than_warns(self) -> None:
        contents = dict(FULL_SOUND)
        del contents["picture_reference_with_burn"]
        self.assertIn("picture_reference_with_burn",
                      tv.validate_package("sound", contents)["missing_required"])

    def test_missing_recommended_items_do_not_block(self) -> None:
        out = tv.validate_package("sound", {
            "aaf": "x", "picture_reference_with_burn": "y", "handles": True})
        self.assertTrue(out["complete"])
        self.assertTrue(out["missing_recommended"])

    def test_short_handles_are_caught_against_the_destination(self) -> None:
        """8 frames is fine for VFX and nowhere near enough for sound."""
        vfx = tv.validate_package("vfx", {
            "plates": "x", "picture_reference_with_burn": "y",
            "shot_list": "z", "handles": True}, handle_frames=8)
        sound = tv.validate_package("sound", FULL_SOUND, handle_frames=8)
        self.assertTrue(vfx["complete"])
        self.assertFalse(sound["complete"])
        self.assertIn("48", sound["handle_finding"])

    def test_a_falsy_value_counts_as_missing(self) -> None:
        contents = dict(FULL_SOUND, aaf="")
        self.assertIn("aaf", tv.validate_package("sound", contents)["missing_required"])

    def test_the_audio_spec_travels_with_a_sound_turnover(self) -> None:
        self.assertEqual(
            tv.validate_package("sound", FULL_SOUND)["audio_spec"]["sample_rate"], "48kHz"
        )


class BurnInTests(unittest.TestCase):
    def test_both_timecodes_are_required(self) -> None:
        """One identifies the material, the other the position in the cut."""
        spec = tv.burn_in_spec(version="v03")
        self.assertIn("source_timecode", spec["fields"])
        self.assertIn("record_timecode", spec["fields"])
        self.assertIn("Both source AND record", spec["requirement"])

    def test_extra_fields_are_appended_without_duplication(self) -> None:
        spec = tv.burn_in_spec(version="v01", extra_fields=["reel", "source_timecode"])
        self.assertEqual(spec["fields"].count("source_timecode"), 1)
        self.assertIn("reel", spec["fields"])

    def test_it_admits_rendering_needs_a_live_resolve(self) -> None:
        self.assertIn("live Resolve", tv.burn_in_spec(version="v01")["note"])


class PlanTests(unittest.TestCase):
    def test_several_destinations_are_checked_at_once(self) -> None:
        out = tv.plan_turnover(["sound", "vfx"], FULL_SOUND)
        self.assertEqual(len(out["packages"]), 2)
        self.assertIn("vfx", out["incomplete_destinations"])

    def test_the_burn_spec_ships_with_the_plan(self) -> None:
        self.assertIn("fields", tv.plan_turnover(["sound"], FULL_SOUND)["burn_in_spec"])

    def test_the_plan_admits_it_exports_nothing(self) -> None:
        note = tv.plan_turnover(["sound"], FULL_SOUND)["note"]
        self.assertIn("Manifests only", note)
        self.assertIn("omits the textless is still a failed turnover", note)

    def test_no_destinations_is_an_error(self) -> None:
        self.assertFalse(tv.plan_turnover([], FULL_SOUND)["success"])

    def test_an_unknown_destination_fails_the_whole_plan(self) -> None:
        self.assertFalse(tv.plan_turnover(["sound", "nope"], FULL_SOUND)["success"])


if __name__ == "__main__":
    unittest.main()
