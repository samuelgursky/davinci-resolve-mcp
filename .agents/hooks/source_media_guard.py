#!/usr/bin/env python3
"""PreToolUse guard: shell commands may read source media, never rewrite it.

AGENTS.md opens with the non-negotiable rule — never modify, transcode, convert,
proxy, relink, replace, or create derivatives of source media unless the user
asked for that exact operation. Analysis output belongs in scratch space, the
session sandbox, or the davinci-resolve-mcp-analysis project root.

Nothing enforced that for Bash. A single `ffmpeg -i camera.mov out.mov` with the
wrong output path, or an `rm` on a card, is unrecoverable. This hook denies
mutating shell commands whose target is a media file outside a scratch root.

What it does not catch, stated plainly so it is not mistaken for a sandbox: it
reads argv lexically, so a directory delete with no media extension
(`rm -rf /Volumes/CARD/DCIM`), an indirect delete (`find … -delete`,
`… | xargs rm`), or a script that writes media of its own
(`python transcode.py --out …`) all pass. This is a tripwire for the common
direct mistake, not a boundary. The boundary is still the rule in AGENTS.md.

Reads the PreToolUse payload on stdin, emits a permission decision on stdout.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path
from typing import List, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_runtime import load_event, pretool_decision

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

# Commands that destroy or relocate what they are pointed at, as opposed to
# writing something new. A derivative-output directory licenses the second but
# never the first: a camera card with an `exports` folder is still a camera card.
DESTRUCTIVE = {"rm", "mv", "dd", "truncate", "shred", "unlink"}

# Scratch roots, anchored: the normalized path must start inside one of these.
SCRATCH_ROOTS = ("/tmp", "/private/tmp", "/var/folders")

# Directory names that mark scratch space, matched as whole path components —
# never as substrings, so `/Volumes/CARD/scratchpad-dailies` is not exempt.
SCRATCH_COMPONENTS = ("scratch", "davinci-resolve-mcp-analysis", ".cache")

# Common host session scratch directory prefixes.
SCRATCH_COMPONENT_PREFIXES = ("claude-", "codex-", "agent-")

# Multi-segment markers, matched as a contiguous run of components.
SCRATCH_RUNS = (("tests", "fixtures"), ("tests", "tmp"))

# Derivative-output directories. These exempt a *write* — a render, a proxy, an
# export landing where it belongs — but deliberately do not exempt a delete or a
# move, which is how a folder named `renders` on a source drive got a pass.
WRITE_ONLY_COMPONENTS = ("proxies", "renders", "exports")


def normalize(path: str) -> str:
    """Absolute, `..`-collapsed, `~`-expanded. Traversal cannot outrun a marker."""
    expanded = os.path.expanduser(os.path.expandvars(path))
    return os.path.normpath(os.path.abspath(expanded))


def components(path: str) -> List[str]:
    return [part for part in normalize(path).lower().split(os.sep) if part]


def has_run(parts: List[str], marker: Sequence[str]) -> bool:
    """True when marker appears as a contiguous run of whole components."""
    width = len(marker)
    return any(parts[i:i + width] == list(marker) for i in range(len(parts) - width + 1))


def decide(decision: str, reason: str) -> None:
    pretool_decision(decision, reason)


def is_scratch(path: str, destructive: bool = False) -> bool:
    """Is this path somewhere a derivative may land?

    `destructive` narrows the answer: a delete or a move must clear a genuine
    scratch root, not merely sit in a directory named `renders`.
    """
    resolved = normalize(path).lower()
    parts = components(path)

    configured = os.environ.get("RESOLVE_MCP_SCRATCH", "")
    roots = SCRATCH_ROOTS + ((normalize(configured).lower(),) if configured else ())
    if any(resolved == root or resolved.startswith(root.rstrip(os.sep) + os.sep) for root in roots):
        return True

    if any(part in SCRATCH_COMPONENTS for part in parts):
        return True
    if any(part.startswith(SCRATCH_COMPONENT_PREFIXES) for part in parts):
        return True
    if any(has_run(parts, marker) for marker in SCRATCH_RUNS):
        return True

    if not destructive and any(part in WRITE_ONLY_COMPONENTS for part in parts):
        return True

    return False


def is_media(token: str) -> bool:
    return token.lower().endswith(MEDIA_SUFFIXES)


def split_commands(command: str) -> List[str]:
    """Split on shell separators so `ffprobe x && rm y` is checked as two.

    Newlines are separators too, and that was a hole worth naming: a multi-line
    block was one segment, so `argv0` came from the first line and a harmless
    one returned before anything under it was looked at. `mkdir -p x` then a
    newline then `mv camera.mov x/` passed, while the same two joined by `;`
    denied — the same command to a shell, two answers from the guard.

    The cost of splitting on newlines is that any multi-line text carried inside
    a command — a heredoc body, a commit message — is read as commands too, so a
    message that merely *quotes* `rm camera.mov` is denied. That is the right way
    round for a tripwire: rephrase, or write the text to a file first.
    """
    return [part for part in re.split(r"&&|\|\||;|\||\n", command) if part.strip()]


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

    destructive = argv0 in DESTRUCTIVE

    if argv0 in {"ffmpeg", "avconv"}:
        # ffmpeg reads every -i and writes the trailing operand. That operand is
        # checked even when it also appears as an input: `ffmpeg -i x.mp4 x.mp4`
        # is the in-place overwrite this hook exists to stop, and exempting an
        # output for matching an input exempted exactly that command.
        #
        # The one trailing token that is not an output is the value of a `-i`
        # immediately before it — `ffmpeg -i master.mov` prints stream info and
        # writes nothing. Denying a read would only teach an agent to route
        # around the guard to look at a file.
        trailing = args[-1:] if args and not args[-1].startswith("-") else []
        if len(args) >= 2 and args[-2] == "-i":
            trailing = []
        return [t for t in trailing if is_media(t) and not is_scratch(t)]

    if argv0 == "cp":
        # Only the destination is at risk.
        operands = [a for a in args if not a.startswith("-")]
        return [t for t in operands[-1:] if is_media(t) and not is_scratch(t)]

    return [
        a for a in args
        if not a.startswith("-") and is_media(a) and not is_scratch(a, destructive)
    ]


def main() -> None:
    event = load_event()

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
