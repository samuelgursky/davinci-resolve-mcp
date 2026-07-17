"""Offline tests for src.utils.lut_paths (Graph.SetLUT master-dir relocation).

Covers the behavior verified live on Resolve Studio 21: SetLUT resolves LUTs
only against the master LUT dir, so a user-dir LUT must be relocated into a
namespaced subfolder of the master dir before it can be applied.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# Stub the Resolve module so importing does not require Resolve installed.
sys.modules.setdefault('DaVinciResolveScript', type(sys)('DaVinciResolveScript'))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils import lut_paths  # noqa: E402


class MasterLutDirTest(unittest.TestCase):
    def test_windows_uses_programdata_env(self):
        with patch.object(lut_paths.platform, "system", return_value="Windows"), \
                patch.dict(os.environ, {"PROGRAMDATA": r"D:\PD"}, clear=False):
            d = lut_paths.master_lut_dir()
        self.assertEqual(
            d,
            os.path.join(r"D:\PD", "Blackmagic Design",
                         "DaVinci Resolve", "Support", "LUT"),
        )

    def test_windows_default_programdata_has_no_double_backslash(self):
        env = {k: v for k, v in os.environ.items() if k != "PROGRAMDATA"}
        with patch.object(lut_paths.platform, "system", return_value="Windows"), \
                patch.dict(os.environ, env, clear=True):
            d = lut_paths.master_lut_dir()
        # Regression: the fallback must be C:\ProgramData, not C:\\ProgramData.
        self.assertNotIn("\\\\", d)
        self.assertTrue(d.startswith(r"C:\ProgramData"))

    def test_darwin_master_root(self):
        with patch.object(lut_paths.platform, "system", return_value="Darwin"):
            d = lut_paths.master_lut_dir()
        self.assertEqual(
            d,
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT",
        )

    def test_linux_falls_back_when_no_dir_present(self):
        with patch.object(lut_paths.platform, "system", return_value="Linux"), \
                patch.object(lut_paths.os.path, "isdir", return_value=False):
            d = lut_paths.master_lut_dir()
        self.assertEqual(d, "/opt/resolve/LUT")


class EnsureLutInMasterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.master = os.path.join(self.root, "master")
        self.user = os.path.join(self.root, "user")
        os.makedirs(self.master, exist_ok=True)
        os.makedirs(self.user, exist_ok=True)
        # Point the helper at our temp master + user dirs.
        self._patches = [
            patch.object(lut_paths, "master_lut_dir", return_value=self.master),
            patch.object(lut_paths, "_user_lut_dir", return_value=self.user),
        ]
        for p in self._patches:
            p.start()
        self.subdir = lut_paths.MASTER_LUT_RELOCATE_SUBDIR

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def _write(self, path, body="LUT_3D_SIZE 2\n"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return path

    def test_user_dir_lut_relocated_into_master_subdir(self):
        self._write(os.path.join(self.user, "Foo.cube"))
        rel = lut_paths.ensure_lut_in_master("Foo.cube")
        self.assertEqual(rel, f"{self.subdir}/Foo.cube")
        # Copied into the namespaced subfolder, not the master root.
        self.assertTrue(os.path.isfile(
            os.path.join(self.master, self.subdir, "Foo.cube")))
        self.assertFalse(os.path.isfile(os.path.join(self.master, "Foo.cube")))

    def test_absolute_path_relocated(self):
        src = self._write(os.path.join(self.root, "elsewhere", "Bar.cube"))
        rel = lut_paths.ensure_lut_in_master(src)
        self.assertEqual(rel, f"{self.subdir}/Bar.cube")
        self.assertTrue(os.path.isfile(
            os.path.join(self.master, self.subdir, "Bar.cube")))

    def test_does_not_clobber_stock_master_lut(self):
        # A stock LUT in the master ROOT with the same basename must survive.
        stock = self._write(os.path.join(self.master, "InstantC.cube"),
                            body="STOCK\n")
        self._write(os.path.join(self.user, "InstantC.cube"), body="USER\n")
        rel = lut_paths.ensure_lut_in_master("InstantC.cube")
        self.assertEqual(rel, f"{self.subdir}/InstantC.cube")
        with open(stock, encoding="utf-8") as f:
            self.assertEqual(f.read(), "STOCK\n")  # untouched
        with open(os.path.join(self.master, self.subdir, "InstantC.cube"),
                  encoding="utf-8") as f:
            self.assertEqual(f.read(), "USER\n")   # user copy staged separately

    def test_already_in_master_subdir_is_noop(self):
        dst = self._write(
            os.path.join(self.master, self.subdir, "Baz.cube"), body="ORIG\n")
        mtime_before = os.path.getmtime(dst)
        rel = lut_paths.ensure_lut_in_master(dst)
        self.assertEqual(rel, f"{self.subdir}/Baz.cube")
        # Same file => no copy, content and mtime preserved.
        self.assertEqual(os.path.getmtime(dst), mtime_before)
        with open(dst, encoding="utf-8") as f:
            self.assertEqual(f.read(), "ORIG\n")

    def test_missing_source_returns_none(self):
        self.assertIsNone(lut_paths.ensure_lut_in_master("Nope.cube"))

    def test_unwritable_master_returns_none(self):
        self._write(os.path.join(self.user, "Qux.cube"))
        with patch.object(lut_paths.os, "makedirs",
                          side_effect=PermissionError("denied")):
            self.assertIsNone(lut_paths.ensure_lut_in_master("Qux.cube"))


if __name__ == "__main__":
    unittest.main()
