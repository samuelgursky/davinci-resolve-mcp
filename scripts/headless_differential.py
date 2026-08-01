#!/usr/bin/env python3
"""Record and difference a Resolve session's capabilities with and without a UI.

    # 1. with the GUI up, establish the baseline
    python scripts/headless_differential.py record --label gui --out /tmp/gui.json

    # 2. quit Resolve, boot it headless, record again
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve" -nogui &
    python scripts/headless_differential.py record --label headless --out /tmp/headless.json

    # 3. difference them
    python scripts/headless_differential.py compare /tmp/gui.json /tmp/headless.json \
        --out docs/reference/headless-capability-matrix.md

`record` creates a disposable project, imports two seconds of ffmpeg-generated
colour bars, exercises the surfaces that plausibly depend on a UI, then deletes
the project and its media. It never touches an existing project — but it does
open and close one, so do not run it against a Resolve that has unsaved work.

The scenarios are deliberately hand-written rather than enumerated. A generated
call list cannot set up a Gallery album, wait on a render, or clean up a Fusion
comp, and those are precisely the surfaces where the UI turns out to matter.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import bridge_differential as bd  # noqa: E402
from src.utils import headless_differential as hd  # noqa: E402
from src.utils.project_cleanup import save_project_if_safe  # noqa: E402

PAGES = ("media", "cut", "edit", "fusion", "color", "fairlight", "deliver")


# ── connection ───────────────────────────────────────────────────────────────


def connect() -> Any:
    """Blackmagic's own module, with the in-app bridge deliberately out of the way.

    The bridge runs *inside* Resolve's own interpreter, so a bridged call could
    never observe a headless difference the same way an external one does. This
    study is about external scripting, which is the transport every agent uses.
    """
    os.environ.pop("DAVINCI_RESOLVE_BRIDGE", None)
    api = os.environ.get(
        "RESOLVE_SCRIPT_API",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
    )
    modules = str(Path(api) / "Modules")
    if modules not in sys.path:
        sys.path.append(modules)
    os.environ.setdefault("RESOLVE_SCRIPT_API", api)
    os.environ.setdefault(
        "RESOLVE_SCRIPT_LIB",
        "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
    )
    import DaVinciResolveScript as dvr  # noqa: E402

    return dvr.scriptapp("Resolve")


def wait_for_project_manager(resolve: Any, timeout: float = 60.0) -> Any:
    """`scriptapp()` answers before the ProjectManager is usable.

    Verified during the E051 sessions and again here: a fresh headless boot hands
    back a live `resolve` handle whose `GetProjectManager()` returns an object
    that is not yet answering. Calling straight through gets None or a stall, and
    the resulting "headless cannot list projects" would be a harness artefact
    rather than a finding.
    """
    deadline = time.monotonic() + timeout
    last: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            pm = resolve.GetProjectManager()
            if pm is not None and pm.GetProjectListInCurrentFolder() is not None:
                return pm
        except Exception as exc:  # pragma: no cover - live-only path
            last = exc
        time.sleep(1.0)
    raise RuntimeError(f"ProjectManager not ready within {timeout}s (last error: {last!r})")


# ── fixture ──────────────────────────────────────────────────────────────────


def make_media(work_dir: Path) -> Path:
    clip = work_dir / "headless_probe_source.mov"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
            "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
            "-y", str(clip),
        ],
        check=True,
        timeout=120,
    )
    return clip


class Fixture:
    """A disposable project with one clip on one timeline."""

    def __init__(self, resolve: Any, work_dir: Path, stamp: str) -> None:
        self.resolve = resolve
        self.work_dir = work_dir
        self.name = f"HEADLESS_PROBE_{stamp}"
        self.pm = wait_for_project_manager(resolve)
        self.project: Any = None
        self.timeline: Any = None
        self.item: Any = None
        self.clip: Any = None
        self.incumbent: Optional[str] = None

    def build(self) -> Dict[str, Any]:
        notes: Dict[str, Any] = {}
        # Loading the scratch project closes whatever is open, and closing an
        # unsaved project in the GUI raises a modal that no script can dismiss —
        # which wedges the run *and* the application. Saving first is not
        # politeness, it is the only way this harness can be safe to point at a
        # live session.
        incumbent = self.pm.GetCurrentProject()
        if incumbent is not None:
            # SaveProject lives on ProjectManager, not Project — one of the
            # "methods live on objects you wouldn't expect" cases the api_truth
            # ledger exists for.
            self.incumbent = incumbent.GetName()
            notes["incumbent_name"] = self.incumbent
            notes["saved_incumbent"] = save_project_if_safe(self.pm)
        self.project = self.pm.CreateProject(self.name)
        notes["created_project"] = bool(self.project)
        if not self.project:
            raise RuntimeError(f"could not create scratch project {self.name}")
        # CreateProject does not load what it created — verified previously, and
        # every import after it would otherwise land in whatever project was
        # already open. That is a destructive harness bug, not a probe result.
        self.pm.LoadProject(self.name)
        self.project = self.pm.GetCurrentProject()
        notes["loaded_project"] = self.project.GetName() == self.name

        media_path = make_media(self.work_dir)
        pool = self.project.GetMediaPool()
        storage = self.resolve.GetMediaStorage()
        imported = storage.AddItemListToMediaPool([str(media_path)]) or []
        notes["imported_clips"] = len(imported)
        self.clip = imported[0] if imported else None
        if self.clip is None:
            raise RuntimeError("media import produced no clips")

        self.timeline = pool.CreateTimelineFromClips("PROBE_TL", [self.clip])
        notes["created_timeline"] = bool(self.timeline)
        if self.timeline:
            self.project.SetCurrentTimeline(self.timeline)
            items = self.timeline.GetItemListInTrack("video", 1) or []
            self.item = items[0] if items else None
        notes["timeline_item"] = bool(self.item)
        return notes

    def teardown(self) -> Dict[str, Any]:
        """Hand the session back on a *named* project, never on the fallback.

        Closing the scratch project drops Resolve onto a fresh, never-saved
        `Untitled Project`. That project cannot be saved — `SaveProject()`
        returns False for it — so the next close or switch raises a modal the
        user has to dismiss by hand. This harness did that to a live GUI session:
        it finished cleanly and left the application prompting.

        Loading the incumbent *first* closes the scratch project (just saved, so
        silent) and never rests on the fallback at all. Delete afterwards, when
        nothing is holding it.
        """
        notes: Dict[str, Any] = {}
        try:
            save_project_if_safe(self.pm)
            # CloseProject first: it releases the session lock, and switching
            # away with LoadProject does not — measured, DeleteProject then
            # returns False no matter how often it is retried.
            notes["closed"] = bool(self.pm.CloseProject(self.project))
            # Then land on a named project, so the session is not left on the
            # unsaveable `Untitled Project` fallback.
            if self.incumbent and self.incumbent != self.name:
                notes["restored_incumbent"] = bool(self.pm.LoadProject(self.incumbent))
        except Exception as exc:
            notes["close_error"] = repr(exc)
        try:
            notes["deleted"] = bool(self.pm.DeleteProject(self.name))
        except Exception as exc:
            notes["delete_error"] = repr(exc)
        return notes


# ── scenarios ────────────────────────────────────────────────────────────────
#
# Each takes the fixture and an `out` dict it fills in. Keys become matrix rows,
# so they are named for what was observed rather than for the call that produced
# it.
#
# `out` is passed in rather than returned so that a scenario which dies halfway
# keeps what it already learned. Returning a dict looked tidier until the colour
# scenario raised on its third call and discarded all three observations,
# reporting as a single opaque error — a silent coverage hole in exactly the
# tool this module exists to close.

Scenario = Callable[[Fixture, Dict[str, Any]], None]
SCENARIOS: Dict[str, Scenario] = {}


def scenario(name: str) -> Callable[[Scenario], Scenario]:
    def register(fn: Scenario) -> Scenario:
        SCENARIOS[name] = fn
        return fn

    return register


@scenario("pages")
def scenario_pages(fx: Fixture, out: Dict[str, Any]) -> None:
    """Page navigation — the most obviously UI-shaped call in the API.

    Worth measuring rather than assuming: several tools call `OpenPage` as a
    precondition for something else (Gallery grabs want Color, render wants
    Deliver), so whether it *reports* success headless decides whether those
    tools fail loudly or proceed on a false premise.
    """
    for page in PAGES:
        out[f"open_{page}"] = fx.resolve.OpenPage(page)
        out[f"reads_back_{page}"] = fx.resolve.GetCurrentPage()


@scenario("gallery")
def scenario_gallery(fx: Fixture, out: Dict[str, Any]) -> None:
    """Still grab and export — the known headless failure, now measured.

    A 2026-07-03 design note recorded `ExportStills` and `export_frame_as_still`
    as headless-only failures, confirmed by re-testing in the GUI. That finding
    lived in `local/design/` where no agent reads it.
    """
    fx.resolve.OpenPage("color")
    gallery = fx.project.GetGallery()
    out["gallery_handle"] = bool(gallery)
    if not gallery:
        return
    album = gallery.GetCurrentStillAlbum()
    out["current_album"] = bool(album)
    out["album_count"] = len(gallery.GetGalleryStillAlbums() or [])

    still = fx.timeline.GrabStill()
    out["grab_still"] = bool(still)
    if still and album:
        export_dir = fx.work_dir / "stills"
        export_dir.mkdir(exist_ok=True)
        out["export_stills"] = album.ExportStills([still], str(export_dir), "probe", "jpg")
        produced = sorted(p.name for p in export_dir.glob("probe*"))
        # The boolean and the filesystem disagree in at least one mode, which is
        # the entire point of checking both.
        out["export_produced_files"] = len(produced)
        album.DeleteStills([still])


@scenario("frame_export")
def scenario_frame_export(fx: Fixture, out: Dict[str, Any]) -> None:
    """`ExportCurrentFrameAsStill` — the other half of the 2026-07-03 note."""
    target = fx.work_dir / "current_frame.png"
    out["export_current_frame"] = fx.project.ExportCurrentFrameAsStill(str(target))
    out["frame_file_written"] = target.exists() and target.stat().st_size > 0


@scenario("fusion")
def scenario_fusion(fx: Fixture, out: Dict[str, Any]) -> None:
    """Fusion access, both the app-level object and a clip-level comp."""
    fusion = fx.resolve.Fusion()
    out["fusion_handle"] = bool(fusion)
    if fusion:
        # GetCurrentComp is the entry point every Fusion tool needs; without it
        # the whole fusion_comp tool family is unreachable.
        try:
            comp = fusion.GetCurrentComp()
            out["current_comp"] = bool(comp)
        except Exception as exc:
            out["current_comp"] = f"error: {type(exc).__name__}"
    if fx.item:
        out["comp_count_before"] = fx.item.GetFusionCompCount()
        added = fx.item.AddFusionComp()
        out["add_fusion_comp"] = bool(added)
        out["comp_count_after"] = fx.item.GetFusionCompCount()
        names = fx.item.GetFusionCompNameList() or []
        out["comp_names"] = len(names)
        if added and names:
            out["delete_fusion_comp"] = fx.item.DeleteFusionCompByName(names[-1])


@scenario("color")
def scenario_color(fx: Fixture, out: Dict[str, Any]) -> None:
    """Grading surface — node graph reads plus a colour-group round trip."""
    if not fx.item:
        return
    graph = fx.item.GetNodeGraph()
    out["node_graph"] = bool(graph)
    if graph:
        out["num_nodes"] = graph.GetNumNodes()
        # Graph exposes GetNodeLabel with no SetNodeLabel beside it — a genuine
        # read/write asymmetry, not an omission here.
        out["read_node_label"] = graph.GetNodeLabel(1)
        out["read_node_lut"] = graph.GetLUT(1)
        out["tools_in_node"] = len(graph.GetToolsInNode(1) or [])
        out["set_node_enabled"] = graph.SetNodeEnabled(1, True)
    group = fx.project.AddColorGroup("PROBE_GROUP")
    out["add_color_group"] = bool(group)
    if group:
        out["assign_to_group"] = fx.item.AssignToColorGroup(group)
        out["delete_color_group"] = fx.project.DeleteColorGroup(group)


@scenario("render")
def scenario_render(fx: Fixture, out: Dict[str, Any]) -> None:
    """Delivery end to end, to a real file.

    The whole reason anyone wants headless. A render that reports success and
    writes nothing is indistinguishable from one that worked until someone looks
    for the file, so both are recorded.
    """
    formats = fx.project.GetRenderFormats() or {}
    out["format_count"] = len(formats)
    codecs = fx.project.GetRenderCodecs("mp4") or {}
    out["codec_count_mp4"] = len(codecs)
    # GetRenderCodecs returns {description: id} and only the id is accepted —
    # feeding it the description shown in Deliver returns False for both ProRes
    # and H.264. Documented trap; using it here would report a known quirk as a
    # headless finding.
    codec_id = codecs.get("H.264") or next(iter(codecs.values()), None)
    out["set_format_codec"] = fx.project.SetCurrentRenderFormatAndCodec("mp4", codec_id) if codec_id else None

    target = fx.work_dir / "render"
    target.mkdir(exist_ok=True)
    out["set_render_settings"] = fx.project.SetRenderSettings(
        {"TargetDir": str(target), "CustomName": "probe_render", "SelectAllFrames": True}
    )
    job_id = fx.project.AddRenderJob()
    out["add_render_job"] = bool(job_id)
    if not job_id:
        return
    out["render_job_count"] = len(fx.project.GetRenderJobList() or [])
    out["start_rendering"] = fx.project.StartRendering(job_id, isInteractiveMode=False)
    deadline = time.monotonic() + 180
    while fx.project.IsRenderingInProgress() and time.monotonic() < deadline:
        time.sleep(1.0)
    status = fx.project.GetRenderJobStatus(job_id) or {}
    out["render_status"] = status.get("JobStatus")
    written = sorted(p for p in target.glob("probe_render*") if p.stat().st_size > 0)
    out["render_produced_files"] = len(written)
    out["delete_render_job"] = fx.project.DeleteRenderJob(job_id)


@scenario("timeline_export")
def scenario_timeline_export(fx: Fixture, out: Dict[str, Any]) -> None:
    """Interchange export — the conform pipeline's entire output side."""
    exports = {
        "aaf": (fx.resolve.EXPORT_AAF, fx.resolve.EXPORT_AAF_NEW),
        "edl": (fx.resolve.EXPORT_EDL, fx.resolve.EXPORT_NONE),
        "fcpxml": (fx.resolve.EXPORT_FCP_7_XML, fx.resolve.EXPORT_NONE),
        "drt": (fx.resolve.EXPORT_DRT, fx.resolve.EXPORT_NONE),
        "otio": (fx.resolve.EXPORT_OTIO, fx.resolve.EXPORT_NONE),
    }
    for label, (export_type, subtype) in exports.items():
        path = fx.work_dir / f"probe_export.{label}"
        try:
            out[f"export_{label}"] = fx.timeline.Export(str(path), export_type, subtype)
            out[f"export_{label}_bytes"] = path.stat().st_size if path.exists() else 0
        except Exception as exc:
            out[f"export_{label}"] = f"error: {type(exc).__name__}"


