#!/usr/bin/env python3
"""Click DaVinci Resolve's native Timeline > Output Blanking menu on macOS."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


ALIASES = {
    "1.33": ["1.33", "1.33:1", "4:3"],
    "4:3": ["1.33", "1.33:1", "4:3"],
    "1.66": ["1.66", "1.66:1"],
    "1.77": ["1.77", "1.77:1", "1.78", "1.78:1", "16:9"],
    "16:9": ["1.77", "1.77:1", "1.78", "1.78:1", "16:9"],
    "1.85": ["1.85", "1.85:1"],
    "2.0": ["2.0", "2.00", "2.0:1", "2.00:1", "2:1"],
    "2.35": ["2.35", "2.35:1"],
    "2.39": ["2.39", "2.39:1"],
    "2.40": ["2.40", "2.4", "2.40:1", "2.4:1"],
    "none": ["None", "No Blanking", "Reset", "Off"],
    "off": ["None", "No Blanking", "Reset", "Off"],
    "reset": ["None", "No Blanking", "Reset", "Off"],
}


def candidate_labels(aspect: Any) -> list[str]:
    raw = str(aspect or "").strip()
    if not raw:
        return []
    key = raw.lower().replace(" ", "")
    if key in ALIASES:
        return ALIASES[key]
    if raw.endswith(":1"):
        return [raw[:-2], raw]
    return [raw, f"{raw}:1"]


def applescript_list(values: list[str]) -> str:
    return "{" + ", ".join(json.dumps(value) for value in values) + "}"


def build_script(candidates: list[str], delay: float) -> str:
    return f"""
tell application "DaVinci Resolve" to activate
delay {delay}
tell application "System Events"
  tell process "DaVinci Resolve"
    set frontmost to true
    set timelineMenuLabels to {applescript_list(["Timeline", "Zeitleiste"])}
    set outputMenuLabels to {applescript_list(["Output Blanking", "Ausgabe-Austastung"])}
    set targetLabels to {applescript_list(candidates)}
    set clickedLabel to ""
    set timelineMenuLabel to ""
    set outputMenuLabel to ""

    repeat with timelineCandidate in timelineMenuLabels
      try
        set timelineMenuLabel to timelineCandidate as text
        set timelineMenu to menu 1 of menu bar item timelineMenuLabel of menu bar 1
        exit repeat
      on error errMsg number errNum
        if errNum is -1719 then error errMsg number errNum
        set timelineMenuLabel to ""
      end try
    end repeat
    if timelineMenuLabel is "" then error "Timeline menu not found"

    repeat with outputCandidate in outputMenuLabels
      try
        set outputMenuLabel to outputCandidate as text
        set outputMenu to menu 1 of menu item outputMenuLabel of timelineMenu
        exit repeat
      on error errMsg number errNum
        if errNum is -1719 then error errMsg number errNum
        set outputMenuLabel to ""
      end try
    end repeat
    if outputMenuLabel is "" then error "Output Blanking submenu not found"

    repeat with targetCandidate in targetLabels
      try
        set clickedLabel to targetCandidate as text
        click menu item clickedLabel of outputMenu
        exit repeat
      on error errMsg number errNum
        if errNum is -1719 then error errMsg number errNum
        set clickedLabel to ""
      end try
    end repeat
    if clickedLabel is "" then
      set availableLabels to name of menu items of outputMenu
      error "Output Blanking preset not found. Available: " & (availableLabels as text)
    end if
    return clickedLabel
  end tell
end tell
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aspect", nargs="?", help="Preset such as 2.39, 2.35, 1.85, 4:3, 16:9, or off")
    parser.add_argument("--dry-run", action="store_true", help="Print candidates without clicking")
    parser.add_argument("--list-presets", action="store_true", help="Print supported aliases")
    parser.add_argument("--delay", type=float, default=0.4, help="Activation delay before reading menus")
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()

    if args.list_presets:
        print(json.dumps(ALIASES, indent=2, sort_keys=True))
        return 0

    candidates = candidate_labels(args.aspect)
    if not candidates:
        parser.error("aspect is required unless --list-presets is used")

    if args.dry_run:
        print(json.dumps({
            "success": True,
            "dry_run": True,
            "aspect": args.aspect,
            "candidate_labels": candidates,
            "menu_path": "Timeline > Output Blanking",
        }, indent=2))
        return 0

    if sys.platform != "darwin":
        print(json.dumps({"success": False, "error": "macOS only"}, indent=2), file=sys.stderr)
        return 2

    proc = subprocess.run(
        ["osascript", "-e", build_script(candidates, args.delay)],
        capture_output=True,
        text=True,
        timeout=args.timeout,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        note = None
        if "-1719" in stderr or "Hilfszugriff" in stderr or "assistive" in stderr.lower():
            note = (
                "Grant Accessibility permission in System Settings > Privacy & Security > "
                "Accessibility for the app/process running this helper or for osascript/Terminal."
            )
        print(json.dumps({
            "success": False,
            "error": stderr or (proc.stdout or "").strip(),
            "returncode": proc.returncode,
            "candidate_labels": candidates,
            "accessibility_note": note,
        }, indent=2), file=sys.stderr)
        return proc.returncode

    print(json.dumps({
        "success": True,
        "clicked_label": (proc.stdout or "").strip(),
        "candidate_labels": candidates,
        "menu_path": "Timeline > Output Blanking",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
