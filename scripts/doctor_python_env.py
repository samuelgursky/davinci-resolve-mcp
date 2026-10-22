"""Python-environment checks for doctor: bitness, version, and which interpreter.

Most "it will not connect" reports that are not about Resolve's preferences are
about Python, and they come in three shapes:

1. **Bitness / architecture.** `fusionscript` is a native library. It loads into
   whichever interpreter imports `DaVinciResolveScript`, and a process cannot load
   a library built for another architecture. Blackmagic requires 64-bit Python.
   A 32-bit Windows Python, or an Intel (x86_64) Python running under Rosetta
   against an arm64-only Resolve, fails at import with an error that never says
   "architecture".
2. **A Python too new for the Resolve build.** 3.13+ is verified on recent
   Resolve (Studio 20.3.2); older builds may not load the scripting module on it.
3. **Several Pythons, and the wrong one running.** The interpreter a terminal
   calls `python3` is often not the one the MCP client starts, and neither is the
   one Resolve's own Scripts menu uses. A test that passes in the terminal proves
   nothing about the server.

Where `fusionscript` loads: for external scripting (Studio) it loads into the
*server's* interpreter, so that is the one the bitness and version checks look
at. Resolve's own Workspace > Scripts menu, which the free-edition bridge runs
from, uses an interpreter Resolve finds for itself; on macOS that is
`PYTHON3HOME`, then `/usr/local/bin/python3` (see install_resolve_bridge.py).

Everything here is read-only. The fact-gathering functions take their runner and
filesystem inputs as arguments so tests can pass fakes; the check functions are
pure and take plain dicts.
"""

from __future__ import annotations

import json
import os
import plistlib
import struct
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable

#: Lowest Python the MCP SDK runs on. Mirrors install.py's SUPPORTED_PYTHON_MIN.
SUPPORTED_PYTHON_MIN = (3, 10)
#: First Python older Resolve builds may fail to load the scripting module on.
#: Mirrors install.py's PYTHON_ABI_RISK_MIN.
PYTHON_ABI_RISK_MIN = (3, 13)
#: The Resolve build 3.13+/3.14 is verified against. At or above it, a 3.13+
#: interpreter is not a warning. Compared as a whole tuple, so 20.3.0 is below.
NEWER_PYTHON_VERIFIED_RESOLVE = (20, 3, 2)

#: Probe run inside each interpreter. Python 2 compatible on purpose: a stray
#: `python` 2.7 on PATH should be reported as 2.7, not as "could not run".
#: `-E -s` keeps PYTHONPATH, PYTHONHOME and user site-packages out of it.
_PROBE_CODE = (
    "import json, platform, struct, sys, sysconfig\n"
    "print(json.dumps({"
    "'version': list(sys.version_info[:3]), "
    "'bits': struct.calcsize('P') * 8, "
    "'machine': platform.machine(), "
    "'platform': sysconfig.get_platform(), "
    "'executable': sys.executable, "
    "'prefix': sys.prefix}))\n"
)

Runner = Callable[[list], dict]


def _default_runner(cmd: list, timeout: int = 10) -> dict:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — a diagnostic must not crash
        return {"returncode": None, "stdout": "", "stderr": str(exc)}
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


# ─── Architecture ─────────────────────────────────────────────────────────────

_ELF_MACHINES = {0x03: "x86", 0x28: "arm", 0x3E: "x86_64", 0xB7: "arm64"}
_MACHO_CPUS = {7: "x86", 12: "arm", 0x01000007: "x86_64", 0x0100000C: "arm64"}
_PE_MACHINES = {0x014C: "x86", 0x01C0: "arm", 0x01C4: "arm", 0x8664: "x86_64", 0xAA64: "arm64"}


