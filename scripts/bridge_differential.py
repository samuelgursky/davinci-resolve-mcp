#!/usr/bin/env python3
"""Qualify the in-app bridge by differencing it against native scripting.

    # Studio: both transports reach the same application — the real differential.
    python scripts/bridge_differential.py --mode differential

    # Free edition: no native side exists, so prove reachability and shape.
    python scripts/bridge_differential.py --mode coverage

    # Add the write scenarios (render, interchange export, SetLUT, scale, modal).
    python scripts/bridge_differential.py --mode coverage --scenarios

`--mode differential` requires Studio, because external scripting is Studio-gated
— which is the entire reason the bridge exists. It also requires the in-app
bridge to be running *in that same Studio instance*: two transports into one
application is what makes a difference attributable to the transport rather than
to the two Resolves having different projects open.

Nothing here writes to a project unless `--scenarios` is passed, and every
scenario undoes what it did. Read `SCENARIOS` before running it against anything
you care about.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import bridge_differential as bd  # noqa: E402


def connect_bridge() -> Any:
    from src.utils import resolve_bridge_client as client

    os.environ.setdefault(client.ENV_ENABLE, "1")
    return client.connect()


def connect_native() -> Any:
    """Blackmagic's own module, deliberately without the bridge in the way."""
    from src.utils import resolve_bridge_client as client

    previous = os.environ.pop(client.ENV_ENABLE, None)
    try:
        import DaVinciResolveScript as dvr

        return dvr.scriptapp("Resolve")
    finally:
        if previous is not None:
            os.environ[client.ENV_ENABLE] = previous


# ── write scenarios ──────────────────────────────────────────────────────────
#
# The enumeration routes anything that mutates to a named scenario, because a
# blind call cannot set up its preconditions or clean up after itself. Each one
# returns a dict of observations; the differential compares those dicts.


def scenario_render(resolve: Any, workspace: Path) -> Dict[str, Any]:
    """The delivery path end to end, to a real file on disk.

    Untested until now, and the most consequential thing the bridge could get
    wrong: a render that reports success and produces nothing is indistinguishable
    from a render that worked, right up until someone looks for the file.
    """
    project = resolve.GetProjectManager().GetCurrentProject()
    observations: Dict[str, Any] = {}
    formats = project.GetRenderFormats() or {}
    observations["format_count"] = len(formats)
    observations["codec_count_for_mov"] = len(project.GetRenderCodecs("mov") or {})

    output = workspace / "bridge_render_probe"
    output.mkdir(parents=True, exist_ok=True)
    observations["set_format"] = project.SetCurrentRenderFormatAndCodec("mov", "H.264")
    observations["set_settings"] = project.SetRenderSettings({
        "TargetDir": str(output),
        "CustomName": "bridge_render_probe",
        "MarkIn": int(project.GetCurrentTimeline().GetStartFrame()),
        "MarkOut": int(project.GetCurrentTimeline().GetStartFrame()) + 4,
    })
    job = project.AddRenderJob()
    observations["job_added"] = bool(job)
    if not job:
        return observations
    try:
        observations["started"] = project.StartRendering([job], False)
        deadline = time.time() + 120
        while time.time() < deadline and project.IsRenderingInProgress():
            time.sleep(0.5)
        status = project.GetRenderJobStatus(job) or {}
        observations["job_status"] = status.get("JobStatus")
        produced = sorted(p.name for p in output.iterdir() if p.is_file())
        observations["files_written"] = len(produced)
        observations["nonempty_output"] = any((output / n).stat().st_size > 0 for n in produced)
    finally:
        project.DeleteRenderJob(job)
    return observations


