"""FastMCP stdio helpers with strict LF line endings across platforms."""

from __future__ import annotations

import sys
from io import TextIOWrapper

import anyio
from mcp.server.stdio import stdio_server


def create_text_stdio():
    """Wrap stdio in UTF-8 text mode without platform newline translation."""
    stdin = anyio.wrap_file(TextIOWrapper(sys.stdin.buffer, encoding="utf-8", newline=""))
    stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline=""))
    return stdin, stdout


async def run_fastmcp_stdio_async(fastmcp):
    """Run a FastMCP server over stdio using strict LF-delimited JSON."""
    stdin, stdout = create_text_stdio()
    async with stdio_server(stdin=stdin, stdout=stdout) as (read_stream, write_stream):
        await fastmcp._mcp_server.run(  # noqa: SLF001 - no public injection point exists yet
            read_stream,
            write_stream,
            fastmcp._mcp_server.create_initialization_options(),
        )


def run_fastmcp_stdio(fastmcp):
    """Synchronous entrypoint for strict-LF FastMCP stdio."""
    anyio.run(lambda: run_fastmcp_stdio_async(fastmcp))