def library_architectures(path: Path) -> tuple[list[str] | None, str | None]:
    """Architectures a native library is built for, read from its header.

    Returns `(archs, None)`, or `(None, reason)` when the header cannot be read.
    Understands ELF (Linux), thin and universal Mach-O (macOS) and PE (Windows),
    which covers every `fusionscript` Blackmagic ships.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError as exc:
        return None, f"cannot read {path}: {exc.strerror or exc}"

    if head[:4] == b"\x7fELF" and len(head) >= 20:
        order = "<" if head[5] == 1 else ">"
        machine = struct.unpack_from(order + "H", head, 18)[0]
        arch = _ELF_MACHINES.get(machine)
        return ([arch] if arch else None), (None if arch else f"unknown ELF machine 0x{machine:x}")

    magic_be = struct.unpack_from(">I", head, 0)[0] if len(head) >= 4 else 0
    if magic_be in (0xCAFEBABE, 0xCAFEBABF) and len(head) >= 8:
        # Universal binary. 0xCAFEBABF is the 64-bit-offset variant (32-byte
        # entries); both start each entry with the big-endian cputype.
        count = struct.unpack_from(">I", head, 4)[0]
        size = 32 if magic_be == 0xCAFEBABF else 20
        archs = []
        for index in range(min(count, 16)):
            offset = 8 + index * size
            if offset + 4 > len(head):
                break
            cpu = struct.unpack_from(">i", head, offset)[0] & 0xFFFFFFFF
            if cpu in _MACHO_CPUS:
                archs.append(_MACHO_CPUS[cpu])
        return (archs or None), (None if archs else "universal binary with no known architecture")

    for order in ("<", ">"):
        magic = struct.unpack_from(order + "I", head, 0)[0] if len(head) >= 8 else 0
        if magic in (0xFEEDFACE, 0xFEEDFACF):
            cpu = struct.unpack_from(order + "i", head, 4)[0] & 0xFFFFFFFF
            arch = _MACHO_CPUS.get(cpu)
            return ([arch] if arch else None), (None if arch else f"unknown Mach-O cpu 0x{cpu:x}")

    if head[:2] == b"MZ" and len(head) >= 0x40:
        pe_offset = struct.unpack_from("<I", head, 0x3C)[0]
        if pe_offset + 6 <= len(head) and head[pe_offset:pe_offset + 4] == b"PE\x00\x00":
            machine = struct.unpack_from("<H", head, pe_offset + 4)[0]
            arch = _PE_MACHINES.get(machine)
            return ([arch] if arch else None), (None if arch else f"unknown PE machine 0x{machine:x}")
        return None, "PE header not within the first 4 KB"

    return None, f"{path} is not a recognised native library"


def interpreter_arch(info: dict) -> str | None:
    """The architecture an interpreter *process* runs as.

    `platform.machine()` alone is wrong on Windows: it reports the OS, so a
    32-bit Python on 64-bit Windows says "AMD64". `sysconfig.get_platform()` is
    the interpreter's own build there. Elsewhere `machine()` is the process
    (an Intel Python under Rosetta reports x86_64), corrected by pointer size.
    """
    plat = str(info.get("platform") or "").lower()
    if plat.startswith("win"):
        mapping = {"win-amd64": "x86_64", "win32": "x86", "win-arm64": "arm64", "win-arm32": "arm"}
        if plat in mapping:
            return mapping[plat]
    machine = str(info.get("machine") or "").lower()
    arch = {
        "x86_64": "x86_64", "amd64": "x86_64", "x64": "x86_64",
        "arm64": "arm64", "aarch64": "arm64", "armv8l": "arm64",
        "i386": "x86", "i686": "x86", "x86": "x86",
    }.get(machine)
    if arch is None:
        return None
    if info.get("bits") == 32:
        return {"x86_64": "x86", "arm64": "arm"}.get(arch, arch)
    return arch


# ─── Facts ────────────────────────────────────────────────────────────────────

def probe_interpreter(path: str | Path, runner: Runner | None = None) -> dict:
    """Version, pointer size and architecture of one interpreter.

    Always returns a dict with `path`; `error` is set when it could not be run.
    """
    runner = runner or _default_runner
    result: dict[str, Any] = {"path": str(path)}
    completed = runner([str(path), "-E", "-s", "-c", _PROBE_CODE])
    stdout = (completed.get("stdout") or "").strip()
    try:
        payload = json.loads(stdout.splitlines()[-1]) if stdout else None
    except (json.JSONDecodeError, IndexError):
        payload = None
    if completed.get("returncode") != 0 or not isinstance(payload, dict):
        detail = (completed.get("stderr") or stdout or "").strip().splitlines()
        result["error"] = detail[-1] if detail else f"exited with {completed.get('returncode')}"
        return result
    result.update(payload)
    result["version"] = tuple(int(part) for part in payload.get("version") or ())
    result["arch"] = interpreter_arch(payload)
    return result


def _real(path: str | Path) -> str:
    try:
        return os.path.normcase(os.path.realpath(str(path)))
    except OSError:
        return os.path.normcase(str(path))


def pythons_on_path(
    path_value: str | None = None,
    platform: str | None = None,
    is_file: Callable[[Path], bool] | None = None,
) -> list[dict]:
    """Every `python3`/`python` on PATH, in PATH order, as `{path, name}`.

    The first is what a terminal runs. Duplicates are NOT collapsed here: a
    venv's `python` and the base interpreter it links to share a real path but
    not a `sys.prefix`, so they are different Pythons as far as installed
    packages go. `dedupe_interpreters` collapses them after probing.
    """
    import sys

    platform = platform or sys.platform
    path_value = os.environ.get("PATH", "") if path_value is None else path_value
    is_file = is_file or (lambda candidate: candidate.is_file())
    names = ("python.exe", "python3.exe") if platform == "win32" else ("python3", "python")
    found: list[dict] = []
    seen: set[str] = set()
    for directory in path_value.split(os.pathsep):
        if not directory:
            continue
        for name in names:
            candidate = Path(directory) / name
            key = os.path.normcase(str(candidate))
            if key in seen:
                continue
            try:
                if not is_file(candidate):
                    continue
            except OSError:
                continue
            seen.add(key)
            found.append({"path": str(candidate), "name": name})
    return found


def same_interpreter(a: dict, b: dict) -> bool:
    """Same path, or same binary AND same `sys.prefix` (i.e. same packages)."""
    if os.path.normcase(os.path.abspath(a["path"])) == os.path.normcase(os.path.abspath(b["path"])):
        return True
    if a.get("error") or b.get("error"):
        return False
    return _real(a["path"]) == _real(b["path"]) and a.get("prefix") == b.get("prefix")


def dedupe_interpreters(probed: list[dict]) -> list[dict]:
    """Collapse probed PATH entries that are the same interpreter, keeping order."""
    kept: list[dict] = []
    for item in probed:
        if not any(same_interpreter(item, other) for other in kept):
            kept.append(item)
    return kept


def client_python_commands(claude_config: Path, codex_config: Path, server_name: str = "server.py") -> list[dict]:
    """The interpreter each MCP client config starts the server with.

    Only entries whose args name the server script count, so another MCP
    server in the same file is not mistaken for this one. Codex's TOML is read
    with `tomllib` where available (3.11+); without it Codex is skipped rather
    than guessed at.
    """
    commands: list[dict] = []

    def _collect(client: str, servers: Any) -> None:
        if not isinstance(servers, dict):
            return
        for key, entry in servers.items():
            if not isinstance(entry, dict):
                continue
            args = entry.get("args") or []
            if not isinstance(args, list) or not any(server_name in str(arg) for arg in args):
                continue
            command = entry.get("command")
            if isinstance(command, str) and command:
                commands.append({"client": client, "entry": str(key), "command": command})

    try:
        data = json.loads(claude_config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict):
        _collect("Claude Desktop", data.get("mcpServers"))

    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        tomllib = None
    if tomllib is not None:
        try:
            toml = tomllib.loads(codex_config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            toml = None
        if isinstance(toml, dict):
            _collect("Codex", toml.get("mcp_servers"))
    return commands


def resolve_app_version(app: Path) -> tuple[int, ...] | None:
    """Resolve's version from the macOS app bundle, without Resolve running.

    macOS only — Windows keeps it in a PE version resource and Linux in no fixed
    place, so those return None and the version check falls back to the live
    probe's answer or to a hedged warning.
    """
    plist = app / "Contents" / "Info.plist"
    try:
        with open(plist, "rb") as handle:
            data = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    return parse_version(data.get("CFBundleShortVersionString") or data.get("CFBundleVersion"))


def parse_version(value: Any) -> tuple[int, ...] | None:
    """Leading numeric dotted parts of a version string: "19.1.3.7" -> (19, 1, 3, 7)."""
    if not value:
        return None
    parts: list[int] = []
    for piece in str(value).strip().split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
        if len(digits) != len(piece):
            break
    return tuple(parts) or None


# ─── Fix text ─────────────────────────────────────────────────────────────────

def _fmt_version(version: Iterable[int] | None) -> str:
    return ".".join(str(part) for part in (version or ())) or "unknown"


def _describe(info: dict) -> str:
    if info.get("error"):
        return f"{info['path']} (could not run: {info['error']})"
    return f"{info['path']} — Python {_fmt_version(info.get('version'))}, {info.get('bits')}-bit {info.get('arch') or info.get('machine') or '?'}"


def rebuild_fix(server_python: str, repo: Path, platform: str, want: str = "a 64-bit Python 3.12") -> str:
    """The exact commands that rebuild the server's environment on a better Python.

    install.py *reuses* an existing venv, so "re-run the installer with 3.12" on
    its own changes nothing. The venv is moved aside (not deleted) first.
    """
    venv_dirs = [repo / "venv", repo / ".venv"]
    # Compared as written, not resolved: a venv's python resolves to the base
    # interpreter outside the venv.
    in_venv = next(
        (venv for venv in venv_dirs
         if os.path.normcase(str(server_python)).startswith(os.path.normcase(str(venv)) + os.sep)),
        None,
    )
    if platform == "win32":
        installer = f'py -3.12 "{repo / "install.py"}"'
        install_note = " (python.org's \"Windows installer (64-bit)\")"
        move = f'move "{in_venv}" "{in_venv}.old"' if in_venv else None
    else:
        installer = f'python3.12 "{repo / "install.py"}"'
        install_note = ""
        move = f'mv "{in_venv}" "{in_venv}.old"' if in_venv else None
    if move:
        return (
            f"Install {want}{install_note}, then rebuild the server's venv on it — "
            f"install.py reuses an existing venv, so move it aside first: {move} && {installer}"
        )
    return (
        f"Install {want}{install_note}, then point the MCP clients at it: "
        f"{installer} --no-venv --python <path to that python>"
    )


# ─── Checks ───────────────────────────────────────────────────────────────────

def _result(status: str, name: str, detail: str, fix: str | None = None) -> dict:
    item = {"status": status, "name": name, "detail": detail}
    if fix:
        item["fix"] = fix
    return item


def check_bitness(server: dict, lib_path: Path, lib_archs: list[str] | None,
                  lib_reason: str | None, repo: Path, platform: str) -> dict:
    """Is the server's interpreter 64-bit, and can it load this fusionscript?"""
    name = "Python bitness"
    if server.get("error"):
        return _result(
            "FAIL", name, f"could not run the server's Python: {_describe(server)}",
            rebuild_fix(server["path"], repo, platform),
        )
    arch = server.get("arch")
    if server.get("bits") == 32:
        return _result(
            "FAIL", name,
            f"{_describe(server)}. Resolve's scripting library is 64-bit only "
            "(Blackmagic requires 64-bit Python), so a 32-bit interpreter cannot import it.",
            rebuild_fix(server["path"], repo, platform),
        )
    if lib_archs is None:
        return _result(
            "INFO", name,
            f"{_describe(server)}. The scripting library's architecture was not read "
            f"({lib_reason}), so whether this interpreter can load it is unchecked.",
        )
    if arch and arch not in lib_archs:
        rosetta = ""
        if platform == "darwin" and arch == "x86_64" and "arm64" in lib_archs:
            rosetta = (
                " This is an Intel Python running under Rosetta on an Apple silicon "
                "Mac — Intel Homebrew in /usr/local and x86_64 conda installs are the "
                "usual source."
            )
        return _result(
            "FAIL", name,
            f"{_describe(server)}, but {lib_path} is built for {', '.join(lib_archs)}. "
            f"A process cannot load a library of another architecture.{rosetta}",
            rebuild_fix(server["path"], repo, platform, want=f"a native {lib_archs[0]} Python 3.12"),
        )
    universal = " (universal)" if len(lib_archs) > 1 else ""
    return _result(
        "OK", name,
        f"{server.get('bits')}-bit {arch or server.get('machine')}; fusionscript is "
        f"{', '.join(lib_archs)}{universal}",
    )


