"""Live validation of the Resolve 21.0 scripting additions.

The Resolve 21.0 surface is implemented in ``src/server.py`` behind
``_requires_method(obj, method, min_version)`` gates, but the only coverage is
``tests/test_resolve21_actions.py``, which drives plain-Python stubs. Stubs
cannot answer the questions that matter on a real build: does the method exist
on the live handle, does it return anything meaningful, and does its effect
survive a readback.

This harness answers them against a live Resolve 21.x, and records the AI
Extras that were installed at the time — three of the Resolve 21 methods refuse
without their Extra, and a bare ``False`` is indistinguishable from a genuine
failure, so "untested for lack of an Extra" must never be reported as "broken".

It also settles a load-bearing question about capability detection. The
``hasattr``/``getattr`` entry in ``src/utils/api_truth.py`` (verified on 21.0.0)
records that the Python bridge fabricates a callable for ANY attribute name,
which would make ``_has_method`` — and therefore every ``_requires_method``
gate — dead code against a live Resolve. ``probe_fabrication`` re-runs that
control across every object type, so the entry can be confirmed or scoped to
the builds where it actually holds.

Source-safe: generates its own synthetic media (ffmpeg bars + macOS ``say``
speech) in a temp dir and never reads or writes user media. Runs in a
disposable project whose media location is pinned to that temp dir, restores
the originally-open project, and deletes both on exit.

Two operations are deliberately NOT executed:

  - ``Resolve.DisableBackgroundTasksForCurrentResolveSession`` — session-wide,
    affects any project open in the running instance, returns None, and has no
    ``Enable...`` counterpart anywhere in the shipped scripting README. There is
    no undo short of restarting Resolve. Presence and signature are recorded;
    the call is not made. Pass --allow-session-mutation to override.
  - ``RemoveMotionBlur`` renders new media, so it runs only under
    --allow-render. Without it, the confirm-gate half is still exercised.

Run:
  env RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
      RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
      PYTHONPATH="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules" \
      venv/bin/python tests/live_resolve21_validation.py [--read-only] [--allow-render] [--json PATH]

Invoke by path, never with ``-m``: ``tests/__init__.py`` installs the offline
guard, which stubs the connection out and yields a silently dead run.
"""
import argparse
import glob
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
from src.utils.project_cleanup import delete_project_safely, save_project_if_safe  # noqa: E402

PROJECT_PREFIX = "ZZ_r21_delta_"
EXTRAS_DIR = ("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Extras")
SCRIPTING_README = ("/Library/Application Support/Blackmagic Design/DaVinci Resolve"
                    "/Developer/Scripting/README.txt")

#: Resolve 21.0 additions, keyed by the object they hang off. The server gates
#: each of these with _requires_method(..., "21.0").
R21_SURFACE = {
    "Resolve": ["DisableBackgroundTasksForCurrentResolveSession"],
    "Project": ["GenerateSpeech", "ResetIntellisearchAnalysis"],
    "Folder": ["PerformAudioClassification", "ClearAudioClassification",
               "AnalyzeForIntellisearch", "AnalyzeForSlate",
               "RemoveMotionBlur", "TranscribeAudio"],
    "MediaPoolItem": ["PerformAudioClassification", "ClearAudioClassification",
                      "AnalyzeForIntellisearch", "AnalyzeForSlate",
                      "RemoveMotionBlur", "TranscribeAudio"],
}

#: Methods the shipped scripting README marks as requiring an Extras download.
#: Without the pack the call returns False for a reason unrelated to the code.
EXTRA_REQUIRED = {
    "AnalyzeForIntellisearch": "AI IntelliSearch - Faster / Better",
    "AnalyzeForSlate": "AI Slate ID",
    "GenerateSpeech": "AI Speech Generator",
    "RemoveMotionBlur": "AI Motion Deblur",
}

results = []


def record(symbol, status, reason, evidence=None):
    """Statuses mirror the probe vocabulary used elsewhere in the repo:
    supported / partially_supported / unsupported / not_applicable / error.
    """
    results.append({
        "symbol": symbol,
        "status": status,
        "reason": reason,
        "evidence": evidence or {},
    })
    print(f"  [{status:20}] {symbol}: {reason}")


