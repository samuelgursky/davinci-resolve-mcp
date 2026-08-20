"""Live validation for issue #147 — source_* fields on TIMECODED media.

The v2.93.0 source_end fix was validated with synthetic media, which starts at
00:00:00:00. That made the start-timecode offset exactly zero, so a reader
answering in timecode space was indistinguishable from one answering in
file-relative space. On camera footage with time-of-day TC it is not: the whole
start timecode lands in `source_end`.

The design here is a CONTROLLED PAIR: two media files from the same generator,
identical in every respect except that one carries a start timecode. Any
difference in the reported source_* fields is therefore attributable to the
timecode and nothing else. Asserting "source_end equals the endFrame we sent"
would be wrong — when the source and timeline rates differ, the record duration
quantizes to whole timeline frames, so the item consumes slightly fewer source
frames than requested (a 93-frame request at 29.97 into a 24 fps timeline
consumes ~92.4, and Resolve reports 392 for the zero-TC control as well). The
invariant that matters is that the timecode changes nothing.

Run with:  venv/bin/python tests/live_source_timecode_validation.py

Creates a bin and timelines in the CURRENT project and deletes them afterwards.
Synthetic media only; no source media is read, written, or transcoded.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

START_TC = "04:18:37;25"
DURATION_S = 60
BIN_NAME = "ISSUE147_TC_VALIDATION"
RANGES = [(300, 393), (0, 100), (1000, 1500)]

results = []


def check(label, ok, detail=""):
    results.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def make_media(work_dir, name, timecode=None):
    path = os.path.join(work_dir, name)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "lavfi", "-i",
           f"testsrc2=size=320x180:rate=30000/1001:duration={DURATION_S}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if timecode:
        cmd += ["-timecode", timecode]
    cmd.append(path)
    subprocess.run(cmd, check=True)
    return path


def measure(resolve, project, media_pool, clip, label):
    """Append each range and return {sent_range: summary} using LOCAL code."""
    from src.server import _timeline_item_summary

    timeline = media_pool.CreateEmptyTimeline(f"ISSUE147_{label}")
    project.SetCurrentTimeline(timeline)
    out = {}
    for src_start, src_end in RANGES:
        appended = media_pool.AppendToTimeline([{
            "mediaPoolItem": clip, "startFrame": src_start, "endFrame": src_end}])
        if not appended:
            continue
        out[(src_start, src_end)] = _timeline_item_summary(
            appended[0], ("video", 1), media_pool_item=clip)
    return timeline, out


def main():
    from src.server import _media_item_source_fps, get_resolve

    resolve = get_resolve()
    if not resolve:
        print("FATAL: no Resolve connection")
        return 1
    print(f"Resolve: {resolve.GetProductName()} {resolve.GetVersionString()}")

    project = resolve.GetProjectManager().GetCurrentProject()
    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()
    print(f"Project: {project.GetName()}  timeline rate: "
          f"{project.GetSetting('timelineFrameRate')}  "
          f"(source is 29.97 — rates differ on purpose)")

    work_dir = tempfile.mkdtemp(prefix="issue147_")
    created_bin = media_pool.AddSubFolder(root, BIN_NAME)
    media_pool.SetCurrentFolder(created_bin or root)

    measured, clips, timelines = {}, [], []
    for label, timecode in (("ZERO", None), ("TC", START_TC)):
        path = make_media(work_dir, f"issue147_{label.lower()}.mov", timecode)
        items = resolve.GetMediaStorage().AddItemListToMediaPool([path])
        if not items:
            print(f"FATAL: import failed for {label}")
            return 1
        clip = items[0]
        clips.append(clip)
        props = clip.GetClipProperty()
        print(f"\n{label}: FPS={props.get('FPS')} Frames={props.get('Frames')} "
              f"Start TC={props.get('Start TC')}")
        timeline, summaries = measure(resolve, project, media_pool, clip, label)
        timelines.append(timeline)
        measured[label] = (summaries, clip, int(props.get("Frames") or 0),
                           _media_item_source_fps(clip))

    zero_summaries, _, _, _ = measured["ZERO"]
    tc_summaries, tc_clip, tc_frames, fps = measured["TC"]

    check("the control really has no timecode",
          str(measured["ZERO"][1].GetClipProperty("Start TC")).startswith("00:00:00"),
          measured["ZERO"][1].GetClipProperty("Start TC"))
    check("the subject really carries the timecode",
          str(tc_clip.GetClipProperty("Start TC")).replace(":", ";")
          == START_TC.replace(":", ";"),
          tc_clip.GetClipProperty("Start TC"))

    print("\n" + "=" * 78)
    print(f"{'sent':>13} | {'zero-TC':>18} | {'timecoded':>18} | match")
    print("-" * 78)
    for key in RANGES:
        zero, tced = zero_summaries.get(key), tc_summaries.get(key)
        if not zero or not tced:
            check(f"both media produced an item for {key[0]}..{key[1]}", False)
            continue
        z = (zero["source_start"], zero["source_end"])
        t = (tced["source_start"], tced["source_end"])
        print(f"{key[0]:>6}..{key[1]:<5} | {str(z):>18} | {str(t):>18} | {z == t}")

        check(f"{key[0]}..{key[1]}: source_end lies inside the clip",
              tced["source_end"] <= tc_frames,
              f"{tced['source_end']} vs {tc_frames} frames")
        check(f"{key[0]}..{key[1]}: timecode changes nothing", z == t,
              f"zero-TC {z} vs timecoded {t}")
        check(f"{key[0]}..{key[1]}: the frame fields can be differenced",
              tced["source_end"] > tced["source_start"],
              f"span {tced['source_end'] - tced['source_start']}")
        check(f"{key[0]}..{key[1]}: seconds agree with frames (within a frame)",
              abs(tced["source_start_seconds"] * fps - tced["source_start"]) < 1.0
              and abs(tced["source_end_seconds"] * fps - tced["source_end"]) < 1.0,
              f"{tced['source_start_seconds']}s / {tced['source_end_seconds']}s")

        # What the pre-fix formula produced on this same item.
        raw_end = tced["source_end_seconds"]  # already rebased; re-add the offset
        offset = (tc_clip.GetClipProperty("Start TC") or "")
        old = int(round((raw_end + _tc_seconds(offset, fps)) * fps))
        check(f"{key[0]}..{key[1]}: the pre-fix value was outside the clip",
              old > tc_frames, f"pre-fix ~{old} vs {tc_frames} frames")

    try:
        media_pool.DeleteTimelines([tl for tl in timelines if tl])
        media_pool.DeleteClips(clips)
        if created_bin:
            media_pool.DeleteFolders([created_bin])
        media_pool.SetCurrentFolder(root)
        print("\nCleaned up bin, timelines and clips.")
    except Exception as exc:  # noqa: BLE001 — cleanup is best-effort
        print(f"\nWARNING: cleanup incomplete: {exc}")

    failed = [label for label, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
    return 1 if failed else 0


def _tc_seconds(tc, fps):
    """Drop-frame timecode string -> seconds (the media is 29.97 DF)."""
    if not tc:
        return 0.0
    hh, mm, ss, ff = (int(part) for part in str(tc).replace(";", ":").split(":"))
    total_minutes = 60 * hh + mm
    dropped = 2 * (total_minutes - total_minutes // 10)
    return (108000 * hh + 1800 * mm + 30 * ss + ff - dropped) / fps


if __name__ == "__main__":
    sys.exit(main())
