"""Universal MCP Tool Execution Lifecycle and Hook Pipeline.

Provides a pluggable, server-wide lifecycle middleware for all compound MCP tools.
Every tool invocation (synchronous or asynchronous) passes through three distinct
lifecycle phases:

  1. Pre-flight (run_before):
     - Risk classification and blast radius calculation (low -> critical)
     - Resolve state inspection (pre-flight timeline duration, track count, project)
     - Safe dry-run simulation interception for non-native dry-run actions
  2. Execution / Error tracking (run_on_error):
     - Catches exceptions, records duration, informs error observers
  3. Post-flight (run_after):
     - Readback verification and contradiction evaluation
     - State drift detection (unintended timeline duration/structure shifts)
     - Correlated execution trace aggregation
"""

from __future__ import annotations

import enum
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("resolve-mcp.execution-lifecycle")


class RiskLevel(str, enum.Enum):
    """Categorized risk level for tool operations."""
    LOW = "low"            # Read-only queries, info probes, status checks
    MEDIUM = "medium"      # Reversible edits, markers, non-destructive properties
    HIGH = "high"          # Deletions, ripples, timeline restructuring, batch edits
    CRITICAL = "critical"  # Project deletion, database resets, permanent loss


class BlastRadius(str, enum.Enum):
    """Scope of impact when an operation executes."""
    ITEM = "item"          # Single clip, single marker, node
    TRACK = "track"        # Single track or stem
    TIMELINE = "timeline"  # Entire active timeline
    PROJECT = "project"    # Entire Resolve project or Media Pool
    SYSTEM = "system"      # System preferences, filesystem, host process


@dataclass
class RiskAssessment:
    """Calculated risk evaluation for a tool action."""
    level: RiskLevel = RiskLevel.LOW
    destructive: bool = False
    blast_radius: BlastRadius = BlastRadius.ITEM
    confirmation_required: bool = False
    snapshot_available: bool = False
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "destructive": self.destructive,
            "blast_radius": self.blast_radius.value,
            "confirmation_required": self.confirmation_required,
            "snapshot_available": self.snapshot_available,
            "reasons": list(self.reasons),
        }


@dataclass
class ToolCallContext:
    """Contextual metadata describing an in-flight tool invocation."""
    tool_name: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    execution_id: Optional[str] = None
    risk: RiskAssessment = field(default_factory=RiskAssessment)
    pre_state: Optional[Dict[str, Any]] = None
    post_state: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HookDecision:
    """Decision returned by a pre-flight hook."""
    proceed: bool = True
    short_circuit_result: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


class LifecycleHook:
    """Base class for all MCP tool lifecycle hooks."""
    name: str = "base_hook"
    enabled: bool = True

    def before_tool_call(self, ctx: ToolCallContext) -> Optional[HookDecision]:
        """Runs before tool invocation. Can short-circuit or modify context."""
        return None

    def after_tool_call(
        self, ctx: ToolCallContext, result: Any, duration_ms: int
    ) -> Optional[Dict[str, Any]]:
        """Runs after successful tool execution. Can enrich result or emit telemetry."""
        return None

    def on_error(
        self, ctx: ToolCallContext, exc: Exception, duration_ms: int
    ) -> None:
        """Runs when tool execution raises an unhandled exception."""
        pass


# ─── Built-in Hook Implementations ──────────────────────────────────────────


