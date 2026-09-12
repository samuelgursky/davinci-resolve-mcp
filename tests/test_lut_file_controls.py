"""LUT file discovery and installation, in both published interfaces.

`graph set_lut` could already put a LUT on a node, but nothing answered which
LUTs exist, and nothing could install or remove one — while the same needs for
DCTL shaders were served by the `dctl` tool, in the same directory tree.

Writes must stay inside the namespaced MCP/ subfolder so stock and vendor LUTs
are never touched, and every listing must report the master-relative path that
Graph.SetLUT actually resolves.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

import src.server as compound
from src.granular import graph as granular
from src.utils import lut_files

IDENTITY_CUBE = """TITLE "test"
LUT_3D_SIZE 2
DOMAIN_MIN 0.0 0.0 0.0
DOMAIN_MAX 1.0 1.0 1.0
0.0 0.0 0.0
1.0 0.0 0.0
0.0 1.0 0.0
1.0 1.0 0.0
0.0 0.0 1.0
1.0 0.0 1.0
0.0 1.0 1.0
1.0 1.0 1.0
"""


class TempLutRoot(unittest.TestCase):
    """Every test runs against a throwaway master LUT root."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(lut_files, "master_lut_dir", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, relative, text=IDENTITY_CUBE):
        path = os.path.join(self.root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path


class PathSafetyTests(TempLutRoot):
    def test_traversal_and_absolute_paths_are_refused(self):
        for name in ("../escape.cube", "a/../../escape.cube", "/etc/passwd.cube",
                     "C:/win.cube", "./.././x.cube"):
            with self.subTest(name=name):
                with self.assertRaises(lut_files.LutPathError):
                    lut_files.resolve_writable(name)

    def test_non_lut_extensions_are_refused(self):
        for name in ("payload.sh", "notes.txt", "thing.py"):
            with self.subTest(name=name):
                with self.assertRaises(lut_files.LutPathError):
                    lut_files.normalize_relative(name)

    def test_missing_extension_defaults_to_cube(self):
        self.assertEqual(lut_files.normalize_relative("warm", default_ext=".cube"), "warm.cube")

    def test_every_documented_extension_is_accepted(self):
        for ext in lut_files.LUT_EXTENSIONS:
            with self.subTest(ext=ext):
                self.assertTrue(lut_files.normalize_relative(f"x{ext}").endswith(ext))

    def test_writes_resolve_inside_the_namespaced_subdir(self):
        absolute, relative = lut_files.resolve_writable("warm.cube")
        self.assertTrue(absolute.startswith(os.path.join(self.root, lut_files.WRITABLE_SUBDIR)))
        self.assertEqual(relative, f"{lut_files.WRITABLE_SUBDIR}/warm.cube")


class ListingTests(TempLutRoot):
    def test_listing_finds_stock_and_installed_and_marks_writability(self):
        self.write("Vendor/Stock.cube")
        self.write(f"{lut_files.WRITABLE_SUBDIR}/Mine.cube")
        out = lut_files.list_luts()
        by_path = {row["set_lut_path"]: row for row in out["luts"]}
        self.assertEqual(out["count"], 2)
        self.assertFalse(by_path["Vendor/Stock.cube"]["writable"])
        self.assertTrue(by_path[f"{lut_files.WRITABLE_SUBDIR}/Mine.cube"]["writable"])

    def test_set_lut_path_is_master_relative_with_forward_slashes(self):
        self.write("A/B/Deep.cube")
        out = lut_files.list_luts()
        self.assertEqual(out["luts"][0]["set_lut_path"], "A/B/Deep.cube")

    def test_non_lut_files_are_ignored(self):
        self.write("Vendor/Stock.cube")
        with open(os.path.join(self.root, "readme.txt"), "w", encoding="utf-8") as h:
            h.write("hi")
        self.assertEqual(lut_files.list_luts()["count"], 1)

    def test_missing_directory_reports_absence_rather_than_raising(self):
        out = lut_files.list_luts("NoSuchFolder")
        self.assertFalse(out["exists"])
        self.assertEqual(out["luts"], [])


class InstallRemoveTests(TempLutRoot):
    def test_install_writes_and_reports_the_set_lut_path(self):
        out = lut_files.install_lut("warm.cube", source=IDENTITY_CUBE)
        self.assertTrue(out["success"])
        self.assertEqual(out["set_lut_path"], f"{lut_files.WRITABLE_SUBDIR}/warm.cube")
        self.assertTrue(os.path.isfile(out["path"]))
        self.assertIn("refresh_luts", out["note"])

    def test_install_refuses_to_clobber_without_overwrite(self):
        lut_files.install_lut("warm.cube", source=IDENTITY_CUBE)
        with self.assertRaises(lut_files.LutPathError):
            lut_files.install_lut("warm.cube", source=IDENTITY_CUBE)
        out = lut_files.install_lut("warm.cube", source=IDENTITY_CUBE, overwrite=True)
        self.assertTrue(out["success"])

    def test_install_needs_exactly_one_source(self):
        with self.assertRaises(lut_files.LutPathError):
            lut_files.install_lut("warm.cube")
        with self.assertRaises(lut_files.LutPathError):
            lut_files.install_lut("warm.cube", source=IDENTITY_CUBE, source_path="/tmp/x.cube")

    def test_install_refuses_empty_content(self):
        with self.assertRaises(lut_files.LutPathError):
            lut_files.install_lut("warm.cube", source="   \n")

    def test_install_from_a_file_copies_it(self):
        source = self.write("Vendor/Stock.cube")
        out = lut_files.install_lut("copied.cube", source_path=source)
        with open(out["path"], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), IDENTITY_CUBE)

    def test_install_from_a_file_copies_a_binary_lut_byte_for_byte(self):
        blob = bytes(range(256)) * 4
        source = os.path.join(self.root, "Vendor", "Stock.olut")
        os.makedirs(os.path.dirname(source), exist_ok=True)
        with open(source, "wb") as handle:
            handle.write(blob)
        out = lut_files.install_lut("copied.olut", source_path=source)
        with open(out["path"], "rb") as handle:
            self.assertEqual(handle.read(), blob)

    def test_install_from_a_file_copies_a_cube_that_is_not_utf8(self):
        text = IDENTITY_CUBE.replace('TITLE "test"', 'TITLE "Lumière"')
        source = os.path.join(self.root, "Vendor", "Lumiere.cube")
        os.makedirs(os.path.dirname(source), exist_ok=True)
        with open(source, "wb") as handle:
            handle.write(text.encode("latin-1"))
        out = lut_files.install_lut("lumiere.cube", source_path=source)
        with open(out["path"], "rb") as handle:
            self.assertEqual(handle.read(), text.encode("latin-1"))

    def test_remove_only_touches_the_writable_subdir(self):
        self.write("Vendor/Stock.cube")
        with self.assertRaises(lut_files.LutPathError):
            lut_files.remove_lut("Stock.cube")
        self.assertTrue(os.path.isfile(os.path.join(self.root, "Vendor", "Stock.cube")))

    def test_remove_deletes_an_installed_lut(self):
        installed = lut_files.install_lut("warm.cube", source=IDENTITY_CUBE)
        out = lut_files.remove_lut("warm.cube")
        self.assertTrue(out["success"])
        self.assertFalse(os.path.exists(installed["path"]))


