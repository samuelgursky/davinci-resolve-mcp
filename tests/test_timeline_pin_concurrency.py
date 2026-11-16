"""Issue #382: a write must not follow the current timeline to another client's.

A pin makes its timeline current once, at the start of a call. ripple_insert,
move and slip then rebuild items with MediaPool.AppendToTimeline, which writes
to whatever is current *when it runs*. Another client switching the current
timeline in between used to send the deletes to our timeline and the
re-appends to theirs, under a reported success. These tests move the current
timeline mid-call and check that the write is refused with both timelines
named, and that nothing reaches the other timeline.
"""

from __future__ import annotations

import unittest
from unittest import mock

import src.server as s
from tests.test_ripple_insert import MediaPoolStub, ProjectStub, _insert_params, _ripple_fixture
from tests.test_timeline_pinning import _Project, _Timeline


class _OtherTimeline:
    def GetName(self):
        return "Other agent"

    def GetUniqueId(self):
        return "timeline-2"


class _CurrentProject(ProjectStub):
    """ProjectStub that reports a current timeline the test can move."""

    def __init__(self, media_pool, current):
        super().__init__(media_pool)
        self.current = current

    def GetCurrentTimeline(self):
        return self.current


class _HijackingMediaPool(MediaPoolStub):
    """After `after` appends, another client makes a different timeline current."""

    def __init__(self, base: MediaPoolStub, after: int):
        super().__init__(base.root, base.timeline)
        self.after = after
        self.project = None

    def AppendToTimeline(self, infos):
        out = super().AppendToTimeline(infos)
        if self.append_count >= self.after and self.project is not None:
            self.project.current = _OtherTimeline()
        return out


def _execute(proj, tl):
    with mock.patch.object(s, "_confirm_token_required", return_value=False):
        return s._timeline_ripple_insert_impl(proj, tl, _insert_params(dry_run=False))


class RippleInsertFollowsNoOtherTimelineTest(unittest.TestCase):
    def test_a_move_before_the_delete_refuses_with_nothing_changed(self):
        _, tl, mp, items = _ripple_fixture()
        proj = _CurrentProject(mp, current=_OtherTimeline())
        err = _execute(proj, tl)["error"]
        self.assertEqual(err["code"], "TIMELINE_CHANGED")
        self.assertEqual(err["state"]["expected_timeline"]["id"], "timeline-1")
        self.assertEqual(err["state"]["current_timeline"]["name"], "Other agent")
        self.assertIn("'Other agent'", err["message"])
        self.assertEqual(mp.append_count, 0)
        self.assertEqual(len(tl.GetItemListInTrack("video", 1)), 3, "nothing may be deleted")

    def test_a_move_mid_rebuild_stops_every_further_append_and_says_what_ran(self):
        _, tl, base_mp, _ = _ripple_fixture()
        mp = _HijackingMediaPool(base_mp, after=1)
        proj = _CurrentProject(mp, current=tl)
        mp.project = proj
        out = _execute(proj, tl)
        err = out["error"]
        self.assertEqual(err["code"], "TIMELINE_CHANGED")
        self.assertFalse(err["retryable"], "a retry would repeat the delete that already ran")
        self.assertEqual(mp.append_count, 1, "no append may run once the timeline moved")
        state = err["state"]
        self.assertEqual(state["tail_items_deleted"], 2)
        self.assertEqual(state["tail_items_reappended"], 1)
        self.assertEqual(state["inserts_placed"], 0)
        self.assertIn("archive", err["remediation"])

    def test_a_pinned_call_reports_the_pin_as_lost(self):
        _, tl, mp, _ = _ripple_fixture()
        proj = _CurrentProject(mp, current=_OtherTimeline())
        token = s._pinned_timeline.set(tl)
        try:
            out = _execute(proj, tl)
        finally:
            s._pinned_timeline.reset(token)
        self.assertEqual(out["error"]["code"], "TIMELINE_PIN_LOST")

    def test_an_unreadable_current_timeline_does_not_block_the_edit(self):
        # ProjectStub has no GetCurrentTimeline: "not measured" must not refuse.
        proj, tl, _, _ = _ripple_fixture()
        self.assertTrue(_execute(proj, tl)["success"])


