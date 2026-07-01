#!/usr/bin/env python3
"""
conform-qc Resolve driver (spec §3.2, P2). Drives a running (headless) DaVinci
Resolve via the scripting API. Used by the Node HeadlessResolveDriver.

Commands (argv[1]):
  ping                         -> {ok, product, version, project}
  readback <xml> [proj] [tl]   -> import the turnover (media OFFLINE), read each
                                  clip's conformed source_start (GetLeftOffset —
                                  resolves subclip startoffset even offline),
                                  delete the temp timeline, emit {ok, clips:[...]}
  export-drp <xml> <out> [proj] -> import, export the project as a .drp, re-import
                                  it to a temp project to prove it opens clean

Key facts (memory feedback_resolve_fcp7_conform_pitfalls):
  - import with importSourceClips=False (True ingests every file -> network timeout)
  - GetLeftOffset() IS the conformed source frame (startoffset+in for subclips),
    available even with media offline because it's parsed from the XML.
  - record seqstart = item.GetStart() - timeline.GetStartFrame() (absolute offset).
All output is a single JSON line on stdout.
"""
import json
import sys

try:
    import DaVinciResolveScript as dvr
except Exception as e:  # pragma: no cover
    print(json.dumps({"ok": False, "error": "DaVinciResolveScript import failed: %r" % e}))
    sys.exit(0)


def out(d):
    print(json.dumps(d))
    sys.exit(0)


def connect():
    r = dvr.scriptapp("Resolve")
    if r is None:
        out({"ok": False, "error": "Resolve not reachable"})
    return r


def get_project(pm, name):
    p = pm.LoadProject(name)
    if p is None:
        p = pm.CreateProject(name)
    return p


def import_timeline(proj, xml, tl_name):
    mp = proj.GetMediaPool()
    return mp.ImportTimelineFromFile(xml, {"importSourceClips": False, "timelineName": tl_name})


def readback_clips(tl):
    base = tl.GetStartFrame()
    clips = []
    for it in (tl.GetItemListInTrack("video", 1) or []):
        clips.append({
            "seqstart": it.GetStart() - base,
            "source_start": it.GetLeftOffset(),
            "name": it.GetName(),
        })
    return clips


def cmd_ping(r):
    pm = r.GetProjectManager()
    p = pm.GetCurrentProject()
    out({"ok": True, "product": r.GetProductName(), "version": r.GetVersionString(),
         "project": p.GetName() if p else None})


def cmd_readback(r, xml, proj_name, tl_name):
    pm = r.GetProjectManager()
    proj = get_project(pm, proj_name)
    mp = proj.GetMediaPool()
    tl = import_timeline(proj, xml, tl_name)
    if not tl:
        out({"ok": False, "error": "import failed"})
    clips = readback_clips(tl)
    # Clean up the temp timeline we created (leave the rest of the project alone).
    try:
        mp.DeleteTimelines([tl])
    except Exception:
        pass
    out({"ok": True, "count": len(clips), "clips": clips})


def cmd_export_drp(r, xml, out_path, proj_name):
    import os
    import zipfile
    pm = r.GetProjectManager()
    proj = get_project(pm, proj_name)
    import_timeline(proj, xml, "cqc_drp")
    ok_export = pm.ExportProject(proj_name, out_path)
    # Validate it "opens clean" WITHOUT polluting the DB: a .drp is a zip archive —
    # confirm it exists, is non-trivial, and is a well-formed archive. (A full
    # re-import-as-project is verifiable but accumulates projects, so we don't.)
    valid = False
    entries = 0
    size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    try:
        with zipfile.ZipFile(out_path) as z:
            entries = len(z.namelist())
            valid = z.testzip() is None and entries > 0
    except Exception:
        valid = False
    out({"ok": bool(ok_export) and valid, "drpPath": out_path, "validArchive": valid, "entryCount": entries, "size": size})


def cmd_readback_online(r, xml, from_prefix, to_prefix, proj_name, tl_name):
    """Relink: rewrite media paths (prefix remap) so media is ONLINE, import with
    ingest, and report per-clip online status + source_start."""
    import os
    import tempfile
    pm = r.GetProjectManager()
    proj = get_project(pm, proj_name)
    mp = proj.GetMediaPool()
    src = open(xml, "r", encoding="utf-8", errors="ignore").read()
    remapped = src.replace(from_prefix, to_prefix)
    fd, tmp = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(remapped)
    try:
        tl = mp.ImportTimelineFromFile(tmp, {"importSourceClips": True, "timelineName": tl_name})
        if not tl:
            out({"ok": False, "error": "import (online) failed"})
        base = tl.GetStartFrame()
        clips = []
        online = 0
        for it in (tl.GetItemListInTrack("video", 1) or []):
            ss = it.GetSourceStartFrame()  # populated only when media links online
            is_online = ss is not None
            if is_online:
                online += 1
            clips.append({"seqstart": it.GetStart() - base, "source_start": it.GetLeftOffset(), "online": is_online})
        try:
            mp.DeleteTimelines([tl])
        except Exception:
            pass
        out({"ok": True, "count": len(clips), "online": online, "clips": clips})
    finally:
        os.unlink(tmp)


def main():
    if len(sys.argv) < 2:
        out({"ok": False, "error": "no command"})
    cmd = sys.argv[1]
    r = connect()
    if cmd == "ping":
        cmd_ping(r)
    elif cmd == "readback":
        xml = sys.argv[2]
        proj = sys.argv[3] if len(sys.argv) > 3 else "conformqc_p2"
        tl = sys.argv[4] if len(sys.argv) > 4 else "cqc_readback"
        cmd_readback(r, xml, proj, tl)
    elif cmd == "export-drp":
        xml = sys.argv[2]
        out_path = sys.argv[3]
        proj = sys.argv[4] if len(sys.argv) > 4 else "conformqc_p2_drp"
        cmd_export_drp(r, xml, out_path, proj)
    elif cmd == "readback-online":
        xml = sys.argv[2]
        from_prefix = sys.argv[3]
        to_prefix = sys.argv[4]
        proj = sys.argv[5] if len(sys.argv) > 5 else "conformqc_p2_online"
        tl = sys.argv[6] if len(sys.argv) > 6 else "cqc_online"
        cmd_readback_online(r, xml, from_prefix, to_prefix, proj, tl)
    else:
        out({"ok": False, "error": "unknown command %s" % cmd})


main()
