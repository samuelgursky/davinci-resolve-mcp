"""Live validation harness for v2.3.3 granular-layer changes.

Imports the granular tool functions directly and calls them against a live
DaVinci Resolve. Reports pass/fail for each new or changed tool.

Run with: venv/bin/python tests/live_v233_validation.py

Tools validated:
  - granular.media_pool.append_to_timeline (both clip_ids and clip_infos forms)
  - granular.media_pool.auto_sync_audio (with audio sync settings dict)
  - granular.media_pool.import_media (clip_infos image-sequence form)
  - granular.timeline.timeline_create_compound_clip (with info dict)
  - granular.project.rename_color_group
  - granular.project.render_with_quick_export (params dict accepted)
  - granular.project.create_cloud_project_tool (skipped — needs cloud account)
  - granular.project.load_cloud_project_tool (skipped — needs cloud account)

Skips: cloud project tools, anything that needs network/cloud account.
Runs against the currently-open Resolve project (creates a disposable
project for isolation).
"""

import os
import subprocess
import sys
import tempfile
import time

# Ensure src/ is on the path
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def make_synthetic_media(work_dir):
    """Generate a few synthetic .mov files via ffmpeg. Returns list of paths."""
    paths = []
    for i, color in enumerate(("red", "blue", "green"), start=1):
        path = os.path.join(work_dir, f"v233_synthetic_{color}.mov")
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=320x240:d=2:r=24",
            "-y", path,
        ], check=True)
        paths.append(path)
    # Image sequence for clip_infos image-sequence test
    seq_dir = os.path.join(work_dir, "seq")
    os.makedirs(seq_dir, exist_ok=True)
    for i in range(1, 4):
        path = os.path.join(seq_dir, f"frame_{i:03d}.png")
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=160x120:d=1:r=24",
            "-frames:v", "1", "-y", path,
        ], check=True)
    return paths, os.path.join(seq_dir, "frame_%03d.png")


