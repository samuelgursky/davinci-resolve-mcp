"""Walk the stress harness's setup sequence one call at a time, on a cold headless Resolve.

Two things are recorded around EVERY call: how long it took, and whether the
current database is still attached afterwards. The hang and the null database
have so far only been seen together, from two different clients, so neither is
known to cause the other. Checking the database between every step is what turns
that correlation into an ordering — if the database goes null one step *before*
the hang, it is a cause; if it only goes null once something is already blocked,
it is a symptom.

Each step has its own alarm, so a hang is reported with the culprit named instead
of parking the process forever.
"""
import json
import signal
import sys
import time
from pathlib import Path

sys.path.append(
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"
)
import DaVinciResolveScript as dvr  # noqa: E402


class Hang(Exception):
    pass


def _alarm(*_):
    raise Hang()


signal.signal(signal.SIGALRM, _alarm)
RESULTS = []


def step(label, fn, secs=45, pm=None):
    """Run one call, timed, with the database checked immediately afterwards."""
    signal.alarm(secs)
    started = time.monotonic()
    outcome, value = "ok", None
    try:
        value = fn()
    except Hang:
        outcome = "HUNG"
    except Exception as exc:
        outcome, value = "error", f"{type(exc).__name__}: {exc}"
    finally:
        signal.alarm(0)
    elapsed = round(time.monotonic() - started, 1)

    db = "unchecked"
    if pm is not None and outcome != "HUNG":
        signal.alarm(20)
        try:
            db = pm.GetCurrentDatabase()
        except Hang:
            db = "HUNG-checking-db"
        except Exception as exc:
            db = f"error: {type(exc).__name__}"
        finally:
            signal.alarm(0)

    record = {"step": label, "outcome": outcome, "seconds": elapsed,
              "value": repr(value)[:120], "database_after": db}
    RESULTS.append(record)
    print(json.dumps(record), flush=True)
    if outcome == "HUNG":
        print(f"\n>>> CULPRIT: {label} hung after {secs}s", flush=True)
        dump()
        raise SystemExit(9)
    return value


def dump():
    Path(sys.argv[1]).write_text(json.dumps(RESULTS, indent=2, default=str), encoding="utf-8")


def main():
    resolve = None
    for _ in range(420):
        resolve = dvr.scriptapp("Resolve")
        if resolve is not None:
            break
        time.sleep(1)
    if resolve is None:
        raise SystemExit("no Resolve")

    pm = step("GetProjectManager", resolve.GetProjectManager, pm=None)
    step("GetCurrentDatabase (baseline)", pm.GetCurrentDatabase, pm=pm)
    step("GetProjectListInCurrentFolder", lambda: len(pm.GetProjectListInCurrentFolder() or []), pm=pm)
    incumbent = step("GetCurrentProject().GetName()",
                     lambda: (pm.GetCurrentProject().GetName() if pm.GetCurrentProject() else None), pm=pm)
    # The first suspect: SaveProject on the never-saved default project. It is
    # the first mutating call the harness makes, and it is documented to return
    # False for exactly this project.
    step("SaveProject (incumbent)", pm.SaveProject, pm=pm)

    name = "COLD_HEADLESS_PROBE"
    step("CreateProject", lambda: bool(pm.CreateProject(name)), pm=pm)
    step("LoadProject", lambda: bool(pm.LoadProject(name)), pm=pm)
    project = step("GetCurrentProject", pm.GetCurrentProject, pm=pm)
    if project is None:
        dump()
        raise SystemExit("no project after LoadProject")

    step("GetMediaStorage", resolve.GetMediaStorage, pm=pm)
    step("project.GetMediaPool", project.GetMediaPool, pm=pm)
    step("GetRenderFormats", lambda: len(project.GetRenderFormats() or {}), pm=pm)
    step("CreateEmptyTimeline", lambda: bool(project.GetMediaPool().CreateEmptyTimeline("COLD_TL")), pm=pm)

    # Teardown, itself instrumented — the harness's teardown is as likely a
    # suspect as its setup, and it runs on every iteration boundary.
    step("SaveProject (scratch)", pm.SaveProject, pm=pm)
    step("CloseProject", lambda: bool(pm.CloseProject(pm.GetCurrentProject())), pm=pm)
    if incumbent:
        step("LoadProject (incumbent)", lambda: bool(pm.LoadProject(incumbent)), pm=pm)
    step("DeleteProject", lambda: bool(pm.DeleteProject(name)), pm=pm)
    dump()
    print("\n>>> COMPLETED WITH NO HANG", flush=True)


if __name__ == "__main__":
    main()
