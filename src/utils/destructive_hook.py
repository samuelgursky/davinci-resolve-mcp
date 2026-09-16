"""Version-on-mutate hook + destructive-action registry (C6).

Wraps each top-level compound tool function in `src/server.py` so that any
destructive sub-action automatically:

1. Resolves the project root via the configured project-root provider.
2. Calls `timeline_versioning.ensure_versioned_before_mutation()` for the run.
3. Captures the declared metric's `before_value` (if `metric` was passed in params).
4. Runs the original handler.
5. Captures the declared metric's `after_value` (and gap stats by default).
6. Logs a `brain_edits` row.

If anything in the hook fails — Resolve isn't connected, no current project,
project_root can't be resolved, the DB can't be opened — the wrapper degrades
silently and the underlying handler still runs. The user's edit must never be
blocked by a versioning failure. (Failures are logged at WARNING.)

## Registering destructive actions

Add `(tool_name, action_name)` entries to `DESTRUCTIVE_ACTIONS_BY_TOOL`. The
enforcement test in `tests/test_destructive_decorator_coverage.py` confirms
every tool that owns destructive actions is decorated.
"""

from __future__ import annotations

import ast
import functools
import inspect
import json
import logging
import os
import textwrap
import time
import uuid
from typing import Any, Callable, Dict, FrozenSet, Optional, Tuple

from src.utils import analysis_runs, brain_edits, media_pool_changes, timeline_versioning
from src.utils.api_truth import API_TRUTH, traps_for, trap_notice
from src.utils.bool_params import coerce_bool, explicit_bool_param
from src.utils.execution_lifecycle import (
    RiskAssessment,
    RiskClassificationHook,
    RiskLevel,
    classify_operation_risk,
)

logger = logging.getLogger("resolve-mcp.destructive-hook")


#: Risk levels safe mode refuses. Names come from `RiskLevel`; a second
#: vocabulary here would let the gate and the reported level disagree.
SAFE_MODE_BLOCKED_RISK_LEVELS: FrozenSet[str] = frozenset({
    RiskLevel.HIGH.value, RiskLevel.CRITICAL.value,
})


# ── Destructive action registry ──────────────────────────────────────────────
#
# Tool name → frozenset of action strings that mutate the working timeline (or
# the timeline-item subtree). Adding a new destructive action means: (a) add it
# here; (b) optionally add a metric-capture entry below if it has a sensible
# default metric.

# Each action is keyed under the tool whose @_destructive_op wrapper actually
# DISPATCHES it. Historically many entries were filed under the wrong tool key
# (e.g. create_timeline/auto_sync_audio under "timeline" though they are media_pool
# actions; set_cdl/copy_grades under "timeline_item" though timeline_item_color
# dispatches them; *_fusion_comp / *_take stale names that never matched), so
# is_destructive() returned False and version-on-mutate archiving silently did not
# fire. EX-REG re-filed every action under its real dispatcher and dropped inert
# entries whose tool is not @_destructive_op-wrapped (e.g. media_pool_item
# replace_clip/link_*). The test_destructive_registry_drift guard asserts every
# string here is a real handler so this can't regress.
DESTRUCTIVE_ACTIONS_BY_TOOL: Dict[str, FrozenSet[str]] = {
    # Plugin-folder writes. These create, replace and delete files that Resolve
    # and Fusion later load and run: a Fuse registers on the next restart, a
    # Resolve-page script runs when clicked. Until they were listed here every
    # gate treated them as reads, and a dry run of `install` wrote the file for
    # real. They never mutate the timeline, so NON_TIMELINE_WRITE_TOOLS keeps
    # them out of timeline archiving while every gate still sees them.
    "dctl": frozenset({"encrypt_native", "install", "remove"}),
    # LUT files under Resolve's master LUT root. Writes are confined to the
    # namespaced MCP/ subfolder by src/utils/lut_files.py; these entries make
    # every gate see them as the writes they are.
    "lut": frozenset({"attenuate", "install", "remove"}),
    "fuse_plugin": frozenset({"install", "remove"}),
    "script_plugin": frozenset({
        "install",
        "remove",
        "safe_install_extension",
        "safe_remove_extension",
    }),
    # Deletes the classifier already rated HIGH (CRITICAL for the raw project
    # delete) on tools that carried no @_destructive_op, so safe mode never saw
    # them. Plus the 21.0 AI deblur, rated MEDIUM: it creates media, and is
    # registered so it is audited and its dry run is honest.
    "folder": frozenset({"remove_motion_blur"}),
    "fusion_comp": frozenset({"delete_keyframe", "delete_tool"}),
    "gallery_stills": frozenset({"delete_stills"}),
    "media_pool_item": frozenset({"remove_motion_blur"}),
    "media_pool_item_markers": frozenset({
        "delete_at_frame",
        "delete_by_color",
        "delete_by_custom_data",
    }),
    "project_manager": frozenset({"archive", "delete", "safe_project_archive",
                                  "safe_project_delete"}),
    "project_settings": frozenset({"delete_color_group"}),
    "render": frozenset({"delete_all_jobs", "delete_job", "delete_preset"}),
    "render_presets": frozenset({"delete_burnin"}),
    "resolve_control": frozenset({"delete_user_preferences_preset"}),
    "media_pool": frozenset({
        "delete_clips",
        "delete_folders",
        "move_clips",
        "move_folders",
        "delete_clip_mattes",
        "delete_timelines",
        "create_timeline",
        "create_timeline_from_clips",
        "append_to_timeline",
        "setup_multicam_timeline",
        "create_multicam_clip",
        "create_stereo_clip",
        "auto_sync_audio",
        "set_clip_marks",
        "clear_clip_marks",
    }),
    "edit_engine": frozenset({
        "execute_selects",
        "execute_tighten",
        "execute_silence_ripple",
        "execute_swap",
    }),
    "timeline": frozenset({
        "set_output_blanking",
        "normalize_audio_level",
        "auto_align_clips",
        "delete_clips",
        "move_clips",
        "duplicate_clips",
        "copy_clips",
        "ripple_insert",
        "copy_range",
        "duplicate_range",
        "overwrite_range",
        "lift_range",
        "apply_cuts",
        "create_compound_clip",
        "create_fusion_clip",
        "convert_to_stereo",
        "set_clips_linked",
        "duplicate",
        "insert_generator",
        "insert_fusion_generator",
        "insert_fusion_composition",
        "insert_ofx_generator",
        "insert_title",
        "insert_fusion_title",
        "add_track",
        "delete_track",
        "set_track_lock",
        "set_track_enable",
        "set_track_name",
        "set_voice_isolation_state",
        # NOTE: timeline.set_name (rename) is intentionally NOT here. A rename is
        # content-preserving and trivially reversible, so version-on-mutate added
        # no recovery value — it only spawned redundant `_archived` copies (one per
        # rename, and renaming an archive archived the archive). Issue #83.
        "set_start_timecode",
        "set_setting",
        "set_mark_in_out",
        "clear_mark_in_out",
        "set_title_text",
        "import_into_timeline",
    }),
    "timeline_markers": frozenset({
        "add",
        "delete_at_frame",
        "delete_by_custom_data",
        "delete_by_color",
        "update_custom_data",
    }),
    "timeline_ai": frozenset({
        "detect_scene_cuts",
        "analyze_dolby_vision",
        "create_subtitles",
    }),
    "timeline_item": frozenset({
        "delete_keyframe",
        "set_output_blanking",
        "set_use_timeline_for_output_blanking",
        "set_clip_enabled",
        "set_property",
        "set_name",
        "set_voice_isolation_state",
        "update_sidecar",
        "set_transform",
        "set_crop",
        "set_retime",
        "set_composite",
        "set_audio",
        # Native 21.1 setters (#208). Registered on landing: as contributed the
        # classifier did not recognise them, so safe mode, the dry-run refusal,
        # the audit log and the operation log all skipped a call that rewrites a
        # clip's speed — and, with RippleTimeline true, moves every clip after it.
        "flatten_multicam",
        "add_transition",
        "set_speed",
        "set_fades",
    }),
    "timeline_item_markers": frozenset({
        "add",
        "add_flag",
        "clear_flags",
        "set_clip_color",
        "clear_clip_color",
        "delete_at_frame",
        "delete_by_custom_data",
        "delete_by_color",
        "update_custom_data",
    }),
    "timeline_item_fusion": frozenset({
        "add_comp",
        "delete_comp",
        "import_comp",
        "load_comp",
        "rename_comp",
    }),
    "timeline_item_color": frozenset({
        "set_cdl",
        "copy_grades",
        "apply_trace_plan",
        "reset_all_node_colors",
        "assign_color_group",
        "remove_from_color_group",
        "create_magic_mask",
        "regenerate_magic_mask",
        "smart_reframe",
        "stabilize",
        "export_lut",
        "add_version",
        "delete_version",
        "load_version",
        "rename_version",
        "set_color_cache",
        "set_fusion_cache",
    }),
    "timeline_item_takes": frozenset({
        "add",
        "delete",
        "select",
        "finalize",
    }),
    "graph": frozenset({
        "set_lut",
        "set_node_enabled",
        "apply_arri_cdl_lut",
        "apply_grade_from_drx",
        "reset_all_grades",
    }),
}


