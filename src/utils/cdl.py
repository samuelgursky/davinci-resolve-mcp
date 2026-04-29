"""CDL normalization helpers shared by compound and granular servers."""

from typing import Any, Dict


def normalize_cdl_payload(cdl: Any) -> Any:
    """Resolve's SetCDL expects strings like ``"1.0 1.0 1.0"`` instead of arrays."""
    if not isinstance(cdl, dict):
        return cdl
    out: Dict[str, Any] = {}
    for key, value in cdl.items():
        if isinstance(value, (list, tuple)):
            out[key] = " ".join(str(item) for item in value)
        elif isinstance(value, bool):
            out[key] = str(value)
        elif isinstance(value, (int, float)):
            out[key] = str(value)
        else:
            out[key] = value
    return out
