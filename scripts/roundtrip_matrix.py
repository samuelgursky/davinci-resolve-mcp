#!/usr/bin/env python3
"""Which interchange format survives an export/import round trip, in which mode.

    python scripts/roundtrip_matrix.py run --mode gui      --out rt_gui.json
    python scripts/roundtrip_matrix.py run --mode headless --out rt_headless.json
    python scripts/roundtrip_matrix.py compare rt_gui.json rt_headless.json

The question this answers is not "does export work" — the probe matrix already
says every format writes a non-empty file in both modes. It is the one an
iterative edit loop actually depends on: **if I export a cut and import it back,
do I get the same cut, with its media still linked?**

That is a different and much stricter test. An export that writes 22 KB of valid
XML and re-imports as a timeline with the right number of clips at the wrong
source timecodes is worse than one that fails outright, because it looks like it
worked.

## What "the same cut" means here

Each timeline is reduced to a fingerprint: for every item, its record start, its
duration, and its **left offset** — the source in-point. Left offset is the part
that matters and the part that silently drifts; a conform that lands every clip
one frame off is the classic failure, and clip counts alone will never show it.

Media linkage is measured separately, because a timeline can rebuild perfectly
and arrive fully offline. Both are recorded: `structure_matches` and `linked`.

## Two ways to link, both tested

`ImportTimelineFromFile` can either re-import the source clips from disk
(`importSourceClips: True`, optionally with `sourceClipsPath`) or reuse what is
already in the media pool (`importSourceClips: False` with `sourceClipsFolders`).
An agent building edits iteratively wants the second — it should not duplicate
its media pool on every iteration — so both are measured rather than assumed.

DRT is special-cased throughout: Blackmagic's own documentation says
`timelineName`, `importSourceClips` and `sourceClipsFolders` are all invalid for
DRT import, so it is imported bare.
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

#: Stable, outside any per-run temp dir, so both modes import byte-identical
#: media from the same absolute paths. A path that differs between modes would
#: make relinking differences unattributable.
MEDIA_DIR = Path.home() / "Movies" / "resolve_roundtrip_fixture"

#: (label, export_type_attr, export_subtype_attr, extension)
FORMATS = [
    ("drt", "EXPORT_DRT", "EXPORT_NONE", "drt"),
    ("fcpxml_1_10", "EXPORT_FCPXML_1_10", "EXPORT_NONE", "fcpxml"),
    ("fcp7xml", "EXPORT_FCP_7_XML", "EXPORT_NONE", "xml"),
    ("aaf", "EXPORT_AAF", "EXPORT_AAF_NEW", "aaf"),
    ("otio", "EXPORT_OTIO", "EXPORT_NONE", "otio"),
    ("edl", "EXPORT_EDL", "EXPORT_NONE", "edl"),
]

#: How to resolve media on import. "reuse_pool" is what an iterative loop wants.
STRATEGIES = ("reuse_pool", "import_source")


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


def build_media() -> List[Path]:
    """Two distinguishable clips, generated once and reused across runs."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    clips = []
    for index, pattern in enumerate(("testsrc2", "smptebars"), start=1):
        clip = MEDIA_DIR / f"rt_source_{index}.mov"
        if not clip.exists() or clip.stat().st_size == 0:
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", f"{pattern}=size=1920x1080:rate=24:duration=8",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=8",
                 "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
                 "-timecode", "01:00:00:00", "-y", str(clip)],
                check=True, timeout=300,
            )
        clips.append(clip)
    return clips


def fingerprint(timeline: Any) -> List[Dict[str, Any]]:
    """Structure of a timeline, in the terms a conform actually cares about.

    `left_offset` is the source in-point. It is included because it is the value
    that drifts silently: a round trip can return the right number of clips, at
    the right places, cut from the wrong part of the source, and only this shows
    it.
    """
    out: List[Dict[str, Any]] = []
    for track in range(1, (timeline.GetTrackCount("video") or 0) + 1):
        for index, item in enumerate(timeline.GetItemListInTrack("video", track) or []):
            try:
                pool_item = item.GetMediaPoolItem()
                source = Path(pool_item.GetClipProperty("File Path")).name if pool_item else None
            except Exception:
                source = None
            out.append({
                "track": track,
                "index": index,
                "start": item.GetStart(),
                "duration": item.GetDuration(),
                "left_offset": item.GetLeftOffset(),
                "source": source,
            })
    return out


def linkage(timeline: Any) -> Dict[str, int]:
    """How many items still point at a real file on disk."""
    linked = offline = 0
    for track in range(1, (timeline.GetTrackCount("video") or 0) + 1):
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
    return {"linked": linked, "offline": offline}