# ── No-archive filters ──────────────────────────────────────────────────────
#
# Some destructive *actions* are technically mutations but their *payloads* are
# free-text metadata that nobody wants to roll back ("Notes" updates, comment
# tweaks, etc.). Registering them in NO_ARCHIVE_ON_KEYS means: if the action's
# `key` param is in this set, skip versioning. Other key choices still archive.
#
# Shape: (tool, action) → {keys_that_skip_archiving}
#   - empty set or missing entry → always archive
#   - non-empty set → only the listed keys skip archiving

NO_ARCHIVE_ON_KEYS: Dict[Tuple[str, str], frozenset] = {
    ("timeline_item", "set_property"): frozenset({"Notes"}),
    # set_clip_property on timeline can target Name/Notes/Comments/etc. — only
    # Notes/Comments are noise; Name changes are real edits and stay archived.
    ("timeline", "set_clip_property"): frozenset({"Notes", "Comments"}),
}


# ── Non-timeline write tools ────────────────────────────────────────────────
#
# Tools whose registered actions do not mutate the working timeline: they write
# plugin folders, or act on projects, the render queue, presets, the gallery,
# pool items or app preferences. Every
# gate applies to them — safe mode, dry-run refusal, the audit log — but they
# skip version-on-mutate archiving, and skip resolving the versioning context
# at all: that goes through the project-root provider, which reaches Resolve,
# and installing a shader must neither snapshot the open timeline nor touch
# Resolve. `media_pool` has its own branch for the same reason; these differ in
# that there is no project state to log.

NON_TIMELINE_WRITE_TOOLS: frozenset = frozenset({
    "dctl", "fuse_plugin", "lut", "script_plugin",
    "folder", "gallery_stills", "media_pool_item", "media_pool_item_markers",
    "project_manager", "project_settings", "render", "render_presets",
    "resolve_control",
})


# ── Strict-mode allowlist ───────────────────────────────────────────────────
#
# Actions in this set REFUSE to run if the version-on-mutate archive fails. For
# everything else (the vast majority), the underlying handler still runs even
# when archive fails — preferring user progress over perfect history. But
# `delete_timelines` permanently destroys timelines; if we couldn't archive
# first, the user almost certainly wants to know before losing data.

STRICT_DEFAULT_ACTIONS: frozenset = frozenset({
    ("timeline", "delete_track"),
    # NOTE: delete_timelines is a media_pool action (EX-REG re-keyed it); it is
    # archive+confirm-token gated (EX3) rather than strict, per the decision that
    # strict over-blocks deletes when there is nothing to archive.
    # delete_clips with ripple=True is destructive in a way single-clip delete
    # isn't — handled separately in is_strict_required() because it depends on
    # the params payload, not just the action name.
})


# ── Plan-only (dry-run) actions ─────────────────────────────────────────────
#
# Actions whose payload can declare the call non-mutating. `ripple_insert` is
# the only destructive action that DEFAULTS to a plan-only call, so without
# this every routine dry-run plan archives a timeline version — the same waste
# the pending-confirm skip (F4) exists to prevent, except the pending-confirm
# skip only fires while the confirm-token preference is ON. With it off, the
# read-only path of the action littered the version chain.

DRY_RUN_DEFAULT_TRUE_ACTIONS: frozenset = frozenset({
    ("timeline", "ripple_insert"),
})


# ── Native dry-run allowlist ────────────────────────────────────────────────
#
# Registered destructive actions whose handler genuinely reads `dry_run` and
# returns a plan instead of mutating. Every OTHER registered destructive action
# ignores the flag: `timeline_markers.add` with `dry_run=true` added a real
# marker, `timeline.delete_track` with `dry_run=true` deleted the track. An
# agent following the guidance "prefer dry_run where it exists" cannot tell
# the two apart from the outside, so an explicit `dry_run=true` on a registered
# destructive action outside this set is REFUSED (DRY_RUN_UNAVAILABLE) before
# archive, state lookup, or handler execution — nothing simulated, nothing
# executed, and the response says so.
#
# This is deliberately a refusal and not a synthesised preview: the lifecycle
# pipeline's original dry-run interceptor answered `success: true` for calls
# it never ran and was removed for it (see
# execution_lifecycle.LifecyclePipeline._register_default_hooks). A dry run
# that always succeeds is worse than none, because it is trusted.
#
# The set is pinned by tests.test_destructive_hook against a static scan of
# src/server.py that follows the params object into helpers: add a native
# dry-run branch to a handler and the test tells you to list it here; list an
# action here without one and the test refuses.

