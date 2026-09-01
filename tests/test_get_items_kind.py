"""timeline.get_items classifies items (E113).

GetItemListInTrack lists transitions as items. A video Cross Dissolve enumerates
by name, but an AUDIO cross-fade enumerates with an EMPTY name (measured
2026-09-01, Studio 19.1.3.7), so the discriminator is: no MediaPoolItem AND an
empty GetProperty() → transition; no MediaPoolItem but transform keys →
generator; otherwise a clip. An API surprise never demotes a clip.
"""
import unittest

import src.server as server


class _Item:
    def __init__(self, name, media, props, raise_media=False):
        self._name, self._media, self._props, self._raise = name, media, props, raise_media

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return "id-" + (self._name or "blank")

    def GetStart(self):
        return 86400

    def GetEnd(self):
        return 86424

    def GetDuration(self):
        return 24

    def GetMediaPoolItem(self):
        if self._raise:
            raise RuntimeError("api surprise")
        return self._media

    def GetProperty(self):
        return self._props


class GetItemsKindTest(unittest.TestCase):
    def test_kinds(self):
        clip = server._describe_track_item(_Item("cut_src.mp4", object(), {"ZoomX": 1.0}))
        video_tr = server._describe_track_item(_Item("Cross Dissolve", None, {}))
        audio_tr = server._describe_track_item(_Item("", None, None))
        gen = server._describe_track_item(_Item("Solid Color", None, {"ZoomX": 1.0}))
        self.assertEqual([clip["kind"], video_tr["kind"], audio_tr["kind"], gen["kind"]], ["clip", "transition", "transition", "generator"])
        self.assertEqual(audio_tr["name"], "")
        self.assertEqual(clip["duration"], 24)

    def test_api_surprise_keeps_a_clip_a_clip(self):
        odd = server._describe_track_item(_Item("", None, {}, raise_media=True))
        self.assertEqual(odd["kind"], "clip")


if __name__ == "__main__":
    unittest.main()
