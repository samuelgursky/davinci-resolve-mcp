import unittest

from src.server import _setup_multicam_timeline
from src.utils.multicam import build_multicam_setup_plan


class MediaPoolItemStub:
    def __init__(self, item_id, name, props=None):
        self.item_id = item_id
        self.name = name
        self.props = props or {}

    def GetUniqueId(self):
        return self.item_id

    def GetName(self):
        return self.name

    def GetClipProperty(self, key=""):
        if not key:
            return dict(self.props)
        return self.props.get(key, "")


class FolderStub:
    def __init__(self, clips=None, subfolders=None):
        self.clips = clips or []
        self.subfolders = subfolders or []

    def GetClipList(self):
        return self.clips

    def GetSubFolderList(self):
        return self.subfolders


def find_clip(folder, clip_id):
    for clip in folder.GetClipList():
        if clip.GetUniqueId() == clip_id:
            return clip
    for subfolder in folder.GetSubFolderList():
        found = find_clip(subfolder, clip_id)
        if found:
            return found
    return None


class TimelineItemStub:
    def __init__(self, item_id, name):
        self.item_id = item_id
        self.name = name

    def GetUniqueId(self):
        return self.item_id

    def GetName(self):
        return self.name


class TimelineStub:
    def __init__(self, name):
        self.name = name
        self.track_counts = {"video": 1, "audio": 1, "subtitle": 0}
        self.track_names = {}
        self.start_timecode = None

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return "timeline-1"

    def GetStartFrame(self):
        return 108000

    def SetStartTimecode(self, timecode):
        self.start_timecode = timecode
        return True

    def GetTrackCount(self, track_type):
        return self.track_counts.get(track_type, 0)

    def AddTrack(self, track_type, options=None):
        self.track_counts[track_type] = self.track_counts.get(track_type, 0) + 1
        return True

    def SetTrackName(self, track_type, track_index, name):
        self.track_names[(track_type, track_index)] = name
        return True


class MediaPoolStub:
    def __init__(self, root):
        self.root = root
        self.timeline = None
        self.appended = []

    def GetRootFolder(self):
        return self.root

    def CreateEmptyTimeline(self, name):
        self.timeline = TimelineStub(name)
        return self.timeline

    def AppendToTimeline(self, clip_infos):
        self.appended = list(clip_infos)
        return [
            TimelineItemStub(f"item-{index + 1}", row["mediaPoolItem"].GetName())
            for index, row in enumerate(clip_infos)
        ]


class ProjectStub:
    def __init__(self):
        self.current_timeline = None

    def SetCurrentTimeline(self, timeline):
        self.current_timeline = timeline
        return True


class MulticamSetupTests(unittest.TestCase):
    def setUp(self):
        self.clip_a = MediaPoolItemStub("a", "A001.mov", {"Frames": "48", "FPS": "24", "Start TC": "01:00:05:00"})
        self.clip_b = MediaPoolItemStub("b", "B001.mov", {"Frames": "72", "FPS": "24", "Start TC": "01:00:10:00"})
        self.root = FolderStub([self.clip_a, self.clip_b])

    def test_plan_stacks_clip_ids_one_angle_per_video_track(self):
        plan, err = build_multicam_setup_plan(
            self.root,
            {"name": "MC Prep", "clip_ids": ["a", "b"]},
            find_clip,
        )

        self.assertIsNone(err)
        self.assertTrue(plan["success"])
        self.assertEqual(plan["max_video_track"], 2)
        self.assertEqual([row["track_index"] for row in plan["append_rows"]], [1, 2])
        self.assertEqual([row["media_type"] for row in plan["append_rows"]], [1, 1])
        self.assertEqual(plan["append_rows"][0]["end_frame"], 48)

    def test_source_timecode_sync_offsets_from_timeline_start_timecode(self):
        plan, err = build_multicam_setup_plan(
            self.root,
            {
                "clip_ids": ["a", "b"],
                "sync_mode": "source_timecode",
                "timeline_start_timecode": "01:00:00:00",
            },
            find_clip,
        )

        self.assertIsNone(err)
        self.assertEqual([row["record_frame"] for row in plan["append_rows"]], [120, 240])

    def test_setup_multicam_timeline_creates_tracks_and_appends_audio_when_requested(self):
        project = ProjectStub()
        pool = MediaPoolStub(self.root)

        result = _setup_multicam_timeline(
            project,
            pool,
            {"name": "MC Prep", "clip_ids": ["a", "b"], "include_audio": True, "start_timecode": "01:00:00:00"},
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["timeline_name"], "MC Prep")
        self.assertIs(project.current_timeline, pool.timeline)
        self.assertEqual(pool.timeline.track_counts["video"], 2)
        self.assertEqual(pool.timeline.track_counts["audio"], 2)
        self.assertEqual(len(pool.appended), 4)
        self.assertEqual([row["mediaType"] for row in pool.appended], [1, 2, 1, 2])
        self.assertEqual([row["trackIndex"] for row in pool.appended], [1, 1, 2, 2])
        self.assertEqual(pool.appended[0]["recordFrame"], 108000)


if __name__ == "__main__":
    unittest.main()
