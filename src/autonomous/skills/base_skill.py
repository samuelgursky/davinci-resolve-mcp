"""
Base Skill - Abstract base class for page-aware skills.

All skills inherit from this and implement:
- get_capabilities() -> List[SkillCapability]
- apply(plan, config) -> List[str]
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger("autonomous.skills")


class CapabilityStatus(str, Enum):
    """Status of a capability."""
    SUPPORTED = "supported"       # Fully supported via MCP
    PARTIAL = "partial"           # Partially supported (some features work)
    UNSUPPORTED = "unsupported"   # Not available via MCP
    UNTESTED = "untested"         # May work but not verified


@dataclass
class SkillCapability:
    """Describes a single capability within a skill."""

    name: str
    description: str
    status: CapabilityStatus
    mcp_tools: List[str] = field(default_factory=list)  # MCP tool names used
    notes: str = ""  # Additional notes or limitations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "mcp_tools": self.mcp_tools,
            "notes": self.notes,
        }


@dataclass
class ExecutionResult:
    """Result of a skill execution step."""

    success: bool
    operation: str
    message: str
    warning: Optional[str] = None

    def __str__(self) -> str:
        prefix = "[OK]" if self.success else "[FAIL]"
        result = f"{prefix} {self.operation}: {self.message}"
        if self.warning:
            result += f" (Warning: {self.warning})"
        return result


class BaseSkill(ABC):
    """
    Abstract base class for DaVinci Resolve page skills.

    Each skill:
    - Is aware of its page (edit/color/fairlight/fusion)
    - Reports capabilities (supported/partial/unsupported)
    - Applies operations via MCP tools
    - Gracefully handles unsupported features
    """

    # Page name (edit, color, fairlight, fusion, deliver)
    PAGE_NAME: str = ""

    # Human-readable skill name
    SKILL_NAME: str = ""

    def __init__(self, resolve=None, project=None):
        """
        Initialize skill with optional Resolve connection.

        Args:
            resolve: DaVinci Resolve instance
            project: Current project instance
        """
        self.resolve = resolve
        self.project = project
        self._capabilities: Optional[List[SkillCapability]] = None

    @abstractmethod
    def get_capabilities(self) -> List[SkillCapability]:
        """
        Return list of capabilities for this skill.

        Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    def apply(self, plan: Any, config: Any) -> List[str]:
        """
        Apply the skill to execute plan operations.

        Args:
            plan: EditPlan or relevant plan object
            config: PipelineConfig

        Returns:
            List of execution log messages
        """
        pass

    @property
    def capabilities(self) -> List[SkillCapability]:
        """Cached capabilities list."""
        if self._capabilities is None:
            self._capabilities = self.get_capabilities()
        return self._capabilities

    def get_capability(self, name: str) -> Optional[SkillCapability]:
        """Get a specific capability by name."""
        for cap in self.capabilities:
            if cap.name == name:
                return cap
        return None

    def is_supported(self, capability_name: str) -> bool:
        """Check if a capability is supported."""
        cap = self.get_capability(capability_name)
        return cap is not None and cap.status in (
            CapabilityStatus.SUPPORTED,
            CapabilityStatus.PARTIAL,
        )

    def get_supported_capabilities(self) -> List[SkillCapability]:
        """Get all supported capabilities."""
        return [
            c for c in self.capabilities
            if c.status in (CapabilityStatus.SUPPORTED, CapabilityStatus.PARTIAL)
        ]

    def get_unsupported_capabilities(self) -> List[SkillCapability]:
        """Get all unsupported capabilities."""
        return [
            c for c in self.capabilities
            if c.status == CapabilityStatus.UNSUPPORTED
        ]

    def switch_to_page(self) -> bool:
        """
        Switch to this skill's page in Resolve.

        Returns:
            True if successful
        """
        if not self.resolve:
            logger.warning("No Resolve connection - cannot switch page")
            return False

        try:
            result = self.resolve.OpenPage(self.PAGE_NAME)
            if result:
                logger.debug(f"Switched to {self.PAGE_NAME} page")
                return True
            else:
                logger.warning(f"Failed to switch to {self.PAGE_NAME} page")
                return False
        except Exception as e:
            logger.error(f"Error switching to {self.PAGE_NAME}: {e}")
            return False

    def _log_result(self, results: List[str], result: ExecutionResult) -> None:
        """Add execution result to log list."""
        results.append(str(result))
        if result.success:
            logger.info(str(result))
        else:
            logger.warning(str(result))

    def _warn_unsupported(self, operation: str, results: List[str]) -> None:
        """Log warning for unsupported operation."""
        msg = f"[SKIP] {operation}: Not supported via MCP"
        results.append(msg)
        logger.warning(msg)

    def report(self) -> str:
        """Generate a capability report for this skill."""
        lines = [
            f"## {self.SKILL_NAME} ({self.PAGE_NAME.upper()} Page)",
            "",
        ]

        supported = self.get_supported_capabilities()
        unsupported = self.get_unsupported_capabilities()

        if supported:
            lines.append("### Supported Operations")
            lines.append("")
            for cap in supported:
                status_icon = "+" if cap.status == CapabilityStatus.SUPPORTED else "~"
                lines.append(f"  [{status_icon}] {cap.name}")
                lines.append(f"      {cap.description}")
                if cap.mcp_tools:
                    lines.append(f"      Tools: {', '.join(cap.mcp_tools)}")
                if cap.notes:
                    lines.append(f"      Note: {cap.notes}")
            lines.append("")

        if unsupported:
            lines.append("### Unsupported Operations")
            lines.append("")
            for cap in unsupported:
                lines.append(f"  [-] {cap.name}")
                lines.append(f"      {cap.description}")
                if cap.notes:
                    lines.append(f"      Reason: {cap.notes}")
            lines.append("")

        return "\n".join(lines)
