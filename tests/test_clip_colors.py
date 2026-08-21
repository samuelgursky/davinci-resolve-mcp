"""SetClipColor's value space and its two silent failures (issue #124).

Both behaviours were enumerated live on Studio 19.1.3.7 (2026-08-06) against
TimelineItem and MediaPoolItem; the stubs here reproduce what was measured.
"""

import unittest
from unittest.mock import patch

from src import server
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



class _BulkItemStub(ClipColorItemStub):
    """A timeline item that answers the four calls the bulk path makes."""

    def __init__(self, item_id="1", name="clip", persists=True):
        super().__init__(persists=persists)
        self.item_id = item_id
        self.name = name
        self.enabled = True
        self.properties = {}

    def GetUniqueId(self):
        return self.item_id

    def GetName(self):
        return self.name

    def SetProperty(self, key, value):
        self.properties[key] = value
        return True

    def GetProperty(self, key):
        return self.properties.get(key)

    def SetClipEnabled(self, value):
        self.enabled = bool(value)
        return True


class BulkSetItemPropertiesClipColorTest(unittest.TestCase):
    """clip_color must work as the ONLY key in an op.

    Triage is the daily use of this tool — paint N clips Apricot/Purple/
    Chocolate in one call — and those ops carry no transform, crop, composite or
    audio payload. `_merge_property_groups` returned {} for them, the handler
    bailed on "op requires properties, ...", and the clip_color branch further
    down was unreachable on exactly the ops that need it.
    """

    def _run(self, ops, item=None, **extra):
        item = item or _BulkItemStub()
        params = {"ops": ops}
        params.update(extra)
        with patch.object(server, "_find_timeline_item_by_id", return_value=item):
            return server._timeline_bulk_set_item_properties(object(), params), item

    def test_clip_color_alone_is_applied(self):
        out, item = self._run([{"timeline_item_id": "1", "clip_color": "Apricot"}])
        self.assertTrue(out["success"], out)
        row = out["results"][0]
        self.assertTrue(row["success"], row)
        self.assertIs(row["clip_color"], True)
        self.assertEqual(item.GetClipColor(), "Apricot")

    def test_enabled_alone_is_applied(self):
        out, item = self._run([{"timeline_item_id": "1", "enabled": False}])
        self.assertTrue(out["success"], out)
        self.assertIs(out["results"][0]["enabled"], True)
        self.assertFalse(item.enabled)

    def test_a_triage_batch_of_colours_all_land(self):
        """The real workflow: three clips, three colours, one call."""
        for color in ("Apricot", "Purple", "Chocolate"):
            with self.subTest(color=color):
                out, item = self._run([{"timeline_item_id": "1", "clip_color": color}])
                self.assertTrue(out["success"], out)
                self.assertEqual(item.GetClipColor(), color)

    def test_a_refused_colour_fails_the_op_instead_of_passing_empty(self):
        """all([]) is True — a colour-only op must not inherit that."""
        out, item = self._run([{"timeline_item_id": "1", "clip_color": "Rose"}])
        self.assertFalse(out["success"], out)
        row = out["results"][0]
        self.assertFalse(row["success"], row)
        self.assertIs(row["clip_color"], False)
        self.assertIn("clip_color_detail", row)

    def test_a_colour_that_does_not_persist_is_reported_as_failure(self):
        """Generators and titles take the call, return True, drop the colour."""
        out, _ = self._run(
            [{"timeline_item_id": "1", "clip_color": "Apricot"}],
            item=_BulkItemStub(persists=False),
        )
        self.assertFalse(out["success"], out)
        self.assertIs(out["results"][0]["clip_color"], False)

    def test_dry_run_reports_the_colour_it_would_set(self):
        out, item = self._run(
            [{"timeline_item_id": "1", "clip_color": "Apricot"}], dry_run=True
        )
        self.assertTrue(out["success"], out)
        self.assertEqual(out["results"][0]["would_set_clip_color"], "Apricot")
        self.assertEqual(item.GetClipColor(), "")

    def test_properties_and_colour_together_still_work(self):
        out, item = self._run([{
            "timeline_item_id": "1",
            "transform": {"ZoomX": 1.5},
            "clip_color": "Purple",
        }])
        self.assertTrue(out["success"], out)
        self.assertEqual(item.properties["ZoomX"], 1.5)
        self.assertEqual(item.GetClipColor(), "Purple")

    def test_a_genuinely_empty_op_is_still_rejected(self):
        out, _ = self._run([{"timeline_item_id": "1"}])
        self.assertFalse(out["success"], out)
        self.assertIn("clip_color", out["results"][0]["error"])


if __name__ == "__main__":
    unittest.main()
