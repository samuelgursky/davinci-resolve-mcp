"""Live validation of the Resolve 21.0.4 scripting additions.

The twelve 21.0.4 rows in ``docs/reference/api-coverage.md`` are guarded and
unit-tested against stubs (``tests/test_resolve2104_actions.py``,
``tests/test_resolve2104_preset_actions.py``) and carried contributor reports
from Studio 21.0.4.5, but no run of this repo's own. This harness runs them
against a live 21.0.4 build.

It works on the **free** edition through the in-app bridge (the default), and on
Studio through external scripting (``--native``). Free 21.0.4 is the case this
was written for: the free edition refuses external scripting, so the bridge is
the only way in.

What it does, in order:

  1. Preflight (read-only, every check must pass): 21.0.4.x, a saved project is
     open, no render running, no ``ZZ_r2104_`` leftovers from an earlier run.
  2. Read-only: ``GetLayoutPresetList``, ``GetBurnInPresetList``,
     ``GetUserPreferencesPresetList`` and
     ``ProjectManager.GetProjectAttributesInCurrentFolder``.
  3. ``DeleteBurnInPreset`` on a name that does not exist. No scripting call
     creates a burn-in preset, so a real delete cannot be set up; the
     missing-name answer is what can be measured without touching the user's
     presets.
  4. User-preferences preset round-trip under ``ZZ_r2104_`` names:
     save -> list -> export -> delete -> import (two-arg) -> delete ->
     import (single-arg) -> delete. Every ``ZZ_r2104_`` preset is swept at the
     end and the list must end equal to how it started.
     ``LoadUserPreferencesPreset`` is **never** called: it swaps the user's
     global preferences for the whole session.
  5. In a disposable project: method presence on every object, then
     ``MediaPoolItem.GetTimeline`` on a timeline item and on a plain media clip,
     and ``Timeline.GetSelectedClips`` with nothing selected. With
     ``--select-wait N`` it then waits up to N seconds for a person to click the
     test clip in the timeline and checks the selection is that clip. The
     originally-open project is restored and the disposable one deleted, and
     both are verified.

Synthetic media only (ffmpeg colour bars in a temp dir). Nothing reads or writes
user media.

Run (free edition, bridge listener started from Workspace > Scripts):
  python3 tests/live_resolve2104_validation.py [--read-only] [--select-wait 120] [--json PATH]

Invoke by path, never with ``-m``: ``tests/__init__.py`` installs the offline
guard, which stubs the connection out and yields a silently dead run.
"""
import argparse
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

from src.utils.project_cleanup import delete_project_safely, save_project_if_safe  # noqa: E402

PREFIX = "ZZ_r2104_"
UNSAVED_PROJECT = "Untitled Project"

#: Resolve 21.0.4 additions, keyed by the object they hang off.
R2104_SURFACE = {
    "Resolve": [
        "GetLayoutPresetList",
        "GetBurnInPresetList",
        "DeleteBurnInPreset",
        "GetUserPreferencesPresetList",
        "SaveUserPreferencesPreset",
        "LoadUserPreferencesPreset",
        "DeleteUserPreferencesPreset",
        "ImportUserPreferencesPreset",
        "ExportUserPreferencesPreset",
    ],
    "ProjectManager": ["GetProjectAttributesInCurrentFolder"],
    "MediaPoolItem": ["GetTimeline"],
    "Timeline": ["GetSelectedClips"],
}

results = []


def record(symbol, status, reason, evidence=None):
    """Statuses mirror tests/live_resolve21_validation.py:
    supported / partially_supported / unsupported / not_applicable / error.
    """
    results.append({"symbol": symbol, "status": status, "reason": reason,
                    "evidence": evidence or {}})
    print(f"  [{status:20}] {symbol}: {reason}")


def methods_of(obj):
    """Methods that genuinely exist on a live object.

    A bridge proxy answers from the far end's dir(); a native handle answers
    from its own dir(). getattr() is not used: on a native handle it fabricates
    a callable for any name.
    """
    if getattr(type(obj), "_methods", None) is not None:
        try:
            return set(obj._methods(refresh=True))
        except Exception:
            return set()
    try:
        return set(dir(obj))
    except Exception:
        return set()


