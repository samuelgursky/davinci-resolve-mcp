"""E1 contract test — MCP resources expose read-only state without a tool turn.

See local/design/agentic-flow-improvements-gameplan-2.md §3 task E1.

These tests verify the resource handlers in isolation (the underlying
callable bound to the FastMCP resource URI). We do NOT exercise the MCP
transport here — that's the host-side spike documented in the gameplan §4.
"""
import unittest
from unittest.mock import patch


class McpResourcesTest(unittest.TestCase):
    def test_mcp_version_resource_returns_version_dict(self):
        from src.server import _resource_mcp_version, VERSION
        out = _resource_mcp_version()
        self.assertIn("version", out)
        self.assertEqual(out["version"], VERSION)

    def test_resolve_connection_resource_handles_no_resolve(self):
        """When Resolve isn't running, resource returns {connected: False}, NOT an error envelope."""
        from src.server import _resource_resolve_connection
        with patch("src.server.get_resolve", return_value=None):
            out = _resource_resolve_connection()
            self.assertFalse(out["connected"])

    def test_current_project_resource_handles_no_project(self):
        from src.server import _resource_current_project
        with patch("src.server.get_resolve", return_value=None):
            out = _resource_current_project()
            self.assertFalse(out["open"])

    def test_current_timeline_resource_handles_no_timeline(self):
        from src.server import _resource_current_timeline
        with patch("src.server.get_resolve", return_value=None):
            out = _resource_current_timeline()
            self.assertFalse(out["open"])

    def test_caps_preset_resource_returns_active_preset(self):
        from src.server import _resource_caps_preset
        out = _resource_caps_preset()
        self.assertIn("preset", out)
        self.assertIn("effective_caps", out)
        self.assertIn("presets_available", out)
        # presets_available is a dict {preset_name: caps_dict} keyed by name.
        self.assertIsInstance(out["presets_available"], dict)
        self.assertIn("minimal", out["presets_available"])

    def test_recent_reports_resource_returns_list_shape(self):
        from src.server import _resource_recent_reports
        out = _resource_recent_reports()
        self.assertIn("entries", out)
        self.assertIsInstance(out["entries"], list)
        # At most 20 entries — registry may be empty or large; we cap the surface.
        self.assertLessEqual(len(out["entries"]), 20)

    def test_installed_tools_resource_returns_capabilities_shape(self):
        from src.server import _resource_installed_tools
        out = _resource_installed_tools()
        # Capabilities shape: tools/transcription/vision dicts.
        self.assertIn("tools", out)

    def test_install_guidance_resource_returns_missing_dict(self):
        from src.server import _resource_install_guidance
        out = _resource_install_guidance()
        self.assertIn("missing", out)

    def test_resource_exception_returns_error_envelope_not_raise(self):
        """The _safe_resource wrapper must convert exceptions into structured errors."""
        from src.server import _safe_resource

        @_safe_resource
        def _boom():
            raise RuntimeError("simulated failure")

        out = _boom()
        self.assertIn("error", out)
        self.assertEqual(out["error"]["code"], "RESOURCE_FAILED")
        self.assertEqual(out["error"]["category"], "resolve_api_failed")
        self.assertTrue(out["error"]["retryable"])
        self.assertIn("simulated failure", out["error"]["message"])


class McpResourceRegistrationTest(unittest.TestCase):
    def test_resources_registered_with_fastmcp_instance(self):
        """All 8 resource URIs must be registered on the mcp instance.
        FastMCP exposes a `_resource_manager` or similar; iterate registrations.
        """
        from src.server import mcp
        expected_uris = {
            "status://mcp_version",
            "status://resolve_connection",
            "status://current_project",
            "status://current_timeline",
            "status://caps_preset",
            "analysis://recent_reports",
            "capabilities://installed_tools",
            "capabilities://install_guidance",
        }
        # FastMCP's resource registry — try a few common attributes; the public
        # surface is async, so we sniff at the manager.
        registered = set()
        if hasattr(mcp, "_resource_manager"):
            rm = mcp._resource_manager
            # FastMCP stores resources in _resources dict on the manager.
            if hasattr(rm, "_resources"):
                registered = set(rm._resources.keys())
        if not registered:
            self.skipTest("FastMCP resource manager internals changed; skipping shape check")
        self.assertTrue(
            expected_uris.issubset(registered),
            f"missing resources: {expected_uris - registered}"
        )


if __name__ == "__main__":
    unittest.main()
