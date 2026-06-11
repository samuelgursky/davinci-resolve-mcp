"""Wiring tests for the live server adapters: clip_where, lint, and the
declarative spec executor. Uses an in-memory fake Resolve so no live app is
needed. The pure cores are covered separately (test_project_spec / _lint /
_clip_query / _structural_diff); these exercise the server.py glue."""
import unittest

from src import server


# ── Fakes ────────────────────────────────────────────────────────────────────
class FakeMPI:
    def __init__(self, uid):
        self._uid = uid

    def GetUniqueId(self):
        return self._uid

    def GetName(self):
        return f"media_{self._uid}"


class FakeItem:
    def __init__(self, start, end, name, mpi):
        self._start, self._end, self._name = start, end, name
        self._mpi = FakeMPI(mpi)

    def GetStart(self):
        return self._start

    def GetEnd(self):
        return self._end

    def GetDuration(self):
        return self._end - self._start

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return f"item_{self._name}"

    def GetMediaPoolItem(self):
        return self._mpi


class FakeTimeline:
    def __init__(self, name, tracks=None, settings=None, markers=None):
        self.name = name
        self._tracks = tracks or {}          # {("video",1): [FakeItem,...]}
        self._settings = settings or {}
        self._markers = markers or {}        # {frame: {color,...}}

    def GetName(self):
        return self.name

    def GetTrackCount(self, tt):
        return max([idx for (t, idx) in self._tracks if t == tt] + [0])

    def GetItemListInTrack(self, tt, idx):
        return self._tracks.get((tt, idx), [])

    def GetSetting(self, key):
        return self._settings.get(key)

    def SetSetting(self, key, value):
        self._settings[key] = value
        return True

    def GetMarkers(self):
        return dict(self._markers)

    def AddMarker(self, frame, color, name, note, duration, custom):
        self._markers[frame] = {"color": color, "name": name, "note": note,
                                "duration": duration, "customData": custom}
        return True

    def GetStartFrame(self):
        return 0

    def GetEndFrame(self):
        return 100

    def GetUniqueId(self):
        return f"tl_{self.name}"

    def GetStartTimecode(self):
        return "01:00:00:00"


class FakeFolder:
    def __init__(self, name):
        self.name = name
        self.subfolders = []

    def GetName(self):
        return self.name

    def GetSubFolderList(self):
        return list(self.subfolders)


class FakeMediaPool:
    def __init__(self, project):
        self._project = project
        self._root = FakeFolder("Master")

    def CreateEmptyTimeline(self, name):
        tl = FakeTimeline(name)
        self._project._timelines.append(tl)
        return tl

    def GetRootFolder(self):
        return self._root

    def AddSubFolder(self, parent, name):
        folder = FakeFolder(name)
        parent.subfolders.append(folder)
        return folder


class FakeProject:
    def __init__(self, name, timelines=None, settings=None):
        self.name = name
        self._timelines = timelines or []
        self._settings = settings or {}
        self._current = self._timelines[0] if self._timelines else None
        self._mp = FakeMediaPool(self)

    def GetName(self):
        return self.name

    def GetCurrentTimeline(self):
        return self._current

    def GetTimelineCount(self):
        return len(self._timelines)

    def GetTimelineByIndex(self, i):
        return self._timelines[i - 1] if 1 <= i <= len(self._timelines) else None

    def GetSetting(self, key):
        return self._settings.get(key)

    def SetSetting(self, key, value):
        self._settings[key] = value
        return True

    def GetMediaPool(self):
        return self._mp

    def GetCurrentRenderFormatAndCodec(self):
        return {"format": "mov", "codec": "ProRes422"}


class FakePM:
    def __init__(self, project, projects=None):
        self._project = project
        self._projects = projects or ([project.GetName()] if project else [])

    def GetCurrentProject(self):
        return self._project

    def GetProjectListInCurrentFolder(self):
        return list(self._projects)

    def CreateProject(self, name):
        self._project = FakeProject(name)
        self._projects.append(name)
        return self._project

    def LoadProject(self, name):
        return self._project


class FakeResolve:
    def __init__(self, pm):
        self._pm = pm

    def GetProjectManager(self):
        return self._pm


# ── Tests ────────────────────────────────────────────────────────────────────
class ClipWhereWiringTest(unittest.TestCase):
    def _timeline(self):
        return FakeTimeline("Edit", tracks={
            ("video", 1): [
                FakeItem(0, 8, "INSERT_a", "mA"),
                FakeItem(8, 248, "wide_master", "mB"),
            ],
            ("audio", 1): [FakeItem(0, 500, "room_tone", "mC")],
        })

    def test_duration_filter(self):
        out = server._timeline_clip_where(self._timeline(), {"duration_lt": 12})
        self.assertTrue(out["success"])
        self.assertEqual(out["match_count"], 1)
        self.assertEqual(out["clips"][0]["name"], "INSERT_a")
        self.assertEqual(out["total_clips"], 3)

    def test_track_type_filter(self):
        out = server._timeline_clip_where(self._timeline(), {"track_type": "audio"})
        self.assertEqual([c["name"] for c in out["clips"]], ["room_tone"])

    def test_unknown_filter_rejected(self):
        out = server._timeline_clip_where(self._timeline(), {"bogus": 1})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["category"], "invalid_input")

    def test_analysis_filter_not_live(self):
        out = server._timeline_clip_where(self._timeline(), {"analyzed": True})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["category"], "unsupported")


