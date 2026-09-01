"""The import_from_drp extractor keeps a timeline's compound containers (E130).

drt.extract_from_drp learned this in E45 (a dropped inner container ships a
compound that imports and reads back but is hollow); the Python route behind
timeline.import_from_drp still dropped every container but the chosen one.
Fixture = Resolve 19.1.3.7's EXPORT_DRT of the depth-2 nested timeline.
"""
import json
import os
import tempfile
import unittest
import zipfile

import src.server as server

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(REPO, "resolve-advanced", "test", "fixtures", "E127_resolve_nested_export.drt")
TEMPLATE = os.path.join(REPO, "resolve-advanced", "vendor", "drp-format", "templates", "media-clip-h264.drp")


def _extract(src, name):
    with zipfile.ZipFile(src) as zf:
        rows = server._drp_seq_containers(zf)
    entry = next(r["entry"] for r in rows if r["name"] == name)
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "x.drt")
        server._extract_seqcontainer_from_drp(src, entry, out)
        with zipfile.ZipFile(out) as zf:
            kept = sorted(n for n in zf.namelist() if server._SEQ_CONTAINER_RE.search(n))
            meta = json.loads(zf.read("metadata.json"))
            with zipfile.ZipFile(src) as srczf:
                names = {r["entry"]: r["name"] for r in server._drp_seq_containers(srczf)}
    return sorted(names[k] for k in kept), meta


class ExtractKeepsCompoundsTest(unittest.TestCase):
    def test_a_timeline_keeps_its_compounds_recursively(self):
        kept, meta = _extract(FIXTURE, "E57_NESTED")
        self.assertEqual(kept, ["E57_IN", "E57_NESTED", "E57_OUT"])
        self.assertEqual(len(meta["keptSeqContainers"]), 3)

    def test_a_compound_keeps_only_what_it_nests(self):
        kept, _ = _extract(FIXTURE, "E57_OUT")
        self.assertEqual(kept, ["E57_IN", "E57_OUT"])

    def test_a_plain_project_keeps_one_container(self):
        kept, meta = _extract(TEMPLATE, "MediaTemplate")
        self.assertEqual(kept, ["MediaTemplate"])
        self.assertEqual(meta["keptSeqContainers"], [meta["sourceSeqContainer"]])


if __name__ == "__main__":
    unittest.main()