def connect(native):
    if native:
        import DaVinciResolveScript as dvr
        return dvr.scriptapp("Resolve"), "external scripting"
    from src.utils import resolve_bridge_client as bridge
    return bridge.connect(require_enabled=False), "in-app bridge"


def as_list(value):
    """Lists from the API can come back as a 1-indexed dict on some builds."""
    if isinstance(value, dict):
        return [value[k] for k in sorted(value)]
    return list(value or [])


def preset_names(value):
    names = []
    for item in as_list(value):
        if isinstance(item, dict):
            names.append(item.get("Name") or item.get("name") or json.dumps(item, sort_keys=True))
        else:
            names.append(str(item))
    return names


def project_names(pm):
    return [str(n) for n in as_list(pm.GetProjectListInCurrentFolder())]


# ── preflight ──────────────────────────────────────────────────────────────

def preflight(resolve, pm, version, any_version, read_only):
    project = pm.GetCurrentProject()
    name = project.GetName() if project else None
    print(f"  current project : {name}")
    problems = []
    if not (version or "").startswith("21.0.4") and not any_version:
        problems.append(f"expected Resolve 21.0.4.x, got {version!r} (pass --any-version to override)")
    if not project:
        problems.append("no project open")
    if read_only:
        return name, problems
    if name == UNSAVED_PROJECT:
        problems.append("the open project is the never-saved 'Untitled Project', which cannot be "
                        "reloaded after the run; open or create a saved project first")
    if project and project.IsRenderingInProgress():
        problems.append("a render is in progress")
    leftovers = [n for n in project_names(pm) if n.startswith(PREFIX)]
    if leftovers:
        problems.append(f"leftover projects from an earlier run: {leftovers}; delete them first")
    if not shutil.which("ffmpeg"):
        problems.append("ffmpeg not on PATH (needed for the synthetic clip)")
    return name, problems


# ── read-only ──────────────────────────────────────────────────────────────

def probe_readonly(resolve, pm, current_name):
    print("\n== read-only ==")
    out = {}
    for name in ("GetLayoutPresetList", "GetBurnInPresetList", "GetUserPreferencesPresetList"):
        try:
            value = getattr(resolve, name)()
        except Exception as exc:
            record(f"Resolve.{name}", "error", f"raised {exc!r}")
            continue
        names = preset_names(value) if isinstance(value, (list, dict)) else []
        out[name] = {"type": type(value).__name__, "names": names}
        if isinstance(value, list):
            record(f"Resolve.{name}", "supported", f"returned a list of {len(names)} preset(s)",
                   {"type": "list", "count": len(names)})
        elif isinstance(value, dict):
            record(f"Resolve.{name}", "partially_supported",
                   f"returned a dict of {len(names)} preset(s), not a list",
                   {"type": "dict", "count": len(names)})
        else:
            record(f"Resolve.{name}", "unsupported", f"returned {value!r}")

    symbol = "ProjectManager.GetProjectAttributesInCurrentFolder"
    try:
        attrs = pm.GetProjectAttributesInCurrentFolder()
    except Exception as exc:
        record(symbol, "error", f"raised {exc!r}")
        return out
    expected = {"lastModifiedDate", "creationDate", "notes", "liveCollaborationMode"}
    rows = attrs if isinstance(attrs, dict) else {}
    keys = set()
    for row in rows.values():
        if isinstance(row, dict):
            keys.update(row.keys())
    current_listed = current_name in rows
    evidence = {"type": type(attrs).__name__, "count": len(rows), "keys": sorted(keys),
                "current_project_listed": current_listed}
    out["GetProjectAttributesInCurrentFolder"] = evidence
    if rows and expected <= keys and current_listed:
        record(symbol, "supported",
               f"returned a dict keyed by project name for {len(rows)} project(s), the open one "
               f"included; per-project keys {sorted(keys)}", evidence)
    else:
        record(symbol, "error",
               f"unexpected shape: {type(attrs).__name__}, {len(rows)} row(s), keys {sorted(keys)}, "
               f"open project listed: {current_listed}", evidence)
    return out


