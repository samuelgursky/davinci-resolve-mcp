"""
Edit Skill - Timeline and clip operations on the Edit page.

Capabilities:
- Timeline creation/management (SUPPORTED)
- Clip insertion (SUPPORTED)
- Markers (SUPPORTED)
- Transform/Crop/Composite (SUPPORTED)
- Retime/Stabilization (SUPPORTED)
- Basic audio properties (PARTIAL)
- Keyframes (SUPPORTED)
- OpenFX (UNSUPPORTED - no MCP tools)
"""

import logging
from typing import List, Dict, Any, Optional

from .base_skill import (
    BaseSkill,
    SkillCapability,
    CapabilityStatus,
    ExecutionResult,
)

logger = logging.getLogger("autonomous.skills.edit")


class EditSkill(BaseSkill):
    """
    Edit page skill for timeline and clip operations.

    Handles:
    - Timeline creation and configuration
    - Clip insertion and arrangement
    - Markers
    - Transform, crop, composite properties
    - Retime and stabilization
    - Basic keyframe operations
    """

    PAGE_NAME = "edit"
    SKILL_NAME = "Edit"

    def get_capabilities(self) -> List[SkillCapability]:
        """Return Edit page capabilities."""
        return [
            # Timeline Management
            SkillCapability(
                name="create_timeline",
                description="Create new timelines with specified settings",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["create_timeline", "create_empty_timeline"],
            ),
            SkillCapability(
                name="switch_timeline",
                description="Switch between timelines",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["set_current_timeline", "list_timelines"],
            ),
            SkillCapability(
                name="timeline_info",
                description="Get timeline information and track structure",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["get_current_timeline", "get_timeline_tracks"],
            ),
            SkillCapability(
                name="delete_timeline",
                description="Delete timelines",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["delete_timeline"],
            ),

            # Clip Operations
            SkillCapability(
                name="add_clips",
                description="Add clips from media pool to timeline",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["add_clip_to_timeline"],
                notes="Clips added at end; precise positioning requires manual work",
            ),
            SkillCapability(
                name="get_timeline_items",
                description="List all clips on timeline with properties",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["get_timeline_items", "get_timeline_item_properties"],
            ),

            # Markers
            SkillCapability(
                name="add_marker",
                description="Add colored markers with notes",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["add_marker"],
            ),

            # Transform/Inspector Properties
            SkillCapability(
                name="transform",
                description="Set clip transform (position, scale, rotation)",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["set_timeline_item_transform"],
            ),
            SkillCapability(
                name="crop",
                description="Set clip crop values",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["set_timeline_item_crop"],
            ),
            SkillCapability(
                name="composite",
                description="Set composite mode and opacity",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["set_timeline_item_composite"],
            ),

            # Speed/Timing
            SkillCapability(
                name="retime",
                description="Change clip speed and retime controls",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["set_timeline_item_retime"],
                notes="Speed change, freeze frame, retime curve available",
            ),
            SkillCapability(
                name="stabilization",
                description="Apply and configure stabilization",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["set_timeline_item_stabilization"],
            ),

            # Keyframes
            SkillCapability(
                name="keyframes",
                description="Add/modify/delete keyframes for properties",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=[
                    "enable_keyframes", "get_timeline_item_keyframes",
                    "add_keyframe", "modify_keyframe", "delete_keyframe",
                    "set_keyframe_interpolation",
                ],
            ),

            # Audio (Basic)
            SkillCapability(
                name="clip_audio",
                description="Basic clip audio properties (volume, pan)",
                status=CapabilityStatus.PARTIAL,
                mcp_tools=["set_timeline_item_audio"],
                notes="Volume and pan only; no EQ/dynamics/Fairlight features",
            ),

            # Unsupported
            SkillCapability(
                name="openfx",
                description="Apply OpenFX plugins to clips",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for OpenFX management",
            ),
            SkillCapability(
                name="transitions",
                description="Add/configure transitions between clips",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for transition management",
            ),
            SkillCapability(
                name="clip_positioning",
                description="Precise clip positioning on timeline",
                status=CapabilityStatus.UNSUPPORTED,
                notes="Clips added at end; no insert/overwrite at specific frame",
            ),
            SkillCapability(
                name="track_management",
                description="Add/remove/configure tracks",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for track management",
            ),
        ]

    def apply(self, plan: Any, config: Any) -> List[str]:
        """
        Apply edit operations from plan.

        Args:
            plan: EditPlan with clips and settings
            config: PipelineConfig

        Returns:
            List of execution log messages
        """
        results = []

        # Check for Resolve connection
        if not self.resolve:
            results.append("[FAIL] No Resolve connection")
            return results

        try:
            # Switch to Edit page
            if not self.switch_to_page():
                results.append("[WARN] Could not switch to Edit page")

            # Get current timeline info
            timeline = self._get_current_timeline()
            if timeline:
                self._log_result(results, ExecutionResult(
                    success=True,
                    operation="Timeline",
                    message=f"Working with: {timeline.get('name', 'Unknown')}",
                ))

            # Process clips from plan
            if hasattr(plan, 'clips') and plan.clips:
                self._apply_clips(plan.clips, results)

            # Process markers
            if hasattr(plan, 'markers') and plan.markers:
                self._apply_markers(plan.markers, results)

            # Process transitions (will warn as unsupported)
            if hasattr(plan, 'transitions') and plan.transitions:
                self._warn_unsupported("Transitions", results)

        except Exception as e:
            results.append(f"[FAIL] Edit skill error: {e}")
            logger.exception("Edit skill failed")

        return results

    def _get_current_timeline(self) -> Optional[Dict[str, Any]]:
        """Get current timeline info."""
        try:
            if self.project:
                timeline = self.project.GetCurrentTimeline()
                if timeline:
                    return {
                        "name": timeline.GetName(),
                        "frame_rate": timeline.GetSetting("timelineFrameRate"),
                    }
        except Exception as e:
            logger.warning(f"Could not get timeline: {e}")
        return None

    def _apply_clips(self, clips: List[Any], results: List[str]) -> None:
        """Apply clip insertions."""
        if not self.is_supported("add_clips"):
            self._warn_unsupported("Add clips", results)
            return

        for i, clip in enumerate(clips):
            try:
                # In a full implementation, this would use MCP tools
                # For now, we report what would be done
                self._log_result(results, ExecutionResult(
                    success=True,
                    operation=f"Clip {i}",
                    message=f"Would add: {clip.name}",
                    warning="Implementation uses add_clip_to_timeline",
                ))
            except Exception as e:
                self._log_result(results, ExecutionResult(
                    success=False,
                    operation=f"Clip {i}",
                    message=f"Failed: {e}",
                ))

    def _apply_markers(self, markers: List[Any], results: List[str]) -> None:
        """Apply marker additions."""
        if not self.is_supported("add_marker"):
            self._warn_unsupported("Markers", results)
            return

        for marker in markers:
            try:
                self._log_result(results, ExecutionResult(
                    success=True,
                    operation="Marker",
                    message=f"Would add at frame {marker.frame}: {marker.note}",
                ))
            except Exception as e:
                self._log_result(results, ExecutionResult(
                    success=False,
                    operation="Marker",
                    message=f"Failed: {e}",
                ))

    def create_timeline(
        self,
        name: str,
        width: int = 1920,
        height: int = 1080,
        fps: str = "24",
    ) -> Optional[str]:
        """
        Create a new timeline.

        Returns timeline name if successful, None otherwise.
        """
        if not self.is_supported("create_timeline"):
            logger.warning("create_timeline not supported")
            return None

        if not self.project:
            logger.error("No project connection")
            return None

        try:
            media_pool = self.project.GetMediaPool()
            if media_pool:
                timeline = media_pool.CreateEmptyTimeline(name)
                if timeline:
                    # Set timeline settings
                    timeline.SetSetting("timelineResolutionWidth", str(width))
                    timeline.SetSetting("timelineResolutionHeight", str(height))
                    timeline.SetSetting("timelineFrameRate", fps)
                    logger.info(f"Created timeline: {name}")
                    return name
        except Exception as e:
            logger.error(f"Failed to create timeline: {e}")

        return None

    def add_clip_to_timeline(self, clip_name: str) -> bool:
        """
        Add a clip from media pool to current timeline.

        Returns True if successful.
        """
        if not self.is_supported("add_clips"):
            logger.warning("add_clips not supported")
            return False

        if not self.project:
            logger.error("No project connection")
            return False

        try:
            media_pool = self.project.GetMediaPool()
            if media_pool:
                # Find clip in media pool
                root_folder = media_pool.GetRootFolder()
                clips = root_folder.GetClipList()

                for clip in clips:
                    if clip.GetName() == clip_name:
                        result = media_pool.AppendToTimeline([clip])
                        if result:
                            logger.info(f"Added clip to timeline: {clip_name}")
                            return True

                logger.warning(f"Clip not found: {clip_name}")
        except Exception as e:
            logger.error(f"Failed to add clip: {e}")

        return False
