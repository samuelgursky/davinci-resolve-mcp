"""Contract tests for the remaining Resolve 21.0.4 README surfaces.

The 24 Jul 2026 README refresh (shipped with 21.0.4) documented ten methods
beyond the three wired for issue #131:

  - Resolve.GetLayoutPresetList                    -> layout_presets list
  - Resolve.GetBurnInPresetList / DeleteBurnInPreset -> render_presets
    list_burnin / delete_burnin
  - the six user-preferences-preset methods        -> resolve_control
    *_user_preferences_preset actions
  - ProjectManager.GetProjectAttributesInCurrentFolder -> project_manager
    list_attributes

The 21.0.4 methods are unavailable on the 19.1.3 baseline this suite runs
against, so every case here is a stub contract, not a live result.
"""
import unittest

import src.server as compound


# ── Stubs ────────────────────────────────────────────────────────────────────


class Resolve2104:
    """A Resolve handle from a 21.0.4+ build: all ten preset surfaces exist."""

    def __init__(self):
        self.layout_presets = ["Edit Layout", "Grade Layout"]
        self.burnin_presets = ["Dailies TC"]
        self.prefs_presets = ["Laptop"]
        self.calls = []

    def GetLayoutPresetList(self):
        return list(self.layout_presets)

    def GetBurnInPresetList(self):
        return list(self.burnin_presets)

    def DeleteBurnInPreset(self, name):
        self.calls.append(("DeleteBurnInPreset", name))
        return name in self.burnin_presets

    def GetUserPreferencesPresetList(self):
        return list(self.prefs_presets)

    def SaveUserPreferencesPreset(self, name):
        self.calls.append(("SaveUserPreferencesPreset", name))
        return True

    def LoadUserPreferencesPreset(self, name):
        self.calls.append(("LoadUserPreferencesPreset", name))
        return name in self.prefs_presets

    def DeleteUserPreferencesPreset(self, name):
        self.calls.append(("DeleteUserPreferencesPreset", name))
        return name in self.prefs_presets

    def ImportUserPreferencesPreset(self, path, name=None):
        self.calls.append(("ImportUserPreferencesPreset", path, name))
        return True

    def ExportUserPreferencesPreset(self, name, path):
        self.calls.append(("ExportUserPreferencesPreset", name, path))
        return name in self.prefs_presets


class LegacyResolve:
    """A pre-21.0.4 build — none of the new preset surfaces exist."""


class ProjectManager2104:
    def __init__(self, attributes):
        self._attributes = attributes

    def GetProjectAttributesInCurrentFolder(self):
        return dict(self._attributes)


class LegacyProjectManager:
    """A pre-21.0.4 ProjectManager — no per-project attributes call."""


class ResolveWithPm:
    def __init__(self, pm):
        self._pm = pm

    def GetProjectManager(self):
        return self._pm


ATTRS = {
    "Zenith_Online": {
        "lastModifiedDate": "2026-08-05T22:30:00-04:00",
        "creationDate": "2026-07-01T09:00:00-04:00",
        "notes": "",
        "liveCollaborationMode": "multi_user",
    }
}


class _ResolveStubTest(unittest.TestCase):
    """Common get_resolve stubbing."""

    resolve_factory = Resolve2104

    def setUp(self):
        self.resolve = self.resolve_factory()
        self._orig = compound.get_resolve
        compound.get_resolve = lambda: self.resolve

    def tearDown(self):
        compound.get_resolve = self._orig


# ── layout_presets list ──────────────────────────────────────────────────────


class LayoutPresetListTest(_ResolveStubTest):
    def test_list_returns_the_saved_preset_names(self):
        out = compound.layout_presets("list", {})
        self.assertEqual(out["presets"], ["Edit Layout", "Grade Layout"])

    def test_pre_2104_build_is_version_guarded(self):
        compound.get_resolve = lambda: LegacyResolve()
        out = compound.layout_presets("list", {})
        self.assertIn("error", out)
        self.assertIn("21.0.4", str(out))

    def test_list_is_a_known_action(self):
        out = compound.layout_presets("no_such_action", {})
        self.assertIn("list", str(out))


# ── render_presets list_burnin / delete_burnin ───────────────────────────────


class BurnInPresetTest(_ResolveStubTest):
    def test_list_burnin_returns_the_preset_names(self):
        out = compound.render_presets("list_burnin", {})
        self.assertEqual(out["presets"], ["Dailies TC"])

    def test_delete_burnin_deletes_by_name(self):
        out = compound.render_presets("delete_burnin", {"name": "Dailies TC"})
        self.assertTrue(out["success"])
        self.assertIn(("DeleteBurnInPreset", "Dailies TC"), self.resolve.calls)

    def test_delete_burnin_requires_a_name(self):
        out = compound.render_presets("delete_burnin", {})
        self.assertIn("error", out)
        self.assertNotIn(("DeleteBurnInPreset", None), self.resolve.calls)

    def test_pre_2104_build_is_version_guarded(self):
        compound.get_resolve = lambda: LegacyResolve()
        for action in ("list_burnin", "delete_burnin"):
            out = compound.render_presets(action, {"name": "x"})
            self.assertIn("error", out)
            self.assertIn("21.0.4", str(out))

    def test_new_actions_are_listed_as_known(self):
        out = compound.render_presets("no_such_action", {})
        self.assertIn("list_burnin", str(out))
        self.assertIn("delete_burnin", str(out))


# ── resolve_control user preferences presets ─────────────────────────────────