def probe_burnin_delete(resolve):
    print("\n== burn-in preset delete (missing name only) ==")
    existing = preset_names(resolve.GetBurnInPresetList())
    name = f"{PREFIX}missing_{int(time.time())}"
    if name in existing:
        record("Resolve.DeleteBurnInPreset", "not_applicable", "probe name already exists; skipped")
        return
    try:
        value = resolve.DeleteBurnInPreset(name)
    except Exception as exc:
        record("Resolve.DeleteBurnInPreset", "error", f"raised {exc!r} on a missing name")
        return
    unchanged = preset_names(resolve.GetBurnInPresetList()) == existing
    record("Resolve.DeleteBurnInPreset",
           "partially_supported" if value is False and unchanged else "error",
           f"missing name returned {value!r}; preset list unchanged: {unchanged}. "
           "No scripting call creates a burn-in preset, so a real delete is not exercised",
           {"returned": value, "list_unchanged": unchanged})


# ── user-preferences presets ───────────────────────────────────────────────

def probe_user_prefs(resolve, tmp):
    print("\n== user-preferences preset round-trip ==")
    stamp = int(time.time())
    name = f"{PREFIX}{stamp}"
    imported = f"{PREFIX}{stamp}_imp"
    file_name = f"{PREFIX}{stamp}_file"  # the single-arg import names its preset after the file
    export_path = os.path.join(tmp, file_name)

    def listed():
        return preset_names(resolve.GetUserPreferencesPresetList())

    start = listed()
    clash = [n for n in (name, imported, file_name) if n in start]
    if clash:
        record("user-preferences round-trip", "not_applicable", f"test names already exist: {clash}")
        return
    created = set()  # every name this probe may have added, claimed before each call

    try:
        created.add(name)
        ok = resolve.SaveUserPreferencesPreset(name)
        now = listed()
        record("Resolve.SaveUserPreferencesPreset", "supported" if ok and name in now else "error",
               f"returned {ok!r}; listed afterwards: {name in now}", {"returned": ok})
        record("Resolve.GetUserPreferencesPresetList (readback)",
               "supported" if name in now else "error",
               f"the saved preset {'appears' if name in now else 'does not appear'} in the list")

        ok = resolve.ExportUserPreferencesPreset(name, export_path)
        written = sorted(os.listdir(tmp))
        exact = os.path.isfile(export_path)
        only = written == [file_name]
        record("Resolve.ExportUserPreferencesPreset", "supported" if ok and exact and only else "error",
               f"returned {ok!r}; one file, at exactly the given path with no extension added: "
               f"{exact and only}", {"returned": ok, "exact_path": exact, "files": written,
                                     "bytes": os.path.getsize(export_path) if exact else None})

        ok = resolve.DeleteUserPreferencesPreset(name)
        gone = name not in listed()
        record("Resolve.DeleteUserPreferencesPreset", "supported" if ok and gone else "error",
               f"returned {ok!r}; gone from the list: {gone}", {"returned": ok})

        if not exact:
            record("Resolve.ImportUserPreferencesPreset", "not_applicable", "no exported file to import")
            return

        created.add(imported)
        ok2 = resolve.ImportUserPreferencesPreset(export_path, imported)
        two_arg = bool(ok2) and imported in listed()
        resolve.DeleteUserPreferencesPreset(imported)

        before = listed()
        created.add(file_name)
        try:
            ok1, single_error = resolve.ImportUserPreferencesPreset(export_path), None
        except Exception as exc:
            ok1, single_error = None, repr(exc)
        added = [n for n in listed() if n not in before]
        created.update(added)
        single_arg = bool(ok1) and added == [file_name]
        record("Resolve.ImportUserPreferencesPreset",
               "supported" if two_arg and single_arg
               else ("partially_supported" if two_arg or single_arg else "error"),
               f"two-arg returned {ok2!r} and listed under the given name: {two_arg}; single-arg "
               f"returned {ok1!r}{' (' + single_error + ')' if single_error else ''} and added "
               f"{added} (named after the file: {added == [file_name]})",
               {"two_arg": {"returned": ok2, "listed": two_arg},
                "single_arg": {"returned": ok1, "added": added, "named_after_file": added == [file_name],
                               "error": single_error}})
    except Exception as exc:
        record("user-preferences round-trip", "error", f"raised {exc!r}")
    finally:
        try:
            sweep = created | {n for n in set(listed()) - set(start) if n.startswith(PREFIX)}
            for leftover in sweep:
                if leftover in listed():
                    resolve.DeleteUserPreferencesPreset(leftover)
            end = listed()
            restored = sorted(end) == sorted(start)
            print(f"  preset list restored to its starting state: {restored}")
            if not restored:
                record("user-preferences cleanup", "error",
                       f"list differs from the start: added {sorted(set(end) - set(start))}, "
                       f"removed {sorted(set(start) - set(end))}")
        except Exception as exc:
            record("user-preferences cleanup", "error", f"raised {exc!r}; check the preset list by hand")


