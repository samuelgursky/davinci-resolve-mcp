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
            "FPS": "60",
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
                "source_start_seconds": 0.4, "source_end_seconds": None,
                "media_pool_item_id": "mpi-1", "media_pool_item_name": "clip.mov",
                "file_path": "D:/media/clip.mov", "online_status": "Online", "source_fps": 60.0,
            },
        )

    def test_disabled_clip_is_omitted_when_enabled_only(self):
        item = _item(uid="disabled-clip")
        item.GetClipEnabled.return_value = False
        out = _dispatch(_timeline({("video", 1): [item]}))

        self.assertEqual(out["count"], 0)
        self.assertEqual(out["tracks"][0]["included_item_count"], 0)

    def test_layered_tracks_keep_zero_based_item_index_per_track(self):
        out = _dispatch(_timeline({
            ("video", 1): [_item(uid="v1-a"), _item(uid="v1-b")],
            ("video", 2): [_item(uid="v2-a")],
        }))
        self.assertEqual(
            [(row["track_index"], row["item_index"], row["timeline_item_id"])
             for row in out["items"]],
            [(1, 0, "v1-a"), (1, 1, "v1-b"), (2, 0, "v2-a")],
        )

    def test_disabled_track_is_reported_but_omitted_by_default(self):
        tl = _timeline(
            {("video", 1): [_item(uid="enabled")], ("video", 2): [_item(uid="disabled")]},
            {("video", 1): True, ("video", 2): False},
        )
        out = _dispatch(tl)
        self.assertEqual([row["timeline_item_id"] for row in out["items"]], ["enabled"])
        self.assertEqual(out["tracks"][1]["item_count"], 1)
        self.assertEqual(out["tracks"][1]["included_item_count"], 0)

    def test_enabled_only_false_includes_disabled_items(self):
        tl = _timeline(
            {("video", 1): [_item(uid="disabled")]},
            {("video", 1): False},
        )
        out = _dispatch(tl, {"enabled_only": False})
        self.assertEqual([row["timeline_item_id"] for row in out["items"]], ["disabled"])

    def test_requested_track_types_preserve_caller_order(self):
        tl = _timeline({
            ("audio", 1): [_item(uid="a1")],
            ("video", 1): [_item(uid="v1")],
            ("subtitle", 1): [_item(uid="s1", media_pool_item=mock.Mock())],
        })
        out = _dispatch(tl, {"track_types": ["audio", "video", "subtitle"]})
        self.assertEqual(
            [(row["track_type"], row["timeline_item_id"]) for row in out["items"]],
            [("audio", "a1"), ("video", "v1"), ("subtitle", "s1")],
        )

    def test_unknown_enabled_state_warns_and_includes_items(self):
        tl = _timeline({("video", 1): [_item(uid="kept")]})
        tl.GetIsTrackEnabled.side_effect = RuntimeError("page busy")
        out = _dispatch(tl)
        self.assertEqual([row["timeline_item_id"] for row in out["items"]], ["kept"])
        self.assertIsNone(out["tracks"][0]["enabled"])
        self.assertEqual(out["warnings"][0]["code"], "TRACK_ENABLED_STATE_UNAVAILABLE")
        self.assertEqual(out["warnings"][0]["track_index"], 1)

    def test_item_without_media_pool_object_has_null_source_fields(self):
        item = _item()
        item.GetMediaPoolItem.return_value = None
        out = _dispatch(_timeline({("video", 1): [item]}))
        self.assertIsNone(out["items"][0]["media_pool_item_id"])
        self.assertIsNone(out["items"][0]["file_path"])
        self.assertIsNone(out["items"][0]["online_status"])

    def test_empty_timeline_is_successful(self):
        out = _dispatch(_timeline({}))
        self.assertTrue(out["success"], out)
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["tracks"], [])
        self.assertEqual(out["items"], [])

    def test_invalid_parameters_return_structured_errors(self):
        invalid = [
            ({"track_types": "video"}, "INVALID_TRACK_TYPES"),
            ({"track_types": []}, "INVALID_TRACK_TYPES"),
            ({"track_types": ["bogus"]}, "INVALID_TRACK_TYPES"),
            ({"track_types": ["video", "video"]}, "INVALID_TRACK_TYPES"),
            ({"enabled_only": 1}, "INVALID_ENABLED_ONLY"),
        ]
        for params, code in invalid:
            with self.subTest(params=params):
                out = _dispatch(_timeline(), params)
                self.assertEqual(out["error"]["code"], code)
                self.assertEqual(out["error"]["category"], "invalid_input")

    def test_item_list_failure_is_a_top_level_error(self):
        tl = _timeline()
        tl.GetItemListInTrack.side_effect = RuntimeError("Resolve refused")
        out = _dispatch(tl)
        self.assertEqual(out["error"]["code"], "TRACK_ITEMS_READ_FAILED")
        self.assertEqual(out["error"]["category"], "resolve_api_failed")


if __name__ == "__main__":
    unittest.main()
