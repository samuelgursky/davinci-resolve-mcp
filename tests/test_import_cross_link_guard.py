"""Cross-link guard on import_timeline_checked (the coarse-identity merge law).

Resolve merges pool media by a coarse identity across imports, so a clip can
silently relink to a DIFFERENT pre-existing file (measured on 19.1.3.7: two
files with near-identical identity blobs; the second file's clips played the
first file's picture, and item readback showed the wrong clip name). These
tests cover the offline halves: expected-path extraction from the archive and
the actual-vs-expected comparison.
"""
import os
import unittest
import zipfile

from src import server


def _archive(tmp, seqs):
    path = os.path.join(tmp, "t.drt")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("project.xml", "<SM_Project/>")
        for i, xml in enumerate(seqs):
            zf.writestr(f"SeqContainer/{i:08d}-aaaa-bbbb-cccc-dddddddddddd.xml", xml)
    return path


class ExpectedPathsTest(unittest.TestCase):
    def test_collects_unique_media_paths(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = _archive(tmp, [
                "<x><MediaFilePath>/m/a.mov</MediaFilePath>"
                "<MediaFilePath>/m/b.mov</MediaFilePath>"
                "<MediaFilePath>/m/a.mov</MediaFilePath></x>",
            ])
            self.assertEqual(server._drt_expected_media_paths(p), {"/m/a.mov", "/m/b.mov"})

    def test_none_when_no_paths_or_unreadable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = _archive(tmp, ["<x/>"])
            self.assertIsNone(server._drt_expected_media_paths(p))
            self.assertIsNone(server._drt_expected_media_paths(os.path.join(tmp, "missing.drt")))


class _Item:
    def __init__(self, fp):
        self._fp = fp

    def GetMediaPoolItem(self):
        return self if self._fp else None

    def GetClipProperty(self, key):
        return self._fp


class _Tl:
    def __init__(self, fps):
        self._fps = fps

    def GetTrackCount(self, tt):
        return 1 if tt == "video" else 0

    def GetItemListInTrack(self, tt, i):
        return [_Item(fp) for fp in self._fps]


class CrossLinkCheckTest(unittest.TestCase):
    def test_missing_expected_path_is_reported(self):
        tl = _Tl(["/m/a.mov", "/m/a.mov"])  # both items link to a.mov
        res = server._timeline_cross_link_check(tl, {"/m/a.mov", "/m/b.mov"})
        self.assertEqual(res["missing"], ["/m/b.mov"])
        self.assertEqual(res["actual"], ["/m/a.mov"])

    def test_clean_when_all_expected_present(self):
        tl = _Tl(["/m/a.mov", "/m/b.mov"])
        res = server._timeline_cross_link_check(tl, {"/m/a.mov", "/m/b.mov"})
        self.assertEqual(res["missing"], [])


if __name__ == "__main__":
    unittest.main()
