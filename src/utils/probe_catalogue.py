"""What to probe in each mode, as data.

Ordered so that cheap read-only probes run first and the destructive ones last.
Within a worker run the order is stable, which is what lets the supervisor
identify a hung probe by position: results stream in order, so the first missing
one was in flight.

Two conventions worth knowing before adding probes:

**State is part of the probe.** `SaveProject` is harmless on a named project and
hangs forever headless on the never-saved `Untitled Project`. A catalogue that
only ever ran calls against a well-formed scratch project would have missed it —
the first differential did exactly that and reported no differences at all. So
probes declare `state="untitled"` when they need Resolve sitting on its default
project, and the worker arranges it.

**Timeouts are per probe.** A render needs minutes; a getter needs seconds.
Giving everything the same generous timeout means a hung getter costs minutes of
wall clock, and giving everything a short one turns a slow render into a false
hang.
"""

from __future__ import annotations

from typing import Any, List

from src.utils.mode_matrix import Probe
from .resolve_writes import set_current_timeline, describe_switch_failure

CATALOGUE: List[Probe] = []

#: Bumped whenever a probe's *body* changes meaning. Results from different
#: catalogue versions must not be compared: the `combine()` fix changed a failed
#: export from `ok:'False/0'` to `false:False`, and comparing runs across that
#: change made one probe look flaky within a mode when it had simply been
#: recorded two ways. The fingerprint below makes that mistake refuse rather
#: than mislead.
CATALOGUE_VERSION = 4


def combine(ok: Any, detail: Any) -> Any:
    """`False` when the call failed, otherwise a composite of call and evidence.

    Probes that returned `f"{ok}/{written}"` unconditionally reported outcome
    `ok`, because a non-empty string is a successful reading. `gallery.
    export_stills` therefore recorded `'False/0'` as a success and was compared
    as merely *divergent* from the GUI's `'True/2'` — burying a clean
    headless-only failure among value differences. The boolean has to survive
    into the outcome, not just into the text.
    """
    if ok is False or ok is None:
        return ok
    return f"{ok}/{detail}"


def probe(name: str, category: str, **kwargs: Any):
    def register(fn):
        CATALOGUE.append(Probe(name, category, fn, **kwargs))
        return fn
    return register


# ── app-level reads ──────────────────────────────────────────────────────────


@probe("app.product_name", "app", timeout=15)
def _probe_app_product_name(ctx): return ctx.resolve.GetProductName()


@probe("app.version_string", "app", timeout=15)
def _probe_app_version_string(ctx): return ctx.resolve.GetVersionString()


@probe("app.current_page", "app", timeout=15)
def _probe_app_current_page(ctx): return ctx.resolve.GetCurrentPage()


@probe("app.keyframe_mode", "app", timeout=15)
def _probe_app_keyframe_mode(ctx): return ctx.resolve.GetKeyframeMode()


@probe("app.fusion_handle", "app", timeout=20)
def _probe_app_fusion_handle(ctx): return bool(ctx.resolve.Fusion())


@probe("app.fusion_current_comp", "app", timeout=20)
def _probe_app_fusion_current_comp(ctx): return bool(ctx.resolve.Fusion().GetCurrentComp())


@probe("app.media_storage", "app", timeout=20)
def _probe_app_media_storage(ctx): return bool(ctx.resolve.GetMediaStorage())


@probe("app.mounted_volumes", "app", timeout=30)
def _probe_app_mounted_volumes(ctx): return len(ctx.resolve.GetMediaStorage().GetMountedVolumeList() or [])


# ── pages: every page, opened and read back ──────────────────────────────────

for _page in ("media", "cut", "edit", "fusion", "color", "fairlight", "deliver"):
    def _make(page):
        def body(ctx):
            ok = ctx.resolve.OpenPage(page)
            return f"{ok}/{ctx.resolve.GetCurrentPage()}"
        return body
    CATALOGUE.append(Probe(f"page.open_{_page}", "pages", _make(_page), timeout=25))


# ── project manager ──────────────────────────────────────────────────────────


@probe("pm.current_database", "project_manager", timeout=20)
def _probe_pm_current_database(ctx): return ctx.pm.GetCurrentDatabase()


@probe("pm.database_list", "project_manager", timeout=30)
def _probe_pm_database_list(ctx): return len(ctx.pm.GetDatabaseList() or [])


