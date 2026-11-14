"""clip_infos track_index / media_type validation (issue #370).

Resolve places a clipInfo whose trackIndex names no existing track, or is not
an int, on track 1 and returns the new items; the server's read-back then
called the wrong-track placement verified. Bad indexes are now refused before
AppendToTimeline, and building a new timeline adds the tracks its rows name.
"""

from __future__ import annotations

import unittest
from unittest import mock

import src.server as s
from src.utils import clip_info_tracks as cit
from tests.test_media_pool_append_verification import (
    ClipStub,
    FolderStub,
    MediaPoolStub,
    ProjectStub,
    TimelineStub,
)


class _Tracks(TimelineStub):
    def __init__(self, video=3, audio=2):
        super().__init__()
        self.counts = {"video": video, "audio": audio, "subtitle": 0}
        self.added = []

    def GetTrackCount(self, track_type):
        return self.counts.get(track_type, 0)

    def AddTrack(self, track_type, *args):
        self.counts[track_type] = self.counts.get(track_type, 0) + 1
        self.added.append(track_type)
        return True

    def GetStartFrame(self):
        return 0


class _RecordingPool(MediaPoolStub):
    def __init__(self, root, timeline):
        super().__init__(root, timeline)
        self.sent = []
        self.created = []

    def AppendToTimeline(self, clips):
        self.sent.extend((c.get("trackIndex"), c.get("mediaType")) for c in clips)
        return super().AppendToTimeline(clips)

    def CreateEmptyTimeline(self, name):
        self.created.append(name)
        return self.timeline


def _row(track_index, **extra):
    return {"clip_id": "clip-1", "start_frame": 0, "end_frame": 24,
            "record_frame": 0, "track_index": track_index, **extra}


class AppendTrackIndexTest(unittest.TestCase):
    def _append(self, *rows, video=3, audio=2):
        tl = _Tracks(video, audio)
        pool = _RecordingPool(FolderStub([ClipStub()]), tl)
        with mock.patch.object(s, "_get_mp", return_value=(None, ProjectStub(tl), pool, None)):
            return s.media_pool("append_to_timeline", {"clip_infos": list(rows)}), pool

    def test_an_existing_track_is_sent_as_an_int(self):
        result, pool = self._append(_row(2, media_type=1))
        self.assertTrue(result.get("success"), result)
        self.assertEqual(pool.sent, [(2, 1)])

    def test_out_of_range_indexes_are_refused_with_the_track_count(self):
        for bad in (5, 99):
            result, pool = self._append(_row(bad, media_type=1))
            self.assertEqual(result["error"]["code"], "TRACK_INDEX_OUT_OF_RANGE", result)
            self.assertIn("3 video", result["error"]["message"])
            self.assertEqual(pool.sent, [], f"track {bad} must not reach Resolve")

    def test_zero_and_negative_are_refused(self):
        for bad in (0, -1):
            result, pool = self._append(_row(bad))
            self.assertEqual(result["error"]["code"], "INVALID_TRACK_INDEX", result)
            self.assertEqual(pool.sent, [])

    def test_a_digit_string_is_coerced_not_dropped(self):
        result, pool = self._append(_row("2", media_type=1))
        self.assertTrue(result.get("success"), result)
        self.assertEqual(pool.sent, [(2, 1)], "'2' used to be sent as a string and land on track 1")

    def test_non_integer_values_are_refused(self):
        for bad in ("two", 2.5, True, [2]):
            result, pool = self._append(_row(bad))
            self.assertIn("error", result, bad)
            self.assertEqual(pool.sent, [], bad)

    def test_media_type_selects_the_track_type_checked(self):
        result, pool = self._append(_row(3, media_type=2))  # 2 audio tracks
        self.assertEqual(result["error"]["code"], "TRACK_INDEX_OUT_OF_RANGE", result)
        self.assertIn("2 audio", result["error"]["message"])
        result, pool = self._append(_row(2, media_type=2))
        self.assertTrue(result.get("success"), result)

    def test_without_media_type_an_index_either_type_has_is_allowed(self):
        result, pool = self._append(_row(3))  # V3 exists, A3 does not
        self.assertTrue(result.get("success"), result)
        result, pool = self._append(_row(4))  # neither exists
        self.assertEqual(result["error"]["code"], "TRACK_INDEX_OUT_OF_RANGE", result)

    def test_a_bad_media_type_is_refused(self):
        for bad in (0, 3, "video"):
            result, pool = self._append(_row(1, media_type=bad))
            self.assertEqual(result["error"]["code"], "INVALID_MEDIA_TYPE", result)
            self.assertEqual(pool.sent, [])

    def test_one_bad_row_refuses_the_whole_batch(self):
        result, pool = self._append(_row(1, media_type=1), _row(9, media_type=1))
        self.assertIn("clip_infos[1]", result["error"]["message"])
        self.assertEqual(pool.sent, [])


