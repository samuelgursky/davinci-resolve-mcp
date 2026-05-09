#!/usr/bin/env python3
"""Live Review Annotation kernel validation against DaVinci Resolve.

This harness creates a disposable project and synthetic media, then probes the
timeline, timeline item, and media pool item annotation surfaces. It removes the
project and generated media unless --keep-open is supplied.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import types
from pathlib import Path


def _install_mcp_stubs() -> None:
    """Allow importing src.server when MCP deps are absent from Python 3.11."""

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
        raise RuntimeError("stdio_server is not used by the live Review Annotation harness")

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory where JSON and Markdown probe reports are written.",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Leave the disposable Resolve project open for visual inspection.",
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

    from src.utils.review_annotation_live_probe import run_probe

    output_dir = args.output_dir or Path(tempfile.mkdtemp(prefix="review-annotation-probe-report_"))
    report = run_probe(server, output_dir, keep_open=args.keep_open)
    return 1 if report["counts"].get("error", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