class ReadTests(TempLutRoot):
    def test_read_reports_shape_not_the_table(self):
        self.write("Vendor/Stock.cube")
        out = lut_files.read_lut_summary("Vendor/Stock.cube")
        self.assertTrue(out["parsed"])
        self.assertEqual(out["size"], 2)
        self.assertEqual(out["entries"], 8)
        self.assertNotIn("table", out)

    def test_non_cube_reports_size_only(self):
        self.write("Vendor/Old.3dl", text="0 0 0\n")
        out = lut_files.read_lut_summary("Vendor/Old.3dl")
        self.assertFalse(out["parsed"])

    def test_missing_file_refuses(self):
        with self.assertRaises(lut_files.LutPathError):
            lut_files.read_lut_summary("Nope.cube")


class AttenuateTests(TempLutRoot):
    def test_strength_is_bounded(self):
        self.write("Vendor/Stock.cube")
        for bad in (-0.1, 1.1, "loud"):
            with self.subTest(bad=bad):
                with self.assertRaises(lut_files.LutPathError):
                    lut_files.attenuate_lut("Vendor/Stock.cube", bad, "out.cube")

    def test_missing_source_refuses(self):
        with self.assertRaises(lut_files.LutPathError):
            lut_files.attenuate_lut("Nope.cube", 0.5, "out.cube")


class BothInterfacesTests(TempLutRoot):
    def test_list_matches_across_both_interfaces(self):
        self.write("Vendor/Stock.cube")
        self.write(f"{lut_files.WRITABLE_SUBDIR}/Mine.cube")
        c = compound.lut("list", {})
        g = granular.list_lut_files()
        self.assertEqual(c["count"], 2)
        self.assertEqual([r["set_lut_path"] for r in c["luts"]],
                         [r["set_lut_path"] for r in g["luts"]])

    def test_install_then_remove_round_trips_in_both_interfaces(self):
        c = compound.lut("install", {"name": "compound.cube", "source": IDENTITY_CUBE})
        g = granular.install_lut_file("granular.cube", source=IDENTITY_CUBE)
        self.assertTrue(c["success"])
        self.assertTrue(g["success"])
        self.assertTrue(compound.lut("remove", {"name": "compound.cube"})["success"])
        self.assertTrue(granular.remove_lut_file("granular.cube")["success"])

    def test_both_refuse_traversal(self):
        self.assertIn("error", compound.lut("install", {"name": "../evil.cube",
                                                        "source": IDENTITY_CUBE}))
        self.assertIn("error", granular.install_lut_file("../evil.cube", source=IDENTITY_CUBE))

    def test_both_refuse_removing_a_stock_lut(self):
        self.write("Vendor/Stock.cube")
        self.assertIn("error", compound.lut("remove", {"name": "Stock.cube"}))
        self.assertIn("error", granular.remove_lut_file("Stock.cube"))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "Vendor", "Stock.cube")))

    def test_neither_interface_generates_from_caller_code(self):
        for caps in (compound.lut("capabilities", {}), granular.get_lut_file_capabilities()):
            self.assertFalse(caps["generate_from_code"])
            self.assertIn("does not execute caller-supplied Python",
                          caps["generate_from_code_reason"])

    def test_compound_dry_run_writes_nothing(self):
        out = compound.lut("install", {"name": "dry.cube", "source": IDENTITY_CUBE,
                                       "dry_run": True})
        self.assertEqual(out.get("would_install"), "dry.cube")
        self.assertEqual(lut_files.list_luts()["count"], 0)

    def test_unknown_action_is_reported(self):
        self.assertIn("error", compound.lut("frobnicate", {}))


if __name__ == "__main__":
    unittest.main()
