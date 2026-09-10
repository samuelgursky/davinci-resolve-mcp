"""Read-only MCP smoke against the open Resolve timeline.

Run from the repository root:
    venv/Scripts/python.exe tests/live_film_cues_validation.py

Does not create projects, markers, media, renders or output files.
"""
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def payload(result):
    assert not result.isError, result
    if result.structuredContent:
        return result.structuredContent
    return json.loads(next(c.text for c in result.content if c.type == "text"))


async def main():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, DAVINCI_RESOLVE_MCP_UPDATE_CHECK="0")
    params = StdioServerParameters(command=sys.executable,
                                  args=[str(root / "src/server.py")], env=env, cwd=str(root))
    async with asyncio.timeout(45):
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                inventory = await session.list_tools()
                marker_tool = next(t for t in inventory.tools if t.name == "timeline_markers")
                assert "export_cue_sheet" in marker_tool.description
                before = payload(await session.call_tool("timeline_markers", {"action": "get_all"}))
                playhead = payload(await session.call_tool("timeline_markers", {"action": "get_current_timecode"}))
                sheet = payload(await session.call_tool("timeline_markers", {"action": "export_cue_sheet"}))
                assert sheet.get("schema") == "film-cues/v1", sheet
                assert len(sheet["cues"]) == len(before["markers"])
                rate = sheet["frame_rate"]
                for cue in sheet["cues"]:
                    assert cue["start_seconds"] == cue["start_frame"] * rate["denominator"] / rate["numerator"]
                after = payload(await session.call_tool("timeline_markers", {"action": "get_all"}))
                after_playhead = payload(await session.call_tool("timeline_markers", {"action": "get_current_timecode"}))
                assert before["markers"] == after["markers"], "Markers changed during read-only probe"
                assert playhead["timecode"] == after_playhead["timecode"], "Playhead changed during probe"
                print(json.dumps({"status": "passed", "transport": "MCP stdio",
                                  "timeline": sheet["timeline"], "frame_rate": rate,
                                  "cue_count": len(sheet["cues"]), "markers_and_playhead_unchanged": True}))


if __name__ == "__main__":
    asyncio.run(main())
