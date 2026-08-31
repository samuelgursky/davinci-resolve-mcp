#!/usr/bin/env python3
"""Run probes in order, streaming one JSONL result per probe. Not run directly.

Launched by `scripts/mode_matrix.py`, which supervises it. The division of labour
is the whole design: this process is *expected* to die. When a probe never
returns there is nothing this side can do about it — the call is blocked inside
fusionscript, and a Python signal handler cannot preempt a thread parked in a C
`pthread_cond_wait`. So the worker's only obligation is to have already written
down everything it finished, in order, flushed, before it hangs. The supervisor
reads that and infers the culprit from what is missing.

Consequences of that contract, both load-bearing:

  - every result is written and flushed immediately, never batched;
  - probes run in the catalogue's order, so "first missing" is unambiguous.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.mode_matrix import classify_outcome  # noqa: E402
from src.utils.probe_catalogue import CATALOGUE, fingerprint  # noqa: E402
from src.utils.project_cleanup import UNSAVED_DEFAULT_PROJECT, save_project_if_safe  # noqa: E402
from src.utils import resolve_runtime as rr  # noqa: E402


class Context:
    """What a probe body is handed."""

    def __init__(self) -> None:
        self.resolve: Any = None
        self.pm: Any = None
        self.project: Any = None
        self.timeline: Any = None
        self.item: Any = None
        self.clip: Any = None
        self.work: Path = Path(tempfile.mkdtemp(prefix="mode_matrix_"))
        self.project_name = ""


def connect() -> Any:
    api = os.environ.get(
        "RESOLVE_SCRIPT_API",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
    )
    modules = str(Path(api) / "Modules")
    if modules not in sys.path:
        sys.path.append(modules)
    import DaVinciResolveScript as dvr

    for _ in range(120):
        resolve = dvr.scriptapp("Resolve")
        if resolve is not None:
            try:
                pm = resolve.GetProjectManager()
                if pm is not None and pm.GetCurrentDatabase():
                    return resolve
            except Exception:
                pass
        time.sleep(1)
    return None


def make_media(work: Path) -> Path:
    clip = work / "probe_source.mov"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
         "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
         "-y", str(clip)],
        check=True, timeout=180,
    )
    return clip


def build_fixture(ctx: Context) -> None:
    """A disposable project with one clip on one timeline."""
    ctx.pm = ctx.resolve.GetProjectManager()
    # Guarded: on the never-saved default project this call hangs forever
    # headless. The worker reaching it here would take down setup for every
    # probe rather than for the one probe that is meant to measure it.
    save_project_if_safe(ctx.pm)
    ctx.project_name = f"MODE_MATRIX_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if not ctx.pm.CreateProject(ctx.project_name):
        raise RuntimeError(f"could not create {ctx.project_name}")
    ctx.pm.LoadProject(ctx.project_name)
    ctx.project = ctx.pm.GetCurrentProject()

    media = make_media(ctx.work)
    clips = ctx.resolve.GetMediaStorage().AddItemListToMediaPool([str(media)]) or []
    ctx.clip = clips[0] if clips else None
    if ctx.clip is None:
        raise RuntimeError("media import produced no clips")
    pool = ctx.project.GetMediaPool()
    ctx.timeline = pool.CreateTimelineFromClips("PROBE_TL", [ctx.clip])
    if ctx.timeline:
        ctx.project.SetCurrentTimeline(ctx.timeline)
        items = ctx.timeline.GetItemListInTrack("video", 1) or []
        ctx.item = items[0] if items else None


def ensure_state(ctx: Context, state: str) -> Optional[str]:
    """Put Resolve on the project this probe needs. Returns a skip reason or None.

    `untitled` means Resolve's never-saved default project — reachable by closing
    whatever is open. It exists as a state because the only mode-dependent hang
    found so far happens exclusively there, and a catalogue that always ran
    against a well-formed scratch project reported no differences at all.
    """
    current = ctx.pm.GetCurrentProject()
    name = current.GetName() if current else None
    if state == "untitled":
        if name == UNSAVED_DEFAULT_PROJECT:
            return None
        # SAVE BEFORE CLOSING. The scratch project has unsaved changes by this
        # point (media imported, timeline built), and CloseProject on a modified
        # project raises the GUI's "save changes?" dialog — which blocked the
        # whole application, put a modal on the user's screen, and got
        # misattributed to the probe that never got to run. It is a named
        # project, so the save is safe in both modes.
        save_project_if_safe(ctx.pm)
        ctx.pm.CloseProject(current) if current else None
        current = ctx.pm.GetCurrentProject()
        name = current.GetName() if current else None
        return None if name == UNSAVED_DEFAULT_PROJECT else f"could not reach the default project (on {name!r})"
    if name != ctx.project_name:
        if not ctx.pm.LoadProject(ctx.project_name):
            return f"could not return to the scratch project (on {name!r})"
        ctx.project = ctx.pm.GetCurrentProject()
        ctx.timeline = ctx.project.GetCurrentTimeline() if ctx.project else None
        if ctx.timeline:
            items = ctx.timeline.GetItemListInTrack("video", 1) or []
            ctx.item = items[0] if items else None
    return None


def unmet(ctx: Context, needs) -> Optional[str]:
    for need in needs:
        if getattr(ctx, need, None) is None:
            return f"needs {need}"
    return None


def emit(handle, record: Dict[str, Any]) -> None:
    handle.write(json.dumps(record, default=str) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--probes", nargs="+", required=True)
    args = parser.parse_args()

    mode = "headless" if rr.is_headless() else "gui"
    ctx = Context()
    ctx.resolve = connect()
    if ctx.resolve is None:
        print("worker: no healthy Resolve", file=sys.stderr)
        return 2

    wanted = set(args.probes)
    probes = [p for p in CATALOGUE if p.name in wanted]

    with args.out.open("a", encoding="utf-8") as handle:
        try:
            build_fixture(ctx)
        except Exception as exc:
            for probe in probes:
                emit(handle, {"probe": probe.name, "category": probe.category,
                              "outcome": "skipped", "mode": mode,
                              "detail": f"fixture failed: {type(exc).__name__}: {exc}"})
            return 3

        for probe in probes:
            # Breadcrumbs, so a hang can be attributed to the phase that caused
            # it. Setting up a probe's state is itself a sequence of Resolve
            # calls that can block, and blaming the probe for a hang in its
            # setup sends the reader looking at the wrong call — which is exactly
            # what happened when CloseProject-on-a-modified-project raised a
            # dialog and `pm.save_untitled_project` was recorded as the culprit.
            emit(handle, {"_start": probe.name, "phase": "state"})
            skip = ensure_state(ctx, probe.state) or unmet(ctx, probe.needs)
            if skip:
                emit(handle, {"probe": probe.name, "category": probe.category,
                              "outcome": "skipped", "mode": mode, "detail": skip})
                continue
            emit(handle, {"_start": probe.name, "phase": "body"})
            started = time.monotonic()
            try:
                value = probe.body(ctx)
                outcome = classify_outcome(value)
                detail = ""
            except Exception as exc:
                value, outcome, detail = None, "raised", f"{type(exc).__name__}: {exc}"
            emit(handle, {
                "probe": probe.name, "category": probe.category, "outcome": outcome,
                "value": repr(value)[:200] if outcome != "raised" else None,
                "seconds": round(time.monotonic() - started, 2),
                "mode": mode, "detail": detail, "note": probe.note,
                "catalogue": fingerprint(),
            })

        # Teardown: close (releases the session lock) before deleting, and never
        # leave the session on the unsaveable default project.
        try:
            ctx.pm.LoadProject(ctx.project_name)
            ctx.pm.CloseProject(ctx.pm.GetCurrentProject())
            ctx.pm.DeleteProject(ctx.project_name)
        except Exception:
            pass
    shutil.rmtree(ctx.work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
