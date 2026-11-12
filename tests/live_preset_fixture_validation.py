"""Live validation of the preset and media rows marked "needs fixture".

``docs/reference/api-coverage.md`` marks these rows ⚠️ because the call was only
made without the context it needs (no preset file, no offline clip, no matching
audio). This harness builds that context from synthetic files and runs each call
for real:

  1. ``SaveLayoutPreset`` on a fresh name, then on the same name again (the
     conflict case), checked against ``GetLayoutPresetList``.
  2. Render presets: ``Project.SaveAsNewRenderPreset`` creates one, then
     ``ExportRenderPreset`` -> ``DeleteRenderPreset`` -> ``ImportRenderPreset``
     -> delete. Both preset exports treat their path as a folder and write
     ``<name>.xml`` inside it (21.0.4.5), so the harness checks that file.
  3. Burn-in presets: no scripting call creates one, so with ``--burnin-wait N``
     the harness waits for a person to save one named ``ZZ_r2104_burnin`` in
     Workspace > Data Burn-In. Then ``ExportBurnInPreset`` -> a real
     ``DeleteBurnInPreset`` -> ``ImportBurnInPreset`` -> delete. Presets that
     existed before the run are never deleted.
  4. In a disposable project: ``RelinkClips`` on a clip whose file was moved,
     and ``AutoSyncAudio`` on a video and a separate audio file that share a
     noise track (checked through the "Synced Audio" clip property, because the
     return value alone is not reliable). Over the in-app bridge this needs the
     bridge to keep the settings dict's number keys (PR #361).

Every ``ZZ_r2104_`` preset is swept at the end and each preset list must end as
it started. The open project is restored and the disposable one deleted.
Synthetic media only (ffmpeg, in a temp dir).

Run (free edition, bridge listener started from Workspace > Scripts):
  python3 tests/live_preset_fixture_validation.py [--burnin-wait 180] [--json PATH]

Invoke by path, never with ``-m`` (``tests/__init__.py`` installs the offline
guard).
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import live_resolve2104_validation as base  # noqa: E402  (also puts the repo root on sys.path)
from src.utils.project_cleanup import delete_project_safely, save_project_if_safe  # noqa: E402

PREFIX = base.PREFIX
record = base.record
names_of = base.preset_names
BURNIN_NAME = f"{PREFIX}burnin"


def sweep(label, list_fn, delete_fn, start):
    """Delete every PREFIX preset added during the run; report if the list differs."""
    try:
        for name in [n for n in list_fn() if n.startswith(PREFIX) and n not in start]:
            delete_fn(name)
        end = list_fn()
        restored = sorted(end) == sorted(start)
        print(f"  {label} list restored to its starting state: {restored}")
        if not restored:
            record(f"{label} cleanup", "error",
                   f"list differs from the start: added {sorted(set(end) - set(start))}, "
                   f"removed {sorted(set(start) - set(end))}")
    except Exception as exc:
        record(f"{label} cleanup", "error", f"raised {exc!r}; check the list by hand")


# ── layout presets ─────────────────────────────────────────────────────────

def probe_layout(resolve):
    print("\n== layout preset save ==")
    listed = lambda: names_of(resolve.GetLayoutPresetList())  # noqa: E731
    start = listed()
    name = f"{PREFIX}layout_{int(time.time())}"
    try:
        ok = resolve.SaveLayoutPreset(name)
        now = listed()
        record("Resolve.SaveLayoutPreset", "supported" if ok and name in now else "error",
               f"fresh name returned {ok!r}; listed afterwards: {name in now}",
               {"returned": ok, "listed": name in now})
        again = resolve.SaveLayoutPreset(name)
        count = listed().count(name)
        record("Resolve.SaveLayoutPreset (existing name)", "supported" if count == 1 else "error",
               f"same name again returned {again!r} "
               f"({'refused' if again is False else 'accepted'}); listed {count} time(s)",
               {"returned": again, "count": count})
    except Exception as exc:
        record("Resolve.SaveLayoutPreset", "error", f"raised {exc!r}")
    finally:
        sweep("layout preset", listed, resolve.DeleteLayoutPreset, start)


# ── render presets ─────────────────────────────────────────────────────────

def probe_render_presets(resolve, project, tmp):
    print("\n== render preset export / import ==")
    listed = lambda: names_of(project.GetRenderPresetList())  # noqa: E731
    start = listed()
    name = f"{PREFIX}render_{int(time.time())}"
    folder = os.path.join(tmp, "render_export.xml")  # named like a file on purpose
    path = os.path.join(folder, f"{name}.xml")
    try:
        ok = project.SaveAsNewRenderPreset(name)
        if not (ok and name in listed()):
            record("Project.SaveAsNewRenderPreset", "error",
                   f"returned {ok!r}; no preset to export, so the export/import rows are not run")
            return
        # Resolve treats the export path as a folder: it creates it and writes <name>.xml inside.
        ok = resolve.ExportRenderPreset(name, folder)
        exists = os.path.isfile(path)
        record("Resolve.ExportRenderPreset", "supported" if ok and exists else "error",
               f"returned {ok!r}; the path became a folder: {os.path.isdir(folder)}; "
               f"<name>.xml inside it: {exists}",
               {"returned": ok, "folder": os.path.isdir(folder), "file": exists,
                "bytes": os.path.getsize(path) if exists else None})
        if not exists:
            record("Resolve.ImportRenderPreset", "not_applicable", "no exported file to import")
            return
        deleted = project.DeleteRenderPreset(name)
        gone = name not in listed()
        before = listed()
        ok = resolve.ImportRenderPreset(path)
        added = [n for n in listed() if n not in before]
        record("Resolve.ImportRenderPreset", "supported" if ok and added else "error",
               f"after a delete (returned {deleted!r}, gone: {gone}) import returned {ok!r} and "
               f"added {added} (same name as exported: {added == [name]})",
               {"returned": ok, "added": added, "same_name": added == [name]})
    except Exception as exc:
        record("render preset round-trip", "error", f"raised {exc!r}")
    finally:
        sweep("render preset", listed, project.DeleteRenderPreset, start)


# ── burn-in presets ────────────────────────────────────────────────────────

def probe_burnin(resolve, tmp, wait):
    print("\n== burn-in preset export / delete / import ==")
    listed = lambda: names_of(resolve.GetBurnInPresetList())  # noqa: E731
    start = listed()
    if BURNIN_NAME in start:
        record("burn-in round-trip", "not_applicable",
               f"{BURNIN_NAME} already exists; delete it by hand and run again")
        return
    if not wait:
        record("burn-in round-trip", "not_applicable",
               "no script call creates a burn-in preset; pass --burnin-wait N to make one by hand")
        return
    print(f"  waiting up to {wait}s: in Resolve open Workspace > Data Burn-In, then in its "
          f"menu (top right) choose Save As New Preset and name it {BURNIN_NAME}")
    deadline = time.time() + wait
    while time.time() < deadline and BURNIN_NAME not in listed():
        time.sleep(1)
    if BURNIN_NAME not in listed():
        record("burn-in round-trip", "not_applicable", f"no {BURNIN_NAME} preset seen within {wait}s")
        return
    print(f"  saw {BURNIN_NAME}")
    folder = os.path.join(tmp, "burnin_export")
    path = os.path.join(folder, f"{BURNIN_NAME}.xml")
    try:
        # Like render presets, the export path is a folder that receives <name>.xml.
        ok = resolve.ExportBurnInPreset(BURNIN_NAME, folder)
        exists = os.path.isfile(path)
        record("Resolve.ExportBurnInPreset", "supported" if ok and exists else "error",
               f"returned {ok!r}; <name>.xml inside the given folder: {exists}",
               {"returned": ok, "file": exists})
        if not exists:
            record("Resolve.DeleteBurnInPreset (existing preset)", "not_applicable",
                   f"export wrote no file, so {BURNIN_NAME} is kept; delete it by hand")
            return
        ok = resolve.DeleteBurnInPreset(BURNIN_NAME)
        gone = BURNIN_NAME not in listed()
        record("Resolve.DeleteBurnInPreset (existing preset)", "supported" if ok and gone else "error",
               f"returned {ok!r}; gone from the list: {gone}", {"returned": ok, "gone": gone})
        before = listed()
        ok = resolve.ImportBurnInPreset(path)
        added = [n for n in listed() if n not in before]
        record("Resolve.ImportBurnInPreset", "supported" if ok and added else "error",
               f"returned {ok!r}; added {added}", {"returned": ok, "added": added})
    except Exception as exc:
        record("burn-in round-trip", "error", f"raised {exc!r}")
    finally:
        keep = start + ([] if os.path.isfile(path) else [BURNIN_NAME])
        sweep("burn-in preset", listed, resolve.DeleteBurnInPreset, keep)


# ── disposable project: relink and auto sync ───────────────────────────────

def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args, "-y"], check=True, timeout=120)


def clip_path(clip):
    try:
        return clip.GetClipProperty("File Path") or ""
    except Exception:
        return ""


def synced(clip):
    try:
        value = clip.GetClipProperty("Synced Audio")
    except Exception:
        return None
    return value


def probe_relink(mp, tmp):
    first, moved = os.path.join(tmp, "first"), os.path.join(tmp, "moved")
    try:
        os.makedirs(first)
        src = os.path.join(first, "relink.mov")
        ffmpeg("-f", "lavfi", "-i", "smptebars=size=640x360:rate=24", "-t", "2", "-c:v", "prores_ks", src)
        clips = base.as_list(mp.ImportMedia([src]))
        if not clips:
            record("MediaPool.RelinkClips", "error", "setup failed: the clip did not import")
            return
        clip = clips[0]
        os.rename(first, moved)
        ok = mp.RelinkClips([clip], moved)
        now = clip_path(clip)
        relinked = bool(now) and os.path.realpath(os.path.dirname(now)) == os.path.realpath(moved)
        record("MediaPool.RelinkClips", "supported" if ok and relinked else "error",
               f"after the file moved, returned {ok!r}; clip path now in the new folder: {relinked}",
               {"returned": ok, "path_after": now, "relinked": relinked})
    except Exception as exc:
        record("MediaPool.RelinkClips", "error", f"raised {exc!r}")


def probe_auto_sync(resolve, mp, tmp):
    noise = os.path.join(tmp, "sync_audio.wav")
    video = os.path.join(tmp, "sync_video.mov")
    try:
        make_sync_media(noise, video)
    except Exception as exc:
        record("MediaPool.AutoSyncAudio", "error", f"setup failed: {exc!r}")
        return
    clips = base.as_list(mp.ImportMedia([video, noise]))
    if len(clips) != 2:
        record("MediaPool.AutoSyncAudio", "error", f"setup failed: {len(clips)} clip(s) imported")
        return
    try:
        mode, waveform = resolve.AUDIO_SYNC_MODE, resolve.AUDIO_SYNC_WAVEFORM
        channel, automatic = resolve.AUDIO_SYNC_CHANNEL_NUMBER, resolve.AUDIO_SYNC_CHANNEL_AUTOMATIC
    except AttributeError as exc:
        record("MediaPool.AutoSyncAudio", "error", f"sync constants missing on the handle: {exc}")
        return
    key_types = {"mode": type(mode).__name__, "channel": type(channel).__name__}
    before = [synced(c) for c in clips]
    try:
        ok = mp.AutoSyncAudio(clips, {mode: waveform, channel: automatic})
    except Exception as exc:
        record("MediaPool.AutoSyncAudio", "error", f"raised {exc!r}")
        return
    after = [synced(c) for c in clips]
    changed = any(is_linked(a) and a != b for a, b in zip(after, before))
    record("MediaPool.AutoSyncAudio", "supported" if changed else "error",
           f"waveform sync returned {ok!r} (evidence only); 'Synced Audio' before {before}, "
           f"after {after}; settings key types {key_types}",
           {"returned": ok, "before": before, "after": after, "linked": changed, "key_types": key_types})


def is_linked(value):
    return bool(value) and str(value).strip() not in ("", "None", "0", "Off", "No")


def make_sync_media(noise, video):
    """A pink-noise track, and a video carrying the same noise one second later."""
    ffmpeg("-f", "lavfi", "-i", "anoisesrc=color=pink:seed=7:amplitude=0.5:sample_rate=48000",
           "-t", "8", "-c:a", "pcm_s24le", noise)
    ffmpeg("-f", "lavfi", "-i", "smptebars=size=640x360:rate=24", "-i", noise,
           "-filter:a", "adelay=1000:all=1,volume=0.6", "-t", "8",
           "-c:v", "prores_ks", "-c:a", "pcm_s24le", video)

def probe_project(resolve, pm, original_name, tmp):
    print("\n== disposable project: relink, auto sync, render presets ==")
    saved = save_project_if_safe(pm)
    if not (saved.get("saved") or saved.get("skipped")):
        record("disposable project", "error",
               f"the open project could not be saved first ({saved.get('reason')}); nothing was changed")
        return
    scratch_name = f"{PREFIX}fixtures_{int(time.time())}"
    try:
        scratch = pm.CreateProject(scratch_name)
    except Exception as exc:
        record("disposable project", "error", f"CreateProject raised {exc!r}")
        return
    if not scratch:
        record("disposable project", "error", "CreateProject returned nothing")
        return
    print(f"  created {scratch_name}")
    try:
        mp = scratch.GetMediaPool()
        presets = os.path.join(tmp, "render-presets")
        os.makedirs(presets)
        probe_render_presets(resolve, scratch, presets)
        relink_dir = os.path.join(tmp, "relink")
        os.makedirs(relink_dir)
        probe_relink(mp, relink_dir)
        sync_dir = os.path.join(tmp, "sync")
        os.makedirs(sync_dir)
        probe_auto_sync(resolve, mp, sync_dir)
    except Exception as exc:
        record("disposable project", "error", f"raised {exc!r}")
    finally:
        result = delete_project_safely(pm, scratch_name, switch_to=original_name)
        current = pm.GetCurrentProject()
        current_name = current.GetName() if current else None
        still_listed = scratch_name in base.project_names(pm)
        print(f"  open project now {current_name!r}; {scratch_name} deleted: {not still_listed}")
        if not result.get("success") or still_listed:
            record("disposable project cleanup", "error",
                   f"{scratch_name} was not deleted: {result.get('detail')}")
        if current_name != original_name:
            record("disposable project cleanup", "error",
                   f"open project is {current_name!r}, expected {original_name!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", action="store_true",
                    help="use external scripting (Studio) instead of the in-app bridge")
    ap.add_argument("--any-version", action="store_true", help="run on a build other than 21.0.4.x")
    ap.add_argument("--burnin-wait", type=int, default=0,
                    help="seconds to wait for a person to save the burn-in test preset")
    ap.add_argument("--json", help="write the full report to this path")
    args = ap.parse_args()

    try:
        resolve, transport = base.connect(args.native)
    except Exception as exc:
        print(f"FATAL: cannot connect to Resolve: {exc}")
        return 1
    if not resolve:
        print("FATAL: cannot connect to Resolve")
        return 1
    product, version = resolve.GetProductName(), resolve.GetVersionString()
    print("== preflight ==")
    print(f"  product         : {product}")
    print(f"  version         : {version}")
    print(f"  transport       : {transport}")
    pm = resolve.GetProjectManager()
    database = pm.GetCurrentDatabase()
    original_name, problems = base.preflight(resolve, pm, version, args.any_version, False)
    if original_name and original_name not in base.project_names(pm):
        problems.append(f"{original_name!r} is not in the Project Manager's current folder, so it "
                        "could not be reopened by name after the run; open that folder first")
    if problems:
        print("\nFATAL: preflight failed:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    report = {"product": product, "version": version, "transport": transport}
    tmp = tempfile.mkdtemp(prefix="resolve_fixtures_")
    try:
        probe_layout(resolve)
        burnin = os.path.join(tmp, "burnin")
        os.makedirs(burnin)
        probe_burnin(resolve, burnin, args.burnin_wait)
        project_dir = os.path.join(tmp, "project")
        os.makedirs(project_dir)
        probe_project(resolve, pm, original_name, project_dir)
    except BaseException as exc:
        record("run", "error", f"stopped early: {exc!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if pm.GetCurrentDatabase() != database:
        record("database", "error", "the current database changed during the run")
    report["results"] = base.results
    base.emit(report, args.json)
    return 1 if any(r["status"] == "error" for r in base.results) else 0


if __name__ == "__main__":
    sys.exit(main())
