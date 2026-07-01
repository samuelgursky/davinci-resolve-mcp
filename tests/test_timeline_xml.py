"""Unit tests for the FCP7/xmeml timeline sanitizer (src.utils.timeline_xml).

Pure parsing — no DaVinci Resolve connection required.
"""

import os
import tempfile
import unittest
import urllib.parse
import xml.etree.ElementTree as ET

from src.utils.timeline_xml import (
    analyze_timeline_xml,
    sanitize_timeline_xml,
    _pathurl_to_disk,
)


def _xmeml(present_path, missing_path):
    """Build an xmeml with one linked clip, one reference-by-id reuse of it, one
    missing-media clip, one generator (file w/o pathurl), and one no-file clip."""
    present_url = "file://localhost" + urllib.parse.quote(present_path)
    missing_url = "file://localhost" + urllib.parse.quote(missing_path)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
<sequence id="seq1">
<name>TEST_SEQ</name>
<rate><timebase>24</timebase><ntsc>FALSE</ntsc></rate>
<media>
<video>
<track>
<clipitem id="ci1"><name>good</name><start>0</start><end>100</end><in>0</in><out>100</out>
<file id="f1"><name>good.mov</name><pathurl>{present_url}</pathurl>
<duration>500</duration></file></clipitem>
<clipitem id="ci2"><name>good-reuse</name><start>100</start><end>200</end><in>0</in><out>100</out>
<file id="f1"/></clipitem>
<clipitem id="ci3"><name>missing.mov</name><start>200</start><end>300</end><in>0</in><out>100</out>
<file id="f2"><name>missing.mov</name><pathurl>{missing_url}</pathurl>
<duration>500</duration></file></clipitem>
<clipitem id="ci4"><name>Universal Counting Leader</name><start>300</start><end>400</end>
<file id="f3"><name>Slug</name><mediaSource>Slug</mediaSource></file></clipitem>
<clipitem id="ci5"><name>Title 1</name><start>400</start><end>500</end></clipitem>
</track>
</video>
<audio>
<track>
<clipitem id="ca1"><name>mix.wav</name><start>0</start><end>500</end><in>0</in><out>500</out>
<file id="f2"/></clipitem>
</track>
</audio>
</media>
</sequence>
</xmeml>
"""


class TimelineXmlSanitizeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="xmltest_")
        # a real present media file
        self.present = os.path.join(self.tmp, "good.mov")
        with open(self.present, "wb") as fh:
            fh.write(b"\x00" * 16)
        self.missing = os.path.join(self.tmp, "does_not_exist.mov")
        self.xml_path = os.path.join(self.tmp, "seq.xml")
        with open(self.xml_path, "w", encoding="utf-8") as fh:
            fh.write(_xmeml(self.present, self.missing))

    def test_pathurl_to_disk(self):
        self.assertEqual(_pathurl_to_disk("file://localhost/a%20b/c.mov"), "/a b/c.mov")
        self.assertEqual(_pathurl_to_disk("file:///a%20b/c.mov"), "/a b/c.mov")
        self.assertIsNone(_pathurl_to_disk(None))

    def test_analyze_counts(self):
        rep = analyze_timeline_xml(self.xml_path)
        self.assertEqual(rep["timeline_name"], "TEST_SEQ")
        # kept: ci1, ci2 (reuse of present file) -> 2 video
        self.assertEqual(rep["kept"], 2)
        # missing: ci3 (video) + ca1 (audio, reference to missing f2) -> 2
        self.assertEqual(rep["missing_media_count"], 2)
        # generators: ci4 (file w/o pathurl) + ci5 (no file) -> 2
        self.assertEqual(rep["generator_count"], 2)
        self.assertTrue(rep["needs_sanitize"])

    def test_sanitize_removes_offending_clips(self):
        res = sanitize_timeline_xml(self.xml_path, out_dir=self.tmp)
        self.assertTrue(os.path.exists(res["output_path"]))
        self.assertEqual(res["kept"], 2)
        self.assertEqual(res["removed_total"], 4)

        root = ET.fromstring(open(res["output_path"], encoding="utf-8").read())
        clip_ids = [ci.get("id") for ci in root.iter("clipitem")]
        # only the present-media clips survive
        self.assertEqual(set(clip_ids), {"ci1", "ci2"})
        # the reference-by-id reuse still resolves to the present file definition
        self.assertIn("f1", [f.get("id") for f in root.iter("file")])

    def test_sanitize_output_is_valid_xml_with_doctype(self):
        res = sanitize_timeline_xml(self.xml_path, out_dir=self.tmp)
        raw = open(res["output_path"], encoding="utf-8").read()
        self.assertIn("<!DOCTYPE xmeml>", raw)
        # parses without error
        ET.fromstring(raw)

    def test_clean_timeline_needs_no_sanitize(self):
        # XML where every clip points at present media
        clean = _xmeml(self.present, self.present).replace("does_not_exist", "good")
        p = os.path.join(self.tmp, "clean.xml")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(clean)
        rep = analyze_timeline_xml(p)
        self.assertEqual(rep["missing_media_count"], 0)

    def test_missing_sequence_raises(self):
        p = os.path.join(self.tmp, "bad.xml")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0"?><xmeml version="4"></xmeml>')
        with self.assertRaises(ValueError):
            analyze_timeline_xml(p)


if __name__ == "__main__":
    unittest.main()
