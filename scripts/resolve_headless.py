#!/usr/bin/env python3
"""Start, stop and guard a headless DaVinci Resolve — the batch/CI entry point.

    python scripts/resolve_headless.py status     # what is running, and in which mode
    python scripts/resolve_headless.py guard      # exit non-zero unless it is safe to start
    python scripts/resolve_headless.py start      # boot -nogui and wait until scriptable
    python scripts/resolve_headless.py stop       # Quit() and wait for the process to go
    python scripts/resolve_headless.py run -- python my_batch.py   # guard, start, run, stop

Why a wrapper rather than a line in a Makefile:

  - **`open -a` silently drops `-nogui`.** On macOS the flag has to go to the
    binary inside the bundle. A CI job that used `open` would get a window on the
    build machine, no error, and a modal nobody can see.
  - **One Resolve per machine.** The application, a render node and any scripted
    launch contend for the same singleton, and losing that contention has
    produced crash loops rather than clean errors. `guard` refuses to start on
    top of an existing instance, which is the check every job needs and none
    remember to write.
  - **`Quit()` is the only clean teardown.** Killing the process leaves project
    locks behind; `CloseProject` on an unsaved project raises a dialog. `Quit()`
    discards and exits — 2.1s, measured.

`run` is the shape a CI job actually wants: it only stops Resolve if it started
it, so running against a session someone else set up does not tear theirs down.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import resolve_runtime as rr  # noqa: E402

DEFAULT_API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
DEFAULT_LIB = (
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
)


def scripting_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """A copy of the environment with the scripting API discoverable."""
    out = dict(env or os.environ)
    api = out.get("RESOLVE_SCRIPT_API", DEFAULT_API)
    out["RESOLVE_SCRIPT_API"] = api
    out.setdefault("RESOLVE_SCRIPT_LIB", DEFAULT_LIB)
    modules = str(Path(api) / "Modules")
    existing = out.get("PYTHONPATH")
    out["PYTHONPATH"] = f"{modules}:{existing}" if existing else modules
    return out


def _connect() -> Any:
    for path in (os.environ.get("RESOLVE_SCRIPT_API", DEFAULT_API),):
        modules = str(Path(path) / "Modules")
        if modules not in sys.path:
            sys.path.append(modules)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", DEFAULT_LIB)
    try:
        import DaVinciResolveScript as dvr
    except ImportError:
        return None
    return dvr.scriptapp("Resolve")


def wait_until_scriptable(timeout: float = 120.0) -> Optional[Any]:
    """Poll until the ProjectManager answers, not merely until a handle exists.

    `scriptapp()` can hand back a live object whose ProjectManager is not yet
    ready. A job that starts work on that handle sees an empty project list and
    concludes the database is empty.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resolve = _connect()
        if resolve is not None:
            try:
                pm = resolve.GetProjectManager()
                if pm is not None and pm.GetProjectListInCurrentFolder() is not None:
                    return resolve
            except Exception:
                pass
        time.sleep(1.0)
    return None


def cmd_status() -> int:
    mode = rr.describe()
    print(f"running:     {mode['running']}")
    print(f"headless:    {mode['headless']}")
    print(f"instances:   {mode['instances']}")
    for line in mode["command_lines"]:
        print(f"  {line.strip()}")
    print(f"guidance:    {mode['guidance']}")
    return 0


def cmd_guard() -> int:
    """Exit 0 only when it is safe to start a headless instance."""
    mode = rr.runtime_mode()
    if not mode["determinable"]:
        print("REFUSE: cannot read the process list, so cannot tell what is running.", file=sys.stderr)
        return 2
    if mode["running"]:
        print(
            f"REFUSE: {mode['instances']} Resolve instance(s) already running "
            f"(headless={mode['headless']}). Stop them first — a second instance "
            f"fights the singleton.",
            file=sys.stderr,
        )
        for line in mode["command_lines"]:
            print(f"  {line.strip()}", file=sys.stderr)
        return 1
    print("OK: nothing running; safe to start a headless instance.")
    return 0


def start(timeout: float) -> int:
    guard = cmd_guard()
    if guard != 0:
        return guard
    command = rr.launch_command(headless=True)
    if command is None:
        print("REFUSE: no DaVinci Resolve install found.", file=sys.stderr)
        return 3
    print(f"starting: {' '.join(command)}")
    subprocess.Popen(command, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started = time.monotonic()
    if wait_until_scriptable(timeout) is None:
        print(f"FAILED: no scripting response within {timeout:.0f}s.", file=sys.stderr)
        return 4
    print(f"ready in {time.monotonic() - started:.1f}s")
    return 0


def stop(timeout: float) -> int:
    mode = rr.runtime_mode()
    if not mode["running"]:
        print("nothing to stop")
        return 0
    resolve = _connect()
    if resolve is None:
        print("REFUSE: Resolve is running but not answering; not killing it.", file=sys.stderr)
        return 5
    started = time.monotonic()
    resolve.Quit()
    while time.monotonic() - started < timeout:
        time.sleep(0.5)
        if not (rr.resolve_processes() or []):
            print(f"stopped in {time.monotonic() - started:.1f}s")
            return 0
    print(f"FAILED: still running {timeout:.0f}s after Quit().", file=sys.stderr)
    return 6


def cmd_run(command: List[str], timeout: float) -> int:
    """Guard, start if needed, run the command, stop only what we started."""
    mode = rr.runtime_mode()
    we_started = False
    if not mode["determinable"]:
        print("REFUSE: cannot read the process list.", file=sys.stderr)
        return 2
    if mode["running"]:
        if not mode["headless"]:
            print(
                "REFUSE: a Resolve with a UI is running. It can raise modal dialogs "
                "that will block this job indefinitely. Quit it first, or run this "
                "against it deliberately with `status` checked by hand.",
                file=sys.stderr,
            )
            return 1
        print("reusing the running headless instance")
    else:
        code = start(timeout)
        if code != 0:
            return code
        we_started = True
    try:
        return subprocess.run(command, env=scripting_env(), check=False).returncode
    finally:
        if we_started:
            stop(timeout)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="seconds to wait for start/stop (default 120)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("guard")
    sub.add_parser("start")
    sub.add_parser("stop")
    run = sub.add_parser("run")
    run.add_argument("argv", nargs=argparse.REMAINDER,
                     help="command to run; put it after a bare --")

    args = parser.parse_args()
    if args.command == "status":
        return cmd_status()
    if args.command == "guard":
        return cmd_guard()
    if args.command == "start":
        return start(args.timeout)
    if args.command == "stop":
        return stop(args.timeout)
    argv = [a for a in args.argv if a != "--"]
    if not argv:
        print("run: nothing to run (put the command after `--`)", file=sys.stderr)
        return 64
    return cmd_run(argv, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
