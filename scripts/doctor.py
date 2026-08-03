#!/usr/bin/env python3
"""Read-only diagnostics for a local DaVinci Resolve MCP setup.

Checks the checkout, Python interpreter, Resolve app and scripting-API paths,
MCP client configs, and probes the DaVinciResolveScript bridge without
mutating anything. Prints OK/WARN/FAIL lines (or JSON with --json) and exits
nonzero only when a FAIL is present.

Run: `python3 scripts/doctor.py`
Network mode: `python3 scripts/doctor.py --resolve-host 127.0.0.1`

Overridable via environment: DAVINCI_MCP_REPO, DAVINCI_MCP_PYTHON,
CODEX_HOME, CLAUDE_DESKTOP_CONFIG, RESOLVE_APP, RESOLVE_SCRIPT_API,
RESOLVE_SCRIPT_MODULES, RESOLVE_SCRIPT_LIB, RESOLVE_SCRIPT_HOST,
RESOLVE_SCRIPT_TIMEOUT.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def find_repo_root() -> Path:
    env_repo = os.environ.get("DAVINCI_MCP_REPO")
    if env_repo:
        return Path(env_repo).expanduser().resolve()
    current = Path(__file__).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "src" / "server.py").exists():
            return candidate
    return current.parents[1]


REPO = find_repo_root()
PYTHON = Path(os.environ.get("DAVINCI_MCP_PYTHON", REPO / "venv" / "bin" / "python")).expanduser()
if not PYTHON.exists():
    PYTHON = REPO / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)
SERVER = REPO / "src" / "server.py"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
CODEX_CONFIG = CODEX_HOME / "config.toml"
#: Where Resolve installs itself, per platform. Mirrors install.py's
#: RESOLVE_PATHS — kept in step by tests/test_doctor_paths.py, because these
#: being macOS-only is exactly the bug that made doctor useless off macOS.
#:
#: doctor used to hardcode the Darwin values. Run standalone on Windows (i.e.
#: without the env vars the npm/install.py flow injects) it then reported four
#: FAILs naming a `.app` bundle and `fusionscript.so` on a machine that had
#: neither — while install.py detected the very same install correctly, which is
#: what made it so confusing to diagnose (issue #106). Linux had the same bug.
_RESOLVE_PATH_CANDIDATES: dict[str, dict[str, tuple[str, ...]]] = {
    "darwin": {
        "app": ("/Applications/DaVinci Resolve/DaVinci Resolve.app",),
        "api": ("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",),
        "lib": ("/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",),
    },
    "win32": {
        "app": (r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe",),
        "api": (
            r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Developer\Scripting",
        ),
        "lib": (r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",),
    },
    "linux": {
        "app": ("/opt/resolve/bin/resolve",),
        "api": (
            "/opt/resolve/Developer/Scripting",
            "/opt/resolve/libs/Fusion/Developer/Scripting",
        ),
        "lib": (
            "/opt/resolve/libs/Fusion/fusionscript.so",
            "/opt/resolve/bin/fusionscript.so",
        ),
    },
}


def _platform_key(platform: str | None = None) -> str:
    """Which candidate set applies. Unknown platforms fall back to Linux."""
    platform = platform if platform is not None else sys.platform
    if platform == "darwin":
        return "darwin"
    if platform == "win32":
        return "win32"
    return "linux"


def _resolve_default(kind: str, platform: str | None = None) -> str:
    """First candidate of `kind` that exists, else the first (so the FAIL line
    names the canonical location rather than an arbitrary miss)."""
    candidates = _RESOLVE_PATH_CANDIDATES[_platform_key(platform)][kind]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return candidates[0]


def _default_claude_config() -> Path:
    """Claude Desktop's config path, MSIX-aware on Windows (issue #93).

    Claude Desktop for Windows ships as an MSIX package whose %APPDATA% writes
    are virtualized into a per-package container, so the documented
    %APPDATA%\\Claude path is a decoy the app never reads. Mirrors
    install.py's windows_claude_desktop_config().
    """
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        try:
            packages = sorted((local / "Packages").glob("Claude_*"))
        except OSError:
            packages = []
        for pkg in packages:
            virtual = pkg / "LocalCache" / "Roaming" / "Claude"
            if virtual.is_dir():
                return virtual / "claude_desktop_config.json"
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        return appdata / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path("~/Library/Application Support/Claude/claude_desktop_config.json").expanduser()
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg / "Claude" / "claude_desktop_config.json"


CLAUDE_CONFIG = Path(
    os.environ.get("CLAUDE_DESKTOP_CONFIG", _default_claude_config())
).expanduser()
RESOLVE_APP = Path(os.environ.get("RESOLVE_APP", _resolve_default("app")))
RESOLVE_API = Path(os.environ.get("RESOLVE_SCRIPT_API", _resolve_default("api")))
RESOLVE_MODULES = Path(os.environ.get("RESOLVE_SCRIPT_MODULES", RESOLVE_API / "Modules"))
RESOLVE_LIB = Path(os.environ.get("RESOLVE_SCRIPT_LIB", _resolve_default("lib")))


def run(cmd: list[str], timeout: int = 12) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}


def run_in_repo(cmd: list[str], timeout: int = 12) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}


def check(results: list[dict[str, str]], status: str, name: str, detail: str) -> None:
    results.append({"status": status, "name": name, "detail": detail})


def file_contains(path: Path, needles: list[str]) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    text = path.read_text(errors="replace")
    missing = [needle for needle in needles if needle not in text]
    if missing:
        return False, "missing: " + ", ".join(missing)
    return True, "contains davinci-resolve MCP entry"


def version_from_server() -> str:
    if not SERVER.exists():
        return "unknown"
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', SERVER.read_text(errors="replace"), re.M)
    return match.group(1) if match else "unknown"


def git_summary() -> str:
    if not (REPO / ".git").exists():
        return "not a git checkout"
    status = run_in_repo(["git", "status", "--short", "--branch"], timeout=8)
    return status["stdout"] or status["stderr"] or "git status produced no output"


def git_head() -> str:
    if not (REPO / ".git").exists():
        return "not a git checkout"
    head = run_in_repo(["git", "describe", "--tags", "--always", "--dirty"], timeout=8)
    return head["stdout"] or head["stderr"] or "git describe produced no output"


def resolve_probe(
    resolve_host: str | None = None,
    resolve_timeout: float | None = None,
) -> dict[str, Any]:
    if not PYTHON.exists():
        return {"import_ok": False, "error": f"{PYTHON} is missing"}

    code = f"""
