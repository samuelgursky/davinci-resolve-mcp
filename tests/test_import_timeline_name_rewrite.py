"""Issue #171 — Resolve honours the sequence name inside an FCP7 XML over the
timelineName import option. The wrapper rewrites the internal name, and a
returned-existing timeline is an error, not success:true/created_new:false."""
import os
import tempfile
import unittest

from src.server import _rewrite_fcp7_sequence_name

FCP7 = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="5">
 <sequence id="sequence-1">
  <name>XML_TRIM_v001</name>
  <duration>300</duration>
  <media><video><track>
   <clipitem id="c1"><name>clip_one.mov</name></clipitem>
  </track></video></media>
 </sequence>
</xmeml>
"""


class RewriteSequenceNameTest(unittest.TestCase):
    def _write(self, text):
        fd, path = tempfile.mkstemp(suffix=".xml")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def test_rewrites_only_the_sequence_name(self):
        path = self._write(FCP7)
        out, changed, err = _rewrite_fcp7_sequence_name(path, "XML_TRIM_v002")
        self.assertIsNone(err)
        self.assertTrue(changed)
        self.addCleanup(os.unlink, out)
        text = open(out, encoding="utf-8").read()
        self.assertIn("<name>XML_TRIM_v002</name>", text)
        self.assertNotIn("XML_TRIM_v001", text)
        self.assertIn("<name>clip_one.mov</name>", text, "clip names must survive")
        self.assertIn("<!DOCTYPE xmeml>", text, "doctype must survive")

    def test_escapes_xml_specials_in_the_new_name(self):
        path = self._write(FCP7)
        out, changed, err = _rewrite_fcp7_sequence_name(path, "A<B & C")
        self.assertTrue(changed)
        self.addCleanup(os.unlink, out)
        self.assertIn("<name>A&lt;B &amp; C</name>", open(out, encoding="utf-8").read())

    def test_no_sequence_name_reports_unchanged(self):
        path = self._write("<xmeml><project><name>P</name></project></xmeml>")
        out, changed, err = _rewrite_fcp7_sequence_name(path, "NEW")
        self.assertIsNone(err)
        self.assertFalse(changed)
        self.assertIsNone(out)

    def test_original_file_is_untouched(self):
        path = self._write(FCP7)
        out, changed, _ = _rewrite_fcp7_sequence_name(path, "XML_TRIM_v002")
        self.addCleanup(os.unlink, out)
        self.assertIn("XML_TRIM_v001", open(path, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
