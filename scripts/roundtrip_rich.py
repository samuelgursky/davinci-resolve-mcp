#!/usr/bin/env python3
"""Round-trip a cut that has something to lose, and report *what* each format loses.

    python scripts/roundtrip_rich.py run --mode gui      --out rr_gui.json
    python scripts/roundtrip_rich.py run --mode headless --out rr_headless.json
    python scripts/roundtrip_rich.py compare rr_gui.json rr_headless.json

`roundtrip_matrix.py` found every format frame-exact in both modes. That result
is real but it was measured on a flat, single-track cut of untouched clips —
the formats agreed because there was nothing to disagree about. A cut like that
is not what anyone builds.

This one has: two video tracks, audio, a per-item transform (pan, zoom,
rotation, crop, flip), clip colours, flags, item markers and timeline markers.
Then it reports fidelity **per dimension** rather than as one boolean, because
"AAF preserved the cut but dropped the transforms" and "AAF preserved everything"
are completely different answers to "which format should my loop use", and a
single match/mismatch flag cannot tell them apart.

Every dimension is verified as *set* on the reference before it is compared —
a dimension the API silently refused to write would otherwise look like a
dimension every format faithfully preserved.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import resolve_runtime as rr  # noqa: E402
from src.utils.project_cleanup import delete_project_safely, save_project_if_safe  # noqa: E402

MEDIA_DIR = Path.home() / "Movies" / "resolve_roundtrip_fixture"

FORMATS = [
    ("drt", "EXPORT_DRT", "EXPORT_NONE", "drt"),
    ("fcpxml_1_10", "EXPORT_FCPXML_1_10", "EXPORT_NONE", "fcpxml"),
    ("fcp7xml", "EXPORT_FCP_7_XML", "EXPORT_NONE", "xml"),
    ("aaf", "EXPORT_AAF", "EXPORT_AAF_NEW", "aaf"),
    ("otio", "EXPORT_OTIO", "EXPORT_NONE", "otio"),
    ("edl", "EXPORT_EDL", "EXPORT_NONE", "edl"),
]

#: The transform written onto one item. Values are deliberately odd so a format
#: that writes defaults back cannot accidentally match.
TRANSFORM = {"ZoomX": 1.35, "Pan": 96.0, "RotationAngle": 12.0,
             "CropLeft": 40.0, "FlipX": True}

DIMENSIONS = ("cut", "tracks", "transform", "colour", "flags", "markers",
              "timeline_markers", "linkage")


def connect(timeout: float = 420.0) -> Any:
    api = os.environ.get(
        "RESOLVE_SCRIPT_API",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
    )
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


def media() -> List[Path]:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for index, pattern in enumerate(("testsrc2", "smptebars"), start=1):
        clip = MEDIA_DIR / f"rt_source_{index}.mov"
        if not clip.exists():
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", f"{pattern}=size=1920x1080:rate=24:duration=8",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=8",
                 "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
                 "-timecode", "01:00:00:00", "-y", str(clip)],
                check=True, timeout=300)
        out.append(clip)
    return out


def describe(timeline: Any) -> Dict[str, Any]:
    """Every dimension of a timeline that a format could drop."""
    video_tracks = timeline.GetTrackCount("video") or 0
    audio_tracks = timeline.GetTrackCount("audio") or 0
    cut: List[Dict[str, Any]] = []
    transform: List[Dict[str, Any]] = []
    colour: List[Any] = []
    flags: List[Any] = []
    markers: List[int] = []
    linked = offline = 0

    for track in range(1, video_tracks + 1):
        for item in timeline.GetItemListInTrack("video", track) or []:
            path = None
            try:
                pool_item = item.GetMediaPoolItem()
                path = pool_item.GetClipProperty("File Path") if pool_item else None
            except Exception:
                path = None
            if path and Path(path).exists():
                linked += 1
            else:
                offline += 1
            cut.append({"track": track, "start": item.GetStart(),
                        "duration": item.GetDuration(),
                        "left_offset": item.GetLeftOffset(),
                        "source": Path(path).name if path else None})
            values = {}
            for key in TRANSFORM:
                try:
                    values[key] = item.GetProperty(key)
                except Exception:
                    values[key] = "error"
            transform.append(values)
            try:
                colour.append(item.GetClipColor())
            except Exception:
                colour.append("error")
            try:
                flags.append(sorted(item.GetFlagList() or []))
            except Exception:
                flags.append("error")
            try:
                markers.append(len(item.GetMarkers() or {}))
            except Exception:
                markers.append(-1)

    audio_items = sum(len(timeline.GetItemListInTrack("audio", t) or [])
                      for t in range(1, audio_tracks + 1))
    return {
        "cut": cut,
        "tracks": {"video": video_tracks, "audio": audio_tracks, "audio_items": audio_items},
        "transform": transform,
        "colour": colour,
        "flags": flags,
        "markers": markers,
        "timeline_markers": len(timeline.GetMarkers() or {}),
        "linkage": {"linked": linked, "offline": offline},
    }


class RichRoundTrip:
    def __init__(self, resolve: Any) -> None:
        self.resolve = resolve
        self.pm = resolve.GetProjectManager()
        self.work = MEDIA_DIR / "exports_rich"
        self.work.mkdir(parents=True, exist_ok=True)
        self.name = f"RICHRT_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.project = self.pool = self.reference = None
        self.incumbent: Optional[str] = None

    def setup(self) -> Dict[str, Any]:
        incumbent = self.pm.GetCurrentProject()
        self.incumbent = incumbent.GetName() if incumbent else None
        save_project_if_safe(self.pm)
        if not self.pm.CreateProject(self.name):
            raise RuntimeError("could not create project")
        self.pm.LoadProject(self.name)
        self.project = self.pm.GetCurrentProject()
        self.pool = self.project.GetMediaPool()

        clips = self.resolve.GetMediaStorage().AddItemListToMediaPool(
            [str(p) for p in media()]) or []
        if len(clips) < 2:
            raise RuntimeError("media import failed")
        frames = int(clips[0].GetClipProperty("Frames") or 0)

        self.reference = self.pool.CreateEmptyTimeline("RR_REFERENCE")
        self.project.SetCurrentTimeline(self.reference)
        # V1: the spine.
        self.pool.AppendToTimeline([
            {"mediaPoolItem": clips[0], "startFrame": 0, "endFrame": frames - 1},
            {"mediaPoolItem": clips[1], "startFrame": 24, "endFrame": 71},
            {"mediaPoolItem": clips[0], "startFrame": 48, "endFrame": 95},
        ])
        # V2: an overlay, which is what makes this a multi-track cut at all.
        self.pool.AppendToTimeline([
            {"mediaPoolItem": clips[1], "startFrame": 0, "endFrame": 47,
             "trackIndex": 2, "recordFrame": self.reference.GetStartFrame() + 96,
             "mediaType": 1},
        ])

        applied: Dict[str, Any] = {}
        items = self.reference.GetItemListInTrack("video", 1) or []
        if items:
            applied["transform"] = {k: items[1].SetProperty(k, v) for k, v in TRANSFORM.items()} \
                if len(items) > 1 else {}
            applied["colour"] = items[0].SetClipColor("Orange")
            applied["flag"] = items[-1].AddFlag("Blue")
            applied["item_marker"] = items[0].AddMarker(1, "Blue", "RRM", "note", 1)
        applied["timeline_marker"] = self.reference.AddMarker(5, "Green", "RRTL", "note", 1)

        reference = describe(self.reference)
        # A dimension the API refused to write would look like a dimension every
        # format preserved. Record which ones actually landed, and compare only
        # those.
        landed = {
            "transform": any(reference["transform"][1].get(k) not in (None, "error")
                             for k in TRANSFORM) if len(reference["transform"]) > 1 else False,
            "colour": any(c not in (None, "", "error") for c in reference["colour"]),
            "flags": any(f for f in reference["flags"] if f and f != "error"),
            "markers": any(m > 0 for m in reference["markers"]),
            "timeline_markers": reference["timeline_markers"] > 0,
            "tracks": reference["tracks"]["video"] > 1,
        }
        return {"project": self.name, "applied": applied, "reference": reference,
                "dimensions_landed": landed}

    def export(self, label, type_attr, sub_attr, ext) -> Dict[str, Any]:
        path = self.work / f"rr_{label}.{ext}"
        if path.is_dir():
            import shutil
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
        try:
            ok = self.reference.Export(str(path), getattr(self.resolve, type_attr),
                                       getattr(self.resolve, sub_attr))
        except Exception as exc:
            return {"exported": False, "error": f"{type(exc).__name__}: {exc}"}
        import_path = path
        if path.is_dir():                      # FCPXML 1.10 writes a bundle
            members = sorted(path.glob("*.fcpxml"))
            import_path = members[0] if members else path
        return {"exported": bool(ok), "path": str(path), "import_path": str(import_path),
                "bytes": import_path.stat().st_size if import_path.is_file() else 0}

    def reimport(self, label: str, path: Path, tag: str) -> Dict[str, Any]:
        options: Dict[str, Any] = {} if label == "drt" else {
            "timelineName": f"RR_{label}_{tag}", "importSourceClips": False,
            "sourceClipsFolders": [self.pool.GetRootFolder()]}
        try:
            imported = self.pool.ImportTimelineFromFile(str(path), options) if options \
                else self.pool.ImportTimelineFromFile(str(path))
        except Exception as exc:
            return {"imported": False, "error": f"{type(exc).__name__}: {exc}"}
        if not imported:
            return {"imported": False}
        out = {"imported": True, "name": imported.GetName(), "described": describe(imported)}
        try:
            self.pool.DeleteTimelines([imported])
        except Exception:
            pass
        return out

    def teardown(self) -> Dict[str, Any]:
        notes = {}
        try:
            save_project_if_safe(self.pm)
            notes["closed"] = bool(self.pm.CloseProject(self.pm.GetCurrentProject()))
            if self.incumbent and self.incumbent != self.name:
                notes["restored"] = bool(self.pm.LoadProject(self.incumbent))
            notes["deleted"] = delete_project_safely(self.pm, self.name,
                                                     switch_to=self.incumbent)["success"]
        except Exception as exc:
            notes["error"] = repr(exc)
        return notes


def _same_number(a: Any, b: Any) -> bool:
    """Float-tolerant equality for transform values.

    Exporters round-trip geometry through their own units, so a crop of 40.0
    comes back as 39.999936. Calling that "lost" is not a useful thing to tell
    anyone — it is the same crop. The tolerance is relative and tight enough that
    a genuinely different value (a reset to 0.0, a default 1.0) still fails.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= max(1e-4, abs(a) * 1e-4)
    return a == b