@scenario("layout_presets")
def scenario_layout_presets(fx: Fixture, out: Dict[str, Any]) -> None:
    """UI layout presets — a surface that has no meaning without a UI.

    Included precisely because it *should* fail headless. A probe set that only
    contains things expected to pass cannot tell a working differential from a
    broken one.
    """
    out["save_layout_preset"] = fx.resolve.SaveLayoutPreset("PROBE_LAYOUT")
    export_path = fx.work_dir / "probe_layout.preset"
    out["export_layout_preset"] = fx.resolve.ExportLayoutPreset("PROBE_LAYOUT", str(export_path))
    out["layout_preset_bytes"] = export_path.stat().st_size if export_path.exists() else 0
    out["load_layout_preset"] = fx.resolve.LoadLayoutPreset("PROBE_LAYOUT")
    out["delete_layout_preset"] = fx.resolve.DeleteLayoutPreset("PROBE_LAYOUT")


@scenario("timeline_edit")
def scenario_timeline_edit(fx: Fixture, out: Dict[str, Any]) -> None:
    """Ordinary editorial writes — the bulk of what the MCP tools do."""
    out["add_marker"] = fx.timeline.AddMarker(1, "Blue", "PROBE", "probe note", 1)
    markers = fx.timeline.GetMarkers() or {}
    out["marker_count"] = len(markers)
    out["delete_marker"] = fx.timeline.DeleteMarkerAtFrame(1)
    out["track_count_video"] = fx.timeline.GetTrackCount("video")
    out["add_track"] = fx.timeline.AddTrack("video")
    out["track_count_after_add"] = fx.timeline.GetTrackCount("video")
    out["delete_track"] = fx.timeline.DeleteTrack("video", fx.timeline.GetTrackCount("video"))
    out["set_track_name"] = fx.timeline.SetTrackName("video", 1, "PROBE_TRACK")
    out["read_track_name"] = fx.timeline.GetTrackName("video", 1)
    if fx.item:
        out["set_zoom"] = fx.item.SetProperty("ZoomX", 1.25)
        out["read_zoom"] = fx.item.GetProperty("ZoomX")


