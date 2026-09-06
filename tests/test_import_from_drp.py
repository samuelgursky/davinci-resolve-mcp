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
        self.assertEqual(containers[0]["name"], "MediaTemplate")  # E129: the pool's timeline name, not the first clip's
        self.assertTrue(containers[0]["entry"].startswith("SeqContainer/"))

    def test_extract_produces_importable_drt(self):
        """The importable-.drt recipe, measured by bisection on 19.1.3.7:
        keep project.xml + MediaPool/ + the SeqContainer at its ORIGINAL uuid
        path (renaming it imports an EMPTY timeline with no error), drop
        Gallery. Live-verified: extracts import with their clips intact."""
        with zipfile.ZipFile(TEMPLATE_DRP, "r") as zf:
            entry = _drp_seq_containers(zf)[0]["entry"]
            source_names = [n for n in zf.namelist() if not n.endswith("/")]
        out = tempfile.mktemp(suffix=".drt")
        try:
            _extract_seqcontainer_from_drp(TEMPLATE_DRP, entry, out)
            with zipfile.ZipFile(out, "r") as z:
                names = z.namelist()
            self.assertIn(entry, names, "SeqContainer must keep its original path")
            self.assertNotIn("Primary1/SeqContainer1.xml", names,
                             "the rename orphans the clips (items=0 on import)")
            self.assertIn("metadata.json", names)
            if "project.xml" in source_names:
                self.assertIn("project.xml", names)
            if any(n.startswith("MediaPool/") for n in source_names):
                self.assertTrue(any(n.startswith("MediaPool/") for n in names),
                                "MpFolder holds the Sm2Sequence/Sm2Timeline objects")
            self.assertNotIn("Gallery.xml", names)
        finally:
            if os.path.exists(out):
                os.unlink(out)

    def test_extract_drops_other_timelines_mpfolder_blocks(self):
        """A multi-timeline source: the non-target timeline's Sm2MpTimelineClip
        block must go, or it imports as a ghost empty timeline."""
        def container(seq_id):
            return (f'<?xml version="1.0"?><Sm2SequenceContainer DbId="c">'
                    f"<VideoTrackVec><Element><Sm2TiTrack DbId=\"t\">"
                    f"<Sequence>{seq_id}</Sequence></Sm2TiTrack></Element>"
                    f"</VideoTrackVec></Sm2SequenceContainer>")
        alpha_seq = "aaaaaaaa-1111-2222-3333-444444444444"
        beta_seq = "bbbbbbbb-1111-2222-3333-444444444444"
        mp = ("<Sm2MpFolder>"
              "<Element><Sm2MpTimelineClip DbId=\"a\"><Name>ALPHA</Name>"
              f"<Sm2Sequence DbId=\"{alpha_seq}\"><Id>{alpha_seq}</Id></Sm2Sequence>"
              "</Sm2MpTimelineClip></Element>"
              "<Element><Sm2MpTimelineClip DbId=\"b\"><Name>BETA</Name>"
              f"<Sm2Sequence DbId=\"{beta_seq}\"><Id>{beta_seq}</Id></Sm2Sequence>"
              "</Sm2MpTimelineClip></Element>"
              "</Sm2MpFolder>")
        src = tempfile.mktemp(suffix=".drp")
        out = tempfile.mktemp(suffix=".drt")
        try:
            with zipfile.ZipFile(src, "w") as z:
                z.writestr("project.xml", "<SM_Project/>")
                z.writestr("MediaPool/Master/MpFolder.xml", mp)
                z.writestr("SeqContainer/aaaa.xml", container(alpha_seq))
                z.writestr("SeqContainer/bbbb.xml", container(beta_seq))
                z.writestr("Gallery.xml", "<g/>")
            _extract_seqcontainer_from_drp(src, "SeqContainer/aaaa.xml", out)
            with zipfile.ZipFile(out, "r") as z:
                names = z.namelist()
                folder = z.read("MediaPool/Master/MpFolder.xml").decode()
            self.assertIn("SeqContainer/aaaa.xml", names)
            self.assertNotIn("SeqContainer/bbbb.xml", names)
            self.assertNotIn("Gallery.xml", names)
            self.assertIn("ALPHA", folder)
            self.assertNotIn("BETA", folder, "ghost timeline block must be removed")
        finally:
            for f in (src, out):
                if os.path.exists(f):
                    os.unlink(f)


class ImportFromDrpTests(unittest.TestCase):
    def test_missing_drp(self):
        res = _import_from_drp(None, None, {"drpPath": "/no/such.drp"})
        self.assertTrue(_is_error(res))
        self.assertIn("does not exist", _err_msg(res))

    def test_name_not_found_reports_available(self):
        res = _import_from_drp(None, None, {"drpPath": TEMPLATE_DRP, "timelineNames": ["No Such TL"]})
        self.assertTrue(_is_error(res))
        self.assertIn("not found", _err_msg(res))
        self.assertIn("MediaTemplate", _remediation(res))  # E129: the pool's timeline name, not the first clip's

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
        res = _import_from_drp(proj, mp, {"drpPath": TEMPLATE_DRP, "timelineNames": ["MediaTemplate"]})  # E129: the pool's timeline name, not the first clip's
        self.assertTrue(res.get("success"), res)
        self.assertEqual(res.get("selected"), 1)
        self.assertEqual(res.get("imported"), 1)
        row = res["results"][0]
        self.assertEqual(row.get("requested"), "MediaTemplate")  # E129: the pool's timeline name, not the first clip's
        self.assertTrue(row.get("success"))
        self.assertEqual(proj.GetTimelineCount(), 1)


