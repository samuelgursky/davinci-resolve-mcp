"""Inputs a call accepted with success while doing something else (#365-#368).

Each case used to answer success: true while dropping or misapplying what the
caller asked for, so the caller found out only from a later read-back, if at all.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import src.server as s
from src.utils import destructive_hook
from src.utils.render_target import missing_target_dir
from tests.test_media_pool_append_verification import (
    ClipStub,
    FolderStub,
    MediaPoolStub,
    ProjectStub,
    TimelineStub,
)
from tests.test_plugin_write_gates import _HookState


class _StartTimeline(TimelineStub):
    def GetStartFrame(self):
        return 86400


class _RecordingMediaPool(MediaPoolStub):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sent = []

    def AppendToTimeline(self, clips):
        self.sent.extend(c.get("recordFrame") for c in clips)
        return super().AppendToTimeline(clips)


class TopLevelRecordFrameModeTest(unittest.TestCase):
    """#365: record_frame_mode beside clip_infos was dropped."""

    ROW = {"clip_id": "clip-1", "start_frame": 0, "end_frame": 24, "track_index": 1}

    def _append(self, params):
        tl = _StartTimeline()
        mp = _RecordingMediaPool(FolderStub([ClipStub()]), tl)
        with mock.patch.object(s, "_get_mp", return_value=(None, ProjectStub(tl), mp, None)):
            return s.media_pool("append_to_timeline", params), mp.sent

    def test_top_level_absolute_places_the_raw_frame(self):
        result, sent = self._append(
            {"clip_infos": [dict(self.ROW, record_frame=87600)], "record_frame_mode": "absolute"})
        self.assertTrue(result.get("success"), result)
        self.assertEqual(sent, [87600])

    def test_top_level_absolute_below_start_is_refused_not_offset(self):
        result, sent = self._append(
            {"clip_infos": [dict(self.ROW, record_frame=1200)], "record_frame_mode": "absolute"})
        self.assertIn("before the timeline start frame 86400", result["error"]["message"])
        self.assertEqual(sent, [], "nothing may reach AppendToTimeline")

    def test_a_rows_own_mode_wins_over_the_top_level_one(self):
        rows = [dict(self.ROW, record_frame=24, record_frame_mode="relative")]
        result, sent = self._append({"clip_infos": rows, "record_frame_mode": "absolute"})
        self.assertTrue(result.get("success"), result)
        self.assertEqual(sent, [86424])

    def test_without_any_mode_frames_stay_relative(self):
        result, sent = self._append({"clip_infos": [dict(self.ROW, record_frame=24)]})
        self.assertTrue(result.get("success"), result)
        self.assertEqual(sent, [86424])

    def test_an_unknown_top_level_mode_is_refused(self):
        result, sent = self._append(
            {"clip_infos": [dict(self.ROW, record_frame=24)], "record_frame_mode": "sideways"})
        self.assertIn("record_frame_mode must be", result["error"]["message"])
        self.assertEqual(sent, [])


class DuplicateDoesNotArchiveTheSourceTest(_HookState):
    """#366: duplicating archived the untouched source timeline."""

    def test_duplicate_is_gated_and_audited_but_not_archived(self):
        self._prefs()
        provider_calls: list = []
        destructive_hook.register_project_root_provider(lambda: provider_calls.append(1))

        @destructive_hook.destructive_op("timeline")
        def handler(action, params=None):
            return {"success": True}

        result = handler("duplicate", {})
        self.assertTrue(result["success"], result)
        self.assertFalse(result["_versioning"]["archived"], result)
        self.assertEqual(result["_versioning"]["skipped_reason"], "source_timeline_unchanged")
        self.assertEqual(provider_calls, [], "duplicate must not resolve the version context")
        reasons = {event.get("reason") for event in self._audit_events()}
        self.assertIn("source_timeline_unchanged", reasons)

    def test_duplicate_stays_registered_so_safe_mode_and_audit_still_apply(self):
        self.assertIn("duplicate", destructive_hook.DESTRUCTIVE_ACTIONS_BY_TOOL["timeline"])

    def test_a_real_timeline_edit_still_reaches_the_archive_path(self):
        self._prefs()
        provider_calls: list = []
        destructive_hook.register_project_root_provider(lambda: provider_calls.append(1))

        @destructive_hook.destructive_op("timeline")
        def handler(action, params=None):
            return {"success": True}

        handler("delete_clips", {"clip_ids": ["x"]})
        self.assertEqual(provider_calls, [1], "an edit must still look for a version context")