NATIVE_DRY_RUN_ACTIONS: frozenset = frozenset({
    ("media_pool", "clear_clip_marks"),
    ("timeline_markers", "add"),
    ("timeline_item_color", "apply_trace_plan"),
    ("media_pool", "set_clip_marks"),
    ("media_pool", "setup_multicam_timeline"),
    ("timeline", "apply_cuts"),
    ("timeline", "ripple_insert"),
    ("timeline_ai", "create_subtitles"),
    ("script_plugin", "safe_install_extension"),
    ("script_plugin", "safe_remove_extension"),
    ("project_manager", "safe_project_delete"),
    ("project_manager", "safe_project_archive"),
    ("lut", "attenuate"),
    ("lut", "install"),
    ("lut", "remove"),
})


def _explicit_dry_run_requested(params: Optional[Dict[str, Any]]) -> bool:
    return explicit_bool_param(params, "dry_run", "dryRun") is True


def lacks_native_dry_run(
    tool_name: str, action: str, params: Optional[Dict[str, Any]] = None,
) -> bool:
    """True when the caller asked for a dry run this destructive action cannot honour.

    Keyed on the destructive registry rather than `is_destructive()` so the
    no-archive filters (a Notes edit, say) cannot let a dry-run request slip
    through to a handler that would execute it for real.
    """
    return (
        _explicit_dry_run_requested(params)
        and action in DESTRUCTIVE_ACTIONS_BY_TOOL.get(tool_name, frozenset())
        and (tool_name, action) not in NATIVE_DRY_RUN_ACTIONS
    )


def _dry_run_unavailable_response(
    *,
    operation_id: str,
    tool_name: str,
    action: str,
    assessment: RiskAssessment,
) -> Dict[str, Any]:
    return {
        "success": False,
        "status": "dry_run_unavailable",
        "dry_run": True,
        "simulated": False,
        "executed": False,
        "operation_id": operation_id,
        "security": {
            "risk_level": assessment.level.value,
            "risk_established": assessment.recognised,
            "safe_mode": _safe_mode_enabled(),
            "blocked": True,
            "policy": "destructive.dry_run_support",
        },
        "risk": assessment.to_dict(),
        "error": {
            "message": (
                f"'{tool_name}.{action}' has no native dry-run path, so dry_run=true "
                "cannot be honoured. Nothing was simulated and nothing was executed."
            ),
            "code": "DRY_RUN_UNAVAILABLE",
            "category": "dry_run_unavailable",
            "retryable": False,
            "remediation": (
                "Use inspect_operation for the static risk assessment, use a "
                "probe_*/safe_* action where one exists, or call again without "
                "dry_run once the operation has been reviewed."
            ),
        },
    }


def _payload_is_plan_only(
    tool_name: str, action: str, params: Optional[Dict[str, Any]],
) -> bool:
    """True iff this call only produces a plan and mutates nothing."""
    dry_run = explicit_bool_param(params, "dry_run", "dryRun")
    if (tool_name, action) in NATIVE_DRY_RUN_ACTIONS and dry_run is True:
        return True
    if (tool_name, action) not in DRY_RUN_DEFAULT_TRUE_ACTIONS:
        return False
    if dry_run is None:
        return True  # dry_run defaults to True for these actions
    return dry_run


def _payload_only_touches_no_archive_keys(
    tool_name: str, action: str, params: Optional[Dict[str, Any]],
) -> bool:
    """Return True iff the destructive action's payload is filtered out."""
    allowlist = NO_ARCHIVE_ON_KEYS.get((tool_name, action))
    if not allowlist or not isinstance(params, dict):
        return False
    # Only filter if `key` param is present (set_property style). Otherwise
    # default to archiving.
    key = params.get("key")
    if not key:
        return False
    return str(key) in allowlist


def is_destructive(tool_name: str, action: str, params: Optional[Dict[str, Any]] = None) -> bool:
    """Should this (tool, action, payload) trigger version-on-mutate?

    Checks the registry AND the payload-aware no-archive filter. Idempotent.
    """
    if action not in DESTRUCTIVE_ACTIONS_BY_TOOL.get(tool_name, frozenset()):
        return False
    if _payload_only_touches_no_archive_keys(tool_name, action, params):
        return False
    if _payload_is_plan_only(tool_name, action, params):
        return False
    return True


def is_strict_required(tool_name: str, action: str, params: Optional[Dict[str, Any]]) -> bool:
    """True if the call must refuse to run when archive fails.

    Triggers on (a) STRICT_DEFAULT_ACTIONS membership, (b) ripple delete on
    timeline.delete_clips, or (c) explicit `strict=True` in params.
    """
    if isinstance(params, dict) and params.get("strict") is True:
        return True
    if (tool_name, action) in STRICT_DEFAULT_ACTIONS:
        return True
    if (
        tool_name == "timeline"
        and action == "delete_clips"
        and isinstance(params, dict)
        and coerce_bool(params.get("ripple"))
    ):
        return True
    return False


def assess_action_risk(
    tool_name: str, action: str, params: Optional[Dict[str, Any]] = None,
) -> RiskAssessment:
    """Classify a call for the safe-operations policy.

    Classification lives in `execution_lifecycle`, which the pre-flight
    inspection surface already uses. Deriving it a second time here would let
    `inspect_operation` and the safe-mode gate disagree about the same call —
    the gate blocking what inspection called reversible, or the reverse.
    """
    return classify_operation_risk(tool_name, action, params or {})


def risk_level_for_action(
    tool_name: str, action: str, params: Optional[Dict[str, Any]] = None,
) -> str:
    """Return the security risk level for a call, as a `RiskLevel` value."""
    return assess_action_risk(tool_name, action, params).level.value


# ── Provider hooks ───────────────────────────────────────────────────────────

_ProjectRootProvider = Callable[[], Optional[Tuple[Any, Any, str, Optional[str]]]]
"""Returns (resolve_handle, project_handle, project_root, project_name) or None."""

_PROVIDER: Optional[_ProjectRootProvider] = None

_PreferenceProvider = Callable[[str], Any]
"""Reads a named preference (e.g. timeline_versioning_auto_save_after_archive)."""

_PREFERENCE_PROVIDER: Optional[_PreferenceProvider] = None

_PendingConfirmCheck = Callable[[str, str, Optional[Dict[str, Any]]], bool]
"""Returns True iff this (tool, action, params) call will be short-circuited by
the confirm-token gate to issue a fresh token (no mutation will run). When True
the wrapper skips the pre-mutation archive — there's nothing yet to archive.
"""

_PENDING_CONFIRM_CHECK: Optional[_PendingConfirmCheck] = None


def register_project_root_provider(fn: _ProjectRootProvider) -> None:
    """Install the provider used by the hook to locate the active project root.

    `src/server.py` registers a provider during startup that consults its
    `get_resolve()` helper + the analysis output-root resolver.
    """
    global _PROVIDER
    _PROVIDER = fn


def register_preference_provider(fn: _PreferenceProvider) -> None:
    """Install the provider used by the hook to read C6 preferences."""
    global _PREFERENCE_PROVIDER
    _PREFERENCE_PROVIDER = fn


