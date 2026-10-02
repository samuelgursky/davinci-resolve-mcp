"""Opt-in Windows Studio subtitle DB -> reopen -> burn-in pixel validation.

Uses synthetic speech/black video, a disposable project, and an existing saved
Word Highlight reference. Saves/restores the original project and restarts
Resolve once. Leaves the QA project/media/report for inspection. No user source
media is read or modified. Run only with explicit acceptance of the restart:

  python tests/live_subtitle_roundtrip.py --reference-project Reference \
    --reference-timeline Reel --accept-restart
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        detail = result.stderr.decode(errors="replace") if isinstance(result.stderr, bytes) else result.stderr
        raise RuntimeError(f"{command[0]} exited {result.returncode}: {detail}")
    return result


def node_action(action, args):
    module = (ROOT / "resolve-advanced/server/tools/project_db.mjs").as_uri()
    script = (f"import {{ projectDbTool }} from {json.dumps(module)};"
              "let s='';for await(const c of process.stdin)s+=c;"
              "console.log(JSON.stringify(await projectDbTool.handler(JSON.parse(s))));")
    result = run(["node", "--input-type=module", "-e", script],
                 input=json.dumps({"action": action, "args": args}), text=True, cwd=ROOT)
    return json.loads(result.stdout)


def synthesize(folder):
    script = folder / "speech.ps1"
    script.write_text('''param([string]$Output)
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$english = $speaker.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'en-*' } | Select-Object -First 1
if (-not $english) { throw 'An English Windows speech voice is required.' }
$speaker.SelectVoice($english.VoiceInfo.Name)
$speaker.Rate = -1
$speaker.SetOutputToWaveFile($Output)
$speaker.Speak('Welcome to the subtitle test. Each word should stay visible. The highlight follows the voice. We can change the colors. We can also correct the text. These captions use a clean outline. This final sentence completes the test.')
$speaker.Dispose()
''', encoding="utf-8")
    wav = folder / "synthetic-speech.wav"
    run(["powershell.exe", "-NoProfile", "-File", str(script), str(wav)])
    duration = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(wav)], text=True).stdout)
    video = folder / "synthetic-black-speech.mp4"
    run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         f"color=c=black:s=1080x1920:r=30:d={math.ceil(duration) + 1}", "-i", str(wav),
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(video)])
    return video


def wait_for(connect, seconds=150):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = connect()
            if value:
                return value
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError("Resolve did not become ready")


def launch_resolve():
    executable = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Blackmagic Design/DaVinci Resolve/Resolve.exe"
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    subprocess.Popen([str(executable)], startupinfo=startup)


def resolve_is_running():
    output = run(["tasklist.exe", "/FO", "CSV", "/NH"], text=True).stdout
    return any(line.lower().startswith('"resolve.exe",') for line in output.splitlines())


def validate_pixels(video, captions, timeline_start):
    # Synthetic source is entirely black. Every caption frame must contain
    # bright caption pixels; green highlights and clear edges are measured too.
    command = ["ffmpeg", "-v", "error", "-i", str(video), "-vf", "scale=270:480",
               "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    size = 270 * 480 * 3
    frame = 0
    checked = 0
    blank = []
    clipped = []
    no_highlight = []
    try:
        while True:
            data = proc.stdout.read(size)
            if not data:
                break
            if len(data) != size:
                raise RuntimeError("truncated decoded render frame")
            absolute = timeline_start + frame
            cue = next((c for c in captions if c["start"] <= absolute < c["end"]), None)
            if cue:
                checked += 1
                bright = 0
                green = 0
                edge = False
                for i in range(0, size, 3):
                    red, g, blue = data[i:i + 3]
                    if max(red, g, blue) > 100:
                        bright += 1
                        x, y = (i // 3) % 270, (i // 3) // 270
                        edge |= x < 3 or x >= 267 or y < 3 or y >= 477
                    if g > 140 and g > red + 60 and g > blue + 60:
                        green += 1
                if bright < 5:
                    blank.append(frame)
                if green < 2:
                    no_highlight.append(frame)
                if edge:
                    clipped.append(frame)
            frame += 1
        error = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(error)
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.stdout.close()
        proc.stderr.close()
    expected = sum(c["end"] - c["start"] for c in captions)
    return {"decoded_frames": frame, "caption_frames_checked": checked, "expected_caption_frames": expected,
            "blank_frames": blank, "no_green_highlight_frames": no_highlight, "edge_frames": clipped,
            "passed": checked == expected and checked > 0 and not blank and not clipped and not no_highlight}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-project", required=True)
    parser.add_argument("--reference-timeline", required=True)
    parser.add_argument("--accept-restart", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32" or not args.accept_restart:
        parser.error("This Windows harness requires --accept-restart (saves the current project and restarts Resolve).")
    os.environ["RESOLVE_VERIFY"] = "1"
    sys.path.insert(0, str(Path(os.environ["PROGRAMDATA"]) / "Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting/Modules"))
    import DaVinciResolveScript as dvr
    from src.server import _resolve_safe_dir, _normalize_auto_caption_settings

    token = uuid.uuid4().hex[:8]
    folder = Path(_resolve_safe_dir(str(ROOT / "tmp" / f"subtitle-qa-{token}")))
    folder.mkdir(parents=True, exist_ok=False)
    report = {"project": f"MCP_SUBTITLE_QA_{token}", "output": str(folder), "passed": False}
    r = dvr.scriptapp("Resolve")
    if not r:
        raise RuntimeError("Open Resolve Studio before starting this harness")
    pm = r.GetProjectManager()
    original = pm.GetCurrentProject()
    original_name = original.GetName() if original else None
    original_timeline = original.GetCurrentTimeline().GetName() if original and original.GetCurrentTimeline() else None
    restarted = False
    try:
        if original and original.IsRenderingInProgress():
            raise RuntimeError("A render is running; refusing to switch projects")
        reference = node_action("list_subtitle_presets", {"projectName": args.reference_project, "timeline": args.reference_timeline})
        if not reference["presets"] or not reference["presets"][0]["preset"]:
            raise RuntimeError("Reference must have a saved Word Highlight preset on subtitle track 1")
        media = synthesize(folder)
        if original and not pm.SaveProject():
            raise RuntimeError("Could not save original project; refusing to switch")
        project = pm.CreateProject(report["project"])
        if not project:
            raise RuntimeError("Could not create disposable project")
        for key, value in {"timelineFrameRate": "30", "timelineResolutionWidth": "1080", "timelineResolutionHeight": "1920"}.items():
            if not project.SetSetting(key, value):
                raise RuntimeError(f"Could not set {key}")
        pool = project.GetMediaPool()
        clips = pool.ImportMedia([str(media)])
        if not clips:
            raise RuntimeError("Synthetic-media import failed")
        timeline = pool.CreateTimelineFromClips("Subtitle QA", clips)
        if not timeline:
            raise RuntimeError("Could not create timeline")
        settings, ignored = _normalize_auto_caption_settings({"language": "english", "chars_per_line": 16, "line_break": "single", "gap": 0}, r)
        print("Generating captions from synthetic speech", flush=True)
        timeline.CreateSubtitlesFromAudio(settings)
        wait_for(lambda: len(timeline.GetItemListInTrack("subtitle", 1) or []) >= 4)
        if not pm.SaveProject():
            raise RuntimeError("Could not save QA project")
        selector = {"projectName": report["project"], "timeline": "Subtitle QA"}
        before = node_action("list_captions", selector)
        report["version"] = r.GetVersionString()
        report["generated_caption_count"] = len(before["captions"])
        report["ignored_generation_settings"] = ignored
        replacements = []
        for i, c in enumerate(before["captions"][:-1]):
            text = ["Hello there", "Bright words"][i] if i < 2 else c["text"]
            words = text.split()
            duration = c["end"] - c["start"]
            replacements.append({"id": c["id"], "text": " ".join(words), "start": c["start"], "end": c["end"],
                "words": [{"text": w, "start": c["start"] + round(j * duration / len(words)),
                           "end": c["start"] + round((j + 1) * duration / len(words))} for j, w in enumerate(words)]})
        deleted = before["captions"][-1]
        added = {"text": "Added caption", "start": deleted["start"], "end": deleted["end"], "words": [
            {"text": "Added", "start": deleted["start"], "end": (deleted["start"] + deleted["end"]) // 2},
            {"text": "caption", "start": (deleted["start"] + deleted["end"]) // 2, "end": deleted["end"]}]}
        edits = {**selector, "replace": replacements, "delete": [deleted["id"]], "add": [added]}
        (folder / "caption-edits.json").write_text(json.dumps(edits, indent=2), encoding="utf-8")
        node_action("write_captions", {**edits, "dryRun": True})
        print("Saving and quitting Resolve for the offline transaction", flush=True)
        r.Quit()
        wait_for(lambda: not resolve_is_running(), seconds=60)
        restarted = True
        r = None
        controls = {"size": 0.055, "position": [0.5, 0.3], "textRed": 1, "textGreen": 1, "textBlue": 1,
                    "highlightRed": 0, "highlightGreen": 1, "highlightBlue": 0,
                    "outlineEnabled": 1, "outlineRed": 0, "outlineGreen": 0, "outlineBlue": 0, "thickness": 0.03}
        report["preset"] = node_action("copy_subtitle_preset", {**selector, "sourceProject": args.reference_project,
            "sourceTimeline": args.reference_timeline, "inputs": controls, "iConfirmProjectClosed": True})
        written = node_action("write_captions", {**edits, "iConfirmProjectClosed": True})
        report["caption_backup"] = written["backup"]
        report["caption_check"] = written["check"]
        print("Reopening Resolve and rendering the disposable QA project", flush=True)
        launch_resolve()
        r = wait_for(lambda: dvr.scriptapp("Resolve"))
        pm = r.GetProjectManager()
        project = wait_for(lambda: pm.LoadProject(report["project"]))
        timeline = project.GetCurrentTimeline()
        timeline.SetTrackEnable("subtitle", 1, True)
        names = [i.GetName().strip() for i in timeline.GetItemListInTrack("subtitle", 1)]
        report["live_text_readback"] = names[:2] == ["Hello there", "Bright words"] and names[-1] == "Added caption"
        if not project.SetCurrentRenderFormatAndCodec("mp4", "H264"):
            raise RuntimeError("H264/MP4 render format unavailable")
        if not project.SetRenderSettings({"TargetDir": str(folder), "CustomName": "subtitle-roundtrip", "SelectAllFrames": True,
            "ExportVideo": True, "ExportAudio": True, "FormatWidth": 1080, "FormatHeight": 1920,
            "ExportSubtitle": True, "SubtitleFormat": "BurnIn"}):
            raise RuntimeError("Render settings were rejected")
        job = project.AddRenderJob()
        if not job or not project.StartRendering([job]):
            raise RuntimeError("Render did not start")
        wait_for(lambda: not project.IsRenderingInProgress(), seconds=300)
        report["render_status"] = project.GetRenderJobStatus(job)
        rendered = folder / "subtitle-roundtrip.mp4"
        if not rendered.exists():
            raise RuntimeError(f"Render output missing: {report['render_status']}")
        report["render"] = str(rendered)
        report["pixels"] = validate_pixels(rendered, written["captions"], int(timeline.GetStartFrame()))
        pm.SaveProject()
        persisted = node_action("list_captions", selector)
        report["persisted_text"] = [c["text"] for c in persisted["captions"]] == [c["text"] for c in written["captions"]]
        report["passed"] = report["pixels"]["passed"] and report["live_text_readback"] and report["persisted_text"]
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        try:
            if restarted and not resolve_is_running():
                launch_resolve()
                r = wait_for(lambda: dvr.scriptapp("Resolve"))
            if r and original_name:
                restored = r.GetProjectManager().LoadProject(original_name)
                if restored and original_timeline:
                    for i in range(1, restored.GetTimelineCount() + 1):
                        t = restored.GetTimelineByIndex(i)
                        if t.GetName() == original_timeline:
                            restored.SetCurrentTimeline(t)
                            break
                report["original_project_restored"] = bool(restored)
        except Exception:
            report["restore_error"] = traceback.format_exc()
        (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
