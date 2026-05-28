"""Contract tests for C1 — bulk_match_to_hero map-reduce shot matching.

See local/design/agentic-flow-improvements-gameplan.md §3 task C1.
"""
import unittest

import src.server as compound


class _TimelineItemStub:
    def __init__(self, uid, name="clip"):
        self._uid = uid
        self._name = name
        self.copy_grades_calls = []

    def GetUniqueId(self):
        return self._uid

    def GetName(self):
        return self._name

    def GetCurrentVersion(self):
        return {"VersionName": "1"}

    def GetVersionNameList(self, version_type):
        return ["1"]

    def GetNodeGraph(self):
        return _NodeGraphStub()

    def GetColorGroup(self):
        return None

    def GetMediaPoolItem(self):
        return None

    def GetIsColorOutputCacheEnabled(self):
        return False

    def GetIsFusionOutputCacheEnabled(self):
        return False

    def CopyGrades(self, targets):
        self.copy_grades_calls.append([t.GetUniqueId() for t in targets])
        return True


class _NodeGraphStub:
    def GetNumNodes(self):
        return 1

    def GetNodeLabel(self, idx):
        return ""

    def GetLUT(self, idx):
        return ""

    def GetToolsInNode(self, idx):
        return []

    def GetNodeCacheMode(self, idx):
        return 0

    def GetNodeEnabled(self, idx):
        return True


class _TimelineStub:
    def __init__(self, items_by_track):
        self._items = items_by_track  # {1: [item, item, ...]}

    def GetTrackCount(self, track_type):
        return len(self._items) if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, idx):
        if track_type != "video":
            return []
        return self._items.get(idx, [])


class _ProjectStub:
    def GetName(self):
        return "Test"

    def GetUniqueId(self):
        return "p1"

    def GetMediaPool(self):
        return None

    def GetColorGroupsList(self):
        return []

    def GetGallery(self):
        return None


class BulkMatchToHeroValidationTest(unittest.TestCase):
    def test_missing_hero_id(self):
        out = compound._bulk_match_to_hero(_ProjectStub(), {"target_ids": ["x"]})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["code"], "MISSING_HERO_ID")

    def test_empty_targets(self):
        out = compound._bulk_match_to_hero(_ProjectStub(), {"hero_id": "h", "target_ids": []})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["code"], "MISSING_TARGETS")

    def test_invalid_method(self):
        out = compound._bulk_match_to_hero(_ProjectStub(), {"hero_id": "h", "target_ids": ["x"], "method": "garbage"})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["code"], "INVALID_METHOD")


class BulkMatchToHeroDryRunTest(unittest.TestCase):
    def setUp(self):
        self.hero = _TimelineItemStub("hero-1", name="Hero")
        self.target_a = _TimelineItemStub("a-1", name="ShotA")
        self.target_b = _TimelineItemStub("b-1", name="ShotB")
        self.tl = _TimelineStub({1: [self.hero, self.target_a, self.target_b]})
        self.original_get_tl = compound._get_tl
        compound._get_tl = lambda: (object(), self.tl, None)

    def tearDown(self):
        compound._get_tl = self.original_get_tl

    def test_copy_grade_dry_run_returns_proposals(self):
        out = compound._bulk_match_to_hero(
            _ProjectStub(),
            {"hero_id": "hero-1", "target_ids": ["a-1", "b-1"],
             "method": "copy_grade", "dry_run": True},
        )
        self.assertEqual(out["method"], "copy_grade")
        self.assertTrue(out["dry_run"])
        self.assertTrue(out["success"])
        names = sorted(p["target_id"] for p in out["proposals"])
        self.assertEqual(names, ["a-1", "b-1"])
        self.assertEqual(self.hero.copy_grades_calls, [])  # no mutation

    def test_missing_target_appears_in_blocked(self):
        out = compound._bulk_match_to_hero(
            _ProjectStub(),
            {"hero_id": "hero-1", "target_ids": ["a-1", "missing-1"],
             "method": "copy_grade", "dry_run": True},
        )
        ids_blocked = [b["target_id"] for b in out["blocked"]]
        self.assertIn("missing-1", ids_blocked)
        self.assertEqual(out["blocked"][0]["error_code"], "TARGET_NOT_FOUND")
        # F3 — partial dry-run with at least one valid proposal is a success.
        # The blocked entry is reportable information, not a call-level failure.
        self.assertTrue(out["success"])
        self.assertEqual(len(out["proposals"]), 1)

    def test_dry_run_all_blocked_is_failure(self):
        out = compound._bulk_match_to_hero(
            _ProjectStub(),
            {"hero_id": "hero-1", "target_ids": ["missing-1", "missing-2"],
             "method": "copy_grade", "dry_run": True},
        )
        self.assertEqual(out["proposals"], [])
        self.assertEqual(len(out["blocked"]), 2)
        # No proposals at all → nothing actionable → success=false.
        self.assertFalse(out["success"])

    def test_cdl_delta_method_returns_unsupported_error(self):
        out = compound._bulk_match_to_hero(
            _ProjectStub(),
            {"hero_id": "hero-1", "target_ids": ["a-1"],
             "method": "cdl_delta", "dry_run": True},
        )
        self.assertIn("error", out)
        self.assertEqual(out["error"]["code"], "CDL_DELTA_UNIMPLEMENTED")
        self.assertEqual(out["error"]["category"], "unsupported")


class BulkMatchToHeroExecuteTest(unittest.TestCase):
    def setUp(self):
        self.hero = _TimelineItemStub("hero-1", name="Hero")
        self.target_a = _TimelineItemStub("a-1", name="ShotA")
        self.tl = _TimelineStub({1: [self.hero, self.target_a]})
        self.original_get_tl = compound._get_tl
        compound._get_tl = lambda: (object(), self.tl, None)
        compound._CONFIRM_TOKENS.clear()

    def tearDown(self):
        compound._get_tl = self.original_get_tl

    def test_execute_without_token_returns_confirm_required(self):
        out = compound._bulk_match_to_hero(
            _ProjectStub(),
            {"hero_id": "hero-1", "target_ids": ["a-1"],
             "method": "copy_grade", "dry_run": False},
        )
        self.assertEqual(out["error"]["category"], "pending_user_decision")
        self.assertIn("confirm_token", out)
        self.assertEqual(self.hero.copy_grades_calls, [])

    def test_execute_with_token_mutates(self):
        # First call: receive token.
        first = compound._bulk_match_to_hero(
            _ProjectStub(),
            {"hero_id": "hero-1", "target_ids": ["a-1"],
             "method": "copy_grade", "dry_run": False},
        )
        token = first["confirm_token"]
        # Second call: echo same params + token.
        second = compound._bulk_match_to_hero(
            _ProjectStub(),
            {"hero_id": "hero-1", "target_ids": ["a-1"],
             "method": "copy_grade", "dry_run": False,
             "confirm_token": token},
        )
        self.assertTrue(second["success"])
        self.assertTrue(second.get("executed"))
        self.assertEqual(self.hero.copy_grades_calls, [["a-1"]])


if __name__ == "__main__":
    unittest.main()
