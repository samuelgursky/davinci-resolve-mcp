import unittest

from src.utils.cover_candidates import rank_cover_candidates


def _sample(frame, pixels):
    raw = bytes(channel for value in pixels for channel in (value, value, value))
    return {"frame": frame, "timecode": f"00:00:00:{frame:02d}", "thumbnail_rgb": (len(pixels), 1, raw)}


class CoverFrameCandidatesTest(unittest.TestCase):
    def test_ranks_detailed_midrange_frame_above_blank_and_clipped_frames(self):
        samples = [
            _sample(1, [0, 0, 0, 0]),
            _sample(2, [255, 255, 255, 255]),
            _sample(3, [40, 180, 60, 200]),
        ]
        ranked = rank_cover_candidates(samples)
        self.assertEqual([row["frame"] for row in ranked], [3, 1, 2])
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])

    def test_equal_scores_use_frame_order_for_determinism(self):
        ranked = rank_cover_candidates([_sample(20, [30, 200]), _sample(10, [30, 200])])
        self.assertEqual([row["frame"] for row in ranked], [10, 20])


if __name__ == "__main__":
    unittest.main()
