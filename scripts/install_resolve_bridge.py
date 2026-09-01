"""Install the bridge (or just the host-model probe) into Resolve's Scripts folder.

    python scripts/install_resolve_bridge.py --probe-only    # settle the host model first
    python scripts/install_resolve_bridge.py                 # probe + bridge launcher

Deploys to every applicable macOS/Windows/Linux location, including the sandboxed
App Store container used by the free edition — which is why the free edition can
be installed alongside a direct-download Studio without either disturbing the other.

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
DEFAULT_CONFIG_PATH = Path.home() / ".config/davinci-resolve-mcp/bridge.json"
ENV_CONFIG_PATH = "DAVINCI_RESOLVE_BRIDGE_CONFIG"
DEFAULT_PORT = 49632


def config_path() -> Path:
    """Bridge config written by this installer and read by the MCP client."""
    override = os.environ.get(ENV_CONFIG_PATH)
    return Path(override).expanduser() if override else DEFAULT_CONFIG_PATH


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
#: So Lite scans more locations than the README documents.
#:
#: **Second correction (issue #104), same version, opposite result:** on another
#: free 21.0.3.7 App Store install the documented tree listed *nothing* — not
#: even the Lua canary, which rules out the Python-detection explanation and
#: points at the folder — while the Fusion standalone tree listed all four files
#: with no restart. Two machines, same build, contradictory results.
#:
#: We cannot tell them apart from outside Resolve, so we stop trying to pick a
#: winner and install to BOTH container trees. The documented path stays first
#: (it is the one Blackmagic commits to), the standalone tree is the fallback
#: that demonstrably works where the documented one silently does not. The cost
#: is one extra App Management prompt; the cost of guessing wrong is a bridge
#: that never appears and gives the user nothing to diagnose.
_SANDBOX_MARKER = "com.blackmagic-design."

#: Scanned by Lite in addition to `_SCRIPTS_SUFFIX`, inside the container only.
#: NOT used outside a sandbox: on a normal install this is genuinely Fusion's
#: own tree and has nothing to do with Resolve.
_SANDBOX_FALLBACK_SUFFIX = "Library/Application Support/Fusion/Scripts/Utility"
#: Containers that are not Resolve (RAW Player, Speed Test, the IO XPC helper).
_NON_RESOLVE_CONTAINERS = ("BlackmagicRaw", "IOXPC")

#: Windows Scripts/Utility trees, per Blackmagic's own README
#: (docs/reference/resolve_scripting_api.txt, "Specific user"/"All users").
#: Two traps, both live in those two lines:
#:
#: 1. The per-user tree carries a `Support` segment that the all-users tree does
#:    NOT. They are not one layout under two roots, and deriving one from the
#:    other lands in a folder Resolve never scans.
#: 2. The README writes the per-user root as `%APPDATA%\Roaming\...`, which is
#:    wrong — `%APPDATA%` already IS `...\AppData\Roaming`, so following it
#:    literally yields `AppData\Roaming\Roaming\...`. The paths below drop the
#:    doubled segment; both were confirmed present and writable on the Windows 11
#:    machine in issue #106.
_WINDOWS_USER_SCRIPTS_SUFFIX = (
    "Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts/Utility"
)
_WINDOWS_ALL_USERS_SCRIPTS_SUFFIX = "Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"


#: The product folder both Windows trees hang off. Its existence is the "Resolve
#: is installed" signal — see `_windows_script_candidates`.
_WINDOWS_PRODUCT_ROOT = "Blackmagic Design/DaVinci Resolve"


def _windows_script_candidates() -> list[Path]:
    """Scripts/Utility trees Resolve scans on Windows (issue #106).

    Gated on the *product* folder, not the Scripts/Utility tree, for the same
    reason the sandbox branch is: Resolve does not create its `Fusion/Scripts`
    tree until a script is installed, so requiring the target to pre-exist skips
    a fresh free-edition install — the one build the bridge exists for. The
    product folder is created on first launch, so it answers "is Resolve
    installed" without demanding a folder only we will ever create.

    Per-user first: it is the one a non-elevated account can actually write,
    while `%PROGRAMDATA%` typically needs an elevated prompt. Ordering it first
    means the target that will succeed is also the one reported first.
    """
    candidates: list[Path] = []
    for env_var, suffix in (
        ("APPDATA", _WINDOWS_USER_SCRIPTS_SUFFIX),
        ("PROGRAMDATA", _WINDOWS_ALL_USERS_SCRIPTS_SUFFIX),
    ):
        root = os.environ.get(env_var)
        if not root:
            continue
        target = Path(root) / suffix
        if target.is_dir() or (Path(root) / _WINDOWS_PRODUCT_ROOT).is_dir():
            candidates.append(target)
    return candidates


def _is_resolve_container(path: Path) -> bool:
    if not path.name.startswith(_SANDBOX_MARKER):
        return False
    return not any(marker in path.name for marker in _NON_RESOLVE_CONTAINERS)


def script_targets() -> list[Path]:
    """Every Scripts/Utility folder Resolve will scan on this machine.

    Sandboxed containers are included because the App Store build cannot see the
    normal per-user path — that isolation is exactly what lets the free edition
    coexist with a direct-download Studio install. Each container contributes
    TWO targets (see the module comment on issue #104): the documented tree
    first, then the Fusion standalone tree that Lite also scans.

    Windows has no sandbox and no `~/Library`, so it gets its own candidate list
    (issue #106) — without one this returned empty on every Windows machine and
    the installer exited with "Is Resolve installed?" on a working install.
    Those candidates arrive pre-vetted, like the sandboxed ones: they are gated
    on Resolve's product folder rather than on the Scripts tree, which Resolve
    does not create until a script is installed.
    """
    home = Path.home()
    # Pre-vetted targets, whose tree gets created rather than being required.
    vetted: list[Path] = []
    candidates: list[Path] = []
    if sys.platform == "win32":
        vetted.extend(_windows_script_candidates())
    else:
        candidates = [
            home / _SCRIPTS_SUFFIX,
            Path("/") / _SCRIPTS_SUFFIX,
            home / ".local/share/DaVinciResolve/Fusion/Scripts/Utility",
        ]
        containers = home / "Library/Containers"
        if containers.is_dir():
            for entry in sorted(containers.iterdir()):
                if _is_resolve_container(entry) and (entry / "Data").is_dir():
                    # The container's existence is the signal; the tree gets created.
                    vetted.append(entry / "Data" / _SCRIPTS_SUFFIX)
                    vetted.append(entry / "Data" / _SANDBOX_FALLBACK_SUFFIX)

    usable: list[Path] = []
    for path in candidates:
        # Non-sandboxed: the install created the tree, so require it.
        if path.is_dir() or (path.parent.is_dir() and os.access(path.parent, os.W_OK)):
            usable.append(path)
    usable.extend(vetted)
    return list(dict.fromkeys(usable))


#: Where a Resolve app bundle actually lives. The App Store build installs flat
#: into /Applications; the direct download uses its own folder. RESOLVE_APP
#: overrides both, matching scripts/doctor.py.
_APP_BUNDLE_CANDIDATES = (
    "/Applications/DaVinci Resolve/DaVinci Resolve.app",
    "/Applications/DaVinci Resolve.app",
    "/Applications/DaVinci Resolve Studio.app",
)


def installed_app_bundles() -> list[str]:
    """Resolve app bundles present on this machine."""
    override = os.environ.get("RESOLVE_APP")
    candidates = (override,) + _APP_BUNDLE_CANDIDATES if override else _APP_BUNDLE_CANDIDATES
    return [path for path in candidates if path and Path(path).is_dir()]


def stale_container_warning(targets: list[Path]) -> str | None:
    """Are we about to install into a container left by an *uninstalled* Resolve?

    A container outlives the app that created it — uninstalling Resolve leaves
    the whole `~/Library/Containers/com.blackmagic-design.*` tree behind. Since
    a container's existence is what makes us target it, the installer would
    otherwise report a clean success on a machine with no Resolve at all, and
    the user would go hunting through the Scripts menu of an app they do not
    have (issue #104). Warn rather than refuse: we cannot enumerate every place
    an app bundle might legitimately live, and being wrong in the refusing
    direction blocks a working install.
    """
    if not any("Containers" in str(target) for target in targets):
        return None
    if installed_app_bundles():
        return None
    return (
        "Installed into a sandbox container, but no DaVinci Resolve app bundle "
        "was found on this machine. A container OUTLIVES the app that created "
        "it, so this is what an uninstalled Resolve looks like — the files were "
        "written, but nothing will ever read them. Checked: "
        + ", ".join(_APP_BUNDLE_CANDIDATES)
        + ". If Resolve is installed somewhere else, re-run with RESOLVE_APP "
        "set to its .app bundle to silence this. If it is not installed, "
        "install it first, then re-run."
    )


#: Resolve enumerates `.py` scripts in Workspace > Scripts only when it can find
#: and load a Python 3, and the failure is completely silent: the script sits in
#: the right folder with the right permissions and simply never appears. Lua is
#: embedded, so `.lua` always lists — which is why a Lua canary is installed
#: alongside the probe.
#:
#: **What it actually looks for (issue #143, corrected 2026-08-10).** This check
#: used to require a *framework* build and send everyone else to python.org. That
#: was the right remedy for the wrong reason, and it turned a one-line fix into a
#: system-wide `sudo` install that managed machines often forbid. In
#: `fusionscript.so` — read on Studio 19.1.3.7, a January 2025 binary, matching
#: what the reporter read on 21.0.4.5 — every `Python.framework` reference is
#: Python **2.7**:
#:
#:     /Library/Frameworks/Python.framework/Versions/2.7/
#:     /System/Library/Frameworks/Python.framework/Versions/2.7/
#:
#: There is no `Python.framework/Versions/3` string at all. Python 3 is found by
#: a different mechanism entirely, whose pieces sit adjacent in the binary:
#:
#:     PYTHON3HOME
#:     /usr/local/bin/python3
#:     python3 -c 'import sys; sys.stdout.write("%s.%s|%s" % (sys.version_info.major, sys.version_info.minor, sys.prefix))'
#:     /libpython
#:
#: i.e. resolve `PYTHON3HOME`, else `/usr/local/bin/python3`; probe it for its
#: version and `sys.prefix`; `dlopen` `<prefix>/lib/libpython3.X.dylib`. The
#: ordering is inferred from adjacency rather than decompiled control flow, but
#: the two entry points are not in doubt.
#:
#: That explains every observation the old rule was built on. python.org works
#: because its installer creates `/usr/local/bin/python3` — verified here, where
#: it is a symlink into `Python.framework/Versions/3.11`. Homebrew on Apple
#: silicon installs to `/opt/homebrew/bin`, pyenv to `~/.pyenv/shims`, and uv to
#: `~/.local/share/uv/...`; none of them land `/usr/local/bin/python3`, so none
#: are found. Framework-ness was never the variable — it was correlated with it.
#:
#: So a non-framework interpreter works once Resolve can see it, and `uv`/`pixi`/
#: conda-forge users are not stuck: they can point `PYTHON3HOME` at their prefix
#: without touching a system directory. It must be set with `launchctl setenv`,
#: not `export` — Resolve is GUI-launched and inherits launchd's environment, not
#: any shell's.
_FRAMEWORK_PYTHON_ROOTS = (
    Path("/Library/Frameworks/Python.framework/Versions"),
    Path("/System/Library/Frameworks/Python.framework/Versions"),
)

#: The interpreter path baked into fusionscript.so as the fallback when
#: PYTHON3HOME is unset. This is the one python.org's installer creates.
_FALLBACK_PYTHON3 = Path("/usr/local/bin/python3")

_LUA_CANARY = """-- Installed by davinci-resolve-mcp as an enumeration canary.
-- If THIS appears under Workspace > Scripts but resolve_bridge_probe does not,
-- Resolve is listing Lua and silently skipping Python: it cannot find a Python 3.
-- It looks at PYTHON3HOME, then /usr/local/bin/python3 -- and nowhere else, which
-- is why Homebrew, pyenv, uv and conda interpreters go unseen. Either point it at
-- the one you have (no sudo):
--   launchctl setenv PYTHON3HOME "$(python3 -c 'import sys; print(sys.prefix)')"
-- (launchctl, not export -- Resolve never sees your shell), or install a
-- python.org build, which creates /usr/local/bin/python3. Restart Resolve after.
print("Resolve is enumerating scripts. If the Python probe is missing, Resolve")
print("cannot find a Python 3: set PYTHON3HOME with launchctl setenv, or install")
print("a python.org build. Homebrew/pyenv/uv/conda are not looked at directly.")
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


def launchd_env(name: str) -> str | None:
    """A variable's value as a GUI-launched Resolve sees it.

    Deliberately NOT ``os.environ``. Resolve is started from the Dock or Finder,
    so it inherits launchd's environment; a ``export PYTHON3HOME=...`` in the
    terminal running this installer is invisible to it. Reading our own
    environment would report a hit in precisely the case where the user has done
    the wrong thing and needs to be told so.
    """
    import subprocess

    try:
        completed = subprocess.run(
            ["launchctl", "getenv", name],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    value = (completed.stdout or "").strip()
    return value or None


def python3_home_prefix() -> dict:
    """Is PYTHON3HOME set for Resolve, and does it point at a loadable Python 3?

    "Loadable" means the `lib/libpython3.X.dylib` that fusionscript.so dlopens.
    An interpreter that cannot supply one is reported as set-but-unusable rather
    than counted, because the silent-non-enumeration symptom is identical and the
    remedy is not.
    """
    value = launchd_env("PYTHON3HOME")
    result = {
        "value": value,
        "in_launchd": value is not None,
        "in_this_shell": os.environ.get("PYTHON3HOME") or None,
        "dylib": None,
        "usable": False,
    }
    if not value:
        return result
    try:
        dylibs = sorted(Path(value).glob("lib/libpython3.*.dylib"))
    except OSError:
        dylibs = []
    if dylibs:
        result["dylib"] = str(dylibs[0])
        result["usable"] = True
    return result


def fallback_python3() -> dict:
    """`/usr/local/bin/python3` — the path baked into fusionscript.so.

    Present for a python.org install (its installer creates it) and absent for
    Homebrew, pyenv, uv and conda, which is the whole of the "framework Pythons
    only" folklore.
    """
    result = {"path": str(_FALLBACK_PYTHON3), "exists": False, "resolves_to": None}
    try:
        if not _FALLBACK_PYTHON3.exists():
            return result
        result["exists"] = True
        result["resolves_to"] = str(_FALLBACK_PYTHON3.resolve())
    except OSError:
        pass
    return result


def python_preflight() -> dict:
    """Will Resolve list the Python probe we are about to install?

    The trap is **macOS-only**: `/Library/Frameworks/...` and
    `/usr/local/bin/python3` are not how Resolve finds Python on Windows or
    Linux (the registry, or the system interpreter). Running the macOS check
    there always found nothing and emitted the macOS remediation — telling the
    Windows 11 user in issue #106, who had a working python.org 3.12, to go
    install the Python they already had. Report "no known reason it will not
    list" off macOS rather than a false alarm; the Lua canary still ships either
    way, so a genuine enumeration problem remains diagnosable.

    On macOS, Resolve is satisfied by EITHER discovery route (see the note on
    `_FRAMEWORK_PYTHON_ROOTS`), so requiring a framework build failed a `uv` or
    `pixi` user who had a perfectly good interpreter and sent them to a
    system-wide `sudo` install they may not be permitted to run — issue #143,
    where free Resolve 21.0.4.5 ran the bridge on uv-managed CPython 3.12.13
    with no python.org Python on the machine at all.
    """
    if sys.platform != "darwin":
        return {
            "framework_pythons": [],
            "python3_home": None,
            "fallback_python3": None,
            "resolve_will_list_python_scripts": True,
            "advice": None,
        }
    frameworks = framework_pythons()
    home = python3_home_prefix()
    fallback = fallback_python3()
    # Either route is sufficient. PYTHON3HOME wins when both are present: that is
    # the order the binary's strings imply, and it is the one the user chose.
    found = home["usable"] or fallback["exists"] or bool(frameworks)
    advice = None
    if not found:
        advice = (
            "Resolve cannot find a Python 3, so it will silently ignore every "
            ".py script in its Scripts folders — they will simply not appear in "
            "Workspace > Scripts, with no error. It looks in exactly two places: "
            "the PYTHON3HOME environment variable, then /usr/local/bin/python3. "
            "Homebrew (/opt/homebrew/bin), pyenv, uv and conda land in neither, "
            "which is why they appear 'unsupported'.\n"
            "Fix it either way:\n"
            "  1. Point Resolve at the interpreter you already have, no sudo:\n"
            "       launchctl setenv PYTHON3HOME \"$(python3 -c 'import sys; "
            "print(sys.prefix)')\"\n"
            "     Use launchctl, NOT export — Resolve is launched from the Dock "
            "and never sees your shell's environment. The prefix must contain "
            "lib/libpython3.X.dylib.\n"
            "  2. Or install a python.org build, which creates "
            "/usr/local/bin/python3 for you.\n"
            "Restart Resolve either way, then re-check. The Lua canary installed "
            "alongside will list regardless, so you can tell 'Python not "
            "detected' apart from 'wrong folder'."
        )
    elif home["in_this_shell"] and not home["in_launchd"]:
        # Found by another route, but the user has clearly tried this one and it
        # will not survive into Resolve. Say so before they conclude it worked.
        advice = (
            "PYTHON3HOME is set in this shell but not in launchd, so Resolve "
            "will not see it — Resolve is GUI-launched and inherits launchd's "
            "environment, not your shell's. Python will still be found via "
            "another route this time. To make PYTHON3HOME the one that counts: "
            "launchctl setenv PYTHON3HOME \"$PYTHON3HOME\", then restart Resolve."
        )
    return {
        "framework_pythons": frameworks,
        "python3_home": home,
        "fallback_python3": fallback,
        "resolve_will_list_python_scripts": found,
        "advice": advice,
    }


def ensure_config(port: int, rotate: bool) -> dict:
    path = config_path()
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
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
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)
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
    # A target can be real, scanned by Resolve, and still unwritable — the
    # Windows all-users tree under %PROGRAMDATA% needs elevation, and Windows
    # `os.access(W_OK)` reports the read-only flag rather than the ACL, so the
    # filter above cannot screen it out. One un-writable target must not abort an
    # install that already succeeded into the per-user tree, so failures are
    # collected and only a clean sweep is fatal.
    skipped: list[tuple[str, str]] = []
    for target in targets:
        try:
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            _install_to(target, probe_only=probe_only, installed=installed)
        except OSError as exc:
            skipped.append((str(target), str(exc)))
    if not installed:
        raise SystemExit(
            "Found DaVinci Resolve Scripts/Utility folders but could not write to "
            "any of them:\n"
            + "\n".join(f"  {path}: {reason}" for path, reason in skipped)
            + "\nRe-run from an account that can write these folders (on Windows, "
            "the %PROGRAMDATA% tree needs an elevated prompt; the per-user "
            "%APPDATA% tree does not)."
        )
    result = {"installed": installed, "probe_only": probe_only, "python": python_preflight()}
    stale = stale_container_warning(targets)
    result["warnings"] = [stale] if stale else []
    if skipped:
        result["warnings"].append(
            "Skipped "
            + str(len(skipped))
            + " unwritable Scripts/Utility folder(s): "
            + "; ".join(f"{path} ({reason})" for path, reason in skipped)
            + ". This is harmless as long as the bridge appears under "
            "Workspace > Scripts."
        )
    result["skipped"] = [path for path, _ in skipped]
    if not probe_only:
        path = config_path()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        result["config"] = {"path": str(path),
                            **{k: v for k, v in loaded.items() if k != "token"}}
    return result


def _install_to(target: Path, *, probe_only: bool, installed: list[str]) -> None:
    """Place the probes, canary and (unless probe-only) the bridge into `target`.

    Raises OSError if the target turns out to be unwritable; `install()` treats
    that as a skip rather than a failure so one un-writable tree cannot abort an
    install that succeeded elsewhere.
    """
    for probe in ("resolve_bridge_probe.py", "resolve_capability_probe.py"):
        shutil.copy2(REPO / "scripts" / probe, target / probe)
        installed.append(str(target / probe))
    # Lua always enumerates; Python only with a framework install. The canary
    # makes "Python not detected" distinguishable from "wrong folder".
    canary = target / "resolve_bridge_canary.lua"
    canary.write_text(_LUA_CANARY, encoding="utf-8")
    installed.append(str(canary))
    if probe_only:
        return
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
    # authenticates against the selected config path.
    runtime_config = runtime / "bridge.json"
    path = config_path()
    shutil.copy2(path, runtime_config)
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
        base64.urlsafe_b64encode(str(path).encode("utf-8")).decode("ascii"),
    )
    launcher_path = target / "resolve_bridge.py"
    launcher_path.write_text(launcher, encoding="utf-8")
    installed.append(str(launcher_path))


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
    for warning in result["warnings"]:
        print("!" * 72)
        print("WARNING: " + warning)
        print("!" * 72)
        print()
    print("Next:")
    print("  1. Restart DaVinci Resolve so it re-scans the Scripts folders.")
    print("  2. Open a saved project (the Scripts menu is empty in Project Manager).")
    print("  3. Workspace > Scripts > resolve_bridge_probe  — run it TWICE.")
    # The probe runs INSIDE Resolve, which never sees the shell's
    # DAVINCI_RESOLVE_BRIDGE_CONFIG — it always writes to the fixed default
    # directory, so the guidance must not follow the override.
    print("  4. Read ~/.config/davinci-resolve-mcp/host-model-probe.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
