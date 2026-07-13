import unittest

from src.server import _variant_item_placement


class PlacedItemStub:
    """Timeline item that reports its own frame positions.

    record frames come from GetStart/GetEnd/GetDuration; the source frame comes
    from GetSourceStartFrame (falling back to GetLeftOffset).
    """

    def __init__(self, start=105, end=165, duration=60, source_start=72):
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


class NoDurationStub(PlacedItemStub):
    GetDuration = None  # method absent -> duration derived from end - start


class LeftOffsetStub:
    """No GetSourceStartFrame; source frame comes from GetLeftOffset."""

    def __init__(self, start=100, end=160, left_offset=50):
        self._start = start
        self._end = end
        self._left_offset = left_offset

    def GetStart(self):
        return self._start

    def GetEnd(self):
        return self._end

    def GetDuration(self):
        return self._end - self._start

    def GetLeftOffset(self):
        return self._left_offset


class RaisingStub:
    def GetStart(self):
        raise RuntimeError("no handle")

    def GetEnd(self):
        raise RuntimeError("no handle")


class VariantItemPlacementTest(unittest.TestCase):
    def test_reports_frames_from_the_item(self):
        placed = _variant_item_placement(PlacedItemStub(start=105, end=165, duration=60, source_start=72))
        self.assertEqual(
            placed,
            {"record_start": 105, "record_end": 165, "duration": 60, "source_start": 72},
        )

    def test_reports_item_duration_that_differs_from_the_span(self):
        # The item's reported duration is authoritative even when it does not
        # equal end - start (Resolve may place a clip shorter than the request).
        placed = _variant_item_placement(PlacedItemStub(start=100, end=250, duration=88))
        self.assertEqual(placed["duration"], 88)

    def test_derives_duration_when_get_duration_absent(self):
        placed = _variant_item_placement(NoDurationStub(start=100, end=160))
        self.assertEqual(placed["duration"], 60)

    def test_falls_back_to_left_offset_for_source_start(self):
        placed = _variant_item_placement(LeftOffsetStub(left_offset=50))
        self.assertEqual(placed["source_start"], 50)

    def test_absent_and_failing_readers_yield_none(self):
        self.assertEqual(
            _variant_item_placement(object()),
            {"record_start": None, "record_end": None, "duration": None, "source_start": None},
        )
        raising = _variant_item_placement(RaisingStub())
        self.assertIsNone(raising["record_start"])
        self.assertIsNone(raising["duration"])


if __name__ == "__main__":
    unittest.main()