def check_version(server: dict, resolve_version: tuple[int, ...] | None,
                  probe: dict, lib_exists: bool, repo: Path, platform: str) -> dict:
    """Is the server's Python inside the range the SDK and this Resolve load?"""
    name = "Python version for Resolve"
    if server.get("error"):
        return _result("INFO", name, "not checked — the server's Python could not be run (see Python bitness)")
    version = tuple(server.get("version") or ())
    shown = _fmt_version(version)
    if version[:2] < SUPPORTED_PYTHON_MIN:
        return _result(
            "FAIL", name,
            f"Python {shown} is below {SUPPORTED_PYTHON_MIN[0]}.{SUPPORTED_PYTHON_MIN[1]}, "
            "the MCP SDK's floor; the server cannot start on it.",
            rebuild_fix(server["path"], repo, platform),
        )
    if version[:2] < PYTHON_ABI_RISK_MIN:
        return _result("OK", name, f"Python {shown} (3.10–3.12 is the lowest-risk range)")

    resolve_shown = _fmt_version(resolve_version) if resolve_version else None
    if probe.get("resolve_connected") and probe.get("transport") != "bridge":
        answered = f"Resolve {probe['version']}" if probe.get("version") else "Resolve"
        return _result(
            "OK", name,
            f"Python {shown}, and {answered} answered on this interpreter, so its "
            "scripting module loads here.",
        )
    import_error = str(probe.get("error") or "")
    if probe.get("import_ok") is False and lib_exists and "No module named" not in import_error:
        return _result(
            "FAIL", name,
            f"Python {shown} could not import Resolve's scripting module "
            f"({probe.get('error')}). The library exists, so the likeliest cause is "
            f"that this Resolve build{' (' + resolve_shown + ')' if resolve_shown else ''} "
            "does not load on Python 3.13+.",
            rebuild_fix(server["path"], repo, platform),
        )
    if resolve_version and tuple(resolve_version) >= NEWER_PYTHON_VERIFIED_RESOLVE:
        return _result(
            "OK", name,
            f"Python {shown} with Resolve {resolve_shown}; 3.13+ is verified on Resolve "
            "20.3.2, and this build is that or newer.",
        )
    which = f"Resolve {resolve_shown}" if resolve_shown else "this Resolve (version not readable)"
    return _result(
        "WARN", name,
        f"Python {shown} with {which}. 3.13+ is verified on Resolve 20.3.2; older "
        "builds may fail to load the scripting module on it (scriptapp(\"Resolve\") "
        "returns None, or the import crashes).",
        "If Resolve is running with scripting enabled and still does not answer: "
        + rebuild_fix(server["path"], repo, platform),
    )


