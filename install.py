#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server — Universal Installer

Supports: macOS, Windows, Linux
Configures: Claude Desktop, Claude Code, Cursor, VS Code (Copilot),
            Windsurf, Cline, Roo Code, Zed, Continue, and manual setup.

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
from pathlib import Path

# ─── Version ──────────────────────────────────────────────────────────────────

VERSION = "2.2.0"

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
    except Exception:
        pass

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

# ─── Config File Operations ──────────────────────────────────────────────────

def read_json(path):
    """Read a JSON file, return empty dict if missing or invalid."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


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
    is_zed = client["id"] == "zed"

    # Build the server entry
    if is_zed:
        server_entry = build_zed_entry(python_path, server_path, api_path, lib_path)
    else:
        server_entry = build_server_entry(python_path, server_path, api_path, lib_path)

    if dry_run:
        preview = {config_key: {"davinci-resolve": server_entry}}
        return True, f"Would write to {config_path}:\n{json.dumps(preview, indent=2)}"

    # Read existing config and merge
    existing = read_json(config_path)

    if config_key not in existing:
        existing[config_key] = {}

    existing[config_key]["davinci-resolve"] = server_entry

    write_json(config_path, existing)
    return True, str(config_path)


def generate_manual_config(python_path, server_path, api_path, lib_path):
    """Generate config snippets for manual setup."""
    entry = build_server_entry(python_path, server_path, api_path, lib_path)
    zed_entry = build_zed_entry(python_path, server_path, api_path, lib_path)

    standard = json.dumps({"mcpServers": {"davinci-resolve": entry}}, indent=2)
    vscode_fmt = json.dumps({"servers": {"davinci-resolve": entry}}, indent=2)
    zed_fmt = json.dumps({"context_servers": {"davinci-resolve": zed_entry}}, indent=2)

    return standard, vscode_fmt, zed_fmt

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
    subtitle = "27 compound · 342 full · 3 platforms"
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

    args = parser.parse_args()
    interactive = args.clients is None

    # ── Banner ──
    if interactive:
        print_banner()

    project_dir = Path(__file__).resolve().parent
    total_steps = 5

    # ══════════════════════════════════════════════════════════════════════
    # STEP 1: Platform & Resolve Detection
    # ══════════════════════════════════════════════════════════════════════

    if interactive:
        print_step(1, total_steps, "Detecting Platform & DaVinci Resolve")

    print(f"  Platform:  {bold(platform_name())} ({platform.machine()})")

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
        print(f"  Using:     {python_path}")
    elif venv_path.exists() and venv_python.exists():
        print(f"  Venv:      {green('Already exists')} at {dim(str(venv_path))}")
        python_path = venv_python

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
            create_venv(venv_path)
            python_path = venv_python
            install_dependencies(venv_path, project_dir)
            print(f"  Venv:      {green('Created')}")
            print(f"  MCP SDK:   {green('Installed')}")
        else:
            python_path = Path(args.python) if args.python else Path(sys.executable)
            print(f"  Using system Python: {python_path}")

    # Override python path if explicitly provided
    if args.python:
        python_path = Path(args.python)

    # ══════════════════════════════════════════════════════════════════════
    # STEP 3: Locate Server Script
    # ══════════════════════════════════════════════════════════════════════

    if interactive:
        print_step(3, total_steps, "Server Script")

    if args.server:
        server_path = Path(args.server).resolve()
    else:
        # Try to find the server script (prefer compound 27-tool server)
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
        standard, vscode_fmt, zed_fmt = generate_manual_config(
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
        if success:
            if "not running" in message.lower():
                print(f"  API:       {green('Module loads OK')}")
                print(f"  Resolve:   {yellow('Not running')} — start Resolve to use MCP tools")
            else:
                print(f"  Connected: {green(message)}")
        else:
            print(f"  Verify:    {yellow(message)}")
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