@probe("pm.project_list_count", "project_manager", timeout=60)
def _probe_pm_project_list_count(ctx): return len(ctx.pm.GetProjectListInCurrentFolder() or []) > 0


@probe("pm.folder_list", "project_manager", timeout=30)
def _probe_pm_folder_list(ctx): return isinstance(ctx.pm.GetFolderListInCurrentFolder(), list)


@probe("pm.current_folder", "project_manager", timeout=20)
def _probe_pm_current_folder(ctx): return ctx.pm.GetCurrentFolder()


#: The probe this whole harness exists for — and it is `blocking`, so it never
#: runs in a sweep unless named explicitly.
#:
#: Measured twice on 2026-08-01, and the second measurement corrected the first.
#: It does not merely hang the calling client: it blocks the ENTIRE application,
#: in the GUI as well as headless. A fresh client opened while it was pending got
#: no answer either. So this is not "GUI returns False, headless hangs" — it is a
#: modal that stops everything, visible and clickable with a UI, invisible and
#: unclearable without one.
#:
#: (An earlier run did see it return False immediately on an unmodified default
#: project, so some condition distinguishes the two behaviours. That condition is
#: not yet established, which is itself a reason to keep this out of sweeps.)
@probe("pm.save_untitled_project", "project_manager", timeout=45, state="untitled",
       blocking=True,
       note="BLOCKS THE WHOLE APP in both modes; needs a force-kill to clear")
def _probe_pm_save_untitled_project(ctx): return ctx.pm.SaveProject()


@probe("pm.save_named_project", "project_manager", timeout=45, state="scratch",
       note="the control for save_untitled_project: must work in both modes")
def _probe_pm_save_named_project(ctx): return ctx.pm.SaveProject()


@probe("pm.current_project_name_on_untitled", "project_manager", timeout=20, state="untitled")
def _probe_pm_current_project_name_on_untitled(ctx): return ctx.pm.GetCurrentProject().GetName()


@probe("pm.export_project", "project_manager", timeout=120, destructive=True)
def _probe_pm_export_project(ctx):
    target = ctx.work / "exported.drp"
    ok = ctx.pm.ExportProject(ctx.project_name, str(target))
    return combine(ok, target.exists() and target.stat().st_size > 0)


# ── project settings ─────────────────────────────────────────────────────────


@probe("project.setting_count", "project_settings", timeout=30, needs=("project",))
def _probe_project_setting_count(ctx): return len(ctx.project.GetSetting() or {}) > 0


@probe("project.read_frame_rate", "project_settings", timeout=20, needs=("project",))
def _probe_project_read_frame_rate(ctx): return ctx.project.GetSetting("timelineFrameRate")


@probe("project.set_resolution", "project_settings", timeout=25, needs=("project",))
def _probe_project_set_resolution(ctx):
    ok = ctx.project.SetSetting("timelineResolutionWidth", "1920")
    return f"{ok}/{ctx.project.GetSetting('timelineResolutionWidth')}"


@probe("project.set_colour_science", "project_settings", timeout=30, needs=("project",))
def _probe_project_set_colour_science(ctx):
    ok = ctx.project.SetSetting("colorScienceMode", "davinciYRGB")
    return f"{ok}/{ctx.project.GetSetting('colorScienceMode')}"


@probe("project.unique_id_shape", "project_settings", timeout=20, needs=("project",))
def _probe_project_unique_id_shape(ctx): return type(ctx.project.GetUniqueId()).__name__


# ── media pool ───────────────────────────────────────────────────────────────


@probe("pool.root_folder", "media_pool", timeout=25, needs=("project",))
def _probe_pool_root_folder(ctx): return bool(ctx.project.GetMediaPool().GetRootFolder())


@probe("pool.clip_count", "media_pool", timeout=30, needs=("clip",))
def _probe_pool_clip_count(ctx): return len(ctx.project.GetMediaPool().GetRootFolder().GetClipList() or [])


@probe("pool.add_subfolder", "media_pool", timeout=30, needs=("project",), destructive=True)
def _probe_pool_add_subfolder(ctx):
    pool = ctx.project.GetMediaPool()
    folder = pool.AddSubFolder(pool.GetRootFolder(), "PROBE_BIN")
    if not folder:
        return False
    moved = pool.SetCurrentFolder(folder)
    pool.SetCurrentFolder(pool.GetRootFolder())
    pool.DeleteFolders([folder])
    return moved


