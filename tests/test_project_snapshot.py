"""Tests for project_manager snapshot — the one read-only readout before planning."""
import json
import unittest
from unittest import mock

import src.server as s

from tests.test_timeline_conform_probe import (
    MediaPoolItemStub,
    TimelineItemStub,
    TimelineStub,
)
from tests.test_tool_exposure import FakeClip, FakeFolder, FakeMP


class SnapshotTimeline(TimelineStub):
    def GetSetting(self, key):
        return "24" if key == "timelineFrameRate" else ""


class SnapshotProject:
    """Read-only by construction: it has no setters, so a snapshot that tried to
    switch timeline, page or folder would raise AttributeError."""

    def __init__(self, timeline, jobs=None, rendering=False):
        self._timeline = timeline
        self._jobs = jobs or []
        self._rendering = rendering

    def GetName(self):
        return "proj"

    def GetUniqueId(self):
        return "proj-1"

    def GetTimelineCount(self):
        return 2

    def GetSetting(self, key):
        return {
            "timelineFrameRate": "24",
            "timelineResolutionWidth": "3840",
            "timelineResolutionHeight": "2160",
        }.get(key, "")

    def GetCurrentTimeline(self):
        return self._timeline

    def GetMediaPool(self):
        return FakeMP(FakeFolder(
            [FakeClip("a", "Video", "1")],
            subs=[FakeFolder([FakeClip("b", "Audio", "2")])],
        ))

    def GetRenderJobList(self):
        return list(self._jobs)

    def GetRenderJobStatus(self, job_id):
        return {"JobStatus": "Complete", "CompletionPercentage": 100}

    def IsRenderingInProgress(self):
        return self._rendering


def _timeline():
    media = MediaPoolItemStub("A.mov", "mpi-a", __file__)
    return SnapshotTimeline({
        "video": {
            1: [
                TimelineItemStub("A", "a1", 0, 10, 100, "video", 1, media),
                TimelineItemStub("B", "b1", 15, 25, 200, "video", 1, media),
            ],
            2: [TimelineItemStub("C", "c1", 5, 18, 300, "video", 2, media)],
        },
        "audio": {1: [TimelineItemStub("A.wav", "a2", 0, 10, 100, "audio", 1, media)]},
    })


class ProjectSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.resolve = mock.Mock()
        self.resolve.GetCurrentPage.return_value = "edit"
        patcher = mock.patch.object(s, "get_resolve", return_value=self.resolve)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _snapshot(self, proj, params=None):
        return s._project_state_snapshot(self.resolve, proj, params or {})

    def test_full_snapshot(self):
        proj = SnapshotProject(_timeline(), jobs=[{"JobId": "job-1", "TimelineName": "Conform Stub"}])
        out = self._snapshot(proj)
        self.assertEqual(sorted(out), sorted(s._SNAPSHOT_SECTIONS))
        self.assertEqual(out["project"], {
            "name": "proj",
            "id": "proj-1",
            "current_page": "edit",
            "timeline_count": 2,
            "settings": {
                "timelineFrameRate": "24",
                "timelineResolutionWidth": "3840",
                "timelineResolutionHeight": "2160",
            },
        })
        timeline = out["timeline"]
        self.assertEqual(timeline["id"], "timeline-1")
        self.assertEqual(timeline["start_frame"], 86400)
        self.assertEqual(timeline["fps"], 24.0)
        self.assertEqual(timeline["item_count"], 4)
        self.assertEqual(timeline["items_returned"], 4)
        self.assertFalse(timeline["items_truncated"])
        self.assertNotIn("markers", timeline)
        self.assertEqual(timeline["tracks"]["video"]["track_count"], 2)
        first = timeline["tracks"]["video"]["tracks"][0]["items"][0]
        self.assertEqual(tuple(first), s._SNAPSHOT_ITEM_FIELDS)
        self.assertEqual(first["timeline_item_id"], "a1")
        self.assertEqual(first["media_pool_item_id"], "mpi-a")
        self.assertEqual((first["start"], first["end"]), (0, 10))
        self.assertEqual(first["source_start"], 100)
        self.assertEqual(out["gaps_overlaps"]["gap_count"], 1)
        self.assertEqual(out["gaps_overlaps"]["gaps"][0]["start"], 10)
        self.assertEqual(out["render"], {
            "is_rendering": False,
            "jobs": [{
                "JobId": "job-1",
                "TimelineName": "Conform Stub",
                "status": {"JobStatus": "Complete", "CompletionPercentage": 100},
            }],
        })
        self.assertEqual(out["media_pool"], {
            "folder_count": 2, "clip_count": 2, "by_type": {"Video": 1, "Audio": 1},
        })
        json.dumps(out)

    def test_snapshot_matches_the_actions_it_replaces(self):
        tl = _timeline()
        out = self._snapshot(SnapshotProject(tl))
        probe = s._timeline_conform_snapshot(tl, {})
        self.assertEqual(out["gaps_overlaps"], s._detect_gaps_overlaps_from_snapshot(probe, {}))
        probe_item = probe["tracks"]["video"]["tracks"][0]["items"][1]
        snap_item = out["timeline"]["tracks"]["video"]["tracks"][0]["items"][1]
        for field in s._SNAPSHOT_ITEM_FIELDS:
            self.assertEqual(snap_item[field], probe_item[field], field)

    def test_include_filters_sections(self):
        proj = SnapshotProject(_timeline())
        proj.GetMediaPool = mock.Mock(side_effect=AssertionError("media pool walked"))
        out = self._snapshot(proj, {"include": ["project", "render"]})
        self.assertEqual(sorted(out), ["project", "render"])

    def test_unknown_section_is_refused(self):
        out = self._snapshot(SnapshotProject(_timeline()), {"include": ["timeline", "markers"]})
        self.assertEqual(out["error"]["code"], "UNKNOWN_SECTION")
        self.assertEqual(out["error"]["state"]["unknown"], ["markers"])

    def test_track_types_bounds_timeline_and_gaps(self):
        out = self._snapshot(SnapshotProject(_timeline()), {"track_types": ["audio"]})
        self.assertEqual(list(out["timeline"]["tracks"]), ["audio"])
        self.assertEqual(out["timeline"]["item_count"], 1)
        self.assertEqual(out["gaps_overlaps"]["gap_count"], 0)

    def test_failing_section_does_not_fail_the_call(self):
        proj = SnapshotProject(_timeline())
        proj.GetRenderJobList = mock.Mock(side_effect=RuntimeError("render queue unreadable"))
        out = self._snapshot(proj)
        self.assertEqual(out["render"], {"error": "render queue unreadable"})
        self.assertEqual(out["project"]["name"], "proj")
        self.assertEqual(out["timeline"]["item_count"], 4)
        self.assertEqual(out["media_pool"]["clip_count"], 2)

    def test_failing_timeline_read_is_reported_in_both_timeline_sections(self):
        tl = _timeline()
        tl.GetItemListInTrack = mock.Mock(side_effect=RuntimeError("track read failed"))
        out = self._snapshot(SnapshotProject(tl))
        self.assertEqual(out["timeline"], {"error": "track read failed"})
        self.assertEqual(out["gaps_overlaps"], {"error": "track read failed"})
        self.assertIn("jobs", out["render"])

    def test_no_current_timeline(self):
        out = self._snapshot(SnapshotProject(None))
        expected = {"available": False, "error": "No current timeline"}
        self.assertEqual(out["timeline"], expected)
        self.assertEqual(out["gaps_overlaps"], expected)
        self.assertEqual(out["project"]["timeline_count"], 2)
        self.assertIn("jobs", out["render"])

    def test_item_limit_truncates_items_but_not_counts_or_gaps(self):
        out = self._snapshot(SnapshotProject(_timeline()), {"item_limit": 1})
        timeline = out["timeline"]
        self.assertTrue(timeline["items_truncated"])
        self.assertEqual(timeline["items_returned"], 1)
        self.assertEqual(timeline["item_count"], 4)
        video_one = timeline["tracks"]["video"]["tracks"][0]
        self.assertEqual(video_one["item_count"], 2)
        self.assertEqual([item["timeline_item_id"] for item in video_one["items"]], ["a1"])
        self.assertEqual(timeline["tracks"]["audio"]["tracks"][0]["items"], [])
        self.assertEqual(out["gaps_overlaps"]["gap_count"], 1)

    def test_bad_params_are_refused(self):
        proj = SnapshotProject(_timeline())
        for params in ({"include": "timeline"}, {"track_types": "video"},
                       {"item_limit": "many"}, {"item_limit": -1}):
            with self.subTest(params=params):
                self.assertEqual(self._snapshot(proj, params)["error"]["category"], "invalid_input")

    def test_default_output_stays_compact_for_a_sixty_item_timeline(self):
        media = MediaPoolItemStub("A.mov", "mpi-a", __file__)
        items = [
            TimelineItemStub(f"Clip {i:02d}", f"item-{i:02d}", i * 48, (i + 1) * 48, 100, "video", 1, media)
            for i in range(60)
        ]
        out = self._snapshot(SnapshotProject(SnapshotTimeline({"video": {1: items}})))
        self.assertFalse(out["timeline"]["items_truncated"])
        self.assertLess(len(json.dumps(out)), 16000)

    def test_dispatch_through_project_manager(self):
        proj = SnapshotProject(_timeline())
        self.resolve.GetProjectManager.return_value.GetCurrentProject.return_value = proj
        out = s.project_manager("snapshot", {"include": ["project"]})
        self.assertEqual(out["project"]["id"], "proj-1")

    def test_dispatch_without_a_project(self):
        self.resolve.GetProjectManager.return_value.GetCurrentProject.return_value = None
        out = s.project_manager("snapshot")
        self.assertEqual(out["error"]["message"], "No project open")


if __name__ == "__main__":
    unittest.main()
