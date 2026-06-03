#!/usr/bin/env python3
"""Click an arbitrary DaVinci Resolve menu path on macOS."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def applescript_list(values: list[str]) -> str:
    return "{" + ", ".join(json.dumps(value) for value in values) + "}"


def build_click_script(menu_path: list[str], delay: float) -> str:
    return f"""
tell application "DaVinci Resolve" to activate
delay {delay}
tell application "System Events"
  tell process "DaVinci Resolve"
    set frontmost to true
    set pathLabels to {applescript_list(menu_path)}
    set pathCount to count of pathLabels
    if pathCount < 2 then error "Menu path must include at least a menu and a menu item"

    set currentMenu to menu 1 of menu bar item (item 1 of pathLabels) of menu bar 1
    if pathCount > 2 then
      repeat with i from 2 to (pathCount - 1)
        set currentMenu to menu 1 of menu item (item i of pathLabels) of currentMenu
      end repeat
    end if
    set clickedLabel to item pathCount of pathLabels
    click menu item clickedLabel of currentMenu
    return clickedLabel
  end tell
end tell
"""


def build_list_menubar_script(delay: float) -> str:
    return f"""
tell application "DaVinci Resolve" to activate
delay {delay}
tell application "System Events"
  tell process "DaVinci Resolve"
    set frontmost to true
    return name of menu bar items of menu bar 1
  end tell
end tell
"""


def run_osascript(script: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def error_payload(proc: subprocess.CompletedProcess[str], menu_path: list[str]) -> dict[str, object]:
    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    note = None
    if "-1719" in stderr or "Hilfszugriff" in stderr or "assistive" in stderr.lower():
        note = (
            "Grant Accessibility permission in System Settings > Privacy & Security > "
            "Accessibility for the app/process running this helper or for osascript/Terminal."
        )
    return {
        "success": False,
        "error": stderr or stdout or f"osascript exited {proc.returncode}",
        "returncode": proc.returncode,
        "menu_path": menu_path,
        "accessibility_note": note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("menu_path", nargs="*", help='Menu path, e.g. Timeline "Output Blanking" 2.39')
    parser.add_argument("--dry-run", action="store_true", help="Print the planned click without executing")
    parser.add_argument("--list-menu-bar", action="store_true", help="List Resolve menu bar labels")
    parser.add_argument("--delay", type=float, default=0.4, help="Activation delay before reading menus")
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()

    if sys.platform != "darwin":
        print(json.dumps({"success": False, "error": "macOS only"}, indent=2), file=sys.stderr)
        return 2

    if args.list_menu_bar:
        proc = run_osascript(build_list_menubar_script(args.delay), args.timeout)
        if proc.returncode != 0:
            print(json.dumps(error_payload(proc, []), indent=2), file=sys.stderr)
            return proc.returncode
        print(json.dumps({
            "success": True,
            "menu_bar_items": [item.strip() for item in (proc.stdout or "").strip().split(",") if item.strip()],
        }, indent=2))
        return 0

    if len(args.menu_path) < 2:
        parser.error("Provide at least two path parts: menu and menu item")

    if args.dry_run:
        print(json.dumps({
            "success": True,
            "dry_run": True,
            "menu_path": args.menu_path,
        }, indent=2))
        return 0

    proc = run_osascript(build_click_script(args.menu_path, args.delay), args.timeout)
    if proc.returncode != 0:
        print(json.dumps(error_payload(proc, args.menu_path), indent=2), file=sys.stderr)
        return proc.returncode

    print(json.dumps({
        "success": True,
        "clicked_label": (proc.stdout or "").strip(),
        "menu_path": args.menu_path,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
