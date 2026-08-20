"""Tests for keyed-param guards found during live cataloguing (2026-08-03).

- media_pool_item get_metadata (and sibling keyed getters): a list-valued `key`
  was passed straight to Resolve, which silently ignored it and returned the
  full dict. Now a list key returns just that subset; a bad list is rejected.
- media_pool delete_timelines: calling with `timeline_names` (or without
  `timeline_ids`) raised a bare KeyError('timeline_ids'). Now it's a clear
  error naming the expected parameter.
"""
import unittest
from unittest import mock

import src.server as s


class FakeClip:
    FULL = {"Description": "desc", "Keywords": "kw", "Scene": "s1"}

    def GetMetadata(self, key=""):
        return self.FULL if key == "" else self.FULL.get(key, "")


class GetMetadataListKeyTest(unittest.TestCase):
    def _call(self, params):
        mp = mock.Mock()
        with mock.patch.object(s, "_get_mp", return_value=(None, None, mp, None)), \
             mock.patch.object(s, "_find_clip", return_value=FakeClip()):
            return s.media_pool_item("get_metadata", params)

    def test_string_key_unchanged(self):
        out = self._call({"clip_id": "x", "key": "Description"})
        self.assertEqual(out["metadata"], "desc")

    def test_omitted_key_returns_full_dict(self):
        out = self._call({"clip_id": "x"})
        self.assertEqual(out["metadata"], FakeClip.FULL)

    def test_list_key_returns_subset(self):
        out = self._call({"clip_id": "x", "key": ["Description", "Scene"]})
        self.assertEqual(out["metadata"], {"Description": "desc", "Scene": "s1"})

    def test_list_key_missing_field_is_none(self):
        out = self._call({"clip_id": "x", "key": ["Description", "NoSuch"]})
        self.assertEqual(out["metadata"], {"Description": "desc", "NoSuch": None})

    def test_empty_list_rejected(self):
        out = self._call({"clip_id": "x", "key": []})
        self.assertIn("error", out)
        self.assertIn("key", out["error"]["message"])

    def test_non_string_list_rejected(self):
        out = self._call({"clip_id": "x", "key": ["Description", 7]})
        self.assertIn("error", out)


class DeleteTimelinesParamTest(unittest.TestCase):
    def _call(self, params):
        proj = mock.Mock()
        proj.GetTimelineCount.return_value = 0
        mp = mock.Mock()
        with mock.patch.object(s, "_get_mp", return_value=(None, proj, mp, None)):
            return s.media_pool("delete_timelines", params)

    def test_missing_timeline_ids_named_in_error(self):
        out = self._call({})
        self.assertIn("error", out)
        self.assertIn("timeline_ids", out["error"]["message"])

    def test_timeline_names_gets_explicit_hint(self):
        out = self._call({"timeline_names": ["Timeline 1"]})
        self.assertIn("error", out)
        self.assertIn("timeline_ids", out["error"]["message"])
        self.assertIn("timeline_names", out["error"]["message"])

    def test_non_list_rejected(self):
        out = self._call({"timeline_ids": "abc"})
        self.assertIn("error", out)
        self.assertIn("timeline_ids", out["error"]["message"])

    def test_valid_ids_pass_validation(self):
        # 0 timelines in the fake project, so passing validation lands on the
        # "No timelines found" lookup error, not the param error.
        out = self._call({"timeline_ids": ["some-id"]})
        self.assertIn("error", out)
        self.assertNotIn("timeline_ids", out["error"]["message"])


if __name__ == "__main__":
    unittest.main()
