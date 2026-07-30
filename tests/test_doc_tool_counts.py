"""Drift guard: the tool counts quoted across docs must match reality.

Counts are computed STATICALLY (no imports, no deps — same posture as the other drift
guards so this runs in the dependency-light publish gate):
  - compound  = `@mcp.tool(` decorators in `src/server.py`
  - granular  = `@mcp.tool(` decorators across `src/granular/*.py`
  - advanced  = entries in the `TOOLS` array in `resolve-advanced/server/index.mjs`

Docs (README, contributing, SKILL, api-coverage, copilot-instructions) quote those
counts by hand and drift. This asserts the docs still match — a stale count fails the
offline suite and the release publish gate instead of shipping wrong numbers.

Fix drift by updating the docs to the printed counts, not by loosening this test.
The counts are cross-checked against the runtime tool registry and agree: 34 / 341.

Decorators are counted from the **parsed syntax tree**, not by matching the text
`@mcp.tool(`. A regex counts the string wherever it appears, including inside a
docstring — which is how a comment explaining where a decorator has to sit once
reported a 35th tool and failed this guard. Prose that mentions the decorator is
not a tool, and a guard that cannot tell the difference reports drift that is not
there.
"""

import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _is_mcp_tool(decorator: ast.expr) -> bool:
    """`@mcp.tool()` and `@mcp.tool(annotations=...)`, bare or called."""
    node = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(node, ast.Attribute) and node.attr == "tool" and (
        isinstance(node.value, ast.Name) and node.value.id == "mcp"
    )


def _count_decorators(*rel_globs: str) -> int:
    total = 0
    for rel in rel_globs:
        for path in sorted(ROOT.glob(rel)):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    total += sum(1 for d in node.decorator_list if _is_mcp_tool(d))
    return total


def _advanced_count() -> int:
    idx = (ROOT / "resolve-advanced" / "server" / "index.mjs").read_text()
    m = re.search(r"const TOOLS\s*=\s*\[([^\]]+)\]", idx)
    if not m:
        raise AssertionError("could not find the TOOLS array in resolve-advanced/server/index.mjs")
    return len([t for t in m.group(1).split(",") if t.strip()])


class DocToolCountsDriftTest(unittest.TestCase):
    def test_doc_counts_match_reality(self):
        comp = _count_decorators("src/server.py")
        gran = _count_decorators("src/granular/*.py")
        adv = _advanced_count()

        # (file, required substring) — each must be present verbatim.
        checks = [
            ("README.md", f"{adv} tools:"),
            ("README.md", f"**{comp}** compound / **{gran}** granular"),
            ("README.md", f"Advanced (offline) tools | **{adv}**"),
            ("README.md", f"Advanced%20(offline)-{adv}%20tools"),
            ("resolve-advanced/README.md", f"## Tools ({adv})"),
            ("src/server.py", f"{comp} compound tools"),
            ("docs/contributing.md", f"Compound MCP server — {comp} tools"),
            ("docs/SKILL.md", f"`src/server.py` | {comp} tools"),
            ("docs/SKILL.md", f"`src/server.py --full` | {gran} tools"),
            ("docs/reference/api-coverage.md", f"**{comp} tools**"),
            ("docs/reference/api-coverage.md", f"**{gran} individual tools**"),
            (".github/copilot-instructions.md", f"compound MCP server ({comp} tools)"),
            (".github/copilot-instructions.md", f"Full server ({gran} tools)"),
        ]

        stale = []
        for rel, needle in checks:
            text = (ROOT / rel).read_text()
            if needle not in text:
                stale.append(f"{rel}: expected to contain {needle!r}")

        self.assertEqual(
            stale,
            [],
            "Doc tool counts are stale (authoritative: "
            f"compound={comp}, granular={gran}, advanced={adv}). "
            "Update these docs:\n  " + "\n  ".join(stale),
        )


if __name__ == "__main__":
    unittest.main()
