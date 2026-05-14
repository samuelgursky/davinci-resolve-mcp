#!/usr/bin/env python3
"""Opt-in live probe for media-analysis polish.

This script connects to the currently open Resolve project and exercises only
source-safe planning/review surfaces. It may write analysis artifacts under the
project analysis root, but it does not import, transcode, proxy, move, rename,
or write beside source media.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.server import media_analysis  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run a source-safe live media-analysis polish probe.")
    parser.add_argument("--target", default="project", help="project, selected, bin:<path>, or absolute file path")
    parser.add_argument("--depth", default="standard", choices=["quick", "standard", "deep", "custom"])
    parser.add_argument("--analysis-root", default=None, help="Optional base analysis root; project subdir is still added")
    parser.add_argument("--max-samples", type=int, default=8, help="Marker thumbnail samples for review")
    parser.add_argument("--execute", action="store_true", help="Execute analysis instead of dry-run planning")
    parser.add_argument("--persist", action="store_true", help="Keep executed analysis artifacts under the project root")
    args = parser.parse_args()

    common = {
        "target": args.target,
        "depth": args.depth,
        "analysis_root": args.analysis_root,
        "dry_run": not args.execute,
        "persist": args.persist,
        "session_only": bool(args.execute and not args.persist),
        "reuse_existing": True,
        "max_analysis_frames": 8,
        "vision": {"enabled": False},
        "transcription": {"enabled": False},
    }
    plan = await media_analysis("plan", common)
    review = await media_analysis("review_timeline_markers", {
        "analysis_root": args.analysis_root,
        "max_samples": args.max_samples,
        "vision": {"enabled": False},
    })
    print(json.dumps({
        "success": bool(plan.get("success")),
        "cwd": os.getcwd(),
        "plan": plan,
        "marker_review": review,
    }, indent=2, ensure_ascii=False))
    return 0 if plan.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