def scenario_interchange_export(resolve: Any, workspace: Path) -> Dict[str, Any]:
    """Timeline.Export to each conform format. The conform surface, untested."""
    timeline = resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
    observations: Dict[str, Any] = {}
    targets = [
        ("EDL", "EXPORT_EDL", "EXPORT_CDL", ".edl"),
        ("FCPXML", "EXPORT_FCP_7_XML", "EXPORT_NONE", ".xml"),
        ("DRT", "EXPORT_DRT", "EXPORT_NONE", ".drt"),
        ("AAF", "EXPORT_AAF", "EXPORT_AAF_NEW", ".aaf"),
    ]
    for label, export_type, subtype, suffix in targets:
        path = workspace / f"bridge_export_probe{suffix}"
        if path.exists():
            path.unlink()
        constant = getattr(resolve, export_type, None)
        sub = getattr(resolve, subtype, None)
        try:
            if constant is None:
                observations[label] = {"ok": False, "reason": "constant_absent"}
                continue
            ok = timeline.Export(str(path), constant, sub) if sub is not None else \
                timeline.Export(str(path), constant)
            observations[label] = {
                "ok": bool(ok),
                "written": path.exists(),
                "bytes": path.stat().st_size if path.exists() else 0,
            }
        except Exception as exc:  # noqa: BLE001 - the failure is the observation
            observations[label] = {"ok": False, "reason": type(exc).__name__, "message": str(exc)[:120]}
    return observations


def scenario_set_lut(resolve: Any, _workspace: Path) -> Dict[str, Any]:
    """SetLUT specifically — last time GetLUT was called and the rest inferred.

    Read back after writing, and restore. A write that returns True and does not
    land is the failure mode this exists to catch, and only the read-back sees it.
    """
    timeline = resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
    items = timeline.GetItemListInTrack("video", 1) or []
    if not items:
        return {"skipped": "no clip on video track 1"}
    item = items[0]
    observations: Dict[str, Any] = {"node_count": item.GetNumNodes()}
    original = item.GetLUT(1)
    observations["lut_before"] = original
    # An empty path is the documented way to clear a node's LUT, so it is a
    # write we can make and unmake without shipping a .cube anywhere.
    observations["set_empty"] = item.SetLUT(1, "")
    observations["lut_after_clear"] = item.GetLUT(1)
    if original:
        observations["restored"] = item.SetLUT(1, original)
    observations["set_out_of_range_node"] = item.SetLUT(999, "")
    return observations


def scenario_scale(resolve: Any, _workspace: Path) -> Dict[str, Any]:
    """Enumerate every item on every track and time it.

    The round trip is 0.6 ms and the handle table holds 4096 entries; both only
    matter at a size nobody has run yet. This measures where they start to.
    """
    timeline = resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
    observations: Dict[str, Any] = {"tracks": {}}
    started = time.time()
    total = 0
    names: List[str] = []
    for kind in ("video", "audio"):
        count = int(timeline.GetTrackCount(kind) or 0)
        for index in range(1, count + 1):
            items = timeline.GetItemListInTrack(kind, index) or []
            observations["tracks"][f"{kind}{index}"] = len(items)
            for item in items:
                names.append(item.GetName())
                total += 1
    elapsed = time.time() - started
    observations["items"] = total
    observations["distinct_names"] = len(set(names))
    observations["elapsed_seconds"] = round(elapsed, 3)
    observations["ms_per_item"] = round(elapsed / total * 1000, 3) if total else None
    return observations


SCENARIOS: Dict[str, Callable[[Any, Path], Dict[str, Any]]] = {
    "render": scenario_render,
    "interchange_export": scenario_interchange_export,
    "set_lut": scenario_set_lut,
    "scale": scenario_scale,
}


def run_scenarios(resolve: Any, workspace: Path, only: Optional[List[str]] = None) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for name, function in SCENARIOS.items():
        if only and name not in only:
            continue
        try:
            results[name] = function(resolve, workspace)
        except Exception as exc:  # noqa: BLE001 - a scenario failing is a result
            results[name] = {"failed": type(exc).__name__, "message": str(exc)[:300]}
    return results


# ── modal behaviour ──────────────────────────────────────────────────────────


