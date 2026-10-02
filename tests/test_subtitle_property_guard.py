"""Impossible subtitle SetProperty calls must not archive or contact Resolve."""
import unittest
from unittest import mock

from src.utils import destructive_hook as hook


class SubtitlePropertyGuard(unittest.TestCase):
    def test_compound_rejects_before_state_lookup_or_archive(self):
        handler = mock.Mock()
        wrapped = hook.destructive_op("timeline_item")(handler)
        with mock.patch.object(hook, "is_destructive", side_effect=AssertionError("archive path reached")):
            result = wrapped("set_property", {"track_type": "subtitle", "key": "Text", "value": "Hello"})
        handler.assert_not_called()
        self.assertFalse(result["success"])
        self.assertFalse(result["_versioning"]["archived"])
        self.assertIn("write_captions", result["error"])

    def test_read_and_video_calls_still_reach_handler(self):
        handler = mock.Mock(return_value={"properties": {}})
        wrapped = hook.destructive_op("timeline_item")(handler)
        with mock.patch.object(hook, "is_destructive", return_value=False):
            wrapped("get_property", {"track_type": "subtitle"})
            wrapped("set_property", {"track_type": "video", "key": "Pan", "value": 0})
        self.assertEqual(handler.call_count, 2)

    def test_granular_refuses_before_item_lookup(self):
        from src.granular import timeline_item
        with mock.patch.object(timeline_item, "_get_timeline_item", side_effect=AssertionError("Resolve contacted")):
            # Unwrap only the audit decorator; exercise the actual handler.
            result = timeline_item.ti_set_property.__wrapped__("Text", "Hello", track_type="subtitle")
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
