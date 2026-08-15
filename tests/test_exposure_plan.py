import unittest

from src.utils.exposure_plan import build_exposure_plan


class ExposurePlanTest(unittest.TestCase):
    def test_deduplicates_identical_source_ranges_and_fans_out_results(self):
        calls = []

        def analyzer(path, at_seconds):
            calls.append((path, at_seconds))
            return {"success": True, "stats": {"median": 0.4}, "cdl": {"Slope": [1.1, 1.1, 1.1]}}

        items = [
            {"timeline_item_id": "a", "file_path": "D:/clip.mov", "online_status": "Online", "source_start": 0, "source_end": 60},
            {"timeline_item_id": "b", "file_path": "D:/clip.mov", "online_status": "Online", "source_start": 0, "source_end": 60},
        ]
        out = build_exposure_plan(items, analyzer, source_fps=30)
        self.assertTrue(out["success"], out)
        self.assertEqual(calls, [("D:/clip.mov", 1.0)])
        self.assertEqual([row["timeline_item_id"] for row in out["items"]], ["a", "b"])
        self.assertEqual(out["unique_ranges_analyzed"], 1)

    def test_offline_item_is_a_blocker_and_is_not_analyzed(self):
        out = build_exposure_plan(
            [{"timeline_item_id": "a", "file_path": "D:/clip.mov", "online_status": "Offline", "source_start": 0, "source_end": 60}],
            lambda *_: self.fail("offline source must not be analyzed"),
        )
        self.assertFalse(out["success"])
        self.assertEqual(out["blockers"][0]["code"], "SOURCE_UNAVAILABLE")

    def test_analyzer_failure_is_structured_per_range(self):
        out = build_exposure_plan(
            [{"timeline_item_id": "a", "file_path": "D:/clip.mov", "online_status": "Online", "source_start": 0, "source_end": 60}],
            lambda *_: {"success": False, "error": "ffmpeg missing"},
        )
        self.assertFalse(out["success"])
        self.assertEqual(out["blockers"][0]["code"], "EXPOSURE_ANALYSIS_FAILED")
        self.assertEqual(out["items"][0]["analysis"]["error"], "ffmpeg missing")

    def test_degenerate_source_range_is_blocked_without_analysis(self):
        out = build_exposure_plan(
            [{"timeline_item_id": "a", "file_path": "D:/clip.mov", "online_status": "Online", "source_start": 60, "source_end": 60}],
            lambda *_: self.fail("degenerate range must not be analyzed"),
        )

        self.assertFalse(out["success"])
        self.assertEqual(out["blockers"][0]["code"], "INVALID_SOURCE_RANGE")
        self.assertEqual(out["unique_ranges_analyzed"], 0)

    def test_uses_each_sources_fps_for_sampling_and_deduplication(self):
        calls = []
        items = [
            {"timeline_item_id": "a", "file_path": "D:/clip.mov", "online_status": "Online", "source_start": 0, "source_end": 60, "source_fps": 60},
            {"timeline_item_id": "b", "file_path": "D:/clip.mov", "online_status": "Online", "source_start": 0, "source_end": 60, "source_fps": 30},
        ]

        out = build_exposure_plan(items, lambda path, at: calls.append((path, at)) or {"success": True})

        self.assertTrue(out["success"], out)
        self.assertEqual(calls, [("D:/clip.mov", 0.5), ("D:/clip.mov", 1.0)])
        self.assertEqual(out["unique_ranges_analyzed"], 2)


if __name__ == "__main__":
    unittest.main()
