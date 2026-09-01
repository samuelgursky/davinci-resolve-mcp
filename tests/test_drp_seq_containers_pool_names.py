"""DRP/DRT container listing names sequences from the pool (E129).

A SeqContainer XML carries no timeline name — its first <Name> is the first
clip's — so `_drp_seq_containers` called Resolve's compound-timeline export
"cut_src.mp4" / "white_src.mp4" and offered its inner compound containers as
timelines. The pool's Sm2MpTimelineClip / Sm2MpCompoundClip embed the
Sm2Sequence each container's <Sequence> names.
"""
import os
import unittest
import zipfile

import src.server as server

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(REPO, "resolve-advanced", "test", "fixtures", "E127_resolve_nested_export.drt")
TEMPLATE = os.path.join(REPO, "resolve-advanced", "vendor", "drp-format", "templates", "media-clip-h264.drp")


class DrpSeqContainersPoolNamesTest(unittest.TestCase):
    def test_resolve_export_names_and_kinds_come_from_the_pool(self):
        with zipfile.ZipFile(FIXTURE) as zf:
            rows = server._drp_seq_containers(zf)
        self.assertEqual([(r["name"], r["kind"]) for r in rows], [("E57_IN", "compound"), ("E57_OUT", "compound"), ("E57_NESTED", "timeline")])
        self.assertEqual([r["index"] for r in rows], [0, 1, 2])

    def test_template_project_keeps_its_timeline_name(self):
        with zipfile.ZipFile(TEMPLATE) as zf:
            rows = server._drp_seq_containers(zf)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["name"], rows[0]["kind"]), ("MediaTemplate", "timeline"))


if __name__ == "__main__":
    unittest.main()
