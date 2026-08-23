"""When Resolve cannot be reached, produce something importable instead of stopping.

An unreachable Resolve currently ends the work. The error explaining *why* is a good
one — it reads the situation and names the fix that applies — but the timeline the caller
wanted still does not exist, and the interchange authoring that could produce it has been
sitting in this repository the whole time, one process away.

This routes to it. A clip plan the live path would have built in the app becomes an
OTIO, EDL, or DRT file the user imports in one action.

## It is an offer, never a substitute

A caller who asked to build a timeline *in Resolve* has not succeeded because a file was
written somewhere. The connection error stays an error and gains an `offline_alternative`
block naming what could be produced; authoring only happens when someone asks for it.
Silently rerouting would turn "your project now has this timeline" into a claim that is
false in the only sense that matters.

## Target order: DRT, then OTIO, then EDL

DRT is Resolve-native and carries track structure. OTIO round-trips through this repo's
own parser and carries gaps, per-clip speed, and transitions. EDL is CMX3600 — video
cuts and M2 speed, nothing else — and is the fallback when the other two are refused.

## Two traps that have already cost time once

- **OTIO source frames are timecode-absolute.** An event with no media timecode origin
  imports as an *empty* timeline: the file opens, nothing appears, and no error is
  raised. Every event that had to assume an origin comes back as a warning naming the
  clip, rather than being discovered later as a silent no-op.
- **A `.drt` carries no per-clip speed.** Retimes flatten to 100% forward. Events that
  lost one are named; OTIO is the target that keeps them.

## Authoring runs in Node, deliberately

`resolve-advanced/server/author-interchange.mjs` already writes all three formats and is
covered by that server's own suite. A second implementation in Python would be two
writers to keep in agreement, and the one that drifts is always the copy nobody runs. If
Node is unavailable, this says so and refuses — it does not fall back to a half-format.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIDGE_SCRIPT = os.path.join(REPO_ROOT, "scripts", "author_interchange.mjs")
AUTHORING_MODULE = os.path.join(
    REPO_ROOT, "resolve-advanced", "server", "author-interchange.mjs"
)

TARGETS = ("drt", "otio", "edl")
DEFAULT_TARGET = "drt"
DEFAULT_FPS = 24.0

#: `drt.downgrade`'s verified map, quoted so the response can say which Resolve a file
#: targets instead of leaving the caller to find out on import.
DRT_PROJECT_VERSIONS = {"18.0.4": 11, "19.1": 14, "21.0": 17}


class OfflineFallbackError(Exception):
    """Bad plan, missing tool, or a target that cannot carry the plan honestly."""


def capabilities() -> Dict[str, Any]:
    node = shutil.which("node")
    return {
        "available": bool(node) and os.path.isfile(BRIDGE_SCRIPT) and os.path.isfile(AUTHORING_MODULE),
        "node_path": node,
        "bridge_script": BRIDGE_SCRIPT if os.path.isfile(BRIDGE_SCRIPT) else None,
        "authoring_module": AUTHORING_MODULE if os.path.isfile(AUTHORING_MODULE) else None,
        "targets": list(TARGETS),
        "default_target": DEFAULT_TARGET,
        "drt_project_versions": DRT_PROJECT_VERSIONS,
        "note": (
            "Writes an importable timeline when Resolve is unreachable. It does not make "
            "a failed live operation succeed — the timeline exists as a file, not in a "
            "project, until someone imports it."
        ),
    }


def _require() -> None:
    report = capabilities()
    if report["available"]:
        return
    missing = []
    if not report["node_path"]:
        missing.append("node is not on PATH")
    if not report["bridge_script"]:
        missing.append(f"{BRIDGE_SCRIPT} is missing")
    if not report["authoring_module"]:
        missing.append("the resolve-advanced authoring module is missing from this install")
    raise OfflineFallbackError(
        "offline interchange authoring is unavailable: " + "; ".join(missing)
    )


# ── plan → events ────────────────────────────────────────────────────────────


def _number(value: Any, field: str, clip_index: int) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise OfflineFallbackError(f"clip {clip_index}: '{field}' is not a number ({value!r})")


def plan_to_events(
    clips: Sequence[Dict[str, Any]], *, fps: float = DEFAULT_FPS
) -> List[Dict[str, Any]]:
    """Turn a file-path clip plan into the normalized event list the writers take.

    Everything is in FRAMES at the timeline rate. `end_frame` is EXCLUSIVE, matching
    `AppendToTimeline`'s half-open range — the two shapes disagreeing would be a
    one-frame error on every clip, which is exactly the kind that survives review.

    Clips without `record_frame` are laid end to end per track, in the order given.
    """
    if not clips:
        raise OfflineFallbackError("supply at least one clip")

    cursor: Dict[str, float] = {"V": 0.0, "A": 0.0}
    events: List[Dict[str, Any]] = []
    for index, clip in enumerate(clips):
        if not isinstance(clip, dict) or not clip.get("path"):
            raise OfflineFallbackError(f"clip {index}: needs a 'path'")
        path = str(clip["path"])
        media_type = str(clip.get("media_type") or clip.get("mediaType") or "video").lower()
        track = "A" if media_type.startswith("audio") else "V"

        start = _number(clip.get("start_frame", clip.get("startFrame", 0)), "start_frame", index) or 0.0
        end = _number(clip.get("end_frame", clip.get("endFrame")), "end_frame", index)
        duration = _number(clip.get("duration_frames", clip.get("durationFrames")), "duration_frames", index)
        if end is None and duration is None:
            raise OfflineFallbackError(
                f"clip {index}: supply end_frame (exclusive) or duration_frames"
            )
        if end is None:
            end = start + float(duration)
        length = float(end) - float(start)
        if length <= 0:
            raise OfflineFallbackError(
                f"clip {index}: end_frame ({end}) must be greater than start_frame ({start}); "
                "end_frame is exclusive"
            )

        record = _number(clip.get("record_frame", clip.get("recordFrame")), "record_frame", index)
        if record is None:
            record = cursor[track]
        cursor[track] = float(record) + length

        event: Dict[str, Any] = {
            "source": path,
            "track": track,
            "recIn": int(round(float(record))),
            "recOut": int(round(float(record) + length)),
            "srcIn": int(round(float(start))),
            "srcOut": int(round(float(end))),
            "fps": float(clip.get("fps") or fps),
        }
        origin = clip.get("media_start_tc_frame", clip.get("mediaStartTcFrame"))
        if origin is not None:
            event["mediaStartTcFrame"] = int(round(float(origin)))
        absolute = clip.get("src_tc_frame", clip.get("srcTcFrame"))
        if absolute is not None:
            event["srcTcFrame"] = int(round(float(absolute)))
        if clip.get("speed") is not None:
            event["speed"] = float(clip["speed"])
        if clip.get("reverse"):
            event["reverse"] = True
        if clip.get("name"):
            event["name"] = str(clip["name"])
        events.append(event)
    return events


# ── authoring ────────────────────────────────────────────────────────────────


def author(
    clips: Sequence[Dict[str, Any]],
    output_path: str,
    *,
    target: str = DEFAULT_TARGET,
    name: str = "Offline Conform",
    fps: float = DEFAULT_FPS,
    start_timecode: str = "01:00:00:00",
    resolution: str = "1920x1080",
) -> Dict[str, Any]:
    """Author an importable timeline file from a clip plan."""
    normalized = str(target or DEFAULT_TARGET).lower()
    if normalized not in TARGETS:
        raise OfflineFallbackError(
            f"unknown target '{target}'. Valid targets: {', '.join(TARGETS)}"
        )
    _require()
    events = plan_to_events(clips, fps=fps)

    request = {
        "events": events,
        "target": normalized,
        "outputPath": os.path.abspath(output_path),
        "opts": {
            "name": name,
            "fps": float(fps),
            "startTimecode": start_timecode,
            "resolution": resolution,
        },
    }
    process = subprocess.run(
        [shutil.which("node"), BRIDGE_SCRIPT],
        input=json.dumps(request).encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=120,
    )
    raw = process.stdout.decode("utf-8", "replace").strip()
    try:
        result = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise OfflineFallbackError(
            f"the authoring bridge produced no usable output "
            f"(exit {process.returncode}): {raw[:300] or process.stderr.decode('utf-8', 'replace')[-300:]}"
        )
    if not result.get("ok"):
        raise OfflineFallbackError(result.get("error") or "authoring failed")

    return {
        "target": result["target"],
        "output_path": result["outputPath"],
        "bytes": result["bytes"],
        "event_count": result["eventCount"],
        "warnings": result.get("warnings", []),
        "import_with": _import_instruction(result["target"]),
        "resolve_version": _version_note(result["target"]),
        "note": (
            "The timeline exists as a file. It is not in any project until it is "
            "imported."
        ),
    }


def _import_instruction(target: str) -> str:
    return {
        "drt": "Resolve: right-click a Media Pool bin > Timelines > Import > Timeline, "
               "or File > Import > Timeline.",
        "otio": "Resolve: File > Import > Timeline, and pick the .otio.",
        "edl": "Resolve: right-click a bin > Timelines > Import > Pre-conformed EDL. "
               "Media must already be in the Media Pool for it to link.",
    }[target]


def _version_note(target: str) -> Dict[str, Any]:
    if target != "drt":
        return {
            "targets": "any Resolve that reads this format",
            "note": "No project-version gate applies to OTIO or EDL.",
        }
    return {
        "targets": "Resolve 21.0 (project version 17)",
        "older_builds": (
            "An older Resolve refuses a newer project version. Use the advanced server's "
            "`drt(action='downgrade')` to stamp it down — verified map: 18.0.4 -> 11, "
            "19.1.x -> 14, 21.0 -> 17."
        ),
        "project_versions": DRT_PROJECT_VERSIONS,
    }


# ── the offer attached to a connection failure ───────────────────────────────


def offline_alternative(*, action: Optional[str] = None) -> Dict[str, Any]:
    """The block a not-connected error carries. Describes an option; performs nothing."""
    report = capabilities()
    if not report["available"]:
        return {
            "available": False,
            "reason": (
                "Offline interchange authoring needs Node and the bundled authoring "
                "module; one of them is missing from this install."
            ),
        }
    return {
        "available": True,
        "what": (
            "Resolve is unreachable, but a timeline can still be written as a file you "
            "import in one action."
        ),
        "call": (
            "timeline(action='author_offline', params={'clips': [{'path': ..., "
            "'start_frame': ..., 'end_frame': ...}], 'output_path': ..., 'target': 'drt'})"
        ),
        "targets": list(TARGETS),
        "does_not": (
            "This does not complete the operation that just failed"
            + (f" ({action})" if action else "")
            + ". Nothing is added to a Resolve project until the file is imported."
        ),
    }
