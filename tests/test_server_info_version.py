"""Tests that serverInfo.version reports the project version instead of the MCP SDK version.

Issue #243: FastMCP initializes the low-level Server without a version parameter,
causing Server.create_initialization_options() to default to the installed mcp
package version. The server must explicitly set _mcp_server.version = VERSION on
both the compound and granular FastMCP instances.
"""
import unittest


class ServerInfoVersionTests(unittest.TestCase):
    def test_compound_server_advertises_project_version(self):
        from src.server import mcp, VERSION

        self.assertTrue(hasattr(mcp, "_mcp_server"))
        self.assertEqual(mcp._mcp_server.version, VERSION)
        options = mcp._mcp_server.create_initialization_options()
        self.assertEqual(options.server_version, VERSION)

    def test_granular_server_advertises_project_version(self):
        from src.granular.common import mcp, VERSION

        self.assertTrue(hasattr(mcp, "_mcp_server"))
        self.assertEqual(mcp._mcp_server.version, VERSION)
        options = mcp._mcp_server.create_initialization_options()
        self.assertEqual(options.server_version, VERSION)


if __name__ == "__main__":
    unittest.main()
