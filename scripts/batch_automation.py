#!/usr/bin/env python3
"""
DaVinci Resolve MCP Batch Automation
-----------------------------------
This script demonstrates automation of common DaVinci Resolve workflows
using the MCP server API. It provides a command-line interface for
executing predefined sequences of operations.

Usage:
    python batch_automation.py [--workflow=NAME] [--config=FILE]

Available Workflows:
    - color_grade: Apply basic color grading to all clips
    - create_proxies: Create proxies for selected media
    - render_timeline: Render a timeline with specific settings
    - organize_media: Organize media into bins by type

Requirements:
    - DaVinci Resolve must be running
    - DaVinci Resolve MCP Server must be running
    - requests module (pip install requests)
"""

import os
import json
import argparse
import logging
import requests
from typing import Dict, Any, Optional, Callable
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(
            f"mcp_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Server configuration
SERVER_URL = "http://localhost:8000/api"


def send_request(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Send a request to the MCP server."""
    try:
        payload = {"tool": tool_name, "params": params}
        logger.info(f"Sending request: {tool_name} with params {params}")
        response = requests.post(SERVER_URL, json=payload)
        response.raise_for_status()
        result = response.json()

        if "error" in result and result["error"]:
            logger.error(f"Error in response: {result['error']}")
        else:
            logger.info(f"Request successful: {tool_name}")

        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        return {"success": False, "error": str(e)}


def workflow_step(description: str) -> Callable:
    """Decorator for workflow steps with descriptive logging."""

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            logger.info(f"STEP: {description}")
            logger.info("-" * 40)
            result = func(*args, **kwargs)
            logger.info("-" * 40)
            return result

        return wrapper

    return decorator


class WorkflowManager:
    """Manages and executes predefined workflows."""

    def __init__(self, config_file: Optional[str] = None):
        """Initialize with optional config file."""
        self.config = {}
        if config_file and os.path.exists(config_file):
            with open(config_file, "r") as f:
                self.config = json.load(f)
                logger.info(f"Loaded configuration from {config_file}")

    @workflow_step("Creating new project")
    def create_project(self, name: str) -> Dict[str, Any]:
        """Create a new project with the given name."""
        return send_request("mcp_davinci_resolve_create_project", {"name": name})

    @workflow_step("Opening existing project")
    def open_project(self, name: str) -> Dict[str, Any]:
        """Open an existing project by name."""
        return send_request("mcp_davinci_resolve_open_project", {"name": name})

    @workflow_step("Creating new timeline")
    def create_timeline(self, name: str) -> Dict[str, Any]:
        """Create a new timeline with the given name."""
        return send_request("mcp_davinci_resolve_create_timeline", {"name": name})

    @workflow_step("Switching to timeline")
    def switch_timeline(self, name: str) -> Dict[str, Any]:
        """Switch to a timeline by name."""
        return send_request("mcp_davinci_resolve_set_current_timeline", {"name": name})

    @workflow_step("Importing media")
    def import_media(self, file_path: str) -> Dict[str, Any]:
        """Import a media file into the media pool."""
        return send_request(
            "mcp_davinci_resolve_import_media", {"file_path": file_path}
        )

    @workflow_step("Creating media bin")
    def create_bin(self, name: str) -> Dict[str, Any]:
        """Create a new bin in the media pool."""
        return send_request("mcp_davinci_resolve_create_bin", {"name": name})

    @workflow_step("Moving media to bin")
    def move_to_bin(self, clip_name: str, bin_name: str) -> Dict[str, Any]:
        """Move a media clip to a bin."""
        return send_request(
            "mcp_davinci_resolve_move_media_to_bin",
            {"clip_name": clip_name, "bin_name": bin_name},
        )

    @workflow_step("Adding clip to timeline")
    def add_to_timeline(
        self, clip_name: str, timeline_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Add a clip to the timeline."""
        params = {"clip_name": clip_name}
        if timeline_name:
            params["timeline_name"] = timeline_name
        return send_request("mcp_davinci_resolve_add_clip_to_timeline", params)

    @workflow_step("Switching page")
    def switch_page(self, page: str) -> Dict[str, Any]:
        """Switch to a specific page in DaVinci Resolve."""
        return send_request("mcp_davinci_resolve_switch_page", {"page": page})

    @workflow_step("Adding node")
    def add_node(
        self, node_type: str = "serial", label: Optional[str] = None
    ) -> Dict[str, Any]:
        """Add a node to the current grade."""
        params = {"node_type": node_type}
        if label:
            params["label"] = label
        return send_request("mcp_davinci_resolve_add_node", params)

    @workflow_step("Setting color wheel parameter")
    def set_color_param(
        self, wheel: str, param: str, value: float, node_index: Optional[int] = None
    ) -> Dict[str, Any]:
        """Set a color wheel parameter for a node."""
        params = {"wheel": wheel, "param": param, "value": value}
        if node_index is not None:
            params["node_index"] = node_index
        return send_request("mcp_davinci_resolve_set_color_wheel_param", params)

    @workflow_step("Adding to render queue")
    def add_to_render_queue(
        self,
        preset_name: str,
        timeline_name: Optional[str] = None,
        use_in_out_range: bool = False,
    ) -> Dict[str, Any]:
        """Add a timeline to the render queue."""
        params = {"preset_name": preset_name, "use_in_out_range": use_in_out_range}
        if timeline_name:
            params["timeline_name"] = timeline_name
        return send_request("mcp_davinci_resolve_add_to_render_queue", params)

    @workflow_step("Starting render")
    def start_render(self) -> Dict[str, Any]:
        """Start rendering the jobs in the render queue."""
        return send_request(
            "mcp_davinci_resolve_start_render", {"random_string": "batch"}
        )

    @workflow_step("Clearing render queue")
    def clear_render_queue(self) -> Dict[str, Any]:
        """Clear all jobs from the render queue."""
        return send_request(
            "mcp_davinci_resolve_clear_render_queue", {"random_string": "batch"}
        )

    @workflow_step("Setting project setting")
    def set_project_setting(
        self, setting_name: str, setting_value: Any
    ) -> Dict[str, Any]:
        """Set a project setting to the specified value."""
        return send_request(
            "mcp_davinci_resolve_set_project_setting",
            {"setting_name": setting_name, "setting_value": setting_value},
        )

    @workflow_step("Saving project")
    def save_project(self) -> Dict[str, Any]:
        """Save the current project."""
        return send_request(
            "mcp_davinci_resolve_save_project", {"random_string": "batch"}
        )

    def run_workflow_color_grade(self) -> None:
        """Run a basic color grading workflow."""
        logger.info("Running color grading workflow")

        # Configure parameters from config or use defaults
        project_name = self.config.get("project_name", "Color Grade Example")
        timeline_name = self.config.get("timeline_name", "Color Timeline")

        # Create or open project
        try:
            self.open_project(project_name)
        except:
            self.create_project(project_name)

        # Set up timeline
        self.create_timeline(timeline_name)
        self.switch_timeline(timeline_name)

        # Import sample media if provided in config
        media_files = self.config.get("media_files", [])
        for file_path in media_files:
            if os.path.exists(file_path):
                self.import_media(file_path)
                clip_name = os.path.basename(file_path)
                self.add_to_timeline(clip_name, timeline_name)

        # Switch to color page and apply basic grade
        self.switch_page("color")

        # Add a serial node for primary correction
        self.add_node("serial", "Primary")

        # Set some color parameters
        # Slightly warm up the midtones
        self.set_color_param("gamma", "red", 0.05, 1)
        self.set_color_param("gamma", "blue", -0.03, 1)

        # Add another node for contrast
        self.add_node("serial", "Contrast")

        # Increase contrast a bit
        self.set_color_param("gain", "master", 0.1, 2)
        self.set_color_param("lift", "master", -0.05, 2)

        # Save the project
        self.save_project()

        logger.info("Color grading workflow completed")

    def run_workflow_render_timeline(self) -> None:
        """Run a workflow to render a timeline."""
        logger.info("Running render timeline workflow")

        # Configure parameters from config or use defaults
        project_name = self.config.get("project_name", "Render Example")
        timeline_name = self.config.get("timeline_name", "Render Timeline")
        preset_name = self.config.get("render_preset", "YouTube 1080p")

        # Create or open project
        try:
            self.open_project(project_name)
        except:
            self.create_project(project_name)

        # Make sure we have a timeline
        timeline_exists = False
        try:
            self.switch_timeline(timeline_name)
            timeline_exists = True
        except:
            self.create_timeline(timeline_name)
            self.switch_timeline(timeline_name)

        # If we need to add media, do it only if timeline is new
        if not timeline_exists:
            media_files = self.config.get("media_files", [])
            for file_path in media_files:
                if os.path.exists(file_path):
                    self.import_media(file_path)
                    clip_name = os.path.basename(file_path)
                    self.add_to_timeline(clip_name, timeline_name)

        # Configure project settings
        self.set_project_setting("timelineFrameRate", "24")

        # Switch to deliver page
        self.switch_page("deliver")

        # Clear any existing render jobs
        self.clear_render_queue()

        # Add timeline to render queue
        self.add_to_render_queue(preset_name, timeline_name)

        # Start rendering
        self.start_render()

        logger.info("Render timeline workflow completed")

    def run_workflow_organize_media(self) -> None:
        """Run a workflow to organize media into bins."""
        logger.info("Running organize media workflow")

        # Configure parameters from config or use defaults
        project_name = self.config.get("project_name", "Media Organization")

        # Create or open project
        try:
            self.open_project(project_name)
        except:
            self.create_project(project_name)

        # Make sure we're on media page
        self.switch_page("media")

        # Create organizational bins
        bins = {
            "Video": [".mp4", ".mov", ".mxf", ".avi"],
            "Audio": [".wav", ".mp3", ".aac", ".m4a"],
            "Images": [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".exr"],
            "Graphics": [".psd", ".ai", ".eps"],
        }

        for bin_name in bins.keys():
            self.create_bin(bin_name)

        # Import media if specified
        media_files = self.config.get("media_files", [])
        imported_clips = []

        for file_path in media_files:
            if os.path.exists(file_path):
                self.import_media(file_path)
                clip_name = os.path.basename(file_path)
                imported_clips.append((clip_name, file_path))

        # Organize clips into bins based on extension
        for clip_name, file_path in imported_clips:
            ext = os.path.splitext(file_path)[1].lower()

            for bin_name, extensions in bins.items():
                if ext in extensions:
                    self.move_to_bin(clip_name, bin_name)
                    break

        # Save the project
        self.save_project()

        logger.info("Media organization workflow completed")

    def run_workflow(self, workflow_name: str) -> None:
        """Run a specified workflow by name."""
        workflows = {
            "color_grade": self.run_workflow_color_grade,
            "render_timeline": self.run_workflow_render_timeline,
            "organize_media": self.run_workflow_organize_media,
        }

        if workflow_name in workflows:
            logger.info(f"Starting workflow: {workflow_name}")
            workflows[workflow_name]()
            logger.info(f"Workflow {workflow_name} completed")
        else:
            logger.error(f"Unknown workflow: {workflow_name}")
            logger.info(f"Available workflows: {', '.join(workflows.keys())}")


def main() -> None:
    """Run the batch automation script."""
    parser = argparse.ArgumentParser(
        description="Automate DaVinci Resolve workflows using MCP Server"
    )
    parser.add_argument(
        "--workflow",
        type=str,
        default="color_grade",
        help="Workflow to run (color_grade, render_timeline, organize_media)",
    )
    parser.add_argument(
        "--config", type=str, default=None, help="Path to JSON configuration file"
    )
    args = parser.parse_args()

    logger.info("Starting DaVinci Resolve MCP Batch Automation")
    logger.info("=" * 50)
    logger.info(f"Workflow: {args.workflow}")
    logger.info(f"Config file: {args.config or 'Using defaults'}")

    try:
        manager = WorkflowManager(args.config)
        manager.run_workflow(args.workflow)
    except Exception as e:
        logger.error(f"Workflow failed: {str(e)}", exc_info=True)

    logger.info("=" * 50)
    logger.info("Batch automation completed")


if __name__ == "__main__":
    main()
