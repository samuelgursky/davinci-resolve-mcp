"""A tool-authored .drt uses a template schema Resolve's import refuses
(measured on Studio 19.1.3.7: a real export re-imports; the same archive
minus project.xml, or any archive with the flat authored container, does
not). The sniffer turns that refusal into a remediation that names the
actual cause instead of pointing at media."""
import io
import os
import tempfile
import unittest
import zipfile

from src.server import _drt_looks_tool_authored

REAL_STYLE = """<?xml version="1.0" encoding="UTF-8"?>
<!--DbAppVer="19.1.3.0007" DbPrjVer="14"-->
<Sm2SequenceContainer DbId="abc">
 <FieldsBlob/>
 <VideoTrackVec><Element><Sm2TiTrack DbId="t1"><Items>
  <Element><Sm2TiVideoClip DbId="c1"><Name>x.mp4</Name><Start>108000</Start></Sm2TiVideoClip></Element>
 </Items></Sm2TiTrack></Element></VideoTrackVec>
</Sm2SequenceContainer>
"""
AUTHORED_STYLE = """<?xml version="1.0" encoding="UTF-8"?>
<Sm2SequenceContainer DbId="abc">
  <Name>T</Name>
  <StartFrame>108000</StartFrame>
  <StartTC>01:00:00:00</StartTC>
</Sm2SequenceContainer>
"""


def _zip(entries):
    fd, path = tempfile.mkstemp(suffix=".drt")
    os.close(fd)
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return path


class AuthoredShapeSnifferTest(unittest.TestCase):
    def _check(self, entries):
        path = _zip(entries)
        self.addCleanup(os.unlink, path)
        return _drt_looks_tool_authored(path)

    def test_authored_flat_container_is_named(self):
        tell = self._check({"Primary1/SeqContainer1.xml": AUTHORED_STYLE})
        self.assertIn("<StartFrame>", tell)

    def test_authored_shape_wins_even_with_project_xml(self):
        tell = self._check({"Primary1/SeqContainer1.xml": AUTHORED_STYLE,
                            "project.xml": "<SM_Project/>"})
        self.assertIn("<StartFrame>", tell)

    def test_real_archive_is_not_flagged(self):
        tell = self._check({
            "project.xml": "<SM_Project/>",
            "SeqContainer/abc.xml": REAL_STYLE,
            "MediaPool/Master/MpFolder.xml": "<x/>",
        })
        self.assertIsNone(tell)

    def test_real_container_without_project_xml_is_flagged(self):
        tell = self._check({"SeqContainer/abc.xml": REAL_STYLE})
        self.assertEqual(tell, "no project.xml in the archive")

    def test_non_zip_returns_none(self):
        fd, path = tempfile.mkstemp()
        os.write(fd, b"not a zip")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        self.assertIsNone(_drt_looks_tool_authored(path))


if __name__ == "__main__":
    unittest.main()
