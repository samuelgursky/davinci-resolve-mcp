#!/usr/bin/env python3
"""Sync the portable agent assets (`.agents/`) with their Claude adapters.

The layout contract (adapted from PR #173):

- `.agents/skills/*/SKILL.md` is the canonical, host-neutral skill corpus —
  the `knowledge` MCP tool serves it, and non-Claude hosts read it directly.
- `.claude/skills/*/SKILL.md` is a CONTENT-COMPLETE copy, byte-identical to
  the canonical file. Claude Code routes on the frontmatter description at
  selection time, so the adapter must carry the full text — a pointer stub
  would cost a read per invocation and hide the trigger phrasing.
- `.agents/roles/*.md` is the body (frontmatter stripped) of the matching
  `.claude/agents/*.md`. The Claude file keeps its frontmatter — name,
  description, tools, and the deliberate `model:` pin — which host-neutral
  role files cannot carry.
- `.agents/hooks/*.py` is canonical executable logic; `.claude/hooks` and
  `.codex/hooks` are thin runpy shims (execution-only surfaces need no
  content duplication).

Edit EITHER side of a skill (they are identical); edit `.claude/agents` for
roles. Then run this script to restore the invariant:

    venv/bin/python scripts/agent-rules/sync_portable_assets.py          # write
    venv/bin/python scripts/agent-rules/sync_portable_assets.py --check  # verify only

`tests/test_portable_asset_parity.py` fails the suite when the invariant is
broken, so drift cannot land.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLAUDE_SKILLS = REPO / ".claude" / "skills"
AGENT_SKILLS = REPO / ".agents" / "skills"
CLAUDE_AGENTS = REPO / ".claude" / "agents"
AGENT_ROLES = REPO / ".agents" / "roles"

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n\n?", re.S)


def strip_frontmatter(text: str) -> str:
    m = _FRONTMATTER_RE.match(text)
    return text[m.end():] if m else text


def skill_pairs():
    names = sorted(
        {p.parent.name for p in CLAUDE_SKILLS.glob("*/SKILL.md")}
        | {p.parent.name for p in AGENT_SKILLS.glob("*/SKILL.md")}
    )
    for name in names:
        yield name, CLAUDE_SKILLS / name / "SKILL.md", AGENT_SKILLS / name / "SKILL.md"


def role_pairs():
    names = sorted(
        {p.stem for p in CLAUDE_AGENTS.glob("*.md")} | {p.stem for p in AGENT_ROLES.glob("*.md")}
    )
    for name in names:
        yield name, CLAUDE_AGENTS / f"{name}.md", AGENT_ROLES / f"{name}.md"


def run(check_only: bool) -> int:
    problems: list[str] = []
    for name, claude_p, agent_p in skill_pairs():
        if not claude_p.exists():
            problems.append(f"skill '{name}': canonical exists but .claude adapter is missing — it would never load in Claude Code")
            if not check_only and agent_p.exists():
                claude_p.parent.mkdir(parents=True, exist_ok=True)
                claude_p.write_text(agent_p.read_text(encoding="utf-8"), encoding="utf-8")
            continue
        src = claude_p.read_text(encoding="utf-8")
        if not agent_p.exists() or agent_p.read_text(encoding="utf-8") != src:
            problems.append(f"skill '{name}': .agents copy {'missing' if not agent_p.exists() else 'differs'}")
            if not check_only:
                agent_p.parent.mkdir(parents=True, exist_ok=True)
                agent_p.write_text(src, encoding="utf-8")
    for name, claude_p, role_p in role_pairs():
        if not claude_p.exists():
            problems.append(f"role '{name}': .agents/roles exists but .claude/agents is missing — restore the frontmatter file by hand (it carries tools/model pins this script cannot invent)")
            continue
        body = strip_frontmatter(claude_p.read_text(encoding="utf-8"))
        if not role_p.exists() or role_p.read_text(encoding="utf-8") != body:
            problems.append(f"role '{name}': .agents/roles {'missing' if not role_p.exists() else 'differs from the .claude/agents body'}")
            if not check_only:
                role_p.parent.mkdir(parents=True, exist_ok=True)
                role_p.write_text(body, encoding="utf-8")
    if problems:
        for p in problems:
            print(("DRIFT: " if check_only else "SYNCED: ") + p)
        return 1 if check_only else 0
    print("portable assets in sync")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify only; non-zero exit on drift")
    args = ap.parse_args()
    return run(check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
