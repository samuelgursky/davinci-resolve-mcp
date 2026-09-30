"""restore_page / restoring_page — putting Resolve back on the caller's page.

Issue #270: a frame capture left Resolve on the Deliver page. Measured on
Studio 19.1.3.7, the cause was that Project.GetCurrentRenderMode() — a getter —
switches Resolve to Deliver, and the capture read "the page the user is on"
after calling it. The restore then had nothing to restore. Separately, the
restore's OpenPage return was discarded and any exception swallowed, so a
switch that did not take would have said nothing either.

restoring_page reads the page BEFORE the block; restore_page reads it back
after the switch. The two page guards (Color for thumbnails, Edit for timeline
edits) carried the same discarded OpenPage and go through the same helper.
"""
import unittest
from unittest import mock

import src.server as s
from src.utils import page_lock


class _Resolve:
    """One globally-active page; OpenPage can refuse, lie, raise, or settle."""

    def __init__(self, page="deliver", refusals=0, lies=False, raises=False, readable=True):
        self.page = page
        self.refusals = refusals
        self.lies = lies
        self.raises = raises
        self.readable = readable
        self.opened = []

    def GetCurrentPage(self):
        if not self.readable:
            raise RuntimeError("no page")
        return self.page

    def OpenPage(self, page):
        self.opened.append(page)
        if self.raises:
            raise RuntimeError("bridge went away")
        if self.lies:
            return True
        if self.refusals > 0:
            self.refusals -= 1
            return False
        self.page = page
        return True


class RestorePageTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(page_lock.time, "sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_switch_that_takes_first_time_is_one_call_and_no_wait(self):
        resolve = _Resolve(page="deliver")
        out = page_lock.restore_page(resolve, "edit", what="a test")
        self.assertEqual(out, {"target": "edit", "restored": True, "page": "edit", "attempts": 1})
        self.assertEqual(resolve.opened, ["edit"])
        self.sleep.assert_not_called()

    def test_already_on_the_page_switches_nothing(self):
        resolve = _Resolve(page="edit")
        out = page_lock.restore_page(resolve, "edit", what="a test")
        self.assertTrue(out["restored"])
        self.assertEqual(out["attempts"], 0)
        self.assertEqual(resolve.opened, [])

    def test_a_refused_switch_is_retried_until_it_takes(self):
        resolve = _Resolve(page="deliver", refusals=2)
        out = page_lock.restore_page(resolve, "edit", what="a test")
        self.assertTrue(out["restored"])
        self.assertEqual(out["attempts"], 3)
        self.assertEqual(self.sleep.call_count, 2)
        self.assertNotIn("error", out)

    def test_a_switch_that_never_takes_is_reported_and_logged(self):
        resolve = _Resolve(page="deliver", refusals=99)
        with self.assertLogs("resolve-mcp.page-lock", level="WARNING") as logs:
            out = page_lock.restore_page(resolve, "edit", what="the render capture")
        self.assertFalse(out["restored"])
        self.assertEqual(out["page"], "deliver")
        self.assertEqual(out["attempts"], page_lock.PAGE_RESTORE_ATTEMPTS)
        self.assertEqual(out["error"], "OpenPage returned False")
        # No wait after the last attempt: there is nothing left to wait for.
        self.assertEqual(self.sleep.call_count, page_lock.PAGE_RESTORE_ATTEMPTS - 1)
        self.assertIn("the render capture", logs.output[0])
        self.assertIn("'deliver'", logs.output[0])

    def test_true_from_openpage_is_not_believed_over_the_page_read_back(self):
        resolve = _Resolve(page="deliver", lies=True)
        with self.assertLogs("resolve-mcp.page-lock", level="WARNING"):
            out = page_lock.restore_page(resolve, "edit", what="a test", attempts=2)
        self.assertFalse(out["restored"])
        self.assertEqual(out["error"], "OpenPage returned True but Resolve is on 'deliver'")

    def test_an_unreadable_page_falls_back_to_openpages_own_answer(self):
        # Nothing to verify against, so the return is all the evidence there is.
        resolve = _Resolve(page="deliver", readable=False)
        out = page_lock.restore_page(resolve, "edit", what="a test")
        self.assertTrue(out["restored"])
        self.assertIsNone(out["page"])
        self.assertEqual(resolve.opened, ["edit"])

    def test_an_unreadable_page_and_a_refusal_is_a_failure(self):
        resolve = _Resolve(page="deliver", readable=False, refusals=99)
        with self.assertLogs("resolve-mcp.page-lock", level="WARNING"):
            out = page_lock.restore_page(resolve, "edit", what="a test", attempts=3)
        self.assertFalse(out["restored"])
        self.assertEqual(out["attempts"], 3)

    def test_a_raising_openpage_is_caught_and_named(self):
        resolve = _Resolve(page="deliver", raises=True)
        with self.assertLogs("resolve-mcp.page-lock", level="WARNING"):
            out = page_lock.restore_page(resolve, "edit", what="a test", attempts=2)
        self.assertFalse(out["restored"])
        self.assertIn("bridge went away", out["error"])


class _RenderProject:
    """GetCurrentRenderMode switches to Deliver, as measured on 19.1.3.7."""

    def __init__(self, resolve, mode=1):
        self.resolve = resolve
        self.mode = mode

    def GetCurrentRenderMode(self):
        self.resolve.page = "deliver"
        return self.mode


class RestoringPageTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(page_lock.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_block_that_moves_the_page_is_undone(self):
        resolve = _Resolve(page="edit")
        with page_lock.restoring_page(resolve, what="a test") as original:
            self.assertEqual(original, "edit")
            resolve.page = "deliver"
        self.assertEqual(resolve.page, "edit")
        self.assertEqual(resolve.opened, ["edit"])

    def test_a_block_that_leaves_the_page_alone_switches_nothing(self):
        resolve = _Resolve(page="edit")
        with page_lock.restoring_page(resolve, what="a test"):
            pass
        self.assertEqual(resolve.opened, [])

    def test_an_unreadable_page_is_never_restored_to_a_guess(self):
        resolve = _Resolve(page="edit", readable=False)
        with page_lock.restoring_page(resolve, what="a test") as original:
            self.assertIsNone(original)
        self.assertEqual(resolve.opened, [])

    def test_no_resolve_is_tolerated(self):
        with page_lock.restoring_page(None, what="a test") as original:
            self.assertIsNone(original)

    def test_the_page_is_restored_when_the_block_raises(self):
        resolve = _Resolve(page="color")
        with self.assertRaises(ValueError):
            with page_lock.restoring_page(resolve, what="a test"):
                resolve.page = "deliver"
                raise ValueError("boom")
        self.assertEqual(resolve.page, "color")

    def test_render_get_mode_does_not_leave_the_user_on_deliver(self):
        resolve = _Resolve(page="edit")
        proj = _RenderProject(resolve, mode=0)
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), proj, None)), \
             mock.patch.object(s, "get_resolve", return_value=resolve):
            out = s.render("get_mode")
        self.assertEqual(out["mode"], 0)
        self.assertEqual(resolve.page, "edit")

    def test_probe_render_settings_does_not_leave_the_user_on_deliver(self):
        resolve = _Resolve(page="color")
        proj = mock.Mock()
        proj.GetCurrentRenderMode.side_effect = lambda: setattr(resolve, "page", "deliver") or 1
        proj.GetRenderJobList.return_value = []
        proj.IsRenderingInProgress.return_value = False
        proj.GetCurrentRenderFormatAndCodec.return_value = {"format": "mov", "codec": "H.264"}
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), proj, None)), \
             mock.patch.object(s, "get_resolve", return_value=resolve):
            out = s.render("probe_render_settings")
        self.assertEqual(out["mode"], 1)
        self.assertEqual(resolve.page, "color")

    def test_granular_get_current_render_mode_does_not_leave_the_user_on_deliver(self):
        from src.granular import project as granular_project

        resolve = _Resolve(page="fairlight")
        proj = _RenderProject(resolve, mode=1)
        resolve.GetProjectManager = lambda: mock.Mock(GetCurrentProject=lambda: proj)
        with mock.patch.object(granular_project, "get_resolve", return_value=resolve):
            out = granular_project.get_current_render_mode()
        self.assertEqual(out["render_mode"], 1)
        self.assertEqual(resolve.page, "fairlight")


