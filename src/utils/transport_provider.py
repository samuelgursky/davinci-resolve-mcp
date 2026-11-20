"""An optional, external transport provider: a local program that can see and drive Resolve's transport.

The scripting API on Resolve 19.x has no Play, Stop or IsPlaying (see playback_guard.py), so this server cannot
tell play from pause beyond the playhead moving, and cannot stop playback to take an exact frame. A site that has
another way in (UI automation, a frame tap, a control surface bridge) can plug it in here without this server
knowing how it works.

Configure with RESOLVE_MCP_TRANSPORT_PROVIDER: the path of an executable, or a JSON array argv
(e.g. ["python3", "-m", "my_transport"], run with RESOLVE_MCP_TRANSPORT_PROVIDER_CWD as its working directory).
Unset or empty means no provider, and every call here returns a PROVIDER_MISSING error.

The provider is called once per request and prints ONE JSON object on stdout:

  status                       -> {"state": "playing_forward|playing_reverse|looping|paused|unknown",
                                   "verified": bool, "agree": [channel...], "position": {...}, ...}
  press <action>               -> {"verdict": "ok|failed|refused", ...}   action: forward, reverse, stop,
                                   play_pause, loop, mute, step_frame_forward, step_frame_back, ...
  capture-live <path>          -> {"ok": bool, "path": ..., "timelineFrame": int, "tc": ..., "ageMs": ...}
                                   (the newest frame the provider has, without touching the transport)
  capture-exact <path> [--pause-ok]
                               -> {"ok": bool, "path": ..., "timelineFrame": int, "restored": bool, ...}

This server never treats a provider's exit status or a "pressed" as proof: it returns the provider's own verdict
fields as they are, and a capture is returned as an image only when the file the provider names exists.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any, Dict, List, Optional, Tuple

ENV = "RESOLVE_MCP_TRANSPORT_PROVIDER"
ENV_CWD = "RESOLVE_MCP_TRANSPORT_PROVIDER_CWD"
TIMEOUT_S = 20.0
PRESS_ACTIONS = (
    "forward", "reverse", "stop", "play_pause", "loop", "mute",
    "step_frame_forward", "step_frame_back", "step_second_forward", "step_second_back",
)


def provider_argv() -> Tuple[Optional[List[str]], Optional[str]]:
    """(argv, None) when a usable provider is configured, else (None, why). Empty counts as unset."""
    raw = (os.environ.get(ENV) or "").strip()
    if not raw:
        return None, f"{ENV} is not set"
    if raw.startswith("["):
        try:
            argv = json.loads(raw)
        except ValueError:
            return None, f"{ENV} is not a valid JSON array"
        if not (isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv)):
            return None, f"{ENV} must be a non-empty array of strings"
        return argv, None
    if not (os.path.isfile(raw) and os.access(raw, os.X_OK)):
        return None, f"{ENV} names {raw!r}, which is not an executable file"
    return [raw], None


def available() -> bool:
    return provider_argv()[0] is not None


def call(args: List[str], timeout: float = TIMEOUT_S) -> Dict[str, Any]:
    """Run the provider with `args`. Returns its JSON object, or {"error": ..., "code": ...}."""
    argv, why = provider_argv()
    if argv is None:
        return {"error": why, "code": "PROVIDER_MISSING"}
    cwd = (os.environ.get(ENV_CWD) or "").strip() or None
    if cwd and not os.path.isdir(cwd):
        return {"error": f"{ENV_CWD} names {cwd!r}, which is not a directory", "code": "PROVIDER_MISSING"}
    try:
        proc = subprocess.run(argv + list(args), stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        return {"error": f"transport provider did not answer within {timeout:.0f} s", "code": "PROVIDER_TIMEOUT"}
    except OSError as exc:
        return {"error": f"transport provider could not start: {exc}", "code": "PROVIDER_FAILED"}
    line = next((l for l in reversed(proc.stdout.splitlines()) if l.strip().startswith("{")), None)
    if not line:
        return {"error": "transport provider printed no JSON object", "code": "PROVIDER_FAILED",
                "stderr": proc.stderr[-400:], "exit": proc.returncode, "argv": shlex.join(argv + list(args))}
    try:
        out = json.loads(line)
    except ValueError:
        return {"error": "transport provider printed invalid JSON", "code": "PROVIDER_FAILED"}
    if not isinstance(out, dict):
        return {"error": "transport provider printed JSON that is not an object", "code": "PROVIDER_FAILED"}
    out.setdefault("providerExit", proc.returncode)
    return out


def status() -> Dict[str, Any]:
    return call(["status"])


def press(action: str) -> Dict[str, Any]:
    if action not in PRESS_ACTIONS:
        return {"error": f"action must be one of {list(PRESS_ACTIONS)}; got {action!r}", "code": "INVALID_ACTION"}
    return call(["press", action])


def capture(path: str, mode: str) -> Dict[str, Any]:
    """mode 'live' (newest frame, transport untouched) or 'pause' (pause, exact export, restore)."""
    if mode == "live":
        out = call(["capture-live", path])
    elif mode == "pause":
        out = call(["capture-exact", path, "--pause-ok"], timeout=40.0)
    else:
        return {"error": f"mode must be 'live' or 'pause'; got {mode!r}", "code": "INVALID_MODE"}
    if not out.get("ok"):
        return out
    # The frame is read only from the path this server asked for. A provider that names some other file is refused
    # rather than followed: that file sits outside the staging folder the caller cleans up, and a provider must not
    # be able to have the server return an arbitrary file on disk as the image.
    named = out.get("path")
    if named and os.path.realpath(str(named)) != os.path.realpath(path):
        out["ok"] = False
        out["error"] = "the provider wrote its frame somewhere other than the path it was given"
        out["code"] = "PROVIDER_PATH_MISMATCH"
    elif not os.path.isfile(path):
        out["ok"] = False
        out["error"] = "the provider reported ok but no file exists at the path it was given"
        out["code"] = "PROVIDER_FAILED"
    return out


def error_category(code: str) -> str:
    """The structured-error category for a code this module returns."""
    if code in ("INVALID_ACTION", "INVALID_MODE"):
        return "invalid_input"
    if code == "PROVIDER_MISSING":
        return "precondition"
    return "api_error"
