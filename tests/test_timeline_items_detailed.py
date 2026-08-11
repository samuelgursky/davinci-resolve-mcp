"""Contract tests for timeline.list_items_detailed."""
import unittest
from unittest import mock

import src.server as s


def _media_pool_item(name="clip.mov", uid="mpi-1", path="D:/media/clip.mov", online="Online"):
    clip = mock.Mock()
    clip.GetName.return_value = name
    clip.GetUniqueId.return_value = uid
    clip.GetMediaId.return_value = "media-1"

    def get_property(key=""):
        properties = {
            "File Path": path,
            "Online Status": online,
            "Type": "Video + Audio",
            "Duration": "120",
        }
        return properties if key == "" else properties.get(key)

    clip.GetClipProperty.side_effect = get_property
    return clip


def _item(name="clip.mov", uid="ti-1", start=86400, duration=120,
          source_start=24, media_pool_item=None):
    item = mock.Mock()
    item.GetName.return_value = name
    item.GetUniqueId.return_value = uid
    item.GetStart.return_value = start
    item.GetEnd.return_value = start + duration
    item.GetDuration.return_value = duration
    item.GetSourceStartFrame.return_value = source_start
    item.GetMediaPoolItem.return_value = media_pool_item or _media_pool_item(name=name)
    return item


def _timeline(track_items=None, enabled=None):
    if track_items is None:
        track_items = {("video", 1): [_item()]}
    if enabled is None:
        enabled = {key: True for key in track_items}
    timeline = mock.Mock()
    timeline.GetTrackCount.side_effect = lambda track_type: max(
        (index for kind, index in track_items if kind == track_type), default=0
    )
    timeline.GetIsTrackEnabled.side_effect = lambda track_type, index: enabled[(track_type, index)]
    timeline.GetItemListInTrack.side_effect = lambda track_type, index: list(
        track_items.get((track_type, index), [])
    )
    return timeline


def _dispatch(timeline, params=None):
    project = mock.Mock()
    project.GetCurrentTimeline.return_value = timeline
    with mock.patch.object(s, "_check", return_value=(mock.Mock(), project, None)):
        return s.timeline("list_items_detailed", params or {})


class TimelineItemsDetailedTest(unittest.TestCase):
    def test_defaults_return_enabled_video_item_with_source_metadata(self):
        out = _dispatch(_timeline())

        self.assertTrue(out["success"], out)
        self.assertEqual(out["track_types"], ["video"])
        self.assertTrue(out["enabled_only"])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(
            out["tracks"],
            [{
                "track_type": "video", "track_index": 1, "enabled": True,
                "item_count": 1, "included_item_count": 1,
            }],
        )
        self.assertEqual(
            out["items"][0],
            {
                "timeline_item_id": "ti-1", "name": "clip.mov",
                "track_type": "video", "track_index": 1, "item_index": 0,
                "start": 86400, "end": 86520, "duration": 120,
                "source_start": 24, "source_end": 144,
                "media_pool_item_id": "mpi-1", "media_pool_item_name": "clip.mov",
                "file_path": "D:/media/clip.mov", "online_status": "Online",
            },
        )


if __name__ == "__main__":
    unittest.main()
