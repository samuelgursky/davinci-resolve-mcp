"""
Offline coverage for the AAF/DRP/PrProj conform-ingest additions:

  * _import_timeline_checked: .prproj honest refuse; .aaf skips the XML sanitize
    path and reports a fuzzy-relink-N/A note (dry-run, no Resolve needed).
  * _drp_seq_containers / _extract_seqcontainer_from_drp: offline zip surgery.
  * _import_from_drp: selection (name/index/all), honest not-found error, dry-run,
    and the full extract→import glue against a fake Resolve.

The live AAF/DRP import into a running Resolve is inherently Resolve-dependent and
is NOT covered here — it needs a live session.
"""

import os
import tempfile
import unittest
import zipfile

from src.server import (
    _PRPROJ_REFUSAL,
    _binary_post_import_relink,
    _drp_seq_containers,
    _extract_seqcontainer_from_drp,
    _import_from_drp,
    _import_timeline_checked,
)

TEMPLATE_DRP = os.path.join(
    os.path.dirname(__file__), "..", "resolve-advanced", "vendor", "drp-format", "templates", "media-clip-h264.drp"
)


def _err_msg(res):
    """Pull the message out of an error envelope (flat or {'error': {...}})."""
    if "error" in res and isinstance(res["error"], dict):
        res = res["error"]
    return res.get("message", "")


def _remediation(res):
    if "error" in res and isinstance(res["error"], dict):
        res = res["error"]
    return res.get("remediation", "")


def _is_error(res):
    return not res.get("success")


class _FakeTimeline:
    def __init__(self, tid, name):
        self._id = tid
        self._name = name

    def GetUniqueId(self):
        return self._id

    def GetName(self):
        return self._name

    def GetTrackCount(self, _tt):
        return 0

    def GetItemListInTrack(self, _tt, _i):
        return []


class _FakeProject:
    def __init__(self):
        self._timelines = []

    def GetTimelineCount(self):
        return len(self._timelines)

    def GetTimelineByIndex(self, index):
        if 1 <= index <= len(self._timelines):
            return self._timelines[index - 1]
        return None


class _FakeMediaPool:
    def __init__(self, project):
        self._project = project
        self._n = 0

    def ImportTimelineFromFile(self, path, options):
        self._n += 1
        tl = _FakeTimeline(f"tl-{self._n}", os.path.basename(path))
        self._project._timelines.append(tl)
        return tl


class PrProjRefusalTests(unittest.TestCase):
    def test_import_prproj_is_refused_and_points_to_bridge(self):
        with tempfile.NamedTemporaryFile(suffix=".prproj", delete=False) as f:
            f.write(b"binary")
            path = f.name
        try:
            res = _import_timeline_checked(None, None, {"path": path})
            self.assertTrue(_is_error(res))
            msg = _err_msg(res)
            self.assertEqual(msg, _PRPROJ_REFUSAL)
            # No longer a dead-end refuse — it names the offline read + convert bridge.
            self.assertIn("convert_to_interchange", msg)
            self.assertIn("parse_interchange", msg)
        finally:
            os.unlink(path)


class _RelinkItem:
    def __init__(self, mpi):
        self._mpi = mpi

    def GetMediaPoolItem(self):
        return self._mpi


class _RelinkTimeline:
    """Fake timeline with N linked Media Pool Items on one video track."""

    def __init__(self, n=3):
        self._items = [_RelinkItem(object()) for _ in range(n)]

    def GetTrackCount(self, tt):
        return 1 if tt == "video" else 0

    def GetItemListInTrack(self, tt, i):
        return self._items if tt == "video" else []


class _RelinkMediaPool:
    def __init__(self):
        self.calls = []

    def RelinkClips(self, items, folder):
        self.calls.append((len(items), folder))
        return True


class BinaryRelinkParityTests(unittest.TestCase):
    def test_relink_calls_relinkclips_per_existing_root(self):
        tl = _RelinkTimeline(3)
        mp = _RelinkMediaPool()
        # one real dir, one bogus dir (must be filtered out)
        real = tempfile.mkdtemp()
        res = _binary_post_import_relink(tl, mp, [real, "/no/such/root"])
        self.assertTrue(res["attempted"])
        self.assertEqual(res["roots"], [real])  # bogus root filtered
        self.assertEqual(len(mp.calls), 1)
        self.assertEqual(mp.calls[0][0], 3)  # 3 media pool items
        self.assertEqual(mp.calls[0][1], real)

    def test_relink_noops_without_existing_roots(self):
        res = _binary_post_import_relink(_RelinkTimeline(2), _RelinkMediaPool(), ["/no/such"])
        self.assertFalse(res["attempted"])
        self.assertIn("root", res["reason"])


