"""Resolve Scripts-menu probe: does a menu script run in-process or as a child?

Run from **Workspace ▸ Scripts ▸ resolve_bridge_probe** (install with
``python scripts/install_resolve_bridge.py --probe-only``).

The answer decides how the bridge's listener must behave, and the two options
are fatal in opposite directions — a daemon thread dies instantly in a child
process, and a blocking loop wedges Resolve in-process. This settles it with
evidence instead of a guess.

Edition-independent: Workspace ▸ Scripts behaves the same on Studio and free, so
this can be run on whatever is already installed.

**Deliberately self-contained.** This file is copied into Resolve's Scripts
folder, where the repository is not on the path and nothing can be imported from
it. The ~20 lines of detection are duplicated here rather than imported, and
`tests/test_resolve_bridge.py` asserts the two copies agree. An import would
raise in Resolve's console and tell you nothing.

Writes findings to ``~/.config/davinci-resolve-mcp/host-model-probe.json`` and
prints them. Starts no listener and touches no project.
"""

import json
import os
import subprocess
import sys
import time

REPORT_PATH = os.path.expanduser("~/.config/davinci-resolve-mcp/host-model-probe.json")

# Kept in sync with src/utils/resolve_bridge.py — see the module docstring.
PARENT_MARKERS = ("resolve", "fuscript", "fusion")


def process_name(pid):
    """Best-effort process name; empty string when it cannot be read."""
    if os.name == "nt":
        # Windows has neither /proc nor ps, so the probe reported an empty
        # parent name on every Windows machine (issue #112).
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return ""
            try:
                size = ctypes.c_ulong(260)
                buf = ctypes.create_unicode_buffer(size.value)
                if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    return ""
                return os.path.basename(buf.value)
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return ""
    try:  # Linux
        with open("/proc/%d/comm" % pid) as handle:
            return handle.read().strip()
    except (OSError, IOError):
        pass
    try:  # macOS
        out = subprocess.Popen(
            ["ps", "-p", str(pid), "-o", "comm="],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).communicate()[0]
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return out.strip()
    except Exception:
        return ""


def host_model():
    """Ask about THIS process, not the parent.

    The sandboxed App Store build blocks `ps` on another process, so the parent
    name comes back empty even though the script IS a child of Resolve
    (measured: pid 97667, parent 97258, name unreadable). Reading sys.executable
    needs no permission, so it is the decision; the parent name is corroboration.
    """
    parent_pid = os.getppid()
    parent_name = process_name(parent_pid) or ""
    executable = sys.executable or ""
    self_is_host = bool(executable) and executable.rstrip("/").endswith("/Resolve")
    return {
        "model": "in_process" if self_is_host else "child_process",
        "parent_pid": parent_pid,
        "parent_name": parent_name,
        "self_executable": executable,
        "self_is_resolve": self_is_host,
        "parent_corroborates": any(m in parent_name.lower() for m in PARENT_MARKERS),
        "blocking_required": not self_is_host,
        "pid": os.getpid(),
    }


def acquire_resolve():
    """The live object, if Resolve handed us one."""
    candidate = globals().get("resolve")
    if candidate is not None:
        return candidate
    bmd = globals().get("bmd")
    if bmd is not None:
        try:
            return bmd.scriptapp("Resolve")
        except Exception:
            return None
    try:
        import DaVinciResolveScript as script_module
        return script_module.scriptapp("Resolve")
    except Exception:
        return None


def main():
    probe = host_model()

    # Does the interpreter survive the script returning? A child process exits
    # here; Resolve's own interpreter keeps this module alive. So a SECOND run
    # sees the marker only in the in-process case — independent corroboration of
    # the parent-name detection above.
    module = sys.modules[__name__]
    previous = getattr(module, "_PREVIOUS_RUN_AT", None)
    probe["previous_run_in_this_interpreter"] = previous
    probe["interpreter_persisted"] = previous is not None
    module._PREVIOUS_RUN_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    resolve_object = acquire_resolve()
    probe["resolve_object_available"] = resolve_object is not None
    if resolve_object is not None:
        try:
            product = resolve_object.GetProductName()
            probe["product"] = product
            probe["version"] = resolve_object.GetVersionString()
            probe["edition"] = "studio" if "studio" in str(product).lower() else "free"
        except Exception as exc:
            probe["product_probe_error"] = type(exc).__name__

    try:
        directory = os.path.dirname(REPORT_PATH)
        if not os.path.isdir(directory):
            os.makedirs(directory)
        with open(REPORT_PATH, "w") as handle:
            json.dump(probe, handle, indent=2, sort_keys=True)
        written = REPORT_PATH
    except (OSError, IOError) as exc:
        # A sandboxed build may not reach ~/.config. The console output is the
        # real result; the file is a convenience.
        written = "could not write (%s) — read the console output above" % type(exc).__name__

    print("=" * 68)
    print("DaVinci Resolve MCP - Scripts-menu host-model probe")
    print("=" * 68)
    print("  host model      : %s" % probe["model"])
    print("  parent process  : %s (pid %s)" % (probe["parent_name"] or "<unreadable — sandbox>", probe["parent_pid"]))
    print("  this interpreter: %s" % (probe["self_executable"] or "<unknown>"))
    print("  this pid        : %s" % probe["pid"])
    print("  blocking needed : %s" % probe["blocking_required"])
    print("  resolve object  : %s" % probe["resolve_object_available"])
    if probe.get("product"):
        print("  product         : %s %s (%s)" % (probe["product"], probe.get("version", "?"), probe.get("edition")))
    print("  interpreter kept: %s" % probe["interpreter_persisted"])
    print()
    if probe["blocking_required"]:
        print("  -> CHILD PROCESS. The listener must BLOCK; a daemon thread would")
        print("     die the moment this script returns.")
    else:
        print("  -> IN-PROCESS (or launched outside Resolve). The listener must")
        print("     NOT block, or Resolve's script execution wedges.")
    print()
    print("  Run this a SECOND time. If 'interpreter kept' flips to True, the")
    print("  script runs inside Resolve's own interpreter. If it stays False,")
    print("  each run is a fresh child process.")
    print()
    print("  report: %s" % written)
    print("=" * 68)
    return probe


main()
