"""The preset export tools report the file Resolve actually writes.

Resolve treats the export path of ExportRenderPreset / ExportBurnInPreset as a
folder and writes ``<presetName>.xml`` inside it (free 21.0.4.5). The tools
used to echo the path back as if it were the file, which the import tools then
could not read.
"""
import os
import shutil
import tempfile
import unittest

import src.granular.resolve_control as rc
import src.server as compound
from src.utils.preset_files import preset_export_file


class FolderExportingResolve:
    """Writes exports the way Resolve does: <path>/<name>.xml."""

    def __init__(self, succeed=True):
        self.succeed = succeed
        self.calls = []

    def _export(self, method, name, path):
        self.calls.append((method, name, path))
        if not self.succeed:
            return False
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, f"{name}.xml"), "w", encoding="utf-8") as fh:
            fh.write("<preset/>")
        return True

    def ExportRenderPreset(self, name, path):
        return self._export("ExportRenderPreset", name, path)

    def ExportBurnInPreset(self, name, path):
        return self._export("ExportBurnInPreset", name, path)


class _WithTmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="preset_export_")
        self.addCleanup(shutil.rmtree, self.tmp, True)


class PresetExportFileTest(unittest.TestCase):
    def test_the_file_is_inside_the_path(self):
        self.assertEqual(preset_export_file("/tmp/out", "Dailies"), os.path.join("/tmp/out", "Dailies.xml"))
        # A path that looks like a file is still a folder to Resolve.
        self.assertEqual(preset_export_file("/tmp/out/x.xml", "Dailies"),
                         os.path.join("/tmp/out/x.xml", "Dailies.xml"))


class ExactPathBuildTest(_WithTmp):
    """A build that writes the exact path it is given still gets a real file."""

    def test_an_exact_file_export_is_reported_as_itself(self):
        given = os.path.join(self.tmp, "exact.xml")
        with open(given, "w", encoding="utf-8") as fh:
            fh.write("<preset/>")
        self.assertEqual(preset_export_file(given, "Dailies"), given)

    def test_the_folder_layout_wins_when_both_could_apply(self):
        folder = os.path.join(self.tmp, "out")
        os.makedirs(folder)
        inside = os.path.join(folder, "Dailies.xml")
        with open(inside, "w", encoding="utf-8") as fh:
            fh.write("<preset/>")
        self.assertEqual(preset_export_file(folder, "Dailies"), inside)


class GranularExportTest(_WithTmp):
    def setUp(self):
        super().setUp()
        self.resolve = FolderExportingResolve()
        self._orig = rc.get_resolve
        rc.get_resolve = lambda: self.resolve
        self.addCleanup(setattr, rc, "get_resolve", self._orig)

    def test_both_tools_return_the_written_file(self):
        for tool, method in ((rc.export_render_preset, "ExportRenderPreset"),
                             (rc.export_burn_in_preset, "ExportBurnInPreset")):
            with self.subTest(tool=tool.__name__):
                folder = os.path.join(self.tmp, method, "given.xml")
                out = tool("Dailies TC", folder)
                self.assertTrue(out["success"])
                self.assertEqual(out["export_path"], folder)
                self.assertTrue(os.path.isfile(out["export_file"]), out)
                self.assertEqual(self.resolve.calls[-1], (method, "Dailies TC", folder))

    def test_a_failed_export_names_no_file(self):
        self.resolve.succeed = False
        for tool in (rc.export_render_preset, rc.export_burn_in_preset):
            with self.subTest(tool=tool.__name__):
                out = tool("Missing", self.tmp)
                self.assertFalse(out["success"])
                self.assertNotIn("export_file", out)


class CompoundExportTest(_WithTmp):
    def setUp(self):
        super().setUp()
        self.resolve = FolderExportingResolve()
        self._orig = compound.get_resolve
        compound.get_resolve = lambda: self.resolve
        self.addCleanup(setattr, compound, "get_resolve", self._orig)

    def test_both_export_actions_return_the_written_file(self):
        for action, method in (("export_render", "ExportRenderPreset"), ("export_burnin", "ExportBurnInPreset")):
            with self.subTest(action=action):
                folder = os.path.join(self.tmp, action)
                out = compound.render_presets(action, {"name": "Dailies", "path": folder})
                self.assertTrue(out["success"], out)
                self.assertTrue(os.path.isfile(out["file"]), out)
                self.assertEqual(self.resolve.calls[-1], (method, "Dailies", folder))

    def test_a_failed_export_names_no_file(self):
        self.resolve.succeed = False
        for action in ("export_render", "export_burnin"):
            with self.subTest(action=action):
                out = compound.render_presets(action, {"name": "Missing", "path": self.tmp})
                self.assertFalse(out["success"])
                self.assertNotIn("file", out)


if __name__ == "__main__":
    unittest.main()
