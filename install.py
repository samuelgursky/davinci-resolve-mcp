#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server — Universal Installer

Supports: macOS, Windows, Linux
Configures: Claude Desktop, Claude Code, Cursor, VS Code (Copilot),
            Windsurf, Cline, Roo Code, Zed, Continue, OpenCode, and manual setup.

Usage:
    python install.py                  # Interactive mode
    python install.py --clients all    # Install all clients non-interactively
    python install.py --clients cursor,claude-desktop --no-venv
    python install.py --help
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from src.utils.update_check import (
    clear_update_prompt_preferences,
    check_for_updates,
    ignore_update_version,
    set_update_mode,
    snooze_update_prompt,
    update_prompt_decision,
)

# ─── Version ──────────────────────────────────────────────────────────────────

VERSION = "2.57.5"
# Only hard floor: mcp[cli] requires Python 3.10+. There is no upper bound —
# Resolve's scripting bridge loads into newer interpreters on recent builds
# (Python 3.14 verified against Resolve Studio 20.3.2). Older Resolve builds
# may fail to connect on 3.13+, but the connection check is the real signal,
# so we proceed with a heads-up rather than refusing to run.
SUPPORTED_PYTHON_MIN = (3, 10)
PYTHON_ABI_RISK_MIN = (3, 13)

# ─── Colors (disabled on Windows cmd without ANSI support) ────────────────────

def _supports_color():
    if os.environ.get("NO_COLOR"):
        return False
    if platform.system() == "Windows":
        return os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM")
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

USE_COLOR = _supports_color()

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def green(t):  return _c("32", t)
def yellow(t): return _c("33", t)
def red(t):    return _c("31", t)
def bold(t):   return _c("1", t)
def dim(t):    return _c("2", t)
def cyan(t):   return _c("36", t)

# ─── Platform Detection ──────────────────────────────────────────────────────

SYSTEM = platform.system()  # Darwin, Windows, Linux

def is_mac():     return SYSTEM == "Darwin"
def is_windows(): return SYSTEM == "Windows"
def is_linux():   return SYSTEM == "Linux"

def platform_name():
    if is_mac():     return "macOS"
    if is_windows(): return "Windows"
    if is_linux():   return "Linux"
    return SYSTEM


def is_supported_python_version(version):
    major, minor = version[:2]
    return major == 3 and minor >= SUPPORTED_PYTHON_MIN[1]


def is_abi_risk_python_version(version):
    major, minor = version[:2]
    return major == 3 and minor >= PYTHON_ABI_RISK_MIN[1]


def format_python_version(version):
    return ".".join(str(part) for part in version[:3])


def python_requirement_text():
    return f"Python {SUPPORTED_PYTHON_MIN[0]}.{SUPPORTED_PYTHON_MIN[1]} or newer"


_ABI_NOTE_PRINTED = False


def print_abi_risk_note_once(version, label="Python"):
    """Emit the 3.13+ heads-up at most once per installer run."""
    global _ABI_NOTE_PRINTED
    if _ABI_NOTE_PRINTED:
        return
    _ABI_NOTE_PRINTED = True
    print(f"  {yellow(label + ':')} {python_abi_risk_note(version)}")


def python_abi_risk_note(version):
    return (
        f"Using Python {format_python_version(version)}. Verified working on recent "
        f"Resolve builds (Studio 20.3.2). If Resolve fails to connect "
        f"(scriptapp(\"Resolve\") returns None), install Python 3.10-3.12 and re-run "
        f"with it, e.g.: python3.12 install.py"
    )


def python_fix_hint():
    return (
        "  How to fix:\n"
        "    - Install Python 3.12 (the lowest-risk version for Resolve), e.g.:\n"
        "        macOS:   brew install python@3.12   (or: pyenv install 3.12)\n"
        "        Linux:   pyenv install 3.12          (or your distro's python3.12 package)\n"
        "        Windows: install Python 3.12 from python.org\n"
        "    - Re-run with that interpreter, e.g.:  python3.12 install.py"
    )


