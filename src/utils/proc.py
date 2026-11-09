"""Subprocess helpers that are safe to call while the MCP stdio server is live.

The server owns the JSON-RPC stdin/stdout while serving over stdio. A child
process that inherits stdin can race-read bytes off the protocol stream and
corrupt it; ``capture_output`` only redirects stdout/stderr. These wrappers
default ``stdin`` to ``DEVNULL`` so subprocess hygiene is centralized rather
than re-applied at every call site.

``windows_pid_alive`` lives here too: the Windows replacement for the
``os.kill(pid, 0)`` liveness probe, which on Windows terminates the process.

``option_like_path_error`` is the Python twin of ``assertNotOption`` in
``resolve-advanced/server/spawn-guard.mjs``. A caller path that lands in a
positional argv slot and starts with ``-`` is read by the child as an option:
ffprobe given ``-report`` writes a log into its working directory (#350).
Check it wherever a caller path is the bare operand of a spawned program.
"""
import subprocess
from typing import Any, Optional

#: Error code shared with the advanced server's ``assertNotOption``.
OPTION_LIKE_PATH_REFUSED = "OPTION_LIKE_PATH_REFUSED"


def option_like_path_error(value: Any, label: str = "path") -> Optional[str]:
    """Why ``value`` cannot be a positional argv operand, or None when it can.

    A string starting with ``-`` is refused, not rewritten to ``./-...``, so a
    path gets the same answer from this server and the advanced one. An
    absolute path or a ``./`` prefix passes.
    """
    if isinstance(value, str) and value.startswith("-"):
        return (
            f"{label} '{value}' starts with '-', so the program would read it as "
            "an option. Pass it as an absolute path or prefix it with ./"
        )
    return None


def safe_run(*args: Any, **kwargs: Any) -> "subprocess.CompletedProcess":
    """subprocess.run with stdin defaulted to DEVNULL (override by passing stdin).

    If ``input`` is given, stdin is left alone — subprocess forbids passing both.
    """
    if "input" not in kwargs:
        kwargs.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.run(*args, **kwargs)


def safe_popen(*args: Any, **kwargs: Any) -> "subprocess.Popen":
    """subprocess.Popen with stdin defaulted to DEVNULL (override by passing stdin)."""
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.Popen(*args, **kwargs)


#: OpenProcess access rights and status codes used by `windows_pid_alive`.
_WIN_SYNCHRONIZE = 0x00100000
_WIN_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WIN_WAIT_OBJECT_0 = 0x0
_WIN_WAIT_TIMEOUT = 0x102
_WIN_ERROR_ACCESS_DENIED = 5
_WIN_ERROR_INVALID_PARAMETER = 87


def windows_pid_alive(pid: int) -> Optional[bool]:
    """Whether `pid` is a running process on Windows, without touching it.

    The POSIX liveness probe, ``os.kill(pid, 0)``, must never run on Windows:
    there any signal other than CTRL_C_EVENT/CTRL_BREAK_EVENT goes through
    ``TerminateProcess``, so the "existence check" kills the process it asks
    about — including this one, when a record names our own pid.

    True: running (access-denied counts, since only a live process can refuse).
    False: no such process, or it has exited. None: could not be determined.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        access = _WIN_SYNCHRONIZE | _WIN_PROCESS_QUERY_LIMITED_INFORMATION
        handle = kernel32.OpenProcess(access, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == _WIN_ERROR_INVALID_PARAMETER:
                return False
            if error == _WIN_ERROR_ACCESS_DENIED:
                return True
            return None
        try:
            status = kernel32.WaitForSingleObject(handle, 0)
        finally:
            kernel32.CloseHandle(handle)
        if status == _WIN_WAIT_OBJECT_0:
            return False  # signalled == exited
        if status == _WIN_WAIT_TIMEOUT:
            return True
        return None
    except Exception:
        return None
