#!/usr/bin/env python3
"""Live validation for the Phase E edit engine (selects / tighten / swap).

Creates a DISPOSABLE Resolve project with synthetic media (ffmpeg testsrc +
macOS `say` speech), analyzes it headlessly, commits synthetic vision, then
runs all three loops end-to-end through the real MCP tool functions:

  plan_selects → execute_selects   (new timeline, additive)
  plan_tighten → execute_tighten   (lifts applied to a DUPLICATE)
  plan_swap    → execute_swap      (item replaced in place)

Never touches source media destructively; the pilot project is deleted at
the end (best effort — DeleteProject is flaky on some builds). The user's
current project is restored.

Run: venv/bin/python tests/live_edit_engine_validation.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PILOT = f"edit_engine_pilot_{time.strftime('%H%M%S')}"
MEDIA_DIR = tempfile.mkdtemp(prefix="drm-edit-engine-media-")

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def synth_clip(name: str, *, speech: str, speech_at: float, duration: float, pattern: str) -> str:
    """Synthetic clip: testsrc video + silence with a spoken phrase at speech_at."""
    aiff = os.path.join(MEDIA_DIR, f"{name}.aiff")
    subprocess.run(["say", "-o", aiff, speech], check=True)
    out = os.path.join(MEDIA_DIR, f"{name}.mp4")
    delay_ms = int(speech_at * 1000)
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"{pattern}=duration={duration}:size=640x360:rate=24",
        "-i", aiff,
        "-filter_complex", f"[1:a]adelay={delay_ms}|{delay_ms},apad[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-t", str(duration),
        out,
    ], check=True, capture_output=True)
    return out


def main() -> int:
    print(f"media dir: {MEDIA_DIR}")
    clip_talk = synth_clip("talk_clip", speech="This is the main interview line for the pilot, spoken at the start.",
                           speech_at=1.0, duration=20.0, pattern="testsrc")
    clip_alt = synth_clip("alt_clip", speech="Alternate coverage line.", speech_at=1.0,
                          duration=26.0, pattern="smptebars")

    import src.server as s
    from src.utils import media_analysis as ma
    from src.utils import analysis_store, embeddings

    r = s.get_resolve()
    if r is None:
        print("Resolve not available — aborting")
        return 2
    pm = r.GetProjectManager()
    previous_project = pm.GetCurrentProject().GetName() if pm.GetCurrentProject() else None
    print(f"previous project: {previous_project}")

    proj = pm.CreateProject(PILOT)
    check("disposable project created", proj is not None, PILOT)
    if proj is None:
        return 2
    mp = proj.GetMediaPool()
    imported = mp.ImportMedia([clip_talk, clip_alt])
    check("media imported", bool(imported) and len(imported) == 2)
    by_path = {}
    for item in imported or []:
        by_path[item.GetClipProperty("File Path")] = item

    try:
        # ── headless analysis (technical + transcript; vision committed below) ──
        records = []
        for path, item in by_path.items():
            records.append({
                "clip_id": item.GetUniqueId(),
                "clip_name": item.GetName(),
                "file_path": path,
                "fps": 24.0,
            })
        pilot_project_id = proj.GetUniqueId() if hasattr(proj, "GetUniqueId") else None
        plan = ma.build_plan(
            project_name=PILOT,
            project_id=pilot_project_id,
            records=records,
            target={"type": "paths", "paths": [r["file_path"] for r in records]},
            params={"depth": "standard", "transcription": {"enabled": True, "allow_model_download": True},
                    "vision": {"enabled": False}},
        )
        check("analysis plan", plan.get("success"), str(plan.get("error") or ""))
        manifest = asyncio.run(ma.execute_plan_async(plan, params={
            "depth": "standard", "transcription": {"enabled": True, "allow_model_download": True}}))
        check("analysis executed", manifest.get("success"),
              f"clips={manifest.get('successful_clip_count')}")
        out_root = manifest["project_root"]
        print(f"analysis root: {out_root}")

        # ── synthetic vision commit (select potential + shots) ──
        for row in manifest["clips"]:
            record = row["record"]
            is_talk = "talk" in str(record.get("clip_name"))
            with open(row["analysis_json"]) as fh:
                report = json.load(fh)
            duration = (report.get("cut_analysis") or {}).get("duration_seconds") or 20.0
            visual = {
                "clip_summary": f"Synthetic pilot clip {record['clip_name']}.",
                "editorial_classification": {
                    "primary_use": "interview" if is_talk else "b_roll",
                    "select_potential": "high" if is_talk else "medium",
                },
                "editing_notes": {"search_tags": ["pilot"], "best_moments": [], "continuity_flags": [], "qc_flags": []},
                "shot_descriptions": [{
                    "shot_index": 1,
                    "time_seconds_start": 0.0,
                    "time_seconds_end": float(duration),
                    "description": "Full synthetic take." if is_talk else "Alternate synthetic take.",
                    "qc_flags": [],
                    "editorial": {"select_potential": "high" if is_talk else "medium",
                                  "editorial_role": "coverage", "best_moment_present": False,
                                  "best_moment": None, "pacing": "moderate"},
                }],
            }
            commit = ma.commit_visual_analysis(
                project_root=out_root, visual=visual, clip_id=record["clip_id"])
            check(f"vision committed: {record['clip_name']}", commit.get("success"),
                  str(commit.get("error") or ""))

        # ── visual embeddings for the swap loop ──
        built = embeddings.build_embeddings(out_root, kinds=("visual",), max_frames_per_clip=8)
        check("visual embeddings", built.get("success"),
              json.dumps(built.get("visual") or built.get("error")))

        # ── E1: selects ──
        plan1 = s.edit_engine("plan_selects", {"min_select_potential": "medium",
                                               "timeline_name": "Pilot Selects"})
        check("plan_selects", plan1.get("success") and plan1.get("decision_count", 0) >= 2,
              f"decisions={plan1.get('decision_count')}")
        gate = s.edit_engine("execute_selects", {"plan_id": plan1["plan_id"]})
        check("execute_selects gated", gate.get("status") == "confirmation_required")
        done1 = s.edit_engine("execute_selects", {"plan_id": plan1["plan_id"],
                                                  "confirm_token": gate.get("confirm_token")})
        check("execute_selects", done1.get("success"),
              f"timeline={done1.get('timeline_name')} appended={done1.get('appended')} readback={done1.get('readback')}")

        # ── E2: tighten (talk clip has dead air after ~5s of speech) ──
        # Build a dedicated timeline with just the talk clip.
        talk_item = by_path[clip_talk if clip_talk in by_path else ma.normalize_path(clip_talk)]
        tl2 = mp.CreateTimelineFromClips("Pilot Tighten Base", [talk_item])
        check("tighten base timeline", tl2 is not None)
        proj.SetCurrentTimeline(tl2)
        plan2 = s.edit_engine("plan_tighten", {"min_pause_seconds": 2.0})
        check("plan_tighten", plan2.get("success") and plan2.get("lift_count", 0) >= 1,
              f"lifts={plan2.get('lift_count')} est_removed={plan2.get('estimated_removed_seconds')}s "
              f"skipped={plan2.get('skipped')}")
        if plan2.get("success"):
            gate2 = s.edit_engine("execute_tighten", {"plan_id": plan2["plan_id"]})
            check("execute_tighten gated", gate2.get("status") == "confirmation_required")
            done2 = s.edit_engine("execute_tighten", {"plan_id": plan2["plan_id"],
                                                      "confirm_token": gate2.get("confirm_token")})
            removed = (done2.get("readback") or {}).get("removed_seconds")
            after_dur = ((done2.get("readback") or {}).get("after") or {}).get("duration_seconds")
            check("execute_tighten",
                  done2.get("success") and (removed or 0) > 5.0 and (after_dur or 0) > 1.0,
                  f"variant={done2.get('variant_timeline')} removed={removed}s kept={after_dur}s "
                  f"lifts={done2.get('lifts_applied')}")
            original, _ = s._find_timeline_by_name(proj, "Pilot Tighten Base")
            check("original untouched", original is not None)
            # Phase 2 hardening: readback carries a cross-name structural diff.
            sdiff = (done2.get("readback") or {}).get("structural_diff") or {}
            sdiff_summary = sdiff.get("summary") or {}
            check("tighten structural diff in readback",
                  bool(sdiff_summary) and sdiff_summary.get("before_clip_count", 0) >= 1
                  and not sdiff.get("error"),
                  f"summary={sdiff_summary}")
            # And the standalone action agrees with the readback.
            live_diff = s.timeline_versioning("diff_timelines", {
                "from_timeline": "Pilot Tighten Base",
                "to_timeline": done2.get("variant_timeline"),
            })
            check("diff_timelines action",
                  live_diff.get("success") and live_diff.get("summary") == sdiff_summary,
                  f"summary={live_diff.get('summary')}")
            # #67: the tightened variant must carry audio, not come out silent.
            t_acct = (done2.get("readback") or {}).get("audio_accounting") or {}
            check("tighten variant carries audio",
                  t_acct.get("variant_audio_items", 0) >= 1
                  and t_acct.get("planned_audio_ranges", 0) >= 1,
                  f"audio_accounting={t_acct}")
            v_tl, _ = s._find_timeline_by_name(proj, done2.get("variant_timeline"))
            if v_tl is not None:
                audio_items = v_tl.GetItemListInTrack("audio", 1) or []
                check("tighten variant A1 not empty", len(audio_items) >= 1,
                      f"A1 items={len(audio_items)}")

        # ── E3: swap (replace the selects timeline's first item) ──
        selects_tl, _ = s._find_timeline_by_name(proj, done1.get("timeline_name"))
        proj.SetCurrentTimeline(selects_tl)
        items = s._edit_engine_collect_items(selects_tl)
        # Swap the talk item: its 20s slot can be filled by the 26s alternate.
        first = next(r for r in items if "talk" in str(r.get("item_name")))
        plan3 = s.edit_engine("plan_swap", {"timeline_start_frame": first["timeline_start_frame"],
                                            "kind": "visual", "limit": 3})
        check("plan_swap", plan3.get("success") and bool(plan3.get("alternates")),
              f"alternates={len(plan3.get('alternates') or [])} error={plan3.get('error')} "
              f"first_item={first}")
        if plan3.get("success"):
            gate3 = s.edit_engine("execute_swap", {"plan_id": plan3["plan_id"], "alternate_index": 0})
            check("execute_swap gated", gate3.get("status") == "confirmation_required")
            done3 = s.edit_engine("execute_swap", {"plan_id": plan3["plan_id"], "alternate_index": 0,
                                                   "confirm_token": gate3.get("confirm_token")})
            check("execute_swap", done3.get("success"),
                  f"replacement={done3.get('replacement')} readback={done3.get('readback')}")
            # Phase 2 hardening: per-track-type symmetry. The replacement
            # appends linked video+audio after a video + linked-audio lift,
            # so item counts per track type must be unchanged.
            rb = done3.get("readback") or {}
            counts_before = (rb.get("before") or {}).get("track_counts") or {}
            counts_after = (rb.get("after") or {}).get("track_counts") or {}
            accounting = rb.get("audio_accounting") or {}
            check("swap track-count symmetry",
                  bool(counts_before) and counts_before == counts_after,
                  f"before={counts_before} after={counts_after} accounting={accounting}")
            check("swap lifted linked audio explicitly",
                  accounting.get("video_items_lifted", 0) >= 1
                  and accounting.get("audio_items_lifted", 0) >= 1,
                  f"accounting={accounting}")

        # ── readback: brain_edits rows with rationale ──
        from src.utils import timeline_brain_db
        conn = timeline_brain_db.connect(out_root)
        rows = conn.execute(
            "SELECT edit_type, rationale FROM brain_edits WHERE edit_type LIKE 'edit_engine.%' ORDER BY id"
        ).fetchall()
        kinds = sorted({str(r["edit_type"]) for r in rows})
        check("brain_edits rationale rows", len(rows) >= 3, f"kinds={kinds}")
        archived = conn.execute("SELECT COUNT(*) FROM timeline_versions").fetchone()[0]
        check("timeline versions archived", archived >= 1, f"versions={archived}")

    finally:
        try:
            from src.utils.project_cleanup import delete_project_safely
            outcome = delete_project_safely(pm, PILOT, switch_to=previous_project)
            if outcome["success"]:
                print(f"cleanup: previous project restored; pilot deleted "
                      f"(attempts={outcome['attempts']})")
            else:
                print(f"cleanup warning: disposable project '{outcome['leftover']}' "
                      f"left in library ({outcome['detail']}) — delete it manually")
        except Exception as exc:
            print(f"cleanup warning: {exc}")

    failures = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
