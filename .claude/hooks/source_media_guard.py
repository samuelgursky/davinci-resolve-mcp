#!/usr/bin/env python3
"""PreToolUse guard: shell commands may read source media, never rewrite it.

AGENTS.md opens with the non-negotiable rule — never modify, transcode, convert,
proxy, relink, replace, or create derivatives of source media unless the user
asked for that exact operation. Analysis output belongs in scratch space, the
session sandbox, or the davinci-resolve-mcp-analysis project root.

Nothing enforced that for Bash. A single `ffmpeg -i camera.mov out.mov` with the
wrong output path, or an `rm` on a card, is unrecoverable. This hook denies
mutating shell commands whose target is a media file outside a scratch root.

Reads the PreToolUse payload on stdin, emits a permission decision on stdout.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from typing import List

MEDIA_SUFFIXES = (
    # camera + delivery containers
    ".mov", ".mp4", ".mxf", ".avi", ".mkv", ".m4v", ".mts", ".m2ts", ".webm",
    # camera raw
    ".braw", ".r3d", ".ari", ".arx", ".arriraw", ".crm", ".cine", ".dng",
    # image sequences
    ".exr", ".dpx", ".tif", ".tiff", ".cr2", ".cr3", ".nef", ".arw",
    # audio
    ".wav", ".aif", ".aiff", ".caf", ".flac", ".mp3", ".m4a",
    # project + grade state
    ".drp", ".drt", ".drx",
)

# Commands that write, move, or destroy whatever they are pointed at.
MUTATING = {
    "rm", "mv", "cp", "dd", "truncate", "shred", "unlink", "install",
    "ffmpeg", "avconv", "HandBrakeCLI", "handbrakecli",
    "convert", "magick", "sips", "qt-faststart",
    "exiftool", "touch", "chmod", "chown",
}

# Roots where derivative files are allowed to land.
SCRATCH_MARKERS = (
    "/scratch",
    "/claude-",
    "davinci-resolve-mcp-analysis",
    "/tmp/",
    "/var/folders/",
    "/private/tmp/",
    ".cache/",
    "/proxies/",
    "/renders/",
    "/exports/",
    "tests/fixtures",
    "tests/tmp",
)


def decide(decision: str, reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    sys.exit(0)


def is_scratch(path: str) -> bool:
    lowered = path.lower()
    if any(marker.lower() in lowered for marker in SCRATCH_MARKERS):
        return True
    configured = os.environ.get("RESOLVE_MCP_SCRATCH", "")
    return bool(configured) and lowered.startswith(configured.lower())


def is_media(token: str) -> bool:
    return token.lower().endswith(MEDIA_SUFFIXES)


def split_commands(command: str) -> List[str]:
    """Split on shell separators so `ffprobe x && rm y` is checked as two."""
    return [part for part in re.split(r"&&|\|\||;|\|", command) if part.strip()]


def endangered_targets(segment: str) -> List[str]:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    if not tokens:
        return []

    argv0 = os.path.basename(tokens[0])
    # Skip an env prefix like `FOO=bar ffmpeg ...`
    index = 0
    while index < len(tokens) and "=" in tokens[index] and not tokens[index].startswith("-"):
        index += 1
        argv0 = os.path.basename(tokens[index]) if index < len(tokens) else argv0

    args = tokens[index + 1:]

    if argv0 not in MUTATING:
        # Still catch redirection onto a media file: `... > camera.mov`
        return [t for t in re.findall(r">>?\s*(\S+)", segment) if is_media(t)]

    if argv0 in {"ffmpeg", "avconv"}:
        # ffmpeg reads every -i and writes the trailing operand.
        inputs = {args[i + 1] for i, a in enumerate(args) if a == "-i" and i + 1 < len(args)}
        outputs = [a for a in args[-1:] if not a.startswith("-") and a not in inputs]
        return [t for t in outputs if is_media(t) and not is_scratch(t)]

    if argv0 == "cp":
        # Only the destination is at risk.
        operands = [a for a in args if not a.startswith("-")]
        return [t for t in operands[-1:] if is_media(t) and not is_scratch(t)]

    return [a for a in args if not a.startswith("-") and is_media(a) and not is_scratch(a)]


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    command = str((event.get("tool_input") or {}).get("command", ""))
    if not command.strip():
        sys.exit(0)

    hits: List[str] = []
    for segment in split_commands(command):
        hits.extend(endangered_targets(segment))

    if not hits:
        sys.exit(0)

    listed = "\n".join(f"  - {path}" for path in dict.fromkeys(hits))
    decide(
        "deny",
        "Blocked: this command writes to, moves, or deletes source media outside a "
        "scratch root.\n\n"
        f"{listed}\n\n"
        "AGENTS.md: never modify, transcode, convert, proxy, relink, replace, or create "
        "derivatives of source media unless the user asked for that exact operation. "
        "Reading is fine — ffprobe, and ffmpeg that writes into scratch, both pass.\n\n"
        "Send derivatives to the session scratch directory or the "
        "davinci-resolve-mcp-analysis project root instead. If the user did explicitly "
        "ask for this exact operation on this exact file, say so and let them approve it.",
    )


if __name__ == "__main__":
    main()
