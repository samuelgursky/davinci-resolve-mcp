"""Test helpers for the structured error envelope landed in A1.

The legacy shape was `{"error": "<prose>"}`. The new shape is
`{"error": {"message": str, "code": str, "category": str,
            "retryable": bool, "remediation": str?}}`.

These helpers let tests assert against the new shape without each test
needing to know the full structure.
"""
from __future__ import annotations
from typing import Any, Dict


def err_message(result: Dict[str, Any]) -> str:
    """Return the human-readable message from a result error, whatever the shape."""
    err = result.get("error") if isinstance(result, dict) else None
    if isinstance(err, dict):
        return str(err.get("message", ""))
    if isinstance(err, str):
        return err
    return ""


def err_code(result: Dict[str, Any]) -> str:
    err = result.get("error") if isinstance(result, dict) else None
    return str(err.get("code", "")) if isinstance(err, dict) else ""


def err_category(result: Dict[str, Any]) -> str:
    err = result.get("error") if isinstance(result, dict) else None
    return str(err.get("category", "")) if isinstance(err, dict) else ""


def is_err(result: Dict[str, Any]) -> bool:
    return isinstance(result, dict) and "error" in result and bool(result["error"])