def _diff_transform(reference: List[Dict[str, Any]], actual: List[Dict[str, Any]]) -> str:
    """Per-key, because "lost" hides the difference that matters.

    Measured: AAF resets every transform key to its default, while FCP7 XML
    preserves zoom, pan and rotation exactly and drops only FlipX. Both were
    reported as `lost` by a whole-dict comparison, which is the same word for
    "carries geometry" and "does not".
    """
    if len(reference) != len(actual):
        return "lost:item-count"
    dropped = set()
    for expected, got in zip(reference, actual):
        for key in TRANSFORM:
            if not _same_number(expected.get(key), got.get(key)):
                dropped.add(key)
    if not dropped:
        return "kept"
    return "lost:all" if dropped == set(TRANSFORM) else "lost:" + ",".join(sorted(dropped))


def diff_dimensions(reference: Dict[str, Any], actual: Dict[str, Any],
                    landed: Dict[str, bool]) -> Dict[str, str]:
    """Per-dimension verdict: kept / lost / n-a."""
    out: Dict[str, str] = {}
    out["cut"] = "kept" if reference["cut"] == actual["cut"] else "lost"
    if out["cut"] == "lost" and len(reference["cut"]) == len(actual["cut"]):
        drifted = [k for k in ("start", "duration", "left_offset")
                   if any(a[k] != b[k] for a, b in zip(reference["cut"], actual["cut"]))]
        out["cut"] = "lost:" + ",".join(drifted) if drifted else "lost:source"
    out["tracks"] = "kept" if reference["tracks"] == actual["tracks"] else (
        f"lost:{actual['tracks']['video']}v{actual['tracks']['audio']}a"
        f"!={reference['tracks']['video']}v{reference['tracks']['audio']}a")
    out["linkage"] = "kept" if actual["linkage"]["offline"] == 0 else \
        f"offline:{actual['linkage']['offline']}"
    for dim in ("transform", "colour", "flags", "markers", "timeline_markers"):
        if not landed.get(dim, True):
            out[dim] = "n/a"          # never set on the reference; nothing to lose
            continue
        if dim == "transform":
            out[dim] = _diff_transform(reference[dim], actual[dim])
        else:
            out[dim] = "kept" if reference[dim] == actual[dim] else "lost"
    return out


