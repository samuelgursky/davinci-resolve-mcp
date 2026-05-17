"""Friendly launcher for the local Resolve MCP control panel."""

from __future__ import annotations

import sys

from src.analysis_dashboard import main


if __name__ == "__main__":
    if "--open" not in sys.argv and "--no-open" not in sys.argv:
        sys.argv.append("--open")
    main()
