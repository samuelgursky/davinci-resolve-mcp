"""Live verification of public-API routes that DO work.

The sibling harness (live_api_gap_verification.py) proves absence. This one
proves presence: for each operation an external report claimed was impossible,
it performs the operation against a DISPOSABLE project built from SYNTHETIC
media and reads the result back, so "there is a supported route" is a
measurement rather than an assertion.

Every case records what was attempted, what was read back, and whether the
readback matched the request. A route only counts when the readback matches.

Source-safe: generates its own synthetic clips in a temp dir, never touches user
media. Restores the originally-open project and deletes the disposable project +
temp media on exit.

Run:
  env RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
      RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
      PYTHONPATH="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules" \
      venv/bin/python tests/live_workaround_verification.py
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

PROJECT_NAME = "ZZ_workaround_verify"
results = []


def record(route, claim, attempted, readback, ok, notes=None):
    results.append({
        "route": route,
        "report_claim": claim,
        "attempted": attempted,
        "readback": readback,
        "verdict": "ROUTE WORKS" if ok else "ROUTE FAILS",
        "notes": notes,
    })


def gen_media(tmp):
    paths = []
    for i, freq in enumerate((440, 880)):
        p = os.path.join(tmp, f"clip{i}.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", f"testsrc2=size=640x360:rate=24:duration=6",
             "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=6",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-shortest", p],
            check=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        paths.append(p)
    return paths


def new_tl(proj, mp, name, video_tracks=1):
    tl = mp.CreateEmptyTimeline(f"{name}_{int(time.time() * 1000) % 100000}")
    proj.SetCurrentTimeline(tl)
    tl = proj.GetCurrentTimeline()
    for _ in range(tl.GetTrackCount("video"), video_tracks):
        tl.AddTrack("video")
    return tl


def title_text(tl):
    for i in range(1, tl.GetTrackCount("video") + 1):
        for it in tl.GetItemListInTrack("video", i) or []:
            if it.GetFusionCompCount():
                tool = it.GetFusionCompByIndex(1).FindTool("Template")
                if tool:
                    return tool.GetInput("StyledText")
    return None


def set_title_text(tl, value):
    for i in range(1, tl.GetTrackCount("video") + 1):
        for it in tl.GetItemListInTrack("video", i) or []:
            if it.GetFusionCompCount():
                tool = it.GetFusionCompByIndex(1).FindTool("Template")
                if tool:
                    tool.SetInput("StyledText", value)
                    return True
    return False


# --------------------------------------------------------------------------
def case_nested_title(proj, mp):
    """A source-less Text+ placed at an exact track and frame, still editable."""
    src = new_tl(proj, mp, "ZZ_title_src")
    src.InsertFusionTitleIntoTimeline("Text+")
    set_title_text(src, "ORIGINAL")
    src_mpi = src.GetMediaPoolItem()

    tgt = new_tl(proj, mp, "ZZ_title_tgt", video_tracks=3)
    start = tgt.GetStartFrame()
    want_track, want_frame, want_dur = 3, start + 100, 90
    placed = mp.AppendToTimeline([{
        "mediaPoolItem": src_mpi, "startFrame": 0, "endFrame": want_dur,
        "trackIndex": want_track, "recordFrame": want_frame,
    }])
    if not placed:
        record("Nested-timeline title placement",
               "Text+ has no track/frame/duration parameters and cannot be placed",
               f"AppendToTimeline(trackIndex={want_track}, recordFrame={want_frame})",
               "append returned nothing", False)
        return
    it = placed[0]
    got = {
        "track": it.GetTrackTypeAndIndex()[1],
        "start": it.GetStart(),
        "duration": it.GetDuration(),
    }
    placed_ok = (got["track"] == want_track and got["start"] == want_frame
                 and got["duration"] == want_dur)

    inner = it.GetMediaPoolItem().GetTimeline()
    before = title_text(inner) if inner else None
    edited = set_title_text(inner, "EDITED VIA API") if inner else False
    after = title_text(inner) if inner else None
    record(
        "Nested-timeline title placement + later text edit",
        "Text+ is source-less, cannot be moved/trimmed, blocks later corrections",
        f"place on V{want_track}@{want_frame} for {want_dur}f, then edit inner text",
        {"placement": got, "want": {"track": want_track, "start": want_frame,
                                    "duration": want_dur},
         "inner_timeline": inner.GetName() if inner else None,
         "text_before": before, "text_after": after},
        placed_ok and edited and after == "EDITED VIA API",
        notes="endFrame is EXCLUSIVE: duration = endFrame - startFrame",
    )


def case_compound_severs_text(proj, mp):
    """The compound alternative places, but destroys text reachability."""
    tl = new_tl(proj, mp, "ZZ_compound")
    tl.InsertFusionTitleIntoTimeline("Text+")
    items = tl.GetItemListInTrack("video", 1) or []
    if not items:
        return
    bare_comps = items[0].GetFusionCompCount()
    bare_mpi = items[0].GetMediaPoolItem()
    comp = tl.CreateCompoundClip([items[0]], {"name": f"ZZ_cmp_{int(time.time()) % 10000}"})
    if not comp:
        record("Compound clip as a placement route", "n/a",
               "Timeline.CreateCompoundClip([text+])", "returned nothing", False)
        return
    cmpi = comp.GetMediaPoolItem()
    inner = cmpi.GetTimeline() if cmpi else None
    record(
        "Compound clip as a placement route (THE TRAP)",
        "compound clips are an acceptable substitute for a bare Text+",
        "CreateCompoundClip([text+]) then reach back for the text",
        {"bare_title": {"FusionCompCount": bare_comps, "MediaPoolItem": bool(bare_mpi)},
         "compound": {"FusionCompCount": comp.GetFusionCompCount(),
                      "MediaPoolItem": bool(cmpi),
                      "clip_type": cmpi.GetClipProperty("Type") if cmpi else None,
                      "GetTimeline()": bool(inner)}},
        False,
        notes="Compounding GRANTS a MediaPoolItem (so it places) but SEVERS the "
              "text: FusionCompCount 1->0 and GetTimeline() is None for "
              "Type='Compound' while it works for Type='Timeline'. Nest instead.",
    )


def case_ripple_delete(proj, mp, clips):
    """DeleteClips(items, True) really ripples; False really leaves a gap."""
    out = {}
    for ripple in (False, True):
        tl = new_tl(proj, mp, f"ZZ_ripple_{int(ripple)}")
        start = tl.GetStartFrame()
        for n in range(3):
            mp.AppendToTimeline([{
                "mediaPoolItem": clips[0], "startFrame": 0, "endFrame": 24,
                "trackIndex": 1, "recordFrame": start + n * 24,
            }])
        before = [i.GetStart() for i in tl.GetItemListInTrack("video", 1) or []]
        if len(before) != 3:
            out[ripple] = {"error": f"expected 3 items, got {len(before)}"}
            continue
        middle = (tl.GetItemListInTrack("video", 1) or [])[1]
        ok = tl.DeleteClips([middle], ripple)
        after = [i.GetStart() for i in tl.GetItemListInTrack("video", 1) or []]
        out[ripple] = {"call": bool(ok), "starts_before": before,
                       "starts_after": after}
    rippled = out.get(True, {}).get("starts_after")
    gapped = out.get(False, {}).get("starts_after")
    # ripple: third clip slides back onto the middle's old start
    ok = (isinstance(rippled, list) and isinstance(gapped, list)
          and len(rippled) == 2 and len(gapped) == 2 and rippled[1] < gapped[1])
    record(
        "Ripple delete",
        "no ripple/non-ripple remove or lift operations exist",
        "Timeline.DeleteClips([middle], ripple=False) vs ripple=True",
        out, ok,
        notes="Ripple delete DOES exist. Lift and the ripple TRIM modes do not — "
              "narrow the claim to those.",
    )


def case_take_selector(proj, mp, clips):
    """AddTake/SelectTakeByIndex/FinalizeTake = in-place source swap."""
    tl = new_tl(proj, mp, "ZZ_takes")
    mp.AppendToTimeline([{"mediaPoolItem": clips[0], "startFrame": 0,
                          "endFrame": 48, "trackIndex": 1,
                          "recordFrame": tl.GetStartFrame()}])
    items = tl.GetItemListInTrack("video", 1) or []
    if not items:
        return
    it = items[0]
    src_before = it.GetMediaPoolItem().GetName()
    added = it.AddTake(clips[1], 0, 48)
    count = it.GetTakesCount()
    sel = it.SelectTakeByIndex(2)
    src_after = it.GetMediaPoolItem().GetName()
    idx = it.GetSelectedTakeIndex()
    final = it.FinalizeTake()
    src_final = it.GetMediaPoolItem().GetName()
    record(
        "Take selector as in-place source swap",
        "an existing clip cannot be corrected locally; substitutions need a rebuild",
        "AddTake(other) -> SelectTakeByIndex(2) -> FinalizeTake()",
        {"AddTake": bool(added), "takes": count, "SelectTakeByIndex(2)": bool(sel),
         "selected_index": idx, "FinalizeTake": bool(final),
         "source_before": src_before, "source_after_select": src_after,
         "source_after_finalize": src_final},
        bool(added) and count >= 2 and src_after != src_before,
        notes="Swaps the SOURCE of a placed item in place, no rebuild. Applies "
              "only to items that have a MediaPoolItem — not to a bare Text+.",
    )


def case_selected_clips(proj, mp, clips):
    """Timeline.GetSelectedClips (Resolve 21.0.4+) — present, but read-only."""
    tl = new_tl(proj, mp, "ZZ_selection")
    mp.AppendToTimeline([{"mediaPoolItem": clips[0], "startFrame": 0,
                          "endFrame": 24, "trackIndex": 1,
                          "recordFrame": tl.GetStartFrame()}])
    exists = "GetSelectedClips" in set(dir(tl))
    got = None
    if exists:
        try:
            sel = tl.GetSelectedClips()
            got = len(sel) if sel else 0
        except Exception as e:  # noqa: BLE001
            got = f"raised {type(e).__name__}"
    setters = [n for n in ("SetSelectedClips", "SelectClips", "SetSelection")
               if n in set(dir(tl))]
    record(
        "Timeline.GetSelectedClips (21.0.4+)",
        "not claimed in the report; checked because selection could be a route",
        "dir() membership + call with nothing selected in the UI",
        {"exists": exists, "returned_count": got, "setters_found": setters},
        exists,
        notes="Read-only: no API sets the selection, so it cannot drive an edit "
              "from a script. Useful only to observe a human's selection.",
    )


def main():
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        print("FATAL: cannot connect to Resolve")
        return 1
    print(f"Resolve: {resolve.GetVersionString()} / {resolve.GetProductName()}")
    pm = resolve.GetProjectManager()
    original = pm.GetCurrentProject()
    original_name = original.GetName() if original else None
    print(f"Original project: {original_name}")

    tmp = tempfile.mkdtemp(prefix="resolve_workaround_")
    try:
        media = gen_media(tmp)
        proj = pm.LoadProject(PROJECT_NAME) or pm.CreateProject(PROJECT_NAME)
        if not proj:
            # CreateProject returns None while certain projects are current —
            # documented for a dirty Untitled project, but observed on a named
            # one too (Studio 21.0.4.5). Switching to ANY clean project clears
            # it. Do NOT use the ledger's CloseProject workaround here: that
            # discards unsaved changes, which is unacceptable when the current
            # project belongs to someone else's session.
            for fallback in (pm.GetProjectListInCurrentFolder() or []):
                if fallback.startswith("ZZ_") and fallback != PROJECT_NAME:
                    if pm.LoadProject(fallback):
                        print(f"unblocked CreateProject by loading {fallback!r}")
                        break
            proj = pm.LoadProject(PROJECT_NAME) or pm.CreateProject(PROJECT_NAME)
        if not proj:
            print("FATAL: could not load or create disposable project")
            return 1
        mp = proj.GetMediaPool()
        clips = mp.ImportMedia(media) or []
        if len(clips) < 2:
            print("FATAL: import produced too few clips")
            return 1

        case_nested_title(proj, mp)
        case_compound_severs_text(proj, mp)
        case_ripple_delete(proj, mp, clips)
        case_take_selector(proj, mp, clips)
        case_selected_clips(proj, mp, clips)

        print("\n" + "=" * 70)
        print(json.dumps(results, indent=2, default=str))
        print("=" * 70)
        works = sum(1 for r in results if r["verdict"] == "ROUTE WORKS")
        print(f"\n{works}/{len(results)} routes VERIFIED WORKING on "
              f"{resolve.GetVersionString()}")
        return 0
    finally:
        try:
            print("\ncleanup:", delete_project_safely(
                pm, PROJECT_NAME, switch_to=original_name, retries=2))
        except Exception as e:  # noqa: BLE001
            print(f"cleanup delete error: {e}")
        try:
            if original_name:
                pm.LoadProject(original_name)
        except Exception as e:  # noqa: BLE001
            print(f"restore error: {e}")
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