def _version_for_python(python_path):
    script = (
        "import sys; "
        "print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    )
    result = subprocess.run(
        [str(python_path), "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(output or f"{python_path} exited with code {result.returncode}")
    parts = result.stdout.strip().split(".")
    if len(parts) < 2:
        raise RuntimeError(f"could not parse Python version from {python_path!s}")
    return tuple(int(part) for part in parts[:3])


def require_supported_python(python_path, label="Python"):
    try:
        version = _version_for_python(python_path)
    except Exception as exc:
        print(f"  {red(label + ':')} Could not inspect {python_path}: {exc}")
        sys.exit(1)
    if not is_supported_python_version(version):
        print(
            f"  {red(label + ':')} {python_requirement_text()} is required "
            f"(the MCP SDK needs 3.10+); found {format_python_version(version)} "
            f"at {python_path}"
        )
        print(python_fix_hint())
        sys.exit(1)
    if is_abi_risk_python_version(version):
        print_abi_risk_note_once(version, label)
    return version


def require_current_python(label="Python"):
    version = (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    if not is_supported_python_version(version):
        print(
            f"  {red(label + ':')} {python_requirement_text()} is required "
            f"(the MCP SDK needs 3.10+); current interpreter is "
            f"{format_python_version(version)} at {sys.executable}"
        )
        print(python_fix_hint())
        sys.exit(1)
    if is_abi_risk_python_version(version):
        print_abi_risk_note_once(version, label)
    return version

# ─── Resolve Path Detection ──────────────────────────────────────────────────

RESOLVE_PATHS = {
    "Darwin": {
        "api": [
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
        ],
        "lib": [
            "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
        ],
        "app": [
            "/Applications/DaVinci Resolve/DaVinci Resolve.app",
        ],
    },
    "Windows": {
        "api": [
            r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Developer\Scripting",
        ],
        "lib": [
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
        ],
        "app": [
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe",
        ],
    },
    "Linux": {
        "api": [
            "/opt/resolve/Developer/Scripting",
            "/opt/resolve/libs/Fusion/Developer/Scripting",
            "/home/{user}/.local/share/DaVinciResolve/Developer/Scripting",
        ],
        "lib": [
            "/opt/resolve/libs/Fusion/fusionscript.so",
            "/opt/resolve/bin/fusionscript.so",
        ],
        "app": [
            "/opt/resolve/bin/resolve",
        ],
    },
}


def find_resolve_paths():
    """Auto-detect DaVinci Resolve installation paths."""
    candidates = RESOLVE_PATHS.get(SYSTEM, RESOLVE_PATHS["Linux"])
    username = os.environ.get("USER", os.environ.get("USERNAME", ""))

    api_path = None
    lib_path = None

    for p in candidates["api"]:
        expanded = p.replace("{user}", username)
        if os.path.isdir(expanded):
            api_path = expanded
            break

    for p in candidates["lib"]:
        expanded = p.replace("{user}", username)
        if os.path.isfile(expanded):
            lib_path = expanded
            break

    return api_path, lib_path


def check_resolve_running():
    """Check if DaVinci Resolve is currently running."""
    try:
        if is_mac():
            result = subprocess.run(
                ["pgrep", "-f", "DaVinci Resolve"],
                capture_output=True, text=True
            )
            return result.returncode == 0
        elif is_windows():
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Resolve.exe"],
                capture_output=True, text=True
            )
            return "Resolve.exe" in result.stdout
        else:  # Linux
            result = subprocess.run(
                ["pgrep", "-f", "resolve"],
                capture_output=True, text=True
            )
            return result.returncode == 0
    except Exception:
        return False

# ─── MCP Client Definitions ──────────────────────────────────────────────────

def home():
    return Path.home()

def appdata():
    """Windows %APPDATA% equivalent."""
    return Path(os.environ.get("APPDATA", home() / "AppData" / "Roaming"))

def xdg_config():
    """Linux XDG_CONFIG_HOME or default."""
    return Path(os.environ.get("XDG_CONFIG_HOME", home() / ".config"))

def vscode_global_storage():
    """VS Code global storage path per platform."""
    if is_mac():
        return home() / "Library" / "Application Support" / "Code" / "User" / "globalStorage"
    elif is_windows():
        return appdata() / "Code" / "User" / "globalStorage"
    else:
        return xdg_config() / "Code" / "User" / "globalStorage"


# Each client entry:
#   id, name, config_path_fn, config_key, merge_strategy, notes
# config_path_fn returns the path; config_key is the JSON key wrapping the server entry
# merge_strategy: "merge" = add to existing JSON; "create" = create if not exists

MCP_CLIENTS = [
    {
        "id": "antigravity",
        "name": "Antigravity",
        "get_path": lambda: home() / ".gemini" / "antigravity" / "mcp_config.json",
        "config_key": "mcpServers",
        "notes": "Google's agentic AI coding assistant (VS Code fork)",
    },
    {
        "id": "claude-desktop",
        "name": "Claude Desktop",
        "get_path": lambda: {
            "Darwin":  home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            "Windows": appdata() / "Claude" / "claude_desktop_config.json",
            "Linux":   xdg_config() / "Claude" / "claude_desktop_config.json",
        }.get(SYSTEM),
        "config_key": "mcpServers",
        "notes": "Anthropic's desktop app for Claude",
    },
    {
        "id": "claude-code",
        "name": "Claude Code",
        "get_path": lambda: Path.cwd() / ".mcp.json",
        "config_key": "mcpServers",
        "notes": "Project-scoped config (committed to repo)",
    },
    {
        "id": "cursor",
        "name": "Cursor",
        "get_path": lambda: {
            "Darwin":  home() / ".cursor" / "mcp.json",
            "Windows": home() / ".cursor" / "mcp.json",
            "Linux":   home() / ".cursor" / "mcp.json",
        }.get(SYSTEM),
        "config_key": "mcpServers",
        "notes": "AI-native code editor (VS Code fork)",
    },
    {
        "id": "vscode",
        "name": "VS Code (GitHub Copilot)",
        "get_path": lambda: Path.cwd() / ".vscode" / "mcp.json",
        "config_key": "servers",
        "notes": "Workspace-scoped config for Copilot agent mode",
    },
    {
        "id": "windsurf",
        "name": "Windsurf",
        "get_path": lambda: {
            "Darwin":  home() / ".codeium" / "windsurf" / "mcp_config.json",
            "Windows": appdata() / "windsurf" / "mcp_settings.json",
            "Linux":   home() / ".codeium" / "windsurf" / "mcp_config.json",
        }.get(SYSTEM),
        "config_key": "mcpServers",
        "notes": "Codeium's AI code editor",
    },
    {
        "id": "cline",
        "name": "Cline",
        "get_path": lambda: vscode_global_storage() / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
        "config_key": "mcpServers",
        "notes": "AI coding assistant (VS Code extension)",
    },
    {
        "id": "roo-code",
        "name": "Roo Code",
        "get_path": lambda: vscode_global_storage() / "rooveterinaryinc.roo-cline" / "settings" / "mcp_settings.json",
        "config_key": "mcpServers",
        "notes": "Autonomous AI coding assistant (VS Code extension)",
    },
    {
        "id": "zed",
        "name": "Zed",
        "get_path": lambda: {
            "Darwin":  home() / ".config" / "zed" / "settings.json",
            "Windows": None,  # Zed doesn't support Windows yet
            "Linux":   home() / ".config" / "zed" / "settings.json",
        }.get(SYSTEM),
        "config_key": "context_servers",
        "notes": "High-performance code editor (macOS/Linux only)",
    },
    {
        "id": "continue",
        "name": "Continue",
        "get_path": lambda: {
            "Darwin":  home() / ".continue" / "config.json",
            "Windows": home() / ".continue" / "config.json",
            "Linux":   home() / ".continue" / "config.json",
        }.get(SYSTEM),
        "config_key": "mcpServers",
        "notes": "Open-source AI code assistant",
    },
    {
        "id": "opencode",
        "name": "OpenCode",
        # OpenCode uses ~/.config/opencode/opencode.json on every platform
        # (it also reads a project-root opencode.json, but the global file is
        # the safe default for an installer). See https://opencode.ai/docs/config/
        "get_path": lambda: home() / ".config" / "opencode" / "opencode.json",
        "config_key": "mcp",
        "notes": "AI coding agent (uses its own type/enabled/command-array format)",
    },
]

CLIENT_IDS = [c["id"] for c in MCP_CLIENTS]

# ─── Server Entry Builder ────────────────────────────────────────────────────

def get_python_base_install(python_path):
    """Resolve the base Python install used by the selected interpreter."""
    script = "import sys; print(sys.base_prefix or sys.prefix)"
    try:
        result = subprocess.run(
            [str(python_path), "-c", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        base_prefix = result.stdout.strip()
        if result.returncode == 0 and base_prefix:
            return base_prefix
    except Exception as exc:
        print(f"Warning: Could not query Python base prefix: {exc}")

    resolved = Path(python_path).resolve()
    if resolved.parent.name.lower() in {"scripts", "bin"}:
        return str(resolved.parent.parent)
    return str(resolved.parent)


def build_server_env(python_path, api_path, lib_path, system=SYSTEM, python_home=None):
    """Build the env block used by all generated stdio MCP configs."""
    api_value = str(api_path or "")
    lib_value = str(lib_path or "")
    env = {
        "RESOLVE_SCRIPT_API": api_value,
        "RESOLVE_SCRIPT_LIB": lib_value,
        "PYTHONPATH": str(Path(api_value) / "Modules") if api_value else "",
    }

    if system == "Windows":
        env["PYTHONHOME"] = str(python_home or get_python_base_install(python_path))

    return env


def build_server_entry(python_path, server_path, api_path, lib_path, system=SYSTEM, python_home=None):
    """Build the standard MCP server config entry."""
    return {
        "command": str(python_path),
        "args": [str(server_path)],
        "env": build_server_env(python_path, api_path, lib_path, system=system, python_home=python_home),
    }


def build_zed_entry(python_path, server_path, api_path, lib_path, system=SYSTEM, python_home=None):
    """Build Zed-specific server entry (different format)."""
    return {
        "command": {
            "path": str(python_path),
            "args": [str(server_path)],
        },
        "env": build_server_env(python_path, api_path, lib_path, system=system, python_home=python_home),
        "settings": {},
    }


def build_opencode_entry(python_path, server_path, api_path, lib_path, system=SYSTEM, python_home=None):
    """Build OpenCode-specific server entry (issue #72).

    OpenCode's schema differs from the standard format in three ways: it wraps
    the entry in a ``"mcp"`` key, the interpreter and script are a single
    ``"command"`` array (no separate ``args``), and the environment block is
    ``"environment"`` rather than ``"env"``. It also expects ``type``/``enabled``
    discriminators. See https://opencode.ai/docs/mcp-servers/
    """
    return {
        "type": "local",
        "enabled": True,
        "command": [str(python_path), str(server_path)],
        "environment": build_server_env(python_path, api_path, lib_path, system=system, python_home=python_home),
    }


def build_entry_for_client(client, python_path, server_path, api_path, lib_path, system=SYSTEM, python_home=None):
    """Return the server entry shaped for a specific client's config schema."""
    builders = {
        "zed": build_zed_entry,
        "opencode": build_opencode_entry,
    }
    builder = builders.get(client["id"], build_server_entry)
    return builder(python_path, server_path, api_path, lib_path, system=system, python_home=python_home)

# ─── Config File Operations ──────────────────────────────────────────────────

class ConfigParseError(Exception):
    """Existing config file has content but could not be parsed.

    Callers must NOT overwrite such a file -- doing so destroys the user's
    settings (issue #71).
    """


def _strip_jsonc(text):
    """Best-effort strip of // and /* */ comments and trailing commas.

    Zed's ``settings.json`` (and several other clients) accept JSON-with-comments.
    Python's ``json`` module rejects those, so we strip them before parsing.
    The walk is string-aware, so a ``//`` or ``/*`` sequence inside a JSON
    string value is preserved.
    """
    out = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    stripped = "".join(out)
    # Drop trailing commas before a closing brace/bracket — string-aware, so a
    # comma inside a string value (e.g. "a, }") is never touched. A prior regex
    # pass here was NOT string-aware and silently corrupted such values during a
    # JSONC merge (follow-up to the issue #71 fix).
    result = []
    i = 0
    n = len(stripped)
    in_string = False
    escape = False
    while i < n:
        ch = stripped[i]
        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and stripped[j] in " \t\r\n":
                j += 1
            if j < n and stripped[j] in "}]":
                i += 1  # trailing comma: drop it
                continue
        result.append(ch)
        i += 1
    return "".join(result)


def read_json(path):
    """Read a JSON/JSONC config file.

    Returns an empty dict when the file is absent or empty (safe to create).
    Raises :class:`ConfigParseError` when the file has content that cannot be
    parsed even after stripping JSONC comments and trailing commas -- callers
    must refuse to overwrite such a file, or they would wipe the user's
    existing settings (issue #71: Zed's settings.json ships with comments).
    """
    try:
        with open(path, "r") as f:
            raw = f.read()
    except FileNotFoundError:
        return {}

    if not raw.strip():
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    try:
        return json.loads(_strip_jsonc(raw))
    except json.JSONDecodeError as exc:
        raise ConfigParseError(str(exc)) from exc


def write_json(path, data):
    """Write JSON to file, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Backup existing file
    if path.exists():
        backup = path.with_suffix(path.suffix + ".backup")
        shutil.copy2(path, backup)

    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def write_client_config(client, python_path, server_path, api_path, lib_path, dry_run=False):
    """Write or merge MCP config for a specific client. Returns (success, message)."""
    config_path = client["get_path"]()
    if config_path is None:
        return False, f"{client['name']} is not available on {platform_name()}"

    config_key = client["config_key"]

    # Build the server entry (some clients use a non-standard schema)
    server_entry = build_entry_for_client(client, python_path, server_path, api_path, lib_path)

    if dry_run:
        preview = {config_key: {"davinci-resolve": server_entry}}
        return True, f"Would write to {config_path}:\n{json.dumps(preview, indent=2)}"

    # Read existing config and merge. If the file exists but cannot be parsed,
    # refuse to overwrite it -- silently replacing it would wipe the user's
    # settings (issue #71, especially Zed's commented settings.json).
    try:
        existing = read_json(config_path)
    except ConfigParseError as exc:
        return False, (
            f"{config_path} exists but could not be parsed ({exc}). "
            f"Refusing to overwrite to avoid data loss. Add the "
            f'"{config_key}" entry manually using the manual config output '
            f"(run with --manual)."
        )

    if config_key not in existing:
        existing[config_key] = {}

    existing[config_key]["davinci-resolve"] = server_entry

    write_json(config_path, existing)
    return True, str(config_path)


def generate_manual_config(python_path, server_path, api_path, lib_path):
    """Generate config snippets for manual setup."""
    entry = build_server_entry(python_path, server_path, api_path, lib_path)
    zed_entry = build_zed_entry(python_path, server_path, api_path, lib_path)
    opencode_entry = build_opencode_entry(python_path, server_path, api_path, lib_path)

    standard = json.dumps({"mcpServers": {"davinci-resolve": entry}}, indent=2)
    vscode_fmt = json.dumps({"servers": {"davinci-resolve": entry}}, indent=2)
    zed_fmt = json.dumps({"context_servers": {"davinci-resolve": zed_entry}}, indent=2)
    opencode_fmt = json.dumps({"mcp": {"davinci-resolve": opencode_entry}}, indent=2)

    return standard, vscode_fmt, zed_fmt, opencode_fmt

# ─── Virtual Environment ─────────────────────────────────────────────────────

def find_python():
    """Find the best Python 3 executable."""
    candidates = ["python3", "python"]
    for cmd in candidates:
        try:
            result = subprocess.run(
                [cmd, "--version"], capture_output=True, text=True
            )
            if result.returncode == 0 and "Python 3" in result.stdout:
                return cmd
        except FileNotFoundError:
            continue
    return None


def create_venv(venv_path):
    """Create a Python virtual environment."""
    print(f"\n  Creating virtual environment at {dim(str(venv_path))}...")
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_path)],
        check=True
    )


def get_venv_python(venv_path):
    """Get the Python executable inside a venv."""
    if is_windows():
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def get_venv_pip(venv_path):
    """Get the pip executable inside a venv."""
    if is_windows():
        return venv_path / "Scripts" / "pip.exe"
    return venv_path / "bin" / "pip"


def install_dependencies(venv_path, project_dir):
    """Install Python dependencies into the venv."""
    pip = get_venv_pip(venv_path)
    req_file = project_dir / "requirements.txt"

    print(f"  Installing dependencies...")

    # Install MCP SDK
    subprocess.run(
        [str(pip), "install", "-q", "mcp[cli]"],
        check=True, capture_output=True
    )

    # Install from requirements.txt if it exists
    if req_file.exists():
        subprocess.run(
            [str(pip), "install", "-q", "-r", str(req_file)],
            check=True, capture_output=True
        )

# ─── Connection Verification ─────────────────────────────────────────────────

def verify_resolve_connection(python_path, api_path, lib_path):
    """Try to import DaVinciResolveScript and connect."""
    if not api_path:
        return False, "Resolve API path not found"

    env = {**os.environ, **build_server_env(python_path, api_path, lib_path)}
    modules_path = env["PYTHONPATH"]
    test_script = textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, {modules_path!r})
        try:
            import DaVinciResolveScript as dvr
            resolve = dvr.scriptapp('Resolve')
            if resolve:
                name = resolve.GetProductName()
                ver = resolve.GetVersionString()
                print(f"CONNECTED: {{name}} {{ver}}")
            else:
                print("IMPORTED_OK: Module loads but Resolve not running or not responding")
        except ImportError as e:
            print(f"IMPORT_ERROR: {{e}}")
        except Exception as e:
            print(f"ERROR: {{e}}")
    """)

    try:
        result = subprocess.run(
            [str(python_path), "-c", test_script],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        output = result.stdout.strip() or result.stderr.strip()
        if output.startswith("CONNECTED:"):
            return True, output.replace("CONNECTED: ", "")
        elif output.startswith("IMPORTED_OK:"):
            return True, "API module loaded (Resolve not running)"
        else:
            if output:
                return False, output
            return False, f"Process exited with code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Connection timed out"
    except Exception as e:
        return False, str(e)

# ─── Interactive UI ───────────────────────────────────────────────────────────

def print_banner():
    title = f"DaVinci Resolve MCP Server — Installer v{VERSION}"
    subtitle = "32 compound · 329 full · 3 platforms"
    print()
    print(bold("  ╔══════════════════════════════════════════════════════╗"))
    print(bold(f"  ║{title:^54}║"))
    print(bold("  ╠══════════════════════════════════════════════════════╣"))
    print(bold(f"  ║{subtitle:^54}║"))
    print(bold("  ╚══════════════════════════════════════════════════════╝"))
    print()


def print_step(num, total, text):
    print(f"\n  {cyan(f'[{num}/{total}]')} {bold(text)}")
    print(f"  {'─' * 50}")


def print_update_status(project_dir, *, force=False):
    """Best-effort installer update notice."""
    result = check_for_updates(VERSION, project_dir, timeout=2.0, force=force)
    status = result.get("status")
    if status == "update_available":
        version_note = dim(
            f"v{result.get('current_version')} -> v{result.get('latest_version')}"
        )
        release_note = dim(f"Latest release: {result.get('release_url')}")
        print(
            f"  MCP Update: {yellow('Available')} "
            f"{version_note}"
        )
        print(f"  {release_note}")
    elif status == "up_to_date":
        print(f"  MCP Update: {green('Up to date')} {dim(f'v{VERSION}')}")
    elif status == "current_ahead":
        print(f"  MCP Update: {green('Local build ahead of latest release')} {dim(f'v{VERSION}')}")
    elif status == "disabled":
        print(f"  MCP Update: {dim('Check disabled')}")
    elif status == "error":
        print(f"  MCP Update: {yellow('Could not check')} {dim(str(result.get('error', '')))}")
    return result


def _run_git(project_dir, args, timeout=45):
    try:
        return subprocess.run(
            ["git", "-C", str(project_dir), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired as exc:
        return exc


def _git_failure_message(result, fallback):
    if result is None:
        return "git is not available on PATH"
    if isinstance(result, subprocess.TimeoutExpired):
        return "git command timed out"
    output = (result.stderr or result.stdout or "").strip()
    return output or fallback


def _record_update_history(project_dir, entry):
    """Append `entry` to `<project_dir>/logs/update_history.json` (best-effort)."""
    import json as _json
    log_dir = os.path.join(project_dir, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        return
    path = os.path.join(log_dir, "update_history.json")
    history = {"entries": []}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                loaded = _json.load(fh)
            if isinstance(loaded, dict) and isinstance(loaded.get("entries"), list):
                history = loaded
        except (OSError, ValueError):
            pass
    history.setdefault("entries", []).append(entry)
    # Trim to most recent 200 entries — keep history bounded.
    if len(history["entries"]) > 200:
        history["entries"] = history["entries"][-200:]
    history["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            _json.dump(history, fh, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _read_current_version(project_dir):
    """Best-effort read of VERSION constant from src/server.py."""
    server_path = os.path.join(project_dir, "src", "server.py")
    try:
        with open(server_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VERSION = "):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _record_attempt(project_dir, *, kind, success, reason=None, message=None,
                    from_version=None, to_version=None, from_sha=None, to_sha=None,
                    initiator=None, extra=None):
    """Append a structured row to update_history.json. `extra` is merged in flat."""
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": kind,  # "update" | "rollback" | "dry_run"
        "success": bool(success),
        "reason": reason,
        "message": message,
        "from_version": from_version,
        "to_version": to_version,
        "from_sha": from_sha,
        "to_sha": to_sha,
        "initiator": initiator,
    }
    if isinstance(extra, dict):
        entry.update(extra)
    _record_update_history(project_dir, entry)


def apply_safe_self_update(project_dir, dry_run=False, *, initiator="cli",
                           strategy="refuse_on_dirty"):
    """Apply a guarded git fast-forward update.

    `strategy` controls behavior when the working tree is dirty:
    - `"refuse_on_dirty"` (default) — return reason="local_changes" without
      touching anything.
    - `"stash_if_needed"` — `git stash push`, apply the update, `git stash pop`.
      If pop conflicts, leave the stash in place and return reason="stash_pop_conflict"
      with the stash ref so the user can resolve.

    Every attempt — success or failure — is recorded in
    `<project_dir>/logs/update_history.json` so the dashboard can show what
    happened and rollback can find the prior SHA.
    """
    inside = _run_git(project_dir, ["rev-parse", "--is-inside-work-tree"])
    if inside is None or isinstance(inside, subprocess.TimeoutExpired) or inside.returncode != 0:
        msg = _git_failure_message(inside, "not a git checkout")
        _record_attempt(project_dir, kind="update", success=False, reason="not_git", message=msg, initiator=initiator)
        return {"success": False, "reason": "not_git", "message": msg}

    status = _run_git(project_dir, ["status", "--porcelain"])
    if status is None or isinstance(status, subprocess.TimeoutExpired) or status.returncode != 0:
        msg = _git_failure_message(status, "could not inspect git status")
        _record_attempt(project_dir, kind="update", success=False, reason="status_failed", message=msg, initiator=initiator)
        return {"success": False, "reason": "status_failed", "message": msg}

    stash_ref = None
    if status.stdout.strip():
        if strategy != "stash_if_needed":
            msg = "local changes are present; continuing with the current build"
            _record_attempt(project_dir, kind="update", success=False, reason="local_changes", message=msg, initiator=initiator)
            return {"success": False, "reason": "local_changes", "message": msg}
        # Auto-stash path: push the working tree onto the stash, remember the
        # ref so we can pop (or surface) it after the update.
        stash_msg = f"mcp-update-autostash-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
        stash = _run_git(project_dir, ["stash", "push", "-u", "-m", stash_msg], timeout=30)
        if stash is None or stash.returncode != 0 or "No local changes to save" in (stash.stdout or ""):
            # If we got here `status` was dirty, so a stash failure means trouble.
            msg = _git_failure_message(stash, "git stash push failed")
            _record_attempt(project_dir, kind="update", success=False, reason="stash_failed", message=msg, initiator=initiator)
            return {"success": False, "reason": "stash_failed", "message": msg}
        stash_ref = stash_msg

    upstream = _run_git(project_dir, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if upstream is None or isinstance(upstream, subprocess.TimeoutExpired) or upstream.returncode != 0:
        msg = _git_failure_message(upstream, "current branch has no configured upstream")
        _record_attempt(project_dir, kind="update", success=False, reason="no_upstream", message=msg, initiator=initiator)
        return {"success": False, "reason": "no_upstream", "message": msg}

    # Capture pre-update SHA + version so rollback knows where to revert to.
    head_before = _run_git(project_dir, ["rev-parse", "HEAD"])
    from_sha = head_before.stdout.strip() if head_before and head_before.returncode == 0 else None
    from_version = _read_current_version(project_dir)

    if dry_run:
        msg = f"would fast-forward from {upstream.stdout.strip()}"
        _record_attempt(project_dir, kind="dry_run", success=True, message=msg,
                        from_version=from_version, from_sha=from_sha, initiator=initiator)
        return {"success": True, "changed": False, "dry_run": True, "message": msg}

    fetch = _run_git(project_dir, ["fetch", "--tags", "--prune"], timeout=90)
    if fetch is None or isinstance(fetch, subprocess.TimeoutExpired) or fetch.returncode != 0:
        msg = _git_failure_message(fetch, "git fetch failed")
        _record_attempt(project_dir, kind="update", success=False, reason="fetch_failed", message=msg,
                        from_version=from_version, from_sha=from_sha, initiator=initiator)
        return {"success": False, "reason": "fetch_failed", "message": msg}

    pull = _run_git(project_dir, ["pull", "--ff-only"], timeout=120)
    if pull is None or isinstance(pull, subprocess.TimeoutExpired) or pull.returncode != 0:
        msg = _git_failure_message(pull, "git pull --ff-only failed")
        _record_attempt(project_dir, kind="update", success=False, reason="pull_failed", message=msg,
                        from_version=from_version, from_sha=from_sha, initiator=initiator)
        return {"success": False, "reason": "pull_failed", "message": msg}

    head_after = _run_git(project_dir, ["rev-parse", "HEAD"])
    to_sha = head_after.stdout.strip() if head_after and head_after.returncode == 0 else None
    to_version = _read_current_version(project_dir)

    output = "\n".join(part.strip() for part in (pull.stdout, pull.stderr) if part and part.strip())
    changed = "Already up to date." not in output

    # Integrity verification: confirm our local HEAD matches what GitHub said
    # was the target SHA. Mismatch could mean: (a) user pushed to a fork mid-
    # update, (b) the release we resolved was different from the branch tip
    # (force-pushed), (c) corruption. We don't roll back automatically — the
    # user may have intentional reasons — but we log it loudly.
    integrity = {"verified": None, "expected_sha": None, "actual_sha": to_sha}
    try:
        from src.utils.update_check import check_for_updates as _cfu  # type: ignore
        info = _cfu(from_version or "0.0.0", project_dir, force=False)
        expected = info.get("release_target_sha")
        if expected:
            integrity["expected_sha"] = expected
            # Compare prefixes (release SHA may be a tag name or short SHA).
            ok = bool(to_sha) and (
                expected == to_sha
                or (len(expected) >= 7 and to_sha.startswith(expected[:7]))
                or (len(to_sha) >= 7 and expected.startswith(to_sha[:7]))
            )
            integrity["verified"] = ok
    except Exception as exc:
        integrity["error"] = f"{type(exc).__name__}: {exc}"

    # If we stashed changes earlier, try to reapply them now.
    stash_pop_conflict = False
    if stash_ref:
        pop = _run_git(project_dir, ["stash", "pop"], timeout=60)
        if pop is None or pop.returncode != 0:
            stash_pop_conflict = True

    result = {
        "success": True, "changed": changed,
        "message": output or "update complete",
        "from_version": from_version, "to_version": to_version,
        "from_sha": from_sha, "to_sha": to_sha,
        "stash_ref": stash_ref,
        "stash_pop_conflict": stash_pop_conflict,
        "integrity": integrity,
    }
    if stash_pop_conflict:
        # Update applied successfully but the stash pop hit a conflict; the
        # user's changes are still in the stash. Don't fail the overall update,
        # but surface the conflict prominently.
        result["reason"] = "stash_pop_conflict"
        result["remediation"] = (
            f"Update applied, but your stashed changes ({stash_ref}) conflict with the new build. "
            "Resolve via `git stash list` + `git stash pop` after restarting; "
            "use `git stash drop` if you want to discard them."
        )

    _record_attempt(project_dir, kind="update", success=True,
                    message=output or "update complete",
                    from_version=from_version, to_version=to_version,
                    from_sha=from_sha, to_sha=to_sha, initiator=initiator,
                    extra={"stash_ref": stash_ref,
                           "stash_pop_conflict": stash_pop_conflict,
                           "integrity": integrity})

    return result


def rollback_to_previous_build(project_dir, *, initiator="cli"):
    """git reset --hard to the from_sha of the most recent successful update.

    Refuses if local changes exist (same guard as apply_safe_self_update) so we
    never silently lose user work. Records a rollback row in update_history.
    """
    import json as _json
    history_path = os.path.join(project_dir, "logs", "update_history.json")
    if not os.path.isfile(history_path):
        return {"success": False, "reason": "no_history", "message": "no update_history.json found"}
    try:
        with open(history_path, "r", encoding="utf-8") as fh:
            history = _json.load(fh)
    except (OSError, _json.JSONDecodeError) as exc:
        return {"success": False, "reason": "history_read_failed", "message": str(exc)}

    # Newest first; find the latest successful "update" entry with a from_sha.
    candidates = [e for e in reversed(history.get("entries") or [])
                  if e.get("kind") == "update" and e.get("success") and e.get("from_sha")]
    if not candidates:
        return {"success": False, "reason": "no_target", "message": "no prior successful update to roll back to"}
    target = candidates[0]
    from_sha = target["from_sha"]

    status = _run_git(project_dir, ["status", "--porcelain"])
    if status is None or status.returncode != 0:
        return {"success": False, "reason": "status_failed", "message": "could not inspect git status"}
    if status.stdout.strip():
        return {"success": False, "reason": "local_changes",
                "message": "local changes are present; commit or stash before rolling back"}

    head_before = _run_git(project_dir, ["rev-parse", "HEAD"])
    pre_rollback_sha = head_before.stdout.strip() if head_before and head_before.returncode == 0 else None
    pre_rollback_version = _read_current_version(project_dir)

    reset = _run_git(project_dir, ["reset", "--hard", from_sha], timeout=60)
    if reset is None or reset.returncode != 0:
        msg = _git_failure_message(reset, f"git reset --hard {from_sha} failed")
        _record_attempt(project_dir, kind="rollback", success=False, reason="reset_failed", message=msg,
                        from_version=pre_rollback_version, from_sha=pre_rollback_sha,
                        to_sha=from_sha, initiator=initiator)
        return {"success": False, "reason": "reset_failed", "message": msg}

    to_version = _read_current_version(project_dir)
    _record_attempt(project_dir, kind="rollback", success=True,
                    message=f"rolled back to {from_sha[:10]}",
                    from_version=pre_rollback_version, to_version=to_version,
                    from_sha=pre_rollback_sha, to_sha=from_sha, initiator=initiator)
    return {"success": True, "changed": pre_rollback_sha != from_sha,
            "message": f"rolled back to {from_sha[:10]}",
            "from_version": pre_rollback_version, "to_version": to_version,
            "from_sha": pre_rollback_sha, "to_sha": from_sha}


def preview_update(project_dir):
    """Fetch the target release metadata + scan for breaking-change markers.

    Returns a dict the UI can render before the user confirms the update:
      {success, latest_version, release_notes, breaking_changes, prerelease,
       channel, current_version, target_sha}
    """
    try:
        from src.utils.update_check import check_for_updates  # type: ignore
    except Exception as exc:
        return {"success": False, "error": f"update_check unavailable: {exc}"}
    current = _read_current_version(project_dir) or "0.0.0"
    try:
        result = check_for_updates(current, project_dir, force=True)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "current_version": current,
        "latest_version": result.get("latest_version"),
        "release_notes": result.get("release_notes") or "",
        "breaking_changes": result.get("release_notes_breaking") or [],
        "prerelease": bool(result.get("prerelease")),
        "channel": result.get("channel"),
        "target_sha": result.get("release_target_sha"),
        "release_url": result.get("release_url"),
        "status": result.get("status"),
    }


def read_update_history(project_dir, limit=20):
    """Most-recent-first list of recorded update attempts. For the dashboard."""
    import json as _json
    path = os.path.join(project_dir, "logs", "update_history.json")
    if not os.path.isfile(path):
        return {"success": True, "entries": []}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            history = _json.load(fh)
    except (OSError, _json.JSONDecodeError) as exc:
        return {"success": False, "error": str(exc), "entries": []}
    entries = (history.get("entries") or [])[-int(limit):]
    entries.reverse()
    return {"success": True, "entries": entries}


def _restart_installer():
    print(f"  {green('Restarting installer with the updated build...')}")
    os.execv(sys.executable, [sys.executable, *sys.argv])


def _print_update_apply_result(result, *, restart_on_change=True):
    if result.get("success"):
        if result.get("dry_run"):
            print(f"  MCP Update: {yellow('Dry run')} {dim(result.get('message', ''))}")
            return
        print(f"  MCP Update: {green('Update command completed')}")
        message = str(result.get("message") or "").strip()
        if message:
            for line in message.splitlines()[:6]:
                print(f"  {dim(line)}")
        if result.get("changed") and restart_on_change:
            _restart_installer()
        return

    print(f"  MCP Update: {yellow('Not applied')} {dim(result.get('message', ''))}")


def maybe_prompt_for_update(project_dir, result, *, interactive, force_update=False, dry_run=False):
    """Prompt or auto-apply updates only in this human-facing installer."""
    if not result or result.get("status") != "update_available":
        return

    decision = update_prompt_decision(result)
    if force_update or decision.get("action") == "auto":
        print(f"  MCP Update: {yellow('Applying safe fast-forward update...')}")
        _print_update_apply_result(apply_safe_self_update(project_dir, dry_run=dry_run))
        return

    if decision.get("action") == "notify":
        print(f"  {dim('Update policy is notify-only; continuing with the current build.')}")
        return
    if decision.get("reason") == "ignored":
        print(f"  {dim('This release was ignored; continuing with the current build.')}")
        return
    if decision.get("reason") == "snoozed":
        snooze_note = f"Update reminder snoozed until {decision.get('snooze_until_iso')}."
        print(f"  {dim(snooze_note)}")
        return
    if not interactive:
        return

    latest = result.get("latest_version") or result.get("latest_tag") or "latest"
    print()
    print(f"  {yellow('A newer DaVinci Resolve MCP is available.')} {dim(f'v{VERSION} -> v{latest}')}")
    print(f"  {dim('Safe auto-update only runs for clean git checkouts with a configured upstream.')}")
    print(f"    {cyan('1')}. Update now")
    print(f"    {cyan('2')}. Continue current build")
    print(f"    {cyan('3')}. Remind me tomorrow")
    print(f"    {cyan('4')}. Ignore this version")
    print(f"    {cyan('5')}. Auto-update this checkout when safe")
    print(f"    {cyan('6')}. Never check automatically")
    try:
        choice = input(f"  Select {dim('[2]')} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if choice in ("1", "u", "update", "update now"):
        _print_update_apply_result(apply_safe_self_update(project_dir, dry_run=dry_run))
    elif choice in ("3", "r", "remind", "later", "snooze"):
        snooze_update_prompt(project_dir)
        print(f"  MCP Update: {dim('Reminder snoozed for 24 hours.')}")
    elif choice in ("4", "i", "ignore"):
        ignore_update_version(project_dir, result)
        print(f"  MCP Update: {dim(f'Ignored v{latest}. Newer releases will still prompt.')}")
    elif choice in ("5", "a", "auto", "auto-update", "autoupdate"):
        set_update_mode(project_dir, "auto")
        print(f"  MCP Update: {green('Safe auto-update enabled for this checkout.')}")
        _print_update_apply_result(apply_safe_self_update(project_dir, dry_run=dry_run))
    elif choice in ("6", "n", "never", "disable", "disabled"):
        set_update_mode(project_dir, "never")
        print(f"  MCP Update: {dim('Automatic update checks disabled for this checkout.')}")


def prompt_yes_no(question, default=True):
    """Prompt for yes/no with a default."""
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"  {question} {dim(suffix)} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def prompt_clients():
    """Interactive client selection menu."""
    print(f"\n  Which MCP client(s) do you want to configure?\n")

    for i, client in enumerate(MCP_CLIENTS, 1):
        path = client["get_path"]()
        available = path is not None
        status = ""
        if not available:
            status = dim(f" (not available on {platform_name()})")
        elif path and path.exists():
            status = green(" (config exists)")

        num = f"{i:>2}"
        print(f"    {cyan(num)}. {client['name']:<28} {dim(client['notes'])}{status}")

    all_num = str(len(MCP_CLIENTS) + 1).rjust(2)
    manual_num = str(len(MCP_CLIENTS) + 2).rjust(2)
    print(f"\n    {cyan(all_num)}. {bold('All of the above')}")
    print(f"    {cyan(manual_num)}. {bold('Manual setup')} {dim('(print config, I will set it up myself)')}")
    print(f"    {cyan(' 0')}. {dim('Skip client configuration')}")

    print()
    try:
        choice = input(f"  Select (comma-separated, e.g. 1,3,5): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return []

    if not choice or choice == "0":
        return []

    selections = []
    for part in choice.replace(" ", "").split(","):
        try:
            idx = int(part)
            if idx == len(MCP_CLIENTS) + 1:  # "All"
                return CLIENT_IDS + ["manual"]
            elif idx == len(MCP_CLIENTS) + 2:  # "Manual"
                selections.append("manual")
            elif 1 <= idx <= len(MCP_CLIENTS):
                selections.append(MCP_CLIENTS[idx - 1]["id"])
        except ValueError:
            # Try matching by name/id
            part_lower = part.lower()
            for client in MCP_CLIENTS:
                if part_lower in client["id"] or part_lower in client["name"].lower():
                    selections.append(client["id"])
                    break

    return list(dict.fromkeys(selections))  # deduplicate, preserve order

# ─── Main Install Flow ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="DaVinci Resolve MCP Server — Universal Installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python install.py                            Interactive mode
              python install.py --clients all              Configure all clients
              python install.py --clients cursor,claude-desktop
              python install.py --clients manual           Just print the config
              python install.py --no-venv --clients cursor Skip venv, configure Cursor
              python install.py --dry-run --clients all    Preview without writing
              python install.py --update-policy auto       Enable guarded auto-updates
              python install.py --update-policy never      Disable update checks
        """)
    )
    parser.add_argument(
        "--clients", type=str, default=None,
        help="Comma-separated client IDs, or 'all' / 'manual' (skip interactive prompt)"
    )
    parser.add_argument(
        "--no-venv", action="store_true",
        help="Skip virtual environment creation (use system Python)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview config changes without writing files"
    )
    parser.add_argument(
        "--python", type=str, default=None,
        help="Path to Python executable to use in MCP configs"
    )
    parser.add_argument(
        "--server", type=str, default=None,
        help="Path to the MCP server script"
    )
    parser.add_argument(
        "--update-policy",
        choices=["prompt", "auto", "notify", "never"],
        default=None,
        help="Set local update policy: prompt, auto, notify, or never"
    )
    parser.add_argument(
        "--update-now", action="store_true",
        help="Apply a safe git fast-forward update if a newer release is available"
    )
    parser.add_argument(
        "--clear-update-preferences", action="store_true",
        help="Clear ignored-version and snooze update preferences"
    )

    args = parser.parse_args()
    interactive = args.clients is None

    # ── Banner ──
    if interactive:
        print_banner()

    project_dir = Path(__file__).resolve().parent
    total_steps = 5

    if args.clear_update_preferences:
        clear_update_prompt_preferences(project_dir)
        print(f"  MCP Update: {green('Cleared ignored-version and snooze preferences')}")
    if args.update_policy:
        set_update_mode(project_dir, args.update_policy)
        print(f"  MCP Update: {green('Policy set')} {dim(args.update_policy)}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 1: Platform & Resolve Detection
    # ══════════════════════════════════════════════════════════════════════

    if interactive:
        print_step(1, total_steps, "Detecting Platform & DaVinci Resolve")

    print(f"  Platform:  {bold(platform_name())} ({platform.machine()})")
    update_result = print_update_status(project_dir, force=args.update_now)
    maybe_prompt_for_update(
        project_dir,
        update_result,
        interactive=interactive,
        force_update=args.update_now,
        dry_run=args.dry_run,
    )

    api_path, lib_path = find_resolve_paths()

    if api_path:
        print(f"  API Path:  {green(api_path)}")
    else:
        print(f"  API Path:  {red('Not found')}")
        if is_linux():
            print(f"  {dim('Tip: DaVinci Resolve typically installs to /opt/resolve/')}")
            print(f"  {dim('     Set RESOLVE_SCRIPT_API environment variable if installed elsewhere')}")

        # Check environment variable fallback
        env_api = os.environ.get("RESOLVE_SCRIPT_API")
        if env_api and os.path.isdir(env_api):
            api_path = env_api
            print(f"  {green('Found via $RESOLVE_SCRIPT_API:')} {api_path}")

    if lib_path:
        print(f"  Library:   {green(lib_path)}")
    else:
        print(f"  Library:   {yellow('Not found')} {dim('(optional — API path is sufficient)')}")

    resolve_running = check_resolve_running()
    if resolve_running:
        print(f"  Resolve:   {green('Running')}")
    else:
        print(f"  Resolve:   {yellow('Not running')} {dim('(start Resolve to verify connection)')}")

    if not api_path:
        print(f"\n  {yellow('Warning:')} Could not auto-detect DaVinci Resolve installation.")
        print(f"  The installer will continue, but you may need to set RESOLVE_SCRIPT_API manually.")
        if interactive and not prompt_yes_no("Continue anyway?"):
            print(f"\n  {dim('Aborted.')}")
            sys.exit(1)

    # ══════════════════════════════════════════════════════════════════════
    # STEP 2: Python Virtual Environment
    # ══════════════════════════════════════════════════════════════════════

    venv_path = project_dir / "venv"
    venv_python = get_venv_python(venv_path)
    skip_venv = args.no_venv

    if interactive:
        print_step(2, total_steps, "Python Environment")

    if skip_venv:
        print(f"  Skipping venv (--no-venv)")
        python_path = Path(args.python) if args.python else Path(sys.executable)
        require_supported_python(python_path, "Selected Python")
        print(f"  Using:     {python_path}")
    elif venv_path.exists() and venv_python.exists():
        print(f"  Venv:      {green('Already exists')} at {dim(str(venv_path))}")
        python_path = venv_python
        require_supported_python(python_path, "Existing venv")

        # Check if deps are installed
        try:
            result = subprocess.run(
                [str(python_path), "-c", "import mcp; print('ok')"],
                capture_output=True, text=True
            )
            if result.stdout.strip() == "ok":
                print(f"  MCP SDK:   {green('Installed')}")
            else:
                print(f"  MCP SDK:   {yellow('Missing')} — installing...")
                install_dependencies(venv_path, project_dir)
                print(f"  MCP SDK:   {green('Installed')}")
        except Exception:
            install_dependencies(venv_path, project_dir)
            print(f"  MCP SDK:   {green('Installed')}")
    else:
        if interactive:
            create_venv_ok = prompt_yes_no("Create virtual environment?")
        else:
            create_venv_ok = True

        if create_venv_ok:
            require_current_python("Virtual environment")
            create_venv(venv_path)
            python_path = venv_python
            require_supported_python(python_path, "Created venv")
            install_dependencies(venv_path, project_dir)
            print(f"  Venv:      {green('Created')}")
            print(f"  MCP SDK:   {green('Installed')}")
        else:
            python_path = Path(args.python) if args.python else Path(sys.executable)
            require_supported_python(python_path, "Selected Python")
            print(f"  Using system Python: {python_path}")

    # Override python path if explicitly provided
    if args.python:
        python_path = Path(args.python)
        require_supported_python(python_path, "Selected --python")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 3: Locate Server Script
    # ══════════════════════════════════════════════════════════════════════

    if interactive:
        print_step(3, total_steps, "Server Script")

    if args.server:
        server_path = Path(args.server).resolve()
    else:
        # Try to find the compound server first.
        candidates = [
            project_dir / "src" / "server.py",
            project_dir / "src" / "resolve_mcp_server.py",
            project_dir / "src" / "main.py",
            project_dir / "resolve_mcp_server.py",
        ]
        server_path = None
        for c in candidates:
            if c.exists():
                server_path = c
                break
        if server_path is None:
            server_path = candidates[0]  # default even if not found yet

    if server_path.exists():
        print(f"  Server:    {green(str(server_path))}")
    else:
        print(f"  Server:    {yellow(str(server_path))} {dim('(file not found — check path)')}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 4: Configure MCP Clients
    # ══════════════════════════════════════════════════════════════════════

    if interactive:
        print_step(4, total_steps, "MCP Client Configuration")

    # Determine which clients to configure
    if args.clients:
        if args.clients.lower() == "all":
            selected_ids = CLIENT_IDS
        elif args.clients.lower() == "manual":
            selected_ids = ["manual"]
        else:
            selected_ids = [s.strip() for s in args.clients.split(",")]
    elif interactive:
        selected_ids = prompt_clients()
    else:
        selected_ids = []

    # Show manual config if requested
    show_manual = "manual" in selected_ids
    client_ids = [c for c in selected_ids if c != "manual"]

    configured = []
    skipped = []

    for client_id in client_ids:
        client = next((c for c in MCP_CLIENTS if c["id"] == client_id), None)
        if not client:
            print(f"  {yellow('Unknown client:')} {client_id}")
            skipped.append(client_id)
            continue

        success, message = write_client_config(
            client, python_path, server_path, api_path, lib_path, dry_run=args.dry_run
        )

        if success:
            if args.dry_run:
                print(f"\n  {cyan(client['name'])} {dim('(dry run)')}")
                for line in message.split("\n"):
                    print(f"    {line}")
                configured.append(client["name"])
            else:
                print(f"  {green('✓')} {client['name']:<28} → {dim(message)}")
                configured.append(client["name"])
        else:
            print(f"  {yellow('⊘')} {client['name']:<28}   {dim(message)}")
            skipped.append(client["name"])

    # Show manual config
    if show_manual:
        standard, vscode_fmt, zed_fmt, opencode_fmt = generate_manual_config(
            python_path, server_path, api_path, lib_path
        )
        env_preview = build_server_env(python_path, api_path, lib_path)
        print(f"\n  {bold('Manual Configuration')}")
        print(f"  {'─' * 50}")
        print(f"\n  {cyan('Standard format')} (Claude Desktop, Cursor, Windsurf, Cline, Roo Code, Continue):")
        print()
        for line in standard.split("\n"):
            print(f"    {line}")
        print(f"\n  {cyan('VS Code format')} (GitHub Copilot agent mode — save as .vscode/mcp.json):")
        print()
        for line in vscode_fmt.split("\n"):
            print(f"    {line}")
        print(f"\n  {cyan('Zed format')} (add to ~/.config/zed/settings.json):")
        print()
        for line in zed_fmt.split("\n"):
            print(f"    {line}")
        print(f"\n  {cyan('OpenCode format')} (add to ~/.config/opencode/opencode.json or a project opencode.json):")
        print()
        for line in opencode_fmt.split("\n"):
            print(f"    {line}")
        print(f"\n  {cyan('JetBrains IDEs')} (IntelliJ, WebStorm, PyCharm, etc.):")
        print(f"    Settings → Tools → AI Assistant → Model Context Protocol (MCP)")
        print(f"    Add server with command: {python_path} {server_path}")
        for key, value in env_preview.items():
            print(f"    Set env: {key}={value}")
        print()

    if not selected_ids:
        print(f"  {dim('No clients selected — skipping configuration')}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 5: Verify Connection
    # ══════════════════════════════════════════════════════════════════════

    if interactive:
        print_step(5, total_steps, "Verification")

    if api_path:
        success, message = verify_resolve_connection(python_path, api_path, lib_path)
        try:
            py_abi_risk = is_abi_risk_python_version(_version_for_python(python_path))
        except Exception:
            py_abi_risk = False
        if success:
            if "not running" in message.lower():
                print(f"  API:       {green('Module loads OK')}")
                # If Resolve IS running but the bridge still reported no connection
                # on a 3.13+ interpreter, that is the ABI-mismatch signature.
                if resolve_running and py_abi_risk:
                    print(
                        f"  Resolve:   {yellow('Running, but the scripting bridge returned no connection')}"
                    )
                    print(
                        f"             This can happen on Python 3.13+ with older Resolve builds. "
                        f"If MCP tools fail, recreate the venv with Python 3.10-3.12."
                    )
                else:
                    print(f"  Resolve:   {yellow('Not running')} — start Resolve to use MCP tools")
            else:
                print(f"  Connected: {green(message)}")
        else:
            print(f"  Verify:    {yellow(message)}")
            if py_abi_risk:
                print(
                    f"             On Python 3.13+ this may be an ABI mismatch with Resolve's "
                    f"scripting library — try Python 3.10-3.12 if it persists."
                )
    else:
        print(f"  {yellow('Skipped')} — Resolve API path not detected")

    # ══════════════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════════════

    print(f"\n  {'═' * 50}")
    if configured or show_manual:
        print(f"  {green(bold('Setup complete!'))}")
        if configured:
            print(f"  Configured: {', '.join(configured)}")
        print()
        print(f"  {bold('Next steps:')}")
        if not resolve_running:
            print(f"    1. Start DaVinci Resolve")
            print(f"    2. Open your MCP client")
            print(f"    3. Start using natural language to control Resolve!")
        else:
            print(f"    1. Open your MCP client")
            print(f"    2. Start using natural language to control Resolve!")
        print()
        print(f"  {dim(f'Server: {server_path}')}")
        print(f"  {dim(f'Python: {python_path}')}")
        if api_path:
            print(f"  {dim(f'API:    {api_path}')}")
    elif not selected_ids:
        print(f"  {green(bold('Environment ready!'))}")
        print(f"  Run {cyan('python install.py --clients all')} to configure MCP clients later.")
    else:
        print(f"  {yellow('No clients configured.')}")
        print(f"  Run {cyan('python install.py')} again to retry.")

    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {dim('Interrupted.')}\n")
        sys.exit(1)
