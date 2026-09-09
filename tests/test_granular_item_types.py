"""Regression contracts for the lowercase item types documented in Resolve 21.1.

No Resolve connection: test the actual granular handlers against narrow stubs.
Title-case values are compatibility controls, not a claim about older builds.
"""
import unittest
from unittest.mock import patch

from src.granular import timeline_item as tools


class Item:
    GetMediaType = None  # Resolve's missing methods can resolve to None.

    def __init__(self, kind):
        self.kind = kind
        self.writes = []

    def GetType(self):
        return self.kind

    def GetUniqueId(self):
        return "item"

    def GetName(self):
        return "synthetic"

    def GetStart(self):
        return 86400

    def GetEnd(self):
        return 86448

    def GetDuration(self):
        return 48

    def GetProperty(self, name):
        return 1.0

    def SetProperty(self, name, value):
        self.writes.append((name, value))
        return True


class Timeline:
    def __init__(self, item):
        self.item = item

    def GetTrackCount(self, kind):
        return 1 if kind == "video" else 0

    def GetItemListInTrack(self, kind, index):
        return [self.item] if kind == "video" else []


class Project:
    def __init__(self, item):
        self.timeline = Timeline(item)

    def GetCurrentTimeline(self):
        return self.timeline


class ItemTypeTests(unittest.TestCase):
    def invoke(self, item, handler, *args, **kwargs):
        with patch.object(tools, "get_current_project", return_value=(None, Project(item))):
            return handler("item", *args, **kwargs)

    def test_video_transform_accepts_lowercase_and_title_case(self):
        for kind in ("video", "Video"):
            with self.subTest(kind=kind):
                item = Item(kind)
                result = self.invoke(item, tools.set_timeline_item_transform, "ZoomX", 0.5)
                self.assertIn("Successfully", result)
                self.assertEqual(item.writes, [("ZoomX", 0.5)])

    def test_other_video_guards_accept_documented_type(self):
        cases = [
            (tools.set_timeline_item_crop, {"crop_type": "Left", "crop_value": 10}),
            (tools.set_timeline_item_composite, {"opacity": 0.5}),
            (tools.set_timeline_item_stabilization, {"enabled": True}),
            (tools.enable_keyframes, {}),
        ]
        for handler, kwargs in cases:
            with self.subTest(handler=handler.__name__):
                item = Item("video")
                result = self.invoke(item, handler, **kwargs)
                self.assertIn("Successfully", result)
                self.assertTrue(item.writes)

    def test_non_video_and_unknown_types_are_not_written(self):
        for kind in ("audio", "generator", "transition", "", None, 1):
            with self.subTest(kind=kind):
                item = Item(kind)
                result = self.invoke(item, tools.set_timeline_item_transform, "ZoomX", 0.5)
                self.assertIn("not a video item", result)
                self.assertEqual(item.writes, [])

    def test_video_resource_does_not_call_missing_media_type(self):
        item = Item("video")
        result = self.invoke(item, tools.get_timeline_item_properties)
        self.assertNotIn("error", result)
        self.assertIn("transform", result)
        self.assertNotIn("audio", result)
        self.assertEqual(result["type"], "video")

    def test_audio_resource_accepts_lowercase_and_title_case(self):
        for kind in ("audio", "Audio"):
            with self.subTest(kind=kind):
                result = self.invoke(Item(kind), tools.get_timeline_item_properties)
                self.assertNotIn("error", result)
                self.assertIn("audio", result)
                self.assertNotIn("transform", result)

    def test_optional_media_type_fallback_remains_supported(self):
        for kind in ("audio", "Audio"):
            with self.subTest(kind=kind):
                item = Item("video")
                item.GetMediaType = lambda: kind
                result = self.invoke(item, tools.get_timeline_item_properties)
                self.assertIn("audio", result)

    def test_audio_write_without_media_type_refuses_instead_of_calling_none(self):
        item = Item("video")
        result = self.invoke(item, tools.set_timeline_item_audio, volume=0.5)
        self.assertIn("does not have audio properties", result)
        self.assertEqual(item.writes, [])


if __name__ == "__main__":
    unittest.main()
