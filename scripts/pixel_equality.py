#!/usr/bin/env python3
"""Do GUI and headless render the same PIXELS? Per effect.

    python scripts/pixel_equality.py run --mode gui      --out px_gui.json
    python scripts/pixel_equality.py run --mode headless --out px_headless.json
    python scripts/pixel_equality.py compare px_gui.json px_headless.json

Everything measured until now compared structure and return values — clip
counts, source offsets, timings, byte counts. None of that can catch the failure
that actually reaches a client: a headless render that completes, produces a file
of the right length in the right codec, and contains **the wrong image** because
a grade, a transform or a Fusion comp was not applied.

The one render comparison that existed was byte-identical between modes, but it
was of a timeline with no grades and no effects. It proved the encoder is
deterministic. It said nothing about the image pipeline.

## How pixels are compared

Not by file hash — a container carries timestamps and UUIDs that differ between
runs regardless of the picture. Each render is decoded and hashed **per frame**
with ffmpeg's `framemd5`, so the comparison is of decoded image data only.
Identical framemd5 lists means identical pixels, frame for frame.

## The control that makes the result mean anything

Each effect is also compared against the **plain** baseline *within the same
mode*. If a grade does not change the picture relative to plain, then "GUI and
headless agree" is vacuous — both rendered the same ungraded image and the test
proved nothing. So every effect must first demonstrate `differs_from_plain:
true`, and any that does not is reported as `INEFFECTIVE` rather than as a pass.

This is the same trap that made the first capability differential report zero
differences: measuring something that was never actually set.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import resolve_runtime as rr  # noqa: E402
from src.utils.project_cleanup import delete_project_safely, save_project_if_safe  # noqa: E402
from src.utils.lut_paths import ensure_lut_in_master  # noqa: E402

WORK = Path.home() / "Movies" / "pixel_equality"
MEDIA = WORK / "source.mov"
LUT = WORK / "px_shift.cube"

#: Rendered lossless-ish and compared on DECODED frames, so the codec cannot
#: mask or manufacture a difference. ProRes 422 HQ is deterministic here and was
#: already shown to produce byte-identical output across modes on a plain cut.
RENDER_FORMAT, RENDER_CODEC = "mov", "ProRes422HQ"


def connect(timeout: float = 420.0) -> Any:
    api = os.environ.get(
        "RESOLVE_SCRIPT_API",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting")
    modules = str(Path(api) / "Modules")
    if modules not in sys.path:
        sys.path.append(modules)
    import DaVinciResolveScript as dvr
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resolve = dvr.scriptapp("Resolve")
        if resolve is not None:
            try:
                pm = resolve.GetProjectManager()
                if pm is not None and pm.GetCurrentDatabase():
                    return resolve
            except Exception:
                pass
        time.sleep(1)
    return None


def build_assets() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    if not MEDIA.exists():
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24:duration=2",
             "-pix_fmt", "yuv420p", "-c:v", "libx264", "-timecode", "01:00:00:00",
             "-y", str(MEDIA)], check=True, timeout=180)
    if not LUT.exists():
        # A blunt, unmistakable LUT: swap red and blue and lift. Subtlety is the
        # enemy here — the LUT exists to prove the grade path reached the
        # renderer, so its effect must be impossible to confuse with rounding.
        lines = ["TITLE \"px_shift\"", "LUT_3D_SIZE 2", "DOMAIN_MIN 0.0 0.0 0.0",
                 "DOMAIN_MAX 1.0 1.0 1.0"]
        for b in (0.0, 1.0):
            for g in (0.0, 1.0):
                for r in (0.0, 1.0):
                    lines.append(f"{min(b + 0.15, 1.0):.6f} {g:.6f} {min(r + 0.15, 1.0):.6f}")
        LUT.write_text("\n".join(lines) + "\n")


def frame_hashes(path: Path) -> List[str]:
    """Per-frame MD5 of DECODED video. Container metadata cannot influence it."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-map", "0:v:0", "-f", "framemd5", "-"],
        capture_output=True, text=True, timeout=600)
    hashes = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if parts:
            hashes.append(parts[-1].strip())
    return hashes


