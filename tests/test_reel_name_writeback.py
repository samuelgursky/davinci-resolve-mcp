"""Issue #77 — 'Reel Name' writes return True but are silently dropped.

Resolve accepts SetClipProperty('Reel Name', ...) / SetMetadata('Reel Name', ...)
and returns True, but when the project derives reel names automatically the value
never persists. We read it back and refuse to report success on mismatch. These
tests exercise the verifier helpers directly and through the media_pool_item
dispatcher with a fake clip whose 'Reel Name' write is a no-op.
"""
import unittest
from unittest import mock

import src.server as s


class FakeClip:
    """A clip whose 'Reel Name' write silently no-ops (matches issue #77),
    while every other property writes and persists normally."""

    def __init__(self, drop_keys=("Reel Name",)):
        self.props = {}
        self.meta = {}
        self.drop_keys = set(drop_keys)

    def GetUniqueId(self):
        return "clip-1"

    def GetName(self):
        return "17001_C006.mov"

    # Clip properties -----------------------------------------------------
    def SetClipProperty(self, key, value):
        if key not in self.drop_keys:
            self.props[key] = value
        return True  # Resolve lies: True even for the dropped key

    def GetClipProperty(self, key=""):
        if key == "":
            return dict(self.props)
        return self.props.get(key, "")

    # Metadata ------------------------------------------------------------
    def SetMetadata(self, key_or_dict, value=None):
        items = key_or_dict.items() if isinstance(key_or_dict, dict) else [(key_or_dict, value)]
        for k, v in items:
            # 'Reel Name' is really a clip property; SetMetadata accepts it but
            # it lands nowhere observable (drop), like the live bug.
            if k not in self.drop_keys:
                self.meta[k] = v
        return True


class VerifierHelpers(unittest.TestCase):
    def test_persisted_write_returns_none(self):
        clip = FakeClip(drop_keys=())  # nothing dropped
        clip.SetClipProperty("Reel Name", "TOPDOWN-C006")
        self.assertIsNone(
            s._verify_clip_property_writeback(clip, "Reel Name", "TOPDOWN-C006")
        )

    def test_silent_revert_returns_failure(self):
        clip = FakeClip()
        clip.SetClipProperty("Reel Name", "TOPDOWN-C006")  # dropped
        fail = s._verify_clip_property_writeback(clip, "Reel Name", "TOPDOWN-C006")
        self.assertIsNotNone(fail)
        self.assertFalse(fail["success"])
        self.assertFalse(fail["verified"])
        self.assertEqual(fail["requested"], "TOPDOWN-C006")
        self.assertEqual(fail["actual"], "")
        self.assertIn("did not", fail["error"].lower())
        self.assertIn("Assist using reel names", fail["hint"])

    def test_unwatched_key_is_never_verified(self):
        clip = FakeClip(drop_keys=("Comments",))  # Comments dropped but unwatched
        self.assertIsNone(
            s._verify_clip_property_writeback(clip, "Comments", "hello")
        )

    def test_unreadable_does_not_contradict(self):
        clip = FakeClip()
        # GetClipProperty raises -> we can't read back -> don't override success
        with mock.patch.object(clip, "GetClipProperty", side_effect=RuntimeError):
            self.assertIsNone(
                s._verify_clip_property_writeback(clip, "Reel Name", "X")
            )

    def test_verify_writeback_batch_finds_dropped_key(self):
        clip = FakeClip()
        fail = s._verify_writeback(clip, {"Comments": "ok", "Reel Name": "X"})
        self.assertIsNotNone(fail)
        self.assertEqual(fail["key"], "Reel Name")


class DispatcherIntegration(unittest.TestCase):
    def _run(self, action, params, clip):
        fake_mp = mock.Mock()
        with mock.patch.object(s, "_get_mp", return_value=(None, None, fake_mp, None)), \
             mock.patch.object(s, "_find_clip", return_value=clip):
            return s.media_pool_item(action, params)

    def test_set_clip_property_reel_name_reports_failure(self):
        clip = FakeClip()
        res = self._run("set_clip_property",
                        {"clip_id": "clip-1", "key": "Reel Name", "value": "TOPDOWN-C006"},
                        clip)
        self.assertFalse(res["success"])
        self.assertFalse(res["verified"])
        self.assertIn("hint", res)

    def test_set_clip_property_normal_field_still_succeeds(self):
        clip = FakeClip()
        res = self._run("set_clip_property",
                        {"clip_id": "clip-1", "key": "Comments", "value": "hi"},
                        clip)
        self.assertTrue(res["success"])
        self.assertNotIn("verified", res)

    def test_set_metadata_dict_form_reel_name_fails(self):
        clip = FakeClip()
        res = self._run("set_metadata",
                        {"clip_id": "clip-1", "metadata": {"Reel Name": "FRONT-C003"}},
                        clip)
        self.assertFalse(res["success"])
        self.assertFalse(res["verified"])

    def test_set_metadata_keyvalue_form_reel_name_fails(self):
        clip = FakeClip()
        res = self._run("set_metadata",
                        {"clip_id": "clip-1", "key": "Reel Name", "value": "FRONT-C004"},
                        clip)
        self.assertFalse(res["success"])

    def test_normalize_metadata_marks_unpersisted(self):
        clip = FakeClip()
        fake_root = object()
        fake_mp = mock.Mock()
        fake_mp.GetRootFolder.return_value = fake_root
        with mock.patch.object(s, "_clips_from_params", return_value=(([clip], []), None)):
            res = s._normalize_metadata(None, fake_mp, {
                "clip_ids": ["clip-1"],
                "metadata": {"Reel Name": "TOPDOWN-C001"},
            })
        self.assertFalse(res["success"])
        row = res["results"][0]
        self.assertFalse(row["success"])
        self.assertEqual(row["unpersisted"], {"Reel Name": ""})


if __name__ == "__main__":
    unittest.main()
