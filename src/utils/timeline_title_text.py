"""Helpers for Edit-page Text+ / generator text via undocumented TimelineItem.GetProperty keys."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

TITLE_TEXT_KEY_HINTS = (
    "styled text",
    "styledtext",
    "text+",
    "rich text",
    "caption",
    "subtitle",
)


def flatten_timeline_item_properties(props: Any) -> Dict[str, Any]:
    if props is None:
        return {}
    if isinstance(props, dict):
        return {str(k): v for k, v in props.items()}
    return {}


def timeline_item_get_property_map(
    item: Any, serialize_fn: Callable[[Any], Any]
) -> Tuple[Dict[str, Any], Optional[str]]:
    last_err: Optional[str] = None
    saw_empty_success = False
    for getter in (lambda: item.GetProperty(), lambda: item.GetProperty("")):
        try:
            raw = getter()
        except TypeError:
            continue
        except Exception as exc:
            last_err = str(exc)
            continue
        flat = flatten_timeline_item_properties(serialize_fn(raw))
        if flat:
            return flat, None
        saw_empty_success = True
    return {}, None if saw_empty_success else last_err or "GetProperty failed"


def candidate_title_property_keys(flat: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Prefer dict keys that may hold Text+ / generator rich text (not in public API docs)."""
    candidates: List[Dict[str, Any]] = []
    for key, value in flat.items():
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if not stripped:
            continue
        lk = key.lower()
        score = 0
        for hint in TITLE_TEXT_KEY_HINTS:
            if hint in lk:
                score += 10
        if stripped.startswith("<?xml") or ("<" in stripped and ">" in stripped):
            score += 5
        if lk == "text":
            score += 8
        if score > 0 or len(stripped) > 24:
            preview = stripped[:200] + ("…" if len(stripped) > 200 else "")
            candidates.append({"key": key, "score": score, "value_preview": preview})
    candidates.sort(key=lambda row: (-row["score"], row["key"]))
    return candidates


def escape_xml_text_body(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def plain_to_minimal_styled_xml(plain: str) -> str:
    """Best-effort Text+ styled payload when only plain copy is available; Resolve may normalize."""
    body = escape_xml_text_body(plain)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<StyledElement>"
        f"<Paragraph><TextRun>{body}</TextRun></Paragraph>"
        "</StyledElement>"
    )