def real_methods(obj):
    """The methods that genuinely exist on a live Resolve object.

    dir() is the only trustworthy source here. Whether getattr() also lies is
    exactly what probe_fabrication() measures rather than assumes.
    """
    try:
        return set(dir(obj))
    except Exception:
        return set()


def installed_extras():
    """Names of the AI Extras packs installed, read from each pack's log."""
    names = []
    for pack in sorted(glob.glob(os.path.join(EXTRAS_DIR, "*", ""))):
        log = os.path.join(pack, "log.dpl1")
        if not os.path.isfile(log):
            continue
        try:
            with open(log, "rb") as fh:
                blob = fh.read()
        except OSError:
            continue
        for label in ("AI Motion Deblur", "AI IntelliSearch", "AI Slate ID",
                      "AI Speech Generator", "AI IntelliScript"):
            if label.encode() in blob and label not in names:
                names.append(label)
    return names


def probe_fabrication(handles):
    """Does getattr() fabricate callables for names that do not exist?

    api_truth records this as true on 21.0.0, which would make _has_method (and
    every _requires_method gate built on it) unable to ever fire against a live
    Resolve. Test each object type: a name that cannot possibly exist should be
    absent from dir() AND not callable via getattr.
    """
    fake = "TotallyMadeUpMethod_xyz123"
    report = {}
    for label, obj in handles.items():
        if obj is None:
            report[label] = {"sampled": False}
            continue
        report[label] = {
            "sampled": True,
            "in_dir": fake in real_methods(obj),
            "getattr_callable": callable(getattr(obj, fake, None)),
        }
    fabricating = sorted(k for k, v in report.items()
                         if v.get("sampled") and v.get("getattr_callable"))
    return report, fabricating


def snapshot(clip):
    """Full clip-property + metadata dicts, for before/after diffing.

    Blackmagic documents no output surface for the Resolve 21 analysis calls, so
    the honest readback is to diff whole dicts rather than guess key names.
    """
    out = {}
    for label, getter in (("properties", "GetClipProperty"), ("metadata", "GetMetadata")):
        try:
            value = getattr(clip, getter)()
            out[label] = value if isinstance(value, dict) else {"_raw": repr(value)}
        except Exception as exc:
            out[label] = {"_error": repr(exc)}
    return out


def diff_snapshots(before, after):
    """Keys that appeared, vanished, or changed between two snapshots."""
    delta = {}
    for section in ("properties", "metadata"):
        b, a = before.get(section, {}), after.get(section, {})
        changed = {k: {"before": b.get(k), "after": a.get(k)}
                   for k in set(b) | set(a) if b.get(k) != a.get(k)}
        if changed:
            delta[section] = changed
    return delta