class LintWiringTest(unittest.TestCase):
    def test_lint_clean_project(self):
        tl = FakeTimeline("Edit", tracks={("video", 1): [FakeItem(0, 10, "a", "m1")]},
                          settings={"timelineFrameRate": "24"})
        proj = FakeProject("Show", timelines=[tl], settings={"colorScienceMode": "acescct"})
        out = server._project_lint_live(FakeResolve(FakePM(proj)), FakePM(proj))
        self.assertTrue(out["success"])
        self.assertEqual(out["counts"]["error"], 0)

    def test_lint_no_project(self):
        pm = FakePM(None, projects=[])
        out = server._project_lint_live(FakeResolve(pm), pm)
        codes = {i["code"] for i in out["issues"]}
        self.assertIn("no_project", codes)

    def test_lint_empty_timeline_warns(self):
        tl = FakeTimeline("Edit", tracks={}, settings={"timelineFrameRate": "24"})
        proj = FakeProject("Show", timelines=[tl])
        pm = FakePM(proj)
        out = server._project_lint_live(FakeResolve(pm), pm)
        self.assertIn("empty_timeline", {i["code"] for i in out["issues"]})

    def test_lint_audio_only_timeline_is_not_empty(self):
        tl = FakeTimeline("Music", tracks={
            ("audio", 1): [FakeItem(0, 240, "music_master", "m1")],
        }, settings={"timelineFrameRate": "24"})
        proj = FakeProject("Show", timelines=[tl])
        pm = FakePM(proj)
        out = server._project_lint_live(FakeResolve(pm), pm)
        self.assertNotIn("empty_timeline", {i["code"] for i in out["issues"]})


class SpecActionWiringTest(unittest.TestCase):
    def test_diff_to_spec_inline(self):
        proj = FakeProject("Show", timelines=[], settings={})
        pm = FakePM(proj)
        out = server._spec_action(FakeResolve(pm), pm, "diff_to_spec", {
            "spec": {"project": "Show", "settings": {"timelineFrameRate": "24"}},
        })
        self.assertTrue(out["success"])
        self.assertIn("actions", out)
        self.assertGreaterEqual(out["change_count"], 1)  # fps setting differs

    def test_apply_spec_creates_timeline_and_marker(self):
        proj = FakeProject("Show", timelines=[], settings={})
        pm = FakePM(proj)
        out = server._spec_action(FakeResolve(pm), pm, "apply_spec", {
            "spec": {
                "project": "Show",
                "timelines": [{"name": "Edit_v2", "fps": 24,
                               "markers": [{"frame": 0, "color": "Blue", "name": "HEAD"}]}],
            },
        })
        self.assertTrue(out["success"], out)
        names = [tl.GetName() for tl in proj._timelines]
        self.assertIn("Edit_v2", names)
        new_tl = next(tl for tl in proj._timelines if tl.GetName() == "Edit_v2")
        self.assertIn(0, new_tl.GetMarkers())

    def test_apply_spec_creates_media_pool_bins(self):
        proj = FakeProject("Show", timelines=[], settings={})
        pm = FakePM(proj)
        spec = {"project": "Show", "bins": ["Master/Media/Scene_01"]}

        out = server._spec_action(FakeResolve(pm), pm, "apply_spec", {"spec": spec})

        self.assertTrue(out["success"], out)
        plan = server._spec_action(FakeResolve(pm), pm, "diff_to_spec", {"spec": spec})
        self.assertEqual(plan["change_count"], 0, plan["actions"])

    def test_apply_spec_idempotent_second_run(self):
        proj = FakeProject("Show", timelines=[], settings={})
        pm = FakePM(proj)
        spec = {"project": "Show",
                "timelines": [{"name": "E", "fps": 24, "markers": [{"frame": 0}]}]}
        server._spec_action(FakeResolve(pm), pm, "apply_spec", {"spec": spec})
        # Second run: plan should be all-noop.
        plan = server._spec_action(FakeResolve(pm), pm, "diff_to_spec", {"spec": spec})
        self.assertEqual(plan["change_count"], 0, plan["actions"])

    def test_bad_spec_returns_invalid_input(self):
        proj = FakeProject("Show")
        pm = FakePM(proj)
        out = server._spec_action(FakeResolve(pm), pm, "apply_spec", {"spec": {"no_project": 1}})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["category"], "invalid_input")

    def test_missing_spec_arg(self):
        proj = FakeProject("Show")
        pm = FakePM(proj)
        out = server._spec_action(FakeResolve(pm), pm, "apply_spec", {})
        self.assertEqual(out["error"]["code"], "NO_SPEC")


if __name__ == "__main__":
    unittest.main()