def check_interpreters(server: dict, on_path: list[dict], clients: list[dict],
                       resolve_python: dict | None, platform: str) -> list[dict]:
    """Which Python runs the server, which one a terminal gets, which one Resolve uses.

    `on_path` entries are probed dicts from `pythons_on_path` (path order).
    `clients` are `{client, command, info?}` dicts; `info` is the probe of the
    command's interpreter when it is an absolute path that differs from `server`.
    `resolve_python` is `{path, source}` for the interpreter Resolve's own Scripts
    menu uses, when known (macOS), else None.
    """
    results: list[dict] = []

    def _is_server(item: dict) -> bool:
        return same_interpreter(item, server)

    # 1. Each client's command: bare name vs absolute, and whether it is ours.
    for entry in clients:
        command = entry["command"]
        label = f"{entry['client']} interpreter"
        if os.sep not in command and "/" not in command:
            terminal = on_path[0]["path"] if on_path else "nothing (no python on this PATH)"
            results.append(_result(
                "WARN", label,
                f"starts the server as `{command}`, which is looked up on the PATH the "
                f"client app sees. GUI apps do not read your shell profile, so that can "
                f"be a different Python from this terminal's ({terminal}) and from the "
                f"one doctor checked ({server['path']}).",
                f"Set \"command\" for the {entry['entry']} entry to the absolute path "
                f"{server['path']}, then restart {entry['client']}.",
            ))
        elif _is_server(entry.get("info") or {"path": command, "error": "not probed"}):
            results.append(_result("OK", label, f"{command} — the interpreter checked above"))
        else:
            info = entry.get("info") or {"path": command, "error": "not probed"}
            results.append(_result(
                "WARN", label,
                f"starts the server with {_describe(info)}, not the interpreter doctor "
                f"checked ({server['path']}). The bitness and version checks above do "
                "not describe what this client runs.",
                f"Set \"command\" for the {entry['entry']} entry to {server['path']}, or "
                f"re-run doctor with DAVINCI_MCP_PYTHON={command} to check that one.",
            ))

    # 2. What a terminal gets vs what runs the server.
    stub = [item for item in on_path if platform == "win32" and "\\windowsapps\\" in item["path"].lower()]
    for item in stub:
        results.append(_result(
            "WARN", "Microsoft Store python alias",
            f"{item['path']} is the App Execution Alias stub, not an installed Python; "
            "a bare `python` can resolve to it and open the Store instead of running.",
            "Settings > Apps > Advanced app settings > App execution aliases: turn off "
            "python.exe and python3.exe.",
        ))
    listing = "; ".join(
        _describe(item) + (" [runs the server]" if _is_server(item) else "")
        for item in on_path
    ) or "none"
    if len(on_path) <= 1:
        results.append(_result("OK", "Pythons on PATH", listing))
    else:
        first = on_path[0]
        if _is_server(first):
            summary = f"{len(on_path)} found; the first is the server's own interpreter."
        else:
            summary = (
                f"{len(on_path)} found. `{first['name']}` in a terminal is "
                f"{first['path']}, not the server's {server['path']} — test imports "
                f"with \"{server['path']}\" -c \"import DaVinciResolveScript\", not "
                f"`{first['name']}`."
            )
        broken = [
            item for item in on_path
            if not item.get("error") and (item.get("bits") == 32 or tuple(item.get("version") or ())[:2] < SUPPORTED_PYTHON_MIN)
        ]
        bare = any(os.sep not in c["command"] and "/" not in c["command"] for c in clients)
        status = "WARN" if bare and not _is_server(first) else "INFO"
        if not _is_server(first) and first in broken:
            status = "WARN"
            summary += (
                f" The first one is {first.get('bits')}-bit Python "
                f"{_fmt_version(first.get('version'))}, which cannot run the server; "
                "anything started as a bare `python` gets it."
            )
        results.append(_result(
            status, "Pythons on PATH", f"{summary} All: {listing}",
            (f"Use absolute interpreter paths in MCP configs ({server['path']}), or put "
             "a 64-bit Python 3.10–3.12 first on PATH.") if status == "WARN" else None,
        ))

    # 3. Where fusionscript loads, and Resolve's own interpreter.
    resolve_side = (
        f"Resolve's own Scripts menu (and the free-edition bridge) uses {resolve_python['path']} "
        f"({resolve_python['source']})"
        if resolve_python else
        "Resolve's own Scripts menu finds its Python itself"
        + (" — none found via PYTHON3HOME or /usr/local/bin/python3; see 'Free-edition bridge'"
           if platform == "darwin" else "")
    )
    results.append(_result(
        "INFO", "Where fusionscript loads",
        f"External scripting loads fusionscript into the server's interpreter "
        f"({server['path']}); {resolve_side}. The two need not match — the bridge talks "
        "to the server over loopback.",
    ))
    return results


