"""SetClipColor's value space and its two silent failures (issue #124).

Both behaviours were enumerated live on Studio 19.1.3.7 (2026-08-06) against
TimelineItem and MediaPoolItem; the stubs here reproduce what was measured.
"""

import unittest

from src.server import _set_clip_color_checked
from src.utils.clip_colors import (
    CLIP_COLORS,
    MARKER_ONLY_NAMES,
    clip_color_refusal,
    is_known_clip_color,
)


class ClipColorItemStub:
    """Accepts the measured palette; refuses everything else with a bare False."""

    def __init__(self, persists=True):
        self.color = ""
        self.persists = persists

    def SetClipColor(self, color):
        if color not in CLIP_COLORS:
            return False
        # A generator takes the call, returns True, and drops the colour.
        if self.persists:
            self.color = color
        return True

    def GetClipColor(self):
        return self.color


class ClipColorVocabularyTest(unittest.TestCase):
    def test_measured_palette_has_sixteen_names(self):
        self.assertEqual(len(CLIP_COLORS), 16)
        self.assertEqual(len(set(CLIP_COLORS)), 16)

    def test_marker_only_names_are_not_clip_colors(self):
        """The decoy set must not intersect the accepted set."""
        self.assertFalse(set(MARKER_ONLY_NAMES) & set(CLIP_COLORS))

    def test_overlapping_names_are_valid(self):
        """Blue/Green/Yellow/Pink/Purple are in both palettes — and do work.

        These five are why reasoning from the marker constants looks right.
        """
        for name in ("Blue", "Green", "Yellow", "Pink", "Purple"):
            self.assertTrue(is_known_clip_color(name), name)

    def test_empty_string_is_not_a_valid_color(self):
        self.assertFalse(is_known_clip_color(""))
        self.assertFalse(is_known_clip_color(None))

    def test_refusal_distinguishes_a_marker_name(self):
        marker = clip_color_refusal("Rose")
        self.assertTrue(marker["state"]["is_marker_only_name"])
        self.assertIn("MARKER", marker["reason"])

        junk = clip_color_refusal("Betamax")
        self.assertFalse(junk["state"]["is_marker_only_name"])

    def test_refusal_always_names_the_valid_set(self):
        for name in ("Rose", "Betamax", "", "Teal"):
            refusal = clip_color_refusal(name)
            self.assertEqual(refusal["state"]["valid_colors"], list(CLIP_COLORS))
            self.assertIn("Chocolate", refusal["remediation"])


class SetClipColorCheckedTest(unittest.TestCase):
    def test_valid_color_on_a_persisting_item_succeeds(self):
        item = ClipColorItemStub()
        result = _set_clip_color_checked(item, "Teal", kind="timeline item")

        self.assertTrue(result["success"])
        self.assertEqual(result["readback"], "Teal")

    def test_marker_name_is_refused_with_the_decoy_named(self):
        item = ClipColorItemStub()
        result = _set_clip_color_checked(item, "Fuchsia", kind="timeline item")

        self.assertEqual(result["error"]["code"], "CLIP_COLOR_REJECTED")
        self.assertTrue(result["error"]["state"]["is_marker_only_name"])
        self.assertEqual(item.GetClipColor(), "")

    def test_true_without_persistence_is_reported_as_failure(self):
        """The generator case: the bool says yes, the readback says no.

        Reporting success here is the silent lie the whole check exists for.
        """
        generator = ClipColorItemStub(persists=False)
        result = _set_clip_color_checked(generator, "Teal", kind="timeline item")

        self.assertFalse(result["success"])
        self.assertEqual(result["readback"], "")
        self.assertEqual(
            [w["code"] for w in result["warnings"]], ["CLIP_COLOR_NOT_PERSISTED"]
        )

    def test_every_measured_color_round_trips(self):
        for name in CLIP_COLORS:
            item = ClipColorItemStub()
            result = _set_clip_color_checked(item, name, kind="media pool item")
            self.assertTrue(result["success"], name)
            self.assertEqual(result["readback"], name)


if __name__ == "__main__":
    unittest.main()