class RiskClassificationHook(LifecycleHook):
    """Evaluates tool + action + params to classify danger level and blast radius."""
    name = "risk_classification"

    _CRITICAL_ACTIONS: Set[Tuple[str, str]] = {
        ("project_manager", "delete_project"),
        ("project_manager", "close_project_without_saving"),
        ("media_pool", "delete_timelines"),
        ("media_pool", "delete_clips"),
    }

    _HIGH_RISK_ACTIONS: Set[Tuple[str, str]] = {
        ("timeline", "delete_clips"),
        ("timeline", "delete_clip_by_id"),
        ("timeline", "delete_markers"),
        ("timeline", "ripple_delete"),
        ("timeline", "cut_clip"),
        ("edit_engine", "execute_selects"),
        ("edit_engine", "auto_cut_silence"),
        ("edit_engine", "ripple_trim"),
        ("project_manager", "save_project_as"),
    }

    _READ_ONLY_PREFIXES = ("get_", "list_", "query_", "probe_", "inspect_", "export_", "check_")

    @classmethod
    def classify(cls, tool_name: str, action: str, params: Dict[str, Any]) -> RiskAssessment:
        reasons: List[str] = []
        destructive = False
        level = RiskLevel.LOW
        radius = BlastRadius.ITEM
        conf_required = False

        pair = (tool_name, action)

        if pair in cls._CRITICAL_ACTIONS:
            level = RiskLevel.CRITICAL
            destructive = True
            radius = BlastRadius.PROJECT if "project" in tool_name else BlastRadius.TIMELINE
            conf_required = True
            reasons.append(f"Action '{action}' is permanently destructive across {radius.value}")
        elif pair in cls._HIGH_RISK_ACTIONS or action.startswith("delete_") or action.startswith("remove_"):
            level = RiskLevel.HIGH
            destructive = True
            if params.get("ripple", False):
                radius = BlastRadius.TIMELINE
                reasons.append("Ripple mode alters downstream timeline synchronization")
            else:
                radius = BlastRadius.ITEM
            conf_required = True
            reasons.append(f"Destructive timeline edit: {action}")
        elif any(action.startswith(p) for p in cls._READ_ONLY_PREFIXES) or action in {"read", "status", "info"}:
            level = RiskLevel.LOW
            destructive = False
            radius = BlastRadius.ITEM
        else:
            # General mutation
            level = RiskLevel.MEDIUM
            destructive = action.startswith("reset_") or action.startswith("clear_")
            radius = BlastRadius.ITEM

        return RiskAssessment(
            level=level,
            destructive=destructive,
            blast_radius=radius,
            confirmation_required=conf_required,
            snapshot_available=False,
            reasons=reasons,
        )

    def before_tool_call(self, ctx: ToolCallContext) -> Optional[HookDecision]:
        ctx.risk = self.classify(ctx.tool_name, ctx.action, ctx.params)
        return None


class ResolveStateInspectionHook(LifecycleHook):
    """Captures pre-flight Resolve project and timeline state non-blockingly."""
    name = "resolve_state_inspection"

    def __init__(self, state_provider: Optional[Callable[[], Optional[Dict[str, Any]]]] = None):
        self._state_provider = state_provider

    def before_tool_call(self, ctx: ToolCallContext) -> Optional[HookDecision]:
        if self._state_provider is None:
            return None
        try:
            state = self._state_provider()
            if state:
                ctx.pre_state = state
                ctx.risk.snapshot_available = True
        except Exception as exc:
            logger.debug(f"Pre-flight state inspection skipped: {exc}")
        return None


class DryRunInterceptionHook(LifecycleHook):
    """Intercepts dry_run requests for operations that lack native dry-run support.

    Allows AI agents to safely simulate the impact, risk, and blast radius of any
    Resolve tool action without executing destructive modifications.
    """
    name = "dry_run_interception"

    # Actions that already implement their own internal dry-run logic
    NATIVE_DRY_RUN_ACTIONS: Set[Tuple[str, str]] = {
        ("timeline", "ripple_insert"),
        ("timeline", "apply_edit_plan"),
        ("edit_engine", "preview_selects"),
        ("media_pool", "import_media"),
    }

    def before_tool_call(self, ctx: ToolCallContext) -> Optional[HookDecision]:
        params = ctx.params
        if not isinstance(params, dict):
            return None

        is_dry_run = params.get("dry_run") is True or params.get("dryRun") is True
        if not is_dry_run:
            return None

        pair = (ctx.tool_name, ctx.action)
        if pair in self.NATIVE_DRY_RUN_ACTIONS:
            # Let the native tool handler perform its specific simulation
            return None

        # Short-circuit simulation for all non-native dry-run operations
        simulated_response = {
            "success": True,
            "dry_run": True,
            "simulated": True,
            "tool": ctx.tool_name,
            "action": ctx.action,
            "operation": f"{ctx.tool_name}.{ctx.action}",
            "risk": ctx.risk.to_dict(),
            "blast_radius": ctx.risk.blast_radius.value,
            "params_submitted": {k: v for k, v in params.items() if k not in {"dry_run", "dryRun"}},
            "pre_state": ctx.pre_state or {},
            "impact_summary": (
                f"Simulated {ctx.action} on {ctx.tool_name}. "
                f"Risk: {ctx.risk.level.value.upper()}. "
                f"Destructive: {ctx.risk.destructive}. "
                f"Blast Radius: {ctx.risk.blast_radius.value}."
            ),
        }
        return HookDecision(proceed=False, short_circuit_result=simulated_response)


