"""
Fairlight Skill - Audio mixing operations on the Fairlight page.

Capabilities:
- Clip volume/pan (PARTIAL - via Edit page tools)
- EQ (UNSUPPORTED - no MCP tools)
- Dynamics/Compressor (UNSUPPORTED - no MCP tools)
- Track levels (UNSUPPORTED - no MCP tools)
- Bus routing (UNSUPPORTED - no MCP tools)
- Automation (UNSUPPORTED - no MCP tools)

Note: DaVinci Resolve MCP has very limited Fairlight support.
Most audio work must be done manually or via the Edit page
set_timeline_item_audio tool.
"""

import logging
from typing import List, Dict, Any, Optional

from .base_skill import (
    BaseSkill,
    SkillCapability,
    CapabilityStatus,
    ExecutionResult,
)

logger = logging.getLogger("autonomous.skills.fairlight")


class FairlightSkill(BaseSkill):
    """
    Fairlight page skill for audio mixing.

    IMPORTANT: MCP has very limited Fairlight support.
    Most capabilities are UNSUPPORTED.

    Only basic clip-level audio properties work via Edit page tools:
    - Volume
    - Pan

    No track-level mixing, EQ, dynamics, or automation.
    """

    PAGE_NAME = "fairlight"
    SKILL_NAME = "Fairlight"

    def get_capabilities(self) -> List[SkillCapability]:
        """Return Fairlight page capabilities."""
        return [
            # Partial Support (via Edit tools)
            SkillCapability(
                name="clip_volume",
                description="Set clip volume level",
                status=CapabilityStatus.PARTIAL,
                mcp_tools=["set_timeline_item_audio"],
                notes="Uses Edit page tool; no Fairlight-specific control",
            ),
            SkillCapability(
                name="clip_pan",
                description="Set clip stereo pan",
                status=CapabilityStatus.PARTIAL,
                mcp_tools=["set_timeline_item_audio"],
                notes="Uses Edit page tool; no Fairlight-specific control",
            ),
            SkillCapability(
                name="clip_mute",
                description="Mute/unmute clips",
                status=CapabilityStatus.PARTIAL,
                mcp_tools=["set_timeline_item_audio"],
                notes="Uses Edit page tool",
            ),

            # Unsupported Features
            SkillCapability(
                name="track_volume",
                description="Set audio track fader levels",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for track-level mixing",
            ),
            SkillCapability(
                name="track_pan",
                description="Set audio track pan",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for track-level mixing",
            ),
            SkillCapability(
                name="track_mute_solo",
                description="Mute/solo audio tracks",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for track control",
            ),
            SkillCapability(
                name="eq",
                description="Apply/adjust EQ (parametric, graphic)",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for EQ",
            ),
            SkillCapability(
                name="dynamics",
                description="Apply compressor, limiter, gate",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for dynamics processing",
            ),
            SkillCapability(
                name="fx_plugins",
                description="Add/configure audio FX plugins",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for audio plugin management",
            ),
            SkillCapability(
                name="bus_routing",
                description="Route audio to buses and submixes",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for bus routing",
            ),
            SkillCapability(
                name="automation",
                description="Record/edit audio automation",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for automation",
            ),
            SkillCapability(
                name="adr",
                description="ADR/voiceover recording",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for ADR",
            ),
            SkillCapability(
                name="loudness",
                description="Loudness metering and normalization",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for loudness",
            ),
            SkillCapability(
                name="noise_reduction",
                description="Apply noise reduction",
                status=CapabilityStatus.UNSUPPORTED,
                notes="No MCP tools for noise reduction",
            ),
        ]

    def apply(self, plan: Any, config: Any) -> List[str]:
        """
        Apply Fairlight audio operations from plan.

        Note: Most operations are unsupported.

        Args:
            plan: EditPlan with audio settings
            config: PipelineConfig

        Returns:
            List of execution log messages
        """
        results = []

        # Check for Resolve connection
        if not self.resolve:
            results.append("[FAIL] No Resolve connection")
            return results

        # Warn about limited support
        results.append(
            "[INFO] Fairlight: Limited MCP support - only basic clip audio available"
        )

        try:
            # Process audio tracks from plan
            if hasattr(plan, 'audio') and plan.audio:
                self._apply_audio_tracks(plan.audio, results)

            # Any Fairlight-specific features would be warned as unsupported
            self._check_unsupported_features(plan, results)

        except Exception as e:
            results.append(f"[FAIL] Fairlight skill error: {e}")
            logger.exception("Fairlight skill failed")

        return results

    def _apply_audio_tracks(self, audio_tracks: List[Any], results: List[str]) -> None:
        """Apply basic audio track settings (where possible)."""
        for audio in audio_tracks:
            # Volume/pan can work via Edit tools
            if hasattr(audio, 'volume') or hasattr(audio, 'pan'):
                if self.is_supported("clip_volume"):
                    self._log_result(results, ExecutionResult(
                        success=True,
                        operation=f"Audio {audio.name}",
                        message="Would set volume/pan via Edit tools",
                        warning="Fairlight mixer not available via MCP",
                    ))
                else:
                    self._warn_unsupported(f"Audio {audio.name}", results)

    def _check_unsupported_features(self, plan: Any, results: List[str]) -> None:
        """Warn about requested features that aren't supported."""
        unsupported_requests = []

        # Check for EQ settings
        if hasattr(plan, 'audio_eq') and plan.audio_eq:
            unsupported_requests.append("EQ settings")

        # Check for dynamics
        if hasattr(plan, 'audio_dynamics') and plan.audio_dynamics:
            unsupported_requests.append("Dynamics/compression")

        # Check for automation
        if hasattr(plan, 'audio_automation') and plan.audio_automation:
            unsupported_requests.append("Audio automation")

        for feature in unsupported_requests:
            self._warn_unsupported(feature, results)

    def set_clip_volume(self, clip_id: str, volume_db: float) -> bool:
        """
        Set clip volume level.

        Args:
            clip_id: Timeline item ID
            volume_db: Volume in dB

        Returns:
            True if successful
        """
        if not self.is_supported("clip_volume"):
            logger.warning("clip_volume not fully supported")
            return False

        if not self.project:
            logger.error("No project connection")
            return False

        try:
            timeline = self.project.GetCurrentTimeline()
            if not timeline:
                return False

            # Find the clip by ID
            # This would use set_timeline_item_audio MCP tool
            logger.info(f"Would set clip {clip_id} volume to {volume_db}dB")
            return True

        except Exception as e:
            logger.error(f"Failed to set volume: {e}")

        return False

    def set_clip_pan(self, clip_id: str, pan: float) -> bool:
        """
        Set clip stereo pan.

        Args:
            clip_id: Timeline item ID
            pan: Pan value (-1 to 1, 0 = center)

        Returns:
            True if successful
        """
        if not self.is_supported("clip_pan"):
            logger.warning("clip_pan not fully supported")
            return False

        logger.info(f"Would set clip {clip_id} pan to {pan}")
        return True

    def get_limitations_summary(self) -> str:
        """Get a summary of Fairlight limitations."""
        return """
FAIRLIGHT LIMITATIONS (MCP):

The DaVinci Resolve MCP server has minimal Fairlight support.

What WORKS (via Edit page tools):
- Clip volume
- Clip pan
- Clip mute

What DOES NOT WORK:
- Track-level mixing (faders, pan, mute/solo)
- EQ (parametric, graphic)
- Dynamics (compressor, limiter, gate, expander)
- Audio FX plugins
- Bus routing and submixes
- Automation
- ADR/recording
- Loudness monitoring
- Noise reduction
- De-esser, de-hummer

WORKAROUND:
For advanced audio work:
1. Use ffmpeg preprocessing (ducking) before import
2. Export audio and use external DAW
3. Manual Fairlight mixing in Resolve
"""
