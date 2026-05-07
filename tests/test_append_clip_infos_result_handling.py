import unittest

from src.server import _append_clip_info_from_timeline_item, _serialize_appended_timeline_item


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


class TimelineItemDupStub:
    """Minimal timeline clip: GetEnd exclusive, LeftOffset + duration = source end inclusive."""

    def __init__(self, mpi=None):
        self._mpi = mpi or object()

    def GetMediaPoolItem(self):
        return self._mpi

    def GetStart(self):
        return 100

    def GetEnd(self):
        return 160

    def GetLeftOffset(self):
        return 50


class TimelineItemDupNoPoolStub(TimelineItemDupStub):
    def GetMediaPoolItem(self):
        return None


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

    def test_serialize_appended_timeline_item_allows_empty_id_when_requested(self):
        item_out, item_err = _serialize_appended_timeline_item(
            TimelineItemStub(unique_id=""), 0, allow_empty_timeline_item_id=True
        )
        self.assertIsNone(item_err)
        self.assertEqual(
            item_out,
            {"timeline_item_id": None, "name": "synthetic_append_clip_infos.mp4"},
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

    def test_append_clip_info_from_timeline_item_maps_trim_and_record(self):
        mpi = object()
        info, err = _append_clip_info_from_timeline_item(TimelineItemDupStub(mpi), target_track_index=2, record_frame_offset=5)
        self.assertIsNone(err)
        self.assertIs(info["mediaPoolItem"], mpi)
        self.assertEqual(info["startFrame"], 50)
        self.assertEqual(info["endFrame"], 109)
        self.assertEqual(info["recordFrame"], 105)
        self.assertEqual(info["trackIndex"], 2)

    def test_append_clip_info_from_timeline_item_rejects_no_media_pool(self):
        info, err = _append_clip_info_from_timeline_item(TimelineItemDupNoPoolStub(), 1, 0)
        self.assertIsNone(info)
        self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main()
