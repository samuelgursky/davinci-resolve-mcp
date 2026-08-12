import unittest
import tempfile
from pathlib import Path
from unittest import mock

import src.server as s
from src.utils.cover_candidates import rank_cover_candidates


def _sample(frame, pixels):
    raw = bytes(channel for value in pixels for channel in (value, value, value))
    return {"frame": frame, "timecode": f"00:00:00:{frame:02d}", "thumbnail_rgb": (len(pixels), 1, raw)}


class CoverFrameCandidatesTest(unittest.TestCase):
    def test_markerless_timeline_gets_uniform_frame_samples(self):
        timeline = mock.Mock()
        timeline.GetStartFrame.return_value = 100
        timeline.GetEndFrame.return_value = 200
        with mock.patch.object(s, "_timeline_conform_snapshot", return_value={"markers": {}}):
            samples, error = s._timeline_contact_sheet_samples(timeline, {"max_samples": 3})

        self.assertIsNone(error)
        self.assertEqual([row["frame"] for row in samples], [100, 150, 199])
        self.assertEqual({row["source"] for row in samples}, {"uniform"})

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

    def test_incomplete_export_request_fails_before_contact_sheet_side_effects(self):
        with mock.patch.object(s, "_timeline_thumbnail_contact_sheet") as contact_sheet:
            out = s._timeline_cover_frame_candidates(
                mock.Mock(),
                mock.Mock(),
                {"selected_frame": 12},
            )

        self.assertEqual(out["error"]["code"], "INCOMPLETE_COVER_EXPORT")
        contact_sheet.assert_not_called()

    def test_export_refuses_existing_or_external_destination(self):
        with tempfile.TemporaryDirectory() as analysis_root, tempfile.TemporaryDirectory() as external_root:
            existing = Path(analysis_root) / "cover.png"
            existing.write_bytes(b"source")
            review = {"success": True, "path": "sheet.png", "project_root": analysis_root, "cover_candidates": [], "samples": []}
            project = mock.Mock()
            timeline = mock.Mock()
            with mock.patch.object(s, "_timeline_thumbnail_contact_sheet", return_value=review):
                overwrite = s._timeline_cover_frame_candidates(project, timeline, {"selected_frame": 12, "export_path": str(existing)})
                external = s._timeline_cover_frame_candidates(project, timeline, {"selected_frame": 12, "export_path": str(Path(external_root) / "cover.png")})

        self.assertEqual(overwrite["error"]["code"], "COVER_EXPORT_EXISTS")
        self.assertEqual(external["error"]["code"], "COVER_EXPORT_OUTSIDE_ANALYSIS_ROOT")
        project.ExportCurrentFrameAsStill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
