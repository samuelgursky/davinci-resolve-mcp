"""Drift guard for cross-platform agent rule files.

The per-IDE rule files (.cursor/rules/*, .github/instructions/*, .windsurf/rules/*,
.cursorrules, .windsurfrules, the AGENTS.md domain-routing block, and
.github/copilot-instructions.md) are GENERATED from one manifest by
scripts/agent-rules/generate.mjs, which also parses tool/action counts from their
canonical docs. This test fails if any generated file is stale — i.e. someone
edited a generated file by hand, or a canonical count changed without regenerating.

Fix a failure with:  node scripts/agent-rules/generate.mjs
"""
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "scripts" / "agent-rules" / "generate.mjs"


class AgentRulesDriftTest(unittest.TestCase):
    def test_generator_exists(self):
        self.assertTrue(GENERATOR.is_file(), f"missing generator: {GENERATOR}")

    def test_generated_files_are_in_sync(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node not on PATH; cannot verify generated agent-rule files")
        proc = subprocess.run(
            [node, str(GENERATOR), "--check"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            proc.returncode,
            0,
            msg=(
                "Agent-rule files are stale. Regenerate with "
                "`node scripts/agent-rules/generate.mjs`.\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            ),
        )

    def test_domain_prompts_registered_in_server(self):
        # The dynamic, every-MCP-client layer: each domain must have a slash prompt.
        server = (REPO / "src" / "server.py").read_text(encoding="utf-8")
        for name in (
            "color_grade_workflow",
            "timeline_edit_workflow",
            "conform_workflow",
            "delivery_workflow",
        ):
            self.assertIn(
                f'name="{name}"',
                server,
                msg=f"missing @mcp.prompt {name} in src/server.py",
            )


if __name__ == "__main__":
    unittest.main()
