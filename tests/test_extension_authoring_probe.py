import unittest

from src.server import (
    _extension_capabilities,
    _extension_template_matrix,
    _probe_dctl_lifecycle,
    _probe_fuse_lifecycle,
    _probe_script_lifecycle,
    _refresh_or_restart_required,
    _safe_install_extension,
)


class ExtensionAuthoringProbeTest(unittest.TestCase):
    def test_refresh_restart_classification(self):
        fuse = _refresh_or_restart_required({"extension_type": "fuse"})
        dctl_lut = _refresh_or_restart_required({"extension_type": "dctl", "category": "lut"})
        dctl_aces = _refresh_or_restart_required({"extension_type": "dctl", "category": "aces_idt"})
        script = _refresh_or_restart_required({"extension_type": "script", "category": "Utility"})

        self.assertTrue(fuse["restart_required"])
        self.assertTrue(dctl_lut["refresh_luts"])
        self.assertTrue(dctl_aces["restart_required"])
        self.assertFalse(script["restart_required"])

    def test_capabilities_include_markers_and_templates(self):
        caps = _extension_capabilities()

        self.assertEqual(caps["markers"]["fuse"], "@mcp-fuse")
        self.assertIn("color_matrix", caps["templates"]["fuse"])
        self.assertIn("transform", caps["templates"]["dctl"])
        self.assertIn("scaffold", caps["templates"]["script"])

    def test_safe_install_dry_run_requires_mcp_name(self):
        result = _safe_install_extension({
            "extension_type": "fuse",
            "name": "ClientFuse",
            "kind": "color_matrix",
            "dry_run": True,
        })

        self.assertIn("error", result)

    def test_safe_install_dry_run_generates_marked_fuse(self):
        result = _safe_install_extension({
            "extension_type": "fuse",
            "name": "_mcp_fuse_dry_run",
            "kind": "color_matrix",
            "dry_run": True,
        })

        self.assertTrue(result["success"])
        self.assertTrue(result["would_install"])

    def test_lifecycle_probes_are_dry_by_default(self):
        fuse = _probe_fuse_lifecycle({"name": "_mcp_fuse_probe"})
        dctl = _probe_dctl_lifecycle({"name": "_mcp_dctl_probe"})
        script = _probe_script_lifecycle({"name": "_mcp_script_probe", "language": "py"})

        self.assertTrue(fuse["has_marker"])
        self.assertTrue(dctl["has_marker"])
        self.assertTrue(script["has_marker"])
        self.assertNotIn("install", fuse)
        self.assertNotIn("install", dctl)
        self.assertNotIn("install", script)

    def test_template_matrix_covers_all_extension_types(self):
        matrix = _extension_template_matrix()

        self.assertGreaterEqual(len(matrix["fuse"]), 1)
        self.assertGreaterEqual(len(matrix["dctl"]), 1)
        self.assertGreaterEqual(len(matrix["script"]), 1)
        self.assertTrue(all("validation" in row or "error" in row for row in matrix["fuse"].values()))


if __name__ == "__main__":
    unittest.main()
