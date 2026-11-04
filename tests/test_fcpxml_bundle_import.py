"""Issue #324: importing the export's own FCPXML bundle `path` works.

Resolve 21.1 exports FCPXML as a directory (`scratch.fcpxml/Info.fcpxml`),
and `export_timeline_checked` returns the directory as `path`. Importing that
`path` failed with "Permission denied" when the rename pass opened the
directory as a file; only `primary_file` worked.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock

import src.server as server

_FCPXML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources><format id="r1" frameDuration="1/24s" width="1920" height="1080"/></resources>
  <library><event name="E"><project name="Exported">
    <sequence format="r1" duration="24/24s" tcStart="0s"><spine/></sequence>
  </project></event></library>
</fcpxml>
"""


class FcpxmlBundleImportTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fcpxml_bundle_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.bundle = os.path.join(self.root, "scratch.fcpxml")
        os.makedirs(self.bundle)
        self.info = os.path.join(self.bundle, "Info.fcpxml")
        with open(self.info, "w", encoding="utf-8") as fh:
            fh.write(_FCPXML)

    def test_the_bundle_resolves_to_its_document(self):
        self.assertEqual(server._fcpxml_bundle_document(self.bundle), self.info)
        self.assertEqual(server._fcpxml_bundle_document(self.bundle + os.sep), self.info)

    def test_a_plain_file_or_other_directory_is_left_alone(self):
        self.assertIsNone(server._fcpxml_bundle_document(self.info))
        self.assertIsNone(server._fcpxml_bundle_document(self.root))

    def test_import_accepts_the_bundle_path_and_renames_inside_it(self):
        proj = mock.Mock()
        proj.GetName.return_value = "Saved Project"
        result = server._import_timeline_checked(
            proj, mock.Mock(),
            {"path": self.bundle, "timeline_name": "rt", "dry_run": True, "import_source_clips": False},
        )
        self.assertNotIn("error", result, result)
        self.assertTrue(result["would_import"])
        self.assertTrue(str(result["path"]).endswith("Info.fcpxml"))


if __name__ == "__main__":
    unittest.main()