# ── disposable project ─────────────────────────────────────────────────────

def gen_bars(tmp):
    path = os.path.join(tmp, "bars.mov")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "smptebars=size=640x360:rate=24", "-t", "2", "-c:v", "prores_ks",
                    "-y", path], check=True)
    return path


def find_timeline_item(folder, timeline_name):
    for clip in as_list(folder.GetClipList()):
        props = clip.GetClipProperty() or {}
        if props.get("Type") == "Timeline" and clip.GetName() == timeline_name:
            return clip
    return None


def probe_surface(handles):
    print("\n== surface ==")
    present = {}
    for owner, names in R2104_SURFACE.items():
        obj = handles.get(owner)
        if obj is None:
            continue
        have = methods_of(obj)
        for name in names:
            symbol = f"{owner}.{name}"
            present[symbol] = name in have
            if name not in have:
                record(symbol, "unsupported", "not in dir() of the live object")
    print(f"  present: {sum(present.values())}/{len(present)}")
    return present


def selected_is(item, clip):
    try:
        mpi = item.GetMediaPoolItem()
        return bool(mpi) and mpi.GetUniqueId() == clip.GetUniqueId()
    except Exception:
        return False


def probe_project(resolve, pm, original_name, tmp, select_wait):
    print("\n== disposable project ==")
    save_project_if_safe(pm)
    scratch_name = f"{PREFIX}{int(time.time())}"
    try:
        scratch = pm.CreateProject(scratch_name, tmp)
    except TypeError:
        scratch = None
    scratch = scratch or pm.CreateProject(scratch_name)
    if not scratch:
        record("disposable project", "error", "CreateProject returned nothing")
        return None
    print(f"  created {scratch_name}")
    surface = None
    try:
        mp = scratch.GetMediaPool()
        root = mp.GetRootFolder()
        imported = as_list(mp.ImportMedia([gen_bars(tmp)]))
        clip = imported[0] if imported else None
        timeline_name = f"{PREFIX}timeline"
        timeline = mp.CreateEmptyTimeline(timeline_name)
        if not (clip and timeline):
            record("disposable project", "error", f"setup failed: clip {bool(clip)}, timeline {bool(timeline)}")
            return None
        scratch.SetCurrentTimeline(timeline)
        mp.AppendToTimeline([clip])
        tl_item = find_timeline_item(root, timeline_name)
        surface = probe_surface({"Resolve": resolve, "ProjectManager": pm,
                                 "MediaPoolItem": tl_item or clip, "Timeline": timeline})

        if tl_item is None:
            record("MediaPoolItem.GetTimeline", "error", "the timeline's media pool item was not found")
        else:
            got = tl_item.GetTimeline()
            same = bool(got) and got.GetUniqueId() == timeline.GetUniqueId()
            record("MediaPoolItem.GetTimeline", "supported" if same else "error",
                   f"timeline item -> {'the same timeline (unique id matches)' if same else repr(got)}",
                   {"same_unique_id": same})
        plain = clip.GetTimeline()
        record("MediaPoolItem.GetTimeline (plain clip)", "supported" if plain is None else "error",
               f"media clip returned {plain!r}", {"returned": repr(plain)})

        empty = timeline.GetSelectedClips()
        empty_ok = isinstance(empty, list) and not empty
        record("Timeline.GetSelectedClips", "supported" if empty_ok else "error",
               f"nothing selected -> {empty!r}", {"empty_selection": repr(empty)})
        if select_wait and empty_ok:
            print(f"  waiting up to {select_wait}s: click the clip in the timeline of {scratch_name}")
            deadline = time.time() + select_wait
            picked = []
            while time.time() < deadline:
                picked = as_list(timeline.GetSelectedClips())
                if picked:
                    break
                time.sleep(1)
            if not picked:
                record("Timeline.GetSelectedClips (selection)", "not_applicable",
                       f"no selection seen within {select_wait}s")
            else:
                match = len(picked) == 1 and selected_is(picked[0], clip)
                names = [item.GetName() for item in picked]
                record("Timeline.GetSelectedClips (selection)", "supported" if match else "error",
                       f"after a click returned {names}; it is the test clip: {match}",
                       {"names": names, "is_test_clip": match})
        return surface
    except Exception as exc:
        record("disposable project", "error", f"raised {exc!r}")
        return surface
    finally:
        result = delete_project_safely(pm, scratch_name, switch_to=original_name)
        current = pm.GetCurrentProject()
        current_name = current.GetName() if current else None
        still_listed = scratch_name in project_names(pm)
        print(f"  open project now {current_name!r}; {scratch_name} deleted: {not still_listed}")
        if not result.get("success") or still_listed:
            record("disposable project cleanup", "error",
                   f"{scratch_name} was not deleted: {result.get('detail')}")
        if current_name != original_name:
            record("disposable project cleanup", "error",
                   f"open project is {current_name!r}, expected {original_name!r}")


