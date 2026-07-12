"""get_items / get_items_in_track validate their track selector (no KeyError)
and accept the 1-based index as either index or track_index."""
import unittest
from unittest import mock

import src.server as s


def _item(name="clip", uid="ti-1", start=0, end=100, duration=100):
    it = mock.Mock()
    it.GetName.return_value = name
    it.GetUniqueId.return_value = uid
    it.GetStart.return_value = start
    it.GetEnd.return_value = end
    it.GetDuration.return_value = duration
    return it


def _dispatch(action, params, track_items=()):
    tl = mock.Mock()
    tl.GetItemListInTrack.return_value = list(track_items)
    proj = mock.Mock()
    proj.GetCurrentTimeline.return_value = tl
    with mock.patch.object(s, "_check", return_value=(mock.Mock(), proj, None)):
        return s.timeline(action, params), tl


class GetItemsSelectorTest(unittest.TestCase):
    def test_get_items_returns_summary(self):
        out, tl = _dispatch("get_items", {"track_type": "video", "index": 1}, [_item()])
        self.assertEqual(out["items"], [{"name": "clip", "id": "ti-1", "start": 0, "end": 100, "duration": 100}])
        tl.GetItemListInTrack.assert_called_once_with("video", 1)

    def test_get_items_accepts_track_index_alias(self):
        out, tl = _dispatch("get_items", {"track_type": "video", "track_index": 2})
        tl.GetItemListInTrack.assert_called_once_with("video", 2)

    def test_get_items_missing_track_type_errors_without_crashing(self):
        out, _ = _dispatch("get_items", {"index": 1})
        self.assertIn("error", out)
        self.assertNotIn("items", out)

    def test_get_items_rejects_unknown_track_type(self):
        out, _ = _dispatch("get_items", {"track_type": "bogus", "index": 1})
        self.assertIn("error", out)

    def test_get_items_in_track_accepts_index_alias(self):
        out, tl = _dispatch("get_items_in_track", {"track_type": "audio", "index": 1})
        tl.GetItemListInTrack.assert_called_once_with("audio", 1)
        self.assertIn("items", out)

    def test_missing_index_error_names_both_aliases(self):
        from tests._error_envelope_helpers import err_message
        out, _ = _dispatch("get_items_in_track", {"track_type": "audio"})
        self.assertIn("track_index", err_message(out))


if __name__ == "__main__":
    unittest.main()
