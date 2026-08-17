"""Guard for the source-frame-rate trap and the units around it.

A timeline item's source frames are counted in the MEDIA's frame rate, not the
timeline's. A WAV has no intrinsic rate, so it takes the PROJECT's timeline rate
at import and freezes it — move the project afterwards and the clip keeps the
old one (measured on Studio 19.1.3.7, 2026-08-10; see the api_truth entry). Read
back at the timeline rate, that offset lands minutes from the real position in
the file, and nothing errors.

Documentation alone cannot stop that — it only helps a caller who thinks to look
it up. These tests pin the guards that make it unmissable: every summary carries
source_fps and the seconds beside the frames, so a frame number always arrives
with its unit attached, and source_end is computed in source space rather than
by adding a timeline duration to a source frame.
"""
import unittest

from src.server import (
    _media_item_source_fps,
    _source_frames_to_seconds,
    _timeline_item_conform_summary,
    _timeline_item_summary,
)


class MediaPoolItemStub:
    """Media-pool item that answers GetClipProperty like Resolve does.

    GetClipProperty('FPS') returns the single value; GetClipProperty('') returns
    the whole property map. Counts calls so the probe path can be shown not to
    re-fetch what it already holds.
    """

    def __init__(self, properties=None, item_id="MediaPoolItem-1", name="clip"):
        self.properties = {} if properties is None else dict(properties)
        self._id = item_id
        self._name = name
        self.property_calls = []

    def GetClipProperty(self, key=""):
        self.property_calls.append(key)
        if key == "":
            return dict(self.properties)
        return self.properties.get(key)

    def GetUniqueId(self):
        return self._id

    def GetName(self):
        return self._name


class TimelineItemStub:
    def __init__(self, media_pool_item=None, start=108000, end=108435,
                 duration=435, source_start=60687):
        self._media_pool_item = media_pool_item
        self._start = start
        self._end = end
        self._duration = duration
        self._source_start = source_start

    def GetStart(self):
        return self._start

    def GetEnd(self):
        return self._end

    def GetDuration(self):
        return self._duration

    def GetSourceStartFrame(self):
        return self._source_start

    def GetMediaPoolItem(self):
        return self._media_pool_item

    def GetUniqueId(self):
        return "TimelineItem-1"

    def GetName(self):
        return "ZOOM0028.WAV"


class SourceFpsReadTest(unittest.TestCase):
    def test_reads_the_wav_rate_resolve_reports(self):
        # The live measurement: Resolve reports FPS 24 (an int) for a WAV.
        self.assertEqual(_media_item_source_fps(MediaPoolItemStub({"FPS": 24})), 24.0)

    def test_reads_a_video_rate_including_string_form(self):
        self.assertEqual(_media_item_source_fps(MediaPoolItemStub({"FPS": 29.97})), 29.97)
        self.assertEqual(_media_item_source_fps(MediaPoolItemStub({"FPS": "29.97"})), 29.97)

    def test_prefers_a_property_dict_the_caller_already_holds(self):
        item = MediaPoolItemStub({"FPS": 24})
        self.assertEqual(_media_item_source_fps(item, {"FPS": 29.97}), 29.97)
        self.assertEqual(item.property_calls, [])  # no second fetch

    def test_unreadable_rate_is_none_not_a_guess(self):
        # An unknown rate must read as unknown. Defaulting to 24 (or to the
        # timeline rate) would reintroduce exactly the silent error being guarded.
        for properties in ({}, {"FPS": ""}, {"FPS": "n/a"}, {"FPS": 0}, {"FPS": None}):
            self.assertIsNone(_media_item_source_fps(MediaPoolItemStub(properties)))
        self.assertIsNone(_media_item_source_fps(None))

    def test_survives_an_item_that_raises(self):
        class Raising:
            def GetClipProperty(self, key=""):
                raise RuntimeError("no handle")

        self.assertIsNone(_media_item_source_fps(Raising()))