def gen_media(tmp):
    """Synthetic media only: colour bars with a tone, plus two-voice speech.

    The speech clip matters — audio classification and speaker detection are
    both meaningless against a sine tone, and a single-voice clip cannot
    falsify use_speaker_detection=True.
    """
    bars = os.path.join(tmp, "bars.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=320x180:rate=24:duration=4",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", bars],
        check=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Two distinct macOS voices so speaker detection has something to detect.
    voices = []
    for idx, (voice, line) in enumerate((
            ("Samantha", "Scene twelve, take three. Camera A is rolling."),
            ("Alex", "Copy that. Sound speed. Marker."))):
        aiff = os.path.join(tmp, f"voice{idx}.aiff")
        subprocess.run(["say", "-v", voice, "-o", aiff, line],
                       check=True, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        voices.append(aiff)

    concat = os.path.join(tmp, "voices.aiff")
    subprocess.run(["ffmpeg", "-y", "-i", voices[0], "-i", voices[1],
                    "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1", concat],
                   check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    speech = os.path.join(tmp, "speech.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24",
         "-i", concat, "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", speech],
        check=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return bars, speech


def free_bytes(path=None):
    """Free bytes on the volume that actually holds user data.

    statvfs("/") on macOS reports the synthesized root, whose free-space figure
    swings by gigabytes as APFS accounts for purgeable space — a probe that
    renders a sub-megabyte file appeared to consume 6 GiB. Measure the data
    volume instead, and treat the delta as indicative rather than exact.
    """
    if path is None:
        path = "/System/Volumes/Data" if os.path.isdir("/System/Volumes/Data") else "/"
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def preflight(resolve, extras):
    """Read-only gate. Every check must pass before anything is mutated."""
    pm = resolve.GetProjectManager()
    product = resolve.GetProductName()
    version = resolve.GetVersionString()
    database = pm.GetCurrentDatabase()
    project = pm.GetCurrentProject()
    original = project.GetName() if project else None

    print(f"  product           : {product}")
    print(f"  version           : {version}")
    print(f"  database          : {(database or {}).get('DbName') if isinstance(database, dict) else database}")
    print(f"  current project   : {original}")
    print(f"  extras installed  : {', '.join(extras) or 'none'}")
    print(f"  free disk         : {free_bytes() / 2**30:.1f} GiB")

    problems = []
    if "Studio" not in (product or ""):
        problems.append(f"not Studio (got {product!r}); external scripting needs Studio")
    if not (version or "").startswith("21."):
        problems.append(f"expected Resolve 21.x, got {version!r}")
    if database is None:
        problems.append("GetCurrentDatabase() is None — the instance is wedged")
    if original is None:
        problems.append("no current project")
    try:
        if project is not None and project.IsRenderingInProgress():
            problems.append("a render is in progress — refusing to touch this session")
    except Exception:
        pass
    leftovers = [p for p in (pm.GetProjectListInCurrentFolder() or [])
                 if p.startswith(PROJECT_PREFIX)]
    if leftovers:
        problems.append(f"leftover scratch projects from a previous run: {leftovers}")
    if free_bytes() < 5 * 2**30:
        problems.append("less than 5 GiB free")
    return pm, original, database, problems


def probe_readonly(resolve, pm, project):
    """Surface + fabrication probes. Touches nothing."""
    mp = project.GetMediaPool()
    folder = mp.GetRootFolder()
    clips = folder.GetClipList() or []
    timeline = project.GetCurrentTimeline()
    items = []
    if timeline:
        try:
            items = timeline.GetItemListInTrack("video", 1) or []
        except Exception:
            items = []

    handles = {
        "Resolve": resolve,
        "ProjectManager": pm,
        "Project": project,
        "MediaPool": mp,
        "Folder": folder,
        "MediaPoolItem": clips[0] if clips else None,
        "Timeline": timeline,
        "TimelineItem": items[0] if items else None,
    }

    print("\n-- getattr fabrication control --")
    fab_report, fabricating = probe_fabrication(handles)
    for label, entry in fab_report.items():
        if entry.get("sampled"):
            print(f"  {label:16} in_dir={entry['in_dir']!s:5} "
                  f"getattr_callable={entry['getattr_callable']}")
        else:
            print(f"  {label:16} not sampled")

    print("\n-- Resolve 21 surface (dir() membership) --")
    surface = {}
    for label in ("Resolve", "Project", "Folder", "MediaPoolItem"):
        obj = handles.get(label)
        if obj is None:
            surface[label] = {"sampled": False}
            continue
        names = real_methods(obj)
        surface[label] = {"sampled": True,
                          "methods": {m: (m in names) for m in R21_SURFACE[label]}}
        for method, present in surface[label]["methods"].items():
            print(f"  {label:14} {method:48} {'present' if present else 'ABSENT'}")

    print("\n-- documented MARKER_* constants on the resolve handle --")
    markers = sorted(c for c in real_methods(resolve) if c.startswith("MARKER_"))
    print(f"  found: {markers or 'NONE'}")

    return {"fabrication": fab_report, "fabricating_types": fabricating,
            "surface": surface, "marker_constants": markers}


def probe_analysis(clip, folder, label, method, extras, *, args=()):
    """Call an analysis method and diff the clip's dicts around it."""
    target = clip if label == "MediaPoolItem" else folder
    symbol = f"{label}.{method}"
    if method not in real_methods(target):
        record(symbol, "unsupported", "absent from dir() on this build")
        return

    extra = EXTRA_REQUIRED.get(method)
    missing_extra = extra and not any(e in extra for e in extras)

    before = snapshot(clip)
    try:
        returned = getattr(target, method)(*args)
    except Exception as exc:
        record(symbol, "error", f"raised {type(exc).__name__}: {exc}")
        return
    after = snapshot(clip)
    delta = diff_snapshots(before, after)

    evidence = {"args": list(args), "returned": repr(returned),
                "readback_delta": delta, "extra_required": extra,
                "extra_installed": not missing_extra if extra else None}

    if missing_extra and not returned:
        record(symbol, "not_applicable",
               f"returned {returned!r}; requires the {extra} Extra, which is not "
               f"installed — indistinguishable from a genuine failure",
               evidence)
    elif returned and delta:
        record(symbol, "supported",
               f"returned {returned!r}; readback shows {sum(len(v) for v in delta.values())} "
               f"changed key(s)", evidence)
    elif returned and not delta:
        record(symbol, "partially_supported",
               f"returned {returned!r} but readback shows no change "
               f"(may be async — see poll note)", evidence)
    else:
        record(symbol, "partially_supported", f"returned {returned!r}", evidence)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--read-only", action="store_true",
                    help="preflight + surface probes only; creates nothing")
    ap.add_argument("--allow-render", action="store_true",
                    help="execute RemoveMotionBlur, which renders new media files")
    ap.add_argument("--allow-session-mutation", action="store_true",
                    help="execute DisableBackgroundTasksForCurrentResolveSession "
                         "(session-wide, no undo without restarting Resolve)")
    ap.add_argument("--json", help="write the full report to this path")
    args = ap.parse_args()

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        print("FATAL: cannot connect to Resolve. Is it running, and is "
              "Preferences > General > External scripting set to Local?")
        return 1

    extras = installed_extras()

    print("== preflight ==")
    pm, original_name, database, problems = preflight(resolve, extras)
    if problems:
        print("\nFATAL: preflight failed:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("  preflight OK")

    project = pm.GetCurrentProject()
    readonly_report = probe_readonly(resolve, pm, project)

    report = {
        "product": resolve.GetProductName(),
        "version": resolve.GetVersionString(),
        "extras_installed": extras,
        "scripting_readme_date": readme_date(),
        "read_only": readonly_report,
        "results": results,
    }

    if args.read_only:
        print("\n-- read-only mode: stopping before any mutation --")
        emit(report, args.json)
        return 0

    tmp = tempfile.mkdtemp(prefix="resolve_r21_")
    scratch_name = f"{PROJECT_PREFIX}{int(time.time())}"
    scratch = None
    disk_before = free_bytes()
    try:
        print(f"\n== scratch project {scratch_name} ==")
        bars, speech = gen_media(tmp)
        print(f"  synthetic media in {tmp}")

        # mediaLocationPath pins anything Resolve authors (notably
        # RemoveMotionBlur output, whose FileName semantics are undocumented)
        # into the temp dir instead of next to real media.
        scratch = pm.CreateProject(scratch_name, tmp)
        if not scratch:
            scratch = pm.CreateProject(scratch_name)
        if not scratch:
            print("FATAL: could not create the scratch project")
            return 1

        mp = scratch.GetMediaPool()
        folder = mp.GetRootFolder()
        clips = mp.ImportMedia([bars, speech]) or []
        print(f"  imported {len(clips)} clips")
        if len(clips) < 2:
            print("FATAL: import produced too few clips")
            return 1
        by_name = {os.path.basename(c.GetClipProperty("File Path") or ""): c for c in clips}
        speech_clip = by_name.get("speech.mp4", clips[-1])

        print("\n== Resolve 21 delta ==")
        probe_analysis(speech_clip, folder, "MediaPoolItem",
                       "PerformAudioClassification", extras)
        probe_analysis(speech_clip, folder, "MediaPoolItem",
                       "ClearAudioClassification", extras)
        probe_analysis(speech_clip, folder, "MediaPoolItem",
                       "AnalyzeForIntellisearch", extras, args=(False, False))
        probe_analysis(speech_clip, folder, "MediaPoolItem",
                       "AnalyzeForSlate", extras, args=("Blue",))
        probe_transcription(speech_clip, extras)
        probe_generate_speech(scratch, extras)
        probe_reset_intellisearch(scratch)
        probe_remove_motion_blur(speech_clip, extras, allow=args.allow_render)
        probe_disable_background_tasks(resolve, allow=args.allow_session_mutation)

    finally:
        print("\n== teardown ==")
        save_project_if_safe(pm)
        if scratch is not None:
            outcome = delete_project_safely(pm, scratch_name, switch_to=original_name)
            print(f"  delete scratch: {outcome}")
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"  removed temp media: {tmp}")

        current = pm.GetCurrentProject()
        restored = current.GetName() if current else None
        db_after = pm.GetCurrentDatabase()
        print(f"  current project: {restored} (expected {original_name})")
        print(f"  database unchanged: {db_after == database}")
        print(f"  disk delta: {(disk_before - free_bytes()) / 2**20:+.1f} MiB")
        report["teardown"] = {
            "restored_project": restored,
            "expected_project": original_name,
            "project_restored": restored == original_name,
            "database_unchanged": db_after == database,
            "disk_delta_mib": round((disk_before - free_bytes()) / 2**20, 1),
        }

    report["results"] = results
    emit(report, args.json)
    return 0


def readme_date():
    try:
        with open(SCRIPTING_README, "r", errors="replace", encoding="utf-8") as fh:
            for line in fh:
                if line.lower().startswith("last updated"):
                    return line.strip()
    except OSError:
        pass
    return None


def probe_transcription(clip, extras):
    """TranscribeAudio gained a use_speaker_detection parameter in 21.0."""
    symbol = "MediaPoolItem.TranscribeAudio"
    if "TranscribeAudio" not in real_methods(clip):
        record(symbol, "unsupported", "absent from dir() on this build")
        return
    outcomes = {}
    for label, call in (("no_arg", lambda: clip.TranscribeAudio()),
                        ("speaker_detection_false", lambda: clip.TranscribeAudio(False)),
                        ("speaker_detection_true", lambda: clip.TranscribeAudio(True))):
        try:
            returned = call()
        except Exception as exc:
            outcomes[label] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        time.sleep(2)
        outcomes[label] = {
            "returned": repr(returned),
            "status": clip.GetClipProperty("Transcription Status"),
            "text": (clip.GetClipProperty("Transcription") or "")[:400],
        }
    texts = {k: v.get("text") for k, v in outcomes.items() if v.get("text")}
    distinct = len(set(texts.values()))
    if not texts:
        record(symbol, "partially_supported",
               "accepted the speaker-detection parameter but produced no "
               "readable transcript within the poll window", outcomes)
    elif distinct > 1:
        record(symbol, "supported",
               f"use_speaker_detection changes the transcript ({distinct} distinct results)",
               outcomes)
    else:
        record(symbol, "partially_supported",
               "use_speaker_detection accepted but True and False produced "
               "identical transcripts", outcomes)


def probe_generate_speech(project, extras):
    symbol = "Project.GenerateSpeech"
    if "GenerateSpeech" not in real_methods(project):
        record(symbol, "unsupported", "absent from dir() on this build")
        return
    have_extra = any("Speech" in e for e in extras)
    settings = {"TextInput": "Scene twelve, take three.", "AddToTimeline": False}
    try:
        returned = project.GenerateSpeech(settings, "01:00:00:00")
    except Exception as exc:
        record(symbol, "error", f"raised {type(exc).__name__}: {exc}")
        return
    evidence = {"settings": settings, "returned": repr(returned),
                "extra_required": "AI Speech Generator", "extra_installed": have_extra,
                "note": "the shipped README caps TextInput at 350 chars; "
                        "src/server.py validates presence but not length"}
    if not returned and not have_extra:
        record(symbol, "not_applicable",
               f"returned {returned!r}; requires the AI Speech Generator Extra, "
               f"which is not installed", evidence)
    else:
        record(symbol, "partially_supported" if not returned else "supported",
               f"returned {returned!r}", evidence)


def probe_reset_intellisearch(project):
    """New in the 21.0.2 shipped README; absent from the repo's bundled copy."""
    symbol = "Project.ResetIntellisearchAnalysis"
    present = "ResetIntellisearchAnalysis" in real_methods(project)
    if not present:
        record(symbol, "unsupported", "absent from dir() on this build")
        return
    try:
        returned = project.ResetIntellisearchAnalysis()
    except Exception as exc:
        record(symbol, "error", f"raised {type(exc).__name__}: {exc}")
        return
    record(symbol, "supported" if returned else "partially_supported",
           f"present on the live handle and returned {returned!r} — this method is "
           f"absent from docs/reference/resolve_scripting_api.txt and unwrapped in "
           f"src/server.py",
           {"returned": repr(returned), "documented_in_shipped_readme": True,
            "wrapped_by_server": False})


def probe_remove_motion_blur(clip, extras, *, allow):
    symbol = "MediaPoolItem.RemoveMotionBlur"
    if "RemoveMotionBlur" not in real_methods(clip):
        record(symbol, "unsupported", "absent from dir() on this build")
        return
    have_extra = any("Deblur" in e for e in extras)
    if not allow:
        record(symbol, "not_applicable",
               "present on the live handle; render deliberately not executed "
               "(pass --allow-render). This call creates NEW media files.",
               {"extra_installed": have_extra})
        return
    source_path = clip.GetClipProperty("File Path")
    try:
        clip.SetMarkInOut(0, 11, "all")
    except Exception:
        pass
    settings = {"FileName": "r21_deblur_probe", "Format": "mp4", "Codec": "H264",
                "UseExtremeMode": False, "UseMarkInMarkOut": True,
                "RenderAtSourceRes": True, "UseMoreGpuMemory": False}
    before = free_bytes()
    try:
        returned = clip.RemoveMotionBlur(settings)
    except Exception as exc:
        record(symbol, "error", f"raised {type(exc).__name__}: {exc}")
        return
    evidence = {
        "settings": settings,
        "returned_type": type(returned).__name__,
        "disk_delta_mib": round((before - free_bytes()) / 2**20, 1),
        "source_path_before": source_path,
        "source_path_after": clip.GetClipProperty("File Path"),
    }
    evidence["source_media_unmodified"] = (
        evidence["source_path_before"] == evidence["source_path_after"])
    record(symbol, "supported" if returned else "partially_supported",
           f"returned {type(returned).__name__}", evidence)


def probe_disable_background_tasks(resolve, *, allow):
    symbol = "Resolve.DisableBackgroundTasksForCurrentResolveSession"
    if symbol.split(".")[1] not in real_methods(resolve):
        record(symbol, "unsupported", "absent from dir() on this build")
        return
    if not allow:
        record(symbol, "not_applicable",
               "present on the live handle; NOT executed — it is session-wide, "
               "affects every project open in this instance, is documented to "
               "return None, and has no Enable... counterpart in the shipped "
               "scripting README, so there is no undo short of restarting "
               "Resolve. Pass --allow-session-mutation to execute.",
               {"documented_return": "None", "counterpart_exists": False})
        return
    try:
        returned = resolve.DisableBackgroundTasksForCurrentResolveSession()
    except Exception as exc:
        record(symbol, "error", f"raised {type(exc).__name__}: {exc}")
        return
    record(symbol, "partially_supported",
           f"returned {returned!r} — success is unobservable, and src/server.py "
           f"returns _ok() unconditionally",
           {"returned": repr(returned)})


def emit(report, path):
    print("\n== summary ==")
    tally = {}
    for entry in report.get("results", []):
        tally[entry["status"]] = tally.get(entry["status"], 0) + 1
    for status, count in sorted(tally.items()):
        print(f"  {status:20} {count}")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
        print(f"\n  report written to {path}")


if __name__ == "__main__":
    sys.exit(main())
