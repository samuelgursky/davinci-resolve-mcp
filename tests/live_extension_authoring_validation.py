#!/usr/bin/env python3
"""Run the live Extension Authoring kernel probe."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path


def _install_mcp_stubs() -> None:
    """Stand in for the MCP SDK only when it is genuinely absent.

    Delegates to the shared installer so this harness cannot drift behind the
    imports `src.server` actually makes; see `src/utils/mcp_import_stubs.py`.
    """
    repo_root = str(Path(__file__).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from src.utils.mcp_import_stubs import install_mcp_stubs

    install_mcp_stubs(stdio_note="stdio_server is not used by this live harness")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    _install_mcp_stubs()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    original_argv = sys.argv[:]
    sys.argv = [sys.argv[0]]
    try:
        import src.server as server  # noqa: WPS433
    finally:
        sys.argv = original_argv

    from src.utils.extension_authoring_live_probe import run_probe  # noqa: WPS433

    output_dir = args.output_dir or Path(tempfile.mkdtemp(prefix="extension-authoring-probe-report_"))
    report = run_probe(server, output_dir, keep_open=args.keep_open)
    if report["counts"].get("error", 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