# ─── Entry point ──────────────────────────────────────────────────────────────

def resolve_menu_python(platform: str) -> dict | None:
    """The interpreter Resolve's Scripts menu would use, where that is knowable.

    macOS only, via the bridge installer's preflight, which reads launchd's
    PYTHON3HOME and /usr/local/bin/python3 the way fusionscript does.
    """
    if platform != "darwin":
        return None
    try:
        import install_resolve_bridge as bridge  # type: ignore
        preflight = bridge.python_preflight()
    except Exception:  # noqa: BLE001
        return None
    home = preflight.get("python3_home") or {}
    if home.get("usable"):
        return {"path": home.get("interpreter"), "source": "PYTHON3HOME"}
    fallback = preflight.get("fallback_python3") or {}
    if fallback.get("exists"):
        return {"path": fallback.get("resolves_to") or fallback.get("path"), "source": "/usr/local/bin/python3"}
    return None


def collect(
    *,
    server_python: Path,
    lib_path: Path,
    app_path: Path,
    repo: Path,
    probe: dict,
    claude_config: Path,
    codex_config: Path,
    platform: str | None = None,
    runner: Runner | None = None,
    path_value: str | None = None,
    menu_python: dict | None | bool = False,
) -> list[dict]:
    """Run every Python-environment check against this machine.

    `runner`, `path_value` and `menu_python` exist for tests; leave them unset
    to inspect the real environment. `menu_python=False` means "look it up".
    """
    import sys

    platform = platform or sys.platform
    runner = runner or _default_runner
    server = probe_interpreter(server_python, runner)
    lib_archs, lib_reason = library_architectures(lib_path)
    resolve_version = parse_version(probe.get("version")) or resolve_app_version(app_path)

    results = [
        check_bitness(server, lib_path, lib_archs, lib_reason, repo, platform),
        check_version(server, resolve_version, probe, lib_path.exists(), repo, platform),
    ]
    if server.get("error"):
        return results

    on_path = dedupe_interpreters([
        {**item, **probe_interpreter(item["path"], runner)}
        for item in pythons_on_path(path_value, platform)[:12]
    ])
    clients = client_python_commands(claude_config, codex_config)
    for entry in clients:
        command = entry["command"]
        if os.sep in command or "/" in command:
            entry["info"] = (
                server if same_interpreter({"path": command}, server)
                else probe_interpreter(command, runner)
            )
    if menu_python is False:
        menu_python = resolve_menu_python(platform)
    results.extend(check_interpreters(server, on_path, clients, menu_python or None, platform))
    return results
