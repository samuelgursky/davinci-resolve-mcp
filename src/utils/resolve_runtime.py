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
import re
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


_PID_PREFIX = re.compile(r"^\s*(\d+)\s+(.*)$")


def _run_ps(columns: str) -> Optional[List[str]]:
    """`ps -Awwo <columns>` as lines, or None when it cannot be run.

    `-ww` on purpose: without it BSD ps may cut long command lines to the
    terminal width, and a cut line no longer ends in the executable. Not
    reproduced here (the Resolve path is 70 characters), but the second-
    instance guard should not depend on where a launch argument happens to
    fall relative to a column limit.
    """
    try:
        out = subprocess.run(
            ["ps", "-Awwo", columns], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10, check=False,
        )
    except Exception:  # pragma: no cover - defensive; an unknown answer is None
        return None
    if out.returncode != 0 and not out.stdout:
        return None
    return (out.stdout or "").splitlines()


def _split_pid(line: str, index: int):
    """(pid, field) for a `pid=,<col>=` row; a row with no pid gets a synthetic one.

    The synthetic pid is the row index, so two column listings of the same
    length join row-by-row. That is what keeps a fake process table written as
    bare command lines (the shape every existing test uses) meaningful: it is
    read as both the executable column and the argv column of one process.
    """
    match = _PID_PREFIX.match(line)
    if match:
        return int(match.group(1)), match.group(2)
    return -(index + 1), line


def _windows_wmic_rows(stdout: str) -> List[Dict[str, Optional[str]]]:
    """WMIC prints one command line per row, under a `CommandLine` header.

    The header row and WMIC's blank padding rows are left in rather than
    filtered: they are not Resolve command lines, so the executable match
    drops them, and a second filter here would be a second place for that
    decision to drift. There is no pid column to read, so pids are synthetic
    and negative — they exist only to key the row, never to name a process.
    """
    return [{"pid": -(index + 1), "comm": None, "args": line}
            for index, line in enumerate(stdout.splitlines())]


def _windows_cim_rows(stdout: str) -> List[Dict[str, Optional[str]]]:
    """`ProcessId`, `ExecutablePath` and `CommandLine`, tab-separated per row.

    Four columns rather than the command line alone, because they fail
    independently exactly as they do on POSIX. Measured on build 26200 by the
    reporter of #210, querying as an unelevated user: for a process the caller
    cannot fully read, CIM still returns the row with `ProcessId` and `Name`
    populated and `CommandLine` NULL — the *column* is access-restricted, not
    the row. Reading only the command line would turn such an instance into no
    row at all: an empty list, which does not mean "undeterminable", it means
    "nothing is running", and that is the answer that launches a second
    Resolve on top of a live one.

    `Name` rather than `ExecutablePath` alone is the reason this holds. That
    measurement showed `Name` surviving the access restriction; it did not
    show `ExecutablePath` surviving it, and for a protected process that field
    is commonly empty too. So the executable column falls back to the bare
    process name, which `RESOLVE_PROCESS_PATTERNS` already matches — enough to
    prove an instance is up, while the mode stays honestly unknown, since
    `-nogui` is only ever visible in the command line.

    Split at most three times: a command line may itself contain tabs, and it
    is the last field, so everything after the third separator belongs to it.
    """
    rows: List[Dict[str, Optional[str]]] = []
    for index, line in enumerate(stdout.splitlines()):
        if not line.strip():
            continue
        fields = line.split("\t", 3)
        fields += [""] * (4 - len(fields))
        try:
            pid = int(fields[0].strip())
        except ValueError:
            pid = -(index + 1)
        rows.append({"pid": pid,
                     "comm": fields[2].strip() or fields[1].strip() or None,
                     "args": fields[3].strip() or None})
    return rows


#: PowerShell equivalent of the WMIC query, emitting the four columns above.
#: The output encoding is forced because the default console codepage mangles
#: a non-ASCII install path before Python ever sees it.
_CIM_COMMAND = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
    "Get-CimInstance Win32_Process -Filter \"name='Resolve.exe'\" | "
    "ForEach-Object { \"$($_.ProcessId)`t$($_.Name)`t$($_.ExecutablePath)`t$($_.CommandLine)\" }"
)

#: Readers for the Windows process table, tried in order until one answers.
#:
#: WMIC first, so a machine that still has it behaves exactly as it did before
#: — but **WMIC was removed in Windows 11 build 26200** and is neither on PATH
#: nor at its old System32\wbem location, so on current Windows it raises
#: FileNotFoundError and every tool refused with "Resolve is not running"
#: while Resolve sat in front of the user (#210). Keeping the old reader first
#: costs nothing precisely because absence fails instantly rather than burning
#: the timeout. Windows PowerShell 5.1 ships with Windows; `pwsh` is the
#: cross-platform 7.x binary, tried last for a machine that has only that one.
#:
#: `None` is returned only when NO reader ran. A reader that ran and found
#: nothing returns an empty list, which is a different answer.
WINDOWS_PROCESS_READERS = (
    (["wmic", "process", "where", "name='Resolve.exe'", "get", "CommandLine"],
     _windows_wmic_rows),
    (["powershell", "-NoProfile", "-NonInteractive", "-Command", _CIM_COMMAND],
     _windows_cim_rows),
    (["pwsh", "-NoProfile", "-NonInteractive", "-Command", _CIM_COMMAND],
     _windows_cim_rows),
)