class AafImportPathTests(unittest.TestCase):
    def test_aaf_skips_sanitize_and_notes_relink_na(self):
        # Put the fake .aaf under the temp dir so the require_temp_path guard passes.
        fd, path = tempfile.mkstemp(suffix=".aaf")
        os.close(fd)
        try:
            res = _import_timeline_checked(
                None,
                None,
                {"path": path, "sanitize_media": True, "relink_search_roots": ["/vol/media"], "dry_run": True},
            )
            self.assertTrue(res.get("success"))
            self.assertTrue(res.get("would_import"))
            # sanitize path must NOT have run for a binary format...
            self.assertNotIn("sanitize", res)
            # ...and the note must explain fuzzy XML relink is N/A.
            self.assertIn("N/A", res.get("note", ""))
            self.assertEqual(res.get("import_path"), path)  # imported as-is, not a sanitized copy
        finally:
            os.unlink(path)


class DrpSeqContainerTests(unittest.TestCase):
    def test_enumerate_template_drp(self):
        with zipfile.ZipFile(TEMPLATE_DRP, "r") as zf:
            containers = _drp_seq_containers(zf)
        self.assertGreaterEqual(len(containers), 1)
        self.assertEqual(containers[0]["name"], "sample.mp4")
        self.assertTrue(containers[0]["entry"].startswith("SeqContainer/"))

    def test_extract_produces_minimal_drt(self):
        with zipfile.ZipFile(TEMPLATE_DRP, "r") as zf:
            entry = _drp_seq_containers(zf)[0]["entry"]
        out = tempfile.mktemp(suffix=".drt")
        try:
            _extract_seqcontainer_from_drp(TEMPLATE_DRP, entry, out)
            with zipfile.ZipFile(out, "r") as z:
                names = z.namelist()
            self.assertIn("Primary1/SeqContainer1.xml", names)
            self.assertIn("metadata.json", names)
            self.assertNotIn("project.xml", names)  # a .drt has no project shell
        finally:
            if os.path.exists(out):
                os.unlink(out)


class ImportFromDrpTests(unittest.TestCase):
    def test_missing_drp(self):
        res = _import_from_drp(None, None, {"drpPath": "/no/such.drp"})
        self.assertTrue(_is_error(res))
        self.assertIn("does not exist", _err_msg(res))

    def test_name_not_found_reports_available(self):
        res = _import_from_drp(None, None, {"drpPath": TEMPLATE_DRP, "timelineNames": ["No Such TL"]})
        self.assertTrue(_is_error(res))
        self.assertIn("not found", _err_msg(res))
        self.assertIn("sample.mp4", _remediation(res))

    def test_dry_run_selects_all(self):
        res = _import_from_drp(None, None, {"drpPath": TEMPLATE_DRP, "dry_run": True})
        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("dry_run"))
        self.assertEqual(res.get("selected"), 1)
        self.assertEqual(res.get("imported"), 0)  # dry run imports nothing
        self.assertTrue(res["results"][0].get("would_import"))
        self.assertTrue(os.path.basename(res["results"][0]["drt_path"]).endswith(".drt"))

    def test_full_extract_and_import_glue(self):
        proj = _FakeProject()
        mp = _FakeMediaPool(proj)
        res = _import_from_drp(proj, mp, {"drpPath": TEMPLATE_DRP, "timelineNames": ["sample.mp4"]})
        self.assertTrue(res.get("success"), res)
        self.assertEqual(res.get("selected"), 1)
        self.assertEqual(res.get("imported"), 1)
        row = res["results"][0]
        self.assertEqual(row.get("requested"), "sample.mp4")
        self.assertTrue(row.get("success"))
        self.assertEqual(proj.GetTimelineCount(), 1)


if __name__ == "__main__":
    unittest.main()
