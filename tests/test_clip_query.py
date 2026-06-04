"""Unit tests for the clip-query DSL (Phase C2)."""
import unittest

from src.utils import clip_query as cq


CLIPS = [
    {"name": "INSERT_hand", "track_type": "video", "track_index": 1,
     "duration": 8, "analyzed": True, "has_transcription": False, "shot_type": "insert"},
    {"name": "wide_master", "track_type": "video", "track_index": 1,
     "duration": 240, "analyzed": True, "has_transcription": True, "shot_type": "wide"},
    {"name": "room_tone", "track_type": "audio", "track_index": 2,
     "duration": 500, "analyzed": False, "has_transcription": False},
]


class ClipQueryTest(unittest.TestCase):
    def test_duration_lt(self):
        out = cq.filter_clips(CLIPS, {"duration_lt": 12})
        self.assertEqual([c["name"] for c in out], ["INSERT_hand"])

    def test_track_type(self):
        out = cq.filter_clips(CLIPS, {"track_type": "audio"})
        self.assertEqual([c["name"] for c in out], ["room_tone"])

    def test_name_contains_case_insensitive(self):
        out = cq.filter_clips(CLIPS, {"name_contains": "insert"})
        self.assertEqual([c["name"] for c in out], ["INSERT_hand"])

    def test_analyzed_false(self):
        out = cq.filter_clips(CLIPS, {"analyzed": False})
        self.assertEqual([c["name"] for c in out], ["room_tone"])

    def test_and_semantics(self):
        out = cq.filter_clips(CLIPS, {"track_type": "video", "duration_gt": 100})
        self.assertEqual([c["name"] for c in out], ["wide_master"])

    def test_empty_filters_returns_all(self):
        self.assertEqual(len(cq.filter_clips(CLIPS, {})), 3)

    def test_sparse_filters_skip_none_and_blank(self):
        out = cq.filter_clips(CLIPS, {"track_type": "video", "name_contains": "", "shot_type": None})
        self.assertEqual(len(out), 2)

    def test_validate_rejects_unknown_keys(self):
        ok, unknown = cq.validate_filters({"duration_lt": 5, "bogus": 1})
        self.assertFalse(ok)
        self.assertEqual(unknown, ["bogus"])

    def test_validate_accepts_known(self):
        ok, unknown = cq.validate_filters({"track_type": "video", "shot_type": "wide"})
        self.assertTrue(ok)
        self.assertEqual(unknown, [])


if __name__ == "__main__":
    unittest.main()