def emit(report, path):
    print("\n== summary ==")
    tally = {}
    for entry in report["results"]:
        tally[entry["status"]] = tally.get(entry["status"], 0) + 1
    for status, count in sorted(tally.items()):
        print(f"  {status:20} {count}")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
        print(f"\n  report written to {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", action="store_true",
                    help="use external scripting (Studio) instead of the in-app bridge")
    ap.add_argument("--read-only", action="store_true", help="list calls only; changes nothing")
    ap.add_argument("--any-version", action="store_true", help="run on a build other than 21.0.4.x")
    ap.add_argument("--select-wait", type=int, default=0,
                    help="seconds to wait for a person to select the test clip")
    ap.add_argument("--json", help="write the full report to this path")
    args = ap.parse_args()

    try:
        resolve, transport = connect(args.native)
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
    original_name, problems = preflight(resolve, pm, version, args.any_version, args.read_only)
    if problems:
        print("\nFATAL: preflight failed:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    report = {"product": product, "version": version, "transport": transport}
    report["read_only"] = probe_readonly(resolve, pm, original_name)
    if args.read_only:
        report["results"] = results
        emit(report, args.json)
        return 1 if any(r["status"] == "error" for r in results) else 0

    probe_burnin_delete(resolve)
    tmp = tempfile.mkdtemp(prefix="resolve_r2104_")
    try:
        prefs = os.path.join(tmp, "prefs")
        os.makedirs(prefs)
        probe_user_prefs(resolve, prefs)
        media = os.path.join(tmp, "media")
        os.makedirs(media)
        report["surface"] = probe_project(resolve, pm, original_name, media, args.select_wait)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    record("Resolve.LoadUserPreferencesPreset", "not_applicable",
           "deliberately not executed: it swaps the user's global preferences session-wide")
    if pm.GetCurrentDatabase() != database:
        record("database", "error", "the current database changed during the run")
    report["results"] = results
    emit(report, args.json)
    return 1 if any(r["status"] == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