def run(mode: str, out: Path) -> int:
    observed = rr.runtime_mode()
    if observed["running"] and bool(observed["headless"]) != (mode == "headless"):
        print(f"REFUSE: Resolve running in the other mode: {observed['command_lines']}",
              file=sys.stderr)
        return 1
    resolve = connect()
    if resolve is None:
        print("REFUSE: no healthy Resolve.", file=sys.stderr)
        return 2

    rt = RichRoundTrip(resolve)
    report: Dict[str, Any] = {"metadata": {
        "mode": mode, "headless": observed["headless"],
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": resolve.GetVersionString()}, "formats": {}}
    try:
        setup = rt.setup()
        report["setup"] = setup
        reference, landed = setup["reference"], setup["dimensions_landed"]
        print(f"reference: {len(reference['cut'])} video items, "
              f"{reference['tracks']['video']}v{reference['tracks']['audio']}a, "
              f"dimensions landed: {[k for k, v in landed.items() if v]}", flush=True)
        for label, type_attr, sub_attr, ext in FORMATS:
            entry = {"export": rt.export(label, type_attr, sub_attr, ext)}
            if entry["export"].get("exported") and entry["export"].get("bytes"):
                outcome = rt.reimport(label, Path(entry["export"]["import_path"]), "a")
                entry["import"] = outcome
                if outcome.get("imported"):
                    entry["dimensions"] = diff_dimensions(reference, outcome["described"], landed)
                    summary = " ".join(f"{k}={v}" for k, v in entry["dimensions"].items())
                    print(f"  {label:12} {summary}", flush=True)
                else:
                    print(f"  {label:12} IMPORT FAILED {outcome}", flush=True)
            else:
                print(f"  {label:12} EXPORT FAILED {entry['export']}", flush=True)
            report["formats"][label] = entry
    finally:
        report["teardown"] = rt.teardown()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"report: {out}")
    return 0


def compare(gui_path: Path, headless_path: Path, out: Optional[Path]) -> int:
    gui, headless = json.loads(gui_path.read_text(encoding="utf-8")), json.loads(headless_path.read_text(encoding="utf-8"))
    assert gui["metadata"]["headless"] is False and headless["metadata"]["headless"] is True
    lines = ["# Complex-cut round trip: what each format keeps", "",
             "Two video tracks, audio, a per-item transform, clip colours, flags, item and "
             "timeline markers. `kept` = identical to the reference; `n/a` = the API would not "
             "set that dimension, so no format can be blamed for losing it.", ""]
    header = "| format | mode | " + " | ".join(DIMENSIONS) + " |"
    lines += [header, "| " + " --- |" * (len(DIMENSIONS) + 2)]
    for label, *_ in FORMATS:
        for tag, report in (("gui", gui), ("headless", headless)):
            entry = report["formats"].get(label, {})
            dims = entry.get("dimensions")
            if not dims:
                state = "import-failed" if entry.get("export", {}).get("exported") else "export-failed"
                lines.append(f"| {label} | {tag} | " + " | ".join([state] * len(DIMENSIONS)) + " |")
            else:
                lines.append(f"| {label} | {tag} | " +
                             " | ".join(dims.get(d, "?") for d in DIMENSIONS) + " |")
    text = "\n".join(lines) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--mode", choices=("gui", "headless"), required=True)
    r.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare")
    c.add_argument("gui", type=Path)
    c.add_argument("headless", type=Path)
    c.add_argument("--out", type=Path)
    args = parser.parse_args()
    return run(args.mode, args.out) if args.command == "run" else \
        compare(args.gui, args.headless, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