# ── effects ──────────────────────────────────────────────────────────────────
#
# Each returns a description of what it did, so a treatment that silently failed
# to apply is visible in the report rather than being read as a format that
# preserved nothing.

def effect_plain(item: Any, project: Any) -> Dict[str, Any]:
    return {"applied": True}


def effect_transform(item: Any, project: Any) -> Dict[str, Any]:
    return {"applied": all([
        item.SetProperty("ZoomX", 1.4), item.SetProperty("ZoomY", 1.4),
        item.SetProperty("Pan", 120.0), item.SetProperty("RotationAngle", 15.0)])}


def effect_cdl(item: Any, project: Any) -> Dict[str, Any]:
    ok = item.SetCDL({"NodeIndex": "1", "Slope": "1.0 0.6 0.4",
                      "Offset": "0.10 0.02 -0.05", "Power": "1.0 1.2 0.9",
                      "Saturation": "0.4"})
    return {"applied": bool(ok)}


def effect_lut(item: Any, project: Any) -> Dict[str, Any]:
    """`SetLUT` will not take an arbitrary path.

    Blackmagic's own note says the call succeeds only "for valid lut paths that
    Resolve has already discovered". Handed an absolute path to a freshly written
    .cube it returns False and reads back an empty string — which is exactly what
    the first run of this script did, quietly turning the grade-path test into a
    no-op. The LUT has to be inside the master LUT directory and referenced
    relative to it.
    """
    relative = ensure_lut_in_master(str(LUT))
    project.RefreshLUTList()
    graph = item.GetNodeGraph()
    if not (graph and relative):
        return {"applied": False, "reason": f"could not stage the LUT ({relative!r})"}
    ok = graph.SetLUT(1, relative)
    return {"applied": bool(ok), "staged_as": relative, "readback": graph.GetLUT(1)}


def effect_fusion(item: Any, project: Any) -> Dict[str, Any]:
    """An EMPTY Fusion comp cannot change the picture, so one is not a test.

    The first run added a bare comp and unsurprisingly rendered pixels identical
    to plain — which says nothing about whether Fusion reaches the renderer. A
    tool is added and wired between MediaIn and MediaOut so there is something to
    detect. Whether that succeeds is itself recorded: this repository already has
    a note that API-created Fusion comps on media clips never render, and this is
    the measurement that either confirms it or does not.
    """
    comp = item.AddFusionComp()
    if not comp:
        return {"applied": False, "reason": "AddFusionComp returned nothing"}
    detail: Dict[str, Any] = {"comp_count": item.GetFusionCompCount()}
    try:
        tools = {}
        for tool in (comp.GetToolList(False) or {}).values():
            try:
                tools.setdefault(tool.ID, tool)
            except Exception:
                continue
        detail["tools_present"] = sorted(tools)
        media_in, media_out = tools.get("MediaIn"), tools.get("MediaOut")
        blur = comp.AddTool("Blur")
        detail["tool_added"] = bool(blur)
        if blur and media_in is not None and media_out is not None:
            blur.SetInput("XBlurSize", 20.0)
            # BOTH connections. The first attempt wired only MediaOut -> Blur and
            # left the Blur with no source, so the comp had nothing to output and
            # the render job came back "Failed" with an 887-byte file. That was a
            # bug in this harness, and it would have been written up as "a Fusion
            # comp breaks the render" — a wrong finding about Resolve produced by
            # a wrong graph.
            blur.ConnectInput("Input", media_in)
            media_out.ConnectInput("Input", blur)
            detail["wired"] = True
        else:
            detail["wired"] = False
            detail["reason"] = f"media_in={bool(media_in)} media_out={bool(media_out)}"
    except Exception as exc:
        detail["tool_error"] = f"{type(exc).__name__}: {exc}"
    detail["applied"] = bool(detail.get("wired"))
    return detail


