import tempfile
import unittest
from pathlib import Path

from src.server import (
    _database_capabilities,
    _project_boundary_report,
    _project_settings_snapshot,
    _safe_project_archive,
    _safe_project_create,
    _safe_project_delete,
    _safe_project_export,
    _safe_project_import,
    _safe_project_restore,
    _safe_set_current_database,
    _safe_set_project_settings,
)


class ProjectStub:
    def __init__(self):
        self.settings = {
            "timelineFrameRate": "24",
            "timelineResolutionWidth": "1920",
            "timelineResolutionHeight": "1080",
        }
        self.set_calls = []

    def GetName(self):
        return "_mcp_project_probe"

    def GetUniqueId(self):
        return "project-1"

    def GetSetting(self, key=""):
        if not key:
            return dict(self.settings)
        return self.settings.get(key)

    def SetSetting(self, key, value):
        self.set_calls.append((key, value))
        self.settings[key] = value
        return True

    def GetPresetList(self):
        return [{"Name": "Current Project", "Width": 1920, "Height": 1080}]

    def GetTimelineCount(self):
        return 0

    def GetCurrentTimeline(self):
        return None

    def GetRenderPresetList(self):
        return ["H.264 Master"]

    def GetQuickExportRenderPresets(self):
        return [{"Name": "H.264"}]

    def GetColorGroupsList(self):
        return []


class ProjectManagerStub:
    def __init__(self):
        self.project = ProjectStub()
        self.deleted = []
        self.created = []
        self.archived = []
        self.exported = []
        self.imported = []
        self.restored = []
        self.closed = False

    def ArchiveProject(self, name, path, src_media=False, render_cache=False, proxy_media=False):
        self.archived.append((name, path, src_media, render_cache, proxy_media))
        return True

    def CreateProject(self, name, media_location_path=None):
        self.created.append((name, media_location_path))
        self.project = ProjectStub()
        return self.project

    def DeleteProject(self, name):
        self.deleted.append(name)
        return True

    def LoadProject(self, name):
        return self.project

    def GetCurrentProject(self):
        return self.project

    def SaveProject(self):
        return True

    def CloseProject(self, project):
        self.closed = True
        self.project = None
        return True

    def GetProjectListInCurrentFolder(self):
        return ["_mcp_project_probe"]

    def GetFolderListInCurrentFolder(self):
        return ["Master"]

    def GetCurrentFolder(self):
        return "Master"

    def ExportProject(self, name, path, with_stills_and_luts=False):
        self.exported.append((name, path, with_stills_and_luts))
        Path(path).write_text("DRP", encoding="utf-8")
        return True

    def ImportProject(self, path, name=None):
        self.imported.append((path, name))
        return True

    def RestoreProject(self, path, name=None):
        self.restored.append((path, name))
        return True

    def GetCurrentDatabase(self):
        return {"DbType": "Disk", "DbName": "Local Database"}

    def GetDatabaseList(self):
        return [{"DbType": "Disk", "DbName": "Local Database"}]

    def SetCurrentDatabase(self, db_info):
        self.switched_to = db_info
        return True


class ResolveStub:
    def GetVersion(self):
        return [20, 3, 2, 9, ""]

    def GetFairlightPresets(self):
        return []

    def SaveLayoutPreset(self, name):
        return True

    def LoadLayoutPreset(self, name):
        return True

    def UpdateLayoutPreset(self, name):
        return True

    def ExportLayoutPreset(self, name, path):
        return True

    def ImportLayoutPreset(self, path, name=None):
        return True

    def DeleteLayoutPreset(self, name):
        return True

    def ImportRenderPreset(self, path):
        return True

    def ExportRenderPreset(self, name, path):
        return True

    def ImportBurnInPreset(self, path):
        return True

    def ExportBurnInPreset(self, name, path):
        return True


class ProjectLifecycleProbeTest(unittest.TestCase):
    def test_safe_project_create_requires_disposable_name(self):
        pm = ProjectManagerStub()
        result = _safe_project_create(pm, ResolveStub(), {"name": "Example Project"})

        self.assertIn("error", result)
        self.assertFalse(pm.created)

    def test_safe_project_create_dry_run(self):
        pm = ProjectManagerStub()
        result = _safe_project_create(pm, ResolveStub(), {"name": "_mcp_project_probe_new", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertTrue(result["would_create"])
        self.assertFalse(pm.created)

    def test_settings_snapshot_and_restore(self):
        project = ProjectStub()
        snapshot = _project_settings_snapshot(project, {})
        result = _safe_set_project_settings(project, {"settings": {"timelineFrameRate": "24"}, "restore": True})

        self.assertEqual(snapshot["settings"]["timelineFrameRate"], "24")
        self.assertTrue(result["success"])
        self.assertEqual(project.settings["timelineFrameRate"], "24")
        self.assertGreaterEqual(len(project.set_calls), 2)

    def test_archive_rejects_media_flags_without_opt_in(self):
        pm = ProjectManagerStub()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = _safe_project_archive(
                pm,
                {"name": "_mcp_project_probe", "path": str(Path(temp_dir) / "archive.dra"), "src_media": True},
            )

        self.assertIn("error", result)
        self.assertFalse(pm.archived)

    def test_export_import_restore_require_temp_and_disposable_names(self):
        pm = ProjectManagerStub()
        with tempfile.TemporaryDirectory() as temp_dir:
            drp = Path(temp_dir) / "probe.drp"
            export_result = _safe_project_export(pm, {"name": "_mcp_project_probe", "path": str(drp)})
            import_result = _safe_project_import(pm, {"name": "_mcp_project_imported", "path": str(drp)})
            restore_result = _safe_project_restore(pm, {"name": "_mcp_project_restored", "path": str(drp)})

        self.assertTrue(export_result["success"])
        self.assertTrue(import_result["success"])
        self.assertTrue(restore_result["success"])

    def test_delete_current_project_requires_close_current(self):
        pm = ProjectManagerStub()
        result = _safe_project_delete(pm, {"name": "_mcp_project_probe"})

        self.assertIn("error", result)
        self.assertFalse(pm.deleted)

    def test_delete_current_project_with_close_current(self):
        pm = ProjectManagerStub()
        result = _safe_project_delete(pm, {"name": "_mcp_project_probe", "close_current": True})

        self.assertTrue(result["success"])
        self.assertTrue(pm.closed)
        self.assertEqual(pm.deleted, ["_mcp_project_probe"])

    def test_database_switch_is_dry_run_by_default(self):
        pm = ProjectManagerStub()
        result = _safe_set_current_database(pm, {"db_info": {"DbType": "Disk", "DbName": "Other"}})

        self.assertTrue(result["success"])
        self.assertTrue(result["would_switch"])
        self.assertFalse(hasattr(pm, "switched_to"))

    def test_boundary_report_includes_database_and_presets(self):
        pm = ProjectManagerStub()
        report = _project_boundary_report(ResolveStub(), pm, pm.project, {})
        database = _database_capabilities(pm)

        self.assertIn("database", report)
        self.assertEqual(database["current"]["DbName"], "Local Database")
        self.assertIn("project_presets", report["presets"])


if __name__ == "__main__":
    unittest.main()
