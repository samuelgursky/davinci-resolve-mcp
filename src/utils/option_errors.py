"""Say which option was wrong, and how — not merely that something was.

Issue #232 reported that `timeline.normalize_audio_level` "rejects every documented
option schema". It does not: every shape in `NormalizeAudioOptions` is accepted. But
the refusal read

    Unknown normalization options or non-dictionary options

which folds two unrelated failures into one sentence, names neither the offending
key nor the type actually received, and lists nothing that *would* be accepted. A
caller whose MCP client had serialised `options` to a JSON string — the one way to
produce that message while passing documented keys — had no way to tell that from a
typo, and neither did the report.

So the message is the bug worth fixing. These builders make a refusal answer three
questions: what was wrong, what was received, and what would have been accepted.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


def _type_name(value: Any) -> str:
    """A type name a caller will recognise from their own client's payload."""
    return {
        str: "a string",
        list: "a list",
        tuple: "a list",
        int: "a number",
        float: "a number",
        bool: "a boolean",
        type(None): "null",
    }.get(type(value), f"a {type(value).__name__}")


def reject_option_keys(
    options: Any,
    accepted: Iterable[str],
    label: str,
    *,
    allow_empty: bool = True,
) -> Optional[str]:
    """Refuse a malformed options mapping, or return None when it is usable.

    The two failures are reported separately because they have different causes and
    different fixes: a non-mapping is almost always the client serialising a nested
    object, while an unknown key is a typo or a stale field name.
    """
    accepted = tuple(accepted)
    if not isinstance(options, dict):
        hint = ""
        if isinstance(options, str):
            # By far the likeliest way to reach here with correct keys: some MCP
            # clients JSON-encode nested objects. Say so, because the caller is
            # looking at a payload that appears correct.
            hint = (
                " It looks like a JSON string — send options as a nested object, "
                "not as encoded text."
            )
        return (
            f"{label} options must be an object with any of "
            f"{', '.join(accepted)}; received {_type_name(options)}.{hint}"
        )
    if not options and not allow_empty:
        return (
            f"{label} options must not be empty; accepted keys are "
            f"{', '.join(accepted)}."
        )
    unknown = sorted(set(options) - set(accepted))
    if unknown:
        return (
            f"Unknown {label} option{'s' if len(unknown) > 1 else ''} "
            f"{', '.join(repr(k) for k in unknown)}; accepted keys are "
            f"{', '.join(accepted)}."
        )
    return None