class RoundTrip:
    def __init__(self, resolve: Any, work: Path) -> None:
        self.resolve = resolve
        self.pm = resolve.GetProjectManager()
        self.work = work
        self.project_name = f"ROUNDTRIP_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.project: Any = None
        self.pool: Any = None
        self.reference: Any = None
        self.incumbent: Optional[str] = None

    def setup(self) -> Dict[str, Any]:
        incumbent = self.pm.GetCurrentProject()
        self.incumbent = incumbent.GetName() if incumbent else None
        save_project_if_safe(self.pm)
        if not self.pm.CreateProject(self.project_name):
            raise RuntimeError("could not create the round-trip project")
        self.pm.LoadProject(self.project_name)
        self.project = self.pm.GetCurrentProject()
        self.pool = self.project.GetMediaPool()

        media = build_media()
        clips = self.resolve.GetMediaStorage().AddItemListToMediaPool([str(p) for p in media]) or []
        if len(clips) < 2:
            raise RuntimeError(f"expected 2 clips imported, got {len(clips)}")

        # A deliberately non-trivial cut: full clips AND trimmed subclips, so a
        # round trip that only preserves clip order still fails the comparison.
        frames = int(clips[0].GetClipProperty("Frames") or 0)
        plan = [
            {"mediaPoolItem": clips[0], "startFrame": 0, "endFrame": frames - 1},
            {"mediaPoolItem": clips[1], "startFrame": 24, "endFrame": 71},
            {"mediaPoolItem": clips[0], "startFrame": 48, "endFrame": 95},
            {"mediaPoolItem": clips[1], "startFrame": 0, "endFrame": frames - 1},
        ]
        self.reference = self.pool.CreateEmptyTimeline("RT_REFERENCE")
        if self.reference is None:
            raise RuntimeError("could not create the reference timeline")
        self.project.SetCurrentTimeline(self.reference)
        if not self.pool.AppendToTimeline(plan):
            raise RuntimeError("AppendToTimeline built nothing")
        return {
            "project": self.project_name,
            "media": [str(p) for p in media],
            "source_frames": frames,
            "reference_fingerprint": fingerprint(self.reference),
            "reference_linkage": linkage(self.reference),
        }

    def export(self, label: str, type_attr: str, sub_attr: str, ext: str) -> Dict[str, Any]:
        path = self.work / f"rt_{label}.{ext}"
        # Re-exporting onto a previous run's output silently mixes runs, and for
        # the bundle format below it would leave stale members behind.
        if path.is_dir():
            import shutil as _shutil
            _shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
        try:
            ok = self.reference.Export(str(path),
                                       getattr(self.resolve, type_attr),
                                       getattr(self.resolve, sub_attr))
        except Exception as exc:
            return {"exported": False, "error": f"{type(exc).__name__}: {exc}"}

        # FCPXML 1.10 does not write a file. It writes a *bundle directory* with
        # `Info.fcpxml` inside — the `.fcpxmld` shape Final Cut uses. So the
        # obvious `stat().st_size > 0` check reports 96 bytes of directory inode
        # and a re-import of the given path fails, which looks exactly like a
        # broken exporter and is not. Import has to be pointed at the member.
        bundle = path.is_dir()
        import_path = path
        member = None
        if bundle:
            members = sorted(path.glob("*.fcpxml")) or sorted(p for p in path.iterdir() if p.is_file())
            member = members[0] if members else None
            import_path = member or path
        return {
            "exported": bool(ok),
            "path": str(path),
            "import_path": str(import_path),
            "is_bundle": bundle,
            "bundle_member": str(member) if member else None,
            "bytes": (member.stat().st_size if member else 0) if bundle
                     else (path.stat().st_size if path.exists() else 0),
        }

    def reimport(self, label: str, path: Path, strategy: str) -> Dict[str, Any]:
        name = f"RT_{label}_{strategy}"
        if label == "drt":
            # Documented: timelineName / importSourceClips / sourceClipsFolders
            # are all invalid for DRT. Passing them anyway is a good way to get a
            # failure that says nothing about the format.
            options: Dict[str, Any] = {}
        elif strategy == "reuse_pool":
            options = {"timelineName": name, "importSourceClips": False,
                       "sourceClipsFolders": [self.pool.GetRootFolder()]}
        else:
            options = {"timelineName": name, "importSourceClips": True,
                       "sourceClipsPath": str(MEDIA_DIR)}

        started = time.monotonic()
        try:
            imported = self.pool.ImportTimelineFromFile(str(path), options) if options \
                else self.pool.ImportTimelineFromFile(str(path))
        except Exception as exc:
            return {"imported": False, "error": f"{type(exc).__name__}: {exc}",
                    "seconds": round(time.monotonic() - started, 1)}
        result: Dict[str, Any] = {
            "imported": bool(imported),
            "seconds": round(time.monotonic() - started, 1),
        }
        if not imported:
            return result
        result["name"] = imported.GetName()
        result["fingerprint"] = fingerprint(imported)
        result["linkage"] = linkage(imported)
        try:
            self.pool.DeleteTimelines([imported])
            result["cleaned"] = True
        except Exception:
            result["cleaned"] = False
        return result

    def teardown(self) -> Dict[str, Any]:
        notes: Dict[str, Any] = {}
        try:
            save_project_if_safe(self.pm)
            notes["closed"] = bool(self.pm.CloseProject(self.pm.GetCurrentProject()))
            if self.incumbent and self.incumbent != self.project_name:
                notes["restored"] = bool(self.pm.LoadProject(self.incumbent))
            notes["deleted"] = delete_project_safely(
                self.pm, self.project_name, switch_to=self.incumbent)["success"]
        except Exception as exc:
            notes["error"] = repr(exc)
        return notes


