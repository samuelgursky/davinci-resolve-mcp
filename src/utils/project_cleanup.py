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

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("davinci-resolve-mcp.project_cleanup")


#: The name Resolve gives the project it opens when it has nothing else to open.
#: It has never been saved and has no location, so it cannot be saved.
UNSAVED_DEFAULT_PROJECT = "Untitled Project"


def save_project_if_safe(pm: Any) -> Dict[str, Any]:
    """`SaveProject()`, unless the current project is the one that hangs on it.

    `ProjectManager.SaveProject()` cannot succeed on the never-saved default
    `Untitled Project` — no location, and no `SaveProjectAs` to give it one. The
    two modes fail differently, and one of them is fatal:

      - GUI: returns False.
      - Headless: **blocks forever.** Measured on a cold `-nogui` boot with the
        database verified attached immediately beforehand — no return after 45
        seconds, client parked in `Fusion::RemoteApp::WaitPkt`. Resolve wants a
        Save-As dialog and waits for an answer that cannot arrive. Interrupting
        it degrades the instance further.

    So the guard is not politeness, it is the difference between a no-op and a
    dead unattended session. Skipping the save costs nothing: there is nothing
    to save on a project that has never had a location.

    Returns ``{saved, skipped, project, reason}``.
    """
    try:
        project = pm.GetCurrentProject()
    except Exception as exc:
        return {"saved": False, "skipped": True, "project": None, "reason": repr(exc)}
    if project is None:
        return {"saved": False, "skipped": True, "project": None, "reason": "no current project"}
    try:
        name = project.GetName()
    except Exception as exc:
        return {"saved": False, "skipped": True, "project": None, "reason": repr(exc)}
    if name == UNSAVED_DEFAULT_PROJECT:
        return {"saved": False, "skipped": True, "project": name,
                "reason": "never-saved default project; SaveProject hangs on it headless"}
    try:
        return {"saved": bool(pm.SaveProject()), "skipped": False, "project": name, "reason": ""}
    except Exception as exc:
        return {"saved": False, "skipped": False, "project": name, "reason": repr(exc)}


def stop_render_before_close(project: Any, *, wait_seconds: float = 8.0) -> Dict[str, Any]:
    """Stop any in-progress render and wait for the flag to clear.

    Closing or deleting a project while its render runs orphans the render and
    wedges Resolve's whole pipeline: IsRenderingInProgress sticks True on every
    subsequent project, new jobs sit at 0%, StartRendering starts returning
    False, and Quit() is refused behind a modal (api_truth, measured live on
    Studio 19.1.3.7). Returns {safe, was_rendering, waited_seconds, detail}.
    A flag that stays True after StopRendering at idle is the stuck state —
    only restarting Resolve clears it, so `safe` comes back False.
    """
    import time as _time

    try:
        rendering = bool(project.IsRenderingInProgress())
    except Exception:
        return {"safe": True, "was_rendering": False, "waited_seconds": 0.0,
                "detail": "IsRenderingInProgress unavailable; proceeding"}
    if not rendering:
        return {"safe": True, "was_rendering": False, "waited_seconds": 0.0, "detail": ""}
    try:
        project.StopRendering()
    except Exception:
        pass
    waited = 0.0
    while waited < wait_seconds:
        _time.sleep(0.5)
        waited += 0.5
        try:
            if not project.IsRenderingInProgress():
                return {"safe": True, "was_rendering": True,
                        "waited_seconds": waited, "detail": "render stopped"}
        except Exception:
            break
    return {
        "safe": False, "was_rendering": True, "waited_seconds": waited,
        "detail": (
            "IsRenderingInProgress is still True after StopRendering and "
            f"{waited:.0f}s — closing now would orphan the render and wedge "
            "Resolve's render pipeline (stuck flag, 0% jobs, refused Quit). "
            "If Resolve is idle at 0% CPU this is the already-stuck state and "
            "only restarting Resolve clears it."
        ),
    }


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
            # Deleting the current project kills its render anyway — stopping
            # first is strictly better than orphaning it (the wedge documented
            # in stop_render_before_close). Refuse only when the flag will not
            # clear, which is the already-wedged state where the delete cannot
            # end well either.
            try:
                project = pm.GetCurrentProject()
            except Exception:
                project = None
            if project is not None:
                render_state = stop_render_before_close(project)
                if not render_state.get("safe"):
                    return {"success": False, "attempts": 0, "leftover": name,
                            "detail": render_state["detail"]}
            # CloseProject ALWAYS, and first. It is what releases the session's
            # lock on the project; switching away with LoadProject does not, and
            # DeleteProject then returns False permanently — retries never help.
            # Measured on Studio 19.1.3.7: after a LoadProject-away, six retries
            # a second apart all failed; after a CloseProject the same delete
            # succeeded on the first attempt.
            try:
                project = pm.GetCurrentProject()
                if project is not None:
                    pm.CloseProject(project)
            except Exception:
                pass
            # Then land on a named project if one was named. CloseProject drops
            # the session onto a fresh, never-saved "Untitled Project" that
            # cannot be saved, so the next close or switch raises a modal no
            # script can dismiss. That is a wedged application, not a tidy-up.
            if switch_to and switch_to != name:
                # A discarded False leaves the session on the unsaveable
                # "Untitled Project" this comment exists to avoid, and the next
                # close or switch raises a modal no script can dismiss. Logged
                # loudly: the caller is mid-delete and cannot be aborted here,
                # but a silent wedge is what made this hard to diagnose.
                try:
                    if not pm.LoadProject(switch_to):
                        logger.error(
                            "LoadProject(%r) returned False after closing %r; the "
                            "session is left on an unsaveable Untitled Project and "
                            "the next close will raise a modal", switch_to, name,
                        )
                except Exception as exc:
                    logger.error("LoadProject(%r) raised after closing %r: %s",
                                 switch_to, name, exc)

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