@scenario("playhead")
def scenario_playhead(fx: Fixture, out: Dict[str, Any]) -> None:
    """Playhead control — GUI-coupled in a way that has bitten frame exports."""
    start = fx.timeline.GetStartTimecode()
    out["start_timecode_shape"] = type(start).__name__
    out["set_current_timecode"] = fx.timeline.SetCurrentTimecode(start)
    out["current_timecode"] = fx.timeline.GetCurrentTimecode()
    out["current_video_item"] = bool(fx.timeline.GetCurrentVideoItem())


@scenario("project_settings")
def scenario_project_settings(fx: Fixture, out: Dict[str, Any]) -> None:
    out["read_frame_rate"] = fx.project.GetSetting("timelineFrameRate")
    out["set_output_res"] = fx.project.SetSetting("timelineResolutionWidth", "1920")
    out["read_output_res"] = fx.project.GetSetting("timelineResolutionWidth")
    out["setting_count"] = len(fx.project.GetSetting() or {})


@scenario("media_pool")
def scenario_media_pool(fx: Fixture, out: Dict[str, Any]) -> None:
    pool = fx.project.GetMediaPool()
    root = pool.GetRootFolder()
    out["root_folder"] = bool(root)
    out["clip_count"] = len(root.GetClipList() or []) if root else 0
    folder = pool.AddSubFolder(root, "PROBE_BIN")
    out["add_subfolder"] = bool(folder)
    out["set_current_folder"] = pool.SetCurrentFolder(folder) if folder else None
    if folder:
        out["delete_subfolder"] = pool.DeleteFolders([folder])
    storage = fx.resolve.GetMediaStorage()
    out["mounted_volume_count"] = len(storage.GetMountedVolumeList() or [])
    if fx.clip:
        out["clip_property_resolution"] = fx.clip.GetClipProperty("Resolution")
        out["set_clip_color"] = fx.clip.SetClipColor("Orange")


