"""Issue #321: an error envelope reaches the client with `isError: true`.

Before, every refusal came back as `CallToolResult.isError == False` with the
failure only inside the JSON body, so a spec-following client counted it as a
success. These tests drive the real FastMCP dispatch (`mcp.call_tool`, the
method the low-level server is wired to) rather than the tool functions, since
the tool functions deliberately still return plain dicts.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any, Dict, Optional

from mcp.types import CallToolResult

from src.utils.mcp_error_flag import ErrorFlaggingFastMCP, flag_tool_error, is_error_payload


def _server() -> ErrorFlaggingFastMCP:
    app = ErrorFlaggingFastMCP("flag-test")

    @app.tool()
    def ok(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"success": True, "action": action}

    @app.tool()
    def refuse(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"error": {"message": "nope", "code": "NOPE", "category": "invalid_input"}}

    @app.tool()
    def negative(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"success": False, "passed": False}

    @app.tool(structured_output=False)
    def unstructured_refuse(action: str) -> Any:
        return {"error": {"message": "nope", "code": "NOPE"}}

    @app.tool(structured_output=False)
    def unstructured_ok(action: str) -> Any:
        return {"success": True}

    return app


def _body(structured):
    """FastMCP wraps a `Dict[str, Any]` return as {"result": ...}."""
    return structured.get("result", structured)


class ErrorFlagThroughDispatchTest(unittest.TestCase):
    def setUp(self):
        self.app = _server()

    def call(self, name):
        return asyncio.run(self.app.call_tool(name, {"action": "x"}))

    def test_error_envelope_sets_is_error_and_keeps_the_body(self):
        result = self.call("refuse")
        self.assertIsInstance(result, CallToolResult)
        self.assertTrue(result.isError)
        self.assertEqual(_body(result.structuredContent)["error"]["code"], "NOPE")
        self.assertEqual(_body(json.loads(result.content[0].text))["error"]["code"], "NOPE")

    def test_success_is_left_as_fastmcp_built_it(self):
        result = self.call("ok")
        self.assertNotIsInstance(result, CallToolResult)
        self.assertTrue(_body(result[1])["success"])

    def test_success_false_without_error_is_not_flagged(self):
        self.assertNotIsInstance(self.call("negative"), CallToolResult)

    def test_unstructured_tools_are_flagged_from_their_text(self):
        result = self.call("unstructured_refuse")
        self.assertIsInstance(result, CallToolResult)
        self.assertTrue(result.isError)
        self.assertNotIsInstance(self.call("unstructured_ok"), CallToolResult)


class ErrorPayloadShapeTest(unittest.TestCase):
    def test_shapes(self):
        self.assertTrue(is_error_payload({"error": {"message": "m"}}))
        self.assertTrue(is_error_payload({"error": "legacy string"}))
        self.assertTrue(is_error_payload({"result": {"error": {"message": "m"}}}))
        self.assertFalse(is_error_payload({"error": None, "success": True}))
        self.assertFalse(is_error_payload({"success": False}))
        self.assertFalse(is_error_payload(["error"]))

    def test_a_tool_built_call_tool_result_is_untouched(self):
        built = CallToolResult(content=[], isError=False)
        self.assertIs(flag_tool_error(built), built)


class CompoundServerUsesTheFlagTest(unittest.TestCase):
    def test_unknown_action_comes_back_flagged(self):
        import src.server as server

        self.assertIsInstance(server.mcp, ErrorFlaggingFastMCP)
        result = asyncio.run(server.mcp.call_tool("timeline", {"action": "__no_such_action__"}))
        self.assertIsInstance(result, CallToolResult)
        self.assertTrue(result.isError)
        self.assertIn("error", _body(result.structuredContent))

    def test_granular_server_uses_the_flag(self):
        from src.granular import common

        self.assertIsInstance(common.mcp, ErrorFlaggingFastMCP)


if __name__ == "__main__":
    unittest.main()
