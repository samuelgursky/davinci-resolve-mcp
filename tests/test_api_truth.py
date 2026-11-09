"""Tests for the behaviorally-verified API truth ledger and its lookup action."""
import unittest
from collections import Counter

import src.server as s
from src.utils.api_truth import lookup_api_truth, API_TRUTH


class LookupTest(unittest.TestCase):
    def test_no_query_returns_all(self):
        self.assertEqual(len(lookup_api_truth()), len(API_TRUTH))

    def test_query_matches_symbol_and_tags(self):
        audio = lookup_api_truth("audio")
        self.assertTrue(any("AutoSyncAudio" in e["symbol"] for e in audio))

    def test_query_matches_reality_text(self):
        res = lookup_api_truth("ellipsis")
        self.assertTrue(any("Transcription" in e["symbol"] for e in res))

    def test_case_insensitive(self):
        self.assertEqual(
            [e["symbol"] for e in lookup_api_truth("FUSION")],
            [e["symbol"] for e in lookup_api_truth("fusion")],
        )

    def test_no_match(self):
        self.assertEqual(lookup_api_truth("nonexistent-zzz"), [])

    def test_source_track_selector_limitation_recorded(self):
        # Issue #74: the Source Track Selector / insert-destination track is not
        # controllable via the API. The verified-limitation entry must be findable
        # by an agent searching for the track-targeting behavior.
        hits = lookup_api_truth("track selector")
        self.assertTrue(any("Source Track Selector" in e["symbol"] for e in hits))
        entry = next(e for e in hits if "Source Track Selector" in e["symbol"])
        self.assertIn("missing-method", entry["tags"])
        self.assertNotIn("enum", entry["tags"])  # no mitigation required

    def test_append_endframe_exclusive_bound_recorded(self):
        # AppendToTimeline clipInfo endFrame is a half-open bound (duration =
        # endFrame - startFrame). The entry must be findable by an agent probing
        # append placement semantics before batch-assembling clip_infos.
        hits = lookup_api_truth("endFrame")
        entry = next(
            (e for e in hits if "AppendToTimeline clipInfo endFrame" in e["symbol"]),
            None,
        )
        self.assertIsNotNone(entry)
        self.assertIn("off-by-one", entry["tags"])
        self.assertIn("exclusive", entry["reality"].lower())

    def test_timeline_endframe_exclusive_bound_recorded(self):
        # Timeline.GetEndFrame() is one past the last frame, so a timeline's
        # frame count is end - start. Two readers shipped end - start + 1
        # until v4.8.21 (PR #269); the ledger must say which it is.
        hits = lookup_api_truth("GetEndFrame")
        entry = next(
            (e for e in hits if e["symbol"].startswith("Timeline.GetEndFrame")),
            None,
        )
        self.assertIsNotNone(entry)
        self.assertIn("off-by-one", entry["tags"])
        self.assertIn("exclusive", entry["reality"].lower())
        self.assertIn("GetEndFrame() - GetStartFrame()", entry["recommended"])

    def test_issue_336_corrections_are_recorded(self):
        # Four of the six calls first reported as broken worked once the
        # reporter measured them on a timeline whose clips sat inside its own
        # range. A withdrawn entry stays in the ledger, so a later reader of
        # the issue finds the correction, but it leaves the Blackmagic report.
        withdrawn = (
            "Timeline.DeleteGaps",
            "Timeline.ExportFrame",
            "TimelineItem.SetPosition / Timeline.MoveItems",
            "TimelineItem.AddMarker at relative frame 0",
        )
        for symbol in withdrawn:
            entry = next(e for e in API_TRUTH if e["symbol"] == symbol)
            self.assertTrue(entry["reality"].startswith("WITHDRAWN"), symbol)
            self.assertNotIn("submit", entry)
            self.assertNotIn("silent-failure", entry["tags"], symbol)
            self.assertNotIn("unreliable-return", entry["tags"], symbol)

        album = next(e for e in API_TRUTH if e["symbol"] == "MediaPool.AddToPhotoAlbum")
        self.assertIn("returned None", album["reality"])
        self.assertIn("21.2.0.6", album["reality"])
        self.assertEqual(album.get("submit"), "bug")

        position = next(
            e for e in API_TRUTH
            if e["symbol"] == "TimelineItem.SetPosition / Timeline.MoveItems"
        )
        # The withdrawal rests on a different build from the first report, so
        # the entry has to keep both readings and say what was never measured.
        self.assertIn("21.2.0.6", position["reality"])
        self.assertIn("21.1.2.10", position["reality"])
        self.assertIn("not known", position["reality"])

        marker = next(
            e for e in API_TRUTH
            if e["symbol"] == "TimelineItem.AddMarker at relative frame 0"
        )
        self.assertIn("TimelineItem.GetMarkers()", marker["reality"])
        self.assertIn("Timeline.GetMarkers()", marker["reality"])
        self.assertFalse(any(
            e["symbol"] == "Timeline.AddMarker at relative frame 0" for e in API_TRUTH
        ))

        record = next(
            e for e in API_TRUTH
            if e["symbol"].startswith("MediaPool.AppendToTimeline clipInfo recordFrame")
        )
        self.assertIn("duration 0", record["reality"])

        offset = next(
            entry for entry in API_TRUTH
            if entry["symbol"] == "TimelineItem.SetLeftOffset"
        )
        # The flag refuses a mapped action. Nothing calls SetLeftOffset, so
        # the fact stays in the ledger without a refusal that can never fire.
        self.assertNotIn("destroys_prior_work", offset)
        self.assertIn("outside", offset["reality"])
        # Narrowed, not withdrawn: the runaway extension came from the clip
        # sitting outside the timeline's range, and did not reproduce.
        self.assertFalse(offset["reality"].startswith("WITHDRAWN"))
        self.assertIn("not recorded as destructive", offset["reality"])
        self.assertNotIn("destructive", offset["tags"])
        self.assertNotIn("submit", offset)

    def test_entries_well_formed(self):
        for e in API_TRUTH:
            self.assertIn("symbol", e)
            self.assertIn("reality", e)
            self.assertIn("recommended", e)
            self.assertIsInstance(e.get("tags", []), list)

    def test_no_duplicate_symbols(self):
        """One symbol, one entry.

        A second entry for a symbol that already had one is easy to add — the
        ledger is long, and a new finding about a call feels like a new fact
        rather than an amendment to an old one. It is worse than untidy:
        `lookup_api_truth` returns both, so an agent reads two accounts of the
        same call and has no way to tell which is current. Nearly shipped for
        `ProjectManager.DeleteProject`, where the right move was to sharpen the
        existing entry with the newly measured mechanism.
        """
        counts = Counter(e["symbol"] for e in API_TRUTH)
        duplicates = sorted(symbol for symbol, n in counts.items() if n > 1)
        self.assertEqual(duplicates, [], f"duplicate api_truth symbols: {duplicates}")


class ApiTruthActionTest(unittest.TestCase):
    def test_action_no_connection_needed(self):
        # api_truth is dispatched before any _check — must work with no Resolve.
        out = s.resolve_control("api_truth", {})
        self.assertIn("verified_on", out)
        self.assertEqual(out["count"], len(API_TRUTH))
        self.assertTrue(out["facts"])

    def test_action_query_filters(self):
        out = s.resolve_control("api_truth", {"query": "fusion"})
        self.assertTrue(out["count"] >= 1)
        self.assertTrue(all("fusion" in (
            e["symbol"] + e.get("object", "") + e["reality"] + " ".join(e.get("tags", []))
        ).lower() for e in out["facts"]))


if __name__ == "__main__":
    unittest.main()
