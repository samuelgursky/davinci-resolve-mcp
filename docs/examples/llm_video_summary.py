#!/usr/bin/env python
"""
Example: Video Project Summary with LLM

This script connects to the DaVinci Resolve MCP server and uses an LLM
to generate a summary of the video project.
"""
import os
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))
from src.mcp_client_example import MCPClient

# You would normally use an actual LLM API here
class MockLLM:
    """Mock LLM client for demonstration purposes."""
    
    async def analyze_project(self, project_data: Dict[str, Any]) -> str:
        """
        Analyze project data and return a summary.
        
        In a real implementation, this would call Claude, GPT-4, or another LLM.
        """
        # In a real implementation, this would send the data to an LLM API
        project_name = project_data.get("name", "Unknown Project")
        fps = project_data.get("fps", "Unknown")
        resolution = project_data.get("resolution", {})
        width = resolution.get("width", "Unknown")
        height = resolution.get("height", "Unknown")
        timelines = project_data.get("timelines", [])
        timeline_count = len(timelines)
        current_timeline = project_data.get("current_timeline", "None")
        
        summary = f"""
Project Summary: {project_name}
====================
Resolution: {width}x{height}
Frame Rate: {fps} fps
Number of Timelines: {timeline_count}
Currently Active Timeline: {current_timeline}

This project appears to be a {self._guess_project_type(project_name)} project.
It uses a {'high' if int(width) >= 1920 else 'standard'} resolution format.

Recommendations:
- Consider organizing media into bins for better management
- Check if the frame rate is consistent across all imported media
- Review the timeline structure for optimal storytelling
"""
        return summary
    
    def _guess_project_type(self, project_name: str) -> str:
        """Make a guess about the project type based on name."""
        project_name = project_name.lower()
        if any(term in project_name for term in ["interview", "talk", "podcast"]):
            return "interview"
        elif any(term in project_name for term in ["commercial", "ad", "promo"]):
            return "commercial"
        elif any(term in project_name for term in ["film", "movie", "short"]):
            return "film"
        elif any(term in project_name for term in ["doc", "documentary"]):
            return "documentary"
        elif any(term in project_name for term in ["music", "video", "mv"]):
            return "music video"
        else:
            return "video editing"

async def main():
    """Main function to run the example."""
    # Initialize the MCP client
    mcp_client = MCPClient("ws://localhost:8765/mcp")
    
    try:
        # Connect to the MCP server
        connected = await mcp_client.connect()
        if not connected:
            print("Failed to connect to the MCP server. Make sure it's running.")
            return
        
        print("Connected to DaVinci Resolve MCP Server")
        
        # Get project information
        project_info = await mcp_client.send_request("get_project_info")
        print(f"Retrieved project info: {json.dumps(project_info, indent=2)}")
        
        # Get timeline clips
        timeline_clips = await mcp_client.send_request("get_timeline_clips")
        print(f"Retrieved {len(timeline_clips.get('clips', []))} clips from timeline")
        
        # Initialize the LLM client (mock for this example)
        llm = MockLLM()
        
        # Generate project summary
        print("\nGenerating project summary...\n")
        summary = await llm.analyze_project(project_info)
        
        # Print the summary
        print(summary)
        
        # In a real application, you might want to:
        # 1. Save the summary to a file
        # 2. Create a summary clip in the timeline
        # 3. Use the summary for other purposes like metadata
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Disconnect from the MCP server
        await mcp_client.disconnect()
        print("Disconnected from MCP server")

if __name__ == "__main__":
    asyncio.run(main()) 