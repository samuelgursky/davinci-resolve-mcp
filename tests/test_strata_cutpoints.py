"""Tests for the face strata compute layer + the cut_candidates solver.

Face landmark math is tested on synthetic landmark series (no mediapipe
needed); cut_candidates on a hand-built strata fixture so every scoring rule
is exercised deterministically.
"""

from __future__ import annotations

import unittest
import shutil
import tempfile

from src.utils import analysis_store, strata, strata_faces, strata_queries, timeline_brain_db
from tests.test_analysis_store import make_report


class DispatchCoercionTests(unittest.TestCase):
    """The media_analysis strata dispatch helpers: LLM clients stringify
    numbers and alias clip refs; the dispatch layer must absorb both."""

    def test_opt_number_coerces_strings(self) -> None:
        import src.server as s

        self.assertEqual(s._opt_number("12.5"), 12.5)
        self.assertEqual(s._opt_number(" 3 "), 3.0)
        self.assertEqual(s._opt_number(7), 7.0)
        self.assertIsNone(s._opt_number("abc"))
        self.assertIsNone(s._opt_number(None))
        self.assertIsNone(s._opt_number(True))

    def test_strata_clip_ref_accepts_all_aliases(self) -> None:
        import src.server as s

        for key in s._STRATA_CLIP_REF_KEYS:
            self.assertEqual(s._strata_clip_ref({key: "ref-1"}), "ref-1", key)
        self.assertIsNone(s._strata_clip_ref({}))


def eye(open_ratio: float):
    """Synthetic eye landmarks: unit-width eye whose EAR ≈ open_ratio."""
    half = open_ratio / 2.0
    return {
        "outer": (0.0, 0.0),
        "inner": (1.0, 0.0),
        "top1": (0.33, -half),
        "top2": (0.66, -half),
        "bot1": (0.33, half),
        "bot2": (0.66, half),
    }


def face_frame(ear: float, iris_dx: float = 0.0):
    e = eye(ear)
    return {
        "left_eye": e,
        "right_eye": e,
        "left_iris": (0.5 + iris_dx / 2.0, 0.0),
        "right_iris": (0.5 + iris_dx / 2.0, 0.0),
        "mouth": {"left": (0.2, 1.0), "right": (0.8, 1.0), "top": (0.5, 0.95), "bottom": (0.5, 1.1)},
        "brow": {"left": (0.33, -0.4), "right": (0.66, -0.4)},
        "face": {"top": (0.5, -0.6), "bottom": (0.5, 1.4)},
    }


class FaceComputeTests(unittest.TestCase):
    def test_ear_open_vs_closed(self) -> None:
        self.assertGreater(strata_faces.eye_aspect_ratio(eye(0.35)), 0.3)
        self.assertLess(strata_faces.eye_aspect_ratio(eye(0.08)), 0.1)

    def test_detect_blinks_from_ear_series(self) -> None:
        rate = 12.0
        series = [0.32] * 12 + [0.10] * 2 + [0.32] * 10  # blink at t=1.0s
        blinks = strata_faces.detect_blinks(series, rate)
        self.assertEqual(len(blinks), 1)
        self.assertAlmostEqual(blinks[0]["time_seconds"], 1.0, delta=0.01)
        self.assertEqual(blinks[0]["payload"]["kind"], "blink")

    def test_long_closure_is_eyes_closed_not_blink(self) -> None:
        rate = 12.0
        series = [0.32] * 6 + [0.10] * 12 + [0.32] * 6  # 1s closure
        blinks = strata_faces.detect_blinks(series, rate)
        self.assertEqual(len(blinks), 1)
        self.assertEqual(blinks[0]["payload"]["kind"], "eyes_closed")

    def test_no_face_frames_do_not_blink(self) -> None:
        series = [0.32] * 5 + [None] * 5 + [0.32] * 5
        self.assertEqual(strata_faces.detect_blinks(series, 12.0), [])

    def test_landmarks_to_tracks_shapes_and_gaze(self) -> None:
        frames = [face_frame(0.32, iris_dx=0.0), face_frame(0.32, iris_dx=0.8), None, face_frame(0.09)]
        tracks = strata_faces.landmarks_to_tracks(frames, rate_hz=12.0)
        self.assertEqual(tracks["frame_count"], 4)
        self.assertEqual(tracks["face_frame_count"], 3)
        curves = tracks["curves"]
        for name in ("gaze_x", "gaze_y", "expression_mouth_open", "expression_brow_raise"):
            self.assertEqual(len(curves[name]), 4)
        self.assertAlmostEqual(curves["gaze_x"][0], 0.0, delta=0.05)
        self.assertGreater(curves["gaze_x"][1], 0.5)  # iris pushed right
        self.assertNotEqual(curves["gaze_x"][2], curves["gaze_x"][2])  # NaN when no face

    def test_capabilities_shape(self) -> None:
        caps = strata_faces.capabilities()
        self.assertIn("available", caps)
        self.assertIn("missing", caps)
        self.assertEqual(caps["writes"]["events"], ["blink"])