class GuardedAppendTest(unittest.TestCase):
    def setUp(self):
        _, self.tl, self.mp, _ = _ripple_fixture()

    def test_refuses_on_a_measured_mismatch(self):
        proj = _CurrentProject(self.mp, current=_OtherTimeline())
        with self.assertRaises(s._TimelineChanged) as ctx:
            s._guarded_append(self.mp, self.tl, [], proj=proj)
        self.assertEqual(ctx.exception.error["error"]["code"], "TIMELINE_CHANGED")

    def test_appends_when_current_matches_or_is_unknown(self):
        for current in (self.tl, None):
            proj = _CurrentProject(self.mp, current=current)
            self.assertEqual(s._guarded_append(self.mp, self.tl, [], proj=proj), [])

    def test_the_tool_wrapper_turns_an_uncaught_refusal_into_the_error(self):
        err = s._timeline_changed_error(self.tl, _OtherTimeline(), stage="x", pinned=False)

        @s._guard_missing_params
        def timeline(action, params=None):
            raise s._TimelineChanged(err)

        out = timeline("noop", {})
        self.assertEqual(out["error"]["code"], "TIMELINE_CHANGED")


class _HijackedProject(_Project):
    """The pin's switch lands, then another client moves the current timeline."""

    def __init__(self, timelines, current, hijacker):
        super().__init__(timelines, current)
        self.hijacker = hijacker
        self.reads_since_switch = None

    def SetCurrentTimeline(self, tl):
        self.reads_since_switch = 0
        return super().SetCurrentTimeline(tl)

    def GetCurrentTimeline(self):
        if self.reads_since_switch is not None:
            self.reads_since_switch += 1
            if self.reads_since_switch == 2:  # after the pin's own readback
                self.current = self.hijacker
        return self.current


class PinLostTest(unittest.TestCase):
    def setUp(self):
        self.a = _Timeline("A scratch", "uid-a")
        self.b = _Timeline("B edit", "uid-b")

    def _patch(self, proj):
        patcher = mock.patch.object(s, "_check", return_value=(object(), proj, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_pinned_write_refuses_instead_of_landing_on_the_new_current(self):
        proj = _HijackedProject([self.a, self.b], current=self.b, hijacker=self.b)
        self._patch(proj)
        out = s.timeline_item("set_name", {"item_index": 0, "name": "renamed", "timeline_id": "uid-a"})
        err = out["error"]
        self.assertEqual(err["code"], "TIMELINE_PIN_LOST")
        self.assertEqual(err["state"]["expected_timeline"]["id"], "uid-a")
        self.assertEqual(err["state"]["current_timeline"]["id"], "uid-b")
        self.assertEqual(self.b.items[0].name, "B edit-clip-0", "the other timeline must be untouched")
        self.assertEqual(self.a.items[0].name, "A scratch-clip-0")

    def test_media_pool_append_to_timeline_takes_a_pin(self):
        self.assertTrue(s._pin_aware("media_pool", "append_to_timeline"))
        # create/import read timeline_name as the NEW timeline's name.
        self.assertFalse(s._pin_aware("media_pool", "create_timeline_from_clips"))
        self.assertFalse(s._pin_aware("media_pool", "import_timeline"))
        proj = _Project([self.a, self.b], current=self.b)
        self._patch(proj)
        scope = s._CallScope("media_pool", "append_to_timeline",
                             ("append_to_timeline", {"clip_ids": ["x"], "timeline_id": "uid-a"}), {})
        try:
            self.assertIsNone(scope.error)
            self.assertIs(proj.current, self.a)
            self.assertIs(s._pinned_timeline.get(), self.a)
            scope.restore()
            self.assertIs(proj.current, self.b)
        finally:
            scope.close()
        self.assertIsNone(s._pinned_timeline.get(), "the pin must not outlive its call")


if __name__ == "__main__":
    unittest.main()