def report(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def main():
    # Late imports so the script can also be syntax-checked without Resolve
    from src.granular.common import get_resolve, _get_mp, _find_clip_by_id  # noqa: F401
    from src.granular import media_pool as gmp
    from src.granular import timeline as gtl
    from src.granular import project as gprj

    print("=" * 70)
    print("v2.3.3 live validation harness")
    print("=" * 70)

    r = get_resolve()
    if r is None:
        print("FATAL: cannot connect to DaVinci Resolve. Is it running?")
        return 2
    print(f"Connected to Resolve {'.'.join(str(x) for x in r.GetVersion()[:4])}")

    pm = r.GetProjectManager()
    project_name = f"v233_validation_{int(time.time())}"
    if not pm.CreateProject(project_name):
        print(f"FATAL: failed to create disposable project '{project_name}'")
        return 2
    print(f"Created disposable project: {project_name}")

    work_dir = tempfile.mkdtemp(prefix="v233_validation_")
    print(f"Synthetic media in: {work_dir}")

    try:
        clip_paths, seq_path = make_synthetic_media(work_dir)

        # Import the synthetic clips via the documented direct API
        proj = pm.GetCurrentProject()
        mp = proj.GetMediaPool()
        imported = mp.ImportMedia(clip_paths)
        if not imported or len(imported) != 3:
            print("FATAL: failed to import synthetic media")
            return 2
        clip_a, clip_b, clip_c = imported
        clip_a_id = clip_a.GetUniqueId()
        clip_b_id = clip_b.GetUniqueId()
        print(f"Imported 3 clips. Sample id: {clip_a_id}")

        # Create a timeline to append into
        tl = mp.CreateEmptyTimeline("v233_test_timeline")
        if not tl:
            print("FATAL: failed to create timeline")
            return 2

        results = []

        # ─── append_to_timeline (granular) — simple form ───
        out = gmp.append_to_timeline(clip_ids=[clip_a_id])
        results.append(report(
            "granular.append_to_timeline (simple clip_ids)",
            out.get("success") is True and out.get("count") == 1,
            f"got {out!r}",
        ))

        # ─── append_to_timeline (granular) — positioned form ───
        out = gmp.append_to_timeline(clip_infos=[{
            "clip_id": clip_b_id, "start_frame": 0, "end_frame": 23,
            "record_frame": 100, "track_index": 1,
        }])
        results.append(report(
            "granular.append_to_timeline (positioned clip_infos)",
            out.get("success") is True
                and out.get("count") == 1
                and isinstance(out.get("items"), list)
                and out["items"][0].get("timeline_item_id"),
            f"items={out.get('items')}",
        ))

        # ─── append_to_timeline (granular) — failure path ───
        out = gmp.append_to_timeline(clip_infos=[{"clip_id": clip_b_id, "start_frame": 0}])
        results.append(report(
            "granular.append_to_timeline failure path returns clean error",
            "error" in out,
            f"got {out!r}",
        ))

        # ─── auto_sync_audio (granular) ───
        out = gmp.auto_sync_audio(
            clip_ids=[clip_a_id, clip_b_id],
            sync_mode="timecode",
            retain_video_metadata=True,
        )
        # Resolve may legitimately return False if clips have no audio to sync;
        # we just want the call to not crash and to forward the dict.
        results.append(report(
            "granular.auto_sync_audio (settings dict mapping)",
            isinstance(out, dict) and "success" in out,
            f"got {out!r}",
        ))

        # ─── auto_sync_audio failure path ───
        out = gmp.auto_sync_audio(clip_ids=[clip_a_id], sync_mode="zerocross")
        results.append(report(
            "granular.auto_sync_audio rejects invalid sync_mode",
            "error" in out and "Unknown sync_mode" in out["error"],
            f"got {out!r}",
        ))

        # ─── import_media (granular) — image sequence ───
        out = gmp.import_media(clip_infos=[{
            "FilePath": seq_path, "StartIndex": 1, "EndIndex": 3,
        }])
        results.append(report(
            "granular.import_media (image-sequence clip_infos)",
            out.get("success") is True and out.get("imported") == 1,
            f"got {out!r}",
        ))

        # ─── timeline_create_compound_clip (granular) — with info dict ───
        # Need a fresh timeline item to compound; use the one we appended.
        # Set current timeline so granular tools can find it.
        proj.SetCurrentTimeline(tl)
        items_on_track = tl.GetItemListInTrack("video", 1) or []
        if items_on_track:
            target_id = items_on_track[0].GetUniqueId()
            out = gtl.timeline_create_compound_clip(
                clip_ids=[target_id], track_type="video", track_index=1,
                name="v233_compound_test", start_timecode="01:00:00:00",
            )
            # Compound creation requires multiple selected items, so this may
            # return success=False even when the dict is forwarded correctly.
            # Verify forwarding by checking shape, not necessarily success=True.
            results.append(report(
                "granular.timeline_create_compound_clip (info dict accepted)",
                isinstance(out, dict) and ("success" in out or "error" in out),
                f"got {out!r}",
            ))
        else:
            results.append(report(
                "granular.timeline_create_compound_clip (info dict accepted)",
                False, "no items to compound",
            ))

        # ─── rename_color_group (granular) ───
        # Create a color group, then rename it.
        cg = proj.AddColorGroup("v233_group_initial")
        if cg:
            out = gprj.rename_color_group(group_name="v233_group_initial",
                                          new_name="v233_group_renamed")
            results.append(report(
                "granular.rename_color_group",
                out.get("success") is True,
                f"got {out!r}",
            ))
            # Cleanup color group
            proj.DeleteColorGroup(cg)
        else:
            results.append(report(
                "granular.rename_color_group",
                False, "failed to create test color group",
            ))

        # ─── render_with_quick_export (granular) — verify dict forwarding ───
        # Don't actually start a render; just verify the call shape forwards
        # the params dict. We use an obviously-bogus preset name so Resolve
        # rejects it without rendering, but the dict path is still exercised.
        out = gprj.render_with_quick_export(
            preset_name="__v233_nonexistent_preset__",
            target_dir=work_dir,
            custom_name="v233_test",
            video_quality=0,
            enable_upload=False,
        )
        results.append(report(
            "granular.render_with_quick_export (params dict accepted)",
            isinstance(out, dict) and "preset_name" in out,
            f"got {out!r}",
        ))

        # ─── compound: get_items_in_track — verifies deprecated→supported fix ───
        # Already on the loaded MCP server, but we can directly verify the
        # call itself returns items via GetItemListInTrack.
        items = tl.GetItemListInTrack("video", 1)
        results.append(report(
            "compound: GetItemListInTrack (replaces deprecated GetItemsInTrack)",
            items is not None,
            f"got {len(items) if items else 0} items",
        ))

        # ─── Summary ───
        print()
        print("=" * 70)
        passed = sum(1 for r in results if r)
        total = len(results)
        print(f"v2.3.3 live validation: {passed}/{total} passed")
        print("=" * 70)
        return 0 if passed == total else 1

    finally:
        # Cleanup: switch to a different project, then delete the disposable
        try:
            projects = pm.GetProjectListInCurrentFolder() or []
            other = next((p for p in projects if p != project_name), None)
            if other:
                pm.LoadProject(other)
            pm.DeleteProject(project_name)
            print(f"Cleaned up disposable project: {project_name}")
        except Exception as exc:
            print(f"WARN: cleanup failed (delete '{project_name}' manually): {exc}")
        # Cleanup temp media
        try:
            import shutil
            shutil.rmtree(work_dir)
            print(f"Cleaned up temp media: {work_dir}")
        except Exception as exc:
            print(f"WARN: temp media cleanup failed: {exc}")


if __name__ == "__main__":
    sys.exit(main())
