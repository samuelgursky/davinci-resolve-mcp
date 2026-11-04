"""Set MCP's `isError` on tool results that carry an error envelope (issue #321).

Every action reports a failure as a JSON body, `{"error": {"message", "code",
...}}`, and returns it normally. FastMCP turns any normal return into a
`CallToolResult` with `isError: false`, so a client that follows the spec — a
PostToolUse hook, a retry policy, a test harness — counted every refusal as a
success. The body was right; only the flag was wrong.

The flag is set here, at the protocol boundary, and nowhere else. The tool
functions keep returning plain dicts: tests, the control panel and the
in-process callers that chain one action into another all read those dicts, and
none of them should start receiving `CallToolResult` objects. The JSON body is
sent unchanged, so callers that parse it keep working.

Only a top-level `error` key counts. `{"success": false}` is deliberately not
flagged: some actions use it for a truthful negative answer (a check that did
not pass), which is a result, not a failed call.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP


def is_error_payload(payload: Any) -> bool:
    """True when a tool's dict result is an error envelope."""
    if not isinstance(payload, dict):
        return False
    if payload.get("error"):
        return True
    # FastMCP wraps non-object return types as {"result": ...}.
    inner = payload.get("result")
    return isinstance(inner, dict) and bool(inner.get("error")) and len(payload) == 1


def _payload_from_content(content: Any) -> Any:
    """The JSON a single text block carries, or None."""
    if not isinstance(content, (list, tuple)) or len(content) != 1:
        return None
    text = getattr(content[0], "text", None)
    if getattr(content[0], "type", None) != "text" or not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def flag_tool_error(result: Any) -> Any:
    """Return `result`, re-issued as an `isError` CallToolResult if it is an error.

    `result` is what `FastMCP.call_tool` returns: a `(content, structured)`
    pair for tools with an output schema, a content list for the rest, or a
    `CallToolResult` a tool built itself (left alone).
    """
    from mcp.types import CallToolResult

    if isinstance(result, CallToolResult):
        return result
    if isinstance(result, tuple) and len(result) == 2:
        content, structured = result
        if is_error_payload(structured):
            return CallToolResult(content=list(content), structuredContent=structured, isError=True)
        return result
    if is_error_payload(_payload_from_content(result)):
        return CallToolResult(content=list(result), isError=True)
    return result


class ErrorFlaggingFastMCP(FastMCP):
    """FastMCP whose tool results report `isError` from the error envelope.

    `FastMCP.__init__` registers `self.call_tool` with the low-level server, so
    overriding the method here is what the wire actually calls.
    """

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return flag_tool_error(await super().call_tool(name, arguments))
