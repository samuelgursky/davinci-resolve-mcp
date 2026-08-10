"""Guard for the audio source-frame-rate trap.

A timeline item's source frames are counted in the MEDIA's frame rate, not the
timeline's, and a WAV carries no native rate — Resolve reports 24 for it. Read
back at the timeline rate, a WAV offset lands minutes from the real position in
the file, and nothing errors: probe derives source_end as
source_start + timeline_duration, so the pair stays self-consistent whatever
rate the caller assumes (api_truth "GetSourceStartFrame on an AUDIO item",
measured on Studio 21.0.3.7).

Documentation alone cannot stop that — it only helps a caller who thinks to look
it up. These tests pin the guard that makes it unmissable: every summary carries
source_fps and the seconds derived with it, so the frame number always arrives
with its unit attached.
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
        self.assertEqual(summary["source_end_seconds"], round((56871 + 435) / 24.0, 3))

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


if __name__ == "__main__":
    unittest.main()
