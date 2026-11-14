"""Arguments a tool does not take are refused, not dropped (issue #372).

FastMCP's argument model ignores unknown keys, so `timeline(action=...,
timeline_name="vB")` reached the tool as `timeline(action=...)` and acted on
the current timeline with success.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any, Dict, Optional
from unittest import mock

from src.utils import mcp_arg_guard
from src.utils.mcp_error_flag import ErrorFlaggingFastMCP


def _server():
    server = ErrorFlaggingFastMCP("test")
    calls = []

    @server.tool()
    def compound(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        calls.append((action, params))
        return {"success": True, "params": params}

    @server.tool()
    def granular(name: str, track_index: int = 1) -> Dict[str, Any]:
        calls.append((name, track_index))
        return {"success": True}

    return server, calls


def _call(server, name, arguments):
    return asyncio.run(server.call_tool(name, arguments))


class UnknownArgumentRefusalTest(unittest.TestCase):
    def test_a_selector_beside_action_is_refused_before_the_tool_runs(self):
        server, calls = _server()
        result = _call(server, "compound", {"action": "get_name", "timeline_name": "vB"})
        self.assertTrue(result.isError)
        error = result.structuredContent["error"]
        self.assertEqual(error["code"], "UNKNOWN_ARGUMENTS")
        self.assertIn("'timeline_name'", error["message"])
        self.assertEqual(error["state"]["corrected_params"], {"timeline_name": "vB"})
        self.assertEqual(calls, [], "the tool must not run with the selector dropped")

    def test_the_correction_merges_with_params_already_given(self):
        server, _ = _server()
        result = _call(server, "compound",
                       {"action": "probe", "params": {"track_types": ["video"]}, "timeline_id": "t2"})
        self.assertEqual(result.structuredContent["error"]["state"]["corrected_params"],
                         {"track_types": ["video"], "timeline_id": "t2"})

    def test_the_same_keys_inside_params_still_run(self):
        server, calls = _server()
        result = _call(server, "compound", {"action": "get_name", "params": {"timeline_name": "vB"}})
        self.assertFalse(getattr(result, "isError", False))
        self.assertEqual(calls, [("get_name", {"timeline_name": "vB"})])

    def test_a_granular_tool_refuses_an_unknown_keyword(self):
        server, calls = _server()
        result = _call(server, "granular", {"name": "x", "trackIndex": 2})
        self.assertTrue(result.isError)
        self.assertIn("'trackIndex'", result.structuredContent["error"]["message"])
        self.assertNotIn("corrected_params", result.structuredContent["error"]["state"])
        self.assertEqual(calls, [])

    def test_known_arguments_pass_through(self):
        server, calls = _server()
        _call(server, "granular", {"name": "x", "track_index": 2})
        self.assertEqual(calls, [("x", 2)])

    def test_an_unknown_tool_is_left_to_fastmcp(self):
        server, _ = _server()
        self.assertEqual(mcp_arg_guard.unknown_arguments(None, {"a": 1}), [])
        with self.assertRaises(Exception):
            _call(server, "missing", {"a": 1})


class RealServerTest(unittest.TestCase):
    def test_the_compound_timeline_tool_refuses_a_top_level_timeline_name(self):
        import src.server as s

        with mock.patch.object(s, "_check", side_effect=AssertionError("reached Resolve")):
            result = _call(s.mcp, "timeline", {"action": "probe_timeline_structure", "timeline_name": "vB"})
        self.assertTrue(result.isError)
        self.assertEqual(result.structuredContent["error"]["code"], "UNKNOWN_ARGUMENTS")

    def test_every_compound_tool_takes_action_and_params_only(self):
        """The refusal's advice ('move it into params') must be true for each compound tool."""
        import src.server as s

        for tool in s.mcp._tool_manager.list_tools():
            accepted = mcp_arg_guard.accepted_arguments(tool)
            if accepted and "action" in accepted:
                self.assertIn("params", accepted, tool.name)


if __name__ == "__main__":
    unittest.main()
