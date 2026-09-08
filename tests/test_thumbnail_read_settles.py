"""Every GetCurrentClipThumbnailImage read goes through _playhead_thumbnail_settled.

The scripting call that follows a playhead move lands before the viewer has
caught up, so a single immediate read returns None even when everything is
correct (measured on Studio 19.1.3.7). `_playhead_thumbnail_settled` polls for
it. The contact sheet was the one caller still reading once, and it returned
"No thumbnail available" for every frame until PR #198 routed it through the
helper. This guard keeps the next caller from repeating that.
"""

from __future__ import annotations

import ast
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(REPO_ROOT, "src", "server.py")
HELPER = "_playhead_thumbnail_settled"


def _raw_reads(tree: ast.AST):
    """(function name, line) for every GetCurrentClipThumbnailImage call."""
    reads = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "GetCurrentClipThumbnailImage"):
                reads.append((func.name, node.lineno))
    return reads


class ThumbnailReadSettlesTests(unittest.TestCase):
    def test_every_thumbnail_read_is_inside_the_settle_helper(self) -> None:
        with open(SERVER, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=SERVER)
        reads = _raw_reads(tree)
        self.assertTrue(reads, "no GetCurrentClipThumbnailImage read found at all")
        outside = [f"{name} at src/server.py:{line}" for name, line in reads if name != HELPER]
        self.assertEqual(
            outside, [],
            "GetCurrentClipThumbnailImage read outside _playhead_thumbnail_settled. "
            "A single read right after a playhead move returns None before the viewer "
            "catches up (PR #198); call the helper instead.\nOffenders: " + ", ".join(outside),
        )

    def test_the_guard_can_see_a_raw_read(self) -> None:
        bad = ast.parse(
            "def _sheet(tl):\n"
            "    tl.SetCurrentTimecode(tc)\n"
            "    return tl.GetCurrentClipThumbnailImage()\n"
        )
        self.assertEqual(_raw_reads(bad), [("_sheet", 3)])


if __name__ == "__main__":
    unittest.main()
