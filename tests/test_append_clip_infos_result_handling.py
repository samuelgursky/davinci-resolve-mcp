import unittest

from src.server import _serialize_appended_timeline_item


class TimelineItemStub:
    def __init__(self, unique_id="timeline-item-123", name="synthetic_append_clip_infos.mp4"):
        self.unique_id = unique_id
        self.name = name

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name


class BrokenTimelineItemStub:
    def GetUniqueId(self):
        raise RuntimeError("Resolve returned no item handle")


class AppendClipInfosResultHandlingTest(unittest.TestCase):
    def test_serialize_appended_timeline_item_requires_item_handle(self):
        item_out, item_err = _serialize_appended_timeline_item(None, 0)

        self.assertIsNone(item_out)
        self.assertEqual(
            item_err,
            {"error": "Failed to append clip_infos to timeline: missing timeline item at index 0"},
        )

    def test_serialize_appended_timeline_item_requires_unique_id(self):
        item_out, item_err = _serialize_appended_timeline_item(TimelineItemStub(unique_id=""), 2)

        self.assertIsNone(item_out)
        self.assertEqual(
            item_err,
            {"error": "Failed to append clip_infos to timeline: missing timeline item id at index 2"},
        )

    def test_serialize_appended_timeline_item_rejects_invalid_item_handle(self):
        item_out, item_err = _serialize_appended_timeline_item(BrokenTimelineItemStub(), 1)

        self.assertIsNone(item_out)
        self.assertEqual(
            item_err,
            {"error": "Failed to append clip_infos to timeline: invalid timeline item at index 1"},
        )

    def test_serialize_appended_timeline_item_returns_summary(self):
        item_out, item_err = _serialize_appended_timeline_item(TimelineItemStub(), 0)

        self.assertIsNone(item_err)
        self.assertEqual(
            item_out,
            {
                "timeline_item_id": "timeline-item-123",
                "name": "synthetic_append_clip_infos.mp4",
            },
        )


if __name__ == "__main__":
    unittest.main()
