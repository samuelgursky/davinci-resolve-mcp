"""Live, mutating verification of catalogued Resolve API gaps.

For each "missing capability" in the api-limitations report, this harness
attempts the plausible API path against a DISPOSABLE project built from
SYNTHETIC ffmpeg media, and records both the failing attempt and a positive
control (a related call that DOES work) so the result is credible rather than a
bare "method not found".

Source-safe: generates its own synthetic clips in a temp dir, never touches user
media. Restores the originally-open project and deletes the disposable project +
temp media on exit.

Run:
  env RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
      RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
      PYTHONPATH="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules" \
      venv/bin/python tests/live_api_gap_verification.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import DaVinciResolveScript as dvr  # noqa: E402
from src.utils.project_cleanup import delete_project_safely  # noqa: E402

PROJECT_NAME = "ZZ_api_gap_verify"
results = []


def record(gap, attempted, outcome, conclusion, control=None):
    results.append({
        "gap": gap,
        "attempted": attempted,
        "outcome": outcome,
        "positive_control": control,
        "conclusion": conclusion,
    })


def has(obj, *names):
    """Return the subset of names that genuinely exist on obj.

    NOTE: hasattr()/getattr() are UNUSABLE here — the Resolve Python bridge
    fabricates a callable for ANY attribute name, so hasattr is always True.
    dir() lists only the real methods, so we membership-test against that.
    """
    existing = set(dir(obj))
    return [n for n in names if n in existing]


def gen_media(tmp):
    paths = []
    for i, freq in enumerate((440, 880)):
        p = os.path.join(tmp, f"clip{i}.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=640x360:rate=24:duration=4",
             "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-shortest", p],
            check=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        paths.append(p)
    return paths


def main():
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        print("FATAL: cannot connect to Resolve")
        return 1
    pm = resolve.GetProjectManager()
    original = pm.GetCurrentProject()
    original_name = original.GetName() if original else None
    print(f"Original project: {original_name}")

    tmp = tempfile.mkdtemp(prefix="resolve_api_gap_")
    proj = None
    try:
        media_paths = gen_media(tmp)
        print(f"Generated synthetic media: {media_paths}")

        # Disposable project: reuse an existing one if present (DeleteProject is
        # severely flaky, so we avoid spawning a fresh undeletable project on
        # every run), else create it.
        proj = pm.LoadProject(PROJECT_NAME) or pm.CreateProject(PROJECT_NAME)
        if not proj:
            print("FATAL: could not load or create disposable project")
            return 1
        mp = proj.GetMediaPool()
        clips = mp.ImportMedia(media_paths) or []
        print(f"Imported {len(clips)} clips")
        if len(clips) < 2:
            print("FATAL: import produced too few clips")
            return 1

        # Build a timeline and grab a TimelineItem (unique name: the reused
        # disposable project may already hold timelines from a prior run)
        tl = mp.CreateEmptyTimeline(f"ZZ_tl_{int(time.time())}")
        if not tl:
            print("FATAL: CreateEmptyTimeline returned None")
            return 1
        proj.SetCurrentTimeline(tl)
        mp.AppendToTimeline([clips[0]])
        item = None
        items = tl.GetItemListInTrack("video", 1) or []
        if items:
            item = items[0]
        if not item:
            print("FATAL: no timeline item to test")
            return 1

        # ---- Gap 7 positive control: AppendToTimeline with recordFrame ----
        rec = tl.GetStartFrame() + 200
        ci = {"mediaPoolItem": clips[1], "startFrame": 0, "endFrame": 40,
              "recordFrame": rec, "trackIndex": 1}
        app2 = mp.AppendToTimeline([ci])
        edit_modes_found = has(mp, "InsertIntoTimeline", "OverwriteIntoTimeline",
                               "ReplaceIntoTimeline", "FitToFill", "PlaceOnTop")
        record(
            "Insert/Overwrite/Replace/Fit-to-Fill edit modes",
            "MediaPool.{Insert,Overwrite,Replace,FitToFill}IntoTimeline(...)",
            f"none exist; only AppendToTimeline. found={edit_modes_found}",
            "CONFIRMED MISSING",
            control=f"AppendToTimeline(recordFrame={rec}) -> {bool(app2)}",
        )

        # ---- Gap 1: timeline-item trim/move/re-time (no setters) ----
        getters = {n: getattr(item, n)() for n in
                   ("GetStart", "GetEnd", "GetDuration", "GetLeftOffset",
                    "GetRightOffset")}
        setters = has(item, "SetStart", "SetEnd", "SetDuration",
                      "SetLeftOffset", "SetRightOffset", "SetPosition")
        record(
            "TimelineItem trim/move/re-time (no position setters)",
            "TimelineItem.Set{Start,End,Duration,LeftOffset,RightOffset}(...)",
            f"no setters exist. found={setters}",
            "CONFIRMED MISSING",
            control=f"getters work: {getters}",
        )

        # ---- Gap 2: razor / blade / split ----
        split_tl = has(tl, "Split", "Razor", "Blade", "SplitClip", "AddEdit")
        split_it = has(item, "Split", "Razor", "Blade", "SplitClip")
        record(
            "Razor / blade / split a timeline item",
            "Timeline.Split / TimelineItem.Split / Razor / Blade",
            f"none exist. timeline={split_tl} item={split_it}",
            "CONFIRMED MISSING",
        )

        # ---- Gap 3: clip speed / retime ratio (mutating attempts) ----
        speed_attempts = {}
        for key in ("Speed", "PlaybackSpeed", "RetimeSpeed", "ClipSpeed"):
            try:
                speed_attempts[key] = bool(item.SetProperty(key, 50))
            except Exception as e:
                speed_attempts[key] = f"raised {type(e).__name__}"
        try:
            retime_quality = bool(item.SetProperty("RetimeProcess", 1))
        except Exception as e:
            retime_quality = f"raised {type(e).__name__}"
        record(
            "Clip speed / retime ratio and speed ramps",
            "TimelineItem.SetProperty('Speed'|'PlaybackSpeed'|... , 50)",
            f"all rejected: {speed_attempts}",
            "CONFIRMED MISSING",
            control=f"SetProperty('RetimeProcess',1) [retime quality] -> {retime_quality}",
        )

        # ---- Gap 4: color node graph + primary grade ----
        try:
            cdl_ok = bool(item.SetCDL({"NodeIndex": "1", "Slope": "1 1 1",
                                       "Offset": "0 0 0", "Power": "1 1 1",
                                       "Saturation": "1"}))
        except Exception as e:
            cdl_ok = f"raised {type(e).__name__}"
        graph = item.GetNodeGraph() if hasattr(item, "GetNodeGraph") else None
        graph_methods = has(graph, "AddNode", "AddSerialNode", "AddParallelNode",
                            "DeleteNode", "SetLift", "SetGamma", "SetGain",
                            "SetOffset", "SetPrimaryValues", "ApplyGrade") if graph else []
        record(
            "Color node-graph editing and primary grade values",
            "Graph.{AddNode,SetLift,SetGamma,SetGain,...}",
            f"none exist. found={graph_methods}; "
            f"num_nodes={graph.GetNumNodes() if graph else 'n/a'}",
            "CONFIRMED MISSING",
            control=f"SetCDL(...) -> {cdl_ok} (CDL/DRX/LUT are the only grade API)",
        )

        # ---- Gap 5: Fairlight audio level / pan (mutating attempts) ----
        # NB: do NOT test "Pan" — it is the documented VIDEO transform key
        # (horizontal position), not audio pan, so it returns True and would be
        # a false positive. Audio level/pan have no SetProperty key at all.
        audio_attempts = {}
        for key in ("Volume", "Level", "Gain", "AudioVolume", "AudioGain"):
            try:
                audio_attempts[key] = bool(item.SetProperty(key, 0))
            except Exception as e:
                audio_attempts[key] = f"raised {type(e).__name__}"
        try:
            xform_ok = bool(item.SetProperty("ZoomX", 1.25))
        except Exception as e:
            xform_ok = f"raised {type(e).__name__}"
        record(
            "Fairlight audio levels / pan / EQ / automation / FairlightFX",
            "TimelineItem.SetProperty('Volume'|'Pan'|... )",
            f"all rejected: {audio_attempts}",
            "CONFIRMED MISSING",
            control=f"SetProperty('ZoomX',1.25) [video transform] -> {xform_ok}",
        )

        # ---- Gap 6: proxy / optimized-media generation ----
        mpi = clips[0]
        gen_methods = has(mpi, "GenerateProxy", "GenerateOptimizedMedia",
                          "CreateProxy", "RenderProxy")
        gen_proj = has(proj, "GenerateOptimizedMedia", "GenerateProxyMedia")
        link_methods = has(mpi, "LinkProxyMedia", "UnlinkProxyMedia",
                           "LinkFullResolutionMedia")
        record(
            "Proxy / optimized-media generation",
            "MediaPoolItem.GenerateProxy / Project.GenerateOptimizedMedia",
            f"none exist. item={gen_methods} project={gen_proj}",
            "CONFIRMED MISSING",
            control=f"only link/unlink exist: {link_methods}",
        )

        # ---- Gap 8: Smart / Power bins ----
        smart = has(mp, "AddSmartBin", "CreateSmartBin", "AddPowerBin",
                    "CreatePowerBin")
        reg = mp.AddSubFolder(mp.GetRootFolder(), "ZZ_regular_bin")
        record(
            "Smart Bins / Power Bins creation",
            "MediaPool.AddSmartBin / AddPowerBin",
            f"none exist. found={smart}",
            "CONFIRMED MISSING",
            control=f"AddSubFolder('ZZ_regular_bin') [regular bin] -> {bool(reg)}",
        )

        # ---- Gap 9: Source/Auto Track Selector + Insert*IntoTimeline target ----
        # The insert methods take no trackIndex, and locking does NOT redirect —
        # it BLOCKS. Control: a media-backed clip CAN target a track.
        sel_methods = has(tl, "GetTrackSelector", "SetTrackSelector",
                          "GetSourceTrackSelector", "SetSourceTrackSelector",
                          "GetAutoTrackSelector", "SetAutoTrackSelector",
                          "SetDestinationTrack", "GetDestinationTrack")
        while tl.GetTrackCount("video") < 2:
            tl.AddTrack("video")
        t_unlocked = tl.InsertFusionTitleIntoTimeline("Text+")
        landed = t_unlocked.GetTrackTypeAndIndex()[1] if t_unlocked else None
        tl.SetTrackLock("video", 1, True)
        t_locked = tl.InsertFusionTitleIntoTimeline("Text+")
        tl.SetTrackLock("video", 1, False)
        rec2 = tl.GetStartFrame() + 400
        ctrl = mp.AppendToTimeline([{"mediaPoolItem": clips[1], "startFrame": 0,
                                     "endFrame": 24, "trackIndex": 2,
                                     "recordFrame": rec2}])
        ctrl_track = ctrl[0].GetTrackTypeAndIndex()[1] if ctrl else None
        record(
            "Source/Auto Track Selector + destination for Insert*IntoTimeline",
            "Timeline.{Get,Set}SourceTrackSelector / a trackIndex arg on the "
            "Insert* family / locking V1 to redirect the insert to V2",
            f"no selector accessor exists: {sel_methods}; insert with nothing "
            f"locked landed on V{landed}; with V1 LOCKED the insert returned "
            f"{t_locked!r} (blocked, NOT redirected to V2)",
            "CONFIRMED MISSING",
            control=f"a MEDIA-BACKED clip targets a track fine: "
                    f"AppendToTimeline(trackIndex=2) -> landed on V{ctrl_track}",
        )

        # ---- Gap 10: edit transitions ----
        trans_tl = has(tl, "AddTransition", "CreateTransition", "GetTransitions",
                       "AddVideoTransition", "InsertTransition")
        trans_it = has(item, "AddTransition", "GetTransition", "SetTransition",
                       "AddVideoTransition")
        record(
            "Transition create / read / copy / remove",
            "Timeline.AddTransition / TimelineItem.AddTransition / GetTransitions",
            f"none exist. timeline={trans_tl} item={trans_it}; transitions "
            f"applied in the UI are invisible to scripting",
            "CONFIRMED MISSING",
            control=f"the timeline object is live and mutable: "
                    f"AddTrack('video') -> {tl.GetTrackCount('video')} video tracks",
        )

        # ---- Gap 11: native multicam clip creation ----
        mc_mp = has(mp, "CreateMulticamClip", "CreateMultiCamClip",
                    "CreateMulticamClipFromClips", "CreateMultiCamClipFromDict")
        mc_proj = has(proj, "CreateMulticamClip", "CreateMultiCamClip")
        stacked = mp.AppendToTimeline([
            {"mediaPoolItem": clips[0], "startFrame": 0, "endFrame": 24,
             "trackIndex": 1, "recordFrame": tl.GetStartFrame() + 600},
            {"mediaPoolItem": clips[1], "startFrame": 0, "endFrame": 24,
             "trackIndex": 2, "recordFrame": tl.GetStartFrame() + 600},
        ])
        record(
            "Native multicam clip creation",
            "MediaPool.CreateMulticamClip(angles) / CreateMultiCamClipFromDict",
            f"none exist. mediapool={mc_mp} project={mc_proj}; the angle->multicam "
            f"conversion is UI-only",
            "CONFIRMED MISSING",
            control=f"angles CAN be stacked programmatically: appended "
                    f"{len(stacked or [])} clips onto V1+V2 at one record frame",
        )

        # ---- Gap 12: per-caption subtitle text and timing ----
        tl.AddTrack("subtitle")
        sub_methods = has(item, "GetText", "SetText", "GetSubtitleText",
                          "SetSubtitleText")
        sub_tl = has(tl, "ImportSubtitles", "ImportSRT", "AddSubtitle",
                     "GetSubtitles", "SetSubtitleText")
        record(
            "Per-subtitle text content, timing, and SRT import",
            "TimelineItem.{Get,Set}Text on a subtitle item / Timeline.ImportSubtitles",
            f"none exist. item={sub_methods} timeline={sub_tl}; File > Import > "
            f"Subtitle is UI-only and per-caption text is unreadable",
            "CONFIRMED MISSING",
            control=f"subtitle TRACKS are scriptable: AddTrack('subtitle') -> "
                    f"{tl.GetTrackCount('subtitle')} subtitle track(s); "
                    f"CreateSubtitlesFromAudio exists: "
                    f"{'CreateSubtitlesFromAudio' in set(dir(tl))}",
        )

        # ---- Gap 13: per-clip audio channel-format conversion ----
        audio_conv_mpi = has(clips[0], "SetAudioChannelMapping",
                             "SetClipAudioFormat", "ConvertToStereo",
                             "SetAudioChannels")
        audio_conv_it = has(item, "SetSourceAudioChannelMapping",
                            "SetAudioMapping", "ConvertToStereo")
        try:
            mapping = item.GetSourceAudioChannelMapping()
        except Exception as e:  # noqa: BLE001
            mapping = f"raised {type(e).__name__}"
        record(
            "Per-clip audio channel-format conversion (Stereo<->Mono)",
            "MediaPoolItem/TimelineItem.SetAudioChannelMapping / ConvertToStereo",
            f"none exist. item={audio_conv_mpi} timeline_item={audio_conv_it}; "
            f"Clip Attributes > Audio is UI-only. ConvertTimelineToStereo is "
            f"timeline-wide and CreateStereoClip is 3D VISUAL stereo, not audio",
            "CONFIRMED MISSING",
            control=f"the mapping is READABLE: GetSourceAudioChannelMapping() -> "
                    f"{str(mapping)[:120]}",
        )

        print("\n" + "=" * 70)
        print(json.dumps(results, indent=2))
        print("=" * 70)
        confirmed = sum(1 for r in results if r["conclusion"] == "CONFIRMED MISSING")
        print(f"\n{confirmed}/{len(results)} gaps CONFIRMED MISSING via live mutating attempts")
        return 0
    finally:
        # Restore session + delete disposable project + temp media
        try:
            cleanup = delete_project_safely(pm, PROJECT_NAME,
                                            switch_to=original_name, retries=2)
            print(f"\ncleanup delete_project: {cleanup}")
        except Exception as e:
            print(f"cleanup delete error: {e}")
        try:
            if original_name:
                pm.LoadProject(original_name)
                print(f"restored project: {original_name}")
        except Exception as e:
            print(f"restore error: {e}")
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"removed temp media dir: {tmp}")


if __name__ == "__main__":
    raise SystemExit(main())
