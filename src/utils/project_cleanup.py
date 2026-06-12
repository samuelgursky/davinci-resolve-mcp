"""Best-effort deletion of disposable Resolve projects.

DeleteProject is flaky on some Resolve builds: it silently returns False when
the target is (or was very recently) the current project, and occasionally on
the first attempt even when it isn't. Disposable test projects then linger in
the project library. This helper centralizes the mitigation so every
disposable-project flow gets it for free:

1. make sure the target is not the current project (load a fallback project,
   or close the target if no fallback is available),
2. retry the delete once after a short pause,
3. report the leftover by name when it still fails, so callers can surface it
   instead of silently leaking.
"""

import time
from typing import Any, Dict, Optional


def delete_project_safely(
    pm: Any,
    name: str,
    *,
    switch_to: Optional[str] = None,
    retries: int = 1,
    delay_seconds: float = 1.0,
) -> Dict[str, Any]:
    """Delete project `name` via project-manager handle `pm`, working around
    DeleteProject flakiness. Returns {success, attempts, leftover, detail}.

    `switch_to`: project to load first when `name` is current (e.g. the
    project that was open before the disposable one was created). Without it,
    the current project is closed instead.
    """
    attempts = 0
    detail = ""
    try:
        current = None
        try:
            project = pm.GetCurrentProject()
            current = project.GetName() if project else None
        except Exception:
            current = None
        if current == name:
            switched = False
            if switch_to and switch_to != name:
                try:
                    switched = bool(pm.LoadProject(switch_to))
                except Exception:
                    switched = False
            if not switched:
                try:
                    project = pm.GetCurrentProject()
                    if project is not None:
                        pm.CloseProject(project)
                except Exception:
                    pass

        last_error = None
        for attempt in range(1 + max(0, int(retries))):
            attempts = attempt + 1
            try:
                if bool(pm.DeleteProject(name)):
                    return {"success": True, "attempts": attempts, "leftover": None, "detail": ""}
                last_error = "DeleteProject returned False"
            except Exception as exc:
                last_error = str(exc)
            if attempt < retries:
                time.sleep(max(0.0, delay_seconds))
        detail = last_error or "DeleteProject failed"
    except Exception as exc:
        detail = str(exc)
    return {"success": False, "attempts": attempts, "leftover": name, "detail": detail}
