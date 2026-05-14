import unittest

from src.server import (
    _contact_sheet_png_bytes,
    _contact_sheet_sample_label,
    _frame_id_to_timecode,
    _story_spine_from_snapshot,
)


class TimelineEditorialHelperTests(unittest.TestCase):
    def test_contact_sheet_adds_label_band(self):
        raw = bytes([255, 0, 0] * 4)
        samples = [{
            "frame": 108000,
            "timecode": "01:00:00:00",
            "source": "marker",
            "marker": {"name": "Premise"},
            "thumbnail_rgb": (2, 2, raw),
        }]

        width, height, png = _contact_sheet_png_bytes(samples, columns=1, padding=2, label_height=12)

        self.assertEqual(width, 6)
        self.assertEqual(height, 18)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertIn("PREMISE", _contact_sheet_sample_label(samples[0], 1).upper())

    def test_frame_id_to_timecode_uses_nominal_frame_rate(self):
        self.assertEqual(_frame_id_to_timecode(108000, 29.97), "01:00:00:00")
        self.assertEqual(_frame_id_to_timecode(108015, 29.97), "01:00:00:15")

    def test_story_spine_sorts_markers_and_summarizes_tracks(self):
        snapshot = {
            "name": "Evidence Cut",
            "id": "timeline-1",
            "start_frame": 108000,
            "end_frame": 108450,
            "start_timecode": "01:00:00:00",
            "markers": {
                108300: {"name": "Button", "note": "final turn", "color": "Blue", "duration": 1},
                108000: {"name": "Premise", "note": "setup", "color": "Green", "duration": 1},
            },
            "tracks": {
                "video": {
                    "tracks": [{
                        "track_index": 1,
                        "items": [{
                            "timeline_item_id": "v1",
                            "name": "Source",
                            "start": 108000,
                            "end": 108120,
                            "source_start": 120,
                            "source_end": 240,
                            "media_pool_item_name": "Source.mov",
                        }],
                    }],
                },
                "audio": {
                    "tracks": [{
                        "track_index": 1,
                        "items": [{
                            "timeline_item_id": "a1",
                            "name": "Source Audio",
                            "start": 108000,
                            "end": 108450,
                            "source_start": 120,
                            "source_end": 570,
                            "media_pool_item_name": "Source.mov",
                        }],
                    }],
                },
                "subtitle": {"tracks": []},
            },
        }

        report = _story_spine_from_snapshot(snapshot)

        self.assertTrue(report["audio_spine"]["present"])
        self.assertEqual(report["beats"][0]["name"], "Premise")
        self.assertEqual(report["beats"][1]["name"], "Button")
        self.assertEqual(report["audio_spine"]["audio_item_count"], 1)
        self.assertEqual(report["audio_spine"]["video_item_count"], 1)
        self.assertIn("Source.mov", report["source_ranges"]["ranges"])


if __name__ == "__main__":
    unittest.main()
