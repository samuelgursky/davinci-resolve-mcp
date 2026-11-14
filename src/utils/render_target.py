"""Render TargetDir validation shared by the compound and granular servers.

`Project.SetRenderSettings` takes a TargetDir that does not exist and answers
True; the refusal only surfaces later, at `AddRenderJob` or when the job
starts (issue #368). The server runs on the machine Resolve renders on, so a
directory this process cannot see is one Resolve cannot write to either.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


def missing_target_dir(settings: Any) -> Optional[str]:
    """The TargetDir from `settings` when it names no existing directory, else None.

    Only a non-empty string is checked; an absent key leaves the project's
    current target alone, and other types are left to Resolve to refuse.
    """
    if not isinstance(settings, dict):
        return None
    target = settings.get("TargetDir")
    if not isinstance(target, str) or not target.strip():
        return None
    return None if os.path.isdir(target) else target


def missing_target_dir_message(target: str) -> str:
    return (
        f"TargetDir does not exist: {target}. Nothing was sent to SetRenderSettings; "
        "Resolve would accept it here and refuse only at add_job or render start."
    )


def missing_target_dir_error(settings: Any) -> Optional[Dict[str, Any]]:
    """Fields for a refusal, or None when TargetDir is absent or exists."""
    target = missing_target_dir(settings)
    if target is None:
        return None
    return {
        "message": missing_target_dir_message(target),
        "code": "TARGET_DIR_NOT_FOUND",
        "category": "invalid_input",
        "remediation": "Create the directory first, or pass an existing TargetDir.",
        "state": {"TargetDir": target},
    }
