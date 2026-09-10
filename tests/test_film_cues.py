"""Picture cues must keep relative frame positions across a DAW handoff."""
import copy
import unittest
from unittest.mock import patch

import src.server as compound
from tests._envelope_helpers import domain_payload


class Timeline:
    def __init__(self, fps=24, start=86400):
        self.fps = fps
        self.start = start
        self.markers = {
            240.0: {"name": "Music in", "note": "Cello", "color": "Blue",
                    "duration": 48.0, "customData": "B1-S02"},
            0.0: {"name": "Picture start", "note": "", "color": "Green",
                  "duration": 1.0, "customData": ""},
        }

    def GetName(self):
        return "Ch5 test"

    def GetStartFrame(self):
        return self.start

    def GetStartTimecode(self):
        return "01:00:00:00"

    def GetSetting(self, key):
        assert key == "timelineFrameRate"
        return self.fps

    def GetMarkers(self):
        return self.markers


class FilmCuesTest(unittest.TestCase):
    def export(self, timeline, params=None):
        with patch.object(compound, "_get_tl", return_value=(None, timeline, None)):
            return domain_payload(compound.timeline_markers("export_cue_sheet", params))

    def test_hour_start_is_metadata_not_an_hour_of_silence(self):
        tl = Timeline()
        original = copy.deepcopy(tl.markers)
        result = self.export(tl)
        self.assertEqual(result.get("schema"), "film-cues/v1")
        self.assertEqual(result["timeline"]["start_frame"], 86400)
        self.assertEqual(result["frame_rate"], {"numerator": 24, "denominator": 1})
        self.assertEqual([c["start_frame"] for c in result["cues"]], [0, 240])
        cue = result["cues"][1]
        self.assertEqual(cue["start_seconds"], 10)
        self.assertEqual(cue["duration_seconds"], 2)
        self.assertEqual(cue["duration_frames"], 48)
        self.assertEqual(cue["custom_data"], "B1-S02")
        self.assertEqual(cue["note"], "Cello")
        self.assertEqual(tl.markers, original)

    def test_ntsc_rates_use_exact_rationals_not_rounded_decimal(self):
        for rate, numerator in [("23.976", 24000), ("29.97 DF", 30000),
                                ("59.94", 60000), ("24000/1001", 24000)]:
            with self.subTest(rate=rate):
                tl = Timeline(rate)
                tl.markers = {numerator: {"name": "Later", "duration": 1}}
                result = self.export(tl)
                self.assertEqual(result.get("frame_rate"),
                                 {"numerator": numerator, "denominator": 1001})
                self.assertEqual(result["cues"][0]["start_seconds"], 1001)

    def test_long_timeline_marker_is_never_guessed_to_be_absolute(self):
        tl = Timeline()
        tl.markers = {90000: {"name": "Late cue", "duration": 24}}
        result = self.export(tl)
        self.assertEqual(result.get("schema"), "film-cues/v1")
        self.assertEqual(result["cues"][0]["start_seconds"], 3750)

    def test_colour_filter_and_empty_result(self):
        result = self.export(Timeline(), {"color": "Blue"})
        self.assertEqual(result.get("schema"), "film-cues/v1")
        self.assertEqual(len(result["cues"]), 1)
        self.assertEqual(result["cues"][0]["name"], "Music in")
        self.assertEqual(self.export(Timeline(), {"color": "Pink"})["cues"], [])

    def test_bad_input_never_exports_a_partial_sheet(self):
        for rate in [None, "garbage", 0, -24, True, "nan", "inf", "24oops"]:
            with self.subTest(rate=rate):
                result = self.export(Timeline(rate))
                self.assertIn("error", result)
                self.assertNotIn("cues", result)
        for frame in [0.5, -1, float("nan"), True]:
            with self.subTest(frame=frame):
                tl = Timeline()
                tl.markers = {frame: {"name": "Bad", "duration": 1}}
                result = self.export(tl)
                self.assertIn("error", result)
                self.assertNotIn("cues", result)

    def test_invalid_duration_and_unreadable_markers_are_errors(self):
        for duration in [0, -1, 1.5, True, float("inf")]:
            with self.subTest(duration=duration):
                tl = Timeline()
                tl.markers = {0: {"name": "Bad", "duration": duration}}
                self.assertIn("error", self.export(tl))
        tl = Timeline()
        tl.markers = None
        self.assertIn("error", self.export(tl))

    def test_empty_timeline_exports_an_empty_sheet(self):
        tl = Timeline()
        tl.markers = {}
        self.assertEqual(self.export(tl).get("cues"), [])

    def test_missing_duration_must_not_invent_a_one_frame_cue(self):
        tl = Timeline()
        tl.markers = {0: {"name": "Incomplete"}}
        result = self.export(tl)
        self.assertIn("error", result)
        self.assertNotIn("cues", result)

    def test_filter_cannot_hide_invalid_timing_or_crash_on_invalid_colour(self):
        for frame, color in [(0.5, "Red"), (0, None)]:
            with self.subTest(frame=frame, color=color):
                tl = Timeline()
                tl.markers = {frame: {"name": "Bad", "duration": 1, "color": color}}
                result = self.export(tl, {"color": "Blue"})
                self.assertIn("error", result)
                self.assertNotIn("cues", result)


if __name__ == "__main__":
    unittest.main()
