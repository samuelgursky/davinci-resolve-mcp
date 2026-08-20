"""Tests for the conform lint.

Conforming is where every upstream organizational mistake surfaces, and it
surfaces in someone else's suite after picture lock. These are the failures
online editors have been writing the same list about for years.
"""

from __future__ import annotations

import unittest

from src.utils import conform_lint as cl


def item(**kw):
    base = {
        "track_index": 1,
        "item_name": "A001_C001",
        "timeline_start_frame": 0,
        "timeline_end_frame": 100,
        "source_start_frame": 50,
        "media_path": "/media/A001_C001.mov",
    }
    base.update(kw)
    return base


def snapshot(items, fps=24.0):
    return {"timeline_name": "EP01", "timeline_fps": fps, "items": items}


def codes(result):
    return {f["code"] for f in result["findings"]}


class FrameRateTests(unittest.TestCase):
    def test_23_976_in_a_24_timeline_is_a_blocker(self) -> None:
        """The classic: 0.1% is seconds of drift over a feature, found in the theatre."""
        out = cl.lint_timeline(snapshot([item(clip_fps=23.976)], fps=24.0))
        self.assertIn("FPS_MISMATCH", codes(out))
        finding = next(f for f in out["findings"] if f["code"] == "FPS_MISMATCH")
        self.assertEqual(finding["severity"], cl.SEVERITY_BLOCKER)

    def test_float_noise_is_not_a_mismatch(self) -> None:
        out = cl.lint_timeline(snapshot([item(clip_fps=23.9760001)], fps=23.976))
        self.assertNotIn("FPS_MISMATCH", codes(out))


class RelinkBlockerTests(unittest.TestCase):
    def test_two_sources_sharing_timecode_is_a_blocker(self) -> None:
        """Misnamed cards. A timecode relink picks one, silently, and picks wrong."""
        out = cl.lint_timeline(snapshot([
            item(item_name="A", media_path="/m/a.mov", source_start_timecode="01:00:00:00"),
            item(item_name="B", media_path="/m/b.mov", source_start_timecode="01:00:00:00"),
        ]))
        self.assertIn("DUPLICATE_SOURCE_TC", codes(out))

    def test_one_source_reused_at_the_same_tc_is_fine(self) -> None:
        """The same file used twice is normal; two different files is the problem."""
        out = cl.lint_timeline(snapshot([
            item(item_name="A", media_path="/m/a.mov", source_start_timecode="01:00:00:00"),
            item(item_name="A again", media_path="/m/a.mov", source_start_timecode="01:00:00:00"),
        ]))
        self.assertNotIn("DUPLICATE_SOURCE_TC", codes(out))

    def test_media_with_no_reference_is_a_blocker(self) -> None:
        out = cl.lint_timeline(snapshot([item(media_path=None)]))
        self.assertIn("OFFLINE_MEDIA", codes(out))


class InterchangeTests(unittest.TestCase):
    def test_scale_to_frame_size_is_flagged(self) -> None:
        """Its sizing data does not reach Resolve at all — every shot redone by hand."""
        out = cl.lint_timeline(snapshot([item(effects=["Scale to Frame Size"])]))
        self.assertIn("FRAGILE_EFFECT", codes(out))
        detail = next(f for f in out["findings"] if f["code"] == "FRAGILE_EFFECT")["detail"]
        self.assertIn("Scale to Frame Size", detail)

    def test_third_party_plugins_are_flagged(self) -> None:
        out = cl.lint_timeline(snapshot([item(effects=["Sapphire Glow", "Neat Video"])]))
        self.assertEqual(
            len(next(f for f in out["findings"] if f["code"] == "FRAGILE_EFFECT")["items"]), 2
        )

    def test_a_plain_effect_list_is_not_flagged(self) -> None:
        out = cl.lint_timeline(snapshot([item(effects=["Transform", "Cropping"])]))
        self.assertNotIn("FRAGILE_EFFECT", codes(out))