@probe("pool.clip_resolution", "media_pool", timeout=25, needs=("clip",))
def _probe_pool_clip_resolution(ctx): return ctx.clip.GetClipProperty("Resolution")


@probe("pool.set_clip_color", "media_pool", timeout=25, needs=("clip",), destructive=True)
def _probe_pool_set_clip_color(ctx): return ctx.clip.SetClipColor("Orange")


@probe("pool.set_clip_metadata", "media_pool", timeout=25, needs=("clip",), destructive=True)
def _probe_pool_set_clip_metadata(ctx):
    ok = ctx.clip.SetMetadata("Comments", "probe")
    return f"{ok}/{ctx.clip.GetMetadata('Comments')}"


@probe("pool.clip_marker_roundtrip", "media_pool", timeout=30, needs=("clip",), destructive=True)
def _probe_pool_clip_marker_roundtrip(ctx):
    added = ctx.clip.AddMarker(1, "Blue", "PROBE", "note", 1)
    count = len(ctx.clip.GetMarkers() or {})
    ctx.clip.DeleteMarkerAtFrame(1)
    return f"{added}/{count}"


@probe("pool.append_to_timeline", "media_pool", timeout=60, needs=("clip", "timeline"), destructive=True)
def _probe_pool_append_to_timeline(ctx):
    pool = ctx.project.GetMediaPool()
    before = ctx.timeline.GetEndFrame()
    frames = int(ctx.clip.GetClipProperty("Frames") or 0)
    pool.AppendToTimeline([{"mediaPoolItem": ctx.clip, "startFrame": 0,
                            "endFrame": max(frames - 1, 0)}])
    return ctx.timeline.GetEndFrame() > before


# ── timeline ─────────────────────────────────────────────────────────────────


@probe("timeline.name", "timeline", timeout=20, needs=("timeline",))
def _probe_timeline_name(ctx): return ctx.timeline.GetName()


@probe("timeline.track_count_video", "timeline", timeout=20, needs=("timeline",))
def _probe_timeline_track_count_video(ctx): return ctx.timeline.GetTrackCount("video")


@probe("timeline.start_timecode", "timeline", timeout=20, needs=("timeline",))
def _probe_timeline_start_timecode(ctx): return ctx.timeline.GetStartTimecode()


@probe("timeline.set_current_timecode", "timeline", timeout=25, needs=("timeline",))
def _probe_timeline_set_current_timecode(ctx): return ctx.timeline.SetCurrentTimecode(ctx.timeline.GetStartTimecode())


@probe("timeline.current_video_item", "timeline", timeout=25, needs=("timeline",))
def _probe_timeline_current_video_item(ctx): return bool(ctx.timeline.GetCurrentVideoItem())


@probe("timeline.marker_roundtrip", "timeline", timeout=30, needs=("timeline",), destructive=True)
def _probe_timeline_marker_roundtrip(ctx):
    added = ctx.timeline.AddMarker(1, "Blue", "PROBE", "note", 1)
    count = len(ctx.timeline.GetMarkers() or {})
    ctx.timeline.DeleteMarkerAtFrame(1)
    return f"{added}/{count}"


@probe("timeline.add_delete_track", "timeline", timeout=40, needs=("timeline",), destructive=True)
def _probe_timeline_add_delete_track(ctx):
    added = ctx.timeline.AddTrack("video")
    n = ctx.timeline.GetTrackCount("video")
    deleted = ctx.timeline.DeleteTrack("video", n)
    return f"{added}/{deleted}"


@probe("timeline.set_track_name", "timeline", timeout=25, needs=("timeline",), destructive=True)
def _probe_timeline_set_track_name(ctx):
    ok = ctx.timeline.SetTrackName("video", 1, "PROBE_TRACK")
    return f"{ok}/{ctx.timeline.GetTrackName('video', 1)}"


@probe("timeline.track_enable_roundtrip", "timeline", timeout=30, needs=("timeline",), destructive=True)
def _probe_timeline_track_enable_roundtrip(ctx):
    off = ctx.timeline.SetTrackEnable("video", 1, False)
    ctx.timeline.SetTrackEnable("video", 1, True)
    return off


@probe("timeline.set_name", "timeline", timeout=30, needs=("timeline",), destructive=True,
       note="documented to fail on the ACTIVE timeline")
def _probe_timeline_set_name(ctx): return ctx.timeline.SetName("PROBE_RENAMED")


