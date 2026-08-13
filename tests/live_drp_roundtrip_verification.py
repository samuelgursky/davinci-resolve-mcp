"""Live round-trip verification for the offline .drp authoring tier.

The drp-format README long claimed "everything here is verified by a live
round-trip". There was no such harness — `RESOLVE_VERIFY=1` ran one test that
threw `TODO — implement once fixtures land`. Three false "verified live" claims
survived in that document as a result, one of which (`place_fusion_title`) was
propagated into a shipped api_truth recommendation before being caught. This is
the harness that was missing.

WHY IT ASSERTS PIXELS. Structural readback is not proof. `place_fusion_title`
passes every structural check there is — right track, right frame, right
duration, PrettyType 'Fusion Title', text correctly encoded in the
CompositionBA — and renders NOTHING, because Resolve never instantiates the
comp. A harness that only diffed intent against `GetStart()`/`GetDuration()`
would have called it green. So every case that should be visible also exports
the composited frame with Project.ExportCurrentFrameAsStill and measures its
luma: an inert item yields max=0 over the whole frame, a real one does not.

KNOWN-BROKEN CASES are declared, not skipped. If one starts passing, the harness
says UNEXPECTED PASS and fails — a fix must update the docs that describe it.

Source-safe: synthetic ffmpeg media only, disposable projects, original project
restored on exit.

Run:
  RESOLVE_VERIFY=1 venv/bin/python tests/live_drp_roundtrip_verification.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

sys.path.append(
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"
)

DRP_FORMAT = os.path.join(REPO_ROOT, "resolve-advanced", "vendor", "drp-format")
START = 86400
results = []


# ---------------------------------------------------------------- helpers
def gen_media(tmp):
    """A visibly non-black clip: testsrc2 is colour bars + motion."""
    p = os.path.join(tmp, "src.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=640x360:rate=24:duration=6",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", p],
        check=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p


def author(js, tmp):
    """Run a drp-format authoring snippet in node; it must write `out`."""
    script = f"const drp=require({json.dumps(DRP_FORMAT)});const fs=require('fs');" \
             f"(async()=>{{{js}}})().catch(e=>{{console.error(e.message);process.exit(1)}});"
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, cwd=tmp)
    if r.returncode != 0:
        raise RuntimeError(f"authoring failed: {r.stderr.strip()}")
    return r.stdout.strip()


def luma_stats(png):
    """max luma + count of bright pixels for a composited frame."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", png, "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    if not raw:
        return {"pixels": 0, "max": None, "bright": 0}
    return {"pixels": len(raw), "max": max(raw),
            "bright": sum(1 for b in raw if b > 16)}


def timecode(tl, offset):
    hh, mm, ss, ff = (int(x) for x in tl.GetStartTimecode().split(":"))
    total = ff + offset
    ss += total // 24
    ff = total % 24
    mm += ss // 60
    ss %= 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def check(case, label, got, want, known_broken=False):
    ok = got == want
    results.append({
        "case": case, "assertion": label, "got": got, "want": want,
        "status": ("KNOWN BROKEN" if not ok else "UNEXPECTED PASS") if known_broken
                  else ("PASS" if ok else "FAIL"),
    })


