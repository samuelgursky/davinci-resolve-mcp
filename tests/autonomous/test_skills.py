"""
Tests for the page-aware skills module.
"""

import pytest
from src.autonomous.skills import (
    BaseSkill,
    CapabilityStatus,
    SkillCapability,
    ExecutionResult,
    EditSkill,
    ColorSkill,
    FairlightSkill,
    FusionSkill,
    get_all_skills,
    generate_capabilities_report,
)


class TestCapabilityStatus:
    """Tests for CapabilityStatus enum."""

    def test_status_values(self):
        """Verify all status values exist."""
        assert CapabilityStatus.SUPPORTED == "supported"
        assert CapabilityStatus.PARTIAL == "partial"
        assert CapabilityStatus.UNSUPPORTED == "unsupported"
        assert CapabilityStatus.UNTESTED == "untested"


class TestSkillCapability:
    """Tests for SkillCapability dataclass."""

    def test_create_capability(self):
        """Test creating a capability."""
        cap = SkillCapability(
            name="test_cap",
            description="A test capability",
            status=CapabilityStatus.SUPPORTED,
            mcp_tools=["tool1", "tool2"],
            notes="Some notes",
        )
        assert cap.name == "test_cap"
        assert cap.description == "A test capability"
        assert cap.status == CapabilityStatus.SUPPORTED
        assert cap.mcp_tools == ["tool1", "tool2"]
        assert cap.notes == "Some notes"

    def test_to_dict(self):
        """Test converting capability to dict."""
        cap = SkillCapability(
            name="test_cap",
            description="A test capability",
            status=CapabilityStatus.PARTIAL,
            mcp_tools=["tool1"],
        )
        d = cap.to_dict()
        assert d["name"] == "test_cap"
        assert d["status"] == "partial"
        assert d["mcp_tools"] == ["tool1"]


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_success_result(self):
        """Test successful result formatting."""
        result = ExecutionResult(
            success=True,
            operation="Test Op",
            message="Completed successfully",
        )
        assert "[OK]" in str(result)
        assert "Test Op" in str(result)

    def test_failure_result(self):
        """Test failed result formatting."""
        result = ExecutionResult(
            success=False,
            operation="Test Op",
            message="Failed to complete",
        )
        assert "[FAIL]" in str(result)

    def test_result_with_warning(self):
        """Test result with warning."""
        result = ExecutionResult(
            success=True,
            operation="Test Op",
            message="Completed",
            warning="But with issues",
        )
        assert "Warning" in str(result)
        assert "But with issues" in str(result)


class TestEditSkill:
    """Tests for EditSkill."""

    def test_page_name(self):
        """Test page name is set correctly."""
        skill = EditSkill()
        assert skill.PAGE_NAME == "edit"
        assert skill.SKILL_NAME == "Edit"

    def test_capabilities_exist(self):
        """Test that capabilities are defined."""
        skill = EditSkill()
        caps = skill.get_capabilities()
        assert len(caps) > 0

    def test_supported_capabilities(self):
        """Test that expected capabilities are supported."""
        skill = EditSkill()
        assert skill.is_supported("create_timeline")
        assert skill.is_supported("add_clips")
        assert skill.is_supported("transform")
        assert skill.is_supported("keyframes")

    def test_unsupported_capabilities(self):
        """Test that expected capabilities are unsupported."""
        skill = EditSkill()
        assert not skill.is_supported("openfx")
        assert not skill.is_supported("transitions")

    def test_get_capability(self):
        """Test getting a specific capability."""
        skill = EditSkill()
        cap = skill.get_capability("create_timeline")
        assert cap is not None
        assert cap.status == CapabilityStatus.SUPPORTED
        assert len(cap.mcp_tools) > 0

    def test_report(self):
        """Test generating a report."""
        skill = EditSkill()
        report = skill.report()
        assert "Edit" in report
        assert "EDIT" in report
        assert "Supported Operations" in report


class TestColorSkill:
    """Tests for ColorSkill."""

    def test_page_name(self):
        """Test page name is set correctly."""
        skill = ColorSkill()
        assert skill.PAGE_NAME == "color"
        assert skill.SKILL_NAME == "Color"

    def test_supported_capabilities(self):
        """Test that expected capabilities are supported."""
        skill = ColorSkill()
        assert skill.is_supported("add_node")
        assert skill.is_supported("apply_lut")
        assert skill.is_supported("color_wheels")
        assert skill.is_supported("copy_grade")

    def test_unsupported_capabilities(self):
        """Test that expected capabilities are unsupported."""
        skill = ColorSkill()
        assert not skill.is_supported("curves")
        assert not skill.is_supported("windows")
        assert not skill.is_supported("tracker")


