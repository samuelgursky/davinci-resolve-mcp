"""Declarative parameter validation for compound-tool actions.

Input validation in the server has historically been scattered: hand-built
"Must be one of" strings, ad-hoc empty/range/path checks inline in each action.
This module centralizes it into one declarative validator that emits consistent,
agent-friendly error messages, so the validation bug class is closed once rather
than patched action by action.

Usage:

    err, clean = validate(params, {
        "path": {"type": str, "required": True, "non_empty": True, "parent_dir_exists": True},
        "mark_in": {"type": int, "required": True},
        "mark_out": {"type": int, "required": True},
        "kind": {"enum": ["all", "video", "audio"], "default": "all"},
    }, invariants=[
        lambda c: "mark_in must be <= mark_out" if c["mark_in"] > c["mark_out"] else None,
    ])
    if err:
        return _err(err)
    # use clean[...] — coerced + defaulted

Rule keys: ``type`` (int/str/float/bool), ``required``, ``default``, ``enum``,
``min``, ``max``, ``non_empty`` (str), ``parent_dir_exists`` (str path).
"""
import os
from typing import Any, Callable, Dict, List, Optional, Tuple


def _coerce(name: str, value: Any, t: type) -> Tuple[Any, Optional[str]]:
    if t is bool:
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on"), None
        return bool(value), None
    if t is int:
        try:
            return int(value), None
        except (TypeError, ValueError):
            return None, f"'{name}' must be an integer"
    if t is float:
        try:
            return float(value), None
        except (TypeError, ValueError):
            return None, f"'{name}' must be a number"
    if t is str:
        if not isinstance(value, str):
            return None, f"'{name}' must be a string"
        return value, None
    return value, None


def validate(
    params: Dict[str, Any],
    rules: Dict[str, Dict[str, Any]],
    invariants: Optional[List[Callable[[Dict[str, Any]], Optional[str]]]] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Validate ``params`` against ``rules``.

    Returns ``(None, cleaned)`` on success (cleaned has coercions + defaults
    applied), or ``(error_message, None)`` on the first violation.
    """
    cleaned = dict(params)

    for name, rule in rules.items():
        present = name in params and params[name] is not None
        if not present:
            if rule.get("required"):
                return f"'{name}' is required", None
            if "default" in rule:
                cleaned[name] = rule["default"]
            continue

        val = params[name]
        t = rule.get("type")
        if t is not None:
            val, err = _coerce(name, val, t)
            if err:
                return err, None

        if "enum" in rule and val not in rule["enum"]:
            return f"'{name}' must be one of: {', '.join(map(str, rule['enum']))}", None
        if rule.get("non_empty") and isinstance(val, str) and not val.strip():
            return f"'{name}' must be non-empty", None
        if "min" in rule and val < rule["min"]:
            return f"'{name}' must be >= {rule['min']}", None
        if "max" in rule and val > rule["max"]:
            return f"'{name}' must be <= {rule['max']}", None
        if rule.get("parent_dir_exists"):
            parent = os.path.dirname(os.path.expanduser(str(val)))
            if parent and not os.path.isdir(parent):
                return f"'{name}' target directory does not exist: {parent}", None

        cleaned[name] = val

    for inv in (invariants or []):
        msg = inv(cleaned)
        if msg:
            return msg, None

    return None, cleaned
