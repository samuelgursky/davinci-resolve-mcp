#!/usr/bin/env python3
"""Measure DaVinci Resolve bridge round-trips for representative operations.

Wraps the live project in a counting proxy and runs a few common traversals,
reporting how many attribute accesses + method calls (each a bridge round-trip)
they cost. This is the measurement that gates whether a property cache is worth
building. Run against an OPEN project; it only reads.

    PYTHONPATH=. venv/bin/python scripts/measure_bridge_cost.py
"""
import sys

import src.server as s
from src.utils.bridge_metrics import measure


def _walk_media_pool(project_proxy):
    """A typical media-pool traversal: every folder, every clip, name + a property."""
    mp = project_proxy.GetMediaPool()
    root = mp.GetRootFolder()
    clips_seen = 0

    def walk(folder):
        nonlocal clips_seen
        for clip in (folder.GetClipList() or []):
            clip.GetName()
            clip.GetClipProperty("Type")
            clips_seen += 1
        for sub in (folder.GetSubFolderList() or []):
            walk(sub)

    walk(root)
    return clips_seen


def main():
    r = s.get_resolve()
    if not r:
        print("Not connected to Resolve.")
        return 1
    proj = r.GetProjectManager().GetCurrentProject()
    if not proj:
        print("No project open.")
        return 1

    clips_holder = {}

    def op(proj_proxy):
        clips_holder["n"] = _walk_media_pool(proj_proxy)

    counts = measure(op, proj)
    n = clips_holder.get("n", 0)
    total = counts["attr_access"] + counts["calls"]
    print(f"project: {proj.GetName()!r}")
    print(f"clips walked: {n}")
    print(f"bridge attr-accesses: {counts['attr_access']}")
    print(f"bridge method-calls:  {counts['calls']}")
    print(f"total round-trips:    {total}")
    if n:
        print(f"round-trips per clip: {total / n:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
