"""api_truth 'Timeline.DeleteClips (flaky first attempt)' — readback-and-retry.

Timeline.DeleteClips can return False on the first call even when every item
is valid and present; an identical immediate retry succeeds. It can also
return False while actually deleting. _timeline_delete_clips_verified treats
a False as advisory: re-list the tracks, and only retry (once) if the items
really survived. These tests exercise the helper directly and through the
timeline delete_clips dispatcher with a fake timeline whose DeleteClips
follows a scripted lie-plan.
"""
import unittest
from unittest import mock

import src.server as s


class FakeItem:
    def __init__(self, uid):
        self.uid = uid

    def GetUniqueId(self):
        return self.uid

    def GetName(self):
        return f"clip-{self.uid}"

    def GetStart(self):
        return 0

    def GetEnd(self):
        return 24

    def GetDuration(self):
        return 24


class NoIdItem(FakeItem):
    def GetUniqueId(self):
        return None


class FlakyTimeline:
    """DeleteClips follows a scripted plan: each call pops one
    (returned_bool, actually_deletes) pair — so it can lie either way."""

    def __init__(self, items, plan):
        self.video = list(items)
        self.plan = list(plan)
        self.calls = 0

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, index):
        return list(self.video) if (track_type, index) == ("video", 1) else []

    def DeleteClips(self, items, ripple):
        self.calls += 1
        returned, deletes = self.plan.pop(0)
        if deletes:
            gone = {id(it) for it in items}
            self.video = [it for it in self.video if id(it) not in gone]
        return returned


class HelperTest(unittest.TestCase):
    def _run(self, plan, items=None):
        items = items if items is not None else [FakeItem("a"), FakeItem("b")]
        tl = FlakyTimeline(items, plan)
        return s._timeline_delete_clips_verified(tl, items, False), tl

    def test_true_first_call_no_retry(self):
        ok, tl = self._run([(True, True)])
        self.assertTrue(ok)
        self.assertEqual(tl.calls, 1)

    def test_false_but_actually_deleted_is_success_without_retry(self):
        ok, tl = self._run([(False, True)])
        self.assertTrue(ok)
        self.assertEqual(tl.calls, 1)  # readback saw them gone; no retry

    def test_false_noop_then_retry_succeeds(self):
        ok, tl = self._run([(False, False), (True, True)])
        self.assertTrue(ok)
        self.assertEqual(tl.calls, 2)

    def test_retry_false_but_actually_deleted_is_success(self):
        ok, tl = self._run([(False, False), (False, True)])
        self.assertTrue(ok)
        self.assertEqual(tl.calls, 2)

    def test_both_calls_noop_fails(self):
        ok, tl = self._run([(False, False), (False, False)])
        self.assertFalse(ok)
        self.assertEqual(tl.calls, 2)
        self.assertEqual(len(tl.video), 2)  # items untouched

    def test_unverifiable_items_fall_back_to_retry_then_fail(self):
        # No usable IDs -> readback can't confirm deletion -> retry, then fail.
        ok, tl = self._run([(False, False), (False, False)],
                           items=[NoIdItem(None)])
        self.assertFalse(ok)
        self.assertEqual(tl.calls, 2)

    def test_items_still_present_true_when_ids_missing(self):
        tl = FlakyTimeline([], [])
        self.assertTrue(s._timeline_items_still_present(tl, [NoIdItem(None)]))


class DispatcherTest(unittest.TestCase):
    def _delete(self, plan):
        items = [FakeItem("a"), FakeItem("b")]
        tl = FlakyTimeline(items, plan)
        fake_proj = mock.Mock()
        fake_proj.GetCurrentTimeline.return_value = tl
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)):
            return s.timeline("delete_clips", {"clip_ids": ["a", "b"]}), tl

    def test_flaky_first_attempt_retries_to_success(self):
        res, tl = self._delete([(False, False), (True, True)])
        self.assertTrue(res["success"])
        self.assertEqual(tl.calls, 2)

    def test_false_negative_reports_success_without_retry(self):
        res, tl = self._delete([(False, True)])
        self.assertTrue(res["success"])
        self.assertEqual(tl.calls, 1)

    def test_genuine_failure_still_reports_false(self):
        res, tl = self._delete([(False, False), (False, False)])
        self.assertFalse(res["success"])


class LiftRangeIntegrationTest(unittest.TestCase):
    def test_lift_range_survives_flaky_first_attempt(self):
        items = [FakeItem("a")]
        tl = FlakyTimeline(items, [(False, False), (True, True)])
        res = s._timeline_lift_range_impl(tl, {"start_frame": 0, "end_frame": 24})
        self.assertTrue(res["success"])
        self.assertEqual(res["deleted_ids"], ["a"])
        self.assertEqual(tl.calls, 2)


if __name__ == "__main__":
    unittest.main()
