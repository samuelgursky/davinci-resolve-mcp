import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src.server as s
from src.granular import resolve_211 as g


class Resolve211ReadCompletionTests(unittest.TestCase):
    def test_transcription_is_available_through_both_interfaces(self):
        calls = []
        full = {
            "language": "en",
            "segments": [{
                "start": "00:00:00:00", "end": "00:00:01:00", "text": "Hello",
                "words": [{"start": "00:00:00:00", "end": "00:00:01:00", "text": " Hello"}],
            }],
        }
        clip = SimpleNamespace(
            GetClipProperty=lambda key: "Transcribed" if key == "Transcription Status" else "Hello",
            GetTranscription=lambda nested: calls.append(nested) or full,
        )
        pool = SimpleNamespace(GetRootFolder=lambda: object())
        project = SimpleNamespace(GetMediaPool=lambda: pool)
        with patch.object(s, "_get_mp", return_value=(None, project, pool, None)), \
             patch.object(s, "_find_clip", return_value=clip), \
             patch.object(g, "get_current_project", return_value=(None, project)), \
             patch.object(g, "_find_clip_by_id", return_value=clip):
            compound = s.media_pool_item("get_transcription", {
                "clip_id": "clip-1", "include_words": True,
                "use_nested_clip_transcription": False,
            })
            granular = g.get_media_pool_item_transcription("clip-1", False)
        self.assertEqual(compound["source"], "get_transcription")
        self.assertEqual(compound["segments"], full["segments"])
        self.assertEqual(granular, {"transcription": full})
        self.assertEqual(calls, [False, False])

    def test_granular_transcription_rejects_bad_inputs_and_missing_method(self):
        self.assertIn("error", g.get_media_pool_item_transcription(""))
        self.assertIn("error", g.get_media_pool_item_transcription("clip", 1))
        pool = SimpleNamespace(GetRootFolder=lambda: object())
        project = SimpleNamespace(GetMediaPool=lambda: pool)
        clip = SimpleNamespace(GetTranscription=None)
        with patch.object(g, "get_current_project", return_value=(None, project)), \
             patch.object(g, "_find_clip_by_id", return_value=clip):
            self.assertIn("error", g.get_media_pool_item_transcription("clip"))

    def test_type_is_available_through_both_interfaces(self):
        item = SimpleNamespace(GetType=lambda: "video")
        with patch.object(s, "_get_item", return_value=(None, item, None)), \
             patch.object(g, "_get_timeline_item", return_value=(item, None)):
            self.assertEqual(s.timeline_item("get_type", {})["type"], "video")
            self.assertEqual(g.get_timeline_item_type(), {"type": "video"})

    def test_type_validation_and_missing_method(self):
        self.assertIn("error", g.get_timeline_item_type(track_index=0))
        item = SimpleNamespace(GetType=None)
        with patch.object(s, "_get_item", return_value=(None, item, None)), \
             patch.object(g, "_get_timeline_item", return_value=(item, None)):
            self.assertIn("error", s.timeline_item("get_type", {}))
            self.assertIn("error", g.get_timeline_item_type())


if __name__ == "__main__":
    unittest.main()
