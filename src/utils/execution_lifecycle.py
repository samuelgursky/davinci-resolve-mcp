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
    LOW = "low"            # Read-only queries, info probes, and known-reversible edits
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
    #: None = not determined. The classifier reads action names; it does not
    #: know whether timeline_versioning would archive a predecessor, and False
    #: would assert "no rollback" as a finding it never made.
    snapshot_available: Optional[bool] = None
    #: False when no rule matched, i.e. the fields below are name-based
    #: defaults rather than an assessment of this specific operation.
    recognised: bool = True
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "destructive": self.destructive,
            "blast_radius": self.blast_radius.value,
            "confirmation_required": self.confirmation_required,
            "snapshot_available": self.snapshot_available,
            "recognised": self.recognised,
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
        ("media_pool", "delete_folders"),
        ("timeline", "delete_track"),
        ("timeline", "lift_range"),
        ("timeline", "overwrite_range"),
        ("timeline", "apply_cuts"),
        ("graph", "reset_all_grades"),
        # Plan execution: each rebuilds the timeline from the plan's lifts and
        # keep_ranges. Same shape as execute_selects and ripple_trim above.
        ("edit_engine", "execute_tighten"),
        ("edit_engine", "execute_swap"),
        ("edit_engine", "execute_silence_ripple"),
        # Restructuring. move_clips passes delete_sources=True, so the originals
        # are removed; ripple_insert shifts everything downstream of the insert;
        # compound/fusion clips replace the selected items with a container and
        # rewire what the timeline points at.
        ("timeline", "move_clips"),
        ("timeline", "ripple_insert"),
        ("timeline", "create_compound_clip"),
        ("timeline", "create_fusion_clip"),
        # ImportIntoTimeline lays an external edit over the timeline;
        # ConvertTimelineToStereo rewrites the audio track layout and has no
        # inverse; DetectSceneCuts cuts every clip it decides to cut.
        ("timeline", "import_into_timeline"),
        ("timeline", "convert_to_stereo"),
        ("timeline_ai", "detect_scene_cuts"),
        # Grades that are replaced wholesale. apply_grade_from_drx documents
        # itself as replacing the entire node graph with no append mode;
        # CopyGrades overwrites each target's grade.
        ("graph", "apply_grade_from_drx"),
        ("timeline_item_color", "copy_grades"),
        # Takes. delete removes one; finalize collapses the item to the selected
        # take and discards the rest.
        ("timeline_item_takes", "delete"),
        ("timeline_item_takes", "finalize"),
        # The only action here that writes OUTSIDE the project: UpdateSidecar
        # rewrites the .braw sidecar or R3D .RMD file next to the camera
        # original. No Resolve undo reaches it, and it changes how that media
        # is interpreted by every other application that reads it.
        ("timeline_item", "update_sidecar"),
    }

    #: Mutating, but bounded and trivially reversible — a marker, a clip colour,
    #: a toggle, or a newly created empty container. Nothing that already exists
    #: is altered or removed, and the inverse is a single action.
    #:
    #: Without this table the name heuristic files them under MEDIUM and flags
    #: them unrecognised, i.e. it warns that the risk is unestablished for the
    #: actions whose risk is the best established of any we dispatch.
    _LOW_RISK_ACTIONS: Set[Tuple[str, str]] = {
        ("timeline_markers", "add"),
        ("timeline_markers", "update_custom_data"),
        ("timeline_item_markers", "add"),
        ("timeline_item_markers", "add_flag"),
        ("timeline_item_markers", "clear_flags"),
        ("timeline_item_markers", "set_clip_color"),
        ("timeline_item_markers", "clear_clip_color"),
        ("timeline_item_markers", "update_custom_data"),
        # Marks and flags: metadata on a clip, no frames touched.
        ("timeline", "set_mark_in_out"),
        ("timeline", "clear_mark_in_out"),
        ("media_pool", "set_clip_marks"),
        ("media_pool", "clear_clip_marks"),
        # Track-level toggles and labels. SetTrackEnable/SetTrackLock/SetTrackName
        # change no content; add_track creates an empty container.
        ("timeline", "add_track"),
        ("timeline", "set_track_enable"),
        ("timeline", "set_track_lock"),
        ("timeline", "set_track_name"),
        ("timeline", "set_clips_linked"),
        ("timeline", "set_title_text"),
        # DuplicateTimeline writes a new timeline; the original is untouched.
        ("timeline", "duplicate"),
        # CreateEmptyTimeline / CreateStereoClip only add. `create_timeline`'s
        # if_exists policy is version/reuse/fail — it has no overwrite path, so
        # it cannot replace an existing timeline.
        ("media_pool", "create_timeline"),
        ("media_pool", "create_timeline_from_clips"),
        ("media_pool", "create_stereo_clip"),
        # Per-item display properties: set them back and the item is as it was.
        ("timeline_item", "set_clip_enabled"),
        ("timeline_item", "set_name"),
        ("timeline_item", "set_crop"),
        ("timeline_item", "set_transform"),
        ("timeline_item", "set_composite"),
        ("timeline_item", "set_audio"),
        # Cache toggles and node *labels* — not grades.
        ("timeline_item_color", "set_color_cache"),
        ("timeline_item_color", "set_fusion_cache"),
        ("timeline_item_color", "reset_all_node_colors"),
        ("timeline_item_color", "rename_version"),
        ("timeline_item_fusion", "add_comp"),
        ("timeline_item_fusion", "rename_comp"),
        ("timeline_item_takes", "add"),
        ("timeline_item_takes", "select"),
        ("graph", "set_node_enabled"),
    }

    #: A real assessment landing between LOW and HIGH: existing content or
    #: settings are altered, recovery is possible but is not one trivial
    #: inverse. This table exists so that MEDIUM can mean something — before it,
    #: MEDIUM was overwhelmingly the `else` fallthrough, which made an assessed
    #: MEDIUM and an unrated action indistinguishable by level alone.
    _MEDIUM_RISK_ACTIONS: Set[Tuple[str, str]] = {
        # Additive edits that place content into an existing timeline. Nothing
        # is deleted (`overwrite_range`, which does delete, is HIGH), but the
        # timeline is no longer what it was.
        ("timeline", "copy_clips"),
        ("timeline", "duplicate_clips"),
        ("timeline", "copy_range"),
        ("timeline", "duplicate_range"),
        ("timeline", "insert_generator"),
        ("timeline", "insert_title"),
        ("timeline", "insert_fusion_generator"),
        ("timeline", "insert_fusion_title"),
        ("timeline", "insert_fusion_composition"),
        ("timeline", "insert_ofx_generator"),
        ("media_pool", "append_to_timeline"),
        # Timeline-wide settings. No content lost, but a wrong start timecode
        # silently invalidates every conform and reference built against it.
        ("timeline", "set_setting"),
        ("timeline", "set_start_timecode"),
        ("timeline", "set_voice_isolation_state"),
        ("timeline_item", "set_voice_isolation_state"),
        # `set_property` takes an arbitrary key/value, so its blast radius is
        # whatever the caller passed; `set_retime` changes duration and sync.
        ("timeline_item", "set_property"),
        ("timeline_item", "set_retime"),
        # Pool reorganisation: clips and bins move, nothing is destroyed, but
        # paths other work depends on change underneath it.
        ("media_pool", "move_clips"),
        ("media_pool", "move_folders"),
        ("media_pool", "auto_sync_audio"),
        ("media_pool", "setup_multicam_timeline"),
        # Analysis passes that write their results back onto the timeline.
        ("timeline_ai", "create_subtitles"),
        ("timeline_ai", "analyze_dolby_vision"),
        # Grade state that is replaced rather than removed. AddVersion also
        # switches the active version, so a later graph write lands on the new
        # one — the reason a "pre-change" backup version can end up holding the
        # post-change grade.
        ("timeline_item_color", "add_version"),
        ("timeline_item_color", "load_version"),
        ("timeline_item_color", "set_cdl"),
        ("timeline_item_color", "assign_color_group"),
        ("timeline_item_color", "stabilize"),
        ("timeline_item_color", "smart_reframe"),
        ("timeline_item_color", "create_magic_mask"),
        ("timeline_item_color", "regenerate_magic_mask"),
        # Importing or switching the active comp changes what renders.
        ("timeline_item_fusion", "import_comp"),
        ("timeline_item_fusion", "load_comp"),
    }

    #: Raw graph LUT writes. Their level follows the graph they target (see
    #: `_graph_scope`): MEDIUM on one item, HIGH on the timeline graph (the
    #: tool's DEFAULT) or a color-group graph, where one call restyles every
    #: clip on the timeline or in the group. Adapted from PR #192.
    _GRAPH_LUT_ACTIONS: Set[Tuple[str, str]] = {
        ("graph", "set_lut"),
        ("graph", "apply_arri_cdl_lut"),
    }

    @staticmethod
    def _graph_scope(params: Dict[str, Any]) -> Tuple["BlastRadius", str]:
        """Blast radius of a `graph` tool call, from its `source` param.

        The graph tool resolves `source` as "timeline" (default) ->
        Timeline.GetNodeGraph(), "item" -> TimelineItem.GetNodeGraph(), and
        "color_group_pre"/"color_group_post" -> the group's pre/post clip
        graph. Every graph mutation — LUT, DRX apply, reset, node toggle —
        lands on whichever graph that names, so the scope is a property of
        the call, not of the action, and a rating that says "item" for a
        reset of a color-group graph is wrong by the size of the group.
        """
        source = str(params.get("source") or "timeline")
        if source == "item":
            return BlastRadius.ITEM, "one timeline item's graph"
        if source in {"color_group_pre", "color_group_post"}:
            return (
                BlastRadius.PROJECT,
                f"a color group's {source} graph (every clip in the group)",
            )
        return BlastRadius.TIMELINE, "the timeline node graph (every clip on the timeline)"

    _READ_ONLY_PREFIXES = ("get_", "list_", "query_", "probe_", "inspect_", "export_", "check_")

    @classmethod
    def classify(cls, tool_name: str, action: str, params: Dict[str, Any]) -> RiskAssessment:
        reasons: List[str] = []
        destructive = False
        level = RiskLevel.LOW
        radius = BlastRadius.ITEM
        conf_required = False
        recognised = True

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
            elif tool_name == "graph":
                radius, scope = cls._graph_scope(params)
                reasons.append(f"Graph target: {scope}")
            else:
                radius = BlastRadius.ITEM
            conf_required = True
            reasons.append(f"Destructive timeline edit: {action}")
        elif pair in cls._GRAPH_LUT_ACTIONS:
            destructive = True
            radius, scope = cls._graph_scope(params)
            if radius is BlastRadius.ITEM:
                level = RiskLevel.MEDIUM
                reasons.append(f"Raw graph LUT write '{action}' is scoped to {scope}")
            else:
                level = RiskLevel.HIGH
                conf_required = True
                reasons.append(f"Raw graph LUT write '{action}' targets {scope}")
        elif pair in cls._LOW_RISK_ACTIONS:
            level = RiskLevel.LOW
            destructive = True
            if tool_name == "graph":
                radius, scope = cls._graph_scope(params)
                reasons.append(f"Graph target: {scope}")
            else:
                radius = BlastRadius.ITEM
            reasons.append(f"Bounded reversible edit: {action}")
        elif pair in cls._MEDIUM_RISK_ACTIONS:
            level = RiskLevel.MEDIUM
            destructive = True
            # Scope follows the tool: the timeline and pool tools act on the
            # timeline or the pool as a whole, the per-item tools on one item.
            radius = (
                BlastRadius.TIMELINE
                if tool_name in {"timeline", "timeline_ai", "edit_engine", "media_pool"}
                else BlastRadius.ITEM
            )
            reasons.append(f"Recoverable edit to existing state: {action}")
        elif any(action.startswith(p) for p in cls._READ_ONLY_PREFIXES) or action in {"read", "status", "info"}:
            level = RiskLevel.LOW
            destructive = False
            radius = BlastRadius.ITEM
        else:
            # Everything the rules do not recognise. This is a heuristic over
            # action NAMES, so "unrecognised" covers both a real action nobody
            # listed and an action that does not exist — and it must not come
            # back as a confident "medium, not destructive". The guard exists
            # for hallucinated calls; answering one with reassurance is the
            # failure it was built to prevent.
            level = RiskLevel.MEDIUM
            destructive = action.startswith("reset_") or action.startswith("clear_")
            radius = BlastRadius.ITEM
            recognised = False
            reasons.append(
                f"'{tool_name}.{action}' matches no risk rule. This assessment is a "
                "name-based default, not a finding — treat the risk as unestablished "
                "and check the tool's own documented behaviour before proceeding."
            )

        return RiskAssessment(
            level=level,
            destructive=destructive,
            blast_radius=radius,
            confirmation_required=conf_required,
            snapshot_available=None,
            reasons=reasons,
            recognised=recognised,
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
        """The hooks that ship enabled. All of them OBSERVE; none short-circuit.

        `HookDecision(proceed=False)` exists so a deliberately registered hook
        can gate a call, and `register_hook` is public for that. Nothing
        shipping uses it, on purpose: a hook that replaces a tool's result is
        answering on behalf of code that never ran.

        The original of this pipeline shipped a dry-run interceptor that did
        exactly that — any `dry_run: true` call outside a four-entry allowlist
        was short-circuited with a synthesised `success: true`. Against 273
        `dry_run` references in `src/server.py` it hijacked actions with real
        dry-run paths (`setup.set_defaults`, `resolve_control.clear_executions`),
        and it answered `success: true` for an invalid enum value and for adding
        a marker with no timeline in existence. `dry_run` is the one thing an
        editor reaches for before a destructive edit; a version of it that
        always succeeds is worse than none, because it is trusted.
        `test_no_default_hook_short_circuits` keeps it that way.
        """
        self._hooks.append(RiskClassificationHook())
        self._hooks.append(ResolveStateInspectionHook())
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
            # One value, from one place. This previously reported
            # `assessment.snapshot_available or (pre_state is not None)` at the
            # top level while `risk.snapshot_available` stayed False — the same
            # response answering "can I roll this back?" both ways. Reading a
            # project name is not a restorable snapshot, and the classifier
            # never sets the flag, so the honest answer is "not determined".
            "snapshot_available": assessment.snapshot_available,
            "reasons": assessment.reasons,
            "recognised": assessment.recognised,
            "pre_state": pre_state,
            # Whether pre_state reflects a live Resolve at all, so a caller can
            # tell "no project open" from "never asked".
            "pre_state_available": pre_state is not None,
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

