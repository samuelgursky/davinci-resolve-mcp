import os
import tempfile
import unittest
from unittest.mock import patch

from src.server import (
    _gallery_capabilities,
    _grade_boundary_report,
    _grade_capabilities,
    _grade_item_snapshot,
    _grade_version_restore,
    _probe_color_node_graph,
    _safe_export_lut,
    _safe_set_cdl,
    _validate_cdl_payload,
)


class GraphStub:
    def __init__(self, nodes=1):
        self.nodes = nodes

    def GetNumNodes(self):
        return self.nodes

    def GetLUT(self, node_index):
        return "No LUT"

    def GetNodeCacheMode(self, node_index):
        return 0

    def GetNodeLabel(self, node_index):
        return f"Node {node_index}"

    def GetToolsInNode(self, node_index):
        return {}

    def ApplyGradeFromDRX(self, path, grade_mode):
        return True


class ColorGroupStub:
    def __init__(self, name="Look Group"):
        self.name = name

    def GetName(self):
        return self.name

    def GetPreClipNodeGraph(self):
        return GraphStub()

    def GetPostClipNodeGraph(self):
        return GraphStub()


class GalleryStub:
    def __init__(self):
        self.albums = [object()]
        self.power = [object()]

    def GetGalleryStillAlbums(self):
        return self.albums

    def GetGalleryPowerGradeAlbums(self):
        return self.power

    def GetAlbumName(self, album):
        return "Album"

    def GetCurrentStillAlbum(self):
        return self.albums[0]

    def SetCurrentStillAlbum(self, album):
        return True

    def CreateGalleryStillAlbum(self):
        return object()

    def CreateGalleryPowerGradeAlbum(self):
        return object()


class ProjectStub:
    def __init__(self):
        self.gallery = GalleryStub()
        self.groups = [ColorGroupStub()]

    def GetGallery(self):
        return self.gallery

    def GetColorGroupsList(self):
        return self.groups

    def AddColorGroup(self, name):
        group = ColorGroupStub(name)
        self.groups.append(group)
        return group

    def DeleteColorGroup(self, group):
        return True


class ItemStub:
    def __init__(self):
        self.cdl_calls = []
        self.lut_exports = []

    def GetName(self):
        return "Color Clip"

    def GetUniqueId(self):
        return "item-1"

    def GetNodeGraph(self, *args):
        return GraphStub(nodes=2)

    def GetCurrentVersion(self):
        return {"versionName": "Default"}

    def GetVersionNameList(self, version_type):
        return ["Default", "Look"] if version_type == 0 else []

    def LoadVersionByName(self, name, version_type):
        return name == "Look"

    def GetColorGroup(self):
        return None

    def GetIsColorOutputCacheEnabled(self):
        return False

    def GetIsFusionOutputCacheEnabled(self):
        return False

    def SetCDL(self, cdl):
        self.cdl_calls.append(cdl)
        return True

    def ExportLUT(self, export_type, path):
        self.lut_exports.append({"type": export_type, "path": path})
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("LUT")
        return True


class ColorGradeProbeTest(unittest.TestCase):
    def test_validate_cdl_payload_normalizes_numeric_triplets(self):
        validation, err = _validate_cdl_payload(
            {
                "NodeIndex": "1",
                "Slope": [1.1, 1.0, 0.9],
                "Offset": "0.0 0.0 0.0",
                "Power": [1, 1, 1],
                "Saturation": "0.8",
            }
        )

        self.assertIsNone(err)
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["cdl"]["NodeIndex"], 1)
        self.assertEqual(validation["cdl"]["Offset"], [0.0, 0.0, 0.0])

    def test_safe_set_cdl_dry_run_does_not_mutate(self):
        item = ItemStub()
        result = _safe_set_cdl(
            item,
            {
                "dry_run": True,
                "cdl": {
                    "NodeIndex": 1,
                    "Slope": [1.0, 1.0, 1.0],
                    "Offset": [0.0, 0.0, 0.0],
                    "Power": [1.0, 1.0, 1.0],
                    "Saturation": 1.0,
                },
            },
        )

        self.assertTrue(result["success"])
        self.assertEqual(item.cdl_calls, [])

    def test_grade_item_snapshot_includes_node_graph_and_versions(self):
        snapshot = _grade_item_snapshot(ItemStub(), ProjectStub())

        self.assertEqual(snapshot["name"], "Color Clip")
        self.assertEqual(snapshot["node_graph"]["num_nodes"], 2)
        self.assertIn("Look", snapshot["versions"]["local"])

    def test_probe_color_node_graph_reads_group_source(self):
        result = _probe_color_node_graph(
            ProjectStub(),
            ItemStub(),
            {"source": "color_group_pre", "group_name": "Look Group"},
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["source"], "color_group_pre")

    def test_safe_export_lut_requires_temp_path(self):
        result = _safe_export_lut(ItemStub(), {"path": os.path.join(os.getcwd(), "look.cube")})

        self.assertIn("error", result)
        self.assertIn("system temp", (result["error"].get("message","") if isinstance(result["error"], dict) else result["error"]))

    def test_safe_export_lut_writes_temp_file(self):
        path = os.path.join(tempfile.mkdtemp(), "look.cube")
        with patch("src.server.get_resolve", return_value=None):
            result = _safe_export_lut(ItemStub(), {"path": path, "type": 33})

        self.assertTrue(result["success"])
        self.assertTrue(result["file_exists"])
        self.assertGreater(result["size"], 0)

    def test_grade_version_restore_dry_run_checks_name(self):
        result = _grade_version_restore(ItemStub(), {"name": "Look", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertEqual(result["would_load"], "Look")

    def test_capability_reports_include_gallery_and_boundaries(self):
        project = ProjectStub()
        item = ItemStub()

        self.assertTrue(_grade_capabilities(item, project)["gallery_available"])
        self.assertTrue(_gallery_capabilities(project)["available"])
        self.assertIn("color_groups", _grade_boundary_report(project, item, {"include_timeline_graph": False}))


if __name__ == "__main__":
    unittest.main()
