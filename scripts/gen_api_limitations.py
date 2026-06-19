#!/usr/bin/env python3
"""Generate the Blackmagic-facing DaVinci Resolve API limitations report.

The single source of truth is the ``submit``-tagged entries in
``src/utils/api_truth.py`` (see ``submittable_limitations``). This script renders
them into ``docs/reference/api-limitations.md`` — a curated, behaviorally-verified
list that can be submitted to Blackmagic Design's developer feedback, split into
capabilities they should *add* and behaviors they should *fix*.

The output is deterministic (no timestamps) so ``tests.test_api_limitations_doc``
can assert the committed file matches. Regenerate after editing any ``submit``
entry:

    venv/bin/python scripts/gen_api_limitations.py

Run with ``--check`` to fail (exit 1) when the committed doc is stale.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.api_truth import (  # noqa: E402
    VERIFIED_ON,
    submittable_limitations,
)

DOC_PATH = REPO_ROOT / "docs" / "reference" / "api-limitations.md"
ISSUE_URL = "https://github.com/samuelgursky/davinci-resolve-mcp/issues"


def _render_entry(entry: dict) -> str:
    lines = [f"### {entry['symbol']}", ""]
    obj = entry.get("object")
    if obj:
        lines.append(f"- **Object:** `{obj}`")
    sig = entry.get("signature")
    if sig:
        lines.append(f"- **Signature:** `{sig}`")
    lines.append(f"- **Behavior:** {entry['reality']}")
    rec = entry.get("recommended")
    if rec:
        lines.append(f"- **Workaround / current handling:** {rec}")
    issue = entry.get("issue")
    if issue is not None:
        lines.append(f"- **Reference:** [issue #{issue}]({ISSUE_URL}/{issue})")
    tags = entry.get("tags")
    if tags:
        lines.append(f"- **Tags:** {', '.join(tags)}")
    lines.append("")
    return "\n".join(lines)


def render() -> str:
    groups = submittable_limitations()
    missing = groups["missing"]
    bugs = groups["bug"]

    out = [
        "# DaVinci Resolve Scripting API — Limitations & Feedback",
        "",
        "<!-- GENERATED FILE — do not edit by hand.",
        "     Source: src/utils/api_truth.py (entries tagged `submit`).",
        "     Regenerate: venv/bin/python scripts/gen_api_limitations.py -->",
        "",
        "This is a curated, behaviorally-verified list of DaVinci Resolve scripting",
        "API gaps and bugs encountered while building this MCP server, intended for",
        "submission to Blackmagic Design's developer feedback. Every item was",
        "observed against live Resolve; each entry notes the current workaround (or",
        "that none exists).",
        "",
        f"**Verified on:** {VERIFIED_ON}",
        "",
        f"**Totals:** {len(missing)} missing capabilities, {len(bugs)} bugs / "
        "unreliable behaviors.",
        "",
        "The authoritative source is the runtime-queryable `api_truth` ledger",
        "(`resolve_control api_truth \"<query>\"`); this document is generated from",
        "it and stays in sync via a drift guard.",
        "",
        "### Scope & completeness",
        "",
        "This list is **not guaranteed exhaustive.** It combines (a) issues hit",
        "while building this MCP server, (b) a `dir()` surface audit of the live",
        "Resolve API objects (ProjectManager, Project, MediaPool, MediaPoolItem,",
        "Timeline, TimelineItem, Graph) diffed against Resolve's UI feature set,",
        "and (c) a live mutating harness (`tests/live_api_gap_verification.py`)",
        "that attempts each operation against a disposable project built from",
        "synthetic media and confirms it fails while a related control succeeds.",
        "That catches absent methods and documented constraints, but not subtler",
        "issues: parameters that exist yet misbehave, version-specific regressions,",
        "or capabilities we simply never exercised. New findings are added as",
        "`submit`-tagged `api_truth` entries and this document is regenerated.",
        "",
        "Note: `hasattr()`/`getattr()` cannot be used to probe this API — the",
        "Python bridge fabricates a callable for any attribute name (see the",
        "`hasattr` bug below). Method existence here was checked with `dir()`.",
        "",
        "## Missing Capabilities (please add)",
        "",
        "Functionality that exists in the Resolve UI but has no scripting API",
        "equivalent, blocking full automation.",
        "",
    ]
    for entry in missing:
        out.append(_render_entry(entry))

    out += [
        "## Bugs / Unreliable Behavior (please fix)",
        "",
        "Methods that exist but misbehave — silent failures, unreliable return",
        "values, or automation-hostile modal prompts.",
        "",
    ]
    for entry in bugs:
        out.append(_render_entry(entry))

    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str]) -> int:
    content = render()
    if "--check" in argv:
        current = DOC_PATH.read_text() if DOC_PATH.exists() else ""
        if current != content:
            print(
                f"STALE: {DOC_PATH.relative_to(REPO_ROOT)} is out of date.\n"
                "Run: venv/bin/python scripts/gen_api_limitations.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {DOC_PATH.relative_to(REPO_ROOT)} is up to date.")
        return 0
    DOC_PATH.write_text(content)
    print(f"Wrote {DOC_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
