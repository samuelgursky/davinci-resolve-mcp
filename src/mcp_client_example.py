#!/usr/bin/env python
"""
Example client for the DaVinci Resolve MCP server.

This script demonstrates how to connect to the MCP server and perform operations.
"""
import asyncio
import json
import time
import uuid
from typing import Dict, Any, Optional
import websockets
from loguru import logger

# MCP server configuration
MCP_SERVER_URL = "ws://localhost:8765/mcp"

class MCPClient:
    """Client for the MCP server."""
    
    def __init__(self, server_url: str = MCP_SERVER_URL):
        """Initialize the client with the server URL."""
        self.server_url = server_url
        self.websocket = None
        self.connected = False
        self.server_info = None
    
    async def connect(self) -> bool:
        """Connect to the MCP server."""
        try:
            self.websocket = await websockets.connect(self.server_url)
            self.connected = True
            
            # Wait for server info message
            response = await self.websocket.recv()
            self.server_info = json.loads(response)
            
            logger.info(f"Connected to MCP server: {self.server_info.get('data', {}).get('name')}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            self.connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from the MCP server."""
        if self.connected and self.websocket:
            message_id = str(uuid.uuid4())
            await self.websocket.send(json.dumps({"id": message_id, "type": "close"}))
            
            try:
                # Wait for close acknowledgment (with timeout)
                response = await asyncio.wait_for(self.websocket.recv(), timeout=2.0)
                response_data = json.loads(response)
                logger.debug(f"Received close acknowledgment: {response_data}")
            except asyncio.TimeoutError:
                logger.warning("No close acknowledgment received from server")
            
            await self.websocket.close()
            logger.info("Disconnected from MCP server")
            
        self.connected = False
        self.websocket = None
    
    async def send_request(self, operation: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a request to the MCP server and wait for a response."""
        if not self.connected or not self.websocket:
            raise Exception("Not connected to MCP server")
        
        # Generate a unique message ID
        message_id = str(uuid.uuid4())
        
        # Create the request message
        request = {
            "id": message_id,
            "type": "request",
            "operation": operation,
            "data": data or {}
        }
        
        # Send the request
        await self.websocket.send(json.dumps(request))
        logger.debug(f"Sent request: {request}")
        
        # Wait for the response
        response = await self.websocket.recv()
        response_data = json.loads(response)
        logger.debug(f"Received response: {response_data}")
        
        # Check if the response is an error
        if response_data.get("type") == "error":
            error_message = response_data.get("data", {}).get("message", "Unknown error")
            raise Exception(f"Error from MCP server: {error_message}")
        
        return response_data.get("data", {})
    
    async def ping(self) -> bool:
        """Send a ping to the server and check for a pong response."""
        if not self.connected or not self.websocket:
            return False
        
        message_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)  # Current time in milliseconds
        
        ping_message = {
            "id": message_id,
            "type": "ping",
            "data": {"timestamp": timestamp}
        }
        
        try:
            await self.websocket.send(json.dumps(ping_message))
            response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
            response_data = json.loads(response)
            
            if response_data.get("type") == "pong":
                return True
            return False
            
        except Exception as e:
            logger.error(f"Ping failed: {e}")
            return False

async def example_workflow():
    """Example workflow demonstrating MCP client usage."""
    client = MCPClient()
    
    try:
        # Connect to the MCP server
        connected = await client.connect()
        if not connected:
            logger.error("Failed to connect to MCP server.")
            return
        
        # Get the list of projects
        projects = await client.send_request("get_projects")
        logger.info(f"Available projects: {projects}")
        
        # Open a project (if available)
        if projects.get("projects") and len(projects.get("projects")) > 0:
            project_name = projects.get("projects")[0]
            logger.info(f"Opening project: {project_name}")
            
            result = await client.send_request("open_project", {"name": project_name})
            logger.info(f"Open project result: {result}")
        
        # Get project info
        project_info = await client.send_request("get_project_info")
        logger.info(f"Project info: {project_info}")
        
        # Get timeline info
        timeline_info = await client.send_request("get_timeline_info")
        logger.info(f"Timeline info: {timeline_info}")
        
        # Get media pool items
        media_items = await client.send_request("get_media_pool_items")
        logger.info(f"Media pool items: {media_items}")
        
        # Get timeline clips
        timeline_clips = await client.send_request("get_timeline_clips")
        logger.info(f"Timeline clips: {timeline_clips}")
        
    except Exception as e:
        logger.error(f"Error in example workflow: {e}")
    finally:
        # Disconnect from the server
        await client.disconnect()

async def main():
    """Run the example workflow."""
    logger.info("Starting MCP client example")
    await example_workflow()
    logger.info("MCP client example completed")

if __name__ == "__main__":
    asyncio.run(main()) 