class CreateTimelineAddsNamedTracksTest(unittest.TestCase):
    def test_rows_naming_higher_tracks_get_them(self):
        tl = _Tracks(video=1, audio=1)
        pool = _RecordingPool(FolderStub([ClipStub()]), tl)
        proj = ProjectStub(tl)
        proj.SetCurrentTimeline = lambda t: True
        rows = [_row(1, media_type=1), _row(3, media_type=1), _row(2, media_type=2)]
        with mock.patch.object(s, "_get_mp", return_value=(None, proj, pool, None)), \
             mock.patch.object(s, "_set_current_timeline_checked", return_value=None), \
             mock.patch.object(s, "_find_timeline_by_name", return_value=(None, None)):
            result = s.media_pool("create_timeline_from_clips", {"name": "N", "clip_infos": rows})
        self.assertTrue(result.get("success"), result)
        self.assertEqual(tl.counts["video"], 3)
        self.assertEqual(tl.counts["audio"], 2)
        self.assertEqual(pool.sent, [(1, 1), (3, 1), (2, 2)])

    def test_an_invalid_index_is_refused_before_the_timeline_exists(self):
        tl = _Tracks()
        pool = _RecordingPool(FolderStub([ClipStub()]), tl)
        with mock.patch.object(s, "_get_mp", return_value=(None, ProjectStub(tl), pool, None)), \
             mock.patch.object(s, "_find_timeline_by_name", return_value=(None, None)):
            result = s.media_pool("create_timeline_from_clips",
                                  {"name": "N", "clip_infos": [_row("x")]})
        self.assertEqual(result["error"]["code"], "INVALID_TRACK_INDEX", result)
        self.assertEqual(pool.created, [], "no empty timeline may be left behind")


class GranularTrackIndexTest(unittest.TestCase):
    def test_the_granular_builder_refuses_out_of_range(self):
        from src.granular import common

        tl = _Tracks(video=1, audio=1)
        root = FolderStub([ClipStub()])
        with mock.patch.object(common, "_find_clip_by_id", return_value=ClipStub()):
            row, err = common._build_append_clip_info_dict(root, _row(5, media_type=1), 0, 0, timeline=tl)
            self.assertIsNone(row)
            self.assertEqual(err["code"], "TRACK_INDEX_OUT_OF_RANGE")
            row, err = common._build_append_clip_info_dict(root, _row("1"), 0, 0, timeline=tl)
            self.assertIsNone(err, err)
            self.assertEqual(row["trackIndex"], 1)


class GranularCreateTimelineTest(unittest.TestCase):
    def _create(self, rows):
        from src.granular import timeline as gt

        tl = _Tracks(video=1, audio=1)
        pool = _RecordingPool(FolderStub([ClipStub()]), tl)
        with mock.patch.object(gt, "_get_mp", return_value=(ProjectStub(tl), pool, None)), \
             mock.patch.object(gt, "_find_clip_by_id", return_value=ClipStub()), \
             mock.patch.object(gt, "set_current_timeline", return_value=(True, {})):
            fn = getattr(gt.create_timeline_from_clips, "fn", gt.create_timeline_from_clips)
            return fn("N", clip_infos=rows), tl, pool

    def test_named_tracks_are_added_before_the_append(self):
        result, tl, pool = self._create([_row(2, media_type=1)])
        self.assertNotIn("error", result, result)
        self.assertEqual(tl.counts["video"], 2)
        self.assertEqual(pool.sent, [(2, 1)])

    def test_an_invalid_index_creates_nothing(self):
        result, tl, pool = self._create([_row(0)])
        self.assertEqual(result.get("code"), "INVALID_TRACK_INDEX", result)
        self.assertEqual(pool.created, [])


class HelperTest(unittest.TestCase):
    def test_coercion(self):
        self.assertEqual(cit.coerce_track_index(2, 0), (2, None))
        self.assertEqual(cit.coerce_track_index(" 2 ", 0), (2, None))
        self.assertEqual(cit.coerce_track_index(2.0, 0), (2, None))
        self.assertIsNotNone(cit.coerce_track_index(False, 0)[1])
        self.assertEqual(cit.coerce_media_type(None, 0), (None, None))

    def test_an_unreadable_track_count_is_not_refused(self):
        class Broken:
            def GetTrackCount(self, t):
                raise RuntimeError("no")
        self.assertIsNone(cit.track_range_error(Broken(), 9, 1, 0))
        self.assertIsNone(cit.track_range_error(None, 9, 1, 0))

    def test_needed_tracks(self):
        needed, err = cit.needed_tracks([{"track_index": 3}, {"track_index": 2, "media_type": 2}])
        self.assertIsNone(err)
        self.assertEqual(needed, {"video": 3, "audio": 3})


if __name__ == "__main__":
    unittest.main()