class CutCandidatesTests(unittest.TestCase):
    """Fixture: 24 fps clip; a word ends at 2.0, next starts at 3.0; pause
    spans the gap; blink at 2.5; breath 2.10–2.35; beat at 2.75; motion
    curve moving in the gap, dead-still early."""

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="strata-cutpoints-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)
        report = make_report()
        report["transcription"] = {
            "success": True,
            "segments": [
                {
                    "start": 0.5,
                    "end": 4.0,
                    "text": "so everything changed",
                    "words": [
                        {"word": "so", "start": 0.5, "end": 0.8},
                        {"word": "everything", "start": 1.2, "end": 2.0},
                        {"word": "changed", "start": 3.0, "end": 3.6},
                    ],
                }
            ],
        }
        result = analysis_store.ingest_report(self.root, report, clip_dir="cutpoint-clip")
        self.clip_uuid = result["clip_uuid"]
        with timeline_brain_db.transaction(self.root) as conn:
            strata.replace_track_events(
                conn, self.clip_uuid, "pause",
                [{"time_seconds": 2.0, "duration_seconds": 1.0}],
                source="prosody_v1", analyzer_version="1.0",
            )
            strata.replace_track_events(
                conn, self.clip_uuid, "breath",
                [{"time_seconds": 2.10, "duration_seconds": 0.25}],
                source="prosody_v1", analyzer_version="1.0",
            )
            strata.replace_track_events(
                conn, self.clip_uuid, "blink",
                [{"time_seconds": 2.5}],
                source="face_v1", analyzer_version="1.0",
            )
            strata.replace_track_events(
                conn, self.clip_uuid, "beat",
                [{"time_seconds": 2.75, "payload": {"tempo_bpm": 120.0}}],
                source="beatgrid_v1", analyzer_version="1.0",
            )
            # motion: still (0.02) until 2.2s, then moving (0.6)
            motion = [0.02] * 22 + [0.6] * 20
            strata.write_curve(
                conn, self.clip_uuid, "motion_energy", motion,
                sample_rate=10.0, source="motion_v1", analyzer_version="1.0",
            )

    def test_rejects_nonpositive_fps(self) -> None:
        for bad in (0, 0.0, -24.0):
            result = strata_queries.cut_candidates(
                self.root, self.clip_uuid, 2.5, fps=bad
            )
            self.assertFalse(result["success"], result)
            self.assertIn("fps", result["error"])

    def test_blink_in_pause_wins(self) -> None:
        result = strata_queries.cut_candidates(self.root, self.clip_uuid, 2.5, window_seconds=0.3)
        self.assertTrue(result["success"], result)
        top = result["candidates"][0]
        self.assertAlmostEqual(top["time_seconds"], 2.5, delta=1.5 / 24.0)
        joined = " ".join(top["reasons"])
        self.assertIn("blink", joined)
        self.assertIn("pause", joined)
        self.assertIn("movement", joined)

    def test_mid_word_frames_are_penalized(self) -> None:
        result = strata_queries.cut_candidates(self.root, self.clip_uuid, 1.6, window_seconds=0.2)
        top = result["candidates"][0]
        # Every frame in 1.4–1.8 is inside "everything": scores are negative.
        self.assertLess(top["score"], 0)
        self.assertIn("everything", " ".join(top["reasons"]))

    def test_breath_bisection_scores_below_clearing(self) -> None:
        result = strata_queries.cut_candidates(self.root, self.clip_uuid, 2.25, window_seconds=0.3, limit=30)
        by_time = {c["time_seconds"]: c for c in result["candidates"]}
        inside = min(by_time, key=lambda t: abs(t - 2.2))
        after = min(by_time, key=lambda t: abs(t - 2.45))
        self.assertLess(by_time[inside]["score"], by_time[after]["score"])
        self.assertIn("bisects a breath", " ".join(by_time[inside]["reasons"]))

    def test_beat_bonus(self) -> None:
        result = strata_queries.cut_candidates(self.root, self.clip_uuid, 2.75, window_seconds=0.1, limit=10)
        top = result["candidates"][0]
        self.assertIn("musical beat", " ".join(top["reasons"]))

    def test_tracks_missing_reported_honestly(self) -> None:
        report = make_report()
        report["clip"]["clip_id"] = "bare-clip-id"
        report["clip"]["media_id"] = "bare-media-id"
        report["clip"]["clip_name"] = "Bare.mp4"
        report["clip"]["file_path"] = "/media/bare.mp4"
        result = analysis_store.ingest_report(self.root, report, clip_dir="bare-clip")
        out = strata_queries.cut_candidates(self.root, result["clip_uuid"], 1.0)
        self.assertTrue(out["success"])
        self.assertIn("transcript_words", out["tracks_missing"])
        self.assertIn("blink", out["tracks_missing"])
        self.assertEqual(out["tracks_used"], [])

    def test_frame_offsets_relative_to_request(self) -> None:
        result = strata_queries.cut_candidates(self.root, self.clip_uuid, 2.5, window_seconds=0.2, limit=30)
        offsets = {c["frame_offset"] for c in result["candidates"]}
        self.assertIn(0, offsets)
        self.assertTrue(any(o < 0 for o in offsets))
        self.assertTrue(any(o > 0 for o in offsets))


if __name__ == "__main__":
    unittest.main()