@probe("timeline.duplicate", "timeline", timeout=60, needs=("timeline",), destructive=True)
def _probe_timeline_duplicate(ctx):
    pool = ctx.project.GetMediaPool()
    dup = pool.DuplicateTimeline("PROBE_DUP")
    return bool(dup)


@probe("timeline.grab_still", "timeline", timeout=60, needs=("timeline",), destructive=True)
def _probe_timeline_grab_still(ctx):
    still = ctx.timeline.GrabStill()
    if not still:
        return False
    album = ctx.project.GetGallery().GetCurrentStillAlbum()
    album and album.DeleteStills([still])
    return True


# ── timeline items ───────────────────────────────────────────────────────────


@probe("item.name", "timeline_item", timeout=20, needs=("item",))
def _probe_item_name(ctx): return ctx.item.GetName()


@probe("item.duration", "timeline_item", timeout=20, needs=("item",))
def _probe_item_duration(ctx): return ctx.item.GetDuration()


@probe("item.left_offset", "timeline_item", timeout=20, needs=("item",))
def _probe_item_left_offset(ctx): return ctx.item.GetLeftOffset()


@probe("item.set_zoom_property", "timeline_item", timeout=25, needs=("item",), destructive=True)
def _probe_item_set_zoom_property(ctx):
    ok = ctx.item.SetProperty("ZoomX", 1.25)
    return f"{ok}/{ctx.item.GetProperty('ZoomX')}"


@probe("item.marker_roundtrip", "timeline_item", timeout=30, needs=("item",), destructive=True)
def _probe_item_marker_roundtrip(ctx):
    added = ctx.item.AddMarker(1, "Blue", "PROBE", "note", 1)
    ctx.item.DeleteMarkerAtFrame(1)
    return added


@probe("item.flag_roundtrip", "timeline_item", timeout=30, needs=("item",), destructive=True)
def _probe_item_flag_roundtrip(ctx):
    added = ctx.item.AddFlag("Blue")
    ctx.item.ClearFlags("All")
    return added


@probe("item.set_clip_color", "timeline_item", timeout=25, needs=("item",), destructive=True)
def _probe_item_set_clip_color(ctx):
    ok = ctx.item.SetClipColor("Orange")
    ctx.item.ClearClipColor()
    return ok


@probe("item.media_pool_item", "timeline_item", timeout=25, needs=("item",))
def _probe_item_media_pool_item(ctx): return bool(ctx.item.GetMediaPoolItem())


# ── colour ───────────────────────────────────────────────────────────────────


@probe("color.node_graph", "color", timeout=30, needs=("item",))
def _probe_color_node_graph(ctx): return bool(ctx.item.GetNodeGraph())


@probe("color.num_nodes", "color", timeout=25, needs=("item",))
def _probe_color_num_nodes(ctx): return ctx.item.GetNodeGraph().GetNumNodes()


@probe("color.node_label", "color", timeout=25, needs=("item",))
def _probe_color_node_label(ctx): return ctx.item.GetNodeGraph().GetNodeLabel(1)


@probe("color.node_lut", "color", timeout=25, needs=("item",))
def _probe_color_node_lut(ctx): return ctx.item.GetNodeGraph().GetLUT(1)


@probe("color.tools_in_node", "color", timeout=25, needs=("item",))
def _probe_color_tools_in_node(ctx): return len(ctx.item.GetNodeGraph().GetToolsInNode(1) or [])


@probe("color.set_node_enabled", "color", timeout=25, needs=("item",), destructive=True)
def _probe_color_set_node_enabled(ctx): return ctx.item.GetNodeGraph().SetNodeEnabled(1, True)


@probe("color.reset_all_grades", "color", timeout=40, needs=("item",), destructive=True)
def _probe_color_reset_all_grades(ctx): return ctx.item.GetNodeGraph().ResetAllGrades()


@probe("color.group_roundtrip", "color", timeout=45, needs=("item", "project"), destructive=True)
def _probe_color_group_roundtrip(ctx):
    group = ctx.project.AddColorGroup("PROBE_GROUP")
    if not group:
        return False
    assigned = ctx.item.AssignToColorGroup(group)
    ctx.item.RemoveFromColorGroup()
    ctx.project.DeleteColorGroup(group)
    return assigned


@probe("color.set_cdl", "color", timeout=30, needs=("item",), destructive=True)
def _probe_color_set_cdl(ctx):
    return ctx.item.SetCDL({"NodeIndex": "1", "Slope": "1 1 1", "Offset": "0 0 0",
                            "Power": "1 1 1", "Saturation": "1"})


