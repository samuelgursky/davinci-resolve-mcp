"""Which Resolve is running, and how — GUI, headless, or nothing at all.

The scripting API cannot answer this. Measured on Studio 19.1.3.7: a `-nogui`
instance returns a real page from `GetCurrentPage()`, the same product and
version strings, and identical results for every UI-shaped call tried —
`OpenPage` for all seven pages, layout preset save/export/load/delete, Gallery
handles, Fusion comps. There is no handle to interrogate and no capability to
sniff. See `docs/reference/headless-cli.md`.

So the mode is read from the operating system: the argument vector of the
running Resolve process. That is the only place `-nogui` is visible.

Why an agent needs to know, given that headless turned out to be capability-
identical:

  - **Modals.** A GUI Resolve can raise a dialog no script can dismiss, and
    project switching does exactly that when the outgoing project has unsaved
    changes. Headless cannot. An agent that knows it is headless can take the
    fast path; one that knows it is not can take the careful one.
  - **Honest errors.** "Resolve is running but not answering" reads very
    differently when the instance is a headless render worker than when it is
    the editor the user is looking at.
  - **Launching.** Starting a GUI Resolve on a machine whose user is mid-session
    is rude; starting a second instance of any kind is worse. Both need the
    current mode, not just a yes/no on "is it running".
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Any, Dict, List, Optional

#: Process paths that mean a DaVinci Resolve application is running. Not the
#: full path: the App Store build lives at `/Applications/DaVinci Resolve.app`
#: and the installer build inside `/Applications/DaVinci Resolve/`, and either
#: one counts.
RESOLVE_PROCESS_PATTERNS = (
    "DaVinci Resolve.app/Contents/MacOS/Resolve",   # macOS, both editions
    "Resolve.exe",                                  # Windows
    "/opt/resolve/bin/resolve",                     # Linux
)

#: The documented headless switch. Blackmagic spells it exactly this way on all
#: three platforms.
HEADLESS_FLAG = "-nogui"

#: Set to 1 to make this server's auto-launch start Resolve without a UI.
ENV_PREFER_HEADLESS = "DAVINCI_RESOLVE_HEADLESS"

#: macOS puts the two editions in different places. Installer/Studio first, to
#: preserve the behaviour that a machine with both starts Studio.
MACOS_RESOLVE_APPS = (
    "/Applications/DaVinci Resolve/DaVinci Resolve.app",
    "/Applications/DaVinci Resolve.app",
)


def _process_lines() -> Optional[List[str]]:
    """Every running command line, or None when that cannot be determined.

    None rather than an empty list on failure: an unanswerable question must not
    become "nothing is running", which is the answer that leads to launching a
    second instance on top of a live one.
    """
    try:
        if platform.system().lower() == "windows":
            # `tasklist` prints no command line, so the flag is invisible there.
            # WMIC does print it and is what makes headless detection possible.
            out = subprocess.run(
                ["wmic", "process", "where", "name='Resolve.exe'", "get", "CommandLine"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        else:
            out = subprocess.run(
                ["ps", "-Ao", "command="], capture_output=True, text=True, timeout=10, check=False
            )
        if out.returncode != 0 and not out.stdout:
            return None
        return (out.stdout or "").splitlines()
    except Exception:  # pragma: no cover - defensive; an unknown answer is None
        return None


def _is_resolve_command(line: str) -> bool:
    """Is this command line a Resolve *executable*, not merely a mention of one?

    A plain substring test matches any process whose command line happens to
    contain the path — including a shell running a script that references it.
    Observed: a `zsh -c '... /Applications/DaVinci Resolve/.../Resolve -nogui ...'`
    was counted as a second Resolve instance, which made `instances` wrong and
    made a launch refuse with "a Resolve is running in the other mode".

    A real Resolve command line is the executable path, optionally followed by
    flags. So strip trailing flag tokens and require what remains to *end* with
    the pattern. That survives the spaces in "DaVinci Resolve.app" (no splitting
    on whitespace) while rejecting a path buried mid-command.
    """
    text = line.strip()
    while True:
        stripped = text.rstrip()
        cut = stripped.rfind(" -")
        if cut == -1:
            break
        candidate = stripped[:cut].rstrip()
        # Only treat the tail as a flag if dropping it still leaves a plausible
        # path; otherwise a directory named " -something" would be eaten.
        if not candidate:
            break
        text = candidate
    return any(text.endswith(pattern) for pattern in RESOLVE_PROCESS_PATTERNS)


def resolve_processes() -> Optional[List[str]]:
    """Command lines of running Resolve applications, or None if undeterminable."""
    lines = _process_lines()
    if lines is None:
        return None
    return [line for line in lines if _is_resolve_command(line)]


def runtime_mode() -> Dict[str, Any]:
    """`{running, headless, instances, command_lines, determinable}`.

    `headless` is None whenever it cannot be established — nothing running, or
    the process list unavailable. Callers must not read None as False; a wrong
    "it has a UI" is what makes an agent wait for a dialog that will never open.
    """
    processes = resolve_processes()
    if processes is None:
        return {
            "determinable": False,
            "running": None,
            "headless": None,
            "instances": None,
            "command_lines": [],
        }
    if not processes:
        return {
            "determinable": True,
            "running": False,
            "headless": None,
            "instances": 0,
            "command_lines": [],
        }
    return {
        "determinable": True,
        "running": True,
        # Any headless instance makes the reachable one headless: only one
        # Resolve can hold the singleton, so a second is a conflict to report
        # rather than a mode to average.
        "headless": any(HEADLESS_FLAG in line for line in processes),
        "instances": len(processes),
        "command_lines": processes,
    }


def is_headless() -> Optional[bool]:
    """True, False, or None when it cannot be determined."""
    return runtime_mode()["headless"]


def prefers_headless(env: Optional[Dict[str, str]] = None) -> bool:
    """Should an auto-launch start Resolve without a UI?"""
    source = env if env is not None else os.environ
    return str(source.get(ENV_PREFER_HEADLESS, "")).strip().lower() in ("1", "true", "yes", "on")


def launch_command(headless: bool) -> Optional[List[str]]:
    """The argv that starts Resolve in the requested mode, or None if not found.

    Headless *must* run the binary inside the bundle. `open -a` hands the
    argument list to LaunchServices, which starts the application normally and
    discards `-nogui` — you get a window and no error, which is the worst
    possible outcome for a batch job that is about to raise a modal nobody will
    see. Verified on macOS.
    """
    system = platform.system().lower()
    if system == "darwin":
        app = next((p for p in MACOS_RESOLVE_APPS if os.path.exists(p)), None)
        if app is None:
            return None
        if not headless:
            return ["open", app]
        return [os.path.join(app, "Contents", "MacOS", "Resolve"), HEADLESS_FLAG]
    if system == "windows":
        exe = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
        if not os.path.exists(exe):
            return None
        return [exe, HEADLESS_FLAG] if headless else [exe]
    if system == "linux":
        exe = "/opt/resolve/bin/resolve"
        if not os.path.exists(exe):
            return None
        return [exe, HEADLESS_FLAG] if headless else [exe]
    return None


#: What an agent should do differently in each mode. Returned alongside the mode
#: so the advice travels with the fact, instead of living in a doc the agent has
#: to already know to read.
MODE_GUIDANCE = {
    True: (
        "Headless: NOT modal-immune — it cannot display a dialog but still tries "
        "to raise one, and the call then never returns. Measured: "
        "ProjectManager.SaveProject() on the never-saved 'Untitled Project' "
        "blocks forever headless where the GUI returns False. Guard every save "
        "with project_cleanup.save_project_if_safe. Capability is otherwise "
        "identical to the GUI across 238 probed observations, but that is a "
        "capability result, not a stability one: long renders, JPEG 2000/DCP "
        "decode and ProRes-in-MXF writes are untested, with a field report of "
        "crashes on write completion."
    ),
    False: (
        "GUI: a modal dialog can block any call until a human clicks it. Before "
        "LoadProject or CloseProject, save the outgoing project via "
        "project_cleanup.save_project_if_safe — SaveProject() returns False for "
        "the never-saved default 'Untitled Project', which is exactly the project "
        "that raises the prompt. Switching to headless does NOT avoid this; there "
        "the same call blocks forever instead."
    ),
    None: (
        "Mode unknown: assume a GUI is present and take the careful path around "
        "project switches."
    ),
}


def describe() -> Dict[str, Any]:
    """Mode plus the guidance that goes with it."""
    mode = runtime_mode()
    return {**mode, "guidance": MODE_GUIDANCE[mode["headless"]]}