EFFECTS = [
    ("plain", effect_plain),
    ("transform", effect_transform),
    ("cdl", effect_cdl),
    ("lut", effect_lut),
    ("fusion_comp", effect_fusion),
]


class PixelRun:
    def __init__(self, resolve: Any) -> None:
        self.resolve = resolve
        self.pm = resolve.GetProjectManager()
        self.name = f"PIXEQ_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.project = self.pool = None
        self.incumbent: Optional[str] = None
        self.renders = WORK / "renders"

    def setup(self) -> Dict[str, Any]:
        incumbent = self.pm.GetCurrentProject()
        self.incumbent = incumbent.GetName() if incumbent else None
        save_project_if_safe(self.pm)
        if not self.pm.CreateProject(self.name):
            raise RuntimeError("could not create project")
        self.pm.LoadProject(self.name)
        self.project = self.pm.GetCurrentProject()
        self.pool = self.project.GetMediaPool()
        build_assets()
        clips = self.resolve.GetMediaStorage().AddItemListToMediaPool([str(MEDIA)]) or []
        if not clips:
            raise RuntimeError("media import failed")
        self.clip = clips[0]
        self.frames = int(self.clip.GetClipProperty("Frames") or 0)
        codecs = self.project.GetRenderCodecs(RENDER_FORMAT) or {}
        if RENDER_CODEC not in codecs.values():
            raise RuntimeError(f"{RENDER_CODEC} not offered for {RENDER_FORMAT}")
        self.project.SetCurrentRenderFormatAndCodec(RENDER_FORMAT, RENDER_CODEC)
        shutil.rmtree(self.renders, ignore_errors=True)
        self.renders.mkdir(parents=True, exist_ok=True)
        return {"project": self.name, "frames": self.frames, "media": str(MEDIA)}

    def render_effect(self, label: str, apply_effect) -> Dict[str, Any]:
        timeline = self.pool.CreateEmptyTimeline(f"PX_{label}")
        self.project.SetCurrentTimeline(timeline)
        self.pool.AppendToTimeline([{"mediaPoolItem": self.clip, "startFrame": 0,
                                     "endFrame": self.frames - 1}])
        items = timeline.GetItemListInTrack("video", 1) or []
        if not items:
            return {"error": "no timeline item"}
        applied = apply_effect(items[0], self.project)

        target = self.renders / label
        target.mkdir(parents=True, exist_ok=True)
        self.project.SetRenderSettings({"TargetDir": str(target), "CustomName": label,
                                        "SelectAllFrames": True})
        job = self.project.AddRenderJob()
        if not job:
            return {"error": "AddRenderJob returned nothing", "applied": applied}
        self.project.StartRendering(job, isInteractiveMode=False)
        deadline = time.monotonic() + 600
        while self.project.IsRenderingInProgress() and time.monotonic() < deadline:
            time.sleep(1)
        status = (self.project.GetRenderJobStatus(job) or {}).get("JobStatus")
        self.project.DeleteRenderJob(job)
        files = sorted(p for p in target.glob(f"{label}*") if p.is_file() and p.stat().st_size)
        if not files:
            return {"error": "no output file", "status": status, "applied": applied}
        hashes = frame_hashes(files[0])
        return {"applied": applied, "status": status, "file": files[0].name,
                "bytes": files[0].stat().st_size, "frames_hashed": len(hashes),
                "frame_hashes": hashes}

    def teardown(self) -> Dict[str, Any]:
        notes: Dict[str, Any] = {}
        try:
            save_project_if_safe(self.pm)
            notes["closed"] = bool(self.pm.CloseProject(self.pm.GetCurrentProject()))
            if self.incumbent and self.incumbent != self.name:
                notes["restored"] = bool(self.pm.LoadProject(self.incumbent))
            notes["deleted"] = delete_project_safely(self.pm, self.name,
                                                     switch_to=self.incumbent)["success"]
        except Exception as exc:
            notes["error"] = repr(exc)
        shutil.rmtree(self.renders, ignore_errors=True)
        return notes