# ── gallery ──────────────────────────────────────────────────────────────────


@probe("gallery.handle", "gallery", timeout=25, needs=("project",))
def _probe_gallery_handle(ctx): return bool(ctx.project.GetGallery())


@probe("gallery.album_count", "gallery", timeout=25, needs=("project",))
def _probe_gallery_album_count(ctx): return len(ctx.project.GetGallery().GetGalleryStillAlbums() or [])


@probe("gallery.export_stills", "gallery", timeout=90, needs=("timeline", "project"), destructive=True,
       note="fails in BOTH modes without a visible Gallery panel")
def _probe_gallery_export_stills(ctx):
    gallery = ctx.project.GetGallery()
    album = gallery.GetCurrentStillAlbum()
    still = ctx.timeline.GrabStill()
    if not (album and still):
        return False
    target = ctx.work / "stills"
    target.mkdir(exist_ok=True)
    ok = album.ExportStills([still], str(target), "probe", "jpg")
    produced = len(list(target.glob("probe*")))
    album.DeleteStills([still])
    return combine(ok, produced)


@probe("gallery.export_current_frame", "gallery", timeout=90, needs=("project",), destructive=True)
def _probe_gallery_export_current_frame(ctx):
    target = ctx.work / "frame.png"
    ok = ctx.project.ExportCurrentFrameAsStill(str(target))
    return combine(ok, target.exists() and target.stat().st_size > 0)


# ── fusion ───────────────────────────────────────────────────────────────────


@probe("fusion.comp_count", "fusion", timeout=30, needs=("item",))
def _probe_fusion_comp_count(ctx): return ctx.item.GetFusionCompCount()


@probe("fusion.add_delete_comp", "fusion", timeout=90, needs=("item",), destructive=True)
def _probe_fusion_add_delete_comp(ctx):
    added = bool(ctx.item.AddFusionComp())
    names = ctx.item.GetFusionCompNameList() or []
    deleted = ctx.item.DeleteFusionCompByName(names[-1]) if names else None
    return f"{added}/{deleted}"


# ── render / deliver ─────────────────────────────────────────────────────────


@probe("render.format_count", "render", timeout=45, needs=("project",))
def _probe_render_format_count(ctx): return len(ctx.project.GetRenderFormats() or {})


@probe("render.codec_count_mov", "render", timeout=45, needs=("project",))
def _probe_render_codec_count_mov(ctx): return len(ctx.project.GetRenderCodecs("mov") or {})


@probe("render.preset_count", "render", timeout=45, needs=("project",))
def _probe_render_preset_count(ctx): return len(ctx.project.GetRenderPresetList() or [])


@probe("render.set_format_codec", "render", timeout=45, needs=("project",), destructive=True)
def _probe_render_set_format_codec(ctx): return ctx.project.SetCurrentRenderFormatAndCodec("mov", "ProRes422HQ")


@probe("render.job_roundtrip", "render", timeout=120, needs=("project", "timeline"), destructive=True)
def _probe_render_job_roundtrip(ctx):
    ctx.project.SetRenderSettings({"TargetDir": str(ctx.work), "CustomName": "probe_job",
                                   "SelectAllFrames": True})
    job = ctx.project.AddRenderJob()
    if not job:
        return False
    count = len(ctx.project.GetRenderJobList() or [])
    deleted = ctx.project.DeleteRenderJob(job)
    return f"{count}/{deleted}"


@probe("render.to_disk", "render", timeout=600, needs=("project", "timeline"), destructive=True,
       note="the delivery path end to end; the only probe that writes real pixels")
def _probe_render_to_disk(ctx):
    import time as _t
    ctx.project.SetCurrentRenderFormatAndCodec("mov", "ProRes422Proxy")
    ctx.project.SetRenderSettings({"TargetDir": str(ctx.work), "CustomName": "probe_render",
                                   "SelectAllFrames": True})
    job = ctx.project.AddRenderJob()
    if not job:
        return False
    # Positional: the free-edition bridge proxies Resolve calls positionally,
    # and a keyword argument dies inside _BoundMethod (PR #165's bug class).
    ctx.project.StartRendering(job, False)
    deadline = _t.monotonic() + 420
    while ctx.project.IsRenderingInProgress() and _t.monotonic() < deadline:
        _t.sleep(1)
    status = (ctx.project.GetRenderJobStatus(job) or {}).get("JobStatus")
    written = [p for p in ctx.work.glob("probe_render*") if p.stat().st_size > 0]
    ctx.project.DeleteRenderJob(job)
    return f"{status}/{len(written)}"


