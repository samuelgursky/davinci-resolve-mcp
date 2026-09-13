#!/usr/bin/env python3
"""Stand-ins for the `mcp` package, for live harnesses that import `src.server`.

`src.server` imports the MCP SDK at module scope, so a live harness cannot reach
the tool functions without it. Harnesses used to each carry a private copy of a
stub installer, and every copy drifted: `src.server` grew `Context`, `Image` and
`mcp.types`, the copies kept offering only `FastMCP`, and each one broke at the
import it had never been taught about.

Two rules keep that from recurring:

1. **Never stub over a real package.** The old copies called
   `sys.modules.setdefault(...)` before anything had imported `mcp`, so the
   stand-ins won on machines where the genuine SDK was installed and working.
   `install_mcp_stubs()` imports the real package first and leaves it alone.
2. **One stub set, checked against its consumer.** `MCP_STUB_NAMES` records what
   the stubs provide; `tests/test_mcp_import_stubs.py` reads the `mcp` imports
   out of `src/server.py` and fails when the server starts needing a name the
   stubs do not define.
"""

from __future__ import annotations

import sys
import types
from typing import Dict, Tuple

# What the stub set provides, per module. The drift guard compares this against
# the names `src/server.py` actually imports, so adding an import there without
# teaching the stubs about it fails a test instead of a live run.
MCP_STUB_NAMES: Dict[str, Tuple[str, ...]] = {
    "mcp": ("types",),
    "mcp.server": (),
    "mcp.server.fastmcp": ("Context", "FastMCP", "Image"),
    "mcp.server.stdio": ("stdio_server",),
    "mcp.types": ("ToolAnnotations", "ImageContent", "TextContent"),
}


def _real_mcp_is_importable() -> bool:
    """True when the genuine SDK is installed and exposes what the server needs."""
    try:
        import mcp  # noqa: F401
        from mcp import types as _real_types  # noqa: F401
        from mcp.server.fastmcp import Context, FastMCP, Image  # noqa: F401
    except Exception:
        return False
    return True


def _build_stub_modules(*, stdio_note: str) -> Dict[str, types.ModuleType]:
    class FastMCP:
        def __init__(self, *args, **kwargs):
            pass

        def _decorator(self, *args, **kwargs):
            def decorate(func):
                return func

            return decorate

        tool = _decorator
        resource = _decorator
        prompt = _decorator

    class Context:
        pass

    class Image:
        def __init__(self, *args, **kwargs):
            pass

    class ToolAnnotations:
        def __init__(self, *args, **kwargs):
            pass

    def stdio_server(*args, **kwargs):
        raise RuntimeError(stdio_note)

    anyio = types.ModuleType("anyio")
    anyio.run = lambda func: func()

    mcp = types.ModuleType("mcp")
    server = types.ModuleType("mcp.server")
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    stdio = types.ModuleType("mcp.server.stdio")
    mcp_types = types.ModuleType("mcp.types")

    fastmcp.FastMCP = FastMCP
    fastmcp.Context = Context
    fastmcp.Image = Image
    stdio.stdio_server = stdio_server
    mcp_types.ToolAnnotations = ToolAnnotations
    mcp_types.ImageContent = object
    mcp_types.TextContent = object
    mcp.types = mcp_types

    return {
        "anyio": anyio,
        "mcp": mcp,
        "mcp.server": server,
        "mcp.server.fastmcp": fastmcp,
        "mcp.server.stdio": stdio,
        "mcp.types": mcp_types,
    }


def install_mcp_stubs(*, stdio_note: str = "stdio_server is not used by this live harness") -> bool:
    """Make `import src.server` work, without displacing a working MCP SDK.

    Returns True when stand-ins were installed, False when the real package was
    found and left in place — so a harness can say which one it ran against.
    """
    if _real_mcp_is_importable():
        return False

    for name, module in _build_stub_modules(stdio_note=stdio_note).items():
        sys.modules.setdefault(name, module)
    return True
