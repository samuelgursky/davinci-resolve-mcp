"""Contract tests for the granular 21.0.4 parity wrappers (issue #140).

The compound tools gained the 21.0.4 surfaces in #133/#139; these cover the
granular equivalents:

  - resolve_control: get_layout_preset_list, get_burn_in_preset_list,
    delete_burn_in_preset, and the six *_user_preferences_preset tools
  - project: get_project_attributes_in_current_folder
  - media_pool_item: get_clip_timeline
  - timeline: get_selected_timeline_items

The 21.0.4 methods are unavailable on the 19.1.3 baseline this suite runs
against, so every case here is a stub contract, not a live result.
"""
import unittest

import src.granular.resolve_control as rc
import src.granular.project as gproject
import src.granular.media_pool_item as gmpi
import src.granular.timeline as gtimeline


# ── Stubs ────────────────────────────────────────────────────────────────────


class Resolve2104:
    def __init__(self):
        self.calls = []

    def GetLayoutPresetList(self):
        return ["Edit Layout", "Grade Layout"]

    def GetBurnInPresetList(self):
        return ["Dailies TC"]

    def DeleteBurnInPreset(self, name):
        self.calls.append(("DeleteBurnInPreset", name))
        return True

    def GetUserPreferencesPresetList(self):
        return ["Laptop"]

    def SaveUserPreferencesPreset(self, name):
        self.calls.append(("SaveUserPreferencesPreset", name))
        return True

    def LoadUserPreferencesPreset(self, name):
        self.calls.append(("LoadUserPreferencesPreset", name))
        return True

    def DeleteUserPreferencesPreset(self, name):
        self.calls.append(("DeleteUserPreferencesPreset", name))
        return True

    def ImportUserPreferencesPreset(self, path, name=None):
        self.calls.append(("ImportUserPreferencesPreset", path, name))
        return True

    def ExportUserPreferencesPreset(self, name, path):
        self.calls.append(("ExportUserPreferencesPreset", name, path))
        return True


class LegacyResolve:
    """A pre-21.0.4 build — none of the new methods exist."""


class Pm2104:
    def GetProjectAttributesInCurrentFolder(self):
        return {"Zenith_Online": {"lastModifiedDate": "2026-08-05T22:30:00-04:00",
                                  "creationDate": "2026-07-01T09:00:00-04:00",
                                  "notes": "", "liveCollaborationMode": "multi_user"}}


class LegacyPm:
    pass


class TimelineObj:
    def GetName(self):
        return "SEQ_01"

    def GetUniqueId(self):
        return "tl-1"

    def GetStartFrame(self):
        return 86400

    def GetEndFrame(self):
        return 87000


class Clip2104:
    def __init__(self, timeline=None):
        self._timeline = timeline

    def GetName(self):
        return "SEQ_01"

    def GetUniqueId(self):
        return "c1"

    def GetTimeline(self):
        return self._timeline


class LegacyClip:
    def GetName(self):
        return "shot_010.mov"

    def GetUniqueId(self):
        return "L1"


class SelectedItem:
    def GetName(self):
        return "shot_010.mov"

    def GetUniqueId(self):
        return "ti-1"

    def GetStart(self):
        return 86400

    def GetEnd(self):
        return 86448


class SelectionTimeline2104:
    def GetSelectedClips(self):
        return [SelectedItem()]


class LegacyTimeline:
    pass


class MediaPoolStub:
    def GetRootFolder(self):
        return object()


# ── resolve_control preset tools ─────────────────────────────────────────────


class GranularPresetToolsTest(unittest.TestCase):
    def setUp(self):
        self.resolve = Resolve2104()
        self._orig = rc.get_resolve
        rc.get_resolve = lambda: self.resolve

    def tearDown(self):
        rc.get_resolve = self._orig

    def test_layout_preset_list(self):
        out = rc.get_layout_preset_list()
        self.assertEqual(out["presets"], ["Edit Layout", "Grade Layout"])

    def test_burn_in_list_and_delete(self):
        self.assertEqual(rc.get_burn_in_preset_list()["presets"], ["Dailies TC"])
        out = rc.delete_burn_in_preset("Dailies TC")
        self.assertTrue(out["success"])
        self.assertIn(("DeleteBurnInPreset", "Dailies TC"), self.resolve.calls)

    def test_user_prefs_family_round_trip(self):
        self.assertEqual(rc.get_user_preferences_preset_list()["presets"], ["Laptop"])
        self.assertTrue(rc.save_user_preferences_preset("Laptop")["success"])
        self.assertTrue(rc.load_user_preferences_preset("Laptop")["success"])
        self.assertTrue(rc.delete_user_preferences_preset("Laptop")["success"])
        self.assertEqual([c[0] for c in self.resolve.calls],
                         ["SaveUserPreferencesPreset", "LoadUserPreferencesPreset",
                          "DeleteUserPreferencesPreset"])

    def test_import_without_name_uses_single_arg_and_filename(self):
        out = rc.import_user_preferences_preset("/tmp/StudioPrefs")
        self.assertTrue(out["success"])
        self.assertEqual(out["preset_name"], "StudioPrefs")
        self.assertIn("not auto-loaded", out["note"])
        self.assertIn(("ImportUserPreferencesPreset", "/tmp/StudioPrefs", None),
                      self.resolve.calls)

    def test_import_with_name_uses_two_arg_form(self):
        out = rc.import_user_preferences_preset("/tmp/StudioPrefs", "Studio")
        self.assertEqual(out["preset_name"], "Studio")
        self.assertIn(("ImportUserPreferencesPreset", "/tmp/StudioPrefs", "Studio"),
                      self.resolve.calls)

    def test_export_passes_name_and_path(self):
        out = rc.export_user_preferences_preset("Laptop", "/tmp/out")
        self.assertTrue(out["success"])
        self.assertIn(("ExportUserPreferencesPreset", "Laptop", "/tmp/out"),
                      self.resolve.calls)

    def test_load_docstring_carries_the_session_wide_warning(self):
        self.assertIn("SESSION-WIDE", rc.load_user_preferences_preset.__doc__)

    def test_pre_2104_build_is_version_guarded(self):
        rc.get_resolve = lambda: LegacyResolve()
        for tool, args in ((rc.get_layout_preset_list, ()),
                           (rc.get_burn_in_preset_list, ()),
                           (rc.delete_burn_in_preset, ("x",)),
                           (rc.get_user_preferences_preset_list, ()),
                           (rc.save_user_preferences_preset, ("x",)),
                           (rc.load_user_preferences_preset, ("x",)),
                           (rc.delete_user_preferences_preset, ("x",)),
                           (rc.import_user_preferences_preset, ("/tmp/x",)),
                           (rc.export_user_preferences_preset, ("x", "/tmp/x"))):
            out = tool(*args)
            self.assertIn("error", out, tool.__name__)
            self.assertIn("21.0.4", str(out), tool.__name__)