def register_pending_confirm_check(fn: _PendingConfirmCheck) -> None:
    """Install the predicate used to detect token-issuance calls.

    When the predicate returns True, the wrapper bypasses the pre-mutation
    archive and the brain_edit row entirely — the underlying handler is still
    invoked so it can mint and return the confirm_token, but no state has
    changed yet. This avoids one wasted archive per token-issuance call (F4).
    """
    global _PENDING_CONFIRM_CHECK
    _PENDING_CONFIRM_CHECK = fn


def _read_preference(key: str, default: Any = None) -> Any:
    if _PREFERENCE_PROVIDER is None:
        return default
    try:
        value = _PREFERENCE_PROVIDER(key)
    except Exception as exc:
        logger.debug("preference provider for %s raised: %s", key, exc)
        return default
    return default if value is None else value


def _coerce_bool(value: Any, default: bool = False) -> bool:
    return coerce_bool(value, default)


def _safe_mode_enabled() -> bool:
    return _coerce_bool(_read_preference("destructive.safe_mode", False), False)


def _audit_enabled() -> bool:
    return _coerce_bool(_read_preference("destructive.audit_log", True), True)


def _audit_log_path() -> str:
    configured = _read_preference("destructive.audit_log_path", None)
    if configured:
        return os.path.expanduser(str(configured))
    project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(project_dir, "logs", "security-audit.jsonl")


def _safe_params_for_audit(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(params, dict):
        return None
    redacted = dict(params)
    for key in ("confirm_token", "confirmToken"):
        if key in redacted:
            redacted[key] = "<redacted>"
    return redacted


def _audit_security_event(
    *,
    operation_id: str,
    tool_name: str,
    action: str,
    risk_level: str,
    status: str,
    params: Optional[Dict[str, Any]],
    recognised: bool = True,
    reason: Optional[str] = None,
    project_root: Optional[str] = None,
    analysis_run_id: Optional[str] = None,
) -> None:
    if not _audit_enabled():
        return
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "operation_id": operation_id,
        "tool": tool_name,
        "action": action,
        "risk_level": risk_level,
        "risk_established": recognised,
        "status": status,
        "reason": reason,
        "analysis_run_id": analysis_run_id,
        "project_root": project_root,
        "params": _safe_params_for_audit(params),
    }
    path = _audit_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")
    except Exception as exc:
        logger.warning("security audit log write failed: %s", exc)


def _security_block_response(
    *,
    operation_id: str,
    tool_name: str,
    action: str,
    risk_level: str,
    recognised: bool = True,
    override_hint: str = "params.allow_risky_operation=true",
) -> Dict[str, Any]:
    return {
        "success": False,
        "status": "blocked_by_security_policy",
        "operation_id": operation_id,
        "security": {
            "risk_level": risk_level,
            "risk_established": recognised,
            "safe_mode": True,
            "blocked": True,
            "policy": "destructive.safe_mode",
        },
        "error": {
            "message": (
                f"Safe mode blocked {risk_level}-risk action "
                f"'{tool_name}.{action}'. "
                f"Re-call with {override_hint}, or disable "
                "destructive.safe_mode in setup defaults."
            ),
            "code": "SAFE_MODE_BLOCKED",
            "category": "destructive_blocked",
            "retryable": False,
            "remediation": (
                f"Pass {override_hint} for this call after review, or "
                "set destructive.safe_mode=false if this session should allow "
                "high-risk destructive actions."
            ),
        },
    }


def _annotate_security(
    result: Any,
    *,
    operation_id: str,
    risk_level: str,
    blocked: bool = False,
    recognised: bool = True,
) -> Any:
    if isinstance(result, dict):
        result.setdefault("operation_id", operation_id)
        result.setdefault("security", {
            "risk_level": risk_level,
            "risk_established": recognised,
            "safe_mode": _safe_mode_enabled(),
            "blocked": blocked,
        })
    return result


def _safe_mode_allows(
    risk_level: str,
    params: Optional[Dict[str, Any]],
    recognised: bool = True,
) -> bool:
    """Whether safe mode lets this call through.

    Only an established HIGH or CRITICAL is blocked. Failing closed on
    `recognised=False` was measured and rejected: 80 of the 108 registered
    destructive actions match no risk rule today, `timeline.add_track` and
    `timeline.duplicate` among them, so it would block three quarters of all
    edits and teach users to leave safe mode off — weaker in practice than a
    narrow gate they keep on. The unclassified actions are reported via
    `risk_established` instead, and want classifying rather than blanket-gating.
    """
    if not _safe_mode_enabled():
        return True
    if risk_level not in SAFE_MODE_BLOCKED_RISK_LEVELS:
        return True
    if isinstance(params, dict) and params.get("allow_risky_operation") is True:
        return True
    return False


def _resolve_versioning_context() -> Optional[Tuple[Any, Any, str, Optional[str]]]:
    if _PROVIDER is None:
        return None
    try:
        return _PROVIDER()
    except Exception as exc:
        logger.debug("project-root provider raised: %s", exc)
        return None


# ── Action analysis_run_id source ────────────────────────────────────────────


def _extract_analysis_run_id(params: Optional[Dict[str, Any]], project_root: Optional[str] = None) -> str:
    """Resolve the analysis_run_id for this call.

    Order:
      1. explicit param `analysis_run_id` or `run_id`
      2. process-level current run (active begin_run/auto-run; idle timer applied)
      3. open a fresh auto-run for this destructive op (B3)

    The auto-run path (step 3) sets initiator='auto' and is closed by either
    the next idle-timeout firing on a later destructive op, or an explicit
    end_run call.
    """
    if isinstance(params, dict):
        rid = params.get("analysis_run_id") or params.get("run_id")
        if rid:
            return str(rid)
    if project_root:
        try:
            timeout = float(_read_preference("versioning_auto_run_idle_timeout_seconds", default=90))
        except Exception:
            timeout = 90.0
        try:
            return analysis_runs.ensure_auto_run_for_destructive(
                project_root=project_root, idle_timeout_seconds=timeout,
            )
        except Exception as exc:
            logger.debug("auto-run open failed; falling back to ephemeral id: %s", exc)
    active = analysis_runs.current_run_id()
    if active:
        analysis_runs.bump_idle_timer()
        return active
    return timeline_versioning.new_analysis_run_id()


def _extract_initiator(params: Optional[Dict[str, Any]]) -> Optional[str]:
    """Provenance label for the row. Explicit param > current run initiator > None."""
    if isinstance(params, dict) and params.get("initiator"):
        return str(params["initiator"])
    return analysis_runs.current_run_initiator()


