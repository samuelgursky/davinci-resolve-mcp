"""Read-only Resolve MCP -> Ableton MCP film-cue handoff.

Run from the Resolve repo with its Python, passing the Ableton source checkout.
Requires both apps and the updated Ableton project handler; never inserts cues.
"""
import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from live_film_cues_validation import payload


async def run(ableton_root, bpm):
    resolve_root = Path(__file__).resolve().parents[1]
    ableton_python = ableton_root / ".venv/Scripts/python.exe"
    if not ableton_python.is_file():
        ableton_python = ableton_root / ".venv/bin/python"
    assert ableton_python.is_file(), "Ableton virtualenv interpreter not found"
    specifications = [
        StdioServerParameters(command=sys.executable, args=[str(resolve_root / "src/server.py")],
                              cwd=str(resolve_root), env=dict(os.environ, DAVINCI_RESOLVE_MCP_UPDATE_CHECK="0")),
        StdioServerParameters(command=str(ableton_python), args=["-m", "ableton_mcp"], cwd=str(ableton_root)),
    ]
    async with asyncio.timeout(60), AsyncExitStack() as stack:
        sessions = []
        for spec in specifications:
            streams = await stack.enter_async_context(stdio_client(spec))
            session = await stack.enter_async_context(ClientSession(*streams))
            await session.initialize()
            sessions.append(session)
        resolve, ableton = sessions
        before = payload(await resolve.call_tool("timeline_markers", {"action": "get_all"}))
        sheet = payload(await resolve.call_tool("timeline_markers", {"action": "export_cue_sheet"}))
        assert sheet.get("schema") == "film-cues/v1", sheet
        args = {"cue_sheet": sheet, "tempo_bpm": bpm,
                "arrangement_start_beats": 0, "cue_namespace": "jim-ch5-preview"}
        planned = payload(await ableton.call_tool("film_cues_plan", args))
        assert planned.get("status") == "ok", (planned.get("status"), planned.get("error"))
        plan = planned["plan"]
        assert len(plan["cues"]) == len(sheet["cues"])
        for source, cue in zip(sheet["cues"], plan["cues"]):
            assert source["id"] == cue["id"] and source["custom_data"] == cue["custom_data"]
            assert abs(cue["start_beats"] - source["start_seconds"] * bpm / 60) < 1e-9
        preview = payload(await ableton.call_tool("film_cues_import", {**args, "preview": True}))
        assert preview.get("status") in ("preview", "conflict"), (preview.get("status"), preview.get("error"))
        assert preview["added"] == [] and preview["transport_restored"] is True
        assert preview["transport_before"] == preview["transport_after"]
        after = payload(await resolve.call_tool("timeline_markers", {"action": "get_all"}))
        assert before["markers"] == after["markers"]
        print(json.dumps({"status": "passed", "transport": "two real MCP stdio servers",
                          "timeline": sheet["timeline"]["name"], "cue_count": len(plan["cues"]),
                          "explicit_assumed_bpm": bpm, "preview_status": preview["status"],
                          "would_add": len(preview["would_add"]), "conflicts": len(preview["conflicts"]),
                          "writes": 0, "tempo_automation_verified": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ableton-repo", type=Path, required=True)
    parser.add_argument("--tempo-bpm", type=float, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.ableton_repo.resolve(), args.tempo_bpm))
