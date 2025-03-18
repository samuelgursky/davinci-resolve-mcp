#!/usr/bin/env python
"""
MCP server implementation for DaVinci Resolve.

This module implements a Model Context Protocol server that connects to DaVinci Resolve.
"""
import os
import sys
import json
import asyncio
from typing import Dict, Any, List, Optional, Tuple, Union
import logging
from pathlib import Path
import importlib

# Add parent directory to path for local imports
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent))

# Import config, making sure to reload it
import config
importlib.reload(config)
from config import settings, SERVER_INFO, SUPPORTED_OPERATIONS

# Print supported operations for debugging
print(f"Loaded supported operations: {SUPPORTED_OPERATIONS}")

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from loguru import logger

from resolve_integration.client import ResolveClient

# Initialize FastAPI app
app = FastAPI(
    title="DaVinci Resolve MCP Server",
    description="Model Context Protocol server for DaVinci Resolve",
    version=settings.SERVER_VERSION,
)

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Resolve client
resolve_client = ResolveClient()

# Set up connection manager for WebSockets
class ConnectionManager:
    """Manager for WebSocket connections."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        """Connect a new client."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """Disconnect a client."""
        self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total connections: {len(self.active_connections)}")
    
    async def send_message(self, message: Dict[str, Any], websocket: WebSocket):
        """Send a message to a specific client."""
        await websocket.send_json(message)
    
    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message to all connected clients."""
        for connection in self.active_connections:
            await connection.send_json(message)

manager = ConnectionManager()

# Helper functions
def check_api_key(x_api_key: Optional[str] = Header(None)):
    """Check if the API key is valid."""
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

# API routes
@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "DaVinci Resolve MCP Server", "version": settings.SERVER_VERSION}

@app.get("/info")
async def server_info():
    """Get server information."""
    return SERVER_INFO

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    resolve_connected = resolve_client.is_connected()
    return {
        "status": "healthy" if resolve_connected else "unhealthy",
        "resolve_connected": resolve_connected,
        "version": settings.SERVER_VERSION,
    }

@app.get("/operations")
async def get_operations():
    """Get supported operations."""
    return {"operations": SUPPORTED_OPERATIONS}

# WebSocket route for MCP
@app.websocket("/mcp")
async def mcp_endpoint(websocket: WebSocket):
    """WebSocket endpoint for MCP."""
    await manager.connect(websocket)
    
    try:
        # Send server info on connection
        await manager.send_message(
            {
                "type": "server_info",
                "data": SERVER_INFO,
            },
            websocket,
        )
        
        # Handle incoming messages
        while True:
            # Receive message
            message = await websocket.receive_json()
            logger.debug(f"Received message: {message}")
            
            # Check message structure
            if "id" not in message or "type" not in message:
                await manager.send_message(
                    {
                        "type": "error",
                        "data": {
                            "message": "Invalid message structure. Must include 'id' and 'type'."
                        },
                    },
                    websocket,
                )
                continue
            
            message_id = message["id"]
            message_type = message["type"]
            
            # Handle different message types
            if message_type == "ping":
                # Ping-pong for keeping connection alive
                await manager.send_message(
                    {
                        "id": message_id,
                        "type": "pong",
                        "data": {"timestamp": message.get("data", {}).get("timestamp", None)},
                    },
                    websocket,
                )
            
            elif message_type == "request":
                # Handle requests for DaVinci Resolve operations
                if "operation" not in message or "data" not in message:
                    await manager.send_message(
                        {
                            "id": message_id,
                            "type": "error",
                            "data": {
                                "message": "Invalid request structure. Must include 'operation' and 'data'."
                            },
                        },
                        websocket,
                    )
                    continue
                
                operation = message["operation"]
                data = message["data"]
                
                if operation not in SUPPORTED_OPERATIONS:
                    await manager.send_message(
                        {
                            "id": message_id,
                            "type": "error",
                            "data": {
                                "message": f"Unsupported operation: {operation}. Supported operations: {SUPPORTED_OPERATIONS}"
                            },
                        },
                        websocket,
                    )
                    continue
                
                # Process the request based on the operation
                try:
                    result = await process_resolve_operation(operation, data)
                    await manager.send_message(
                        {
                            "id": message_id,
                            "type": "response",
                            "operation": operation,
                            "data": result,
                        },
                        websocket,
                    )
                except Exception as e:
                    logger.error(f"Error processing operation {operation}: {str(e)}")
                    await manager.send_message(
                        {
                            "id": message_id,
                            "type": "error",
                            "operation": operation,
                            "data": {
                                "message": f"Error processing operation: {str(e)}"
                            },
                        },
                        websocket,
                    )
            
            elif message_type == "close":
                # Client wants to close the connection
                await manager.send_message(
                    {
                        "id": message_id,
                        "type": "close_ack",
                    },
                    websocket,
                )
                break
            
            else:
                # Unknown message type
                await manager.send_message(
                    {
                        "id": message_id,
                        "type": "error",
                        "data": {
                            "message": f"Unknown message type: {message_type}"
                        },
                    },
                    websocket,
                )
                
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        manager.disconnect(websocket)