class SourceSecondsTest(unittest.TestCase):
    def test_converts_with_the_media_rate(self):
        # The measured case: 56871 source frames of a WAV is 2369.6 s into the
        # file. Read at the 29.97 timeline rate it would be 1897.6 s — 7m52s off.
        self.assertEqual(_source_frames_to_seconds(56871, 24.0), 2369.625)
        self.assertNotEqual(_source_frames_to_seconds(56871, 24.0),
                            _source_frames_to_seconds(56871, 29.97))

    def test_unknown_inputs_yield_none(self):
        self.assertIsNone(_source_frames_to_seconds(None, 24.0))
        self.assertIsNone(_source_frames_to_seconds(100, None))
        self.assertIsNone(_source_frames_to_seconds(100, 0))


class SummaryCarriesTheRateTest(unittest.TestCase):
    def test_summary_reports_rate_and_seconds_for_a_wav(self):
        item = TimelineItemStub(MediaPoolItemStub({"FPS": 24}, name="ZOOM0028.WAV"),
                                source_start=56871, duration=435)
        summary = _timeline_item_summary(item, ("audio", 1))
        self.assertEqual(summary["source_start"], 56871)
        self.assertEqual(summary["source_fps"], 24.0)
        self.assertEqual(summary["source_start_seconds"], 2369.625)
        self.assertEqual(summary["source_end"], 56871 + 435)
        # source_end is source_start + TIMELINE duration, so it is itself
        # unit-mixed: 435 frames of 29.97 record time added to a 24 fps source
        # frame. Dividing THAT by 24 reports an 18.1 s span for a 14.5 s clip —
        # the same class of silent error this module exists to stop. With no
        # source-space end reader on the item, the end must read unknown.
        self.assertIsNone(summary["source_end_seconds"])

    def test_end_seconds_come_from_resolves_own_second_reader(self):
        # GetSourceEndTime answers in seconds with no rate inference at all, so
        # it wins outright when the build exposes it.
        class WithSourceTimes(TimelineItemStub):
            def GetSourceStartTime(self):
                return 2369.625

            def GetSourceEndTime(self):
                return 2369.625 + 435 / 29.97

        summary = _timeline_item_summary(
            WithSourceTimes(MediaPoolItemStub({"FPS": 24}), source_start=56871, duration=435),
            ("audio", 1))
        self.assertEqual(summary["source_start_seconds"], 2369.625)
        self.assertEqual(summary["source_end_seconds"], 2384.14)
        # The span is the clip's real record length, not the unit-mixed 18.125 s.
        self.assertAlmostEqual(
            summary["source_end_seconds"] - summary["source_start_seconds"],
            435 / 29.97, places=2)

    def test_end_seconds_fall_back_to_the_source_space_end_frame(self):
        # No second-reader, but GetSourceEndFrame is a genuine SOURCE frame, so
        # it may be divided by the media rate. source_end (derived) may not.
        class WithSourceEndFrame(TimelineItemStub):
            def GetSourceEndFrame(self):
                return 56871 + round(435 * 24 / 29.97)

        summary = _timeline_item_summary(
            WithSourceEndFrame(MediaPoolItemStub({"FPS": 24}), source_start=56871, duration=435),
            ("audio", 1))
        self.assertEqual(summary["source_end_seconds"], round((56871 + 348) / 24.0, 3))
        self.assertNotEqual(summary["source_end_seconds"],
                            round(summary["source_end"] / 24.0, 3))

    def test_summary_reports_the_video_rate(self):
        item = TimelineItemStub(MediaPoolItemStub({"FPS": 29.97}), source_start=20379)
        summary = _timeline_item_summary(item, ("video", 1))
        self.assertEqual(summary["source_fps"], 29.97)
        self.assertEqual(summary["source_start_seconds"], round(20379 / 29.97, 3))

    def test_missing_media_pool_item_leaves_the_rate_unknown(self):
        summary = _timeline_item_summary(TimelineItemStub(None), ("audio", 1))
        self.assertIsNone(summary["source_fps"])
        self.assertIsNone(summary["source_start_seconds"])
        self.assertIsNone(summary["source_end_seconds"])
        self.assertEqual(summary["source_start"], 60687)  # frames still reported

    def test_left_offset_fallback_on_audio_leaves_the_rate_unknown(self):
        # GetLeftOffset counts an AUDIO item in TIMELINE frames (measured: it
        # advances at 29.970 where GetSourceStartFrame advances at 24.000 on the
        # same WAV). Pairing that number with the media rate would convert it
        # confidently wrong, so the rate must read unknown instead.
        class NoSourceStartFrame(TimelineItemStub):
            GetSourceStartFrame = None

            def GetLeftOffset(self):
                return 75784

        item = NoSourceStartFrame(MediaPoolItemStub({"FPS": 24}))
        summary = _timeline_item_summary(item, ("audio", 1))
        self.assertEqual(summary["source_start"], 75784)  # frame still reported
        self.assertIsNone(summary["source_fps"])
        self.assertIsNone(summary["source_start_seconds"])

    def test_left_offset_fallback_on_video_keeps_the_rate(self):
        # On video the two readers share the source frame space, so the fallback
        # is still convertible.
        class NoSourceStartFrame(TimelineItemStub):
            GetSourceStartFrame = None

            def GetLeftOffset(self):
                return 20379

        summary = _timeline_item_summary(
            NoSourceStartFrame(MediaPoolItemStub({"FPS": 29.97})), ("video", 1))
        self.assertEqual(summary["source_fps"], 29.97)
        self.assertEqual(summary["source_start_seconds"], round(20379 / 29.97, 3))

    def test_probe_summary_does_not_refetch_the_property_map(self):
        # _timeline_item_conform_summary already pulls the full property dict for
        # file_path/media_status; the rate must come out of that same dict rather
        # than costing the probe a second bridge call per item.
        media_pool_item = MediaPoolItemStub(
            {"FPS": 24, "File Path": "/tmp/ZOOM0028.WAV"}, name="ZOOM0028.WAV")
        summary = _timeline_item_conform_summary(
            TimelineItemStub(media_pool_item, source_start=56871), "audio", 1, 0)
        self.assertEqual(summary["source_fps"], 24.0)
        self.assertEqual(summary["source_start_seconds"], 2369.625)
        self.assertEqual(summary["file_path"], "/tmp/ZOOM0028.WAV")
        self.assertEqual(media_pool_item.property_calls, [""])


