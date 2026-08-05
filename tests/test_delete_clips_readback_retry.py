"""api_truth 'Timeline.DeleteClips (requires the Edit page; flaky first
attempt)' — page guard and readback-and-retry.

Timeline.DeleteClips can return False on the first call even when every item
is valid and present; an identical immediate retry succeeds. It can also
return False while actually deleting. _timeline_delete_clips_verified treats
a False as advisory and reads the tracks back — but only a COMPLETED walk
over identifiable items can report 'absent'. A walk that raised, enumerated
nothing, or covered items with no readable ID is 'unknown': never reported as
success, and never retried (a second destructive call we equally cannot read
buys no information).

These tests use a fake timeline whose DeleteClips follows a scripted lie-plan
and whose track walk can be made blind, so both the flaky-retry path and the
blind-readback path are exercised offline.
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
    (returned_bool, actually_deletes) pair — so it can lie either way.

    blind='raise'  -> GetItemListInTrack raises (bridge hiccup mid-readback)
    blind='empty'  -> GetTrackCount reports no tracks at all
    blind='count_raises' -> GetTrackCount raises
    """

    def __init__(self, items, plan, blind=None):
        self.video = list(items)
        self.plan = list(plan)
        self.blind = blind
        self.calls = 0

    def GetTrackCount(self, track_type):
        if self.blind == "count_raises":
            raise RuntimeError("bridge lost")
        if self.blind == "empty":
            return 0
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, index):
        if self.blind == "raise":
            raise RuntimeError("bridge lost")
        return list(self.video) if (track_type, index) == ("video", 1) else []

    def DeleteClips(self, items, ripple):
        self.calls += 1
        returned, deletes = self.plan.pop(0)
        if deletes:
            gone = {id(it) for it in items}
            self.video = [it for it in self.video if id(it) not in gone]
        return returned


class PresenceTest(unittest.TestCase):
    """The tri-state readback itself. 'unknown' is the load-bearing state."""

    def test_present_when_item_found(self):
        items = [FakeItem("a")]
        tl = FlakyTimeline(items, [])
        self.assertEqual(s._timeline_items_presence(tl, items), "present")

    def test_absent_after_a_complete_walk(self):
        tl = FlakyTimeline([], [])
        self.assertEqual(s._timeline_items_presence(tl, [FakeItem("a")]), "absent")

    def test_walk_that_raises_is_unknown_not_absent(self):
        tl = FlakyTimeline([], [], blind="raise")
        self.assertEqual(s._timeline_items_presence(tl, [FakeItem("a")]), "unknown")

    def test_track_count_raising_is_unknown(self):
        tl = FlakyTimeline([], [], blind="count_raises")
        self.assertEqual(s._timeline_items_presence(tl, [FakeItem("a")]), "unknown")

    def test_enumerating_no_tracks_is_unknown(self):
        tl = FlakyTimeline([], [], blind="empty")
        self.assertEqual(s._timeline_items_presence(tl, [FakeItem("a")]), "unknown")

    def test_unreadable_id_is_unknown(self):
        tl = FlakyTimeline([], [])
        self.assertEqual(s._timeline_items_presence(tl, [NoIdItem(None)]), "unknown")

    def test_one_unreadable_id_taints_the_whole_batch(self):
        tl = FlakyTimeline([], [])
        self.assertEqual(
            s._timeline_items_presence(tl, [FakeItem("a"), NoIdItem(None)]),
            "unknown",
        )

    def test_sighting_wins_over_a_partial_walk_failure(self):
        # video track walks fine and holds the item; audio raises.
        items = [FakeItem("a")]
        tl = FlakyTimeline(items, [])
        real_list = tl.GetItemListInTrack

        def flaky_list(track_type, index):
            if track_type != "video":
                raise RuntimeError("bridge lost")
            return real_list(track_type, index)

        with mock.patch.object(tl, "GetTrackCount", return_value=1), \
             mock.patch.object(tl, "GetItemListInTrack", side_effect=flaky_list):
            self.assertEqual(s._timeline_items_presence(tl, items), "present")


class HelperTest(unittest.TestCase):
    def _run(self, plan, items=None, blind=None):
        items = items if items is not None else [FakeItem("a"), FakeItem("b")]
        tl = FlakyTimeline(items, plan, blind=blind)
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

    # ── the blind-readback class: never success, never a blind retry ──────
    def test_blind_readback_after_failed_delete_is_not_success(self):
        ok, tl = self._run([(False, False)], blind="raise")
        self.assertFalse(ok)
        self.assertEqual(tl.calls, 1)  # unknown -> no second destructive call

    def test_readback_enumerating_nothing_is_not_success(self):
        ok, tl = self._run([(False, False)], blind="empty")
        self.assertFalse(ok)
        self.assertEqual(tl.calls, 1)

    def test_unverifiable_items_are_not_deleted_twice(self):
        ok, tl = self._run([(False, False)], items=[NoIdItem(None)])
        self.assertFalse(ok)
        self.assertEqual(tl.calls, 1)

    def test_blind_readback_never_masks_a_true_return(self):
        ok, tl = self._run([(True, True)], blind="raise")
        self.assertTrue(ok)  # honest True is still honest; no readback needed
        self.assertEqual(tl.calls, 1)

    def test_readback_going_blind_only_after_the_retry_is_not_success(self):
        items = [FakeItem("a")]
        tl = FlakyTimeline(items, [(False, False), (False, False)])
        original = s._timeline_items_presence
        seen = []

        def blind_second_time(timeline, targets):
            seen.append(1)
            if len(seen) == 1:
                return original(timeline, targets)
            return "unknown"

        with mock.patch.object(s, "_timeline_items_presence",
                               side_effect=blind_second_time):
            ok = s._timeline_delete_clips_verified(tl, items, False)
        self.assertFalse(ok)
        self.assertEqual(tl.calls, 2)


