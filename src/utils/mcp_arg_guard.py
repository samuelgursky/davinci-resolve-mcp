"""Refuse tool arguments the tool's signature does not name (issue #372).

FastMCP validates a call's arguments with a pydantic model built from the tool
function's signature, and that model ignores keys it has no field for. For the
compound tools, which take `(action, params)`, a selector passed beside
`action` instead of inside `params` — `timeline(action="get_name",
timeline_name="vB")` — was therefore dropped before any server code ran, and
the call acted on the current timeline and answered success. Nothing
downstream could report it as `ignored_params`, because nothing downstream
ever saw it.

The check runs at the protocol boundary, before the tool is called, and
refuses rather than folding the keys into `params`: a guessed placement is
another way to act on something the caller did not ask for.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def accepted_arguments(tool: Any) -> Optional[set]:
    """The argument names `tool` accepts (field names and aliases), or None if unknown."""
    model = getattr(getattr(tool, "fn_metadata", None), "arg_model", None)
    fields = getattr(model, "model_fields", None)
    if not isinstance(fields, dict):
        return None
    names = set(fields)
    names.update(f.alias for f in fields.values() if getattr(f, "alias", None))
    return names


def unknown_arguments(tool: Any, arguments: Optional[Dict[str, Any]]) -> List[str]:
    """Keys of `arguments` that `tool` has no parameter for, sorted."""
    if not isinstance(arguments, dict) or not arguments:
        return []
    accepted = accepted_arguments(tool)
    if accepted is None:
        return []
    return sorted(str(k) for k in arguments if k not in accepted)


def refusal(tool_name: str, unknown: Iterable[str], arguments: Dict[str, Any],
            accepted: Optional[set]) -> Dict[str, Any]:
    """The error envelope for a call that passed arguments the tool does not take."""
    unknown = list(unknown)
    quoted = ", ".join(repr(k) for k in unknown)
    takes_params = bool(accepted) and "params" in accepted
    if takes_params:
        moved = dict(arguments.get("params") or {}) if isinstance(arguments.get("params"), dict) else {}
        moved.update({k: arguments[k] for k in unknown})
        message = (
            f"{tool_name} does not take {quoted} beside 'action'; this tool reads its "
            f"arguments from 'params'. Nothing was run: the key would have been dropped "
            f"and the call would have acted with it unset (for a timeline selector, on "
            f"the current timeline)."
        )
        remediation = f"Move {quoted} into params, e.g. params={moved!r}."
        state = {"unknown_arguments": unknown, "corrected_params": moved}
    else:
        message = (
            f"{tool_name} has no parameter {quoted}. Nothing was run: the key would "
            "have been dropped silently."
        )
        remediation = "Pass only the parameters the tool's input schema lists."
        state = {"unknown_arguments": unknown}
    if accepted:
        state["accepted_arguments"] = sorted(accepted)
    return {
        "success": False,
        "error": {
            "message": message,
            "code": "UNKNOWN_ARGUMENTS",
            "category": "invalid_input",
            "retryable": True,
            "remediation": remediation,
            "state": state,
        },
    }
