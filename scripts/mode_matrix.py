#!/usr/bin/env python3
"""Exhaustively difference GUI against headless Resolve, surviving hangs.

    python scripts/mode_matrix.py run --mode gui      --out runs/gui.jsonl
    python scripts/mode_matrix.py run --mode headless --out runs/headless.jsonl
    python scripts/mode_matrix.py compare runs/gui.jsonl runs/headless.jsonl \
        --out docs/reference/headless-capability-matrix.md

## The architecture, and why it is not one script

`ProjectManager.SaveProject()` on the never-saved `Untitled Project` never
returns headless. Any harness that calls it in-process stops there, and its
report is whatever it wrote before it died. The first differential could not have
found that bug, and did not.

So this splits in two:

  - a **worker** that runs probes in order and streams each result to JSONL,
    flushed per line;
  - a **supervisor** that runs the worker with a deadline. If the worker exits
    early or overruns, the supervisor reads the JSONL, sees which probe has no
    result, records it as `hang`, restarts Resolve, waits for it to be healthy,
    and relaunches the worker to resume *after* the offender.

The consequence worth stating: a hang costs one probe and one Resolve restart,
not the run. That is what makes "exhaustive" possible at all.

## Health, not liveness

Between batches the supervisor requires `GetCurrentDatabase()` to be non-None.
Resolve can accept scripting connections, answer product/version/page queries,
and still have no database attached — in that state every project call returns
False forever. A liveness check passes straight through it; only the database
reading catches it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import mode_matrix as mm  # noqa: E402
from src.utils import resolve_runtime as rr  # noqa: E402
from src.utils.probe_catalogue import CATALOGUE, fingerprint  # noqa: E402

WORKER = Path(__file__).resolve().parent / "mode_matrix_worker.py"


def scripting_env() -> Dict[str, str]:
    env = dict(os.environ)
    api = env.get(
        "RESOLVE_SCRIPT_API",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
    )
    env["RESOLVE_SCRIPT_API"] = api
    env.setdefault(
        "RESOLVE_SCRIPT_LIB",
        "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
    )
    modules = str(Path(api) / "Modules")
    env["PYTHONPATH"] = f"{modules}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else modules
    env.pop("DAVINCI_RESOLVE_BRIDGE", None)
    return env


# ── Resolve supervision ──────────────────────────────────────────────────────


def health(timeout: float = 420.0) -> Optional[Dict[str, Any]]:
    """Wait for a Resolve whose ProjectManager has a database attached."""
    code = (
        "import DaVinciResolveScript as d, json, time, sys\n"
        "for _ in range(int(sys.argv[1])):\n"
        "    r = d.scriptapp('Resolve')\n"
        "    if r is not None:\n"
        "        try:\n"
        "            pm = r.GetProjectManager()\n"
        "            db = pm.GetCurrentDatabase() if pm else None\n"
        "            if db:\n"
        "                print(json.dumps(db)); sys.exit(0)\n"
        "        except Exception: pass\n"
        "    time.sleep(1)\n"
        "sys.exit(3)\n"
    )
    try:
        out = subprocess.run([sys.executable, "-c", code, str(int(timeout))],
                             env=scripting_env(), capture_output=True, text=True,
                             timeout=timeout + 60)
    except subprocess.TimeoutExpired:
        print("  health: timed out waiting for a database", file=sys.stderr)
        return None
    if out.returncode != 0:
        # Say WHY. "no healthy Resolve" with no reason sent this investigation
        # looking at Resolve twice when the probe subprocess had simply failed to
        # start — an unhelpful error of exactly the kind this study keeps finding
        # in the API it is measuring.
        detail = (out.stderr or out.stdout or "").strip().splitlines()
        print(f"  health: probe exited {out.returncode}"
              + (f": {detail[-1][:200]}" if detail else " with no output"), file=sys.stderr)
        return None
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        print(f"  health: unparseable output {out.stdout.strip()[:200]!r}", file=sys.stderr)
        return None


def stop_resolve(force_after: float = 30.0) -> str:
    """Quit, escalating to a kill. Returns how it went."""
    code = (
        "import DaVinciResolveScript as d, signal\n"
        "signal.signal(signal.SIGALRM, lambda *a: (_ for _ in ()).throw(SystemExit(7)))\n"
        "signal.alarm(20)\n"
        "r = d.scriptapp('Resolve')\n"
        "r and r.Quit()\n"
    )
    subprocess.run([sys.executable, "-c", code], env=scripting_env(),
                   capture_output=True, text=True, timeout=60, check=False)
    deadline = time.monotonic() + force_after
    while time.monotonic() < deadline:
        if not (rr.resolve_processes() or []):
            return "clean"
        time.sleep(1)
    subprocess.run(["pkill", "-9", "-f", "MacOS/Resolve"], check=False)
    time.sleep(8)
    return "forced"


def start_resolve(headless: bool) -> bool:
    command = rr.launch_command(headless=headless)
    if command is None:
        return False
    subprocess.Popen(command, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def restart(headless: bool) -> Optional[Dict[str, Any]]:
    how = stop_resolve()
    print(f"    resolve stopped ({how}); restarting {'headless' if headless else 'gui'}", flush=True)
    if not start_resolve(headless):
        return None
    # Generous: a boot after an unclean shutdown was measured at 2m05s to a
    # usable script server, against under 3s clean. Giving up early here would
    # abort the run for a Resolve that was merely slow.
    return health(420.0)


# ── the run ──────────────────────────────────────────────────────────────────


def completed_probes(path: Path) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return results
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn final line from a killed worker
        # `_start` breadcrumbs are phase markers, not results; `last_phase`
        # reads them. Keyed apart so a marker can never be mistaken for an
        # outcome.
        if "probe" in record:
            results[record["probe"]] = record
    return results


def last_phase(path: Path) -> Optional[Dict[str, Any]]:
    """The most recent phase breadcrumb, naming what was in flight."""
    if not path.exists():
        return None
    marker = None
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "_start" in record:
            marker = record
    return marker


def append(path: Path, record: Dict[str, Any]) -> None:
    with path.open("a") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


def run(mode: str, out: Path, only: Optional[List[str]], batch_timeout: float) -> int:
    headless = mode == "headless"
    observed = rr.runtime_mode()
    if observed["running"] and bool(observed["headless"]) != headless:
        print(f"REFUSE: a Resolve is running in the other mode: {observed['command_lines']}",
              file=sys.stderr)
        return 1
    if not observed["running"]:
        start_resolve(headless)
    db = health()
    if db is None:
        print("REFUSE: no healthy Resolve (no database attached).", file=sys.stderr)
        return 2

    # Blocking probes are opt-in by name. One of them stops the whole
    # application in both modes, costing a force-kill and a slow restart, so a
    # sweep that included them by default could never run to completion
    # unattended — which is the entire point of a sweep.
    if only:
        planned = [p.name for p in CATALOGUE if p.name in only]
    else:
        planned = [p.name for p in CATALOGUE if not p.blocking]
    skipped_blocking = [p.name for p in CATALOGUE if p.blocking and p.name not in planned]
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"mode={mode} db={json.dumps(db)} probes={len(planned)} out={out}", flush=True)
    if skipped_blocking:
        # Never silently: an excluded probe that vanishes from the report reads
        # as one that passed.
        print(f"  excluded (blocking, run explicitly with --only): {', '.join(skipped_blocking)}",
              flush=True)

    hangs = 0
    while True:
        done = completed_probes(out)
        remaining = [n for n in planned if n not in done]
        if not remaining:
            break
        print(f"  worker: {len(remaining)} probe(s) remaining, starting at {remaining[0]}", flush=True)
        proc = subprocess.Popen(
            [sys.executable, "-u", str(WORKER), "--out", str(out), "--probes", *remaining],
            env=scripting_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            proc.communicate(timeout=batch_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()

        after = completed_probes(out)
        newly = [n for n in remaining if n in after]
        still = [n for n in remaining if n not in after]
        if not still:
            break
        # The first unrecorded probe is the one that was in flight when the
        # worker stopped. Nothing else can have taken it down: results are
        # flushed per line, in order.
        culprit = still[0]
        probe = next(p for p in CATALOGUE if p.name == culprit)
        marker = last_phase(out) or {}
        phase = marker.get("phase") if marker.get("_start") == culprit else "unknown"
        hangs += 1
        print(f"  !! {culprit} did not return in phase={phase} "
              f"(worker completed {len(newly)} probe(s) first)", flush=True)
        append(out, {
            "probe": culprit, "category": probe.category, "outcome": "hang",
            "value": None, "seconds": None, "mode": mode, "phase": phase,
            "catalogue": fingerprint(),
            # A hang during `state` setup is NOT evidence about the probe's own
            # call; it is evidence about reaching the state. Recorded as such so
            # the comparison does not report a bug in the wrong place.
            "detail": ("hung while setting up its state, not in the probe call itself"
                       if phase == "state" else
                       "worker died or overran with this probe's call in flight"),
        })
        if restart(headless) is None:
            print("REFUSE: Resolve did not come back healthy after a hang.", file=sys.stderr)
            return 3

    results = completed_probes(out)
    counts: Dict[str, int] = {}
    for record in results.values():
        counts[record.get("outcome", "?")] = counts.get(record.get("outcome", "?"), 0) + 1
    print(json.dumps({"mode": mode, "probes": len(results), "outcomes": counts,
                      "hangs_recovered": hangs}, indent=2))
    return 0


def compare(gui_paths: List[Path], headless_paths: List[Path], out: Optional[Path]) -> int:
    gui_stores, headless_stores = [], []
    for label, paths, sink in (("gui", gui_paths, gui_stores),
                               ("headless", headless_paths, headless_stores)):
        for path in paths:
            store = completed_probes(path)
            modes = {r.get("mode") for r in store.values()}
            # A mislabeled file inverts every verdict silently; the recorded mode
            # is the check, not the filename.
            if modes and modes != {label}:
                print(f"REFUSE: {path} was labelled {label} but contains {modes}", file=sys.stderr)
                return 1
            stamps = {r.get("catalogue") for r in store.values() if r.get("catalogue")}
            if stamps and stamps != {fingerprint()}:
                print(f"REFUSE: {path} was recorded with catalogue {stamps}, "
                      f"current is {fingerprint()}. Re-run it; comparing across "
                      f"catalogue versions reports harness changes as findings.",
                      file=sys.stderr)
                return 1
            sink.append(store)
    matrix = mm.build_repeated_matrix(gui_stores, headless_stores)
    matrix["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    text = mm.render_markdown(matrix)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        out.with_suffix(".json").write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")
    print(text)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--mode", choices=("gui", "headless"), required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--only", nargs="*")
    r.add_argument("--batch-timeout", type=float, default=900.0)
    c = sub.add_parser("compare")
    # Lists, not single files: one run per mode reports flakes as findings, which
    # was measured happening. Repeats are how a difference is distinguished from
    # noise.
    c.add_argument("--gui", type=Path, nargs="+", required=True)
    c.add_argument("--headless", type=Path, nargs="+", required=True)
    c.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        return run(args.mode, args.out, args.only, args.batch_timeout)
    return compare(args.gui, args.headless, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
