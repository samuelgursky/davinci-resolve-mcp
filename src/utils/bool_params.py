"""Boolean coercion helpers for tool parameters and preferences."""

from __future__ import annotations

from typing import Any, Dict, Optional


_TRUE_STRINGS = {"1", "true", "yes", "on"}
_FALSE_STRINGS = {"0", "false", "no", "off"}


def coerce_bool(value: Any, default: bool = False) -> bool:
    """Return a predictable bool for user-facing params and config values."""
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
        return default
    return bool(value)


def explicit_bool_param(params: Optional[Dict[str, Any]], *keys: str) -> Optional[bool]:
    """Coerce the first present key, or None when none of the keys are present."""
    if not isinstance(params, dict):
        return None
    for key in keys:
        if key in params:
            return coerce_bool(params[key])
    return None