class SourceEndIsComputedInSourceSpaceTest(unittest.TestCase):
    """source_end is EXCLUSIVE and must be a SOURCE frame.

    It used to be `source_start + duration`, where duration is a TIMELINE
    duration (GetDuration) — unit-mixed the moment the rates differ. Measured
    live on Studio 19.1.3.7 against the endFrame actually sent, that overshot by
    +24, +26, +108 and +149 frames on a 24 fps WAV in a 29.97 fps timeline, and
    `extract_source_frame_ranges` builds pull ranges out of it.

    Resolve's second-reader has no frame-rate assumption in it, so
    `GetSourceEndTime x source_fps` is in source space by construction: exact on
    12 of 12 valid items across matched AND mismatched rates, both media types.
    """

    @staticmethod
    def _item(fps, source_start, duration, end_time):
        class WithEndTime(TimelineItemStub):
            def GetSourceEndTime(self):
                return end_time

        return WithEndTime(MediaPoolItemStub({"FPS": fps}),
                           source_start=source_start, duration=duration)

    def test_mismatched_rates_no_longer_overshoot(self):
        # The measured row: WAV frozen at 24 in a 29.97 timeline, source frames
        # 300-735 sent, timeline duration 543. GetSourceEndTime read 30.633 s.
        item = self._item(24, source_start=300, duration=543, end_time=30.633)
        summary = _timeline_item_summary(item, ("audio", 1))
        self.assertEqual(summary["source_end"], 735)          # what was sent
        self.assertNotEqual(summary["source_end"], 300 + 543)  # the old +108
        # Still exclusive: the span is the source frames the item consumes.
        self.assertEqual(summary["source_end"] - summary["source_start"], 435)

    def test_matched_rates_land_on_exactly_the_old_value(self):
        # 29.97 source in a 29.97 timeline: the derived value was already right,
        # so the new route must reproduce it or every matched-rate consumer moves.
        item = self._item(29.97, source_start=300, duration=435, end_time=24.524)
        summary = _timeline_item_summary(item, ("video", 1))
        self.assertEqual(summary["source_end"], 300 + 435)

    def test_rounding_absorbs_the_seconds_quantisation(self):
        # The conversions land just off an integer in both directions and must
        # round to the frame that was sent, not truncate toward it.
        for fps, start, end_time, expected in (
            (24, 0, 4.175, 100),        # 100.20 -> 100
            (24, 1500, 71.800, 1723),   # 1723.20 -> 1723
            (24, 3000, 150.008, 3600),  # 3600.19 -> 3600
            (29.97, 300, 24.524, 735),  # 734.98 -> 735
        ):
            with self.subTest(fps=fps, end_time=end_time):
                item = self._item(fps, source_start=start, duration=1, end_time=end_time)
                self.assertEqual(
                    _timeline_item_summary(item, ("audio", 1))["source_end"], expected)

    def test_falls_back_to_the_old_value_without_the_second_reader(self):
        # An older build keeps the historical number rather than losing the field.
        item = TimelineItemStub(MediaPoolItemStub({"FPS": 24}),
                                source_start=300, duration=543)
        self.assertEqual(_timeline_item_summary(item, ("audio", 1))["source_end"], 843)

    def test_falls_back_when_the_rate_is_unreadable(self):
        # Seconds alone cannot produce a frame; without a rate there is nothing
        # to multiply by, so the historical value stands.
        item = self._item("n/a", source_start=300, duration=543, end_time=30.633)
        self.assertEqual(_timeline_item_summary(item, ("audio", 1))["source_end"], 843)

    def test_an_end_at_or_before_the_start_is_refused(self):
        # Readers disagreeing about an item must not yield a negative span.
        item = self._item(24, source_start=300, duration=543, end_time=1.0)
        summary = _timeline_item_summary(item, ("audio", 1))
        self.assertEqual(summary["source_end"], 843)
        self.assertGreater(summary["source_end"], summary["source_start"])

    def test_the_left_offset_audio_fallback_keeps_the_pair_self_consistent(self):
        # On the GetLeftOffset fallback for an audio item, source_start is a
        # TIMELINE frame (75784 where the source frame is 60687). A source-space
        # end beside it would make start and end different units in one summary,
        # and source_end - source_start meaningless. Neither choice rescues a
        # consumer here, so keep the historical self-consistent pair — the end
        # stays a duration away from the start — and let source_fps: null carry
        # the warning that these numbers have no reliable unit.
        class NoStartFrame(TimelineItemStub):
            GetSourceStartFrame = None

            def GetLeftOffset(self):
                return 75784

            def GetSourceEndTime(self):
                return 30.633

        summary = _timeline_item_summary(NoStartFrame(MediaPoolItemStub({"FPS": 24})),
                                         ("audio", 1))
        self.assertIsNone(summary["source_fps"])
        self.assertEqual(summary["source_end"] - summary["source_start"],
                         summary["duration"])


