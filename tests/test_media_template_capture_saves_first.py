"""capture_media_template must SAVE the current project before it switches away.

Measured 2026-09-01 (E108, Studio 19.1.3.7): ProjectManager.CreateProject
replaces the current project, and a current project that was never saved is
simply gone afterwards — the capture's restore could not LoadProject the name
and Resolve fell back to a transient "Untitled Project". A freshly created
scratch project with two imported timelines vanished this way.
"""
import os
import unittest

import src.server as server


class _FakeProject:
    def __init__(self, name):
        self._name = name

    def GetName(self):
        return self._name


class _FakePM:
    def __init__(self, save_ok=True):
        self.calls = []
        self.save_ok = save_ok

    def GetCurrentProject(self):
        return _FakeProject("_mcp_unsaved")

    def SaveProject(self):
        self.calls.append("SaveProject")
        return self.save_ok

    def CreateProject(self, name):
        self.calls.append(("CreateProject", name))
        return None  # stop the capture right after the switch attempt


class CaptureSavesFirst(unittest.TestCase):
    def test_saves_the_current_project_before_creating_the_scratch(self):
        pm = _FakePM(save_ok=True)
        res = server._capture_media_template(None, pm, {"media_path": os.path.abspath(__file__)})
        self.assertEqual(pm.calls[0], "SaveProject", pm.calls)
        self.assertEqual(pm.calls[1][0], "CreateProject", pm.calls)
        self.assertTrue(pm.calls[1][1].startswith("_mcp_media_tpl_"))
        # The fake scratch creation fails by design — the capture reports that, not a lost project.
        self.assertIn("scratch project", str(res.get("error", res)))

    def test_refuses_when_the_current_project_cannot_be_saved(self):
        pm = _FakePM(save_ok=False)
        res = server._capture_media_template(None, pm, {"media_path": os.path.abspath(__file__)})
        self.assertEqual(pm.calls, ["SaveProject"], "must not create the scratch when the save failed")
        msg = str(res.get("error", res))
        self.assertIn("_mcp_unsaved", msg)
        self.assertIn("save", msg.lower())


if __name__ == "__main__":
    unittest.main()