# ── project attributes ───────────────────────────────────────────────────────


class GranularProjectAttributesTest(unittest.TestCase):
    def setUp(self):
        self._orig = gproject.get_project_manager
        gproject.get_project_manager = lambda: Pm2104()

    def tearDown(self):
        gproject.get_project_manager = self._orig

    def test_attributes_come_back_keyed_by_project_name(self):
        out = gproject.get_project_attributes_in_current_folder()
        self.assertIn("Zenith_Online", out["projects"])
        self.assertEqual(out["projects"]["Zenith_Online"]["liveCollaborationMode"],
                         "multi_user")

    def test_pre_2104_build_is_version_guarded(self):
        gproject.get_project_manager = lambda: LegacyPm()
        out = gproject.get_project_attributes_in_current_folder()
        self.assertIn("error", out)
        self.assertIn("21.0.4", str(out))


# ── media_pool_item get_clip_timeline ────────────────────────────────────────


class GranularGetClipTimelineTest(unittest.TestCase):
    def setUp(self):
        self.clip = Clip2104(timeline=TimelineObj())
        self._orig_get_mp = gmpi._get_mp
        self._orig_find = gmpi._find_clip_by_id
        gmpi._get_mp = lambda: (None, MediaPoolStub(), None)
        gmpi._find_clip_by_id = lambda root, cid: self.clip

    def tearDown(self):
        gmpi._get_mp = self._orig_get_mp
        gmpi._find_clip_by_id = self._orig_find

    def test_timeline_entry_returns_a_summary(self):
        out = gmpi.get_clip_timeline("c1")
        self.assertTrue(out["is_timeline"])
        self.assertEqual(out["timeline"], {"name": "SEQ_01", "unique_id": "tl-1",
                                           "start_frame": 86400, "end_frame": 87000})

    def test_ordinary_clip_is_not_a_timeline(self):
        self.clip = Clip2104(timeline=None)
        out = gmpi.get_clip_timeline("c1")
        self.assertFalse(out["is_timeline"])
        self.assertNotIn("error", out)

    def test_pre_2104_build_is_version_guarded(self):
        self.clip = LegacyClip()
        out = gmpi.get_clip_timeline("L1")
        self.assertIn("error", out)
        self.assertIn("21.0.4", str(out))

    def test_a_raising_gettimeline_is_reported_not_propagated(self):
        class Raises(Clip2104):
            def GetTimeline(self):
                raise RuntimeError("boom")

        self.clip = Raises()
        out = gmpi.get_clip_timeline("c1")
        self.assertIn("error", out)
        self.assertIn("boom", str(out))


# ── timeline get_selected_timeline_items ─────────────────────────────────────


class GranularSelectedItemsTest(unittest.TestCase):
    def setUp(self):
        self._orig = gtimeline._get_timeline
        gtimeline._get_timeline = lambda: (None, SelectionTimeline2104(), None)

    def tearDown(self):
        gtimeline._get_timeline = self._orig

    def test_selected_items_are_summarized(self):
        out = gtimeline.get_selected_timeline_items()
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["items"][0], {"name": "shot_010.mov", "unique_id": "ti-1",
                                           "start": 86400, "end": 86448})

    def test_empty_selection_is_an_answer(self):
        class NothingSelected:
            def GetSelectedClips(self):
                return []

        gtimeline._get_timeline = lambda: (None, NothingSelected(), None)
        out = gtimeline.get_selected_timeline_items()
        self.assertEqual(out, {"count": 0, "items": []})

    def test_pre_2104_build_is_version_guarded(self):
        gtimeline._get_timeline = lambda: (None, LegacyTimeline(), None)
        out = gtimeline.get_selected_timeline_items()
        self.assertIn("error", out)
        self.assertIn("21.0.4", str(out))


if __name__ == "__main__":
    unittest.main()
