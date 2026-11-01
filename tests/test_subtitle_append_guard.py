"""Subtitle clipInfo appends are refused before they can abort Resolve.

Issue #335: on Studio 21.1.2.10, AppendToTimeline with a clipInfo for a
Type=Subtitle MediaPoolItem aborts the process. The plain clip list does not.
"""

import unittest
from unittest import mock

import src.server as server
import src.granular.common as granular
from src.utils import subtitle_append_guard as guard


class Item:
    def __init__(self, unique_id, type_name):
        self.unique_id = unique_id
        self.type_name = type_name

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.unique_id

    def GetClipProperty(self, key):
        if key == "Type":
            return self.type_name
        return False


class Folder:
    def __init__(self, clips):
        self.clips = clips

    def GetClipList(self):
        return list(self.clips)

    def GetSubFolderList(self):
        return []


class TimelineItem:
    def __init__(self, unique_id, name):
        self.unique_id = unique_id
        self.name = name

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name


class Timeline:
    def __init__(self):
        self.items = []

    def GetName(self):
        return "Timeline 1"

    def GetUniqueId(self):
        return "timeline-1"

    def GetStartFrame(self):
        return 0

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, track_index):
        if track_type == "video" and track_index == 1:
            return list(self.items)
        return []


class Project:
    def __init__(self, timeline):
        self.timeline = timeline

    def GetCurrentTimeline(self):
        return self.timeline


class Pool:
    def __init__(self, root, timeline):
        self.root = root
        self.timeline = timeline
        self.calls = []

    def GetRootFolder(self):
        return self.root

    def AppendToTimeline(self, payload):
        self.calls.append(payload)
        appended = []
        for index, row in enumerate(payload, start=1):
            clip = row.get("mediaPoolItem") if isinstance(row, dict) else row
            item = TimelineItem(f"timeline-item-{index}", clip.GetName())
            self.timeline.items.append(item)
            appended.append(item)
        return appended


def _clip_info(clip_id):
    return {
        "clip_id": clip_id,
        "start_frame": 0,
        "end_frame": 1007,
        "record_frame": 1,
        "track_index": 2,
    }


class ResolveVersion:
    def __init__(self, text):
        self.text = text

    def GetVersionString(self):
        return self.text


class RefusalMessageTest(unittest.TestCase):
    def test_version_matrix(self):
        item = Item("srt", "Subtitle")
        payload = {"mediaPoolItem": item}
        self.assertIsNone(guard.refusal_message(payload, "21.0.4.5"))
        self.assertIsNone(guard.refusal_message(payload, "Studio 19.1.3.7"))
        self.assertIn("21.1.0", guard.refusal_message(payload, "21.1.0"))
        self.assertIn("Sm2MpObject.cpp:546", guard.refusal_message(payload, "21.1.2.10"))
        self.assertIn("could not be read", guard.refusal_message(payload, None))
        self.assertIn("could not be read", guard.refusal_message(payload, "not-a-version"))

    def test_a_video_clipinfo_and_a_plain_clip_list_are_forwarded(self):
        video = {"mediaPoolItem": Item("clip", "Video")}
        self.assertIsNone(guard.refusal_message(video, "21.1.2.10"))
        self.assertIsNone(guard.refusal_message([Item("srt", "Subtitle")], "21.1.2.10"))
        self.assertFalse(guard.is_subtitle_item(object()))
        self.assertFalse(guard.is_subtitle_item(Item("clip", False)))


class CompoundAppendTest(unittest.TestCase):
    def _append(self, item, version):
        timeline = Timeline()
        pool = Pool(Folder([item]), timeline)
        project = Project(timeline)
        resolve = None if version is None else ResolveVersion(version)
        with mock.patch.object(server, "_get_mp", return_value=(None, project, pool, None)), \
             mock.patch.object(server, "get_resolve", return_value=resolve) as get_resolve:
            result = server.media_pool("append_to_timeline", {"clip_infos": [_clip_info(item.unique_id)]})
        return result, pool, get_resolve

    def test_a_subtitle_clipinfo_on_21_1_2_never_reaches_resolve(self):
        result, pool, _get_resolve = self._append(Item("srt", "Subtitle"), "21.1.2.10")
        self.assertEqual(result["error"]["code"], "SUBTITLE_APPEND_CRASH")
        self.assertEqual(result["error"]["category"], "unsupported")
        self.assertFalse(result["error"]["retryable"])
        self.assertEqual(pool.calls, [])
        self.assertIn("issue #335", result["error"]["message"])

    def test_an_unreadable_version_is_refused_too(self):
        result, pool, _get_resolve = self._append(Item("srt", "Subtitle"), None)
        self.assertEqual(result["error"]["code"], "SUBTITLE_APPEND_CRASH")
        self.assertEqual(pool.calls, [])
        self.assertIn("could not be read", result["error"]["message"])

    def test_21_0_4_still_forwards_the_clipinfo(self):
        result, pool, _get_resolve = self._append(Item("srt", "Subtitle"), "21.0.4.5")
        self.assertTrue(result["success"])
        self.assertEqual(len(pool.calls), 1)
        self.assertEqual(pool.calls[0][0]["mediaPoolItem"].unique_id, "srt")

    def test_a_video_clipinfo_on_21_1_is_forwarded(self):
        result, pool, get_resolve = self._append(Item("clip", "Video"), "21.1.2.10")
        self.assertTrue(result["success"])
        self.assertEqual(len(pool.calls), 1)
        self.assertFalse(any(name == "GetVersionString" for name, _, _ in get_resolve.mock_calls))

    def test_plain_clip_ids_of_a_subtitle_are_still_forwarded(self):
        item = Item("srt", "Subtitle")
        timeline = Timeline()
        pool = Pool(Folder([item]), timeline)
        with mock.patch.object(server, "_get_mp", return_value=(None, Project(timeline), pool, None)), \
             mock.patch.object(server, "get_resolve") as get_resolve:
            result = server.media_pool("append_to_timeline", {"clip_ids": ["srt"]})
        self.assertTrue(result["success"])
        self.assertEqual(len(pool.calls), 1)
        self.assertIs(pool.calls[0][0], item)
        self.assertFalse(any(name == "GetVersionString" for name, _, _ in get_resolve.mock_calls))


class GranularBuilderTest(unittest.TestCase):
    def test_the_granular_builder_refuses_the_same_clipinfo(self):
        item = Item("srt", "Subtitle")
        with mock.patch.object(granular, "_resolve_version_string", return_value="21.1.2.10"):
            out, err = granular._build_append_clip_info_dict(
                Folder([item]), _clip_info("srt"), 0, 0,
            )
        self.assertIsNone(out)
        self.assertEqual(err["code"], "SUBTITLE_APPEND_CRASH")
        self.assertIn("clip_infos[0]", err["error"])


if __name__ == "__main__":
    unittest.main()
