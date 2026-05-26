"""Parse and patch Fusion GroupOperator .setting files (InstanceInput / ordered blocks)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# SpeechBubblev10-compatible 14-input layout for thought-bubble remaps.
# Input order matches Edit-page control order; inner SourceOp names assume
# Text + TextBox legs like AMZ thought/speech macros.
THOUGHT_BUBBLE_SPEECH_ORDER_TEMPLATE = """Inputs = ordered() {
\t\t\t\tInput1 = InstanceInput {
\t\t\t\t\tSourceOp = "Text",
\t\t\t\t\tSource = "StyledText",
\t\t\t\t\tName = "Text",
\t\t\t\t},
\t\t\t\tInput2 = InstanceInput {
\t\t\t\t\tSourceOp = "Text",
\t\t\t\t\tSource = "Font",
\t\t\t\t\tControlGroup = 2,
\t\t\t\t},
\t\t\t\tInput3 = InstanceInput {
\t\t\t\t\tSourceOp = "Text",
\t\t\t\t\tSource = "Style",
\t\t\t\t\tControlGroup = 2,
\t\t\t\t},
\t\t\t\tInput4 = InstanceInput {
\t\t\t\t\tSourceOp = "TextBox",
\t\t\t\t\tSource = "TextSize",
\t\t\t\t\tName = "Text Size",
\t\t\t\t\tMaxScale = {max_scale},
\t\t\t\t\tDefault = 0.06,
\t\t\t\t},
\t\t\t\tInput5 = InstanceInput {
\t\t\t\t\tSourceOp = "TextBox",
\t\t\t\t\tSource = "CharacterSpacingClone",
\t\t\t\t\tName = "Tracking",
\t\t\t\t\tDefault = 1,
\t\t\t\t},
\t\t\t\tInput6 = InstanceInput {
\t\t\t\t\tSourceOp = "TextBox",
\t\t\t\t\tSource = "LineSpacingClone",
\t\t\t\t\tName = "Line Spacing",
\t\t\t\t\tDefault = 1,
\t\t\t\t},
\t\t\t\tInput7 = InstanceInput {
\t\t\t\t\tSourceOp = "TextBox",
\t\t\t\t\tSource = "LayoutWidth",
\t\t\t\t\tName = "Text Wrap Width",
\t\t\t\t\tDefault = 0.5,
\t\t\t\t},
\t\t\t\tInput8 = InstanceInput {
\t\t\t\t\tSourceOp = "TextBox",
\t\t\t\t\tSource = "ExtendHorizontal1",
\t\t\t\t\tName = "Bubble Padding Horizontal",
\t\t\t\t\tDefault = 0.2,
\t\t\t\t},
\t\t\t\tInput9 = InstanceInput {
\t\t\t\t\tSourceOp = "TextBox",
\t\t\t\t\tSource = "ExtendVertical1",
\t\t\t\t\tName = "Bubble Padding Vertical",
\t\t\t\t\tDefault = 0.2,
\t\t\t\t},
\t\t\t\tInput10 = InstanceInput {
\t\t\t\t\tSourceOp = "TextBox",
\t\t\t\t\tSource = "Round1",
\t\t\t\t\tName = "Round Corners",
\t\t\t\t\tDefault = 0.5,
\t\t\t\t},
\t\t\t\tInput11 = InstanceInput {
\t\t\t\t\tSourceOp = "Text",
\t\t\t\t\tSource = "Red1",
\t\t\t\t\tName = "Text Color",
\t\t\t\t\tControlGroup = 10,
\t\t\t\t\tDefault = 0.1764705882353,
\t\t\t\t},
\t\t\t\tInput12 = InstanceInput {
\t\t\t\t\tSourceOp = "Text",
\t\t\t\t\tSource = "Green1",
\t\t\t\t\tControlGroup = 10,
\t\t\t\t},
\t\t\t\tInput13 = InstanceInput {
\t\t\t\t\tSourceOp = "Text",
\t\t\t\t\tSource = "Blue1",
\t\t\t\t\tControlGroup = 10,
\t\t\t\t},
\t\t\t\tInput14 = InstanceInput {
\t\t\t\t\tSourceOp = "Text",
\t\t\t\t\tSource = "Alpha1",
\t\t\t\t\tControlGroup = 10,
\t\t\t\t\tDefault = 1,
\t\t\t\t},
\t\t\t},"""

INSTANCE_INPUT_RE = re.compile(
    r"(Input\d+)\s*=\s*InstanceInput\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}",
    re.DOTALL,
)
FIELD_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|([\d.eE+-]+))')

FUSION_COMMIT_CHECKLIST = [
    "Open the Fusion page for the modified timeline item (or comp scope).",
    "Select the group/macro node and nudge one published control so Resolve refreshes bindings.",
    "Verify Edit-page controls respond (Text, Text Size, wrap, padding, corners).",
    "Save the project (Ctrl+S / Cmd+S).",
    "If InstanceInput order changed, confirm Edit Controls order in UI; LoadSettings may require manual UI 'Load Settings' on the group.",
]

FUSION_GROUP_GUARDRAILS = [
    "Do not call project_manager.load or switch projects mid Fusion edit — comp scope and undo stacks are lost.",
    "Batch graph mutations: prefer bulk_set_inputs / bulk_set_expressions over many single-action calls.",
    "InstanceInput remapping via LoadSettings may not refresh Edit-page control order until the group is selected and settings reloaded in Fusion UI.",
    "Never delete a group via automation; group_settings_load only patches published inputs and inner settings.",
    "After mutating a timeline-item Fusion comp, follow fusion_commit_hint before expecting Edit-page updates.",
]


@dataclass
class InstanceInputSummary:
    slot: str
    source_op: Optional[str] = None
    source: Optional[str] = None
    name: Optional[str] = None
    max_scale: Optional[float] = None
    default: Optional[str] = None
    control_group: Optional[int] = None
    raw_fields: Dict[str, Any] = field(default_factory=dict)


def _find_balanced_brace(text: str, open_index: int) -> int:
    depth = 0
    for idx in range(open_index, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx
    raise ValueError("Unbalanced braces in .setting content")


def parse_instance_input_block(inputs_inner: str) -> List[InstanceInputSummary]:
    summaries: List[InstanceInputSummary] = []
    for match in INSTANCE_INPUT_RE.finditer(inputs_inner):
        slot = match.group(1)
        body = match.group(2)
        fields: Dict[str, Any] = {}
        for field_match in FIELD_RE.finditer(body):
            key, str_val, num_val = field_match.group(1), field_match.group(2), field_match.group(3)
            if str_val is not None:
                fields[key] = str_val
            elif num_val is not None:
                try:
                    fields[key] = float(num_val) if "." in num_val or "e" in num_val.lower() else int(num_val)
                except ValueError:
                    fields[key] = num_val
        max_scale = fields.get("MaxScale")
        if isinstance(max_scale, (int, float)):
            max_scale_f: Optional[float] = float(max_scale)
        else:
            max_scale_f = None
        cg = fields.get("ControlGroup")
        summaries.append(
            InstanceInputSummary(
                slot=slot,
                source_op=fields.get("SourceOp"),
                source=fields.get("Source"),
                name=fields.get("Name"),
                max_scale=max_scale_f,
                default=str(fields["Default"]) if "Default" in fields else None,
                control_group=int(cg) if isinstance(cg, int) else None,
                raw_fields=fields,
            )
        )

    def _slot_key(slot: str) -> int:
        try:
            return int(slot.replace("Input", ""))
        except ValueError:
            return 9999

    summaries.sort(key=lambda row: _slot_key(row.slot))
    return summaries


def parse_setting_file(path: str, group_name: Optional[str] = None) -> Dict[str, Any]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        content = handle.read()
    _, _, inner = _group_inputs_span(content, group_name=group_name)
    inputs = parse_instance_input_block(inner)
    return {
        "path": os.path.abspath(path),
        "published_inputs": [
            {
                "slot": row.slot,
                "name": row.name,
                "source_op": row.source_op,
                "source": row.source,
                "max_scale": row.max_scale,
                "default": row.default,
                "control_group": row.control_group,
            }
            for row in inputs
        ],
        "input_count": len(inputs),
    }


def render_template(template_key: str, *, max_scale: float = 0.25) -> str:
    if template_key in ("thought_bubble", "thought_bubble_speech_order", "speech_bubble_v10_14"):
        return THOUGHT_BUBBLE_SPEECH_ORDER_TEMPLATE.replace("{max_scale}", str(max_scale))
    raise ValueError(f"Unknown template {template_key!r}")


def _group_inputs_span(content: str, group_name: Optional[str] = None) -> Tuple[int, int, str]:
    """Return absolute (start, end_exclusive, inner) for the Inputs ordered block."""
    if group_name:
        pattern = re.compile(
            rf"{re.escape(group_name)}\s*=\s*GroupOperator\s*\{{",
            re.MULTILINE,
        )
        match = pattern.search(content)
        if not match:
            raise ValueError(f"GroupOperator {group_name!r} not found in .setting file")
        group_open = match.end() - 1
    else:
        match = re.search(r"=\s*GroupOperator\s*\{", content)
        if not match:
            raise ValueError("No GroupOperator found in .setting file")
        group_open = match.end() - 1

    group_close = _find_balanced_brace(content, group_open)
    group_body = content[group_open + 1 : group_close]
    inputs_marker = re.search(r"Inputs\s*=\s*ordered\s*\(\s*\)\s*\{", group_body)
    if not inputs_marker:
        raise ValueError("GroupOperator has no Inputs = ordered() block")
    abs_start = group_open + 1 + inputs_marker.start()
    open_brace = group_open + 1 + inputs_marker.end() - 1
    close_brace = _find_balanced_brace(content, open_brace)
    replace_end = close_brace + 1
    if replace_end < len(content) and content[replace_end] == ",":
        replace_end += 1
    return abs_start, replace_end, content[open_brace + 1 : close_brace]


def patch_group_inputs_block(
    content: str,
    *,
    template_key: str = "thought_bubble",
    group_name: Optional[str] = None,
    max_scale: float = 0.25,
) -> Tuple[str, Dict[str, Any]]:
    replace_start, replace_end, old_inner = _group_inputs_span(content, group_name=group_name)
    old_inputs = parse_instance_input_block(old_inner)
    new_block = render_template(template_key, max_scale=max_scale)
    new_content = content[:replace_start] + new_block + content[replace_end:]
    new_inner = _group_inputs_span(new_content, group_name=group_name)[2]
    new_inputs = parse_instance_input_block(new_inner)
    diff = []
    old_by_slot = {row.slot: row for row in old_inputs}
    new_by_slot = {row.slot: row for row in new_inputs}
    for slot in sorted(set(old_by_slot) | set(new_by_slot), key=lambda s: int(s.replace("Input", "") or 0)):
        before = old_by_slot.get(slot)
        after = new_by_slot.get(slot)
        if before is None:
            diff.append({"slot": slot, "change": "added", "after": _summary_dict(after)})
        elif after is None:
            diff.append({"slot": slot, "change": "removed", "before": _summary_dict(before)})
        elif _summary_dict(before) != _summary_dict(after):
            diff.append(
                {
                    "slot": slot,
                    "change": "modified",
                    "before": _summary_dict(before),
                    "after": _summary_dict(after),
                }
            )
    return new_content, {
        "template": template_key,
        "max_scale": max_scale,
        "old_input_count": len(old_inputs),
        "new_input_count": len(new_inputs),
        "diff": diff,
        "diff_count": len(diff),
    }


def _summary_dict(row: Optional[InstanceInputSummary]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "source_op": row.source_op,
        "source": row.source,
        "name": row.name,
        "max_scale": row.max_scale,
    }


def patch_setting_file(
    source_path: str,
    dest_path: str,
    *,
    template_key: str = "thought_bubble",
    group_name: Optional[str] = None,
    max_scale: float = 0.25,
) -> Dict[str, Any]:
    with open(source_path, encoding="utf-8", errors="replace") as handle:
        content = handle.read()
    patched, summary = patch_group_inputs_block(
        content,
        template_key=template_key,
        group_name=group_name,
        max_scale=max_scale,
    )
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".", exist_ok=True)
    with open(dest_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(patched)
    summary["source_path"] = os.path.abspath(source_path)
    summary["dest_path"] = os.path.abspath(dest_path)
    return summary


def default_backup_path(base_path: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root, ext = os.path.splitext(base_path)
    return f"{root}.backup_{stamp}{ext or '.setting'}"


def fusion_commit_hint(*, modified: bool = True) -> Dict[str, Any]:
    return {
        "modified": modified,
        "checklist": list(FUSION_COMMIT_CHECKLIST),
        "guardrails": list(FUSION_GROUP_GUARDRAILS),
        "instance_input_note": (
            "LoadSettings updates inner tool wiring but may not remap Edit-page "
            "InstanceInput order until Fusion UI reloads group settings on the node."
        ),
    }