class FakeResolve:
    """Just enough of the Resolve app object for the page guard."""

    def __init__(self, page="edit", open_ok=True, raise_on=None, events=None):
        self.page = page
        self.open_ok = open_ok
        self.raise_on = raise_on  # 'get' or 'open'
        self.events = events if events is not None else []

    def GetCurrentPage(self):
        if self.raise_on == "get":
            raise RuntimeError("bridge lost")
        return self.page

    def OpenPage(self, page):
        if self.raise_on == "open":
            raise RuntimeError("bridge lost")
        self.events.append(("open", page))
        if self.open_ok:
            self.page = page
        return self.open_ok

    @property
    def opened(self):
        return [page for kind, page in self.events if kind == "open"]


class PageGuardTest(unittest.TestCase):
    """The wrong-page failure: on Fairlight the call deterministically
    returns False and deletes nothing. The guard switches to Edit for the
    call and restores the caller's page after."""

    def _logged(self, tl, events):
        real_delete = tl.DeleteClips

        def logged_delete(items, ripple):
            events.append(("delete", None))
            return real_delete(items, ripple)

        tl.DeleteClips = logged_delete
        return tl

    def test_switches_to_edit_before_delete_and_restores_after(self):
        events = []
        items = [FakeItem("a")]
        tl = self._logged(FlakyTimeline(items, [(True, True)]), events)
        r = FakeResolve(page="fairlight", events=events)
        ok = s._timeline_delete_clips_verified(tl, items, False, resolve=r)
        self.assertTrue(ok)
        self.assertEqual(events, [("open", "edit"), ("delete", None), ("open", "fairlight")])

    def test_already_on_edit_touches_no_pages(self):
        items = [FakeItem("a")]
        tl = FlakyTimeline(items, [(True, True)])
        r = FakeResolve(page="edit")
        self.assertTrue(s._timeline_delete_clips_verified(tl, items, False, resolve=r))
        self.assertEqual(r.opened, [])

    def test_page_restored_even_when_the_delete_fails(self):
        items = [FakeItem("a")]
        tl = FlakyTimeline(items, [(False, False), (False, False)])
        r = FakeResolve(page="fairlight")
        ok = s._timeline_delete_clips_verified(tl, items, False, resolve=r)
        self.assertFalse(ok)
        self.assertEqual(r.opened, ["edit", "fairlight"])
        self.assertEqual(r.page, "fairlight")

    def test_guard_failure_never_blocks_the_delete(self):
        # GetCurrentPage raising must not stop the delete attempt.
        items = [FakeItem("a")]
        tl = FlakyTimeline(items, [(True, True)])
        r = FakeResolve(raise_on="get")
        self.assertTrue(s._timeline_delete_clips_verified(tl, items, False, resolve=r))
        self.assertEqual(tl.calls, 1)

    def test_openpage_refusing_means_no_restore_attempt(self):
        items = [FakeItem("a")]
        tl = FlakyTimeline(items, [(True, True)])
        r = FakeResolve(page="fairlight", open_ok=False)
        self.assertTrue(s._timeline_delete_clips_verified(tl, items, False, resolve=r))
        self.assertEqual(r.opened, ["edit"])  # tried once; no restore of a page never left

    def test_no_resolve_handle_means_no_guard(self):
        # Direct callers (and offline tests) pass no handle; behavior is
        # exactly the pre-guard helper.
        items = [FakeItem("a")]
        tl = FlakyTimeline(items, [(False, False), (True, True)])
        self.assertTrue(s._timeline_delete_clips_verified(tl, items, False))
        self.assertEqual(tl.calls, 2)


class DispatcherTest(unittest.TestCase):
    def _delete(self, plan, blind=None, resolve=None):
        items = [FakeItem("a"), FakeItem("b")]
        tl = FlakyTimeline(items, plan, blind=blind)
        fake_proj = mock.Mock()
        fake_proj.GetCurrentTimeline.return_value = tl
        with mock.patch.object(s, "get_resolve", return_value=resolve), \
             mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)):
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

    def test_dispatcher_threads_the_resolve_handle_to_the_guard(self):
        r = FakeResolve(page="fairlight")
        res, tl = self._delete([(True, True)], resolve=r)
        self.assertTrue(res["success"])
        self.assertEqual(r.opened, ["edit", "fairlight"])


class LiftRangeIntegrationTest(unittest.TestCase):
    def test_lift_range_survives_flaky_first_attempt(self):
        items = [FakeItem("a")]
        tl = FlakyTimeline(items, [(False, False), (True, True)])
        res = s._timeline_lift_range_impl(tl, {"start_frame": 0, "end_frame": 24})
        self.assertTrue(res["success"])
        self.assertEqual(res["deleted_ids"], ["a"])
        self.assertEqual(tl.calls, 2)

    def test_lift_range_does_not_claim_success_on_a_blind_readback(self):
        items = [FakeItem("a")]
        tl = FlakyTimeline(items, [(False, False)])
        collected = s._timeline_lift_range_impl  # resolve before patching tl
        tl.blind = None
        res = None
        # Walk succeeds while collecting the range, then goes blind for the
        # post-delete readback — the ordering that produced the regression.
        original_list = tl.GetItemListInTrack

        def blind_after_delete(track_type, index):
            if tl.calls:
                raise RuntimeError("bridge lost")
            return original_list(track_type, index)

        with mock.patch.object(tl, "GetItemListInTrack", side_effect=blind_after_delete):
            res = collected(tl, {"start_frame": 0, "end_frame": 24})
        self.assertFalse(res["success"])
        self.assertEqual(tl.calls, 1)


if __name__ == "__main__":
    unittest.main()
