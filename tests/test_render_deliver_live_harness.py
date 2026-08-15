"""Regression coverage for the live Render/Deliver harness import boundary."""

import subprocess
import sys
import unittest
from pathlib import Path


class RenderDeliverLiveHarnessTest(unittest.TestCase):
    def test_mcp_stubs_cover_current_compound_server_imports(self):
        repo_root = Path(__file__).resolve().parents[1]
        harness_path = repo_root / "tests" / "live_render_deliver_validation.py"
        code = (
            "import importlib.util, sys; "
            f"spec = importlib.util.spec_from_file_location('live_harness', {str(harness_path)!r}); "
            "h = importlib.util.module_from_spec(spec); "
            "spec.loader.exec_module(h); "
            "h._install_mcp_stubs(); "
            "fastmcp = sys.modules['mcp.server.fastmcp']; "
            "assert all(hasattr(fastmcp.FastMCP(), name) "
            "for name in ('tool', 'resource', 'prompt')); "
            "assert hasattr(fastmcp, 'Context'); "
            "assert hasattr(fastmcp, 'Image'); "
            "assert hasattr(sys.modules['mcp.types'], 'ToolAnnotations'); "
            "import src.server"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
