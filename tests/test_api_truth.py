"""Tests for the behaviorally-verified API truth ledger and its lookup action."""
import unittest

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

    def test_entries_well_formed(self):
        for e in API_TRUTH:
            self.assertIn("symbol", e)
            self.assertIn("reality", e)
            self.assertIn("recommended", e)
            self.assertIsInstance(e.get("tags", []), list)


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