def run(mode: str, out: Path) -> int:
    observed = rr.runtime_mode()
    if observed["running"] and bool(observed["headless"]) != (mode == "headless"):
        print("REFUSE: Resolve is running in the other mode.", file=sys.stderr)
        return 1
    resolve = connect()
    if resolve is None:
        print("REFUSE: no healthy Resolve.", file=sys.stderr)
        return 2

    run_ = PixelRun(resolve)
    report: Dict[str, Any] = {"metadata": {
        "mode": mode, "headless": observed["headless"],
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": resolve.GetVersionString(),
        "render": f"{RENDER_FORMAT}/{RENDER_CODEC}"}, "effects": {}}
    try:
        report["setup"] = run_.setup()
        print(f"setup: {report['setup']}", flush=True)
        for label, fn in EFFECTS:
            result = run_.render_effect(label, fn)
            report["effects"][label] = result
            print(f"  {label:12} applied={result.get('applied')} "
                  f"frames={result.get('frames_hashed')} bytes={result.get('bytes')} "
                  f"{result.get('error','')}", flush=True)
    finally:
        report["teardown"] = run_.teardown()

    # Within-mode control: did each effect actually change the picture?
    plain = report["effects"].get("plain", {}).get("frame_hashes")
    for label, entry in report["effects"].items():
        if label == "plain" or not plain or not entry.get("frame_hashes"):
            continue
        entry["differs_from_plain"] = entry["frame_hashes"] != plain
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"report: {out}")
    return 0


def compare(gui_path: Path, headless_path: Path, out: Optional[Path]) -> int:
    gui, headless = json.loads(gui_path.read_text()), json.loads(headless_path.read_text())
    if gui["metadata"]["headless"] is not False or headless["metadata"]["headless"] is not True:
        print("REFUSE: mode metadata does not match the arguments.", file=sys.stderr)
        return 1

    lines = ["# Pixel equality: GUI vs headless rendered frames", "",
             "Frames are compared after decoding (ffmpeg `framemd5`), so container "
             "metadata cannot influence the result. `effective` is the within-mode "
             "control: whether the effect changed the picture at all relative to "
             "`plain`. An effect that is not effective makes its mode comparison "
             "meaningless, and is called out rather than counted as a pass.", "",
             "| effect | effective (GUI) | effective (headless) | pixels identical across modes |",
             "| --- | --- | --- | --- |"]
    verdicts = {}
    for label, _ in EFFECTS:
        g, h = gui["effects"].get(label, {}), headless["effects"].get(label, {})
        gh, hh = g.get("frame_hashes"), h.get("frame_hashes")
        if not gh or not hh:
            verdict = "render-failed"
        elif gh == hh:
            verdict = "**identical**"
        else:
            same = sum(1 for a, b in zip(gh, hh) if a == b)
            verdict = f"**DIFFER** ({same}/{len(gh)} frames match)"
        verdicts[label] = verdict
        eff_g = "—" if label == "plain" else str(g.get("differs_from_plain"))
        eff_h = "—" if label == "plain" else str(h.get("differs_from_plain"))
        lines.append(f"| {label} | {eff_g} | {eff_h} | {verdict} |")

    ineffective = [l for l, _ in EFFECTS if l != "plain"
                   and not gui["effects"].get(l, {}).get("differs_from_plain")]
    if ineffective:
        lines += ["", "## Ineffective treatments — these prove nothing", "",
                  "These did not change the rendered picture relative to `plain` in the GUI, so "
                  "agreement between modes says only that both rendered the same unaffected "
                  "image: " + ", ".join(f"`{l}`" for l in ineffective) + "."]
    text = "\n".join(lines) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--mode", choices=("gui", "headless"), required=True)
    r.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare")
    c.add_argument("gui", type=Path)
    c.add_argument("headless", type=Path)
    c.add_argument("--out", type=Path)
    args = parser.parse_args()
    return run(args.mode, args.out) if args.command == "run" else \
        compare(args.gui, args.headless, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
