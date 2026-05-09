#!/usr/bin/env python3
"""Live validation for the Media Pool / ingest kernel.

Creates a disposable Resolve project, generates synthetic media, imports it into
the Media Pool, probes import/metadata/annotation/link surfaces, writes optional
reports, and deletes the project unless --keep-open is provided.

Run with Python 3.10-3.12 against a running Resolve Studio instance:

  python3.11 tests/live_media_pool_ingest_validation.py
  python3.11 tests/live_media_pool_ingest_validation.py --output-dir /tmp/media-pool-ingest-probe
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
        raise RuntimeError("stdio_server is not used by the live Media Pool ingest harness")

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
    parser = argparse.ArgumentParser(description="Live Media Pool / ingest kernel validation harness")
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Leave the disposable project open for manual inspection.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for Media Pool ingest JSON/Markdown reports. Defaults to a temp directory.",
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

    output_dir = args.output_dir or Path(tempfile.mkdtemp(prefix="media-pool-ingest-probe-report_"))
    from src.utils.media_pool_ingest_live_probe import run_probe

    report = run_probe(server, output_dir, keep_open=args.keep_open)
    if report["counts"].get("error", 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