def compare_fingerprints(reference: List[Dict[str, Any]],
                         actual: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(reference) != len(actual):
        return {"structure_matches": False,
                "reason": f"item count {len(actual)} != reference {len(reference)}"}
    for expected, got in zip(reference, actual):
        for key in ("start", "duration", "left_offset"):
            if expected[key] != got[key]:
                return {
                    "structure_matches": False,
                    "reason": f"item {expected['index']} {key}: {got[key]} != {expected[key]}",
                    # The one that matters most, called out by name so it is not
                    # lost among count mismatches.
                    "frame_accurate": key != "left_offset",
                }
    return {"structure_matches": True}


def run(mode: str, out: Path) -> int:
    observed = rr.runtime_mode()
    if observed["running"] and bool(observed["headless"]) != (mode == "headless"):
        print(f"REFUSE: Resolve is running in the other mode: {observed['command_lines']}",
              file=sys.stderr)
        return 1
    resolve = connect()
    if resolve is None:
        print("REFUSE: no healthy Resolve.", file=sys.stderr)
        return 2

    work = MEDIA_DIR / "exports"
    work.mkdir(parents=True, exist_ok=True)
    rt = RoundTrip(resolve, work)
    report: Dict[str, Any] = {
        "metadata": {
            "mode": mode,
            "headless": observed["headless"],
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "version": resolve.GetVersionString(),
        },
        "formats": {},
    }
    try:
        setup = rt.setup()
        report["setup"] = setup
        reference = setup["reference_fingerprint"]
        print(f"reference: {len(reference)} items, "
              f"linkage={setup['reference_linkage']}", flush=True)

        for label, type_attr, sub_attr, ext in FORMATS:
            entry: Dict[str, Any] = {"export": rt.export(label, type_attr, sub_attr, ext)}
            if entry["export"].get("exported") and entry["export"].get("bytes"):
                path = Path(entry["export"]["import_path"])
                entry["imports"] = {}
                for strategy in (("reuse_pool",) if label == "drt" else STRATEGIES):
                    outcome = rt.reimport(label, path, strategy)
                    if outcome.get("imported") and outcome.get("fingerprint") is not None:
                        outcome.update(compare_fingerprints(reference, outcome["fingerprint"]))
                    entry["imports"][strategy] = outcome
                    flag = ("MATCH" if outcome.get("structure_matches")
                            else "import-failed" if not outcome.get("imported") else "MISMATCH")
                    link = outcome.get("linkage", {})
                    print(f"  {label:12} {strategy:14} {flag:14} "
                          f"linked={link.get('linked')} offline={link.get('offline')}", flush=True)
            else:
                print(f"  {label:12} export failed: {entry['export']}", flush=True)
            report["formats"][label] = entry
    finally:
        report["teardown"] = rt.teardown()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"report: {out}")
    return 0


def _verdict(entry: Dict[str, Any], strategy: str) -> str:
    imports = entry.get("imports") or {}
    outcome = imports.get(strategy)
    if not entry.get("export", {}).get("exported"):
        return "export-failed"
    if outcome is None:
        return "n/a"
    if not outcome.get("imported"):
        return "import-failed"
    if outcome.get("structure_matches"):
        link = outcome.get("linkage", {})
        return "exact" if link.get("offline", 0) == 0 else f"exact-but-{link.get('offline')}-offline"
    return "structure-drift"


def compare(gui_path: Path, headless_path: Path, out: Optional[Path]) -> int:
    gui = json.loads(gui_path.read_text())
    headless = json.loads(headless_path.read_text())
    assert gui["metadata"]["headless"] is False, f"{gui_path} is not a GUI run"
    assert headless["metadata"]["headless"] is True, f"{headless_path} is not a headless run"

    lines = ["# Timeline round-trip fidelity: export, re-import, compare", "",
             "`exact` = every item's record start, duration and **source in-point** survived, "
             "with all media linked. Anything else is unusable for an iterative edit loop.", "",
             "| format | link strategy | GUI | headless |", "| --- | --- | --- | --- |"]
    for label, *_ in FORMATS:
        for strategy in (("reuse_pool",) if label == "drt" else STRATEGIES):
            lines.append(f"| {label} | {strategy} | "
                         f"{_verdict(gui['formats'].get(label, {}), strategy)} | "
                         f"{_verdict(headless['formats'].get(label, {}), strategy)} |")
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
    if args.command == "run":
        return run(args.mode, args.out)
    return compare(args.gui, args.headless, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