# ── recording ────────────────────────────────────────────────────────────────


def resolve_process_argv() -> List[str]:
    """How the running Resolve was actually started.

    Recorded rather than assumed: the difference between the two runs is only
    attributable to `-nogui` if `-nogui` is genuinely the difference, and a
    lingering render-node instance has silently supplied the answer before.
    """
    try:
        out = subprocess.run(["ps", "-Ao", "pid=,command="], capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines():
            if "DaVinci Resolve.app/Contents/MacOS/Resolve" in line:
                return line.split()
    except Exception:
        pass
    return []


def record(label: str, out_path: Path, only: Optional[List[str]]) -> Dict[str, Any]:
    started = time.monotonic()
    resolve = connect()
    if resolve is None:
        raise SystemExit(
            "No Resolve answered the scripting API. Start it (or start it with -nogui) first."
        )
    argv = resolve_process_argv()
    metadata = {
        "label": label,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": resolve.GetVersionString(),
        "product": resolve.GetProductName(),
        "process_argv": argv,
        "nogui_in_argv": "-nogui" in argv,
        "connect_seconds": round(time.monotonic() - started, 2),
    }
    # A label that contradicts the process it connected to makes every downstream
    # verdict wrong, and is far easier to do by accident than to notice later.
    if label == "headless" and not metadata["nogui_in_argv"]:
        raise SystemExit("--label headless but the running Resolve has no -nogui in its argv")
    if label == "gui" and metadata["nogui_in_argv"]:
        raise SystemExit("--label gui but the running Resolve was started with -nogui")

    work_dir = Path(tempfile.mkdtemp(prefix=f"headless_probe_{label}_"))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scenarios: Dict[str, Any] = {}
    surface: Dict[str, Any] = {}
    fixture: Optional[Fixture] = None
    try:
        fixture = Fixture(resolve, work_dir, stamp)
        scenarios["fixture"] = fixture.build()
        # The read-only surface walks outwards from the *current* project and
        # timeline, so it has to run after the fixture exists. Probing whatever
        # project happened to be open would compare a GUI run against the user's
        # session and a headless run against nothing, and report the difference
        # between two projects as the difference between two modes.
        surface_plan = bd.probe_surface()
        metadata["surface_methods"] = len(surface_plan["safe_to_probe"])
        surface = bd.run_probes(resolve, surface_plan["safe_to_probe"])
        for name, fn in SCENARIOS.items():
            if only and name not in only:
                continue
            observations: Dict[str, Any] = {}
            scenarios[name] = observations
            try:
                fn(fixture, observations)
            except Exception as exc:
                # A scenario that raises is a finding, not a crash: the exception
                # type is exactly what differs between modes for some surfaces.
                # Whatever it recorded before dying is already in `observations`.
                observations["scenario_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if fixture is not None:
            scenarios["teardown"] = fixture.teardown()
        shutil.rmtree(work_dir, ignore_errors=True)

    metadata["elapsed_seconds"] = round(time.monotonic() - started, 2)
    report = {"metadata": metadata, "surface": surface, "scenarios": scenarios}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="record one mode")
    rec.add_argument("--label", choices=("gui", "headless"), required=True)
    rec.add_argument("--out", type=Path, required=True)
    rec.add_argument("--only", nargs="*", help="restrict to named scenarios")

    cmp_ = sub.add_parser("compare", help="difference two recordings")
    cmp_.add_argument("gui", type=Path)
    cmp_.add_argument("headless", type=Path)
    cmp_.add_argument("--out", type=Path)

    args = parser.parse_args()

    if args.command == "record":
        report = record(args.label, args.out, args.only)
        counts = {k: len(v) if isinstance(v, dict) else 1 for k, v in report["scenarios"].items()}
        print(json.dumps({"metadata": report["metadata"], "scenario_observations": counts}, indent=2))
        return 0

    gui = json.loads(args.gui.read_text(encoding="utf-8"))
    headless = json.loads(args.headless.read_text(encoding="utf-8"))
    matrix = hd.build_matrix(gui, headless)
    markdown = hd.render_matrix_markdown(matrix)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
        args.out.with_suffix(".json").write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
