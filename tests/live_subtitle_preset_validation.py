"""Synthetic-only live acceptance. Keeps Studio running and restores UI context.

Run with the repository Python environment. Requires an already open MCP_QA_*
project and a subtitle timeline carrying Word Highlight. Never launches Resolve.
"""
import json
import re
import sys
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.utils.platform import setup_environment
from src.utils.qa_privacy import anonymize_host_paths


def main():
    # The Windows terminal codepage cannot encode the server's migration logs.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    setup_environment()
    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Existing Resolve session unavailable; no launch attempted")
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project or not project.GetName().startswith("MCP_QA_"):
        raise RuntimeError("This acceptance requires a disposable MCP_QA_* project")
    original = project.GetCurrentTimeline()
    page, tc = resolve.GetCurrentPage(), original.GetCurrentTimecode()
    folder = ROOT / "logs" / f"subtitle-acceptance-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True)
    report = {"resolve": resolve.GetVersionString(), "project": project.GetName(), "frames": []}
    from src import server
    # Pin the existing native handle; even a failed transport never launches.
    server.resolve = resolve
    server._launch_resolve = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Launch forbidden"))
    try:
        exported = folder / "native.drt"
        assert original.Export(str(exported), resolve.EXPORT_DRT)
        bare = folder / "without-preset.drt"
        with zipfile.ZipFile(exported) as source, zipfile.ZipFile(bare, "w", zipfile.ZIP_DEFLATED) as target:
            for name in source.namelist():
                data = source.read(name)
                if name.startswith("SeqContainer/") and name.endswith(".xml"):
                    xml = data.decode("utf-8")
                    xml, count = re.subn(r"<FusionCompHolderItems>[\s\S]*?</FusionCompHolderItems>",
                                         "<FusionCompHolderItems/>", xml)
                    assert count == 1, "Acceptance expects one animated subtitle track"
                    data = xml.encode("utf-8")
                target.writestr(name, data)
        timeline = project.GetMediaPool().ImportTimelineFromFile(str(bare), {"importSourceClips": False})
        assert timeline and timeline.GetTrackCount("subtitle") == original.GetTrackCount("subtitle")
        assert project.SetCurrentTimeline(timeline)
        # Exercise the public dispatcher, native preset creation and readback.
        result = server.timeline_ai("set_subtitle_preset", {
            "preset": "Word Highlight", "inputs": {"textRed": 1, "textGreen": 1, "textBlue": 1,
                                                       "highlightRed": 1, "highlightGreen": 0, "highlightBlue": 1},
            "revision_name": f"MCP Subtitle Acceptance {uuid.uuid4().hex[:8]}",
        })
        report["action"] = result
        if not result.get("success"):
            raise RuntimeError(json.dumps(result, default=str))
        revised = project.GetCurrentTimeline()
        # Representative word phases plus one caption-free gap. The image path
        # is native Resolve output, never a thumbnail or source derivative.
        for frame in (108200, 108220, 108180):
            image = server.timeline_frame("capture", {"frame": frame, "format": "png", "quality": "frame"})
            if isinstance(image, dict) or isinstance(image, list):
                raise RuntimeError(f"Capture/restore failed: {image}")
            path = folder / f"frame-{frame}.png"
            path.write_bytes(image.data)
            report["frames"].append(str(path))
        assert project.GetCurrentTimeline().GetUniqueId() == revised.GetUniqueId()
        report["success"] = True
        print(json.dumps(anonymize_host_paths(report), indent=2, default=str))
    finally:
        assert project.SetCurrentTimeline(original)
        original.SetCurrentTimecode(tc)
        resolve.OpenPage(page)
        (folder / "report.json").write_text(json.dumps(anonymize_host_paths(report), indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
