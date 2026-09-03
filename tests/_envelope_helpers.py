"""Helpers for tests that assert a tool's exact return shape.

Two additive private keys ride alongside a tool's domain payload: `_versioning`
(from the destructive hook) and `_operation` (the operation envelope). Both are
namespaced precisely so they cannot shadow a domain key, which also means a
test asserting the domain shape should not have to know about them.

`domain_payload` strips them. Use `assert_enveloped` when the point of the test
is that the envelope arrived at all.
"""
from __future__ import annotations

from typing import Any, Dict

PRIVATE_KEYS = ("_versioning", "_operation")


def domain_payload(result: Any) -> Any:
    """A result with the additive private envelopes removed."""
    if not isinstance(result, dict):
        return result
    return {k: v for k, v in result.items() if k not in PRIVATE_KEYS}


def operation_envelope(result: Any) -> Dict[str, Any]:
    """The `_operation` envelope, or {} when the call carried none."""
    if not isinstance(result, dict):
        return {}
    envelope = result.get("_operation")
    return envelope if isinstance(envelope, dict) else {}
