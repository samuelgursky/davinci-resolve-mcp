#!/usr/bin/env python3
"""PreToolUse guard: no grade lands without a frame reference behind it.

AGENTS.md ("Frame-Referenced Color Work") requires inspecting Resolve-rendered
frames before applying a grade, look, shot match, LUT, CDL, DRX, or copied
grade. That rule is prose, so it decays as a session gets long. This hook makes
it structural: a grade-applying action is refused until the session shows
evidence that frames were actually looked at.

Reads the PreToolUse payload on stdin, emits a permission decision on stdout.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_runtime import load_event, pretool_decision

# Actions on timeline_item_color that write grade state to the project.
GRADE_APPLY_ACTIONS = {
    "safe_set_cdl",
    "safe_copy_grade",
    "safe_apply_drx",
    "bulk_match_to_hero",
    "propose_grade",
}

# Whole-grade artifacts applied across many clips. These are the actions that
# overwrite hand-work irrecoverably, so they always surface to the user even
# when frame evidence exists.
BULK_APPLY_ACTIONS = {"safe_copy_grade", "bulk_match_to_hero"}

# Tools whose use counts as having looked at frames.
EVIDENCE_TOOLS = {
    "mcp__davinci-resolve__media_analysis",
    "mcp__davinci-resolve__gallery",
    "mcp__davinci-resolve__gallery_stills",
}

# timeline_item_color actions that inspect rather than write.
EVIDENCE_ACTIONS = {
    "grade_evidence_base",
    "grade_boundary_report",
    "probe_grade_item",
    "probe_node_graph",
    "grade_version_snapshot",
}

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".dpx", ".exr")


def decide(decision: str, reason: str) -> None:
    pretool_decision(decision, reason)


def state_path(session_id: str) -> Path | None:
    if not session_id:
        return None
    digest = sha256(session_id.encode("utf-8", errors="replace")).hexdigest()
    return Path(tempfile.gettempdir()) / "davinci-resolve-agent-hooks" / f"{digest}.frame-evidence"


def event_has_frame_evidence(event: Dict[str, Any]) -> bool:
    name = str(event.get("tool_name") or "")
    payload = event.get("tool_input") or {}
    if not isinstance(payload, dict):
        payload = {}
    if name in EVIDENCE_TOOLS:
        return True
    if name == "mcp__davinci-resolve__timeline_item_color":
        return payload.get("action") in EVIDENCE_ACTIONS
    if name in {"Read", "view_image"}:
        target = str(payload.get("file_path") or payload.get("path") or "").lower()
        return target.endswith(IMAGE_SUFFIXES)
    if name == "Bash":
        return "contact_sheet.py" in str(payload.get("command") or "")
    return False


def record_frame_evidence(event: Dict[str, Any]) -> None:
    if not event_has_frame_evidence(event):
        return
    path = state_path(str(event.get("session_id") or ""))
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frame evidence observed\n", encoding="utf-8")
    except OSError:
        pass


def has_recorded_frame_evidence(event: Dict[str, Any]) -> bool:
    path = state_path(str(event.get("session_id") or ""))
    return bool(path and path.is_file())


def transcript_entries(path: str) -> List[Dict[str, Any]]:
    if not path or not os.path.exists(path):
        return []
    entries: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def tool_uses(entries: List[Dict[str, Any]]):
    """Yield (name, input) for every tool_use block in the transcript."""
    for entry in entries:
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield block.get("name", ""), block.get("input") or {}


def has_frame_evidence(path: str) -> bool:
    for name, payload in tool_uses(transcript_entries(path)):
        if name in EVIDENCE_TOOLS:
            return True

        if name == "mcp__davinci-resolve__timeline_item_color":
            if payload.get("action") in EVIDENCE_ACTIONS:
                return True

        # Frames read back as local images — the host-vision path in
        # docs/guides/media-analysis-guide.md ends here.
        if name == "Read":
            target = str(payload.get("file_path", "")).lower()
            if target.endswith(IMAGE_SUFFIXES):
                return True

        if name == "Bash":
            command = str(payload.get("command", ""))
            if "contact_sheet.py" in command:
                return True

    return False


def main() -> None:
    event = load_event()
    if not event:
        sys.exit(0)

    if event.get("hook_event_name") == "PostToolUse":
        record_frame_evidence(event)
        sys.exit(0)

    tool_input = event.get("tool_input") or {}
    action = tool_input.get("action")
    if action not in GRADE_APPLY_ACTIONS:
        sys.exit(0)

    params = tool_input.get("params") or {}
    if params.get("dry_run"):
        sys.exit(0)  # A preview writes nothing.

    evidence = has_recorded_frame_evidence(event) or has_frame_evidence(
        event.get("transcript_path", "")
    )

    if not evidence:
        decide(
            "deny",
            f"AGENTS.md requires frame references before '{action}' applies a grade. "
            "Nothing in this session has looked at a Resolve-rendered frame yet.\n\n"
            "Gather evidence first, then retry:\n"
            "  - timeline_item_color(action='grade_evidence_base') for the trust-scored base\n"
            "  - timeline_item_color(action='probe_node_graph') to see the existing grade\n"
            "  - gallery_stills / media_analysis to pull frames, then Read them as images\n\n"
            "Grading from metadata, graph availability, or a style label alone is the "
            "failure mode this guard exists to catch. If the user explicitly asked for a "
            "blind/global pass, say so and re-run with dry_run first.",
        )

    if action in BULK_APPLY_ACTIONS:
        decide(
            "ask",
            f"'{action}' applies a whole-grade artifact across clips and can overwrite "
            "hand-graded work with no recovery path. Frame evidence is present, so this "
            "is a confirmation, not a block.\n\n"
            "Before confirming, be sure you have: verified the target clips are uniform, "
            "and taken a grade_version_snapshot so the previous grade is recoverable.",
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
