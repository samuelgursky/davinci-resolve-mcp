"""Issue #325: an Online image sequence is not reported missing.

Resolve reports a sequence's File Path as `name.[0000-8999].jpeg`;
os.path.exists is False for that pattern, so the conform probe said
`file_exists: false` and detect_missing_media listed the clip for relink.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import src.server as server
from src.utils.media_paths import media_exists


class SequencePathTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="seq_paths_")
        self.addCleanup(shutil.rmtree, self.root, True)
        for frame in (0, 1, 2, 8999):
            open(os.path.join(self.root, f"Flowers_v2.{frame:04d}.jpeg"), "wb").close()

    def path(self, name):
        return os.path.join(self.root, name)

    def test_a_bracket_range_with_both_ends_on_disk_exists(self):
        exists, sequence = media_exists(self.path("Flowers_v2.[0000-8999].jpeg"))
        self.assertTrue(exists)
        self.assertEqual((sequence["first"], sequence["last"]), (0, 8999))

    def test_a_missing_end_frame_is_missing(self):
        exists, sequence = media_exists(self.path("Flowers_v2.[0000-9000].jpeg"))
        self.assertFalse(exists)
        self.assertTrue(sequence["first_exists"])
        self.assertFalse(sequence["last_exists"])

    def test_printf_and_hash_patterns_need_one_frame(self):
        self.assertTrue(media_exists(self.path("Flowers_v2.%04d.jpeg"))[0])
        self.assertTrue(media_exists(self.path("Flowers_v2.####.jpeg"))[0])
        self.assertFalse(media_exists(self.path("Other.%04d.jpeg"))[0])

    def test_plain_files_behave_as_before(self):
        self.assertEqual(media_exists(self.path("Flowers_v2.0001.jpeg")), (True, None))
        self.assertEqual(media_exists(self.path("nope.mov")), (False, None))
        self.assertEqual(media_exists(None), (False, None))

    def test_detect_missing_media_keeps_an_online_sequence_present(self):
        snapshot = {"tracks": {"video": {"tracks": [{"track_index": 1, "items": [{
            "timeline_item_id": "t1", "name": "Flowers",
            "file_path": self.path("Flowers_v2.[0000-8999].jpeg"), "media_status": "Online",
        }]}]}}}
        report = server._detect_missing_media_from_snapshot(snapshot)
        self.assertEqual(report["missing_count"], 0)


if __name__ == "__main__":
    unittest.main()
