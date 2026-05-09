#!/usr/bin/env python3
"""Live validation for the Fusion Composition kernel."""

from __future__ import annotations

import argparse
import sys
import tempfile
import types
from pathlib import Path


def _install_mcp_stubs() -> None:
    class FastMCP:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self, *args, **kwargs):
            def decorate(func):
                return func

            return decorate

        def resource(self, *args, **kwargs):
            def decorate(func):
                return func

            return decorate

    def stdio_server(*args, **kwargs):
        raise RuntimeError("stdio_server is not used by the live Fusion Composition harness")

    anyio = types.ModuleType("anyio")
    anyio.run = lambda func: func()

    mcp = types.ModuleType("mcp")
    server = types.ModuleType("mcp.server")
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    stdio = types.ModuleType("mcp.server.stdio")

    fastmcp.FastMCP = FastMCP
    stdio.stdio_server = stdio_server

    sys.modules.setdefault("anyio", anyio)
    sys.modules.setdefault("mcp", mcp)
    sys.modules.setdefault("mcp.server", server)
    sys.modules.setdefault("mcp.server.fastmcp", fastmcp)
    sys.modules.setdefault("mcp.server.stdio", stdio)


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Fusion Composition kernel validation harness")
    parser.add_argument("--keep-open", action="store_true", help="Leave the disposable project open for inspection.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for Fusion Composition JSON/Markdown reports. Defaults to a temp directory.",
    )
    args = parser.parse_args()

    _install_mcp_stubs()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    original_argv = sys.argv[:]
    sys.argv = [sys.argv[0]]
    try:
        import src.server as server
    finally:
        sys.argv = original_argv

    output_dir = args.output_dir or Path(tempfile.mkdtemp(prefix="fusion-composition-probe-report_"))
    from src.utils.fusion_composition_live_probe import run_probe

    report = run_probe(server, output_dir, keep_open=args.keep_open)
    if report["counts"].get("error", 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
