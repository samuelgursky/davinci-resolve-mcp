"""Portable-asset parity guard (the drift guard for the `.agents/` layout).

The contract (adapted from PR #173 — see scripts/agent-rules/sync_portable_assets.py):
`.claude/skills` adapters are CONTENT-COMPLETE byte-identical copies of the
canonical `.agents/skills` files (Claude routes on frontmatter descriptions,
so pointer stubs would degrade skill selection); `.agents/roles` are the
frontmatter-stripped bodies of `.claude/agents`; the Claude agent files keep
their frontmatter pins; client hook shims delegate to canonical hooks that
actually exist. Any drift here is the "new skill silently never loads in
Claude Code" failure mode — fail the suite instead.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "agent-rules"))

from sync_portable_assets import role_pairs, skill_pairs, strip_frontmatter  # noqa: E402


class SkillParity(unittest.TestCase):
    def test_every_skill_has_both_copies_and_they_match(self):
        pairs = list(skill_pairs())
        self.assertGreater(len(pairs), 0)
        for name, claude_p, agent_p in pairs:
            with self.subTest(skill=name):
                self.assertTrue(claude_p.exists(), f"{name}: no .claude adapter — the skill would never load in Claude Code")
                self.assertTrue(agent_p.exists(), f"{name}: no canonical .agents copy")
                self.assertEqual(claude_p.read_text(encoding="utf-8"), agent_p.read_text(encoding="utf-8"),
                                 f"{name}: adapter and canonical differ — run scripts/agent-rules/sync_portable_assets.py")

    def test_adapters_keep_rich_trigger_descriptions(self):
        # Claude selects skills by the frontmatter description. A stub or a
        # trimmed description degrades routing on every session.
        for name, claude_p, _ in skill_pairs():
            with self.subTest(skill=name):
                text = claude_p.read_text(encoding="utf-8")
                m = re.search(r"^description:\s*(.+?)$", text, re.M)
                self.assertIsNotNone(m, f"{name}: no description frontmatter")
                self.assertGreater(len(m.group(1)), 60,
                                   f"{name}: description suspiciously short — did a stub replace the adapter?")
                self.assertNotIn("Read and follow", text.split("---")[-1][:200],
                                 f"{name}: adapter body looks like a pointer stub")


class RoleParity(unittest.TestCase):
    def test_roles_are_the_agent_bodies(self):
        pairs = list(role_pairs())
        self.assertGreater(len(pairs), 0)
        for name, claude_p, role_p in pairs:
            with self.subTest(role=name):
                self.assertTrue(claude_p.exists(), f"{name}: no .claude/agents file")
                self.assertTrue(role_p.exists(), f"{name}: no .agents/roles file")
                self.assertEqual(strip_frontmatter(claude_p.read_text(encoding="utf-8")), role_p.read_text(encoding="utf-8"),
                                 f"{name}: role differs from the agent body — run sync_portable_assets.py")

    def test_claude_agents_keep_their_frontmatter_pins(self):
        # The model pin is deliberate for the vision-heavy reviewers; the
        # host-neutral role files cannot carry it, so losing it from the
        # .claude file loses it from the repo.
        for name, claude_p, _ in role_pairs():
            with self.subTest(role=name):
                text = claude_p.read_text(encoding="utf-8")
                self.assertRegex(text, r"^---\n", f"{name}: missing frontmatter")
                self.assertRegex(text, r"(?m)^tools:", f"{name}: frontmatter lost its tools pin")
                self.assertRegex(text, r"(?m)^model:\s*\S+", f"{name}: frontmatter lost its model pin")


class HookShims(unittest.TestCase):
    def test_every_canonical_hook_has_working_shims(self):
        canonical = sorted((REPO / ".agents" / "hooks").glob("*.py"))
        self.assertGreater(len(canonical), 0)
        for hook in canonical:
            if hook.name == "hook_runtime.py":
                continue
            for client in (".claude", ".codex"):
                shim = REPO / client / "hooks" / hook.name
                with self.subTest(hook=hook.name, client=client):
                    self.assertTrue(shim.exists(), f"{client}/hooks/{hook.name} shim missing")
                    self.assertIn(f".agents/hooks/{hook.name}", shim.read_text(encoding="utf-8"),
                                  f"{client} shim does not delegate to the canonical hook")

    def test_scratch_prefixes_stay_narrow(self):
        # This tuple EXEMPTS paths from the source-media deny. A generic
        # prefix (e.g. "agent-") would make real directories deletable.
        guard = (REPO / ".agents" / "hooks" / "source_media_guard.py").read_text(encoding="utf-8")
        m = re.search(r"SCRATCH_COMPONENT_PREFIXES\s*=\s*\(([^)]*)\)", guard)
        self.assertIsNotNone(m)
        prefixes = set(re.findall(r'"([^"]+)"', m.group(1)))
        self.assertEqual(prefixes, {"claude-", "codex-"},
                         "scratch exemption prefixes changed — each one widens what the deny will NOT protect")


if __name__ == "__main__":
    unittest.main()
