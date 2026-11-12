"""probe_interchange_roundtrip puts back the timeline that was current (#364).

The probe exports the timeline, imports the file, compares, and deletes the
imported copy. Resolve makes an imported timeline current, and deleting it
leaves Resolve to pick another one, in practice the last in the list. Nothing
switched back, so a later call on "the current timeline" edited the wrong one,
and the bug was invisible whenever the starting timeline happened to be last.
"""

import unittest
from unittest import mock

import src.server as server


class _Timeline:
    def __init__(self, timeline_id):
        self.timeline_id = timeline_id

    def GetUniqueId(self):
        return self.timeline_id

    def GetName(self):
        return self.timeline_id


class _Project:
    """Import makes the new timeline current; deleting it falls back to the last."""

    def __init__(self, timelines, current, *, switch_works=True):
        self.timelines = list(timelines)
        self.current = current
        self.switch_works = switch_works
        self.switches = []

    def GetCurrentTimeline(self):
        return self.current

    def SetCurrentTimeline(self, timeline):
        self.switches.append(timeline)
        if self.switch_works:
            self.current = timeline
        return self.switch_works


class _MediaPool:
    def __init__(self, project):
        self.project = project

    def DeleteTimelines(self, timelines):
        for timeline in timelines:
            self.project.timelines.remove(timeline)
        if self.project.current in timelines:
            self.project.current = self.project.timelines[-1]
        return True


class ProbeRestoresCurrentTimelineTest(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.c = _Timeline("A"), _Timeline("B"), _Timeline("C")
        self.imported = _Timeline("A roundtrip")

    def _run(self, project, *, import_ok=True, params=None):
        pool = _MediaPool(project)

        def fake_import(proj, mp, p):
            if not import_ok:
                # A failed import can still have left a timeline current.
                proj.current = self.c
                return {"success": False, "error": "import refused"}
            proj.timelines.append(self.imported)
            proj.current = self.imported
            return {"success": True, "id": "A roundtrip"}

        patches = [
            mock.patch.object(server, "_render_temp_path_ok", return_value=True),
            mock.patch.object(server, "_timeline_export_spec",
                              return_value={"requested": "FCPXML", "extension": ".fcpxml"}),
            mock.patch.object(server, "_export_timeline_checked",
                              return_value={"success": True, "path": "/tmp/x.fcpxml"}),
            mock.patch.object(server, "_import_timeline_checked", side_effect=fake_import),
            mock.patch.object(server, "_timeline_by_selector",
                              side_effect=lambda proj, sel, prefix: (self.imported, None)),
            mock.patch.object(server, "_timeline_conform_snapshot", return_value={}),
            mock.patch.object(server, "_compare_timeline_snapshots", return_value={"match": True}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return server._probe_interchange_roundtrip(
            project, pool, self.a, {"format": "fcpxml", **(params or {})})

    def test_cleanup_restores_the_starting_timeline_when_it_is_not_last(self):
        project = _Project([self.a, self.b, self.c], current=self.a)

        out = self._run(project)

        self.assertTrue(out["success"])
        self.assertEqual(out["cleanup"], {"success": True})
        self.assertNotIn(self.imported, project.timelines)
        self.assertIs(project.current, self.a)
        self.assertEqual(out["current_timeline"], {"restored": True})

    def test_without_cleanup_the_imported_copy_does_not_stay_current(self):
        project = _Project([self.a, self.b, self.c], current=self.a)

        out = self._run(project, params={"cleanup_imported": False})

        self.assertIn(self.imported, project.timelines)
        self.assertIs(project.current, self.a)
        self.assertTrue(out["current_timeline"]["restored"])

    def test_a_failed_import_restores_it_too(self):
        project = _Project([self.a, self.b, self.c], current=self.a)

        out = self._run(project, import_ok=False)

        self.assertFalse(out["success"])
        self.assertEqual(out["stage"], "import")
        self.assertIs(project.current, self.a)
        self.assertTrue(out["current_timeline"]["restored"])

    def test_a_restore_that_does_not_take_is_reported(self):
        project = _Project([self.a, self.b, self.c], current=self.a, switch_works=False)

        out = self._run(project)

        self.assertTrue(out["success"])
        self.assertFalse(out["current_timeline"]["restored"])
        self.assertIn("'A'", out["current_timeline"]["error"])
        self.assertIn("'C'", out["current_timeline"]["error"])
        self.assertEqual(out["current_timeline"]["state"]["current_timeline_id"], "C")


if __name__ == "__main__":
    unittest.main()