class TimecodedMediaSharesTheFileRelativeOriginTest(unittest.TestCase):
    """Issue #147: a non-zero start timecode must not leak into source_end.

    Resolve's second-readers answer in the media's TIMECODE space, while
    GetSourceStartFrame is file-relative. `round(GetSourceEndTime x fps)` was
    therefore a source frame only on media starting at 00:00:00:00 — which is
    exactly what the v2.93.0 live validation used, so the whole synthetic suite
    was blind to it by construction.

    The numbers below are the reporter's measured Canon MP4: 29.97 fps, 10650
    frames, start TC 04:18:37;25 (15517.834 s), cut into a 24 fps timeline for a
    75-frame record duration.
    """

    FPS = 29.97
    CLIP_FRAMES = 10650
    START_TC_SECONDS = 15517.834
    SOURCE_START = 3637
    START_TIME = 15639.187   # TC-absolute, as Resolve reports it
    END_TIME = 15642.304     # TC-absolute, as Resolve reports it

    def _item(self, **kwargs):
        start_time, end_time = self.START_TIME, self.END_TIME

        class Timecoded(TimelineItemStub):
            def GetSourceStartTime(self):
                return start_time

            def GetSourceEndTime(self):
                return end_time

        params = {"source_start": self.SOURCE_START, "duration": 75}
        params.update(kwargs)
        return Timecoded(MediaPoolItemStub({"FPS": self.FPS}), **params)

    def test_source_end_stays_inside_the_clip(self):
        summary = _timeline_item_summary(self._item(), ("video", 1))
        # The bug reported 468800 — 44x the clip's own length.
        self.assertNotEqual(summary["source_end"], 468800)
        self.assertLess(summary["source_end"], self.CLIP_FRAMES)
        self.assertEqual(summary["source_end"], 3730)

    def test_the_two_frame_fields_can_be_differenced(self):
        summary = _timeline_item_summary(self._item(), ("video", 1))
        span = summary["source_end"] - summary["source_start"]
        # 75 record frames at 24 fps is 93.7 source frames at 29.97 — a plain
        # rate conversion with no retime.
        self.assertEqual(span, 93)

    def test_the_seconds_share_the_frames_origin(self):
        # Agreement is to within one frame, not to the decimal: the frame fields
        # are quantized to frame boundaries while the seconds keep the remainder.
        summary = _timeline_item_summary(self._item(), ("video", 1))
        self.assertLess(
            abs(summary["source_start_seconds"] * self.FPS - summary["source_start"]), 1.0)
        self.assertLess(
            abs(summary["source_end_seconds"] * self.FPS - summary["source_end"]), 1.0)
        # The reported seconds are no longer the raw TC-absolute readings.
        self.assertLess(summary["source_start_seconds"], self.START_TC_SECONDS)

    def test_the_seconds_span_is_preserved(self):
        # Rebasing shifts the origin; it must not change the clip's length.
        summary = _timeline_item_summary(self._item(), ("video", 1))
        self.assertAlmostEqual(
            summary["source_end_seconds"] - summary["source_start_seconds"],
            self.END_TIME - self.START_TIME, places=2)

    def test_zero_timecode_media_is_untouched(self):
        # The same item with the offset removed: the correction must be exactly
        # zero, or every existing consumer of zero-TC media moves under them.
        class ZeroTC(TimelineItemStub):
            def GetSourceStartTime(self):
                return 300 / 29.97

            def GetSourceEndTime(self):
                return 735 / 29.97

        summary = _timeline_item_summary(
            ZeroTC(MediaPoolItemStub({"FPS": 29.97}), source_start=300, duration=435),
            ("video", 1))
        self.assertEqual(summary["source_end"], 735)
        self.assertAlmostEqual(summary["source_start_seconds"], 300 / 29.97, places=3)

    def test_a_reader_disagreement_still_refuses_an_inverted_span(self):
        # End before start in TC space: fall back rather than emit a negative
        # span, exactly as on the uncalibrated path.
        item = self._item()
        item.GetSourceEndTime = lambda: self.START_TIME - 5.0
        summary = _timeline_item_summary(item, ("video", 1))
        self.assertGreater(summary["source_end"], summary["source_start"])


if __name__ == "__main__":
    unittest.main()