class PageGuardRestoreTest(unittest.TestCase):
    """The guards' own way back is checked and logged, not discarded."""

    def setUp(self):
        patcher = mock.patch.object(page_lock.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_color_guard_returns_to_the_callers_page(self):
        resolve = _Resolve(page="edit")
        with page_lock.color_page_for_thumbnails(resolve) as on_color:
            self.assertTrue(on_color)
            self.assertEqual(resolve.page, "color")
        self.assertEqual(resolve.page, "edit")

    def test_color_guard_retries_a_way_back_that_does_not_take_at_once(self):
        resolve = _Resolve(page="edit")
        with page_lock.color_page_for_thumbnails(resolve):
            resolve.refusals = 2
        self.assertEqual(resolve.page, "edit")
        self.assertEqual(resolve.opened, ["color", "edit", "edit", "edit"])

    def test_color_guard_logs_a_way_back_that_never_takes(self):
        resolve = _Resolve(page="edit")
        with self.assertLogs("resolve-mcp.page-lock", level="WARNING") as logs:
            with page_lock.color_page_for_thumbnails(resolve):
                resolve.refusals = 99
        self.assertEqual(resolve.page, "color")
        self.assertIn("could not restore the 'edit' page after a Color-page read", logs.output[0])

    def test_edit_guard_logs_a_way_back_that_never_takes(self):
        resolve = _Resolve(page="fairlight")
        with self.assertLogs("resolve-mcp.page-lock", level="WARNING") as logs:
            with page_lock.edit_page_for_timeline_edits(resolve) as on_edit:
                self.assertTrue(on_edit)
                resolve.refusals = 99
        self.assertIn("could not restore the 'fairlight' page after an Edit-page edit",
                      logs.output[0])

    def test_edit_guard_that_never_left_does_not_switch_back(self):
        resolve = _Resolve(page="fairlight", refusals=99)
        with page_lock.edit_page_for_timeline_edits(resolve) as on_edit:
            self.assertFalse(on_edit)
        self.assertEqual(resolve.opened, ["edit"])


class RestoreStatePageTest(unittest.TestCase):
    """restore_state lists the page as restored only when it was read back."""

    def setUp(self):
        patcher = mock.patch.object(page_lock.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.token = "page-restore-test"
        s._RESOLVE_STATE_SNAPSHOTS[self.token] = {"page": "edit"}
        self.addCleanup(s._RESOLVE_STATE_SNAPSHOTS.pop, self.token, None)

    def _restore(self, resolve):
        resolve.GetProjectManager = lambda: None
        with mock.patch.object(s, "get_resolve", return_value=resolve):
            return s._resolve_restore_state({"state_token": self.token})

    def test_a_page_that_came_back_is_listed(self):
        out = self._restore(_Resolve(page="color"))
        self.assertEqual(out["restored"]["page"], "edit")
        self.assertNotIn("page_error", out["restored"])

    def test_a_page_that_did_not_come_back_is_an_error_not_a_claim(self):
        with self.assertLogs("resolve-mcp.page-lock", level="WARNING"):
            out = self._restore(_Resolve(page="color", refusals=99))
        self.assertNotIn("page", out["restored"])
        self.assertEqual(out["restored"]["page_error"], "OpenPage returned False")


if __name__ == "__main__":
    unittest.main()