import json
import sys
sys.path.insert(0, {str(REPO)!r})
sys.path.insert(0, {str(RESOLVE_MODULES)!r})
try:
    import DaVinciResolveScript as dvr
    from src.utils.resolve_connection import connect_resolve
except Exception as exc:
    payload = {{"import_ok": False, "error": repr(exc)}}
else:
    try:
        resolve = connect_resolve(dvr)
    except Exception as exc:
        payload = {{
            "import_ok": True,
            "module": getattr(dvr, "__file__", None),
            "resolve_connected": False,
            "connection_error": repr(exc),
        }}
    else:
        payload = {{
            "import_ok": True,
            "module": getattr(dvr, "__file__", None),
            "resolve_connected": bool(resolve),
            "product": resolve.GetProductName() if resolve else None,
            "version": resolve.GetVersionString() if resolve else None,
        }}
print(json.dumps(payload))
"""
    env = {
        **os.environ,
        "RESOLVE_SCRIPT_API": str(RESOLVE_API),
        "RESOLVE_SCRIPT_LIB": str(RESOLVE_LIB),
        "PYTHONPATH": str(RESOLVE_MODULES),
    }
    if resolve_host is not None:
        env["RESOLVE_SCRIPT_HOST"] = resolve_host
    if resolve_timeout is not None:
        env["RESOLVE_SCRIPT_TIMEOUT"] = str(resolve_timeout)
    process_timeout = 12.0
    configured_timeout = env.get("RESOLVE_SCRIPT_TIMEOUT")
    if configured_timeout:
        try:
            network_timeout = float(configured_timeout)
            if math.isfinite(network_timeout) and network_timeout > 0:
                process_timeout = max(process_timeout, network_timeout + 2)
        except ValueError:
            pass
    proc = subprocess.run(
        [str(PYTHON), "-c", code],
        capture_output=True,
        text=True,
        timeout=process_timeout,
        env=env,
    )
    output = (proc.stdout or proc.stderr).strip()
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        payload = {"import_ok": False, "error": output or f"probe exited {proc.returncode}"}
    payload["returncode"] = proc.returncode
    return payload


def detect_edition(probe: dict[str, Any]) -> str | None:
    """"Studio" / "Free" from the connected product name, or None if unknown.

    Only knowable when something answered. Guessing from an install path would
    be wrong on any machine running both, which is common — the sandboxed free
    edition and a direct-download Studio coexist happily.
    """
    product = str(probe.get("product") or "")
    if not product:
        return None
    return "Studio" if "studio" in product.lower() else "Free"


def bridge_checks(probe: dict[str, Any]) -> list[dict[str, str]]:
    """Report the free-edition in-app bridge as a first-class path.

    The bridge shipped in v2.68.0 and nothing in the diagnostics mentioned it,
    so a free-edition user running doctor saw a wall of failures and no way
    through — which is precisely the conclusion the docs used to push them to.
    """
    results: list[dict[str, str]] = []
    installer = REPO / "scripts" / "install_resolve_bridge.py"
    enabled = os.environ.get("DAVINCI_RESOLVE_BRIDGE", "").strip().lower() not in ("", "0", "false", "no", "off")

    installed_at: list[str] = []
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        import install_resolve_bridge as _bridge  # type: ignore

        for folder in _bridge.script_targets():
            if (folder / "resolve_bridge.py").exists():
                installed_at.append(str(folder))
    except Exception:
        # Never let a diagnostic tool be the thing that crashes.
        installed_at = []

    if installed_at:
        check(results, "OK", "Free-edition bridge", f"installed: {installed_at[0]}")
    elif installer.exists():
        check(
            results, "INFO", "Free-edition bridge",
            "not installed. Only needed on the FREE edition (Studio uses external "
            f"scripting directly). Install: {PYTHON} {installer}",
        )
    else:
        check(results, "WARN", "Free-edition bridge", f"installer missing: {installer}")

    edition = detect_edition(probe)
    if edition:
        check(results, "OK", "Resolve edition", edition)
    elif installed_at or enabled:
        check(results, "INFO", "Resolve edition",
              "unknown — nothing answered, so the edition cannot be read")

    if enabled:
        connected = bool(probe.get("resolve_connected"))
        check(
            results, "OK" if connected else "WARN", "DAVINCI_RESOLVE_BRIDGE",
            "set — the bridge is the only transport tried"
            + ("" if connected else ". Nothing answered: in Resolve run "
               "Workspace > Scripts > resolve_bridge (a saved project must be open)."),
        )
    elif installed_at:
        check(
            results, "INFO", "DAVINCI_RESOLVE_BRIDGE",
            "not set — the bridge is installed but will not be used. "
            "export DAVINCI_RESOLVE_BRIDGE=1 to enable it.",
        )
    return results


#: Optional extras and what each unlocks. Absent is INFO, never FAIL — the core
#: install is deliberately small and every feature below refuses honestly with
#: its own install line rather than degrading into a guess.
OPTIONAL_EXTRAS = (
    ("numpy", "colour pre-balance, reference-still matching, sound-density audit", "pip install numpy"),
    ("librosa", "beat / bar / phrase detection for music-driven cutting", "pip install librosa"),
    ("whisper", "transcription, and the word-level tools built on it", "pip install -U openai-whisper"),
    ("open_clip", "visual similarity and find_similar", "pip install open_clip_torch"),
    ("transformers", "CLAP audio embeddings", "pip install transformers"),
    ("cv2", "additional frame analysis", "pip install opencv-python"),
)


def extras_checks() -> list[dict[str, str]]:
    """Report which optional extras are installed and what each would unlock.

    Absence is informational. The point is that a user should not have to
    discover an extra by hitting a refusal mid-workflow — "setup too hard" was
    one of the loudest complaints this release set out to answer, and shipping
    features behind an undocumented `pip install` is the same failure.
    """
    import importlib.util

    results: list[dict[str, str]] = []
    missing: list[str] = []
    for module, unlocks, install in OPTIONAL_EXTRAS:
        try:
            present = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            present = False
        if present:
            check(results, "OK", f"Extra: {module}", unlocks)
        else:
            missing.append(module)
            check(results, "INFO", f"Extra: {module}", f"not installed — {unlocks} ({install})")
    if missing:
        check(
            results, "INFO", "Optional extras",
            f"{len(missing)} of {len(OPTIONAL_EXTRAS)} absent. None are required; each "
            "feature refuses with its install line rather than guessing.",
        )
    return results


def collect(
    resolve_host: str | None = None,
    resolve_timeout: float | None = None,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

    check(results, "OK" if REPO.exists() else "FAIL", "MCP checkout", str(REPO))
    check(results, "OK" if SERVER.exists() else "FAIL", "Server entrypoint", str(SERVER))
    check(results, "OK" if PYTHON.exists() else "FAIL", "Python", str(PYTHON))
    check(results, "OK" if RESOLVE_APP.exists() else "FAIL", "Resolve app", str(RESOLVE_APP))
    check(results, "OK" if RESOLVE_API.exists() else "FAIL", "Resolve scripting API", str(RESOLVE_API))
    check(results, "OK" if RESOLVE_MODULES.exists() else "FAIL", "Resolve scripting modules", str(RESOLVE_MODULES))
    check(results, "OK" if RESOLVE_LIB.exists() else "FAIL", "Resolve scripting library", str(RESOLVE_LIB))

    needles = [str(SERVER)]
    ok, detail = file_contains(CODEX_CONFIG, needles)
    check(results, "OK" if ok else "WARN", "Codex MCP config", f"{CODEX_CONFIG}: {detail}")
    ok, detail = file_contains(CLAUDE_CONFIG, needles)
    check(results, "OK" if ok else "WARN", "Claude Desktop MCP config", f"{CLAUDE_CONFIG}: {detail}")

    pyver = run([str(PYTHON), "--version"]) if PYTHON.exists() else {"ok": False, "stdout": "", "stderr": "missing"}
    check(results, "OK" if pyver["ok"] else "FAIL", "Python version", pyver["stdout"] or pyver["stderr"])

    probe = resolve_probe(resolve_host, resolve_timeout)
    if probe.get("import_ok"):
        check(results, "OK", "DaVinciResolveScript import", str(probe.get("module")))
        if probe.get("resolve_connected"):
            detail = f"{probe.get('product')} {probe.get('version')}"
            check(results, "OK", "Resolve scripting connection", detail)
        elif probe.get("connection_error"):
            check(
                results,
                "FAIL",
                "Resolve scripting connection",
                str(probe["connection_error"]),
            )
        else:
            # This is also exactly what the free edition looks like: the module
            # imports fine and scriptapp refuses, because Blackmagic gates
            # *external* scripting to Studio. Sending someone to toggle a
            # preference that cannot help them is a dead end, so name the bridge
            # here too.
            check(
                results,
                "WARN",
                "Resolve scripting connection",
                "Module import worked, but scriptapp returned no object. On Studio: "
                "External scripting = Local, or Network with --resolve-host set to "
                "the Resolve host IP, then restart Resolve. On the FREE edition "
                "external scripting is gated off entirely — use the in-app bridge "
                "(see 'Free-edition bridge' below).",
            )
    else:
        check(results, "FAIL", "DaVinciResolveScript import", str(probe.get("error")))

    results.extend(bridge_checks(probe))

    results.extend(extras_checks())

    check(results, "OK", "MCP server version", version_from_server())
    check(results, "OK", "MCP git head", git_head())
    check(results, "OK", "Git status", git_summary())
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--resolve-host",
        help="Resolve host IP for Network scripting mode",
    )
    parser.add_argument(
        "--resolve-timeout",
        type=float,
        help="Network connection timeout in seconds (default: 5)",
    )
    args = parser.parse_args()

    results = collect(args.resolve_host, args.resolve_timeout)
    if args.json:
        print(json.dumps({"checks": results}, indent=2))
    else:
        for item in results:
            print(f"[{item['status']}] {item['name']}: {item['detail']}")

    return 1 if any(item["status"] == "FAIL" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