# ── interchange export ───────────────────────────────────────────────────────

_EXPORTS = (("aaf", "EXPORT_AAF", "EXPORT_AAF_NEW"), ("edl", "EXPORT_EDL", "EXPORT_NONE"),
            ("fcpxml", "EXPORT_FCP_7_XML", "EXPORT_NONE"), ("drt", "EXPORT_DRT", "EXPORT_NONE"),
            ("otio", "EXPORT_OTIO", "EXPORT_NONE"))

for _label, _type, _sub in _EXPORTS:
    def _make(label, type_name, sub_name):
        def body(ctx):
            path = ctx.work / f"probe.{label}"
            ok = ctx.timeline.Export(str(path), getattr(ctx.resolve, type_name),
                                     getattr(ctx.resolve, sub_name))
            return combine(ok, path.exists() and path.stat().st_size > 0)
        return body
    CATALOGUE.append(Probe(f"export.{_label}", "interchange", _make(_label, _type, _sub),
                           timeout=120, needs=("timeline",), destructive=True))


# ── audio / fairlight ────────────────────────────────────────────────────────


@probe("audio.track_count", "audio", timeout=25, needs=("timeline",))
def _probe_audio_track_count(ctx): return ctx.timeline.GetTrackCount("audio")


@probe("audio.add_delete_track", "audio", timeout=45, needs=("timeline",), destructive=True)
def _probe_audio_add_delete_track(ctx):
    added = ctx.timeline.AddTrack("audio", "stereo")
    n = ctx.timeline.GetTrackCount("audio")
    deleted = ctx.timeline.DeleteTrack("audio", n) if n else None
    return f"{added}/{deleted}"


@probe("audio.set_track_name", "audio", timeout=30, needs=("timeline",), destructive=True)
def _probe_audio_set_track_name(ctx):
    if not ctx.timeline.GetTrackCount("audio"):
        return None
    return ctx.timeline.SetTrackName("audio", 1, "PROBE_AUDIO")


# ── layout / UI-shaped surfaces ──────────────────────────────────────────────


@probe("layout.save_preset", "layout", timeout=60, destructive=True)
def _probe_layout_save_preset(ctx): return ctx.resolve.SaveLayoutPreset("PROBE_LAYOUT")


@probe("layout.export_preset", "layout", timeout=60, destructive=True)
def _probe_layout_export_preset(ctx):
    path = ctx.work / "layout.preset"
    ok = ctx.resolve.ExportLayoutPreset("PROBE_LAYOUT", str(path))
    return combine(ok, path.exists() and path.stat().st_size > 0)


@probe("layout.load_preset", "layout", timeout=60, destructive=True)
def _probe_layout_load_preset(ctx): return ctx.resolve.LoadLayoutPreset("PROBE_LAYOUT")


@probe("layout.delete_preset", "layout", timeout=45, destructive=True)
def _probe_layout_delete_preset(ctx): return ctx.resolve.DeleteLayoutPreset("PROBE_LAYOUT")


# ── project lifecycle (last: these move the current project) ──────────────────


#: Lifecycle probes use a per-run unique suffix and the safe delete helper.
#:
#: They did neither at first, and it produced a false finding: the GUI pass left
#: a `PROBE_LIFECYCLE` behind (its DeleteProject hit the session lock), so the
#: headless pass's CreateProject collided with the existing name, returned False,
#: and was reported as `headless_degraded`. CreateProject with a fresh name works
#: identically in both modes. A fixed name plus an unreliable delete is a
#: cross-run dependency, and a differential must not have one.
def _unique(ctx, stem):
    return f"{stem}_{ctx.project_name.split('_')[-1]}"


def _safe_delete(ctx, name):
    from src.utils.project_cleanup import delete_project_safely
    return delete_project_safely(ctx.pm, name, switch_to=ctx.project_name)["success"]


@probe("lifecycle.create_project", "lifecycle", timeout=90, destructive=True)
def _probe_lifecycle_create_project(ctx):
    name = _unique(ctx, "PROBE_LIFECYCLE")
    made = bool(ctx.pm.CreateProject(name))
    if made:
        _safe_delete(ctx, name)
    return made