# ---------------------------------------------------------------- main
def main():
    if os.environ.get("RESOLVE_VERIFY") not in ("1", "true", "yes"):
        print("skipped — set RESOLVE_VERIFY=1 to run (needs a live Resolve)")
        return 0

    import DaVinciResolveScript as dvr
    from src.utils.project_cleanup import delete_project_safely

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        print("FATAL: cannot connect to Resolve")
        return 1
    version = resolve.GetVersionString()
    print(f"Resolve {version} / {resolve.GetProductName()}")
    pm = resolve.GetProjectManager()
    original = pm.GetCurrentProject()
    original_name = original.GetName() if original else None

    tmp = tempfile.mkdtemp(prefix="drp_roundtrip_")
    stills = os.path.join(tmp, "stills")
    os.makedirs(stills, exist_ok=True)
    imported = []
    try:
        media = gen_media(tmp)
        spec = '{width:640,height:360,frameCount:144,fps:24}'

        cases = [
            # name, authoring snippet, what to assert after import
            ("media_clip", f"""
             const r=await drp.addMediaClip({{mediaFile:{json.dumps(media)},spec:{spec},
               timelineName:'RT_MEDIA',durationFrames:96}});
             fs.writeFileSync('out.drp', r.buffer);""", "visible"),
            ("split_clip", f"""
             const b=await drp.addMediaClip({{mediaFile:{json.dumps(media)},spec:{spec},
               timelineName:'RT_SPLIT',durationFrames:96}});
             const r=await drp.splitClip(b.buffer,{{track:1,at:{START + 48}}});
             fs.writeFileSync('out.drp', r.buffer);""", "structure"),
            ("trim_clip", f"""
             const b=await drp.addMediaClip({{mediaFile:{json.dumps(media)},spec:{spec},
               timelineName:'RT_TRIM',durationFrames:96}});
             const r=await drp.trimClip(b.buffer,{{track:1,clipIndex:0,newDuration:36}});
             fs.writeFileSync('out.drp', r.buffer);""", "structure"),
            ("move_clip", f"""
             const b=await drp.addMediaClip({{mediaFile:{json.dumps(media)},spec:{spec},
               timelineName:'RT_MOVE',durationFrames:48}});
             const r=await drp.moveClip(b.buffer,{{fromTrack:1,toTrack:2,clipIndex:0,
               toStart:{START + 200}}});
             fs.writeFileSync('out.drp', r.buffer);""", "structure"),
            ("place_generator", """
             const b=await drp.createEmptyProject({timelineName:'RT_GEN'});
             const r=await drp.placeGenerator(b.buffer,{trackIndex:1,startFrame:%d,
               durationFrames:96,generatorName:'SMPTE Color Bar'});
             fs.writeFileSync('out.drp', r.buffer);""" % START, "visible"),
            ("place_fusion_title", """
             const b=await drp.createEmptyProject({timelineName:'RT_TITLE'});
             const r=await drp.placeFusionTitle(b.buffer,{trackIndex:1,startFrame:%d,
               durationFrames:96,name:'RT',text:'ROUNDTRIP'});
             fs.writeFileSync('out.drp', r.buffer);""" % START, "visible_known_broken"),
        ]

        for name, js, mode in cases:
            print(f"\n--- {name}")
            author(js, tmp)
            drp_path = os.path.join(tmp, "out.drp")
            # DeleteProject is documented-flaky, so a previous run can leave the
            # name taken and ImportProject then fails with a bare False. Never
            # collide: try the clean name, and fall back to a run-unique one.
            # Also step off the current project first — project operations are
            # blocked while certain projects are current (see the CreateProject
            # api_truth entry).
            existing = pm.GetProjectListInCurrentFolder() or []
            proj_name = f"ZZ_RT_{name}"
            if proj_name in existing:
                if original_name and original_name != proj_name:
                    pm.LoadProject(original_name)
                pm.DeleteProject(proj_name)
                if proj_name in (pm.GetProjectListInCurrentFolder() or []):
                    proj_name = f"ZZ_RT_{name}_{os.getpid()}"
            if not pm.ImportProject(drp_path, proj_name):
                check(name, "ImportProject", False, True)
                continue
            imported.append(proj_name)
            proj = pm.LoadProject(proj_name)
            tl = proj.GetTimelineByIndex(1)
            proj.SetCurrentTimeline(tl)
            tl = proj.GetCurrentTimeline()

            v1 = tl.GetItemListInTrack("video", 1) or []
            v2 = tl.GetItemListInTrack("video", 2) or []
            if name == "split_clip":
                check(name, "two clips on V1 after blade", len(v1), 2)
                check(name, "second piece starts at the cut",
                      v1[1].GetStart() if len(v1) > 1 else None, START + 48)
            elif name == "trim_clip":
                check(name, "duration after trim",
                      v1[0].GetDuration() if v1 else None, 36)
            elif name == "move_clip":
                check(name, "moved to V2", len(v2), 1)
                check(name, "moved to requested frame",
                      v2[0].GetStart() if v2 else None, START + 200)

            if mode.startswith("visible"):
                item = (v1 or v2)[0]
                resolve.OpenPage("color")
                tl.SetCurrentTimecode(
                    timecode(tl, item.GetStart() - tl.GetStartFrame() + item.GetDuration() // 2))
                png = os.path.join(stills, f"{name}.png")
                proj.ExportCurrentFrameAsStill(png)
                st = luma_stats(png) if os.path.exists(png) else {"max": None, "bright": 0}
                print(f"    frame: max_luma={st['max']} bright_px={st['bright']}")
                visible = bool(st["max"] and st["max"] > 16)
                check(name, "renders something on screen", visible, True,
                      known_broken=mode.endswith("known_broken"))

        print("\n" + "=" * 70)
        print(json.dumps(results, indent=2))
        print("=" * 70)
        bad = [r for r in results if r["status"] in ("FAIL", "UNEXPECTED PASS")]
        for r in results:
            print(f"  [{r['status']:14s}] {r['case']}: {r['assertion']} "
                  f"(got {r['got']!r}, want {r['want']!r})")
        if any(r["status"] == "UNEXPECTED PASS" for r in results):
            print("\nUNEXPECTED PASS — a known-broken case now works. Update the "
                  "api_truth entry and the drp-format README before shipping.")
        print(f"\n{sum(1 for r in results if r['status']=='PASS')} passed, "
              f"{sum(1 for r in results if r['status']=='KNOWN BROKEN')} known-broken, "
              f"{len(bad)} need attention — on {version}")
        return 1 if bad else 0
    finally:
        # Step off whatever we imported BEFORE deleting — DeleteProject cannot
        # remove the current project, and silently leaving litter is how the
        # next run collides on the name.
        try:
            if original_name:
                pm.LoadProject(original_name)
        except Exception:  # noqa: BLE001
            pass
        leftover = []
        for n in imported:
            try:
                res = delete_project_safely(pm, n, switch_to=original_name, retries=3)
                if not res.get("success"):
                    leftover.append(n)
            except Exception:  # noqa: BLE001
                leftover.append(n)
        if leftover:
            print(f"\nWARNING: could not delete {len(leftover)} disposable "
                  f"project(s): {leftover}. DeleteProject is flaky; remove them "
                  f"in the Project Manager or a later run will name around them.")
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
