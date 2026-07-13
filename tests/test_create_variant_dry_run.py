import unittest

from src.server import _timeline_create_variant_from_ranges, _build_append_clip_info_dict
from tests._error_envelope_helpers import err_message, is_err


class MediaPoolItemStub:
    def __init__(self, unique_id):
        self._id = unique_id

    def GetUniqueId(self):
        return self._id


class RootFolderStub:
    def __init__(self, clips):
        self._clips = clips

    def GetClipList(self):
        return self._clips

    def GetSubFolderList(self):
        return []


class MediaPoolStub:
    def __init__(self, root):
        self._root = root
        self.created = None

    def GetRootFolder(self):
        return self._root

    def CreateEmptyTimeline(self, name):
        self.created = name
        raise AssertionError("dry_run must not create a timeline")


class ProjectStub:
    def __init__(self, mp):
        self._mp = mp

    def GetMediaPool(self):
        return self._mp


class SourceTimelineStub:
    def GetStartFrame(self):
        return 0


def _proj_with_clip(clip_id):
    return ProjectStub(MediaPoolStub(RootFolderStub([MediaPoolItemStub(clip_id)])))


class CreateVariantDryRunTest(unittest.TestCase):
    def test_dry_run_reports_would_create_without_creating(self):
        proj = _proj_with_clip("mp-1")
        res = _timeline_create_variant_from_ranges(proj, SourceTimelineStub(), {
            "name": "variant",
            "dry_run": True,
            "ranges": [{"clip_id": "mp-1", "start_frame": 0, "end_frame": 100}],
        })
        self.assertTrue(res.get("dry_run"))
        self.assertTrue(res.get("would_create_timeline"))
        self.assertIsNone(proj.GetMediaPool().created)

    def test_dry_run_fails_on_unresolvable_clip_id(self):
        proj = _proj_with_clip("mp-1")
        res = _timeline_create_variant_from_ranges(proj, SourceTimelineStub(), {
            "name": "variant",
            "dry_run": True,
            "ranges": [{"clip_id": "does-not-exist", "start_frame": 0, "end_frame": 100}],
        })
        self.assertTrue(is_err(res))
        self.assertIn("media pool clip not found", err_message(res))

    def test_dry_run_fails_on_invalid_frame_range(self):
        proj = _proj_with_clip("mp-1")
        res = _timeline_create_variant_from_ranges(proj, SourceTimelineStub(), {
            "name": "variant",
            "dry_run": True,
            "ranges": [{"clip_id": "mp-1", "start_frame": 100, "end_frame": 100}],
        })
        self.assertTrue(is_err(res))
        self.assertIn("requires valid start_frame/end_frame", err_message(res))

    def test_pack_dry_run_needs_no_record_frame(self):
        proj = _proj_with_clip("mp-1")
        res = _timeline_create_variant_from_ranges(proj, SourceTimelineStub(), {
            "name": "variant",
            "dry_run": True,
            "pack": True,
            "ranges": [{"clip_id": "mp-1", "start_frame": 0, "end_frame": 100}],
        })
        self.assertTrue(res.get("would_create_timeline"))
        self.assertIsNone(res["ranges"][0]["record_frame"])


class BuildAppendClipInfoPackTest(unittest.TestCase):
    def setUp(self):
        self.root = RootFolderStub([MediaPoolItemStub("mp-1")])

    def test_pack_omits_record_frame(self):
        info, err = _build_append_clip_info_dict(
            self.root, {"clip_id": "mp-1", "start_frame": 0, "end_frame": 100, "track_index": 1},
            0, pack=True)
        self.assertIsNone(err)
        self.assertNotIn("recordFrame", info)

    def test_non_pack_still_requires_record_frame(self):
        info, err = _build_append_clip_info_dict(
            self.root, {"clip_id": "mp-1", "start_frame": 0, "end_frame": 100, "track_index": 1},
            0, pack=False)
        self.assertIsNone(info)
        self.assertIn("record_frame", err_message(err))

    def test_non_pack_reports_record_frame_before_track_index(self):
        # Missing both: record_frame is validated first (preserved error order).
        info, err = _build_append_clip_info_dict(
            self.root, {"clip_id": "mp-1", "start_frame": 0, "end_frame": 100}, 0, pack=False)
        self.assertIsNone(info)
        self.assertIn("record_frame", err_message(err))


if __name__ == "__main__":
    unittest.main()
