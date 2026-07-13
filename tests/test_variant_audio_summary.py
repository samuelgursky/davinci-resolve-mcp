"""create_variant_from_ranges reports whether a variant carries audio."""
import unittest

from src.server import _variant_audio_summary


class VariantAudioSummaryTest(unittest.TestCase):
    def test_video_only_warns(self):
        summary = _variant_audio_summary([{"media_type": 1}, {"media_type": 1}])
        self.assertEqual((summary["video_ranges"], summary["audio_ranges"]), (2, 0))
        self.assertIn("video-only", summary["warning"])

    def test_with_audio_has_no_warning(self):
        summary = _variant_audio_summary([{"media_type": 1}, {"media_type": 2}])
        self.assertEqual((summary["video_ranges"], summary["audio_ranges"]), (1, 1))
        self.assertNotIn("warning", summary)


if __name__ == "__main__":
    unittest.main()
