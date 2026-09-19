"""allow_partial_item_delete must be read the way a caller meant it.

Several MCP clients send booleans as strings. A bare bool() test turns
allow_partial_item_delete="false" into True, so the guard that refuses to
delete timeline items the requested range only partially covers is skipped:
timeline.lift_range and timeline.apply_cuts delete whole clips for a caller
who explicitly asked them not to. The same handlers already coerce `ripple`
through coerce_bool a few lines away.
"""
import unittest
from unittest import mock

import src.server as s


class FakeItem:
    def __init__(self, uid, start, end):
        self.uid = uid
        self.start = start
        self.end = end

    def GetUniqueId(self):
        return self.uid

    def GetName(self):
        return f"clip-{self.uid}"

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end


class RecordingTimeline:
    """One video track holding a single 0..48 item, so a 0..24 range only
    partially covers it — exactly the case the guard exists for."""

    def __init__(self):
        self.video = [FakeItem("a", 0, 48)]
        self.deleted = []

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, index):
        return list(self.video) if (track_type, index) == ("video", 1) else []

    def DeleteClips(self, items, ripple):
        self.deleted.extend(it.GetUniqueId() for it in items)
        gone = {id(it) for it in items}
        self.video = [it for it in self.video if id(it) not in gone]
        return True


class AllowPartialItemDeleteStringTest(unittest.TestCase):
    def _lift(self, value):
        tl = RecordingTimeline()
        params = {"start_frame": 0, "end_frame": 24}
        if value is not _MISSING:
            params["allow_partial_item_delete"] = value
        return s._timeline_lift_range_impl(tl, params), tl

    def test_string_false_still_blocks_the_partial_delete(self):
        res, tl = self._lift("false")
        self.assertIn("blocked", res)
        self.assertEqual(tl.deleted, [])

    def test_off_and_no_still_block_the_partial_delete(self):
        for value in ("off", "no", "0"):
            with self.subTest(value=value):
                res, tl = self._lift(value)
                self.assertIn("blocked", res)
                self.assertEqual(tl.deleted, [])

    def test_string_true_still_allows_the_partial_delete(self):
        for value in ("true", "yes", "on", "1", True):
            with self.subTest(value=value):
                res, tl = self._lift(value)
                self.assertNotIn("blocked", res)
                self.assertEqual(tl.deleted, ["a"])

    def test_real_false_and_absent_still_block(self):
        for value in (False, _MISSING):
            with self.subTest(value=value):
                res, tl = self._lift(value)
                self.assertIn("blocked", res)
                self.assertEqual(tl.deleted, [])

    # --- timeline.apply_cuts reads the same flag off its own params ---

    def _apply_cuts(self, params):
        tl = RecordingTimeline()
        fake_proj = mock.Mock()
        fake_proj.GetCurrentTimeline.return_value = tl
        base = {
            "cuts": [{"action": "lift", "span": {"start": 0, "end": 24}}],
            "dry_run": False,
        }
        base.update(params)
        with mock.patch.object(s, "get_resolve", return_value=None), \
             mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)), \
             mock.patch.object(s, "_confirm_token_required", return_value=False):
            return s.timeline("apply_cuts", base), tl

    def test_apply_cuts_string_false_still_blocks_the_partial_delete(self):
        res, tl = self._apply_cuts({"allow_partial_item_delete": "false"})
        self.assertEqual(tl.deleted, [])
        self.assertIn("blocked", res["results"][0]["result"])

    def test_apply_cuts_default_still_allows_the_partial_delete(self):
        res, tl = self._apply_cuts({})
        self.assertEqual(tl.deleted, ["a"])

    def test_apply_cuts_real_false_still_blocks(self):
        res, tl = self._apply_cuts({"allow_partial_item_delete": False})
        self.assertEqual(tl.deleted, [])


class _Missing:
    def __repr__(self):
        return "<absent>"


_MISSING = _Missing()


if __name__ == "__main__":
    unittest.main()