class ReadbackVerificationHook(LifecycleHook):
    """Evaluates readback verification data attached to operation results."""
    name = "readback_verification"

    def after_tool_call(
        self, ctx: ToolCallContext, result: Any, duration_ms: int
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(result, dict):
            return None

        # Check if result carries a verification block
        verif = result.get("verification")
        if isinstance(verif, dict):
            contradiction = verif.get("contradiction", False)
            verified = verif.get("verified", False)
            if contradiction:
                logger.warning(
                    f"Readback contradiction detected on {ctx.tool_name}.{ctx.action}: {verif}"
                )
            return {
                "readback_checked": True,
                "verified": verified,
                "contradiction": contradiction,
            }

        # Track unverified destructive operations
        if ctx.risk.destructive and "verification" not in result:
            return {
                "readback_checked": False,
                "status": "unverified",
                "notice": f"Destructive operation {ctx.tool_name}.{ctx.action} completed without readback verification",
            }
        return None


class DriftDetectionHook(LifecycleHook):
    """Detects unexpected timeline duration or track structure drift."""
    name = "drift_detection"

    _DURATION_ALTERING_ACTIONS = {
        "ripple_delete", "ripple_insert", "auto_cut_silence", "execute_selects",
        "delete_clips", "cut_clip", "delete_item", "ripple_trim"
    }

    def __init__(self, state_provider: Optional[Callable[[], Optional[Dict[str, Any]]]] = None):
        self._state_provider = state_provider

    def after_tool_call(
        self, ctx: ToolCallContext, result: Any, duration_ms: int
    ) -> Optional[Dict[str, Any]]:
        if not ctx.pre_state or self._state_provider is None:
            return None

        try:
            post_state = self._state_provider()
            if not post_state:
                return None
            ctx.post_state = post_state

            pre_dur = ctx.pre_state.get("duration_frames")
            post_dur = post_state.get("duration_frames")

            # Check if duration changed on a non-duration-altering action
            if (
                pre_dur is not None
                and post_dur is not None
                and pre_dur != post_dur
                and ctx.action not in self._DURATION_ALTERING_ACTIONS
            ):
                warning = (
                    f"Timeline duration drifted unexpectedly from {pre_dur} to {post_dur} frames "
                    f"during non-duration altering action '{ctx.action}'"
                )
                logger.warning(warning)
                return {
                    "drift_detected": True,
                    "drift_warnings": [warning],
                    "duration_delta_frames": post_dur - pre_dur,
                }
        except Exception as exc:
            logger.debug(f"Drift detection evaluation skipped: {exc}")
        return None


class ProvenanceTraceHook(LifecycleHook):
    """Correlates tool lifecycle events into the active execution trace."""
    name = "provenance_trace"

    def after_tool_call(
        self, ctx: ToolCallContext, result: Any, duration_ms: int
    ) -> Optional[Dict[str, Any]]:
        return {
            "execution_id": ctx.execution_id,
            "duration_ms": duration_ms,
            "risk_level": ctx.risk.level.value,
        }


# ─── Pipeline Coordinator ───────────────────────────────────────────────────


class LifecyclePipeline:
    """Thread-safe coordinator running registered lifecycle hooks."""

    def __init__(self):
        self._hooks: List[LifecycleHook] = []
        self._lock = threading.RLock()
        self._register_default_hooks()

    def _register_default_hooks(self):
        self._hooks.append(RiskClassificationHook())
        self._hooks.append(ResolveStateInspectionHook())
        self._hooks.append(DryRunInterceptionHook())
        self._hooks.append(ReadbackVerificationHook())
        self._hooks.append(DriftDetectionHook())
        self._hooks.append(ProvenanceTraceHook())

    def register_hook(self, hook: LifecycleHook) -> None:
        with self._lock:
            # Replace existing hook with same name if present
            self._hooks = [h for h in self._hooks if h.name != hook.name]
            self._hooks.append(hook)

    def set_state_provider(self, provider: Callable[[], Optional[Dict[str, Any]]]) -> None:
        """Configures state provider callable on inspection and drift hooks."""
        with self._lock:
            for hook in self._hooks:
                if isinstance(hook, (ResolveStateInspectionHook, DriftDetectionHook)):
                    hook._state_provider = provider

    def run_before(self, ctx: ToolCallContext) -> HookDecision:
        with self._lock:
            hooks = list(self._hooks)

        for hook in hooks:
            if not hook.enabled:
                continue
            try:
                decision = hook.before_tool_call(ctx)
                if decision and not decision.proceed:
                    return decision
            except Exception as exc:
                logger.error(f"Error in hook '{hook.name}.before_tool_call': {exc}", exc_info=True)
        return HookDecision(proceed=True)

    def run_after(self, ctx: ToolCallContext, result: Any, duration_ms: int) -> Any:
        with self._lock:
            hooks = list(self._hooks)

        contributions: Dict[str, Any] = {}
        for hook in hooks:
            if not hook.enabled:
                continue
            try:
                contrib = hook.after_tool_call(ctx, result, duration_ms)
                if contrib and isinstance(contrib, dict):
                    contributions[hook.name] = contrib
            except Exception as exc:
                logger.error(f"Error in hook '{hook.name}.after_tool_call': {exc}", exc_info=True)

        # Attach telemetry into operation envelope or result if it's a dict
        if isinstance(result, dict) and contributions:
            if "_operation" in result and isinstance(result["_operation"], dict):
                result["_operation"].setdefault("lifecycle", {}).update(contributions)
        return result

    def run_on_error(self, ctx: ToolCallContext, exc: Exception, duration_ms: int) -> None:
        with self._lock:
            hooks = list(self._hooks)

        for hook in hooks:
            if not hook.enabled:
                continue
            try:
                hook.on_error(ctx, exc, duration_ms)
            except Exception as hook_exc:
                logger.error(f"Error in hook '{hook.name}.on_error': {hook_exc}", exc_info=True)

    def list_hooks(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": h.name,
                    "enabled": h.enabled,
                    "class": h.__class__.__name__,
                }
                for h in self._hooks
            ]

    def inspect_operation(
        self, tool_name: str, action: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Inspects pre-flight risk, blast radius, and state before execution."""
        p = params or {}
        assessment = RiskClassificationHook.classify(tool_name, action, p)
        pre_state = None
        for hook in self._hooks:
            if isinstance(hook, ResolveStateInspectionHook) and hook._state_provider:
                try:
                    pre_state = hook._state_provider()
                except Exception:
                    pass
                break

        return {
            "success": True,
            "tool": tool_name,
            "action": action,
            "risk": assessment.to_dict(),
            "destructive": assessment.destructive,
            "blast_radius": assessment.blast_radius.value,
            "confirmation_required": assessment.confirmation_required,
            "snapshot_available": assessment.snapshot_available or (pre_state is not None),
            "reasons": assessment.reasons,
            "pre_state": pre_state,
        }


# Global singleton pipeline
_GLOBAL_PIPELINE = LifecyclePipeline()


def get_lifecycle_pipeline() -> LifecyclePipeline:
    return _GLOBAL_PIPELINE


def inspect_operation(
    tool_name: str, action: str, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    return _GLOBAL_PIPELINE.inspect_operation(tool_name, action, params)


def list_lifecycle_hooks() -> List[Dict[str, Any]]:
    return _GLOBAL_PIPELINE.list_hooks()


def classify_operation_risk(
    tool_name: str, action: str, params: Optional[Dict[str, Any]] = None
) -> RiskAssessment:
    return RiskClassificationHook.classify(tool_name, action, params or {})