class TimelineHygieneTests(unittest.TestCase):
    def test_an_item_buried_under_an_opaque_layer_is_flagged(self) -> None:
        """Invisible in the cut, still conformed, still relinked, still carried."""
        out = cl.lint_timeline(snapshot([
            item(item_name="buried", track_index=1, timeline_start_frame=10, timeline_end_frame=50),
            item(item_name="cover", track_index=2, timeline_start_frame=0, timeline_end_frame=100),
        ]))
        self.assertIn("BURIED_ITEM", codes(out))

    def test_a_transparent_layer_above_does_not_bury(self) -> None:
        out = cl.lint_timeline(snapshot([
            item(item_name="visible", track_index=1, timeline_start_frame=10, timeline_end_frame=50),
            item(item_name="overlay", track_index=2, timeline_start_frame=0,
                 timeline_end_frame=100, opacity=40),
        ]))
        self.assertNotIn("BURIED_ITEM", codes(out))

    def test_overlapping_items_on_one_track_are_reported(self) -> None:
        out = cl.lint_timeline(snapshot([
            item(item_name="a", timeline_start_frame=0, timeline_end_frame=100),
            item(item_name="b", timeline_start_frame=90, timeline_end_frame=200),
        ]))
        self.assertIn("TRACK_OVERLAP", codes(out))

    def test_source_starting_at_frame_zero_has_no_head_handle(self) -> None:
        out = cl.lint_timeline(snapshot([item(source_start_frame=0)]))
        self.assertIn("NO_HEAD_HANDLE", codes(out))


class ReelNameTests(unittest.TestCase):
    def test_missing_reel_names_warn_because_edls_need_them(self) -> None:
        out = cl.lint_timeline(snapshot([item()]))
        self.assertIn("MISSING_REEL_NAME", codes(out))

    def test_a_reel_name_over_eight_chars_is_info_not_a_blocker(self) -> None:
        out = cl.lint_timeline(snapshot([item(reel_name="A001_LONG_NAME")]))
        finding = next(f for f in out["findings"] if f["code"] == "REEL_NAME_TOO_LONG")
        self.assertEqual(finding["severity"], cl.SEVERITY_INFO)


class HonestyTests(unittest.TestCase):
    """A lint that silently skips half its rules while reporting clean is worse
    than no lint at all."""

    def test_checks_that_could_not_run_are_named(self) -> None:
        out = cl.lint_timeline({"timeline_name": "X", "items": [item()]})
        joined = " ".join(out["not_checked"])
        self.assertIn("frame-rate mismatch", joined)
        self.assertIn("duplicate source timecode", joined)

    def test_a_snapshot_with_no_items_says_nothing_was_checked(self) -> None:
        out = cl.lint_timeline(snapshot([]))
        self.assertIn("no items", " ".join(out["not_checked"]))

    def test_a_fully_populated_clean_timeline_reports_clean(self) -> None:
        out = cl.lint_timeline(snapshot([
            item(source_start_timecode="01:00:00:00", reel_name="A001",
                 clip_fps=24.0, effects=["Transform"], source_start_frame=50),
        ]))
        self.assertTrue(out["clean"], out["findings"])
        self.assertEqual(out["not_checked"], [])

    def test_findings_are_ordered_worst_first(self) -> None:
        out = cl.lint_timeline(snapshot([
            item(item_name="a", media_path=None),
            item(item_name="b", source_start_frame=0),
        ]))
        ranks = [cl._SEVERITY_RANK[f["severity"]] for f in out["findings"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_every_finding_explains_why_it_matters(self) -> None:
        out = cl.lint_timeline(snapshot([
            item(media_path=None), item(effects=["Lumetri Color"]), item(source_start_frame=0),
        ]))
        for finding in out["findings"]:
            self.assertGreater(len(finding["detail"]), 60, finding["code"])


if __name__ == "__main__":
    unittest.main()
