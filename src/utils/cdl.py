"""CDL normalization helpers shared by compound and granular servers."""

from typing import Any, Dict

_CDL_KEY_ALIASES = {
    "nodeindex": "NodeIndex",
    "node_index": "NodeIndex",
    "slope": "Slope",
    "offset": "Offset",
    "power": "Power",
    "saturation": "Saturation",
}


def canonicalize_cdl_keys(cdl: Any) -> Any:
    """Canonicalize lowercase/snake_case CDL keys to Resolve's PascalCase keys."""
    if not isinstance(cdl, dict):
        return cdl
    out: Dict[str, Any] = {}
    for key, value in cdl.items():
        canonical = _CDL_KEY_ALIASES.get(str(key).lower(), key)
        if canonical not in out or key == canonical:
            out[canonical] = value
    return out


def normalize_cdl_payload(cdl: Any) -> Any:
    """Resolve's SetCDL expects strings like ``"1.0 1.0 1.0"`` instead of arrays."""
    if not isinstance(cdl, dict):
        return cdl
    canonical_cdl = canonicalize_cdl_keys(cdl)
    out: Dict[str, Any] = {}
    for key, value in canonical_cdl.items():
        if isinstance(value, (list, tuple)):
            out[key] = " ".join(str(item) for item in value)
        elif isinstance(value, bool):
            out[key] = str(value)
        elif isinstance(value, (int, float)):
            out[key] = str(value)
        else:
            out[key] = value
    return out