@probe("lifecycle.load_and_close", "lifecycle", timeout=120, destructive=True)
def _probe_lifecycle_load_and_close(ctx):
    name = _unique(ctx, "PROBE_LIFECYCLE2")
    if not ctx.pm.CreateProject(name):
        return False
    loaded = bool(ctx.pm.LoadProject(name))
    closed = bool(ctx.pm.CloseProject(ctx.pm.GetCurrentProject()))
    ctx.pm.LoadProject(ctx.project_name)
    deleted = _safe_delete(ctx, name)
    return f"{loaded}/{closed}/{deleted}"


@probe("lifecycle.delete_after_close_releases_lock", "lifecycle", timeout=120, destructive=True,
       note="LoadProject-away does NOT release the lock; CloseProject does")
def _probe_lifecycle_delete_after_close_releases_lock(ctx):
    name = _unique(ctx, "PROBE_LOCK")
    if not ctx.pm.CreateProject(name):
        return False
    ctx.pm.LoadProject(name)
    ctx.pm.LoadProject(ctx.project_name)          # switch away WITHOUT closing
    without_close = bool(ctx.pm.DeleteProject(name))
    if not without_close:
        ctx.pm.LoadProject(name)
        ctx.pm.CloseProject(ctx.pm.GetCurrentProject())
        ctx.pm.LoadProject(ctx.project_name)
        with_close = bool(ctx.pm.DeleteProject(name))
        return f"without_close={without_close}/with_close={with_close}"
    return f"without_close={without_close}"


def fingerprint() -> str:
    """Identity of this catalogue: version plus the probe set it defines."""
    import hashlib

    names = ",".join(sorted(p.name for p in CATALOGUE))
    digest = hashlib.sha256(names.encode()).hexdigest()[:12]
    return f"v{CATALOGUE_VERSION}-{digest}"


# ── long-running / AI / media-management surfaces ────────────────────────────
#
# These are the surfaces most likely to behave differently without a UI: they
# either spawn background work, need Studio AI models, or write large files.
# Generous timeouts, because a slow op misreported as a hang is a false finding
# and this catalogue's whole point is not producing those.


@probe("longop.transcribe_audio", "longop", timeout=300, needs=("clip",), destructive=True,
       note="Studio AI; may need a language model present")
def _probe_longop_transcribe_audio(ctx):
    ok = ctx.clip.TranscribeAudio()
    if ok:
        try:
            ctx.clip.ClearTranscription()
        except Exception:
            pass
    return ok


@probe("longop.auto_sync_audio", "longop", timeout=180, needs=("project",), destructive=True,
       note="needs >= 2 pool items, at least one video and one audio")
def _probe_longop_auto_sync_audio(ctx):
    clips = ctx.project.GetMediaPool().GetRootFolder().GetClipList() or []
    if len(clips) < 2:
        return None
    return ctx.project.GetMediaPool().AutoSyncAudio(clips[:2])


@probe("longop.create_subtitles_from_audio", "longop", timeout=300, needs=("timeline",),
       destructive=True, note="Studio AI; enum-keyed settings dict")
def _probe_longop_subtitles(ctx):
    return ctx.timeline.CreateSubtitlesFromAudio()


@probe("longop.link_unlink_proxy", "longop", timeout=120, needs=("clip",), destructive=True)
def _probe_longop_proxy(ctx):
    path = ctx.clip.GetClipProperty("File Path")
    linked = ctx.clip.LinkProxyMedia(path) if path else None
    unlinked = ctx.clip.UnlinkProxyMedia()
    return f"{linked}/{unlinked}"


# ── editorial constructs ─────────────────────────────────────────────────────


@probe("editorial.compound_clip", "editorial", timeout=180, needs=("timeline", "item"),
       destructive=True)
def _probe_editorial_compound(ctx):
    items = ctx.timeline.GetItemListInTrack("video", 1) or []
    if not items:
        return None
    made = ctx.project.GetMediaPool().CreateCompoundClip(
        items[:1], {"name": "PROBE_COMPOUND"})
    return bool(made)


@probe("editorial.fusion_clip", "editorial", timeout=180, needs=("timeline",), destructive=True)
def _probe_editorial_fusion_clip(ctx):
    items = ctx.timeline.GetItemListInTrack("video", 1) or []
    if not items:
        return None
    return bool(ctx.project.GetMediaPool().CreateFusionClip(items[:1]))


