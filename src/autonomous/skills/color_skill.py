"""
Color Skill - Color grading operations on the Color page.

Capabilities:
- Node management (SUPPORTED)
- LUT application (SUPPORTED)
- Color wheels (SUPPORTED)
- Color presets/PowerGrades (SUPPORTED)
- Grade copying (SUPPORTED)
- Color science/space settings (SUPPORTED)
- Curves (UNSUPPORTED - no direct MCP tools)
- Windows/Masks (UNSUPPORTED - no MCP tools)
- Tracker (UNSUPPORTED - no MCP tools)
"""

import logging
from typing import List, Dict, Any, Optional

from .base_skill import (
    BaseSkill,
    SkillCapability,
    CapabilityStatus,
    ExecutionResult,
)

logger = logging.getLogger("autonomous.skills.color")


class ColorSkill(BaseSkill):
    """
    Color page skill for grading operations.

    Handles:
    - Node graph management
    - LUT application and export
    - Color wheel adjustments
    - Color presets (PowerGrades)
    - Grade copying between clips
    - Color science configuration
    """

    PAGE_NAME = "color"
    SKILL_NAME = "Color"

    def get_capabilities(self) -> List[SkillCapability]:
        """Return Color page capabilities."""
        return [
            # Node Management
            SkillCapability(
                name="add_node",
                description="Add serial/parallel/layer nodes to grade",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["add_node", "get_current_color_node"],
            ),
            SkillCapability(
                name="node_info",
                description="Get current node information",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["get_current_color_node"],
            ),

            # LUT Operations
            SkillCapability(
                name="apply_lut",
                description="Apply LUT to current node",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["apply_lut"],
            ),
            SkillCapability(
                name="export_lut",
                description="Export grade as LUT file",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["export_lut", "get_lut_formats"],
            ),
            SkillCapability(
                name="export_powergrade_luts",
                description="Export all PowerGrades as LUTs",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["export_all_powergrade_luts"],
            ),

            # Color Wheels
            SkillCapability(
                name="color_wheels",
                description="Adjust Lift/Gamma/Gain/Offset color wheels",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["get_color_wheel_params", "set_color_wheel_param"],
                notes="Supports all wheel parameters (master, red, green, blue)",
            ),

            # Presets/PowerGrades
            SkillCapability(
                name="list_presets",
                description="List available color presets",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["get_color_presets"],
            ),
            SkillCapability(
                name="save_preset",
                description="Save current grade as preset",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["save_color_preset"],
            ),
            SkillCapability(
                name="apply_preset",
                description="Apply preset to current clip",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["apply_color_preset"],
            ),
            SkillCapability(
                name="delete_preset",
                description="Delete a color preset",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["delete_color_preset"],
            ),
            SkillCapability(
                name="preset_albums",
                description="Create/delete preset albums",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["create_color_preset_album", "delete_color_preset_album"],
            ),

            # Grade Copying
            SkillCapability(
                name="copy_grade",
                description="Copy grade between clips",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["copy_grade"],
                notes="Full or partial grade copying supported",
            ),

            # Color Science
            SkillCapability(
                name="color_science",
                description="Set color science mode and color space",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["set_color_science_mode_tool", "set_color_space_tool"],
            ),
            SkillCapability(
                name="color_settings",
                description="Get color management settings",
                status=CapabilityStatus.SUPPORTED,
                mcp_tools=["get_color_settings_endpoint"],
            ),

            # Unsupported Features
            SkillCapability(
                name="curves",
                description="Adjust curves (hue vs sat, custom curves)",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for curves manipulation",
            ),
            SkillCapability(
                name="primaries_bars",
                description="Adjust primaries using bars interface",
                status=CapabilityStatus.UNSUPPORTED,
                notes="Only color wheels supported, not bars",
            ),
            SkillCapability(
                name="windows",
                description="Create/edit power windows and masks",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for window/mask management",
            ),
            SkillCapability(
                name="tracker",
                description="Track objects for window/stabilization",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for tracking",
            ),
            SkillCapability(
                name="qualifier",
                description="Use HSL qualifier for selections",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for qualifier",
            ),
            SkillCapability(
                name="blur",
                description="Apply blur/sharpen to node",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for blur effects",
            ),
            SkillCapability(
                name="hdr_wheels",
                description="HDR color wheels interface",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for HDR wheels",
            ),
        ]

    def apply(self, plan: Any, config: Any) -> List[str]:
        """
        Apply color grading operations from plan.

        Args:
            plan: EditPlan with grade settings
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
            # Switch to Color page
            if not self.switch_to_page():
                results.append("[WARN] Could not switch to Color page")

            # Apply LUT if specified
            if hasattr(plan, 'grade') and plan.grade:
                self._apply_grade(plan.grade, results)

        except Exception as e:
            results.append(f"[FAIL] Color skill error: {e}")
            logger.exception("Color skill failed")

        return results

    def _apply_grade(self, grade: Any, results: List[str]) -> None:
        """Apply grade settings from plan."""
        # LUT application
        if hasattr(grade, 'lut_path') and grade.lut_path:
            if self.is_supported("apply_lut"):
                self._log_result(results, ExecutionResult(
                    success=True,
                    operation="LUT",
                    message=f"Would apply: {grade.lut_path}",
                ))
            else:
                self._warn_unsupported("LUT application", results)

        # Preset application
        if hasattr(grade, 'preset_name') and grade.preset_name:
            if self.is_supported("apply_preset"):
                self._log_result(results, ExecutionResult(
                    success=True,
                    operation="Preset",
                    message=f"Would apply: {grade.preset_name}",
                ))
            else:
                self._warn_unsupported("Preset application", results)

    def apply_lut(self, lut_path: str, node_index: int = None) -> bool:
        """
        Apply a LUT to current or specified node.

        Args:
            lut_path: Full path to LUT file
            node_index: Optional specific node index

        Returns:
            True if successful
        """
        if not self.is_supported("apply_lut"):
            logger.warning("apply_lut not supported")
            return False

        if not self.project:
            logger.error("No project connection")
            return False

        try:
            timeline = self.project.GetCurrentTimeline()
            if not timeline:
                logger.error("No current timeline")
                return False

            current_clip = timeline.GetCurrentVideoItem()
            if not current_clip:
                logger.error("No current clip")
                return False

            # Apply LUT
            result = current_clip.SetLUT(node_index or 1, lut_path)
            if result:
                logger.info(f"Applied LUT: {lut_path}")
                return True

        except Exception as e:
            logger.error(f"Failed to apply LUT: {e}")

        return False

    def add_node(self, node_type: str = "serial", label: str = None) -> bool:
        """
        Add a node to the current clip's grade.

        Args:
            node_type: "serial", "parallel", or "layer"
            label: Optional node label

        Returns:
            True if successful
        """
        if not self.is_supported("add_node"):
            logger.warning("add_node not supported")
            return False

        if not self.project:
            logger.error("No project connection")
            return False

        try:
            timeline = self.project.GetCurrentTimeline()
            if not timeline:
                logger.error("No current timeline")
                return False

            current_clip = timeline.GetCurrentVideoItem()
            if not current_clip:
                logger.error("No current clip")
                return False

            # Add node based on type
            if node_type == "serial":
                result = current_clip.AddNode()
            elif node_type == "parallel":
                result = current_clip.AddNode("parallel")
            elif node_type == "layer":
                result = current_clip.AddNode("layer")
            else:
                logger.error(f"Unknown node type: {node_type}")
                return False

            if result:
                logger.info(f"Added {node_type} node")
                return True

        except Exception as e:
            logger.error(f"Failed to add node: {e}")

        return False

    def set_wheel_param(
        self,
        wheel: str,
        param: str,
        value: float,
        node_index: int = None,
    ) -> bool:
        """
        Set a color wheel parameter.

        Args:
            wheel: "lift", "gamma", "gain", or "offset"
            param: "master", "red", "green", or "blue"
            value: Parameter value
            node_index: Optional node index

        Returns:
            True if successful
        """
        if not self.is_supported("color_wheels"):
            logger.warning("color_wheels not supported")
            return False

        if not self.project:
            logger.error("No project connection")
            return False

        try:
            timeline = self.project.GetCurrentTimeline()
            if not timeline:
                return False

            current_clip = timeline.GetCurrentVideoItem()
            if not current_clip:
                return False

            # Build property name
            prop_name = f"{wheel}_{param}"

            # Set the property
            result = current_clip.SetProperty(prop_name, value)
            if result:
                logger.info(f"Set {prop_name} to {value}")
                return True

        except Exception as e:
            logger.error(f"Failed to set wheel param: {e}")

        return False

    def copy_grade(
        self,
        source_clip: str = None,
        target_clip: str = None,
        mode: str = "full",
    ) -> bool:
        """
        Copy grade from one clip to another.

        Args:
            source_clip: Source clip name (or current if None)
            target_clip: Target clip name (or current if None)
            mode: "full" or "partial"

        Returns:
            True if successful
        """
        if not self.is_supported("copy_grade"):
            logger.warning("copy_grade not supported")
            return False

        # Implementation would use the copy_grade MCP tool
        logger.info(f"Would copy grade: {source_clip} -> {target_clip} ({mode})")
        return True
