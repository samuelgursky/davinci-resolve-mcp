import unittest
from unittest import mock

import src.server as s
from src.utils.readback import reset_verification_stats, verification_stats


class ClipStub:
    def __init__(self, unique_id="clip-1", name="source.mov"):
        self.unique_id = unique_id
        self.name = name

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name


class FolderStub:
    def __init__(self, clips=None):
        self.clips = clips or []

    def GetClipList(self):
        return list(self.clips)

    def GetSubFolderList(self):
        return []


class TimelineItemStub:
    def __init__(self, unique_id, name):
        self.unique_id = unique_id
        self.name = name

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name


class TimelineStub:
    def __init__(self):
        self.items = []

    def GetName(self):
        return "Timeline 1"

    def GetUniqueId(self):
        return "timeline-1"

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, track_index):
        if track_type == "video" and track_index == 1:
            return list(self.items)
        return []


class ProjectStub:
    def __init__(self, timeline):
        self.timeline = timeline

    def GetCurrentTimeline(self):
        return self.timeline


class MediaPoolStub:
    def __init__(self, root, timeline):
        self.root = root
        self.timeline = timeline

    def GetRootFolder(self):
        return self.root

    def AppendToTimeline(self, clips):
        appended = []
        for index, row in enumerate(clips, start=1):
            clip = row.get("mediaPoolItem") if isinstance(row, dict) else row
            item = TimelineItemStub(f"timeline-item-{index}", clip.GetName())
            self.timeline.items.append(item)
            appended.append(item)
        return appended


class MediaPoolAppendVerificationTest(unittest.TestCase):
    def test_append_to_timeline_simple_updates_verified_operation_and_stats(self):
        reset_verification_stats()
        clip = ClipStub()
        timeline = TimelineStub()
        project = ProjectStub(timeline)
        media_pool = MediaPoolStub(FolderStub([clip]), timeline)

        with mock.patch.object(s, "_get_mp", return_value=(None, project, media_pool, None)):
            result = s.media_pool("append_to_timeline", {"clip_ids": ["clip-1"]})

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        operation = result["verified_operation"]
        self.assertEqual(operation["name"], "media_pool.append_to_timeline")
        self.assertTrue(operation["verified"])
        self.assertEqual(operation["verification_status"], "readback_verified")
        self.assertEqual(operation["execution"]["success"], True)
        self.assertEqual(operation["readback"]["item_count_delta"], 1)

        stats = verification_stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["verified"], 1)
        self.assertEqual(stats["contradicted"], 0)
        self.assertEqual(stats["unverified"], 0)

    def test_append_to_timeline_clip_infos_updates_verified_operation_and_stats(self):
        reset_verification_stats()
        clip = ClipStub()
        timeline = TimelineStub()
        project = ProjectStub(timeline)
        media_pool = MediaPoolStub(FolderStub([clip]), timeline)

        with mock.patch.object(s, "_get_mp", return_value=(None, project, media_pool, None)):
            result = s.media_pool(
                "append_to_timeline",
                {
                    "clip_infos": [
                        {
                            "clip_id": "clip-1",
                            "start_frame": 0,
                            "end_frame": 24,
                            "record_frame": 0,
                            "track_index": 1,
                            "media_type": 1,
                        }
                    ]
                },
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["timeline_item_id"], "timeline-item-1")
        operation = result["verified_operation"]
        self.assertEqual(operation["name"], "media_pool.append_to_timeline")
        self.assertTrue(operation["verified"])
        self.assertEqual(operation["verification_status"], "readback_verified")
        self.assertEqual(operation["readback"]["item_count_delta"], 1)

        stats = verification_stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["verified"], 1)


if __name__ == "__main__":
    unittest.main()
