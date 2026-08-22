#!/usr/bin/env python3
"""Why a lock-wrapped Fusion value write is ignored at render, and what undoes it.

This is the isolation harness behind the Composition.Lock entry in api_truth. It
is not a pass/fail regression test - it is the experiment, kept runnable so the
result can be re-checked on another Resolve build instead of taken on trust.

Measured on Studio 19.1.3.7 (2026-08-22):

    U1 locked write, nothing after      SUPPRESSED   (PSNR inf vs baseline)
    U2 ... then an UNLOCKED write       RENDERED     rescued
    U3 StartUndo/.../EndUndo around it  RENDERED     rescued
    U4 ConnectInput inside the lock     SUPPRESSED   does not rescue
    U5 GetInput readback after Unlock   SUPPRESSED   does not rescue

Every case builds its graph through the lock-wrapped fusion_comp add_tool/connect
calls, which is the PRECONDITION: the same locked write against a graph wired by
plain attribute assignment renders normally. That is why raw-API attempts to
reproduce the bug kept coming back green, and why "a lock around a value write"
is necessary but not sufficient.

U3 is what lets bulk_set_inputs and bulk_set_expressions escape the bug - both
wrap their write in StartUndo/EndUndo. add_fusion_mask and set_text_plus also
escape it, for reasons NOT identified here; U4 and U5 were the two obvious
candidates and both were ruled out.

Run against a running Resolve Studio with Python 3.10-3.12:

    python3.11 tests/live_fusion_lock_mechanism_probe.py
"""
import re, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.live_fusion_value_write_validation import _install_mcp_stubs

_install_mcp_stubs()
import src.server as server
import DaVinciResolveScript as bmd

def sh(c): return subprocess.run(c,capture_output=True,text=True)
def psnr(a,b):
    p=sh(["ffmpeg","-hide_banner","-i",str(a),"-i",str(b),"-lavfi","psnr","-f","null","-"])
    m=re.search(r"average:(inf|[0-9.]+)",p.stderr)
    return float("inf") if m.group(1)=="inf" else float(m.group(1))
def render(project,mi,mo,d,name):
    project.SetCurrentRenderFormatAndCodec("mov","H264")
    project.SetRenderSettings({"SelectAllFrames":False,"MarkIn":int(mi),"MarkOut":int(mo),
                               "TargetDir":str(d),"CustomName":name})
    job=project.AddRenderJob(); project.StartRendering([job])
    end=time.time()+300
    while time.time()<end:
        st=(project.GetRenderJobStatus(job) or {}).get("JobStatus")
        if st=="Complete": break
        if st in ("Failed","Cancelled"): raise AssertionError(f"{name}:{st}")
        time.sleep(2)
    project.DeleteRenderJob(job)
    return sorted(Path(d).glob(f"{name}*.mov"))[-1]

r=bmd.scriptapp("Resolve"); pm=r.GetProjectManager()
prev=pm.GetCurrentProject(); prev_name=prev.GetName() if prev else None
work=Path(tempfile.mkdtemp(prefix="mod_"))
sh(["ffmpeg","-hide_banner","-loglevel","error","-f","lavfi",
    "-i","testsrc2=size=1280x720:rate=24:duration=4","-pix_fmt","yuv420p",
    "-c:v","libx264","-g","12","-y",str(work/"s.mov")])
pname=f"_mod_{int(time.time())}"; pm.CreateProject(pname); project=pm.GetCurrentProject()
res={}
try:
    r.OpenPage("edit"); mp=project.GetMediaPool()
    clip=mp.ImportMedia([str(work/"s.mov")])[0]
    def case(tag, fn):
        tl=mp.CreateEmptyTimeline(f"U_{tag}"); project.SetCurrentTimeline(tl)
        s=int(round(float(tl.GetStartFrame())))
        mp.AppendToTimeline([{"mediaPoolItem":clip,"startFrame":0,"endFrame":96,
                              "recordFrame":s,"trackIndex":1,"mediaType":1}])
        item=tl.GetItemListInTrack("video",1)[0]; item.AddFusionComp(); iid=item.GetUniqueId()
        def call(a,pp):
            d={"clip_id":iid,"comp_index":1}; d.update(pp); return server.fusion_comp(a,d)
        call("add_tool",{"tool_type":"Blur","name":"UBlur"})
        call("connect",{"target_tool":"UBlur","input_name":"Input","source_tool":"MediaIn1"})
        call("connect",{"target_tool":"MediaOut1","input_name":"Input","source_tool":"UBlur"})
        base=render(project,s,s+47,work,f"{tag}_base")
        c=item.GetFusionCompByIndex(1); t=c.FindTool("UBlur"); mo_t=c.FindTool("MediaOut1")
        fn(c,t,mo_t)
        v=psnr(base, render(project,s,s+47,work,f"{tag}_out"))
        res[tag]=v
        print(f"  {tag:24} {'SUPPRESSED' if v==float('inf') else f'RENDERED {v:.2f}dB'}")

    case("U1_locked_write_only", lambda c,t,m: (c.Lock(), t.SetInput("XBlurSize",20), c.Unlock()))
    def u2(c,t,m):
        c.Lock(); t.SetInput("XBlurSize",20); c.Unlock(); t.SetInput("XBlurSize",20)
    case("U2_then_unlocked_write", u2)
    def u3(c,t,m):
        c.StartUndo("u"); c.Lock(); t.SetInput("XBlurSize",20); c.Unlock(); c.EndUndo(True)
    case("U3_undo_wrapped", u3)
    def u4(c,t,m):
        c.Lock(); t.SetInput("XBlurSize",20); m.ConnectInput("Input", t); c.Unlock()
    case("U4_structural_after", u4)
    def u5(c,t,m):
        c.Lock(); t.SetInput("XBlurSize",20); c.Unlock(); t.GetInput("XBlurSize")
    case("U5_readback_after", u5)

    print("\n=== SUMMARY ===")
    for k,v in res.items():
        print(f"  {k:24} {'SUPPRESSED' if v==float('inf') else f'RENDERED {v:.2f}dB'}")
finally:
    try:
        if prev_name: pm.LoadProject(prev_name)
        pm.DeleteProject(pname); print("\ncleaned up:",pname)
    except Exception as e: print("cleanup warning:",e)