def _process_table() -> Optional[List[Dict[str, Optional[str]]]]:
    """One row per process: `{pid, comm, args}`, or None when undeterminable.

    Two columns because they fail independently. `args` is the argument
    vector, the only place `-nogui` is visible — but the kernel refuses to
    expose it for some processes (ps prints `(Resolve)` in parentheses) and a
    launch argument after the path breaks a suffix match on it. `comm` is the
    executable path as the kernel knows it — on macOS the full path — and it
    is readable whenever the process is. An instance is counted on EITHER;
    the mode is read from argv when argv is readable.

    None rather than an empty list on failure: an unanswerable question must
    not become "nothing is running", which is the answer that leads to
    launching a second instance on top of a live one.
    """
    if platform.system().lower() == "windows":
        # `tasklist` prints no command line, so the flag is invisible there.
        # The readers below do print it, which is what makes headless
        # detection possible on Windows at all.
        #
        # Decoded explicitly: `text=True` alone decodes with the locale
        # codepage, which raises UnicodeDecodeError on a byte cp1252 has no
        # mapping for — and this read is the input to the second-instance
        # guard, so it must fail to "cannot tell", never to an exception.
        # ASCII is byte-identical under both codecs, so the matching this
        # feeds is unchanged; what these readers emit for a non-ASCII install
        # path on a non-English Windows is not something we can verify here.
        for reader, parse in WINDOWS_PROCESS_READERS:
            try:
                out = subprocess.run(
                    reader, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=10, check=False,
                )
            except Exception:
                continue  # this reader is unusable here; try the next one
            if out.returncode != 0 and not (out.stdout or "").strip():
                continue
            return parse(out.stdout or "")
        return None

    comm_lines = _run_ps("pid=,comm=")
    args_lines = _run_ps("pid=,args=")
    if comm_lines is None and args_lines is None:
        return None
    rows: Dict[int, Dict[str, Optional[str]]] = {}
    for index, line in enumerate(comm_lines or []):
        pid, comm = _split_pid(line, index)
        rows.setdefault(pid, {"pid": pid, "comm": None, "args": None})["comm"] = comm
    for index, line in enumerate(args_lines or []):
        pid, args = _split_pid(line, index)
        rows.setdefault(pid, {"pid": pid, "comm": None, "args": None})["args"] = args
    return list(rows.values())


def _process_lines() -> Optional[List[str]]:
    """Argument vectors of every process, kept for callers that read only argv."""
    table = _process_table()
    if table is None:
        return None
    return [row["args"] for row in table if row["args"] is not None]


def _matches_pattern(executable: str) -> bool:
    """Does this bare executable path name a Resolve application?"""
    return any(executable.endswith(pattern) for pattern in RESOLVE_PROCESS_PATTERNS)


def _is_resolve_command(line: str) -> bool:
    r"""Is this command line a Resolve *executable*, not merely a mention of one?

    A plain substring test matches any process whose command line happens to
    contain the path — including a shell running a script that references it.
    Observed: a `zsh -c '... /Applications/DaVinci Resolve/.../Resolve -nogui ...'`
    was counted as a second Resolve instance, which made `instances` wrong and
    made a launch refuse with "a Resolve is running in the other mode".

    A real Resolve command line is the executable path, optionally followed by
    flags. So strip trailing flag tokens and require what remains to *end* with
    the pattern. That survives the spaces in "DaVinci Resolve.app" (no splitting
    on whitespace) while rejecting a path buried mid-command.

    Windows quotes that path. WMIC prints the executable wrapped in double
    quotes whenever it contains spaces, which the default install path always
    does (`"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"`),
    so the line ends in `"` and `endswith("Resolve.exe")` was false on every
    stock Windows machine — `runtime_mode` reported nothing running while the
    same server was driving that very instance, and the second-instance guard
    in `get_resolve()` lost its input. Reported in #150. A leading quote means
    the executable is exactly what sits inside the first quoted span; anything
    after the closing quote is arguments, and the flag loop never sees it.
    """
    return _matches_pattern(_executable_from_line(line))


