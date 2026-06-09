#!/usr/bin/env python3
"""Read-only diagnostics for a local DaVinci Resolve MCP setup.

Checks the checkout, Python interpreter, Resolve app and scripting-API paths,
MCP client configs, and probes the DaVinciResolveScript bridge without
mutating anything. Prints OK/WARN/FAIL lines (or JSON with --json) and exits
nonzero only when a FAIL is present.

Run: `python3 scripts/doctor.py`

Overridable via environment: DAVINCI_MCP_REPO, DAVINCI_MCP_PYTHON,
CODEX_HOME, CLAUDE_DESKTOP_CONFIG, RESOLVE_APP, RESOLVE_SCRIPT_API,
RESOLVE_SCRIPT_MODULES, RESOLVE_SCRIPT_LIB.
"""

from __future__ import annotations

import argparse
import json
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
CLAUDE_CONFIG = Path(
    os.environ.get(
        "CLAUDE_DESKTOP_CONFIG",
        "~/Library/Application Support/Claude/claude_desktop_config.json",
    )
).expanduser()
RESOLVE_APP = Path(os.environ.get("RESOLVE_APP", "/Applications/DaVinci Resolve/DaVinci Resolve.app"))
RESOLVE_API = Path(
    os.environ.get(
        "RESOLVE_SCRIPT_API",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
    )
)
RESOLVE_MODULES = Path(os.environ.get("RESOLVE_SCRIPT_MODULES", RESOLVE_API / "Modules"))
RESOLVE_LIB = Path(
    os.environ.get(
        "RESOLVE_SCRIPT_LIB",
        "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
    )
)


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


def resolve_probe() -> dict[str, Any]:
    if not PYTHON.exists():
        return {"import_ok": False, "error": f"{PYTHON} is missing"}

    code = f"""
import json
import sys
sys.path.insert(0, {str(RESOLVE_MODULES)!r})
try:
    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp("Resolve")
    payload = {{
        "import_ok": True,
        "module": getattr(dvr, "__file__", None),
        "resolve_connected": bool(resolve),
        "product": resolve.GetProductName() if resolve else None,
        "version": resolve.GetVersionString() if resolve else None,
    }}
except Exception as exc:
    payload = {{"import_ok": False, "error": repr(exc)}}
print(json.dumps(payload))
"""
    env = {
        **os.environ,
        "RESOLVE_SCRIPT_API": str(RESOLVE_API),
        "RESOLVE_SCRIPT_LIB": str(RESOLVE_LIB),
        "PYTHONPATH": str(RESOLVE_MODULES),
    }
    proc = subprocess.run([str(PYTHON), "-c", code], capture_output=True, text=True, timeout=12, env=env)
    output = (proc.stdout or proc.stderr).strip()
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        payload = {"import_ok": False, "error": output or f"probe exited {proc.returncode}"}
    payload["returncode"] = proc.returncode
    return payload


def collect() -> list[dict[str, str]]:
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

    probe = resolve_probe()
    if probe.get("import_ok"):
        check(results, "OK", "DaVinciResolveScript import", str(probe.get("module")))
        if probe.get("resolve_connected"):
            detail = f"{probe.get('product')} {probe.get('version')}"
            check(results, "OK", "Resolve scripting connection", detail)
        else:
            check(
                results,
                "WARN",
                "Resolve scripting connection",
                'Module import worked, but scriptapp("Resolve") returned no object. Open DaVinci Resolve Studio, set Preferences > General > External scripting using = Local, and restart Resolve.',
            )
    else:
        check(results, "FAIL", "DaVinciResolveScript import", str(probe.get("error")))

    check(results, "OK", "MCP server version", version_from_server())
    check(results, "OK", "MCP git head", git_head())
    check(results, "OK", "Git status", git_summary())
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    results = collect()
    if args.json:
        print(json.dumps({"checks": results}, indent=2))
    else:
        for item in results:
            print(f"[{item['status']}] {item['name']}: {item['detail']}")

    return 1 if any(item["status"] == "FAIL" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
