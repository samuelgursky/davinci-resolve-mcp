"""timeline.get_items classifies items (E113/E115).

GetItemListInTrack lists transitions as items. Measured on Studio 19.1.3.7:
an AUDIO cross-fade enumerates with an EMPTY name; a Solid Color generator and
a subtitle item return no MediaPoolItem and None from GetProperty() — exactly
like a transition. So the discriminator is geometry: a transition straddles a
cut (one neighbour ends inside its span, another starts inside it); a
generator owns its span; a clip has media; subtitle tracks are subtitles.
"""
import unittest

import src.server as server


class _Item:
    def __init__(self, name, start, end, media=None, raise_media=False):
        self._name, self._start, self._end, self._media, self._raise = name, start, end, media, raise_media

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return f"id-{self._name or 'blank'}-{self._start}"

    def GetStart(self):
        return self._start

    def GetEnd(self):
        return self._end

    def GetDuration(self):
        return self._end - self._start

    def GetMediaPoolItem(self):
        if self._raise:
            raise RuntimeError("api surprise")
        return self._media

    def GetProperty(self):
        return None  # measured: None for transitions, generators AND subtitles alike


def kinds(items, track_type="video"):
    return [d["kind"] for d in server._describe_track_items(items, track_type)]


class GetItemsKindTest(unittest.TestCase):
    def test_fades_timeline_measured_order(self):
        # E107_FADES V1 as Resolve enumerated it (record order, transitions interleaved).
        items = [
            _Item("Solid Color", 86400, 86412),
            _Item("Cross Dissolve", 86400, 86424),
            _Item("cut_src.mp4", 86412, 86508, media=object()),
            _Item("Cross Dissolve", 86496, 86520),
            _Item("white_src.mp4", 86508, 86604, media=object()),
            _Item("Cross Dissolve", 86592, 86616),
            _Item("Solid Color", 86604, 86616),
        ]
        self.assertEqual(kinds(items), ["generator", "transition", "clip", "transition", "clip", "transition", "generator"])

    def test_nameless_audio_cross_fade_is_a_transition_by_geometry(self):
        items = [_Item("cut_src.mp4", 86400, 86484, media=object()), _Item("", 86472, 86496), _Item("quiet_src.mp4", 86484, 86568, media=object())]
        self.assertEqual(kinds(items, "audio"), ["clip", "transition", "clip"])

    def test_lone_generator_and_subtitles(self):
        self.assertEqual(kinds([_Item("Solid Color", 86400, 86448)]), ["generator"])
        self.assertEqual(kinds([_Item("hello", 86400, 86448), _Item("world", 86448, 86496)], "subtitle"), ["subtitle", "subtitle"])

    def test_api_surprise_keeps_a_clip_a_clip(self):
        self.assertEqual(kinds([_Item("", 86400, 86424, raise_media=True)]), ["clip"])


if __name__ == "__main__":
    unittest.main()
