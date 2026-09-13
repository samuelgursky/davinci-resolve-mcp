"""Live Resolve smoke test for v2.5.0 script_plugin authoring.

Installs a media_rules script in Workspace → Scripts → Edit, plus a scaffold
in Utility (Lua and Python flavors), and reports that the install paths
exist on disk. Resolve does NOT need to be restarted — the menu refreshes
each time it's opened.

Cleans up regardless of pass/fail.
"""

import os
import subprocess
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

# Stand in for the MCP SDK only when it is genuinely absent, so this smoke test
# can reach src.server functions without spinning up the full MCP server.
from src.utils.mcp_import_stubs import install_mcp_stubs  # noqa: E402

install_mcp_stubs(stdio_note="stdio_server is not used by this live harness")

from src.utils.platform import get_resolve_paths  # noqa: E402

paths = get_resolve_paths()
os.environ["RESOLVE_SCRIPT_API"] = paths["api_path"]
os.environ["RESOLVE_SCRIPT_LIB"] = paths["lib_path"]
sys.path.insert(0, paths["modules_path"])

import DaVinciResolveScript as dvr_script  # noqa: E402
from src.server import script_plugin  # noqa: E402


SCRIPTS_TO_INSTALL = [
    # (name, kind, category, language, options)
    ("McpLiveRulesLua",     "media_rules", "Edit",    "lua", None),
    ("McpLiveRulesPy",      "media_rules", "Edit",    "py",  None),
    ("McpLiveScaffoldLua",  "scaffold",    "Utility", "lua", None),
    ("McpLiveScaffoldPy",   "scaffold",    "Utility", "py",  None),
]


def main():
    installed = []
    print(f"=== Installing {len(SCRIPTS_TO_INSTALL)} scripts ===")
    for name, kind, category, language, options in SCRIPTS_TO_INSTALL:
        opts = dict(options or {})
        opts["language"] = language
        gen = script_plugin('template', {
            'kind': kind, 'name': name, 'options': opts,
        })
        if 'error' in gen:
            print(f"  [GEN FAIL] {name}: {gen['error']}")
            continue
        r = script_plugin('install', {
            'name': name, 'source': gen['source'],
            'category': category, 'language': language, 'overwrite': True,
        })
        if 'error' in r:
            print(f"  [INSTALL FAIL] {name}: {r['error']}")
            continue
        installed.append((name, category, language, r['path']))
        size = os.path.getsize(r['path'])
        print(f"  [OK] {name:25s} → {category}/  ({language}, {size} bytes)")

    print()
    print("=== Verify scripts are visible to Resolve ===")
    print("Scripts live at:")
    for name, category, language, path in installed:
        print(f"  {path}")
    print()
    print("Resolve picks these up without a restart. To verify:")
    print("  1. Launch Resolve (or it can already be running)")
    print("  2. Open any project")
    print("  3. Check Workspace → Scripts → Edit       (should show "
          "McpLiveRulesLua, McpLiveRulesPy)")
    print("     and Workspace → Scripts → Utility    (should show "
          "McpLiveScaffoldLua, McpLiveScaffoldPy)")
    print()
    print("Optional: open Console (Workspace → Console → Lua tab) and click any")
    print("of the McpLive* scripts in the menu — it should run without errors")
    print("(media_rules runs against your current project in DRY-RUN mode by")
    print("default, scaffold just prints version info).")
    print()

    # Try to also confirm via Resolve API that the installation succeeded —
    # but only if Resolve is already running. Do NOT auto-launch.
    cand = dvr_script.scriptapp("Resolve")
    if cand is not None:
        try:
            ver = cand.GetVersion()
            if ver:
                print(f"=== Resolve is running ({cand.GetVersionString()}) ===")
                print("Files exist on disk; ready for you to inspect the menu.")
        except Exception:
            pass

    # Cleanup prompt
    print()
    print("Press ENTER once you've confirmed (or just want to clean up)...")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        print()

    print("=== Cleanup ===")
    for name, category, language, path in installed:
        r = script_plugin('remove', {
            'name': name, 'category': category, 'language': language,
        })
        if r.get('success'):
            print(f"  removed: {name}.{language}")
        else:
            print(f"  WARN remove failed: {name}.{language} — {r}")


if __name__ == "__main__":
    main()
