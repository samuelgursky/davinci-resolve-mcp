#!/usr/bin/env python3
"""Live validation for the DRX apply readback and timeline refusal (issues #318, #319).

Requires DaVinci Resolve Studio running with external scripting set to Local.
Creates a disposable project from one synthetic clip (pass --media), then:

  1. applies a .drx whose <pTrackVer> carries the grade to the TIMELINE graph
     through graph.apply_grade_from_drx; where Resolve applies it the readback
     must report [timeline], and where it returns False (every timeline apply on
     Studio 19.1.3.7) it must report no change;
  2. applies a native .drx (empty <pTrackVer>) to the timeline and expects
     DRX_NO_TIMELINE_GRADE with the timeline graph untouched;
  3. measures the premise with the raw API: the same empty .drx applied
     directly to the timeline graph (reported to empty it on Studio 21.1.1.10);
  4. applies the native .drx to the clip and expects changed_graphs == [item];
  5. re-applies it and records whether any graph changed (a same-structure
     apply may change only parameters, which no readback reaches);
  6. puts the clip in a color group and applies again through
     timeline_item_color.safe_apply_drx, recording which graph changed.

Steps 3, 5 and 6 record what this build does rather than assert it. On
Studio 19.1.3.7 (2026-10-27) every timeline apply returned False and changed
nothing, and a grouped clip's grade landed in the clip graph. The
disposable project is deleted at the end unless --keep-open is passed.

Run:
  env RESOLVE_SCRIPT_API=... RESOLVE_SCRIPT_LIB=... PYTHONPATH=.../Modules \\
    venv/bin/python tests/live_drx_apply_readback_validation.py --media /path/to/synthetic.mov
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "resolve-advanced/vendor/drx-codec/__tests__/fixtures/p2-1-face-refinement.drx"
ITEM = {"track_type": "video", "track_index": 1, "item_index": 0}


def _install_mcp_stubs() -> None:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from src.utils.mcp_import_stubs import install_mcp_stubs

    install_mcp_stubs(stdio_note="stdio_server is not used by this live harness")


def _with_track_grade(native: str) -> str:
    """The clip grade copied into <pTrackVer> (VerType 1), clip part marked empty."""
    clip = re.search(r"<pClipFullVer>(.*?)</pClipFullVer>", native, re.DOTALL).group(1)
    track = clip.replace("<VerType>0</VerType>", "<VerType>1</VerType>")
    clip_off = clip.replace("<HasCorrection>true</HasCorrection>", "<HasCorrection>false</HasCorrection>")
    out = native.replace(clip, clip_off, 1)
    if "<pTrackVer>" not in out:   # drx generate's single-node path writes none
        return out.replace("</pClipFullVer>", f"</pClipFullVer>\n <pTrackVer>{track}</pTrackVer>", 1)
    return re.sub(r"<pTrackVer>.*?</pTrackVer>", lambda _m: f"<pTrackVer>{track}</pTrackVer>",
                  out, count=1, flags=re.DOTALL)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--media", required=True, help="synthetic clip to build the disposable project from")
    ap.add_argument("--drx", default=str(FIXTURE),
                    help="clip grade to apply; use one in this build's format (drx generate writes "
                         "19.1.3's) whose node label differs from an empty node, so a change shows")
    ap.add_argument("--keep-open", action="store_true")
    args = ap.parse_args()

    _install_mcp_stubs()
    import src.server as server

    server._confirm_token_required = lambda: False   # harness only; the token flow has its own tests

    resolve = server.get_resolve()
    if resolve is None:
        print("CANNOT RUN: no Resolve connection")
        return 2
    pm = resolve.GetProjectManager()
    print("Resolve", resolve.GetVersionString())

    work = Path(tempfile.mkdtemp(prefix="drx_readback_"))
    native_text = Path(args.drx).read_text(encoding="utf-8")
    native = work / "native_empty_track.drx"
    native.write_text(native_text, encoding="utf-8")
    track = work / "with_track_grade.drx"
    track.write_text(_with_track_grade(native_text), encoding="utf-8")

    start = pm.GetCurrentProject()
    start_name = start.GetName() if start else None
    if start is not None:
        pm.SaveProject()
    name = f"MCP_DRX_Readback_{int(time.time())}"
    proj = pm.CreateProject(name)
    if not proj:
        print("CANNOT RUN: CreateProject failed")
        return 2
    results, failures = {}, []

    def check(label, ok, detail):
        results[label] = {"pass": bool(ok), "detail": detail}
        if not ok:
            failures.append(label)
        print(("PASS " if ok else "FAIL ") + label + ": " + json.dumps(detail, default=str)[:600])

    def record(label, detail):
        results[label] = {"recorded": detail}
        print("INFO " + label + ": " + json.dumps(detail, default=str)[:600])

    try:
        mp = proj.GetMediaPool()
        clips = []
        for _ in range(10):          # a just-created project can refuse the first import
            clips = mp.ImportMedia([args.media]) or []
            if clips:
                break
            time.sleep(1)
        if not clips:
            raise RuntimeError(f"ImportMedia failed for {args.media}")
        tl = mp.CreateTimelineFromClips("Readback", clips)
        if not tl:
            raise RuntimeError("CreateTimelineFromClips failed")
        proj.SetCurrentTimeline(tl)
        resolve.OpenPage("color")
        item = tl.GetItemListInTrack("video", 1)[0]
        tl_count = lambda: tl.GetNodeGraph().GetNumNodes()

        # 1. timeline apply with a real timeline grade
        before = tl_count()
        out = server.graph("apply_grade_from_drx", {"path": str(track), "source": "timeline"})
        # Studio 19.1.3.7 returns False for every timeline-graph apply; the
        # readback must then report no change. Where it applies, it must say so.
        consistent = (out.get("changed_graphs") == ["timeline"]) if out.get("success") else \
            (out.get("changed_graphs") == [] and tl_count() == before)
        check("timeline apply with track grade: readback agrees with Resolve's return", consistent,
              {"before": before, "after": tl_count(), "success": out.get("success"),
               "changed_graphs": out.get("changed_graphs")})

        # 2. refusal
        before = tl_count()
        out = server.graph("apply_grade_from_drx", {"path": str(native), "source": "timeline"})
        code = (out.get("error") or {}).get("code")
        check("timeline apply refused for empty track grade",
              code == "DRX_NO_TIMELINE_GRADE" and tl_count() == before,
              {"before": before, "after": tl_count(), "code": code})

        # 3. premise, raw API
        before = tl_count()
        raw = tl.GetNodeGraph().ApplyGradeFromDRX(str(native), 0)
        record("raw timeline apply of empty track grade (premise)",
               {"returned": raw, "nodes_before": before, "nodes_after": tl_count()})

        # 4. clip apply
        out = server.graph("apply_grade_from_drx", {**ITEM, "path": str(native), "source": "item"})
        check("clip apply reports the item graph changed",
              out.get("success") and "item" in out.get("changed_graphs", []), out)

        # 5. same-structure re-apply
        out = server.graph("apply_grade_from_drx", {**ITEM, "path": str(native), "source": "item"})
        record("same-structure re-apply", {k: out.get(k) for k in ("success", "changed_graphs", "warning", "graphs")})

        # 6. clip in a color group, through safe_apply_drx
        group = proj.AddColorGroup("Readback group")
        assigned = bool(group and item.AssignToColorGroup(group))
        server.graph("reset_all_grades", {**ITEM, "source": "item"})
        out = server.timeline_item_color("safe_apply_drx", {**ITEM, "path": str(native), "source": "item",
                                                            "require_temp_path": False})
        record("grouped clip apply (safe_apply_drx)",
               {"assigned_to_group": assigned,
                **{k: out.get(k) for k in ("success", "changed_graphs", "graphs", "warning")},
                "error": (out.get("error") or {}).get("code")})
        check("grouped clip apply readback covers group graphs",
              {"color_group_pre", "color_group_post"} <= set(out.get("graphs") or {}), out.get("graphs"))
    finally:
        if args.keep_open:
            print(f"kept open: {name}")
        else:
            # DeleteProject refuses the current project, so load another first.
            if start_name and start_name != name:
                pm.LoadProject(start_name)
            else:
                pm.CloseProject(proj)
            print("deleted disposable project:", bool(pm.DeleteProject(name)))

    print(f"\n{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