def _executable_from_line(line: str) -> str:
    """The executable path from a command line, with argument tokens removed.

    Split out of `_is_resolve_command` so the install-location lookup below
    agrees with the "is this Resolve" test about where the path ends. See that
    function's docstring for why the quoting and flag-stripping rules are these.
    """
    text = line.strip()
    if text.startswith('"'):
        close = text.find('"', 1)
        if close > 1:
            return text[1:close]
    # A launch ARGUMENT after the path — a project file, most likely — is not a
    # flag, so the flag-stripping loop below leaves it attached and the suffix
    # test fails. If the line STARTS with a path that ends in a Resolve pattern
    # at a token boundary, that path is the executable, whatever follows it.
    # The prefix must contain no quote (a launcher quoting the path) and no
    # flag token (`/bin/sh -c /opt/resolve/bin/resolve` names Resolve without
    # being it), which keeps the "mere mention" cases out.
    for pattern in RESOLVE_PROCESS_PATTERNS:
        cut = text.find(pattern)
        while cut != -1:
            end = cut + len(pattern)
            prefix = text[:end]
            at_boundary = end == len(text) or text[end].isspace()
            if at_boundary and '"' not in prefix and " -" not in prefix:
                return prefix
            cut = text.find(pattern, cut + 1)
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
    return text


def _argv_unreadable(args: Optional[str]) -> bool:
    """ps prints `(name)` when the kernel will not hand over the argument vector."""
    if args is None:
        return True
    text = args.strip()
    return text.startswith("(") and text.endswith(")")


def _resolve_rows() -> Optional[List[Dict[str, Optional[str]]]]:
    """Process-table rows that are a running Resolve application."""
    table = _process_table()
    if table is None:
        return None
    matched = []
    for row in table:
        args = row.get("args")
        comm = row.get("comm")
        by_args = args is not None and not _argv_unreadable(args) and _is_resolve_command(args)
        by_comm = comm is not None and _matches_pattern(comm.strip())
        if by_args or by_comm:
            matched.append(row)
    return matched


def resolve_processes() -> Optional[List[str]]:
    """Command lines of running Resolve applications, or None if undeterminable.

    A row whose argv is unreadable reports its executable path instead, so a
    caller still sees WHICH Resolve is up even when it cannot see how it was
    started.
    """
    rows = _resolve_rows()
    if rows is None:
        return None
    return [row["args"] if not _argv_unreadable(row.get("args")) else (row.get("comm") or "")
            for row in rows]


#: Where the scripting library sits relative to the Resolve executable. The
#: library ships *inside* the application, so the running executable's own path
#: is the only locator that is right by construction — every hardcoded install
#: root is a guess about where the user chose to put Resolve.
_LIB_RELATIVE_TO_EXECUTABLE = {
    "windows": ("fusionscript.dll",),
    "darwin": ("../Libraries/Fusion/fusionscript.so",),
    "linux": (
        "../libs/Fusion/fusionscript.so",
        "../libs/fusionscript.so",
        "fusionscript.so",
    ),
}


def running_resolve_lib() -> Optional[str]:
    """Scripting library of the *running* Resolve, or None.

    Blackmagic's own `DaVinciResolveScript.py` falls back to one hardcoded
    install path per platform, and this project's defaults mirror it. A Resolve
    installed anywhere else — a second drive, an external volume, a custom
    directory — is therefore invisible to both, and the failure is silent: the
    module imports, the DLL behind it does not load, and the user is told the
    edition or the preference is at fault.

    The running process settles it without guessing. Returns None when nothing
    is running, the process list is unavailable, or the derived path does not
    exist; callers keep their existing defaults in that case.
    """
    processes = resolve_processes()
    if not processes:
        return None
    suffixes = _LIB_RELATIVE_TO_EXECUTABLE.get(platform.system().lower(), ())
    for line in processes:
        executable_dir = os.path.dirname(_executable_from_line(line))
        if not executable_dir:
            continue
        for suffix in suffixes:
            candidate = os.path.normpath(
                os.path.join(executable_dir, *suffix.split("/"))
            )
            if os.path.isfile(candidate):
                return candidate
    return None


def runtime_mode() -> Dict[str, Any]:
    """`{running, headless, instances, command_lines, determinable}`.

    `headless` is None whenever it cannot be established — nothing running, or
    the process list unavailable. Callers must not read None as False; a wrong
    "it has a UI" is what makes an agent wait for a dialog that will never open.
    """
    rows = _resolve_rows()
    if rows is None:
        return {
            "determinable": False,
            "running": None,
            "headless": None,
            "instances": None,
            "command_lines": [],
        }
    if not rows:
        return {
            "determinable": True,
            "running": False,
            "headless": None,
            "instances": 0,
            "command_lines": [],
        }
    readable = [row["args"] for row in rows if not _argv_unreadable(row.get("args"))]
    # Any headless instance makes the reachable one headless: only one Resolve
    # can hold the singleton, so a second is a conflict to report rather than
    # a mode to average. An instance counted on its executable path alone has
    # an argv this process cannot read, so unless another instance shows the
    # flag the mode is UNKNOWN — None, never False: a wrong "it has a UI" is
    # what makes an agent wait for a dialog that will never open.
    headless: Optional[bool] = any(HEADLESS_FLAG in line for line in readable)
    if not headless and len(readable) < len(rows):
        headless = None
    return {
        "determinable": True,
        "running": True,
        "headless": headless,
        "instances": len(rows),
        "command_lines": [row["args"] if not _argv_unreadable(row.get("args"))
                          else (row.get("comm") or "") for row in rows],
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