@probe("editorial.take_selector", "editorial", timeout=180, needs=("item", "clip"),
       destructive=True)
def _probe_editorial_takes(ctx):
    added = ctx.item.AddTake(ctx.clip)
    count = ctx.item.GetTakesCount()
    selected = ctx.item.SelectTakeByIndex(1) if count else None
    finalized = ctx.item.FinalizeTake() if count else None
    return f"{added}/{count}/{selected}/{finalized}"


@probe("editorial.nested_timeline", "editorial", timeout=180, needs=("project", "timeline"),
       destructive=True)
def _probe_editorial_nested(ctx):
    """A timeline appended into another timeline — the nesting an edit loop uses."""
    pool = ctx.project.GetMediaPool()
    outer = pool.CreateEmptyTimeline("PROBE_OUTER")
    if outer is None:
        return False
    # Timelines appear in the media pool as clips; that is how one is nested.
    nested = [c for c in (pool.GetRootFolder().GetClipList() or [])
              if (c.GetClipProperty("Type") or "") == "Timeline"]
    if not nested:
        return None
    # AppendToTimeline writes to the CURRENT timeline, so a discarded False
    # here would nest the clip into ctx.timeline and then count PROBE_OUTER's
    # empty track -- a measurement of the wrong timeline, reported as this one's.
    switched, detail = set_current_timeline(ctx.project, outer)
    if not switched:
        return describe_switch_failure(detail, "nesting the probe timeline")
    appended = pool.AppendToTimeline([{"mediaPoolItem": nested[0]}])
    count = len(outer.GetItemListInTrack("video", 1) or [])
    restored, restore_detail = set_current_timeline(ctx.project, ctx.timeline)
    result = f"{bool(appended)}/{count}"
    if not restored:
        # The measurement stands; the teardown did not. Say so in the result
        # rather than leaving the next probe on PROBE_OUTER without warning.
        result += " (probe timeline left current: " + \
            describe_switch_failure(restore_detail, "restoring the probe timeline") + ")"
    return result


@probe("editorial.set_clips_linked", "editorial", timeout=90, needs=("timeline",),
       destructive=True)
def _probe_editorial_linked(ctx):
    items = ctx.timeline.GetItemListInTrack("video", 1) or []
    if not items:
        return None
    off = ctx.timeline.SetClipsLinked(items[:1], False)
    ctx.timeline.SetClipsLinked(items[:1], True)
    return off


# ── project-level / delivery presets ─────────────────────────────────────────


@probe("projectlevel.render_preset_roundtrip", "projectlevel", timeout=120, needs=("project",),
       destructive=True)
def _probe_projectlevel_render_preset(ctx):
    saved = ctx.project.SaveAsNewRenderPreset("PROBE_RENDER_PRESET")
    deleted = ctx.project.DeleteRenderPreset("PROBE_RENDER_PRESET") if saved else None
    return f"{saved}/{deleted}"


@probe("projectlevel.export_burn_in_preset", "projectlevel", timeout=120, destructive=True)
def _probe_projectlevel_burnin(ctx):
    path = ctx.work / "burnin.preset"
    ok = ctx.resolve.ExportBurnInPreset("Default", str(path))
    return combine(ok, path.exists() and path.stat().st_size > 0)


@probe("projectlevel.archive_project", "projectlevel", timeout=600, destructive=True,
       note="writes a .dra bundle; media excluded to keep it small")
def _probe_projectlevel_archive(ctx):
    target = ctx.work / "archive"
    target.mkdir(exist_ok=True)
    ok = ctx.pm.ArchiveProject(ctx.project_name, str(target / "probe.dra"),
                               False, False, False)
    produced = len(list(target.rglob("*"))) if target.exists() else 0
    return combine(ok, produced)


@probe("projectlevel.multi_job_queue", "projectlevel", timeout=180, needs=("project", "timeline"),
       destructive=True)
def _probe_projectlevel_multi_job(ctx):
    """Three queued jobs — a delivery queue is rarely one render."""
    ids = []
    for index in range(3):
        ctx.project.SetRenderSettings({"TargetDir": str(ctx.work),
                                       "CustomName": f"queue_{index}",
                                       "SelectAllFrames": True})
        job = ctx.project.AddRenderJob()
        if job:
            ids.append(job)
    count = len(ctx.project.GetRenderJobList() or [])
    for job in ids:
        ctx.project.DeleteRenderJob(job)
    return f"{len(ids)}/{count}"
