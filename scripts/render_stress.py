#!/usr/bin/env python3
"""Stress a Resolve render session until it breaks, and record how it broke.

The capability differential (`scripts/headless_differential.py`) answers "can
headless do this at all". It cannot answer "does headless survive a real
delivery", because its render is two seconds of 640x360 H.264. This harness
answers the second question, on synthetic media, without needing production
assets:

    # 20 ProRes renders in one headless session, 60s of DCP-like J2K each
    python scripts/render_stress.py --mode headless --iterations 20 --duration 60

    # the same run with a UI, for the comparison that makes it mean something
    python scripts/render_stress.py --mode gui --iterations 20 --duration 60

    # once production assets are available, same harness, real source
    python scripts/render_stress.py --mode headless --source /path/to/dcp_video.mxf

The synthetic source is JPEG 2000 in MXF OP1A at 12 bits, 1998x1080 — which
Resolve identifies as `JPEG 2000 / MXF OP1A / 12 bit`, the same decode path a
DCP video track file takes. The render target is ProRes in QuickTime, because
**this Resolve offers ProRes in no MXF flavour** — `GetRenderCodecs` returns
ProRes only under `mov`, so "MXF to ProRes" means J2K-MXF in, ProRes-QuickTime
out.

What it is actually looking for:

  - **Crashes at end of write.** Each iteration is bracketed by a snapshot of
    `crash_archive.txt`, so a new crash block is captured with its stack rather
    than being noticed later as "it died at some point".
  - **Process death.** The driver runs outside Resolve and watches the PID, so a
    hard exit is recorded as a result instead of hanging the run.
  - **Leaks.** Resident memory is sampled through every render, so growth across
    iterations is visible. A teardown bug and a slow leak both present as "it
    crashes eventually"; the RSS curve separates them.
  - **Degradation.** Per-iteration wall time is recorded for the same reason.

Outputs are deleted after each iteration is verified unless `--keep`, because
ProRes 422 HQ at this resolution is roughly 2 GB per minute.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import resolve_runtime as rr  # noqa: E402
from src.utils.project_cleanup import save_project_if_safe  # noqa: E402

CRASH_ARCHIVE = Path(
    os.path.expanduser(
        "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/crash_archive.txt"
    )
)
RESOLVE_LOG = Path(
    os.path.expanduser(
        "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/logs/ResolveDebug.txt"
    )
)

DEFAULT_API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"


# ── connection ───────────────────────────────────────────────────────────────


def connect(timeout: float = 420.0) -> Optional[Any]:
    """Wait for a scriptable Resolve.

    The timeout is generous on purpose. A clean headless boot is scriptable in
    under 3 seconds, but a boot *after an unclean shutdown* took 2 minutes 5
    seconds to start its script server — measured, after force-killing a wedged
    instance. A 90-second wait concluded "headless will not start" fifteen
    seconds before it did, which is exactly the false negative that leads a
    supervisor to launch a second instance on top of a starting one.
    """
    os.environ.pop("DAVINCI_RESOLVE_BRIDGE", None)
    api = os.environ.get("RESOLVE_SCRIPT_API", DEFAULT_API)
    modules = str(Path(api) / "Modules")
    if modules not in sys.path:
        sys.path.append(modules)
    os.environ.setdefault("RESOLVE_SCRIPT_API", api)
    os.environ.setdefault(
        "RESOLVE_SCRIPT_LIB",
        "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
    )
    import DaVinciResolveScript as dvr

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resolve = dvr.scriptapp("Resolve")
        if resolve is not None:
            try:
                pm = resolve.GetProjectManager()
                if pm is not None and pm.GetProjectListInCurrentFolder() is not None:
                    return resolve
            except Exception:
                pass
        time.sleep(1.0)
    return None


def resolve_pid() -> Optional[int]:
    try:
        out = subprocess.run(["ps", "-Ao", "pid=,command="], capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines():
            if any(p in line for p in rr.RESOLVE_PROCESS_PATTERNS):
                return int(line.split()[0])
    except Exception:
        pass
    return None


def rss_mb(pid: Optional[int]) -> Optional[float]:
    if pid is None:
        return None
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
        return round(int(out.stdout.strip()) / 1024, 1)
    except Exception:
        return None


# ── crash capture ────────────────────────────────────────────────────────────


class CrashWatch:
    """Bracket an operation and capture whatever Resolve appended to its archive.

    Resolve appends every crash stack to one growing file with no timestamps, so
    "did this iteration crash" is only answerable by remembering where the file
    ended before it started. Reading the file afterwards and looking for
    something that seems recent is guesswork.
    """

    def __init__(self) -> None:
        self.offset = self._size()

    @staticmethod
    def _size() -> int:
        try:
            return CRASH_ARCHIVE.stat().st_size
        except OSError:
            return 0

    def take(self) -> Optional[str]:
        """New crash text since the last call, or None."""
        size = self._size()
        if size <= self.offset:
            self.offset = size  # rotation/truncation resets the mark
            return None
        try:
            with CRASH_ARCHIVE.open("r", errors="replace", encoding="utf-8") as handle:
                handle.seek(self.offset)
                text = handle.read()
        except OSError:
            return None
        self.offset = size
        return text or None


def log_tail(lines: int = 80) -> str:
    try:
        content = RESOLVE_LOG.read_text(errors="replace", encoding="utf-8").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


# ── source media ─────────────────────────────────────────────────────────────


def build_j2k_source(work: Path, seconds: int, width: int, height: int, fps: int) -> Path:
    """DCP-like JPEG 2000 in MXF OP1A, 12-bit.

    Kept short and repeated on the timeline rather than generated at full length:
    the decode work per frame is identical either way, and a 5-minute J2K source
    is several gigabytes of scratch for no extra signal.
    """
    out = work / "j2k_source.mxf"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}:duration={seconds}",
            "-c:v", "jpeg2000", "-pix_fmt", "xyz12le", "-q:v", "1",
            "-f", "mxf", str(out), "-y",
        ],
        check=True, timeout=900,
    )
    return out


# ── the run ──────────────────────────────────────────────────────────────────


class StressRun:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.work = Path(tempfile.mkdtemp(prefix="render_stress_"))
        self.out_dir = Path(args.out) if args.out else (self.work / "renders")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.project_name = f"RENDER_STRESS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.crash = CrashWatch()
        self.iterations: List[Dict[str, Any]] = []
        self.resolve: Any = None
        self.pid: Optional[int] = None
        self.source: Optional[Path] = None
        self.incumbent: Optional[str] = None

    # -- setup ---------------------------------------------------------------

    def attach(self) -> bool:
        self.resolve = connect()
        self.pid = resolve_pid()
        return self.resolve is not None

    def build_project(self) -> Dict[str, Any]:
        pm = self.resolve.GetProjectManager()
        incumbent = pm.GetCurrentProject()
        self.incumbent = incumbent.GetName() if incumbent else None
        # Guarded: SaveProject BLOCKS FOREVER headless on the never-saved
        # 'Untitled Project', which is exactly the project a fresh headless
        # boot is sitting on. This call hung two stress runs before it was
        # traced.
        save_project_if_safe(pm)
        if not pm.CreateProject(self.project_name):
            raise RuntimeError(f"could not create {self.project_name}")
        pm.LoadProject(self.project_name)
        project = pm.GetCurrentProject()

        if self.args.source:
            self.source = Path(self.args.source).expanduser()
            if not self.source.exists():
                raise RuntimeError(f"--source not found: {self.source}")
        else:
            self.source = build_j2k_source(
                self.work, self.args.clip_seconds, self.args.width, self.args.height, self.args.fps
            )

        storage = self.resolve.GetMediaStorage()
        clips = storage.AddItemListToMediaPool([str(self.source)]) or []
        if not clips:
            raise RuntimeError(f"Resolve would not import {self.source}")
        clip = clips[0]
        pool = project.GetMediaPool()

        # Repeat the clip until the timeline reaches the requested duration. The
        # decode path is per-frame, so N copies of a short clip stresses it the
        # same as one long clip while keeping the scratch bounded.
        #
        # NOT via CreateTimelineFromClips([clip] * n): that call **deduplicates
        # repeated references to the same MediaPoolItem**. Passing one clip 15
        # times built a 96-frame timeline — one copy — and reported no error, so
        # every "60 second" render in the first run was actually 4 seconds. The
        # harness looked like it was working and was testing almost nothing.
        # AppendToTimeline with explicit clipInfo dicts appends each instance.
        frames = int(clip.GetClipProperty("Frames") or 0)
        fps = float(clip.GetClipProperty("FPS") or self.args.fps)
        want = max(1, int(round(self.args.duration * fps / max(frames, 1))))
        timeline = pool.CreateEmptyTimeline("STRESS_TL")
        if timeline is None:
            raise RuntimeError("could not create the stress timeline")
        project.SetCurrentTimeline(timeline)
        # endFrame is EXCLUSIVE-adjacent in this API: the last frame index is
        # frames - 1, and passing `frames` appends nothing.
        appended = pool.AppendToTimeline(
            [{"mediaPoolItem": clip, "startFrame": 0, "endFrame": max(frames - 1, 0)}] * want
        )
        if not appended:
            raise RuntimeError("AppendToTimeline appended nothing")
        built = timeline.GetEndFrame() - timeline.GetStartFrame()
        # Assert the timeline is the length that was asked for. The whole failure
        # above was a silent short-build that no check would have caught.
        if built < want * max(frames - 1, 1) * 0.9:
            raise RuntimeError(
                f"timeline short-built: wanted ~{want * frames} frames, got {built}"
            )

        codecs = project.GetRenderCodecs(self.args.format) or {}
        # GetRenderCodecs returns {description: id} and rejects the description.
        codec_id = codecs.get(self.args.codec) or self.args.codec
        if codec_id not in codecs.values():
            raise RuntimeError(
                f"codec {self.args.codec!r} not offered for format {self.args.format!r}. "
                f"Available: {sorted(codecs)}"
            )
        if not project.SetCurrentRenderFormatAndCodec(self.args.format, codec_id):
            raise RuntimeError(f"SetCurrentRenderFormatAndCodec({self.args.format}, {codec_id}) refused")

        return {
            "project": self.project_name,
            "source": str(self.source),
            "source_codec": clip.GetClipProperty("Video Codec"),
            "source_format": clip.GetClipProperty("Format"),
            "source_resolution": clip.GetClipProperty("Resolution"),
            "clips_on_timeline": want,
            "timeline_frames": timeline.GetEndFrame() - timeline.GetStartFrame(),
            "render_format": self.args.format,
            "render_codec": codec_id,
        }

    # -- one iteration -------------------------------------------------------

    def render_once(self, index: int) -> Dict[str, Any]:
        record: Dict[str, Any] = {"iteration": index}
        project = self.resolve.GetProjectManager().GetCurrentProject()
        name = f"stress_{index:03d}"
        project.SetRenderSettings({
            "TargetDir": str(self.out_dir),
            "CustomName": name,
            "SelectAllFrames": True,
        })
        job = project.AddRenderJob()
        record["job"] = bool(job)
        if not job:
            record["outcome"] = "add_render_job_failed"
            return record

        started = time.monotonic()
        record["start_rendering"] = project.StartRendering(job, isInteractiveMode=False)
        peak = 0.0
        samples = 0
        deadline = started + self.args.timeout
        died = False
        while time.monotonic() < deadline:
            current = rss_mb(self.pid)
            if current is None:
                died = True
                break
            peak = max(peak, current)
            samples += 1
            try:
                if not project.IsRenderingInProgress():
                    break
            except Exception:
                # A dead Resolve makes the handle raise rather than answer. That
                # is the crash, not an error in the harness.
                died = True
                break
            time.sleep(1.0)

        record["elapsed_seconds"] = round(time.monotonic() - started, 1)
        record["peak_rss_mb"] = peak or None
        record["rss_samples"] = samples
        produced = sorted(p for p in self.out_dir.glob(f"{name}*") if p.is_file())
        record["output_files"] = [p.name for p in produced]
        record["output_bytes"] = sum(p.stat().st_size for p in produced)

        if died or resolve_pid() != self.pid:
            record["outcome"] = "resolve_died"
        else:
            try:
                status = project.GetRenderJobStatus(job) or {}
                record["job_status"] = status.get("JobStatus")
                record["outcome"] = "complete" if status.get("JobStatus") == "Complete" else "incomplete"
                project.DeleteRenderJob(job)
            except Exception as exc:
                record["outcome"] = "resolve_died"
                record["exception"] = f"{type(exc).__name__}: {exc}"

        crash = self.crash.take()
        if crash:
            # The whole point of the harness: a stack, attached to the iteration
            # that produced it, rather than a file someone reads tomorrow.
            record["crash_captured"] = True
            record["crash_text"] = crash[-6000:]
            record["log_tail"] = log_tail()
        if not self.args.keep:
            for path in produced:
                path.unlink(missing_ok=True)
        return record

    # -- recovery ------------------------------------------------------------

    def recover(self) -> bool:
        """Bring Resolve back after a death, so the run continues past the first one.

        Stopping at the first crash would answer "does it crash" and nothing
        else. Whether it crashes on iteration 2 or iteration 40, and whether the
        RSS was climbing first, are the parts that point at a cause.
        """
        if not self.args.restart_on_crash:
            return False
        headless = self.args.mode == "headless"
        command = rr.launch_command(headless=headless)
        if command is None:
            return False
        subprocess.Popen(command, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not self.attach():
            return False
        pm = self.resolve.GetProjectManager()
        pm.LoadProject(self.project_name)
        return pm.GetCurrentProject() is not None

    # -- teardown ------------------------------------------------------------

    def teardown(self) -> Dict[str, Any]:
        """Hand the session back on a *named* project, never on the fallback.

        Closing the stress project drops Resolve onto a fresh, never-saved
        `Untitled Project`, which cannot be saved — so the next close or switch
        raises a modal a human has to clear. This harness did exactly that to a
        live GUI session: it finished cleanly and left the application prompting
        with no way to cancel.

        Loading the incumbent first closes the stress project silently (it was
        just saved) and never rests on the fallback. Delete afterwards.
        """
        notes: Dict[str, Any] = {}
        try:
            pm = self.resolve.GetProjectManager()
            save_project_if_safe(pm)
            # Order matters, and both steps are load-bearing:
            #   1. CloseProject releases the session's lock. Switching away with
            #      LoadProject does NOT — measured: DeleteProject then returns
            #      False forever, and retrying never helps. After a CloseProject
            #      the same delete succeeds on the first attempt.
            #   2. LoadProject(incumbent) immediately afterwards, so the session
            #      does not rest on the never-saved `Untitled Project` fallback
            #      that CloseProject drops it onto — that fallback cannot be
            #      saved, so the next close or switch raises a modal a human has
            #      to clear. This harness did that to a live GUI session.
            notes["closed"] = bool(pm.CloseProject(pm.GetCurrentProject()))
            if self.incumbent and self.incumbent != self.project_name:
                notes["restored_incumbent"] = bool(pm.LoadProject(self.incumbent))
            notes["deleted"] = bool(pm.DeleteProject(self.project_name))
        except Exception as exc:
            notes["teardown_error"] = repr(exc)
        shutil.rmtree(self.work, ignore_errors=True)
        return notes


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode", choices=("headless", "gui", "current"), default="current",
                        help="which session to stress; 'current' uses whatever is running")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--duration", type=int, default=60, help="timeline length in seconds")
    parser.add_argument("--clip-seconds", type=int, default=4, help="length of the generated source clip")
    parser.add_argument("--width", type=int, default=1998)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--format", default="mov")
    parser.add_argument("--codec", default="Apple ProRes 422 HQ")
    parser.add_argument("--source", help="use real media instead of the synthetic J2K MXF")
    parser.add_argument("--out", help="render output directory (default: temp, deleted after)")
    parser.add_argument("--keep", action="store_true", help="keep rendered files")
    parser.add_argument("--timeout", type=float, default=3600, help="per-render timeout in seconds")
    parser.add_argument("--restart-on-crash", action="store_true",
                        help="relaunch Resolve and keep going after a death")
    parser.add_argument("--report", type=Path, help="write the JSON report here")
    args = parser.parse_args()

    mode = rr.runtime_mode()
    if args.mode != "current":
        want_headless = args.mode == "headless"
        if mode["running"] and bool(mode["headless"]) != want_headless:
            print(f"REFUSE: a Resolve is already running in the other mode: {mode['command_lines']}",
                  file=sys.stderr)
            return 1
        if not mode["running"]:
            command = rr.launch_command(headless=want_headless)
            if command is None:
                print("REFUSE: no Resolve install found.", file=sys.stderr)
                return 3
            print(f"starting: {' '.join(command)}")
            subprocess.Popen(command, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    run = StressRun(args)
    if not run.attach():
        print("REFUSE: no Resolve answered the scripting API.", file=sys.stderr)
        return 4

    observed = rr.runtime_mode()
    print(f"stressing: headless={observed['headless']} pid={run.pid}", flush=True)
    setup = run.build_project()
    print(json.dumps(setup, indent=2), flush=True)

    for index in range(1, args.iterations + 1):
        record = run.render_once(index)
        run.iterations.append(record)
        flag = " CRASH" if record.get("crash_captured") else ""
        print(f"  [{index:3d}/{args.iterations}] {record.get('outcome'):16} "
              f"{record.get('elapsed_seconds')}s  peak_rss={record.get('peak_rss_mb')}MB  "
              f"bytes={record.get('output_bytes')}{flag}", flush=True)
        if record["outcome"] == "resolve_died":
            if not run.recover():
                print("  Resolve died and was not recovered; stopping.")
                break
            print("  recovered; continuing", flush=True)

    report = {
        "metadata": {
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "headless": observed["headless"],
            "iterations_requested": args.iterations,
            "duration_seconds": args.duration,
            "format": args.format,
            "codec": args.codec,
        },
        "setup": setup,
        "iterations": run.iterations,
        "teardown": run.teardown(),
    }
    deaths = [i for i in run.iterations if i.get("outcome") == "resolve_died"]
    crashes = [i for i in run.iterations if i.get("crash_captured")]
    report["summary"] = {
        "completed": sum(1 for i in run.iterations if i.get("outcome") == "complete"),
        "deaths": len(deaths),
        "crash_blocks_captured": len(crashes),
        "first_death_iteration": deaths[0]["iteration"] if deaths else None,
        "peak_rss_mb": max((i.get("peak_rss_mb") or 0) for i in run.iterations) if run.iterations else None,
        "rss_first_to_last": [
            run.iterations[0].get("peak_rss_mb") if run.iterations else None,
            run.iterations[-1].get("peak_rss_mb") if run.iterations else None,
        ],
    }
    print(json.dumps(report["summary"], indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