class TestFairlightSkill:
    """Tests for FairlightSkill."""

    def test_page_name(self):
        """Test page name is set correctly."""
        skill = FairlightSkill()
        assert skill.PAGE_NAME == "fairlight"
        assert skill.SKILL_NAME == "Fairlight"

    def test_partial_capabilities(self):
        """Test that clip audio is partial."""
        skill = FairlightSkill()
        # These are partial (via Edit tools)
        assert skill.is_supported("clip_volume")
        assert skill.is_supported("clip_pan")

        # Check status is PARTIAL
        cap = skill.get_capability("clip_volume")
        assert cap.status == CapabilityStatus.PARTIAL

    def test_unsupported_capabilities(self):
        """Test that track-level features are unsupported."""
        skill = FairlightSkill()
        assert not skill.is_supported("track_volume")
        assert not skill.is_supported("eq")
        assert not skill.is_supported("dynamics")
        assert not skill.is_supported("automation")

    def test_limitations_summary(self):
        """Test getting limitations summary."""
        skill = FairlightSkill()
        summary = skill.get_limitations_summary()
        assert "LIMITATIONS" in summary
        assert "DOES NOT WORK" in summary


class TestFusionSkill:
    """Tests for FusionSkill."""

    def test_page_name(self):
        """Test page name is set correctly."""
        skill = FusionSkill()
        assert skill.PAGE_NAME == "fusion"
        assert skill.SKILL_NAME == "Fusion"

    def test_all_unsupported(self):
        """Test that all Fusion capabilities are unsupported."""
        skill = FusionSkill()

        # No supported capabilities
        supported = skill.get_supported_capabilities()
        assert len(supported) == 0

        # All capabilities are unsupported
        unsupported = skill.get_unsupported_capabilities()
        assert len(unsupported) > 0

        # Specific checks
        assert not skill.is_supported("create_node")
        assert not skill.is_supported("text_plus")
        assert not skill.is_supported("particles")

    def test_limitations_summary(self):
        """Test getting limitations summary."""
        skill = FusionSkill()
        summary = skill.get_limitations_summary()
        assert "NO Fusion support" in summary


class TestGetAllSkills:
    """Tests for get_all_skills helper."""

    def test_returns_all_skills(self):
        """Test that all skills are returned."""
        skills = get_all_skills()
        assert len(skills) == 4

        # Check skill types
        skill_types = [type(s).__name__ for s in skills]
        assert "EditSkill" in skill_types
        assert "ColorSkill" in skill_types
        assert "FairlightSkill" in skill_types
        assert "FusionSkill" in skill_types


class TestGenerateCapabilitiesReport:
    """Tests for generate_capabilities_report function."""

    def test_report_generation(self):
        """Test that report is generated."""
        report = generate_capabilities_report()
        assert "CAPABILITIES REPORT" in report

    def test_report_contains_summary(self):
        """Test that report contains summary."""
        report = generate_capabilities_report()
        assert "SUMMARY" in report
        assert "Fully Supported" in report
        assert "Partially Supported" in report
        assert "Unsupported" in report

    def test_report_contains_all_pages(self):
        """Test that report contains all pages."""
        report = generate_capabilities_report()
        assert "EDIT" in report
        assert "COLOR" in report
        assert "FAIRLIGHT" in report
        assert "FUSION" in report

    def test_report_contains_legend(self):
        """Test that report contains legend."""
        report = generate_capabilities_report()
        assert "LEGEND" in report
        assert "[+]" in report
        assert "[~]" in report
        assert "[-]" in report


class TestSkillApply:
    """Tests for skill apply methods."""

    def test_edit_apply_no_resolve(self):
        """Test Edit skill apply without Resolve connection."""
        skill = EditSkill()

        # Create a mock plan with no data
        class MockPlan:
            clips = []
            markers = []
            transitions = []

        results = skill.apply(MockPlan(), None)
        assert "[FAIL] No Resolve connection" in results

    def test_color_apply_no_resolve(self):
        """Test Color skill apply without Resolve connection."""
        skill = ColorSkill()

        class MockPlan:
            grade = None

        results = skill.apply(MockPlan(), None)
        assert "[FAIL] No Resolve connection" in results

    def test_fairlight_apply_no_resolve(self):
        """Test Fairlight skill apply without Resolve connection."""
        skill = FairlightSkill()

        class MockPlan:
            audio = []
            audio_eq = None
            audio_dynamics = None
            audio_automation = None

        results = skill.apply(MockPlan(), None)
        assert "[FAIL] No Resolve connection" in results

    def test_fusion_apply_warns(self):
        """Test Fusion skill apply warns about no support."""
        skill = FusionSkill()

        class MockPlan:
            fusion = None
            titles = None
            effects = None

        results = skill.apply(MockPlan(), None)
        assert any("No MCP support" in r for r in results)