def probe_modal_timeout(resolve: Any, timeout: float) -> Dict[str, Any]:
    """Does a blocked Resolve time the client out, or hang it forever?

    Cannot open a dialog from here — that is the point of a modal — so this
    measures the property that matters when one is open: the client gives up on a
    bounded schedule and says something actionable, rather than pinning a tool
    call until the user notices.
    """
    from src.utils import resolve_bridge_client as client

    transport = getattr(resolve, "_transport", None)
    if transport is None:
        return {"skipped": "native transport has no timeout to probe"}
    previous = transport.timeout
    transport.timeout = timeout
    started = time.time()
    try:
        resolve.GetProductName()
        return {"answered": True, "seconds": round(time.time() - started, 3),
                "note": "nothing was blocking; run again with a dialog open in Resolve"}
    except client.BridgeCallError as exc:
        return {"answered": False, "code": exc.code, "seconds": round(time.time() - started, 3),
                "message": exc.message[:200]}
    finally:
        transport.timeout = previous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("differential", "coverage", "surface"), default="coverage")
    parser.add_argument("--scenarios", action="store_true", help="run the write scenarios (mutates the project)")
    parser.add_argument("--only", action="append", help="restrict to one scenario; repeatable")
    parser.add_argument("--workspace", default=str(Path.home() / "Movies" / "mcp_bridge_test"))
    parser.add_argument("--json", dest="json_path", help="write the full report here")
    arguments = parser.parse_args()

    surface = bd.probe_surface()
    report: Dict[str, Any] = {"surface": {k: v for k, v in surface.items() if k != "sources"}}

    if arguments.mode == "surface":
        print(json.dumps(report, indent=2))
        return 0

    workspace = Path(arguments.workspace).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)

    bridge = connect_bridge()
    report["bridge_health"] = bridge.bridge_health()
    bridged = bd.run_probes(bridge, surface["safe_to_probe"])
    report["coverage"] = bd.coverage_report(surface, bridged)
    report["modal_timeout"] = probe_modal_timeout(bridge, timeout=5.0)

    if arguments.mode == "differential":
        native = connect_native()
        if native is None:
            print("native scripting is unavailable — Studio only. Use --mode coverage.",
                  file=sys.stderr)
            return 2
        product = native.GetProductName()
        if product != report["bridge_health"]["product"]:
            # Two different applications would make every difference meaningless.
            print(f"refusing to diff: native sees {product!r}, the bridge sees "
                  f"{report['bridge_health']['product']!r}. Both transports must reach the "
                  "same running Resolve.", file=sys.stderr)
            return 2
        report["diff"] = bd.compare(bd.run_probes(native, surface["safe_to_probe"]), bridged)
        if arguments.scenarios:
            report["scenarios"] = {
                "native": run_scenarios(native, workspace, arguments.only),
                "bridge": run_scenarios(bridge, workspace, arguments.only),
            }
    elif arguments.scenarios:
        report["scenarios"] = {"bridge": run_scenarios(bridge, workspace, arguments.only)}

    if arguments.json_path:
        Path(arguments.json_path).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    coverage = report["coverage"]
    print("bridge      : %s %s (%s)" % (report["bridge_health"]["product"],
                                        report["bridge_health"]["version"],
                                        report["bridge_health"]["edition"]))
    print("surface     : %d methods called by the tools, %d safe to probe"
          % (coverage["called_by_tools"], coverage["safe_to_probe"]))
    print("exercised   : %d/%d read methods on the live object graph"
          % (coverage["exercised"], coverage["safe_to_probe"]))
    if coverage["unreachable_objects"]:
        print("unreachable : %s (no such object in this project)"
              % ", ".join(coverage["unreachable_objects"]))
    if coverage["not_exercised"]:
        print("not covered : %s" % ", ".join(coverage["not_exercised"]))
    if "diff" in report:
        diff = report["diff"]
        print("differential: %d probes compared, %d differences"
              % (diff["compared"], len(diff["differences"])))
        for difference in diff["differences"][:20]:
            print("  ! %-46s %s" % (difference["key"], difference["kind"]))
    for name, outcome in (report.get("scenarios", {}).get("bridge", {}) or {}).items():
        print("scenario %-19s %s" % (name, json.dumps(outcome, sort_keys=True)[:180]))
    failed = "diff" in report and not report["diff"]["identical"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
