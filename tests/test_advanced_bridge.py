"""Control-panel → advanced-server bridge (read-only): guards + payload shapes."""
import shutil
import unittest
from unittest import mock

from src.analysis_dashboard import (
    _advanced_capabilities_payload,
    _advanced_lineage_payload,
    _advanced_root,
    _dashboard_doc,
    _run_advanced_bridge,
    DOC_SOURCES,
)

HAVE_NODE = shutil.which("node") is not None


class LineageGuards(unittest.TestCase):
    def test_write_ops_refused(self):
        # The bridge is a read-only allowlist — ingest/QC mutations stay with MCP tools.
        for op in ("ingest_xml", "ingest_live", "rollback_plan", "qc", "write"):
            result = _advanced_lineage_payload(op, {"db": "/tmp/x.db"})
            self.assertFalse(result["success"], op)
            self.assertIn("unknown lineage op", result["error"])

    def test_db_required(self):
        result = _advanced_lineage_payload("list", {})
        self.assertFalse(result["success"])
        self.assertIn("required", result["error"])

    def test_missing_db_is_refused_not_created(self):
        # openStore would CREATE an empty sqlite file — the panel must never do that.
        result = _advanced_lineage_payload("list", {"db": "/nonexistent/dir/lineage.db"})
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])


class BridgeRuntime(unittest.TestCase):
    def test_missing_node_is_graceful(self):
        with mock.patch("shutil.which", return_value=None):
            result = _run_advanced_bridge("capabilities", "get")
        self.assertFalse(result["success"])
        self.assertIn("Node.js not found", result["error"])
        self.assertIn("hint", result)

    def test_unknown_surface_from_bridge(self):
        if not HAVE_NODE:
            self.skipTest("node not on PATH")
        result = _run_advanced_bridge("nope", "x")
        self.assertFalse(result["success"])
        self.assertIn("unknown surface", result["error"])

    @unittest.skipUnless(HAVE_NODE, "node not on PATH")
    def test_capabilities_end_to_end(self):
        payload = _advanced_capabilities_payload()
        self.assertTrue(payload["success"], payload)
        result = payload["result"]
        self.assertIn("core", result)
        for dep in ("ffmpeg", "sharp", "better-sqlite3"):
            self.assertIn(dep, result["optional"])
        self.assertEqual(payload["root"], _advanced_root())


class DocsRegistry(unittest.TestCase):
    def test_advanced_server_doc_registered_and_loads(self):
        self.assertIn("advanced-server", DOC_SOURCES)
        payload = _dashboard_doc("advanced-server")
        self.assertTrue(payload["success"], payload)
        self.assertIn("davinci-resolve-advanced-mcp", payload["content"])


if __name__ == "__main__":
    unittest.main()
