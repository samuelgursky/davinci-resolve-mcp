"""
DaVinci Resolve Skills - Page-aware capability modules.

Each skill is aware of what MCP operations are supported and
gracefully handles unsupported features with warnings.
"""

from .base_skill import BaseSkill, CapabilityStatus, SkillCapability, ExecutionResult
from .edit_skill import EditSkill
from .color_skill import ColorSkill
from .fairlight_skill import FairlightSkill
from .fusion_skill import FusionSkill

__all__ = [
    "BaseSkill",
    "CapabilityStatus",
    "SkillCapability",
    "ExecutionResult",
    "EditSkill",
    "ColorSkill",
    "FairlightSkill",
    "FusionSkill",
]


def get_all_skills():
    """Get instances of all skills for capability reporting."""
    return [
        EditSkill(),
        ColorSkill(),
        FairlightSkill(),
        FusionSkill(),
    ]


def generate_capabilities_report() -> str:
    """
    Generate a comprehensive capabilities report for all skills.

    Returns:
        Formatted string showing all supported/unsupported operations
    """
    lines = [
        "=" * 60,
        "DAVINCI RESOLVE MCP - CAPABILITIES REPORT",
        "=" * 60,
        "",
    ]

    skills = get_all_skills()

    # Summary counts
    total_supported = 0
    total_partial = 0
    total_unsupported = 0

    for skill in skills:
        for cap in skill.capabilities:
            if cap.status == CapabilityStatus.SUPPORTED:
                total_supported += 1
            elif cap.status == CapabilityStatus.PARTIAL:
                total_partial += 1
            elif cap.status == CapabilityStatus.UNSUPPORTED:
                total_unsupported += 1

    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Fully Supported:    {total_supported}")
    lines.append(f"  Partially Supported: {total_partial}")
    lines.append(f"  Unsupported:        {total_unsupported}")
    lines.append("")

    # Per-skill reports
    for skill in skills:
        lines.append(skill.report())

    # Legend
    lines.append("=" * 60)
    lines.append("LEGEND")
    lines.append("-" * 40)
    lines.append("  [+] Fully supported via MCP")
    lines.append("  [~] Partially supported (some features work)")
    lines.append("  [-] Not supported via MCP")
    lines.append("")

    return "\n".join(lines)
