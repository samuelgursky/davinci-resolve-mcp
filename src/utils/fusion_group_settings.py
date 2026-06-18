"""Parse and patch Fusion GroupOperator .setting files.

Fusion's .setting format is a Lua-like nested structure. Real-world group
exports routinely contain InstanceInput blocks with nested UserControls /
ControlGroup tables (>=2 levels of braces), so we cannot parse them with a
flat regex. All structural scans here use balanced-brace matching.

Public surface:
  parse_setting_file(path, group_name=None) -> dict
      Inspect a .setting file and return the published-input summary for a
      named (or first) GroupOperator.

  splice_inputs_block(source_path, template_path, dest_path,
                      group_name=None) -> dict
      Replace the `Inputs = ordered() { ... }` block of source_path with
      the matching block from template_path and write to dest_path.
      Returns a before/after diff summary.

  default_backup_path(path) -> str
      Generate a timestamped backup filename next to a target path.

  FUSION_GROUP_GUARDRAILS, FUSION_COMMIT_CHECKLIST
      Advisory text. Other modules may surface these on demand; this module
      does not jam them into every return.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


FUSION_COMMIT_CHECKLIST: Tuple[str, ...] = (
    "Open the Fusion page for the modified timeline item (or comp scope).",
    "Select the group/macro node and nudge one published control so Resolve refreshes bindings.",
    "Verify Edit-page controls respond (Text, Text Size, wrap, padding, corners).",
    "Save the project (Ctrl+S / Cmd+S).",
    "If InstanceInput order changed, confirm Edit Controls order in UI; LoadSettings may require manual UI 'Load Settings' on the group.",
)

FUSION_GROUP_GUARDRAILS: Tuple[str, ...] = (
    "Do not call project_manager.load or switch projects mid Fusion edit — comp scope and undo stacks are lost.",
    "Batch graph mutations: prefer bulk_set_inputs / bulk_set_expressions over many single-action calls.",
    "InstanceInput remapping via LoadSettings may not refresh Edit-page control order until the group is selected and settings reloaded in Fusion UI.",
    "Never delete a group via automation; group_settings_load only patches published inputs and inner settings.",
    "After mutating a timeline-item Fusion comp, follow the commit checklist before expecting Edit-page updates.",
)


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


# Used only to read shallow fields out of an InstanceInput body that we have
# already isolated with balanced-brace scanning. We never use it to FIND the
# bounds of a block.
_FIELD_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|([\d.eE+-]+))')

_INPUT_HEAD_RE = re.compile(r"(Input\d+)\s*=\s*InstanceInput\s*\{")


def _find_balanced_brace(text: str, open_index: int) -> int:
    """Return the index of the `}` that closes the `{` at open_index."""
    depth = 0
    for idx in range(open_index, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx
    raise ValueError("Unbalanced braces")


def _iter_instance_input_blocks(inputs_inner: str) -> List[Tuple[str, str]]:
    """Yield (slot, body) pairs by walking InstanceInput heads + balanced braces."""
    blocks: List[Tuple[str, str]] = []
    pos = 0
    while True:
        match = _INPUT_HEAD_RE.search(inputs_inner, pos)
        if not match:
            break
        slot = match.group(1)
        open_brace = match.end() - 1
        try:
            close_brace = _find_balanced_brace(inputs_inner, open_brace)
        except ValueError:
            break
        body = inputs_inner[open_brace + 1 : close_brace]
        blocks.append((slot, body))
        pos = close_brace + 1
    return blocks


def _shallow_fields(body: str) -> Dict[str, Any]:
    """Extract top-level `key = value` fields, skipping nested braces."""
    fields: Dict[str, Any] = {}
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == "{":
            try:
                close = _find_balanced_brace(body, i)
            except ValueError:
                break
            i = close + 1
            continue
        match = _FIELD_RE.match(body, i)
        if match:
            key, str_val, num_val = match.group(1), match.group(2), match.group(3)
            if str_val is not None:
                fields[key] = str_val
            elif num_val is not None:
                try:
                    fields[key] = (
                        float(num_val) if "." in num_val or "e" in num_val.lower() else int(num_val)
                    )
                except ValueError:
                    fields[key] = num_val
            i = match.end()
        else:
            i += 1
    return fields


def parse_instance_input_block(inputs_inner: str) -> List[InstanceInputSummary]:
    summaries: List[InstanceInputSummary] = []
    for slot, body in _iter_instance_input_blocks(inputs_inner):
        fields = _shallow_fields(body)
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
    summaries.sort(key=lambda row: _slot_key(row.slot))
    return summaries


def _slot_key(slot: str) -> int:
    try:
        return int(slot.replace("Input", ""))
    except ValueError:
        return 9999


def _group_inputs_span(
    content: str, group_name: Optional[str] = None
) -> Tuple[int, int, str]:
    """Return absolute (start, end_exclusive, inner) for the Inputs ordered block."""
    if group_name:
        pattern = re.compile(
            rf"{re.escape(group_name)}\s*=\s*GroupOperator\s*\{{",
            re.MULTILINE,
        )
        match = pattern.search(content)
        if not match:
            raise ValueError(f"GroupOperator {group_name!r} not found in .setting content")
        group_open = match.end() - 1
    else:
        match = re.search(r"=\s*GroupOperator\s*\{", content)
        if not match:
            raise ValueError("No GroupOperator found in .setting content")
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


def _read_template_inputs_block(
    template_path: str, group_name: Optional[str] = None
) -> str:
    """Pull the full `Inputs = ordered() { ... },` block from a .setting file."""
    with open(template_path, encoding="utf-8", errors="replace") as handle:
        content = handle.read()
    start, end, _ = _group_inputs_span(content, group_name=group_name)
    return content[start:end]


def _summary_dict(row: Optional[InstanceInputSummary]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "source_op": row.source_op,
        "source": row.source,
        "name": row.name,
        "max_scale": row.max_scale,
        "control_group": row.control_group,
    }


def _diff_inputs(
    before: List[InstanceInputSummary], after: List[InstanceInputSummary]
) -> List[Dict[str, Any]]:
    before_by_slot = {row.slot: row for row in before}
    after_by_slot = {row.slot: row for row in after}
    all_slots = sorted(set(before_by_slot) | set(after_by_slot), key=_slot_key)
    diff: List[Dict[str, Any]] = []
    for slot in all_slots:
        b = before_by_slot.get(slot)
        a = after_by_slot.get(slot)
        if b is None:
            diff.append({"slot": slot, "change": "added", "after": _summary_dict(a)})
        elif a is None:
            diff.append({"slot": slot, "change": "removed", "before": _summary_dict(b)})
        elif _summary_dict(b) != _summary_dict(a):
            diff.append(
                {
                    "slot": slot,
                    "change": "modified",
                    "before": _summary_dict(b),
                    "after": _summary_dict(a),
                }
            )
    return diff


def splice_inputs_block(
    source_path: str,
    template_path: str,
    dest_path: str,
    *,
    source_group_name: Optional[str] = None,
    template_group_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Replace source's `Inputs = ordered() { ... }` with template's, write dest.

    source_path: .setting whose published inputs you want to replace.
    template_path: .setting whose Inputs block defines the desired layout.
    dest_path: where to write the spliced result.

    Returns a summary with input counts before/after and a per-slot diff.
    """
    with open(source_path, encoding="utf-8", errors="replace") as handle:
        source_content = handle.read()
    src_start, src_end, src_inner = _group_inputs_span(
        source_content, group_name=source_group_name
    )
    before_inputs = parse_instance_input_block(src_inner)
    template_block = _read_template_inputs_block(
        template_path, group_name=template_group_name
    )

    new_content = source_content[:src_start] + template_block + source_content[src_end:]
    _, _, new_inner = _group_inputs_span(new_content, group_name=source_group_name)
    after_inputs = parse_instance_input_block(new_inner)

    os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".", exist_ok=True)
    # Atomic write (temp + os.replace): a crash mid-write must not truncate the
    # Fusion .setting file and leave the GroupOperator config uneditable (PS5).
    tmp_path = f"{dest_path}.tmp-{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(new_content)
        os.replace(tmp_path, dest_path)
    finally:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return {
        "source_path": os.path.abspath(source_path),
        "template_path": os.path.abspath(template_path),
        "dest_path": os.path.abspath(dest_path),
        "before_input_count": len(before_inputs),
        "after_input_count": len(after_inputs),
        "diff": _diff_inputs(before_inputs, after_inputs),
    }


def default_backup_path(base_path: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root, ext = os.path.splitext(base_path)
    return f"{root}.backup_{stamp}{ext or '.setting'}"
