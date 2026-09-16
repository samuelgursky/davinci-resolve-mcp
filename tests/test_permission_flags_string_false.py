"""A string "false" must not grant a permission the caller spelled out refusing.

Six opt-in flags gate something destructive, and every one of them defaults to
off: allow_media_archive, close_current, allow_generate, allow_render,
allow_switch and acknowledge_trap. They were read with bare truthiness, so
allow_render="false" -- the spelling a client that stringifies its JSON scalars
sends -- is truthy and the permission is granted. These open in the opposite
direction from overwrite="false" (#239, v4.7.2) and ripple="false" (84a8a49,
v4.6.4): there a string "false" performed a destructive act the caller had asked
to be refused; here it hands over a permission the caller declined to give.

Every case below sends a false spelling and checks two things: the call is
refused, and the destructive effect did not happen -- no archive written, no
project closed or deleted, no subtitle pass, no render, no database switch, no
grade-destroying handler entered.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# Stub the Resolve module so server.py imports without Resolve installed.
sys.modules.setdefault('DaVinciResolveScript', type(sys)('DaVinciResolveScript'))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.server import (  # noqa: E402
    _safe_project_archive,
    _safe_project_delete,
    _safe_quick_export,
    _safe_set_current_database,
    _subtitle_generation_probe,
    project_manager,
)
from src.utils import destructive_hook as dh  # noqa: E402

FALSE_SPELLINGS = ("false", "False", "FALSE", "no", "off", "0")

DISPOSABLE = "_mcp_project_probe"


class ProjectStub:
    def GetName(self):
        return DISPOSABLE

    def GetUniqueId(self):
        return "project-1"


class ProjectManagerStub:
    """Records the calls that must not happen while a guard holds."""

    def __init__(self):
        self.project = ProjectStub()
        self.archived = []
        self.deleted = []
        self.switched_to = []
        self.closed = False

    def GetCurrentProject(self):
        return self.project

    def ArchiveProject(self, name, path, src_media=False, render_cache=False, proxy_media=False):
        self.archived.append((name, path, src_media, render_cache, proxy_media))
        return True

    def DeleteProject(self, name):
        self.deleted.append(name)
        return True

    def SaveProject(self):
        return True

    def CloseProject(self, project):
        self.closed = True
        self.project = None
        return True

    def GetCurrentDatabase(self):
        return {"DbType": "Disk", "DbName": "Local Database"}

    def GetDatabaseList(self):
        return [{"DbType": "Disk", "DbName": "Local Database"}]

    def SetCurrentDatabase(self, db_info):
        self.switched_to.append(db_info)
        return True


class ResolveStub:
    def __init__(self, pm):
        self._pm = pm

    def GetProjectManager(self):
        return self._pm

    def GetVersion(self):
        return [21, 1, 0, 14, ""]


class ArchiveFlagTests(unittest.TestCase):
    """project_manager archive: two opt-ins, and two flags crash Resolve 21.1.0.14."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "probe.dra")

    def test_allow_media_archive_string_false_does_not_unlock_the_media_flags(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                pm = ProjectManagerStub()
                out = _safe_project_archive(pm, {
                    "name": DISPOSABLE,
                    "path": self.path,
                    "src_media": True,
                    "allow_media_archive": spelling,
                    # True, so allow_media_archive is the only guard under test.
                    "acknowledge_trap": True,
                })

                self.assertEqual(pm.archived, [], "ArchiveProject ran with source media on")
                self.assertFalse(os.path.exists(self.path))
                self.assertIn("error", out)

    def test_acknowledge_trap_string_false_does_not_unlock_the_crashing_flags(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                pm = ProjectManagerStub()
                out = _safe_project_archive(pm, {
                    "name": DISPOSABLE,
                    "path": self.path,
                    "src_media": True,
                    "allow_media_archive": True,
                    "acknowledge_trap": spelling,
                })

                self.assertEqual(pm.archived, [], "ArchiveProject ran on a crashing flag")
                self.assertFalse(out.get("success"))
                self.assertEqual(out.get("retry_with"), {"acknowledge_trap": True})

    def test_raw_archive_action_acknowledge_trap_string_false_is_refused(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                pm = ProjectManagerStub()
                with patch("src.server.get_resolve", return_value=ResolveStub(pm)):
                    out = project_manager("archive", {
                        "name": DISPOSABLE,
                        "path": self.path,
                        "proxy_media": True,
                        "acknowledge_trap": spelling,
                    })

                self.assertEqual(pm.archived, [], "ArchiveProject ran on a crashing flag")
                self.assertFalse(out.get("success"))


class CloseCurrentTests(unittest.TestCase):
    """Deleting the project someone has open is the call that loses their work."""

    def test_safe_project_delete_string_false_keeps_the_open_project(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                pm = ProjectManagerStub()
                out = _safe_project_delete(pm, {"name": DISPOSABLE, "close_current": spelling})

                self.assertFalse(pm.closed, "the open project was closed")
                self.assertEqual(pm.deleted, [], "the open project was deleted")
                self.assertIn("error", out)

    def test_raw_delete_action_string_false_keeps_the_open_project(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                pm = ProjectManagerStub()
                with patch("src.server.get_resolve", return_value=ResolveStub(pm)):
                    out = project_manager("delete", {"name": DISPOSABLE, "close_current": spelling})

                self.assertEqual(pm.deleted, [], "the open project was deleted")
                self.assertFalse(out.get("success"))


class TimelineStub:
    def __init__(self):
        self.subtitle_calls = []

    def CreateSubtitlesFromAudio(self, settings=None):
        self.subtitle_calls.append(settings)
        return True


class AllowGenerateTests(unittest.TestCase):
    def test_string_false_does_not_call_create_subtitles_from_audio(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                timeline = TimelineStub()
                out = _subtitle_generation_probe(
                    timeline, {"settings": {"language": "en"}, "allow_generate": spelling})

                self.assertEqual(timeline.subtitle_calls, [],
                                 "CreateSubtitlesFromAudio ran without permission")
                self.assertTrue(out["success"])
                self.assertTrue(out["would_generate"])


class RenderProjectStub:
    def __init__(self):
        self.quick_export_calls = []

    def GetQuickExportRenderPresets(self):
        return ["H.264 Master"]

    def RenderWithQuickExport(self, preset, params):
        self.quick_export_calls.append({"preset": preset, "params": params})
        return {"Status": "Queued"}


class AllowRenderTests(unittest.TestCase):
    def test_string_false_does_not_start_a_quick_export(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                project = RenderProjectStub()
                out = _safe_quick_export(project, {
                    "preset": "H.264 Master",
                    "target_dir": tempfile.gettempdir(),
                    "custom_name": "quick_export_probe",
                    "allow_render": spelling,
                })

                self.assertEqual(project.quick_export_calls, [],
                                 "RenderWithQuickExport ran without permission")
                self.assertTrue(out["success"])
                self.assertFalse(out["would_render"])


class AllowSwitchTests(unittest.TestCase):
    """SetCurrentDatabase closes whatever project is open, unsaved work included."""

    def test_string_false_does_not_switch_the_database(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                pm = ProjectManagerStub()
                out = _safe_set_current_database(pm, {
                    "db_info": {"DbType": "Disk", "DbName": "Other"},
                    "dry_run": False,
                    "allow_switch": spelling,
                })

                self.assertEqual(pm.switched_to, [], "SetCurrentDatabase ran without permission")
                self.assertTrue(out["success"])
                self.assertTrue(out["would_switch"])


class TrapGuardTests(unittest.TestCase):
    """The trap guard refuses actions whose verified behaviour destroys work."""

    @staticmethod
    def _tool():
        calls = []

        @dh.destructive_op("timeline_item_color")
        def timeline_item_color(action, params=None, *a, **k):
            calls.append(action)
            return {"success": True}

        return timeline_item_color, calls

    def test_string_false_does_not_stand_the_guard_down(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                tool, calls = self._tool()
                out = tool("copy_grades", {"acknowledge_trap": spelling})

                self.assertEqual(calls, [], "the grade-destroying handler ran")
                self.assertFalse(out["success"])
                self.assertEqual(out["retry_with"], {"acknowledge_trap": True})


if __name__ == "__main__":
    unittest.main()
