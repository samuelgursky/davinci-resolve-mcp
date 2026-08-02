#!/usr/bin/env python3
"""Can a cut be re-imported after its media has moved? Per format, per mode.

    python scripts/relink_moved_media.py run --mode headless --out relink_hl.json

Every round-trip measured so far imported media that was still exactly where it
was exported from. That is the easy case and not the one conform exists for. The
question here is the real one: **the cut is on one machine and the footage is
somewhere else — which formats can still find it, and is the result still
frame-exact?**

The test moves the media for real. Sources are staged into their own directory,
the project is built from that directory, the cut is exported, and then the
directory is *renamed* — so the paths baked into every exported file are now
dead. Import then runs in a fresh project with `sourceClipsPath` pointing at the
new location.

Two things are measured, and the second is the one that matters:

  - **linked** — did Resolve find the media at all?
  - **cut fidelity** — having found it, is the cut still frame-exact? A relink
    that lands the right files at the wrong source in-points is worse than one
    that fails, because it produces a plausible wrong answer.

The original fixture in `resolve_roundtrip_fixture/` is never touched; the
staging directories are separate copies, and are cleaned up at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import resolve_runtime as rr  # noqa: E402
from src.utils.project_cleanup import delete_project_safely, save_project_if_safe  # noqa: E402

FIXTURE = Path.home() / "Movies" / "resolve_roundtrip_fixture"
STAGE_FROM = Path.home() / "Movies" / "relink_origin"
STAGE_TO = Path.home() / "Movies" / "relink_moved"

FORMATS = [
    ("drt", "EXPORT_DRT", "EXPORT_NONE", "drt"),
    ("fcpxml_1_10", "EXPORT_FCPXML_1_10", "EXPORT_NONE", "fcpxml"),
    ("fcp7xml", "EXPORT_FCP_7_XML", "EXPORT_NONE", "xml"),
    ("aaf", "EXPORT_AAF", "EXPORT_AAF_NEW", "aaf"),
    ("otio", "EXPORT_OTIO", "EXPORT_NONE", "otio"),
    ("edl", "EXPORT_EDL", "EXPORT_NONE", "edl"),
]


def connect(timeout: float = 420.0) -> Any:
    api = os.environ.get(
        "RESOLVE_SCRIPT_API",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting")
    modules = str(Path(api) / "Modules")
    if modules not in sys.path:
        sys.path.append(modules)
    import DaVinciResolveScript as dvr
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
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


def stage() -> List[Path]:
    """Fresh copies in their own directory, so the fixture is never moved."""
    for path in (STAGE_FROM, STAGE_TO):
        shutil.rmtree(path, ignore_errors=True)
    STAGE_FROM.mkdir(parents=True, exist_ok=True)
    out = []
    for index in (1, 2):
        source = FIXTURE / f"rt_source_{index}.mov"
        if not source.exists():
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=24:duration=8",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=8",
                 "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
                 "-timecode", "01:00:00:00", "-y", str(source)],
                check=True, timeout=300)
        target = STAGE_FROM / source.name
        shutil.copy2(source, target)
        out.append(target)
    return out


def cut_of(timeline: Any) -> List[Dict[str, Any]]:
    out = []
    for track in range(1, (timeline.GetTrackCount("video") or 0) + 1):
        for item in timeline.GetItemListInTrack("video", track) or []:
            path = None
            try:
                pool_item = item.GetMediaPoolItem()
                path = pool_item.GetClipProperty("File Path") if pool_item else None
            except Exception:
                path = None
            out.append({"track": track, "start": item.GetStart(),
                        "duration": item.GetDuration(),
                        "left_offset": item.GetLeftOffset(),
                        "source": Path(path).name if path else None,
                        "resolved": bool(path and Path(path).exists()),
                        "dir": str(Path(path).parent) if path else None})
    return out


def run(mode: str, out_path: Path) -> int:
    observed = rr.runtime_mode()
    if observed["running"] and bool(observed["headless"]) != (mode == "headless"):
        print("REFUSE: Resolve running in the other mode.", file=sys.stderr)
        return 1
    resolve = connect()
    if resolve is None:
        print("REFUSE: no healthy Resolve.", file=sys.stderr)
        return 2
    pm = resolve.GetProjectManager()
    save_project_if_safe(pm)
    incumbent = pm.GetCurrentProject()
    incumbent_name = incumbent.GetName() if incumbent else None

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    build_name, import_name = f"RELINK_SRC_{stamp}", f"RELINK_DST_{stamp}"
    exports = Path.home() / "Movies" / f"relink_exports_{stamp}"
    exports.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {"metadata": {
        "mode": mode, "headless": observed["headless"],
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": resolve.GetVersionString()}, "formats": {}}

    try:
        # ── build the cut from STAGE_FROM ────────────────────────────────────
        media = stage()
        pm.CreateProject(build_name)
        pm.LoadProject(build_name)
        project = pm.GetCurrentProject()
        pool = project.GetMediaPool()
        clips = resolve.GetMediaStorage().AddItemListToMediaPool([str(p) for p in media]) or []
        if len(clips) < 2:
            raise RuntimeError("staging import failed")
        frames = int(clips[0].GetClipProperty("Frames") or 0)
        timeline = pool.CreateEmptyTimeline("RELINK_REF")
        project.SetCurrentTimeline(timeline)
        pool.AppendToTimeline([
            {"mediaPoolItem": clips[0], "startFrame": 0, "endFrame": frames - 1},
            {"mediaPoolItem": clips[1], "startFrame": 24, "endFrame": 71},
            {"mediaPoolItem": clips[0], "startFrame": 48, "endFrame": 95},
        ])
        reference = cut_of(timeline)
        report["reference"] = reference
        print(f"built {len(reference)} items from {STAGE_FROM}", flush=True)

        for label, type_attr, sub_attr, ext in FORMATS:
            path = exports / f"relink.{ext}"
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            ok = timeline.Export(str(path), getattr(resolve, type_attr),
                                 getattr(resolve, sub_attr))
            import_path = path
            if path.is_dir():
                members = sorted(path.glob("*.fcpxml"))
                import_path = members[0] if members else path
            report["formats"][label] = {"exported": bool(ok), "import_path": str(import_path)}

        # ── move the media, and close the project that still references it ───
        pm.SaveProject()
        pm.CloseProject(pm.GetCurrentProject())
        shutil.move(str(STAGE_FROM), str(STAGE_TO))
        print(f"moved media: {STAGE_FROM} -> {STAGE_TO}", flush=True)

        # ── import each cut into a fresh project, pointed at the NEW path ────
        pm.CreateProject(import_name)
        pm.LoadProject(import_name)
        project = pm.GetCurrentProject()
        pool = project.GetMediaPool()
        for label, *_ in FORMATS:
            entry = report["formats"][label]
            if not entry.get("exported"):
                continue
            options: Dict[str, Any] = {} if label == "drt" else {
                "timelineName": f"RL_{label}",
                "importSourceClips": True,
                "sourceClipsPath": str(STAGE_TO),
            }
            try:
                imported = pool.ImportTimelineFromFile(entry["import_path"], options) if options \
                    else pool.ImportTimelineFromFile(entry["import_path"])
            except Exception as exc:
                entry["imported"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"
                print(f"  {label:12} import raised {exc}", flush=True)
                continue
            if not imported:
                entry["imported"] = False
                print(f"  {label:12} import returned None", flush=True)
                continue
            actual = cut_of(imported)
            entry["imported"] = True
            entry["cut"] = actual
            resolved = sum(1 for i in actual if i["resolved"])
            # Frame fidelity compared on the fields that survive a relink: the
            # media may legitimately live somewhere new, but the cut must not
            # move.
            same = (len(actual) == len(reference) and all(
                a["start"] == b["start"] and a["duration"] == b["duration"]
                and a["left_offset"] == b["left_offset"]
                for a, b in zip(reference, actual)))
            entry["relinked"] = resolved
            entry["total"] = len(actual)
            entry["frame_exact"] = same
            where = {i["dir"] for i in actual if i["dir"]}
            entry["resolved_dirs"] = sorted(where)
            print(f"  {label:12} relinked={resolved}/{len(actual)} frame_exact={same} "
                  f"dirs={[Path(w).name for w in sorted(where)]}", flush=True)
            try:
                pool.DeleteTimelines([imported])
            except Exception:
                pass
    finally:
        try:
            pm.SaveProject()
            pm.CloseProject(pm.GetCurrentProject())
            if incumbent_name:
                pm.LoadProject(incumbent_name)
            for name in (build_name, import_name):
                delete_project_safely(pm, name, switch_to=incumbent_name)
        except Exception as exc:
            report["teardown_error"] = repr(exc)
        shutil.rmtree(STAGE_TO, ignore_errors=True)
        shutil.rmtree(STAGE_FROM, ignore_errors=True)
        shutil.rmtree(exports, ignore_errors=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"report: {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--mode", choices=("gui", "headless"), required=True)
    r.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    return run(args.mode, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