class _LinkedItem:
    def __init__(self, name, uid):
        self.name, self.uid = name, uid

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.uid

    def GetLinkedItems(self):
        return []


class GetClipsLinkedPinTest(unittest.TestCase):
    """#367 report: get_clips_linked resolving items on the current timeline.

    Does not reproduce against the compound tool: the pin switches, the item is
    found on the pinned timeline, and the caller's timeline comes back. Kept so
    a regression of the pin for this action fails here.
    """

    def test_timeline_id_finds_items_on_the_pinned_timeline(self):
        from tests.test_timeline_pinning import _Project, _Timeline

        class _TL(_Timeline):
            def __init__(self, name, uid):
                super().__init__(name, uid)
                self.items = [_LinkedItem(f"{name}-clip", f"{uid}-item")]

            def GetTrackCount(self, track_type):
                return 1 if track_type == "video" else 0

        a, b = _TL("A", "uid-a"), _TL("B", "uid-b")
        proj = _Project([a, b], current=a)
        with mock.patch.object(s, "_check", return_value=(object(), proj, None)):
            result = s.timeline("get_clips_linked", {"clip_ids": ["uid-b-item"], "timeline_id": "uid-b"})
        self.assertEqual(result["groups"][0].get("name"), "B-clip", result)
        self.assertNotIn("error", result["groups"][0])
        self.assertIs(proj.current, a)
        self.assertNotIn("ignored_params", result)


class _RenderProject:
    def __init__(self):
        self.sent = []

    def SetRenderSettings(self, settings):
        self.sent.append(dict(settings))
        return True


class RenderTargetDirTest(unittest.TestCase):
    """#368: set_settings took a TargetDir that does not exist."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.missing = os.path.join(self.tmp.name, "no-such-dir")
        self.proj = _RenderProject()
        patcher = mock.patch.object(s, "_check", return_value=(object(), self.proj, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_missing_target_dir_is_refused_before_resolve_sees_it(self):
        result = s.render("set_settings", {"settings": {"TargetDir": self.missing}})
        self.assertEqual(result["error"]["code"], "TARGET_DIR_NOT_FOUND", result)
        self.assertEqual(self.proj.sent, [])

    def test_an_existing_target_dir_is_sent(self):
        result = s.render("set_settings", {"settings": {"TargetDir": self.tmp.name}})
        self.assertTrue(result.get("success"), result)
        self.assertEqual(self.proj.sent, [{"TargetDir": self.tmp.name}])

    def test_settings_without_target_dir_are_unaffected(self):
        result = s.render("set_settings", {"settings": {"CustomName": "x"}})
        self.assertTrue(result.get("success"), result)

    def test_the_helper_ignores_absent_and_empty_values(self):
        self.assertIsNone(missing_target_dir({}))
        self.assertIsNone(missing_target_dir({"TargetDir": ""}))
        self.assertIsNone(missing_target_dir({"TargetDir": self.tmp.name}))
        self.assertEqual(missing_target_dir({"TargetDir": self.missing}), self.missing)

    def test_the_granular_tool_refuses_too(self):
        from src.granular import project as granular_project

        with mock.patch.object(granular_project, "get_resolve",
                               side_effect=AssertionError("reached Resolve")):
            result = granular_project.set_render_settings({"TargetDir": self.missing})
        self.assertIn("TargetDir does not exist", result.get("error", ""), result)


if __name__ == "__main__":
    unittest.main()