def _extract_metric(params: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not isinstance(params, dict):
        return (None, None, None)
    return (
        params.get("metric"),
        params.get("direction"),
        params.get("rationale"),
    )


# ── Decorator ────────────────────────────────────────────────────────────────


#: Set truthy to disable the trap guard entirely (both the refusal and the
#: advisory push). Exists because the refusal is a behaviour change for callers
#: that previously got a bare `{"success": true}` from a destructive copy.
TRAP_GUARD_ENV = "RESOLVE_MCP_DISABLE_TRAP_GUARD"


def _trap_guard_disabled() -> bool:
    return os.environ.get(TRAP_GUARD_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


#: Actions that already make the caller confirm, so the trap guard must NOT also
#: refuse them.
#:
#: `destroys_prior_work` is a property of the SYMBOL (TimelineItem.CopyGrades),
#: but four actions call that symbol and two of them already own a confirmation
#: path. Refusing those means the caller is told to add `acknowledge_trap`, and
#: only after retrying discovers they also need a confirm token — two
#: acknowledgements for one operation, found serially. Worse, it lands hardest on
#: `safe_copy_grade`, whose whole name promises it is the careful route; making
#: it the most irritating to call pushes people toward the raw `copy_grades` the
#: guard exists to protect them from.
#:
#: Two mechanisms enforcing one rule drift apart. The confirm-token flow is older
#: and more specific, so it wins and this guard stands down. These actions still
#: get the advisory `known_limitation` — the fact is worth having, the second
#: refusal is not.
TRAP_REFUSAL_EXEMPT_ACTIONS: FrozenSet[Tuple[str, str]] = frozenset({
    # Issues a confirm_token whose preview names the exact risk: "Replaces the
    # entire node graph on every successfully resolved target item."
    ("timeline_item_color", "safe_copy_grade"),
    # Dry-run-by-default in the handler (`p.get("dry_run", True)`), then
    # confirm_token to execute. A first call with no params mutates nothing.
    ("timeline_item_color", "bulk_match_to_hero"),
})


def _trap_acknowledged(params: Optional[Dict[str, Any]]) -> bool:
    """Did the caller explicitly accept a known-destructive behaviour?"""
    return isinstance(params, dict) and coerce_bool(params.get("acknowledge_trap"))


def _trap_block_response(
    tool_name: str, action: str, blocking: list,
) -> Dict[str, Any]:
    """Refuse a call whose verified behaviour destroys unrecoverable work.

    The point is not to forbid the operation — it is to make the caller say out
    loud that they know what it does. `CopyGrades` returns True while replacing
    a hand-built grade wholesale and leaving no version to go back to, so a
    caller who did not know that cannot tell success from loss.
    """
    return {
        "success": False,
        "error": (
            f"'{tool_name}.{action}' is refused: its verified behaviour destroys "
            "existing work that cannot be recovered afterwards. Read "
            "`known_limitation`, then re-send with acknowledge_trap=true if that "
            "is genuinely what you want."
        ),
        "known_limitation": [trap_notice(e) for e in blocking],
        "retry_with": {"acknowledge_trap": True},
        "override_env": TRAP_GUARD_ENV,
    }


def _attach_trap_notices(result: Any, traps: list) -> Any:
    """Ride the verified fact along on the result, without overwriting one."""
    if not traps or not isinstance(result, dict):
        return result
    result.setdefault("known_limitation", [trap_notice(e) for e in traps])
    return result


# ── Granular server enforcement ──────────────────────────────────────────────
#
# `destructive_op` above wraps a `(action, params)` signature. Granular tools do not
# have one: each tool IS the operation, with its own keyword arguments. For four
# releases that meant safe mode — the setting a user turns on precisely so that a
# HIGH-risk call is refused — did nothing whatsoever on the granular server, and no
# granular write produced an audit row. A user running with `destructive.safe_mode`
# on was protected on one server and not the other, with nothing saying so.
#
# This decorator closes that. It deliberately does NOT archive: the compound hook
# duplicates a timeline into an Archive bin before a mutation, and doing that around
# 130-odd granular calls would bury a project in versions for operations as small
# as setting a clip colour. What it does is the part that was missing and cannot be
# recovered after the fact — refuse when policy says refuse, and record what ran.
# A granular write therefore stays UNRECOVERABLE after it runs; the docs say so
# rather than implying parity with the compound server.

#: Verb → risk level, matching how the compound tables rate the same verbs
#: (deletes and removes HIGH, sets and loads MEDIUM). Only HIGH and CRITICAL are
#: refused by safe mode, so this mapping is what makes the setting mean anything
#: on this surface.
#:
#: Values are `RiskLevel` VALUES, not names. The first draft wrote "HIGH" here while
#: `SAFE_MODE_BLOCKED_RISK_LEVELS` holds `RiskLevel.HIGH.value == "high"`, so nothing
#: ever matched and safe mode was cosmetic on every decorated tool. One vocabulary.
GRANULAR_RISK_BY_VERB: Dict[str, str] = {
    "delete": RiskLevel.HIGH.value,
    "remove": RiskLevel.HIGH.value,
    "clear": RiskLevel.HIGH.value,
    "reset": RiskLevel.HIGH.value,
    "replace": RiskLevel.HIGH.value,
    "unlink": RiskLevel.HIGH.value,
    "overwrite": RiskLevel.HIGH.value,
    "quit": RiskLevel.HIGH.value,
    "restart": RiskLevel.HIGH.value,
    "set": RiskLevel.MEDIUM.value,
    "load": RiskLevel.MEDIUM.value,
    "switch": RiskLevel.MEDIUM.value,
    "close": RiskLevel.MEDIUM.value,
    "stop": RiskLevel.MEDIUM.value,
    "lift": RiskLevel.MEDIUM.value,
}

#: Namespaces stripped before reading the verb, kept in step with
#: `src.granular.common.NAMESPACE_PREFIXES`.
_GRANULAR_NAMESPACES = ("ti_", "timeline_", "graph_", "folder_")

#: Resolve method names the ledger marks `destroys_prior_work`. Derived from
#: `API_TRUTH` rather than written out, so flagging a new entry raises every tool
#: that reaches it without anyone remembering this table exists.
GRANULAR_TRAP_METHODS: FrozenSet[str] = frozenset(
    str(entry["symbol"]).rsplit(".", 1)[-1]
    for entry in API_TRUTH
    if entry.get("destroys_prior_work")
)

#: Name of the per-call safe-mode override, the same one the compound server reads
#: from `params`. Granular tools have no `params` dict, so the decorator adds it to
#: the tool's own signature.
GRANULAR_OVERRIDE_PARAM = "allow_risky_operation"


def _reaches_trap_symbol(fn: Callable[..., Any]) -> bool:
    """Does the function body call a method the ledger says destroys prior work?

    Read from source with `ast`, the same way the ratchet test finds it, so the
    rating is mechanical: a tool that reaches `TimelineItem.CopyGrades` is HIGH
    because the ledger says so, not because someone rated it by hand.
    """
    if not GRANULAR_TRAP_METHODS:
        return False
    try:
        source = inspect.getsource(fn)
    except (OSError, TypeError):
        return False
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in GRANULAR_TRAP_METHODS):
            return True
    return False


_RISK_ORDER = {
    RiskLevel.LOW.value: 0,
    RiskLevel.MEDIUM.value: 1,
    RiskLevel.HIGH.value: 2,
    RiskLevel.CRITICAL.value: 3,
}


@functools.lru_cache(maxsize=1)
def _established_compound_ratings() -> Dict[str, str]:
    """Compound risk ratings keyed by action name, most severe wins.

    The same operation is often exposed on both servers under the same action
    name — `clear_flags`, `delete_clips`, `copy_grades` — and the compound tables
    are where someone actually assessed it. Guessing from the verb when a real
    rating exists produced 20 disagreements, three of them UNDER-rating: the verb
    table called `ti_copy_grades` MEDIUM (so safe mode let it through) while the
    compound tables rate `copy_grades` HIGH, and `delete_clips` is CRITICAL there
    against HIGH here.

    Most-severe-wins because a name rated differently by two compound tools is
    ambiguous, and a gate should resolve ambiguity by refusing more, not less.
    """
    ratings: Dict[str, str] = {}
    for table, level in (
        ("_CRITICAL_ACTIONS", RiskLevel.CRITICAL.value),
        ("_HIGH_RISK_ACTIONS", RiskLevel.HIGH.value),
        ("_MEDIUM_RISK_ACTIONS", RiskLevel.MEDIUM.value),
        ("_LOW_RISK_ACTIONS", RiskLevel.LOW.value),
    ):
        for _tool, action in getattr(RiskClassificationHook, table, ()) or ():
            current = ratings.get(action)
            if current is None or _RISK_ORDER[level] > _RISK_ORDER[current]:
                ratings[action] = level
    return ratings


def _granular_action_name(tool_name: str) -> str:
    """The tool name with its namespace removed — the compound action name."""
    name = (tool_name or "").lower()
    for prefix in _GRANULAR_NAMESPACES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def granular_risk_level(tool_name: str, fn: Optional[Callable[..., Any]] = None) -> str:
    """Rate a granular tool, preferring an assessment over a guess.

    In order: HIGH if the body reaches a symbol the ledger marks
    `destroys_prior_work`; else the compound server's established rating for the
    same action name; else the verb. Unknown verbs are MEDIUM, never HIGH.

    Rating an unrecognised verb HIGH would let safe mode block writes nobody has
    assessed, which is the failure `_safe_mode_allows` documents: over-blocking
    teaches people to switch the setting off, and a setting left off protects
    nothing. The compound lookup cuts both ways for the same reason — it raises
    `copy_grades` to HIGH, and it lowers the seventeen `clear_*`/`set_*` tools the
    verb table called HIGH while compound rates them LOW.
    """
    if fn is not None and _reaches_trap_symbol(fn):
        return RiskLevel.HIGH.value
    name = _granular_action_name(tool_name)
    established = _established_compound_ratings().get(name)
    if established is not None:
        return established
    return GRANULAR_RISK_BY_VERB.get(name.split("_", 1)[0], RiskLevel.MEDIUM.value)


def _with_override_param(fn: Callable[..., Any]) -> Tuple[inspect.Signature, bool]:
    """The tool's signature plus `allow_risky_operation: bool = False`.

    FastMCP builds the MCP input schema from `inspect.signature`, which honours
    `__signature__`, so this is what makes the override callable from a client.
    Returns (signature, added): `added` is False when the tool already declares
    the parameter itself, in which case it is passed straight through.
    """
    sig = inspect.signature(fn)
    if GRANULAR_OVERRIDE_PARAM in sig.parameters:
        return sig, False
    extra = inspect.Parameter(
        GRANULAR_OVERRIDE_PARAM,
        inspect.Parameter.KEYWORD_ONLY,
        default=False,
        annotation=bool,
    )
    params = list(sig.parameters.values())
    # Keyword-only goes after every positional-or-keyword parameter and before
    # **kwargs, if the tool has one.
    tail = [p for p in params if p.kind is inspect.Parameter.VAR_KEYWORD]
    head = [p for p in params if p.kind is not inspect.Parameter.VAR_KEYWORD]
    return sig.replace(parameters=head + [extra] + tail), True


def _returns_plain_string(fn: Callable[..., Any]) -> bool:
    """Does this tool declare `-> str`?

    FastMCP builds an output schema from the return annotation and validates
    against it, so handing a dict to a tool annotated `-> str` raises ToolError
    and the caller never sees the refusal — only a generic execution error with
    none of its code or remediation. 27 granular tools declare `-> str`, and the
    HIGH-risk ones among them are exactly the calls safe mode exists to stop.
    """
    annotation = getattr(fn, "__annotations__", {}).get("return")
    return annotation is str or annotation in ("str", "'str'")


def _block_for(fn: Callable[..., Any], block: Dict[str, Any]) -> Any:
    """The refusal, shaped to the contract the tool declares.

    A string-returning tool gets the message and its remediation as text. That
    loses the machine-readable `code`, which is a real cost — but a refusal the
    client can read beats a ToolError that discards it entirely, and it is the
    only shape that tool's own schema will accept.
    """
    if not _returns_plain_string(fn):
        return block
    error = block.get("error") or {}
    message = error.get("message") or "Blocked by destructive.safe_mode."
    remediation = error.get("remediation")
    code = error.get("code")
    parts = [f"{code}: {message}" if code else message]
    if remediation:
        parts.append(remediation)
    return " ".join(parts)


def granular_destructive_op(
    tool_name: Optional[str] = None,
    *,
    risk_level: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Apply safe-mode policy and audit logging to one granular tool.

    Wraps an arbitrary keyword signature rather than `(action, params)`. The call's
    bound arguments become the `params` every downstream helper expects, and an
    `allow_risky_operation` parameter is added to the tool's schema so a single
    HIGH-risk call can be let through with safe mode still on — the same override
    the compound server reads from `params`.

    No archive is taken. A granular write cannot be recovered after it runs.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        action = tool_name or getattr(fn, "__name__", "unknown")
        level = risk_level or granular_risk_level(action, fn)
        signature, added_override = _with_override_param(fn)

        @functools.wraps(fn)
        def _inner(*args: Any, **kwargs: Any) -> Any:
            override = False
            if added_override and GRANULAR_OVERRIDE_PARAM in kwargs:
                override = _coerce_bool(kwargs.pop(GRANULAR_OVERRIDE_PARAM), False)
            # Bind so a positionally-passed argument is still audited by name. A
            # signature mismatch must not turn a working tool into an error, so
            # fall back to the keywords we were given.
            try:
                bound = inspect.signature(fn).bind_partial(*args, **kwargs)
                bound.apply_defaults()
                params: Dict[str, Any] = dict(bound.arguments)
            except Exception:
                params = dict(kwargs)
            if added_override:
                params[GRANULAR_OVERRIDE_PARAM] = override
            elif GRANULAR_OVERRIDE_PARAM in params:
                params[GRANULAR_OVERRIDE_PARAM] = _coerce_bool(
                    params[GRANULAR_OVERRIDE_PARAM], False)

            operation_id = f"op_{uuid.uuid4().hex[:12]}"
            if not _safe_mode_allows(level, params, True):
                _audit_security_event(
                    operation_id=operation_id,
                    tool_name="granular",
                    action=action,
                    risk_level=level,
                    status="blocked",
                    params=params,
                    reason="safe_mode",
                )
                return _block_for(fn, _security_block_response(
                    operation_id=operation_id,
                    tool_name="granular",
                    action=action,
                    risk_level=level,
                    override_hint=f"{GRANULAR_OVERRIDE_PARAM}=true",
                ))

            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                # A call that reached Resolve and then failed used to leave no row
                # at all. The audit log is this surface's only record of what ran,
                # so going silent precisely when something broke is the worst place
                # to have a gap. Record it, then let the exception continue
                # untouched — the hook is a witness, not a handler.
                _audit_security_event(
                    operation_id=operation_id,
                    tool_name="granular",
                    action=action,
                    risk_level=level,
                    status="failed",
                    params=params,
                    reason=type(exc).__name__,
                )
                raise

            # A first call that mints a confirm token has not mutated anything, and
            # recording it as "allowed" overstates what happened — the compound hook
            # distinguishes the same case via _PENDING_CONFIRM_CHECK.
            pending = (isinstance(result, dict)
                       and result.get("status") == "confirmation_required")
            _audit_security_event(
                operation_id=operation_id,
                tool_name="granular",
                action=action,
                risk_level=level,
                status="pending_confirmation" if pending else "allowed",
                params=params,
                reason="confirm_token_required" if pending else "no_archive_on_granular",
            )
            return _annotate_security(result, operation_id=operation_id, risk_level=level)

        _inner.__signature__ = signature  # type: ignore[attr-defined]
        _inner.__granular_destructive__ = (action, level)  # type: ignore[attr-defined]
        return _inner

    return decorator


def destructive_op(tool_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap a top-level tool function with the version-on-mutate hook.

    The wrapped function must accept `action: str` as its first positional
    argument and `params: Optional[Dict]` as its second (matches the existing
    compound-tool signature).
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def _inner(action: str, params: Optional[Dict[str, Any]] = None, *args, **kwargs) -> Any:
            if lacks_native_dry_run(tool_name, action, params):
                # An explicit dry-run request this handler would silently
                # execute for real. Refuse before archive, state lookup, or the
                # handler itself; see NATIVE_DRY_RUN_ACTIONS.
                operation_id = f"op_{uuid.uuid4().hex[:12]}"
                assessment = assess_action_risk(tool_name, action, params)
                _audit_security_event(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    action=action,
                    risk_level=assessment.level.value,
                    status="blocked",
                    params=params,
                    reason="dry_run_unavailable",
                    recognised=assessment.recognised,
                )
                return _dry_run_unavailable_response(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    action=action,
                    assessment=assessment,
                )

            if not is_destructive(tool_name, action, params):
                return fn(action, params, *args, **kwargs)

            operation_id = f"op_{uuid.uuid4().hex[:12]}"
            assessment = assess_action_risk(tool_name, action, params)
            risk_level = assessment.level.value
            risk_recognised = assessment.recognised
            if not _safe_mode_allows(risk_level, params, risk_recognised):
                _audit_security_event(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    action=action,
                    risk_level=risk_level,
                    status="blocked",
                    params=params,
                    reason="safe_mode",
                    recognised=risk_recognised,
                )
                return _security_block_response(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    action=action,
                    risk_level=risk_level,
                    recognised=risk_recognised,
                )

            if tool_name in NON_TIMELINE_WRITE_TOOLS:
                result = fn(action, params, *args, **kwargs)
                _audit_security_event(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    action=action,
                    risk_level=risk_level,
                    status="allowed",
                    params=params,
                    reason="not_a_timeline_mutation",
                    recognised=risk_recognised,
                )
                if isinstance(result, dict):
                    result.setdefault("_versioning", {
                        "analysis_run_id": None,
                        "archived": False,
                        "skipped_reason": "not_a_timeline_mutation",
                    })
                return _annotate_security(
                    result,
                    operation_id=operation_id,
                    risk_level=risk_level,
                    recognised=risk_recognised,
                )

            # F4 — token-issuance calls don't mutate; skip the archive entirely
            # so that token preview/cancel paths don't litter the version chain.
            # The wrapper still annotates `_versioning` on the result so callers
            # can see *why* nothing was archived.
            if _PENDING_CONFIRM_CHECK is not None:
                try:
                    will_gate = bool(_PENDING_CONFIRM_CHECK(tool_name, action, params))
                except Exception as exc:
                    logger.debug("pending-confirm check raised: %s", exc)
                    will_gate = False
                if will_gate:
                    result = fn(action, params, *args, **kwargs)
                    _audit_security_event(
                        operation_id=operation_id,
                        tool_name=tool_name,
                        action=action,
                        risk_level=risk_level,
                        status="pending_confirmation",
                        params=params,
                        reason="confirm_token_required",
                        recognised=risk_recognised,
                    )
                    if isinstance(result, dict):
                        result.setdefault("_versioning", {
                            "analysis_run_id": None,
                            "archived": False,
                            "skipped_reason": "pending_confirm_token",
                        })
                    return _annotate_security(
                        result,
                        operation_id=operation_id,
                        risk_level=risk_level,
                        recognised=risk_recognised,
                    )

            strict = is_strict_required(tool_name, action, params)

            ctx = _resolve_versioning_context()
            if ctx is None:
                if strict:
                    _audit_security_event(
                        operation_id=operation_id,
                        tool_name=tool_name,
                        action=action,
                        risk_level=risk_level,
                        status="blocked",
                        params=params,
                        reason="strict_missing_version_context",
                        recognised=risk_recognised,
                    )
                    return _annotate_security({
                        "success": False,
                        "error": (
                            f"strict mode: '{tool_name}.{action}' refuses to run because the "
                            "version-on-mutate context (project_root) couldn't be resolved. "
                            "Open a project in Resolve, or pass strict=false to override."
                        ),
                    },
                    operation_id=operation_id,
                    risk_level=risk_level,
                    blocked=True,
                    recognised=risk_recognised,
                )
                # No Resolve / no project — let the underlying handler run; it
                # will either succeed (e.g. in dry-run) or surface its own error.
                result = fn(action, params, *args, **kwargs)
                _audit_security_event(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    action=action,
                    risk_level=risk_level,
                    status="allowed",
                    params=params,
                    reason="no_version_context",
                    recognised=risk_recognised,
                )
                return _annotate_security(
                    result,
                    operation_id=operation_id,
                    risk_level=risk_level,
                    recognised=risk_recognised,
                )

            resolve_h, project_h, project_root, project_name = ctx
            run_id = _extract_analysis_run_id(params, project_root=project_root)
            metric, direction, rationale = _extract_metric(params)
            initiator = _extract_initiator(params)

            # Media-pool destructive ops don't archive a timeline; they log to
            # a separate provenance table. Branch here so the rest of the
            # wrapper only handles the timeline path.
            if tool_name == "media_pool":
                result = fn(action, params, *args, **kwargs)
                _audit_security_event(
                    operation_id=operation_id,
                    tool_name=tool_name,
                    action=action,
                    risk_level=risk_level,
                    status="allowed",
                    params=params,
                    project_root=project_root,
                    analysis_run_id=run_id,
                    recognised=risk_recognised,
                )
                try:
                    media_pool_changes.log_media_pool_change(
                        project_root=project_root,
                        analysis_run_id=run_id,
                        action=action,
                        params=params if isinstance(params, dict) else None,
                        after_state=_summarise_result(result),
                        initiator=initiator,
                    )
                except Exception as exc:
                    logger.warning("media_pool_change log failed: %s", exc)
                if isinstance(result, dict):
                    result.setdefault("_versioning", {
                        "analysis_run_id": run_id,
                        "category": "media_pool",
                        "initiator": initiator,
                    })
                return _annotate_security(
                    result,
                    operation_id=operation_id,
                    risk_level=risk_level,
                    recognised=risk_recognised,
                )

            before_value: Optional[float] = None
            timeline_before_name: Optional[str] = None
            try:
                current_tl = project_h.GetCurrentTimeline()
                if current_tl is not None:
                    timeline_before_name = current_tl.GetName()
                    if metric:
                        before_value = brain_edits.capture_metric(metric, current_tl)
            except Exception as exc:
                logger.debug("pre-capture failed: %s", exc)

            archive_result: Dict[str, Any] = {"archived": False}
            archive_exc: Optional[Exception] = None
            auto_save = bool(_read_preference(
                "timeline_versioning_auto_save_after_archive", False,
            ))
            try:
                archive_result = timeline_versioning.ensure_versioned_before_mutation(
                    resolve=resolve_h,
                    project=project_h,
                    project_root=project_root,
                    analysis_run_id=run_id,
                    reason=f"{tool_name}.{action}",
                    initiator=initiator,
                    auto_save=auto_save,
                )
            except Exception as exc:
                archive_exc = exc
                logger.warning(
                    "version-on-mutate hook failed (%sstrict mode): %s",
                    "blocking under " if strict else "continuing past in non-",
                    exc,
                )

            # Strict mode: archive must have either landed OR been a legitimate
            # no-op (already_archived_for_run | no_current_timeline). If the
            # hook raised, OR returned archived=False with an unexpected reason,
            # refuse the underlying call.
            if strict:
                skipped_ok = (
                    archive_result.get("archived") is False
                    and archive_result.get("skipped_reason") in {
                        "already_archived_for_run",
                    }
                )
                if archive_exc is not None or (
                    not archive_result.get("archived") and not skipped_ok
                ):
                    _audit_security_event(
                        operation_id=operation_id,
                        tool_name=tool_name,
                        action=action,
                        risk_level=risk_level,
                        status="blocked",
                        params=params,
                        reason="strict_archive_failed",
                        project_root=project_root,
                        analysis_run_id=run_id,
                        recognised=risk_recognised,
                    )
                    return _annotate_security({
                        "success": False,
                        "error": (
                            f"strict mode: refused '{tool_name}.{action}' because the "
                            "pre-mutation archive could not be created. "
                            f"reason={archive_result.get('skipped_reason') or 'archive_failed'} "
                            f"exception={type(archive_exc).__name__ if archive_exc else 'none'}"
                        ),
                        "_versioning": {
                            "analysis_run_id": run_id,
                            "archived": False,
                            "strict_block": True,
                        },
                    },
                    operation_id=operation_id,
                    risk_level=risk_level,
                    blocked=True,
                    recognised=risk_recognised,
                )

            # Run the underlying handler regardless of hook outcome.
            result = fn(action, params, *args, **kwargs)
            _audit_security_event(
                operation_id=operation_id,
                tool_name=tool_name,
                action=action,
                risk_level=risk_level,
                status="allowed",
                params=params,
                project_root=project_root,
                analysis_run_id=run_id,
                recognised=risk_recognised,
            )

            after_value: Optional[float] = None
            timeline_after_name: Optional[str] = timeline_before_name
            try:
                current_tl = project_h.GetCurrentTimeline()
                if current_tl is not None:
                    timeline_after_name = current_tl.GetName()
                    if metric:
                        after_value = brain_edits.capture_metric(metric, current_tl)
            except Exception as exc:
                logger.debug("post-capture failed: %s", exc)

            try:
                brain_edits.log_brain_edit(
                    project_root=project_root,
                    analysis_run_id=run_id,
                    edit_type=f"{tool_name}.{action}",
                    tool_name=tool_name,
                    action_name=action,
                    timeline_before=timeline_before_name,
                    timeline_after=timeline_after_name,
                    target_metric=metric,
                    metric_direction=direction,
                    before_value=before_value,
                    after_value=after_value,
                    rationale=rationale,
                    params=params if isinstance(params, dict) else None,
                    result_summary=_summarise_result(result),
                    project_name=project_name,
                    initiator=initiator,
                )
            except Exception as exc:
                logger.warning("brain_edit log failed: %s", exc)

            # Annotate the result with versioning context so the caller (and the
            # control panel) can show what happened. Don't shadow existing keys.
            if isinstance(result, dict):
                result.setdefault("_versioning", {
                    "analysis_run_id": run_id,
                    "archived": archive_result.get("archived"),
                    "archived_version": archive_result.get("version"),
                    "metric": metric,
                    "before_value": before_value,
                    "after_value": after_value,
                })
            return _annotate_security(
                result,
                operation_id=operation_id,
                risk_level=risk_level,
                recognised=risk_recognised,
            )

        @functools.wraps(fn)
        def wrapper(action: str, params: Optional[Dict[str, Any]] = None, *args, **kwargs) -> Any:
            # Trap push. `_inner` has a dozen return paths (dry-run refusal,
            # safe-mode block, pending-confirm, strict/no-context, normal); one
            # outer attach point covers all of them and cannot drift as those
            # paths change.
            traps = traps_for(tool_name, action)
            if traps and not _trap_guard_disabled():
                blocking = [t for t in traps if t.get("destroys_prior_work")]
                # A dry run destroys nothing, so there is nothing to acknowledge
                # — and preempting `_inner` here would swallow its
                # DRY_RUN_UNAVAILABLE refusal, which is the more important
                # answer: it tells the caller this action cannot be previewed
                # at all. The advisory push still rides along on that refusal.
                if (
                    blocking
                    and (tool_name, action) not in TRAP_REFUSAL_EXEMPT_ACTIONS
                    and not _trap_acknowledged(params)
                    and not _explicit_dry_run_requested(params)
                ):
                    return _trap_block_response(tool_name, action, blocking)
            return _attach_trap_notices(_inner(action, params, *args, **kwargs), traps)

        wrapper.__wrapped_tool_name__ = tool_name  # type: ignore[attr-defined]
        wrapper.__is_destructive_wrapped__ = True  # type: ignore[attr-defined]
        return wrapper

    return decorator


def _summarise_result(result: Any) -> Optional[Dict[str, Any]]:
    """Compact result summary suitable for the brain_edit row."""
    if not isinstance(result, dict):
        return None
    keys = ("success", "error", "name", "count", "deleted", "inserted", "updated")
    summary: Dict[str, Any] = {}
    for key in keys:
        if key in result:
            summary[key] = result[key]
    return summary or None