async def process_resolve_operation(operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Process a DaVinci Resolve operation."""
    if not resolve_client.is_connected():
        return {"error": "Not connected to DaVinci Resolve. Make sure it's running with a project open."}
    
    # First, check API capabilities and include in response
    api_capabilities = resolve_client.api_capabilities
    
    try:
        # Handle operations that don't require an open project
        if operation == "get_projects":
            projects = resolve_client.get_project_list()
            return {"projects": projects, "api_capabilities": api_capabilities}
        
        # Handle get_api_capabilities operation to return API capabilities
        if operation == "get_api_capabilities":
            return {"api_capabilities": api_capabilities}
        
        # For operations requiring a project, ensure one is open
        if operation in ["get_project_info", "get_timeline_info", "get_media_pool_items", 
                        "get_timeline_clips", "create_project", "open_project", 
                        "add_clip_to_timeline", "export_timeline", "apply_lut", "render_project"]:
            # Only try to ensure a project is open for operations that require it
            if not resolve_client.ensure_project_open():
                return {"error": "No project is open in DaVinci Resolve and couldn't open one automatically.",
                        "api_capabilities": api_capabilities}
        
        # Handle different operations
        if operation == "get_project_info":
            try:
                if not resolve_client.current_project:
                    return {"error": "No project open in DaVinci Resolve",
                            "api_capabilities": api_capabilities}
                
                # Get basic project info that we know works
                project_info = {
                    "name": resolve_client.current_project.GetName(),
                    "timelines": [],
                    "current_timeline": None,
                    "media_pool_item_count": 0,
                    "api_capabilities": api_capabilities
                }
                
                # Try to get additional info only if API capabilities allow
                if api_capabilities.get("get_timeline_names", False):
                    try:
                        timelines = resolve_client.get_timeline_list()
                        project_info["timelines"] = timelines
                    except Exception as e:
                        logger.error(f"Error getting timeline list: {e}")
                
                # Try to get current timeline
                if api_capabilities.get("get_current_timeline", False):
                    try:
                        timeline = resolve_client.get_current_timeline()
                        if timeline:
                            project_info["current_timeline"] = timeline.GetName()
                    except Exception as e:
                        logger.error(f"Error getting current timeline: {e}")
                
                # Try timeline by index if no timelines found
                if not project_info["timelines"] and api_capabilities.get("get_timeline_by_index", False):
                    try:
                        timeline = resolve_client.get_timeline_by_index(0)
                        if timeline:
                            name = timeline.GetName()
                            project_info["timelines"] = [name]
                            if not project_info["current_timeline"]:
                                project_info["current_timeline"] = name
                    except Exception as e:
                        logger.error(f"Error getting timeline by index: {e}")
                
                # Try to get media pool items count
                if api_capabilities.get("get_media_pool", False) and api_capabilities.get("get_root_folder", False) and api_capabilities.get("get_clip_list", False):
                    try:
                        media_pool_items = resolve_client.get_media_pool_items()
                        project_info["media_pool_item_count"] = len(media_pool_items) if media_pool_items else 0
                    except Exception as e:
                        logger.error(f"Error getting media pool items count: {e}")
                
                return project_info
            except Exception as e:
                logger.error(f"Error in get_project_info: {e}")
                return {"error": f"Failed to get project info: {str(e)}",
                        "api_capabilities": api_capabilities}
        
        elif operation == "get_timeline_info":
            timeline = resolve_client.get_current_timeline()
            if not timeline:
                # Try to get a timeline by index as fallback
                logger.info("No current timeline, trying to get timeline by index")
                timeline = resolve_client.get_timeline_by_index(0)
                
                if not timeline:
                    return {"error": "No timeline available", "available_methods": ["get_timeline_by_index"]}
            
            try:
                timeline_name = timeline.GetName() if timeline else "Unknown"
                # Safely get track count
                try:
                    track_count = timeline.GetTrackCount()
                except Exception as e:
                    logger.error(f"Error getting track count: {e}")
                    track_count = 0
                
                # Safely get timeline items
                try:
                    timeline_items = resolve_client.get_timeline_items(timeline)
                    item_count = len(timeline_items) if timeline_items else 0
                except Exception as e:
                    logger.error(f"Error getting timeline items: {e}")
                    item_count = 0
                
                return {
                    "name": timeline_name,
                    "track_count": track_count,
                    "item_count": item_count,
                }
            except Exception as e:
                logger.error(f"Error getting timeline info: {e}")
                return {"error": f"Failed to get timeline info: {str(e)}"}
        
        elif operation == "get_media_pool_items":
            try:
                # Check if required API capabilities are available
                if not all([api_capabilities.get("get_media_pool", False), 
                            api_capabilities.get("get_root_folder", False),
                            api_capabilities.get("get_clip_list", False)]):
                    return {"error": "Media pool API capabilities not available", 
                            "items": [], 
                            "api_capabilities": api_capabilities}
                
                items = resolve_client.get_media_pool_items()
                result_items = []
                
                if items:
                    for item in items:
                        try:
                            if item:
                                name = item.GetName() if hasattr(item, "GetName") else "Unknown"
                                item_type = item.GetType() if hasattr(item, "GetType") else "Unknown"
                                result_items.append({"name": name, "type": item_type})
                        except Exception as e:
                            logger.error(f"Error processing media pool item: {e}")
                            continue
                
                return {"items": result_items, "api_capabilities": api_capabilities}
            except Exception as e:
                logger.error(f"Error processing media pool items: {e}")
                return {"error": f"Failed to process media pool items: {str(e)}", 
                        "items": [], 
                        "api_capabilities": api_capabilities}
        
        elif operation == "get_timeline_clips":
            try:
                # Check if required API capabilities are available
                if not api_capabilities.get("get_current_timeline", False) and not api_capabilities.get("get_timeline_by_index", False):
                    return {"error": "Timeline API capabilities not available", 
                            "clips": [], 
                            "api_capabilities": api_capabilities}
                
                # Get current timeline
                timeline = resolve_client.get_current_timeline()
                if not timeline:
                    # Try to get a timeline by index as fallback
                    logger.info("No current timeline, trying to get timeline by index")
                    timeline = resolve_client.get_timeline_by_index(0)
                    
                    if not timeline:
                        return {"error": "No timeline available", "clips": []}
                
                logger.info(f"Getting clips from timeline: {timeline.GetName()}")
                
                # Try to get timeline items directly from tracks
                result_clips = []
                try:
                    video_track_count = timeline.GetTrackCount("video")
                    logger.info(f"Video track count: {video_track_count}")
                    
                    for i in range(1, video_track_count + 1):
                        try:
                            track_items = timeline.GetItemListInTrack("video", i)
                            if track_items:
                                logger.info(f"Found {len(track_items)} items in video track {i}")
                                for item in track_items:
                                    try:
                                        if item:
                                            name = item.GetName() if hasattr(item, "GetName") else "Unknown"
                                            duration = item.GetDuration() if hasattr(item, "GetDuration") else 0
                                            result_clips.append({"name": name, "duration": duration})
                                    except Exception as e:
                                        logger.error(f"Error processing timeline clip: {e}")
                        except Exception as e:
                            logger.error(f"Error getting items from track {i}: {e}")
                except Exception as e:
                    logger.error(f"Error getting track count: {e}")
                
                return {"clips": result_clips, "api_capabilities": api_capabilities}
            except Exception as e:
                logger.error(f"Error processing timeline clips: {e}")
                return {"error": f"Failed to process timeline clips: {str(e)}", 
                        "clips": [], 
                        "api_capabilities": api_capabilities}
        
        elif operation == "select_clips_by_name":
            try:
                # Validate input
                if "clip_name" not in data:
                    return {"error": "Missing required parameter: clip_name", 
                            "api_capabilities": api_capabilities}
                
                clip_name = data["clip_name"]
                
                # Check if timeline capabilities are available
                if not api_capabilities.get("get_current_timeline", False) and not api_capabilities.get("get_timeline_by_index", False):
                    return {"error": "Timeline API capabilities not available", 
                            "api_capabilities": api_capabilities}
                
                # Get current timeline
                timeline = resolve_client.get_current_timeline()
                if not timeline:
                    # Try to get a timeline by index as fallback
                    logger.info("No current timeline, trying to get timeline by index")
                    timeline = resolve_client.get_timeline_by_index(0)
                    
                    if not timeline:
                        return {"error": "No timeline available", 
                                "api_capabilities": api_capabilities}
                
                logger.info(f"Getting clips from timeline: {timeline.GetName()}")
                
                # Get all timeline items
                timeline_items = []
                try:
                    video_track_count = timeline.GetTrackCount("video")
                    logger.info(f"Video track count: {video_track_count}")
                    
                    for i in range(1, video_track_count + 1):
                        try:
                            track_items = timeline.GetItemListInTrack("video", i)
                            if track_items:
                                logger.info(f"Found {len(track_items)} items in video track {i}")
                                timeline_items.extend(track_items)
                        except Exception as e:
                            logger.error(f"Error getting items from track {i}: {e}")
                except Exception as e:
                    logger.error(f"Error getting track count: {e}")
                
                if not timeline_items:
                    return {"success": False, 
                            "error": "No clips found in timeline", 
                            "items_found": 0, 
                            "items_selected": 0,
                            "api_capabilities": api_capabilities}
                
                # Find matching clips
                matching_clips = []
                for item in timeline_items:
                    try:
                        name = item.GetName()
                        if clip_name.lower() in name.lower():
                            matching_clips.append(item)
                            logger.info(f"Found matching clip: {name}")
                    except Exception as e:
                        logger.error(f"Error checking clip name: {e}")
                
                if not matching_clips:
                    return {"success": False, 
                            "error": f"No clips found matching '{clip_name}'", 
                            "items_found": 0, 
                            "items_selected": 0,
                            "api_capabilities": api_capabilities}
                
                # Try to select the clips
                success = False
                
                # Method 1: Try SetSelection
                try:
                    timeline.SetSelection(matching_clips)
                    logger.info(f"Selected {len(matching_clips)} clips using SetSelection")
                    success = True
                except Exception as e:
                    logger.warning(f"SetSelection failed: {e}")
                
                # Method 2: Try individual selection
                if not success:
                    try:
                        for clip in matching_clips:
                            clip.AddFlag("Selected")
                        logger.info(f"Selected {len(matching_clips)} clips using AddFlag")
                        success = True
                    except Exception as e:
                        logger.error(f"AddFlag selection failed: {e}")
                
                return {"success": success, 
                        "items_found": len(matching_clips), 
                        "items_selected": len(matching_clips) if success else 0,
                        "api_capabilities": api_capabilities}
                
            except Exception as e:
                logger.error(f"Error selecting clips by name: {e}")
                return {"success": False,
                        "error": f"Failed to select clips by name: {str(e)}", 
                        "items_found": 0,
                        "items_selected": 0,
                        "api_capabilities": api_capabilities}
        
        elif operation == "create_project":
            project_name = data.get("name")
            if not project_name:
                raise Exception("Project name is required")
            
            result = resolve_client.project_manager.CreateProject(project_name)
            if result:
                resolve_client.current_project = resolve_client.project_manager.GetCurrentProject()
                return {"success": True, "project_name": project_name}
            else:
                return {"success": False, "error": "Failed to create project"}
        
        elif operation == "open_project":
            project_name = data.get("name")
            if not project_name:
                raise Exception("Project name is required")
            
            result = resolve_client.open_project(project_name)
            return {"success": result, "project_name": project_name}
        
        elif operation == "add_clip_to_timeline":
            # This is a simplified implementation
            clip_name = data.get("clip_name")
            if not clip_name:
                raise Exception("Clip name is required")
            
            media_pool = resolve_client.current_project.GetMediaPool()
            clips = resolve_client.get_media_pool_items()
            
            target_clip = None
            for clip in clips:
                if clip.GetName() == clip_name:
                    target_clip = clip
                    break
                
            if not target_clip:
                return {"success": False, "error": f"Clip not found: {clip_name}"}
            
            # Add to current timeline
            timeline = resolve_client.get_current_timeline()
            if not timeline:
                return {"success": False, "error": "No active timeline"}
            
            result = media_pool.AppendToTimeline([target_clip])
            return {"success": bool(result), "clip_name": clip_name}
        
        # Add implementations for other operations as needed
        
        else:
            raise Exception(f"Operation not implemented: {operation}")
    except Exception as e:
        logger.error(f"Error in operation {operation}: {e}")
        return {"error": f"Operation failed: {str(e)}"}

def run_server():
    """Run the MCP server."""
    logger.info(f"Starting DaVinci Resolve MCP Server on {settings.HOST}:{settings.PORT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    
    # Check if DaVinci Resolve is available
    if not resolve_client.is_connected():
        logger.warning("Not connected to DaVinci Resolve. Please make sure it's running.")
    else:
        logger.info("Connected to DaVinci Resolve")
        
        # Log available projects
        projects = resolve_client.get_project_list()
        logger.info(f"Available projects: {projects}")
    
    # Run the server
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_level="debug" if settings.DEBUG else "info",
    )

if __name__ == "__main__":
    run_server() 