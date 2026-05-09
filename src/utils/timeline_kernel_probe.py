"""Helpers for timeline edit kernel capability probe reports."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, Iterable, List, Optional


PROBE_STATUSES = {
    "supported",
    "partially_supported",
    "read_only",
    "write_only_unverifiable",
    "version_or_page_dependent",
    "unsupported",
    "not_applicable",
    "error",
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_timeline_item_property_keys(api_text: str) -> List[str]:
    """Return documented TimelineItem GetProperty/SetProperty keys in doc order."""
    start_marker = "The supported keys with their accepted values are:"
    end_marker = "Values beyond the range will be clipped"
    start = api_text.find(start_marker)
    if start < 0:
        return []
    end = api_text.find(end_marker, start)
    section = api_text[start:end if end >= 0 else None]
    keys: List[str] = []
    for match in re.finditer(r'^\s+"([^"]+)"\s*:', section, flags=re.MULTILINE):
        key = match.group(1)
        if key not in keys:
            keys.append(key)
    return keys


def parse_api_class_methods(api_text: str, class_name: str) -> List[str]:
    """Return method names documented under a top-level API class section."""
    lines = api_text.splitlines()
    start_index: Optional[int] = None
    for index, line in enumerate(lines):
        if line.strip() == class_name:
            start_index = index + 1
            break
    if start_index is None:
        return []

    methods: List[str] = []
    for line in lines[start_index:]:
        stripped = line.strip()
        if stripped and not line.startswith(" ") and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", stripped):
            break
        match = re.match(r"\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if match:
            method = match.group(1)
            if method not in methods:
                methods.append(method)
    return methods


def ordered_unique(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def values_match(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return bool(actual) is expected
    try:
        return abs(float(actual) - float(expected)) <= 0.001
    except (TypeError, ValueError):
        return actual == expected


class ProbeRecorder:
    """Collects normalized capability probe records and renders reports."""

    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []

    def record(
        self,
        category: str,
        name: str,
        status: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        evidence: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if status not in PROBE_STATUSES:
            raise ValueError(f"unknown probe status: {status}")
        item = {
            "category": category,
            "name": name,
            "status": status,
            "details": details or {},
        }
        if evidence is not None:
            item["evidence"] = evidence
        self.records.append(item)
        return item

    def record_exception(self, category: str, name: str, exc: Exception, *, details: Optional[Dict[str, Any]] = None):
        payload = dict(details or {})
        payload["exception"] = repr(exc)
        return self.record(category, name, "error", details=payload)

    def counts(self) -> Dict[str, int]:
        counts = Counter(record["status"] for record in self.records)
        return {status: counts.get(status, 0) for status in sorted(PROBE_STATUSES)}

    def to_report(self, metadata: Dict[str, Any], artifacts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "metadata": metadata,
            "artifacts": artifacts or {},
            "counts": self.counts(),
            "records": self.records,
        }


def render_markdown_report(report: Dict[str, Any]) -> str:
    metadata = report.get("metadata", {})
    counts = report.get("counts", {})
    records = report.get("records", [])
    artifacts = report.get("artifacts", {})

    title = metadata.get("title", "Timeline Edit Kernel Capability Probe")

    lines = [
        f"# {title}",
        "",
        "## Run",
        "",
        f"- Timestamp: `{metadata.get('timestamp_utc', '')}`",
        f"- Resolve: `{metadata.get('product', '')} {metadata.get('version_string', '')}`",
        f"- Python: `{metadata.get('python', '')}`",
        f"- Platform: `{metadata.get('platform', '')}`",
        f"- Project: `{metadata.get('project_name', '')}`",
        "",
        "## Counts",
        "",
    ]
    for status in sorted(PROBE_STATUSES):
        lines.append(f"- `{status}`: {counts.get(status, 0)}")

    if artifacts:
        lines.extend(["", "## Artifacts", ""])
        for key, value in artifacts.items():
            lines.append(f"- `{key}`: `{value}`")

    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        by_category.setdefault(record["category"], []).append(record)

    lines.extend(["", "## Records", ""])
    for category in sorted(by_category):
        lines.extend([f"### {category}", ""])
        lines.append("| Name | Status | Notes |")
        lines.append("|---|---:|---|")
        for record in by_category[category]:
            details = record.get("details", {})
            note_parts = []
            for key in ("reason", "read", "write", "readback", "restore", "page", "item_type"):
                if key in details:
                    note_parts.append(f"{key}={json.dumps(details[key], default=str)}")
            if not note_parts and details:
                note_parts.append(json.dumps(details, default=str, sort_keys=True)[:220])
            notes = "; ".join(note_parts).replace("|", "\\|")
            lines.append(
                f"| `{record['name']}` | `{record['status']}` | {notes} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
