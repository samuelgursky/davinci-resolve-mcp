"""Install the bridge (or just the host-model probe) into Resolve's Scripts folder.

    python scripts/install_resolve_bridge.py --probe-only    # settle the host model first
    python scripts/install_resolve_bridge.py                 # probe + bridge launcher

Deploys to every applicable macOS/Linux location, including the sandboxed App
Store container used by the free edition — which is why the free edition can be
installed alongside a direct-download Studio without either disturbing the other.

Nothing is started here. Resolve must be restarted after installing so it
re-scans the Scripts folders, and the script is then run from
**Workspace ▸ Scripts**.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path.home() / ".config/davinci-resolve-mcp"
CONFIG_PATH = CONFIG_DIR / "bridge.json"
DEFAULT_PORT = 49632

_SCRIPTS_SUFFIX = "Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"

#: A sandboxed (App Store) build sees its container as HOME, so Resolve's
#: documented per-user path virtualizes to `<container>/Data/` + the SAME suffix.
#: The vendor segment is kept.
#:
#: Two traps, both hit on a real install:
#:
#: 1. `<container>/Data/Library/Application Support/Fusion/Scripts/Utility`
#:    exists and is pre-scaffolded with Color/Comp/Deliver/Edit/Tool/Utility, but
#:    it is **Fusion's standalone tree**, not Resolve's. Keying on "which
#:    directory already exists" picks it over the one the README documents.
#: 2. Resolve does not create its own `Fusion/Scripts` tree until a script is
#:    installed, so requiring the target to pre-exist skips the free edition
#:    entirely — the one build the bridge exists for.
#:
#: So: a container that exists means the edition is installed, and the tree is
#: *created*. Blackmagic's README is the authority on the suffix, not the
#: filesystem.
#:
#: **Correction, measured on free 21.0.3.7:** an earlier version of trap 1 said
#: Resolve "does not scan" the Fusion standalone tree. It does — a marker left in
#: `<container>/Data/Library/Application Support/Fusion/Scripts/Utility` appeared
#: under Workspace ▸ Scripts, as did one in
#: `<container>/Data/Documents/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility`.
#: So Lite scans more locations than the README documents. That changes nothing
#: about *where to install* — the documented paths work, and each extra target is
#: another chance for the App Management prompt to stall the copy — but the reason
#: to prefer them is that they are documented, not that the others are dead.
_SANDBOX_MARKER = "com.blackmagic-design."
#: Containers that are not Resolve (RAW Player, Speed Test, the IO XPC helper).
_NON_RESOLVE_CONTAINERS = ("BlackmagicRaw", "IOXPC")


def _is_resolve_container(path: Path) -> bool:
    if not path.name.startswith(_SANDBOX_MARKER):
        return False
    return not any(marker in path.name for marker in _NON_RESOLVE_CONTAINERS)


def script_targets() -> list[Path]:
    """Every Scripts/Utility folder Resolve will scan on this machine.

    Sandboxed containers are included because the App Store build cannot see the
    normal per-user path — that isolation is exactly what lets the free edition
    coexist with a direct-download Studio install.
    """
    home = Path.home()
    candidates = [
        home / _SCRIPTS_SUFFIX,
        Path("/") / _SCRIPTS_SUFFIX,
        home / ".local/share/DaVinciResolve/Fusion/Scripts/Utility",
    ]
    containers = home / "Library/Containers"
    sandboxed: list[Path] = []
    if containers.is_dir():
        for entry in sorted(containers.iterdir()):
            if _is_resolve_container(entry) and (entry / "Data").is_dir():
                sandboxed.append(entry / "Data" / _SCRIPTS_SUFFIX)

    usable: list[Path] = []
    for path in candidates:
        # Non-sandboxed: the install created the tree, so require it.
        if path.is_dir() or (path.parent.is_dir() and os.access(path.parent, os.W_OK)):
            usable.append(path)
    # Sandboxed: the container's existence is the signal; the tree gets created.
    usable.extend(sandboxed)
    return list(dict.fromkeys(usable))


#: Resolve enumerates `.py` scripts in Workspace > Scripts only when it finds a
#: **framework** Python. Homebrew/pyenv/conda interpreters are not detected, and
#: the failure is completely silent: the script sits in the right folder with the
#: right permissions and simply never appears. Lua is embedded, so `.lua` always
#: lists — which is why a Lua canary is installed alongside the probe.
_FRAMEWORK_PYTHON_ROOTS = (
    Path("/Library/Frameworks/Python.framework/Versions"),
    Path("/System/Library/Frameworks/Python.framework/Versions"),
)

_LUA_CANARY = """-- Installed by davinci-resolve-mcp as an enumeration canary.
-- If THIS appears under Workspace > Scripts but resolve_bridge_probe does not,
-- Resolve is listing Lua and silently skipping Python: it cannot find a
-- framework Python install. Install one from python.org and restart Resolve.
print("Resolve is enumerating scripts. If the Python probe is missing, install a")
print("framework Python from python.org (Homebrew/pyenv are NOT detected).")
"""


def framework_pythons() -> list[str]:
    """Framework Python versions Resolve can actually see."""
    found: list[str] = []
    for root in _FRAMEWORK_PYTHON_ROOTS:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            # `Versions/Current` is a symlink to a real version — counting it
            # would report two installs where there is one.
            if entry.is_symlink():
                continue
            if (entry / "bin" / "python3").exists() or (entry / "Python").exists():
                found.append(f"{root}/{entry.name}")
    return found


def python_preflight() -> dict:
    """Will Resolve list the Python probe we are about to install?"""
    frameworks = framework_pythons()
    return {
        "framework_pythons": frameworks,
        "resolve_will_list_python_scripts": bool(frameworks),
        "advice": None if frameworks else (
            "No framework Python found. Resolve will silently ignore every .py "
            "script in its Scripts folders — they will simply not appear in "
            "Workspace > Scripts, with no error. Homebrew, pyenv and conda "
            "interpreters are NOT detected. Install a framework build from "
            "python.org (any recent 3.x), restart Resolve, and re-check. The "
            "Lua canary installed alongside will list either way, so you can "
            "tell 'Python not detected' apart from 'wrong folder'."
        ),
    }


def ensure_config(port: int, rotate: bool) -> dict:
    existing: dict = {}
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
    token = existing.get("token")
    if rotate or not isinstance(token, str) or len(token) < 43:
        token = secrets.token_urlsafe(32)
    # ResolveOperations requires roots; without them the bridge refuses to start.
    # Conservative default: the user's home. Widen deliberately, not by accident.
    existing_media = [r for r in (existing.get("allowed_media_roots") or []) if isinstance(r, str)]
    existing_output = [r for r in (existing.get("allowed_output_roots") or []) if isinstance(r, str)]
    config = {
        "host": "127.0.0.1",
        "port": port,
        "token": token,
        "auth_clock_skew_seconds": 60,
        "allowed_media_roots": existing_media or [str(Path.home())],
        "allowed_output_roots": existing_output or [str(Path.home() / "Movies")],
    }
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_PATH)
    os.chmod(CONFIG_PATH, 0o600)
    return config


def install(*, probe_only: bool, port: int, rotate: bool) -> dict:
    # Write the config first: the launcher embeds its path, and a launcher
    # pointing at a file that does not exist yet is a confusing first run.
    if not probe_only:
        ensure_config(port, rotate)
    targets = script_targets()
    if not targets:
        raise SystemExit(
            "No writable DaVinci Resolve Scripts/Utility folder found. Is Resolve installed?"
        )
    installed: list[str] = []
    for target in targets:
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        for probe in ("resolve_bridge_probe.py", "resolve_capability_probe.py"):
            shutil.copy2(REPO / "scripts" / probe, target / probe)
            installed.append(str(target / probe))
        # Lua always enumerates; Python only with a framework install. The canary
        # makes "Python not detected" distinguishable from "wrong folder".
        canary = target / "resolve_bridge_canary.lua"
        canary.write_text(_LUA_CANARY, encoding="utf-8")
        installed.append(str(canary))
        if not probe_only:
            runtime = target.parents[1] / ".davinci_mcp_runtime"
            runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
            for module in ("resolve_bridge.py", "resolve_bridge_ops.py"):
                shutil.copy2(REPO / "src/utils" / module, runtime / module)
                installed.append(str(runtime / module))
            # A sandboxed (App Store) build cannot read ~/.config at all — inside
            # the container `~` IS the container, so an absolute real-home path is
            # unreachable by construction (measured: "Operation not permitted").
            # The runtime dir is already inside the container, so the config goes
            # beside the modules. Same token, so the out-of-sandbox client still
            # authenticates against ~/.config.
            runtime_config = runtime / "bridge.json"
            shutil.copy2(CONFIG_PATH, runtime_config)
            os.chmod(runtime_config, 0o600)
            installed.append(str(runtime_config))
            # The launcher IS the menu entry. Without it the modules sit in the
            # runtime dir with nothing able to start them.
            launcher_source = (REPO / "scripts/resolve_bridge_launcher.py").read_text(encoding="utf-8")
            launcher = launcher_source.replace(
                "@@RUNTIME_ROOT_B64@@",
                base64.urlsafe_b64encode(str(runtime).encode("utf-8")).decode("ascii"),
            ).replace(
                "@@CONFIG_PATH_B64@@",
                base64.urlsafe_b64encode(str(CONFIG_PATH).encode("utf-8")).decode("ascii"),
            )
            launcher_path = target / "resolve_bridge.py"
            launcher_path.write_text(launcher, encoding="utf-8")
            installed.append(str(launcher_path))
    result = {"installed": installed, "probe_only": probe_only, "python": python_preflight()}
    if not probe_only:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        result["config"] = {"path": str(CONFIG_PATH),
                            **{k: v for k, v in loaded.items() if k != "token"}}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-only", action="store_true",
                        help="install only the host-model probe (run this first)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--rotate-token", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("--port must be 1024..65535")

    result = install(probe_only=args.probe_only, port=args.port, rotate=args.rotate_token)
    print(json.dumps(result, indent=2, sort_keys=True))
    print()
    if not result["python"]["resolve_will_list_python_scripts"]:
        print("!" * 72)
        print("WARNING: " + result["python"]["advice"])
        print("!" * 72)
        print()
    print("Next:")
    print("  1. Restart DaVinci Resolve so it re-scans the Scripts folders.")
    print("  2. Open a saved project (the Scripts menu is empty in Project Manager).")
    print("  3. Workspace > Scripts > resolve_bridge_probe  — run it TWICE.")
    print("  4. Read ~/.config/davinci-resolve-mcp/host-model-probe.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