class UserPreferencesPresetTest(_ResolveStubTest):
    def test_list_returns_the_preset_names(self):
        out = compound.resolve_control("list_user_preferences_presets", {})
        self.assertEqual(out["presets"], ["Laptop"])

    def test_save_load_delete_round_trip_by_name(self):
        self.assertTrue(
            compound.resolve_control("save_user_preferences_preset", {"name": "Laptop"})["success"])
        self.assertTrue(
            compound.resolve_control("load_user_preferences_preset", {"name": "Laptop"})["success"])
        self.assertTrue(
            compound.resolve_control("delete_user_preferences_preset", {"name": "Laptop"})["success"])
        self.assertEqual(
            [c[0] for c in self.resolve.calls],
            ["SaveUserPreferencesPreset", "LoadUserPreferencesPreset",
             "DeleteUserPreferencesPreset"])

    def test_name_is_required_for_the_named_actions(self):
        for action in ("save_user_preferences_preset", "load_user_preferences_preset",
                       "delete_user_preferences_preset"):
            out = compound.resolve_control(action, {})
            self.assertIn("error", out)
        self.assertEqual(self.resolve.calls, [])

    def test_import_without_a_name_uses_the_single_arg_form(self):
        out = compound.resolve_control("import_user_preferences_preset",
                                       {"path": "/tmp/prefs.zip"})
        self.assertTrue(out["success"])
        self.assertIn(("ImportUserPreferencesPreset", "/tmp/prefs.zip", None),
                      self.resolve.calls)

    def test_import_without_a_name_says_the_file_names_the_preset(self):
        # Round-tripped on Studio 21.0.4.5 (PR #139): the single-arg form
        # returns True and the preset comes back named after the file, so a
        # caller who passed no name is told what to look for.
        out = compound.resolve_control("import_user_preferences_preset",
                                       {"path": "/tmp/prefs.zip"})
        self.assertIn("takes its name from the file", out["note"])

    def test_import_with_a_name_does_not_claim_the_file_named_it(self):
        out = compound.resolve_control("import_user_preferences_preset",
                                       {"path": "/tmp/prefs.zip", "name": "Studio"})
        self.assertNotIn("takes its name from the file", out["note"])

    def test_import_notes_that_the_preset_is_not_auto_loaded(self):
        # The README is explicit that import does not activate the preset;
        # the answer carries that forward so a caller doesn't stop early.
        out = compound.resolve_control("import_user_preferences_preset",
                                       {"path": "/tmp/prefs.zip", "name": "Studio"})
        self.assertIn("not auto-loaded", out["note"])
        self.assertIn(("ImportUserPreferencesPreset", "/tmp/prefs.zip", "Studio"),
                      self.resolve.calls)

    def test_export_requires_name_and_path(self):
        out = compound.resolve_control("export_user_preferences_preset", {"name": "Laptop"})
        self.assertIn("error", out)
        out = compound.resolve_control("export_user_preferences_preset",
                                       {"name": "Laptop", "path": "/tmp/prefs.zip"})
        self.assertTrue(out["success"])

    def test_pre_2104_build_is_version_guarded(self):
        compound.get_resolve = lambda: LegacyResolve()
        out = compound.resolve_control("list_user_preferences_presets", {})
        self.assertIn("error", out)
        self.assertIn("21.0.4", str(out))

    def test_new_actions_are_listed_as_known(self):
        out = compound.resolve_control("no_such_action", {})
        self.assertIn("list_user_preferences_presets", str(out))
        self.assertIn("export_user_preferences_preset", str(out))


# ── project_manager list_attributes ──────────────────────────────────────────


class ListProjectAttributesTest(unittest.TestCase):
    def setUp(self):
        self._orig = compound.get_resolve
        compound.get_resolve = lambda: ResolveWithPm(ProjectManager2104(ATTRS))

    def tearDown(self):
        compound.get_resolve = self._orig

    def test_attributes_come_back_keyed_by_project_name(self):
        out = compound.project_manager("list_attributes", {})
        self.assertEqual(out["projects"], ATTRS)

    def test_pre_2104_build_is_version_guarded(self):
        compound.get_resolve = lambda: ResolveWithPm(LegacyProjectManager())
        out = compound.project_manager("list_attributes", {})
        self.assertIn("error", out)
        self.assertIn("21.0.4", str(out))

    def test_list_attributes_is_a_known_action(self):
        out = compound.project_manager("no_such_action", {})
        self.assertIn("list_attributes", str(out))


# ── capability advertisement ─────────────────────────────────────────────────


class CapabilityAdvertisementTest(unittest.TestCase):
    def test_project_capabilities_advertise_the_new_surfaces(self):
        caps = compound._project_capabilities(None, None, Resolve2104())["resolve"]

        self.assertTrue(caps["layout_presets"]["list"])
        self.assertTrue(caps["render_presets"]["list_burnin"])
        self.assertTrue(caps["render_presets"]["delete_burnin"])
        self.assertEqual(
            sorted(caps["user_preferences_presets"]),
            ["delete", "export", "import", "list", "load", "save"])
        self.assertTrue(all(caps["user_preferences_presets"].values()))

    def test_legacy_build_reports_the_new_surfaces_absent(self):
        caps = compound._project_capabilities(None, None, LegacyResolve())["resolve"]

        self.assertFalse(caps["layout_presets"]["list"])
        self.assertFalse(caps["render_presets"]["list_burnin"])
        self.assertFalse(caps["render_presets"]["delete_burnin"])
        self.assertFalse(any(caps["user_preferences_presets"].values()))


if __name__ == "__main__":
    unittest.main()