if __name__ == "__main__":
    unittest.main()


class _NamedProject:
    """Minimal project stand-in: all the guard reads is the name."""

    def __init__(self, name):
        self._name = name

    def GetName(self):
        return self._name


class UnsavedProjectRefusalTests(unittest.TestCase):
    """U6 — importing into the never-saved default project is refused, not silently no-opped.

    Resolve accepts ImportTimelineFromFile on the never-saved 'Untitled Project', creates
    nothing, and reports no cause; the generic 'Resolve created no timeline' error that came
    back instead pointed at missing media and sanitize_media, which is the wrong road.
    """

    def _xml(self):
        fd, path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        return path

    def test_refuses_on_the_never_saved_untitled_project(self):
        path = self._xml()
        try:
            res = _import_timeline_checked(
                _NamedProject("Untitled Project"), None, {"path": path, "dry_run": True})
            self.assertTrue(_is_error(res))
            # The remediation must name the PROJECT STATE — that is the whole point.
            rem = _remediation(res)
            self.assertIn("project", rem.lower())
            self.assertTrue("save" in rem.lower() or "load" in rem.lower())
            # And it must NOT send the caller down the missing-media road.
            self.assertNotIn("sanitize_media", rem)
            self.assertIn("Untitled Project", _err_msg(res))
        finally:
            os.unlink(path)

    def test_refusal_is_hard__no_override_flag_reopens_it(self):
        # An override would reintroduce the silent no-op: the call cannot succeed either way.
        path = self._xml()
        try:
            for extra in ({"force": True}, {"allow_unsaved_project": True}, {"require_temp_path": False}):
                params = {"path": path, "dry_run": True}
                params.update(extra)
                res = _import_timeline_checked(_NamedProject("Untitled Project"), None, params)
                self.assertTrue(_is_error(res), f"must still refuse with {extra}")
        finally:
            os.unlink(path)

    def test_a_named_project_imports_with_nothing_else_changed(self):
        # Same file, same params — only the project name differs.
        path = self._xml()
        try:
            res = _import_timeline_checked(
                _NamedProject("A Named Project"), None, {"path": path, "dry_run": True})
            self.assertTrue(res.get("success"))
            self.assertTrue(res.get("would_import"))
        finally:
            os.unlink(path)

    def test_dated_untitled_projects_are_NOT_refused(self):
        # Closing a project on a populated database lands on 'Untitled Project <date>_<time>',
        # which is a real database project — measured on 19.1.3: imports into it succeed
        # (2 items / 2 linked). Refusing it would block a call that works.
        path = self._xml()
        try:
            res = _import_timeline_checked(
                _NamedProject("Untitled Project 2026-08-05_170228"), None, {"path": path, "dry_run": True})
            self.assertTrue(res.get("success"))
        finally:
            os.unlink(path)


class OtioRemediationTests(unittest.TestCase):
    """U18 — a .otio is JSON, so the XML sanitize path and its advice do not apply."""

    def test_sanitize_is_na_for_otio_and_the_file_is_imported_as_is(self):
        fd, path = tempfile.mkstemp(suffix=".otio")
        os.close(fd)
        try:
            res = _import_timeline_checked(
                None, None, {"path": path, "sanitize_media": True, "dry_run": True})
            self.assertTrue(res.get("success"))
            self.assertNotIn("sanitize", res)          # the XML rewrite never ran
            self.assertEqual(res.get("import_path"), path)  # imported as-is, not a copy
            self.assertIn("N/A", res.get("note", ""))
            self.assertIn("JSON", res.get("note", ""))
        finally:
            os.unlink(path)


class _NamedFakeProject(_FakeProject):
    def GetName(self):
        return "A Named Project"


class _RefusingMediaPool:
    """Resolve's no-timeline outcome: the call returns nothing and creates nothing."""

    def ImportTimelineFromFile(self, path, options):
        return None


class OtioNoTimelineRemediationTests(unittest.TestCase):
    def test_otio_failure_does_not_blame_missing_media_or_sanitize(self):
        fd, path = tempfile.mkstemp(suffix=".otio")
        os.close(fd)
        try:
            res = _import_timeline_checked(_NamedFakeProject(), _RefusingMediaPool(), {"path": path})
            self.assertTrue(_is_error(res))
            rem = _remediation(res)
            # The old advice was flatly wrong for .otio — the media is usually online and
            # sanitize_media cannot even parse a JSON file.
            self.assertNotIn("sanitize_media=True", rem)
            self.assertNotIn("generator clips", rem)
            # It names the real cause: the document's shape, and the frame origin.
            self.assertIn("Clip.2", rem)
            self.assertIn("media_references", rem)
            self.assertIn("timecode origin", rem)
            self.assertIn("EXPORT_OTIO", rem)  # how to get a known-good file to compare
        finally:
            os.unlink(path)

    def test_xml_failure_still_gets_the_sanitize_advice(self):
        # The XML road is unchanged — only .otio was being misdiagnosed.
        fd, path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        try:
            res = _import_timeline_checked(_NamedFakeProject(), _RefusingMediaPool(), {"path": path})
            self.assertTrue(_is_error(res))
            self.assertIn("sanitize_media=True", _remediation(res))
        finally:
            os.unlink(path)
