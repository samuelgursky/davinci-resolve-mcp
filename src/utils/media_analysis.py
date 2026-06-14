"""Planning helpers for project-scoped media analysis.

This module deliberately performs no package installation and does not modify
source media. It is the safety/planning layer that the MCP tool uses before any
future ffprobe, ffmpeg, transcription, or vision work happens.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import json
import math
import os
import platform as _platform
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.utils import analysis_caps as _analysis_caps

# Caps preference reader — server.py registers a provider that reads the
# media-analysis prefs file. Until then, the default preset is used.
_CAPS_PRESET_PROVIDER: Optional[Callable[[], Optional[str]]] = None
_CAPS_OVERRIDES_PROVIDER: Optional[Callable[[], Optional[Dict[str, Any]]]] = None


def register_caps_preset_provider(fn: Callable[[], Optional[str]]) -> None:
    global _CAPS_PRESET_PROVIDER
    _CAPS_PRESET_PROVIDER = fn


def register_caps_overrides_provider(fn: Callable[[], Optional[Dict[str, Any]]]) -> None:
    global _CAPS_OVERRIDES_PROVIDER
    _CAPS_OVERRIDES_PROVIDER = fn


def _resolve_active_caps() -> _analysis_caps.Caps:
    """Pull the active caps from the registered provider, falling back to defaults."""
    preset = None
    overrides = None
    if _CAPS_PRESET_PROVIDER is not None:
        try:
            preset = _CAPS_PRESET_PROVIDER()
        except Exception:
            preset = None
    if _CAPS_OVERRIDES_PROVIDER is not None:
        try:
            overrides = _CAPS_OVERRIDES_PROVIDER()
        except Exception:
            overrides = None
    return _analysis_caps.resolve_caps(preset, overrides)


def _apply_caps_to_response(payload: Any) -> Any:
    """Trim a response payload to the active caps.response_chars limit."""
    caps = _resolve_active_caps()
    return _analysis_caps.trim_response_payload(payload, caps.response_chars)


def _cap_frames_for_active_caps(frame_paths: List[str]) -> List[str]:
    """Clip `frame_paths` to caps.frames_per_clip (None = uncapped). Also
    downscales each frame in place to caps.max_frame_dim_pixels."""
    caps = _resolve_active_caps()
    capped = frame_paths
    if caps.frames_per_clip is not None and len(frame_paths) > caps.frames_per_clip:
        capped = frame_paths[: caps.frames_per_clip]
    if caps.max_frame_dim_pixels is not None:
        for path in capped:
            try:
                _analysis_caps.downscale_frame_if_needed(path, caps.max_frame_dim_pixels)
            except Exception:
                # Downscale is best-effort; original-resolution upload is acceptable.
                pass
    return capped


# Rough estimates for the pre-call budget check. Different vision providers
# tokenize images differently — these are deliberately conservative defaults
# (real cost will usually be a bit lower so refusals only fire on genuine
# overruns). Override at call sites if you have a tighter measurement.
AVG_VISION_TOKENS_PER_FRAME = 1000
AVG_TRANSCRIPTION_TOKENS_PER_SECOND = 10


def _check_caps_pre_call(
    *,
    project_root: Optional[str],
    estimated_vision_tokens: int = 0,
    clip_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Refuse the call if `estimated_vision_tokens` would blow any cumulative cap.

    Returns None if allowed, else a clean error dict suitable for return-as-is.
    Silently allows when project_root is unavailable (caps DB lives there).
    """
    if not project_root or estimated_vision_tokens <= 0:
        return None
    try:
        caps = _resolve_active_caps()
        decision = _analysis_caps.check_budget(
            project_root=project_root, caps=caps,
            estimated_vision_tokens=estimated_vision_tokens,
            clip_id=clip_id, job_id=job_id,
        )
    except Exception:
        return None  # never block on infra failure
    if decision.allowed:
        return None
    # Log the refusal so the dashboard can show recent denials. Best-effort —
    # never let logging failure mask the refusal itself.
    try:
        _analysis_caps.log_caps_event(
            project_root=project_root,
            event_type="refusal",
            reason=decision.reason,
            preset=caps.preset,
            estimated_vision_tokens=estimated_vision_tokens,
            current_usage=decision.current_usage,
            cap=decision.cap,
            headroom=decision.headroom,
            clip_id=clip_id,
            job_id=job_id,
        )
    except Exception:
        pass
    return {
        "success": False,
        "status": "caps_exhausted",
        "reason": decision.reason,
        "estimated_vision_tokens": estimated_vision_tokens,
        "current_usage": decision.current_usage,
        "cap": decision.cap,
        "headroom": decision.headroom,
        "preset": caps.preset,
        "remediation": (
            "Raise the cap via `media_analysis.set_caps_preset` (e.g. preset='generous' "
            "or preset='unlimited'), or wait for the day_bucket to roll over. "
            f"Most-binding scope: {decision.reason}."
        ),
    }


def _annotate_clip_vision_failure(clip_result: Dict[str, Any], vision: Any) -> None:
    """Lift caps-refusal info into a structured error envelope on `clip_result`.

    When vision returns `status="caps_exhausted"` (a pre-call budget refusal),
    the caller buries the cause in the per-clip `error` string. This helper
    instead writes a `{code, category, reason, remediation, message}` dict and
    surfaces a separate `caps_refusal` block with usage/cap/headroom numbers.
    Falls back to the generic "did not complete" message for non-caps failures.
    """
    caps_refusal = (
        vision
        if isinstance(vision, dict) and vision.get("status") == "caps_exhausted"
        else None
    )
    if caps_refusal:
        clip_result.update({
            "success": False,
            "error": {
                "code": "CAPS_REFUSAL",
                "category": "budget_exhausted",
                "retryable": False,
                "reason": caps_refusal.get("reason"),
                "remediation": caps_refusal.get("remediation"),
                "message": (
                    "Visual analysis refused — caps budget exhausted "
                    f"({caps_refusal.get('reason')})."
                ),
            },
            "caps_refusal": {
                "preset": caps_refusal.get("preset"),
                "estimated_vision_tokens": caps_refusal.get("estimated_vision_tokens"),
                "current_usage": caps_refusal.get("current_usage"),
                "cap": caps_refusal.get("cap"),
                "headroom": caps_refusal.get("headroom"),
            },
            "visual": vision,
        })
    else:
        clip_result.update({
            "success": False,
            "error": "Visual analysis was requested but did not complete.",
            "visual": vision,
        })


def _annotate_partial_success(manifest: Dict[str, Any]) -> None:
    """D3 — Mark batch manifests with explicit completed/failed clip-id lists.

    When N-of-M clips fail mid-batch, the caller needs to know exactly which
    clips succeeded so it can retry only the failed subset instead of redoing
    everything. We populate:
        - partial_success: True when there's a mix (some success, some fail);
          False otherwise (all-success or all-fail).
        - completed_clip_ids: list of clip_ids whose row.success is True.
        - failed_clip_ids: list of clip_ids whose row.success is False AND
          which are not in a vision-pending state (pending isn't a failure).

    For all-fail batches, set an aggregate error envelope with code=PARTIAL_FAILURE,
    category=batch_partial (per D1) so the caller's retry policy can route on it.
    """
    clips = manifest.get("clips") or []
    if not clips:
        return

    def _clip_id(row: Dict[str, Any]) -> Optional[str]:
        record = row.get("record") or {}
        return record.get("clip_id") or row.get("clip_id")

    completed_ids = [_clip_id(row) for row in clips if row.get("success")]
    completed_ids = [cid for cid in completed_ids if cid]
    failed_ids = [
        _clip_id(row) for row in clips
        if not row.get("success") and row.get("vision_status") != "pending_host_analysis"
    ]
    failed_ids = [cid for cid in failed_ids if cid]

    has_success = bool(completed_ids)
    has_failure = bool(failed_ids)
    is_partial = has_success and has_failure

    manifest["partial_success"] = is_partial
    manifest["completed_clip_ids"] = completed_ids
    manifest["failed_clip_ids"] = failed_ids

    # Only set a top-level aggregate error envelope when at least one clip
    # failed and no other top-level error has already been set (e.g. by
    # _annotate_manifest_caps_refusal). Don't clobber a more specific error.
    if has_failure and not manifest.get("error"):
        if is_partial:
            manifest["error"] = {
                "code": "PARTIAL_FAILURE",
                "category": "batch_partial",
                "retryable": False,
                "message": (
                    f"{len(failed_ids)} of {manifest.get('clip_count', len(clips))} "
                    "clip(s) failed. Other clips completed successfully."
                ),
                "remediation": (
                    "Retry only failed_clip_ids; do not re-run completed_clip_ids."
                ),
            }


def _annotate_manifest_caps_refusal(manifest: Dict[str, Any]) -> None:
    """Aggregate per-clip CAPS_REFUSAL errors onto the manifest top-level.

    Counts refusals and, if any fired, copies the first refusal's structured
    fields onto `manifest["error"]` so server.py's `executed.error` propagation
    surfaces a CAPS_REFUSAL envelope on the top-level analyze response without
    callers having to walk `manifest.clips[*].error`.
    """
    clips = manifest.get("clips") or []
    refusal_count = sum(
        1 for row in clips
        if isinstance(row.get("error"), dict) and row["error"].get("code") == "CAPS_REFUSAL"
    )
    manifest["caps_refusal_clip_count"] = refusal_count
    if refusal_count <= 0:
        return
    first_refusal = next(
        (row["error"] for row in clips
         if isinstance(row.get("error"), dict) and row["error"].get("code") == "CAPS_REFUSAL"),
        None,
    )
    if first_refusal:
        manifest["error"] = {
            "code": "CAPS_REFUSAL",
            "category": "budget_exhausted",
            "retryable": False,
            "reason": first_refusal.get("reason"),
            "remediation": first_refusal.get("remediation"),
            "message": (
                f"{refusal_count} of {manifest.get('clip_count', refusal_count)} "
                "clip(s) refused — caps budget exhausted. See manifest.clips[*].caps_refusal."
            ),
        }


def _record_caps_usage(
    *,
    project_root: Optional[str],
    clip_id: Optional[str] = None,
    job_id: Optional[str] = None,
    vision_tokens: int = 0,
    transcription_tokens: int = 0,
    frames_uploaded: int = 0,
    wall_clock_ms: int = 0,
) -> None:
    """Best-effort caps usage recording. Silently degrades if the brain DB isn't
    available (e.g. project_root not resolved)."""
    if not project_root:
        return
    try:
        caps = _resolve_active_caps()
        _analysis_caps.record_usage_all_scopes(
            project_root=project_root,
            clip_id=clip_id,
            job_id=job_id,
            vision_tokens=vision_tokens,
            transcription_tokens=transcription_tokens,
            frames_uploaded=frames_uploaded,
            wall_clock_ms=wall_clock_ms,
            preset=caps.preset,
        )
    except Exception:
        pass  # caps recording is advisory; never break the analysis pipeline

from src.utils.sync_detection import detect_sync_event_capabilities
from src.utils import analysis_memory


def _ensure_path_includes_standard_tool_dirs() -> None:
    """Augment os.environ['PATH'] with common tool install dirs.

    macOS GUI apps (Claude.app, Dock/Spotlight launches) inherit launchd's bare
    PATH (/usr/bin:/bin:/usr/sbin:/sbin) and never source the user's shell rc.
    That makes shutil.which("ffprobe") return None even when Homebrew has it at
    /opt/homebrew/bin/ffprobe. Subprocess calls (subprocess.run(["ffprobe"...]))
    then also fail to find the binary. Prepending the standard tool dirs here
    fixes both detection and execution for every importer of this module.
    """
    candidates = [
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/usr/local/sbin",
        "/opt/local/bin",
        "/opt/local/sbin",
    ]
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    existing = set(parts)
    additions = [d for d in candidates if os.path.isdir(d) and d not in existing]
    if additions:
        os.environ["PATH"] = os.pathsep.join(additions + parts) if parts else os.pathsep.join(additions)


_ensure_path_includes_standard_tool_dirs()


ANALYSIS_DIR_NAME = "davinci-resolve-mcp-analysis"
HIDDEN_ANALYSIS_DIR_NAME = ".davinci-resolve-mcp-analysis"
ANALYSIS_VERSION = "0.2"
ANALYSIS_INDEX_FILENAME = "index.sqlite"
ANALYSIS_REGISTRY_FILENAME = "analysis_registry.json"
ANALYSIS_INDEX_SCHEMA_VERSION = 1
ANALYSIS_REGISTRY_SCHEMA_VERSION = 1
DEFAULT_MAX_RELATED_PROJECT_ROOTS = 32
COMMAND_TIMEOUT_SECONDS = 300
HOST_CHAT_PATHS_PROVIDER = "host_chat_paths"
HOST_CHAT_VISION_PROVIDERS = {
    "host_chat_paths",
    "host_chat",
    "current_chat",
    "chat_context",
    "mcp_sampling",
}
VISION_SCHEMA_REFERENCE = "davinci_resolve_mcp.visual_analysis.v2"
DEFAULT_TRANSCRIPTION_ENABLED = True
SOURCE_TRUST_VALUES = ("auto", "filename", "low", "medium", "high")
DEFAULT_SOURCE_TRUST = "auto"


def _resolve_source_trust(options: Any) -> str:
    """Return the effective source_trust for an analysis run.

    Pulls from options.source_trust, options.vision.source_trust (and camelCase
    aliases). Defaults to "auto" (conservative-by-default — see
    _build_vision_prompt_with_source_trust for trust-tier semantics). Unknown
    values fall back to the default rather than raising; the prompt-builder
    surfaces a note in that case.
    """
    if not isinstance(options, dict):
        return DEFAULT_SOURCE_TRUST
    vision = options.get("vision") if isinstance(options.get("vision"), dict) else {}
    candidate = (
        options.get("source_trust") or options.get("sourceTrust")
        or vision.get("source_trust") or vision.get("sourceTrust")
    )
    if not candidate:
        return DEFAULT_SOURCE_TRUST
    value = str(candidate).strip().lower()
    if value in SOURCE_TRUST_VALUES:
        return value
    return DEFAULT_SOURCE_TRUST
MARKER_PLAN_DEFAULT_COLORS = {
    "shot": "Blue",
    "best_moment": "Green",
    "qc_warning": "Red",
    "black_or_title": "Red",
}

DEFAULT_VISION_ANALYSIS_PROMPT = """Return only strict JSON for editorial media analysis (schema v2).

You are producing the foundation an editorial AI uses to assemble cuts and answer
questions about this footage. Outputs are TRUSTED BY DEFAULT — downstream tools
treat them as ground truth. Be conservative: hedge identity, intent, and value
claims when frame evidence is thin. Per-field confidence is how you signal
uncertainty (low / medium / high). Description-of-what-is-visible beats
interpretation when the evidence is ambiguous. If you cannot tell, return
`unknown` or `null` — that is a valid and useful answer.

READ every frame file listed under `frame_paths` as an image. Use the full
sequence plus the computed motion / variance and cut-boundary evidence in the
payload. Describe what changes across the clip; do not treat one frame as the
whole clip unless only one frame was provided. When frames are tagged
`shot_start`, `shot_end`, `cut_before`, `cut_after`, or `flash_candidate`,
explicitly compare adjacent boundary frames and say whether they read as a real
cut, a flash frame, a title / black insertion, or a high-motion moment inside
one continuous shot.

PER-SHOT COVERAGE IS REQUIRED. The payload's `shot_table` lists every detected
shot. Emit one `shot_descriptions` entry for every `shot_index` in `shot_table`.
Each entry's content must be grounded in THAT shot's frames only — never paste
the clip summary or a neighbouring shot's content. If a shot has no associated
frames (sampler missed it), say so explicitly in `description` and set
`qc_flags: ["no_in_shot_frame_sampled"]`.

CROSS-SHOT RELATIONSHIPS. After describing every shot individually, fill the
`relationships` block on each shot with pattern observations only (which shots
appear to be the same setup, which continue action from prior shots, which look
like alternate takes). DO NOT suggest editorial pairings (no "cuts well to" /
"cuts poorly to" — those are user-side runtime queries, not stored fields).

ENUMS ARE CLOSED. Use only the documented values. If none fits, use `unknown`.

CONFIDENCE PER GROUP. Each shot carries confidence ratings per major field
group. Default `medium` unless evidence is clearly strong (`high`) or thin
(`low`). Downstream tools weight outputs by confidence.

BEST MOMENT IS NULLABLE. Only populate `best_moment` if there is a moment within
the shot an editor would naturally point to. If the shot is a sustained flat
beat, return `null` and set `best_moment_present: false`. Forced best_moments
add noise.

CONTINUITY QC. Surface eye-line and screen-direction observations as QC
questions ("possible eye-line mismatch between shots 12 and 13") — not as
assertions. Skip prop-continuity claims (we cannot reliably track props).

V2 SCHEMA:
{
  "success": true,
  "provider": "host_chat_paths",
  "schema_version": "2.0",

  "clip_summary": "Colleague-style first-impression paragraph, 2-4 sentences. Primary editorial summary; downstream tools use this as the clip's Description.",
  "clip_summary_oneliner": "Elevator-pitch single sentence describing the clip.",

  "editorial_classification": {
    "primary_use": "action|interview|b_roll|insert|establishing|montage|screen_recording|titles|finished_video|other",
    "select_potential": "low|medium|high",
    "energy_arc": "rising|falling|flat|spiky|varied|unknown",
    "style": "documentary|narrative|experimental|commercial|mixed_genre|unknown",
    "genre_indicators": [],
    "reason": "Why this classification."
  },

  "slate": {
    "slate_visible": false,
    "scene": "", "shot": "", "take": "", "camera": "", "roll": "", "date": "", "production": "",
    "visible_text": [],
    "confidence": {
      "overall": "low|medium|high",
      "scene": "low|medium|high", "shot": "low|medium|high",
      "take": "low|medium|high", "camera": "low|medium|high"
    }
  },

  "shot_descriptions": [
    {
      "shot_index": 1,
      "time_seconds_start": 0.0,
      "time_seconds_end": 1.969,
      "frame_indices_used": [1, 2, 3],

      "visual": {
        "shot_size": "wide|medium_wide|medium|medium_close|close|extreme_close|insert|establishing|other",
        "framing": "single|two_shot|group|crowd|empty|insert|establishing|abstract",
        "camera_height": "eye_level|high_angle|low_angle|birds_eye|dutch|unknown",
        "camera_motion": "locked|pan|tilt|dolly|handheld|crane|drone|zoom|composite|other",
        "motion_direction": "left|right|up|down|in|out|clockwise|counter_clockwise|none",
        "depth_of_field": "deep|shallow|rack_focus|unknown",
        "lens_character": "wide|normal|tele|fisheye|unknown",
        "lens_format": "spherical|anamorphic|fisheye|unknown",
        "lighting": "natural|high_key|low_key|practical|backlit|silhouette|mixed|unknown",
        "color_mood": "warm|cool|neutral|desaturated|saturated|monochrome|unnatural|unknown",
        "composition_notes": "Short freeform note on composition."
      },

      "content": {
        "primary_subject": {
          "type": "person|object|landscape|interior|vehicle|animal|text_graphic|abstract",
          "description": "Short concrete description.",
          "performance": {
            "eye_line": "to_camera|off_left|off_right|down|up|closed|unknown",
            "energy": "low|medium|high",
            "emotional_register": "Short freeform observation, e.g. 'looks tense, jaw clenched'. Use null if no person."
          }
        },
        "secondary_subjects": [],
        "action": "1-sentence description of what's happening.",
        "location": "1-sentence description of where this is.",
        "visible_text": [],
        "objects_of_note": [],
        "audio_character": "silence|sync_dialogue|vo_dialogue|music|ambient|sfx|mixed|unknown"
      },

      "production": {
        "composite_shot": false,
        "composite_panels": null,
        "vfx_present": "none|minor|major|unknown"
      },

      "editorial": {
        "editorial_role": "establishing|coverage|reaction|insert|transition|b_roll|montage_element|titles_or_graphics|bumper|other",
        "select_potential": "low|medium|high",
        "best_moment_present": false,
        "best_moment": null,
        "pacing": "still|moderate|kinetic|variable",
        "stillness_type": "held_tension|quiet|contemplative|transitional|dead_air|unknown|null",
        "pacing_note": "Use when pacing is still or variable; null otherwise."
      },

      "cuttability": {
        "cut_in": {"quality": "poor|ok|clean", "notes": ""},
        "cut_out": {"quality": "poor|ok|clean", "notes": ""},
        "match_action_in": false,
        "match_action_out": false,
        "cut_compatibility_hints": "Freeform notes for downstream assembly logic."
      },

      "relationships": {
        "same_setup_as": [],
        "continues_from": [],
        "alt_take_of": []
      },

      "transition_in": {"type": "cut|fade|dissolve|wipe|unknown", "duration_seconds": 0},
      "transition_out": {"type": "cut|fade|dissolve|wipe|unknown", "duration_seconds": 0},

      "confidence": {
        "visual": "low|medium|high",
        "content": "low|medium|high",
        "audio": "low|medium|high",
        "editorial": "low|medium|high",
        "cuttability": "low|medium|high"
      },

      "description": "1-3 sentences, colleague-style note, editorially useful.",
      "qc_flags": []
    }
  ],

  "cross_shot": {
    "coverage_groups": [
      {"label": "interview master + close", "shot_indices": [3, 5, 7], "setup_description": ""}
    ],
    "continuity_chains": [
      {"label": "action continues across shots 20-25", "shot_indices": [20, 21, 22, 23, 24, 25], "action_description": ""}
    ],
    "alt_take_groups": [],
    "energy_arc": "rising|falling|flat|spiky|varied|unknown"
  },

  "editing_notes": {
    "best_moments": ["List of notable clip-wide moments (separate from per-shot best_moment)."],
    "continuity_flags": [],
    "qc_flags": [],
    "search_tags": ["Keywords for cross-clip retrieval. This is what populates the clip's Keywords metadata in Resolve."]
  },

  "analysis_keyframes": [
    {
      "time_seconds": 0.0,
      "selection_reason": "first_usable|midpoint|last_usable|scene_change|cut_before|cut_after|shot_start|shot_end|shot_representative|shot_progress|flash_candidate|motion_peak|interval",
      "description": "What is visible in this frame.",
      "editing_value": "How an editor might use this moment.",
      "qc_flags": []
    }
  ],

  "qc": {
    "warnings": [],
    "continuity_observations": [
      {"kind": "eye_line|screen_direction", "shot_indices": [12, 13], "observation": "Possible eye-line break between A's looking-left in shot 12 and looking-right in shot 13.", "confidence": "low|medium|high"}
    ],
    "coverage_gaps": []
  },

  "confidence": {
    "visual": "low|medium|high",
    "motion": "computed",
    "transcript": "unavailable|provided"
  }
}

Do not include markdown fences, prose outside JSON, or keys outside this schema.
When a field is not applicable (e.g. performance fields on a landscape shot,
composite_panels when composite_shot is false, best_moment for flat shots),
use null. When evidence is thin, use the documented `unknown` enum value and
mark confidence `low`. Never invent identity, intent, or editorial value beyond
what the frames support."""

DEPTHS = {"quick", "standard", "deep", "custom"}
DEFAULT_DEPTH = "standard"
FRAME_CAPS = {
    "quick": 0,
    "standard": 8,
    "deep": 24,
    "custom": 8,
}
HARD_FRAME_CAP = 512

# ── Frame-sampling modes ─────────────────────────────────────────────────────
# How many frames a clip gets is governed by a `sampling_mode`. `depth` still
# governs *which* analysis layers run; the mode governs frame coverage + cost.
#
#   fixed           "Economy"            — flat N frames (depth-derived / max_analysis_frames),
#                                          independent of clip length. Most predictable cost.
#   per_minute      "Balanced"           — N = clamp(minutes * frames_per_minute, floor, ceiling).
#                                          Cost is linear in footage length; content-blind.
#   adaptive_capped "Thorough"           — content-aware (per-shot boundaries + flashes), bounded
#                                          by [floor, frame_ceiling]. Best coverage, bounded cost.
#   adaptive        "Thorough (uncapped)" — content-aware, bounded only by the absolute HARD_FRAME_CAP.
#                                          Use only when clips are known to be short/few.
#
# The math-layer default is `adaptive` so any caller that doesn't thread a
# sampling config keeps the legacy demand-driven behaviour. The *product*
# default (what new analysis runs use) is resolved at the preference layer in
# server.py and recommends "adaptive_capped" (Thorough).
SAMPLING_MODES = {"fixed", "per_minute", "adaptive", "adaptive_capped"}
DEFAULT_SAMPLING_MODE = "adaptive"
RECOMMENDED_SAMPLING_MODE = "adaptive_capped"
DEFAULT_FRAMES_PER_MINUTE = 4.0
DEFAULT_FRAME_FLOOR = 3
DEFAULT_FRAME_CEILING = 80

# Thoroughness ranking — used for cache reuse: a richer prior report satisfies a
# cheaper mode, but switching *up* forces a re-sample.
SAMPLING_MODE_RANK = {"fixed": 0, "per_minute": 1, "adaptive_capped": 2, "adaptive": 3}

# User-facing labels (prompt + control panel).
SAMPLING_MODE_LABELS = {
    "fixed": "Economy",
    "per_minute": "Balanced",
    "adaptive_capped": "Thorough",
    "adaptive": "Thorough (uncapped)",
}

_SAMPLING_MODE_ALIASES = {
    "economy": "fixed", "fixed": "fixed", "flat": "fixed",
    "balanced": "per_minute", "per_minute": "per_minute", "perminute": "per_minute",
    "per-minute": "per_minute", "duration": "per_minute",
    "thorough": "adaptive_capped", "adaptive_capped": "adaptive_capped",
    "adaptive-capped": "adaptive_capped", "capped": "adaptive_capped",
    "thorough_uncapped": "adaptive", "thorough (uncapped)": "adaptive",
    "adaptive": "adaptive", "uncapped": "adaptive",
}


def normalize_sampling_mode(value: Any, default: Optional[str] = None) -> Optional[str]:
    """Resolve a user-supplied mode string (label or key) to a canonical mode."""
    raw = str(value or "").strip().lower().replace("_", "_")
    return _SAMPLING_MODE_ALIASES.get(raw, default)


def _resolve_sampling_config(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Read sampling mode + tunables from analysis params, applying defaults."""
    params = params or {}

    def _first(*keys: str) -> Any:
        for key in keys:
            if key in params and params[key] is not None:
                return params[key]
        return None

    mode = normalize_sampling_mode(
        _first("sampling_mode", "samplingMode"), default=DEFAULT_SAMPLING_MODE
    ) or DEFAULT_SAMPLING_MODE

    def _pos_float(value: Any, fallback: float) -> float:
        try:
            f = float(value)
        except (TypeError, ValueError):
            return fallback
        return f if f > 0 else fallback

    rate = _pos_float(_first("frames_per_minute", "framesPerMinute"), DEFAULT_FRAMES_PER_MINUTE)
    floor = int(_pos_float(_first("frame_floor", "frameFloor"), DEFAULT_FRAME_FLOOR))
    ceiling = int(_pos_float(_first("frame_ceiling", "frameCeiling"), DEFAULT_FRAME_CEILING))
    if ceiling < floor:
        ceiling = floor
    return {
        "mode": mode,
        "frames_per_minute": rate,
        "frame_floor": floor,
        "frame_ceiling": ceiling,
    }


def _clamp_int(value: Any, low: int, high: int) -> int:
    if high < low:
        high = low
    v = int(value)
    if v < low:
        return low
    if v > high:
        return high
    return v


def slugify(value: Any, fallback: str = "untitled") -> str:
    raw = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", raw)
    slug = re.sub(r"-+", "-", slug).strip("-._")
    return slug or fallback


def short_hash(value: Any, length: int = 10) -> str:
    raw = str(value or "").encode("utf-8", errors="replace")
    return hashlib.sha1(raw).hexdigest()[:length]


def project_directory_name(project_name: Any, project_id: Any = None) -> str:
    basis = project_id or project_name or "project"
    return f"{slugify(project_name, 'project')}-{short_hash(basis)}"


def stable_clip_basis(record: Dict[str, Any]) -> str:
    """Return the canonical rename-stable identity used to hash a report folder.

    The canonical basis is the *normalized file path*: it is present on both
    Resolve-derived and path-based batch records, it survives a Media Pool
    rename, and a genuine relink to a different file is handled separately as a
    superseded source. Resolve-internal ids (clip_id/media_id) are absent from
    path-based records and not portable across project copies, so they are only
    used when no file path is available; the display name is the last resort.

    Folder *resolution* (matching an existing report) must tolerate the legacy
    bases too — see :func:`stable_clip_match_hashes`.
    """
    file_path = record.get("file_path")
    if file_path:
        return normalize_path(file_path)
    return str(
        record.get("clip_id")
        or record.get("media_id")
        or record.get("clip_name")
        or "clip"
    )


def stable_clip_hash(record: Dict[str, Any]) -> str:
    """Return the canonical 12-char hash that anchors a clip's report folder."""
    return short_hash(stable_clip_basis(record), 12)


def stable_clip_match_hashes(record: Dict[str, Any]) -> List[str]:
    """All folder hashes that could identify this clip's existing report.

    Returns the canonical hash first, followed by legacy bases so reports
    written before the canonical file-path scheme (clip_id-first, or a raw
    un-normalized path) still resolve without an on-disk migration. The display
    name is only used when nothing more unique is available, so two different
    clips that merely share a name are never matched to the same report.
    """
    hashes: List[str] = []
    seen: set = set()

    def add(value: Any) -> None:
        if not value:
            return
        digest = short_hash(value, 12)
        if digest not in seen:
            seen.add(digest)
            hashes.append(digest)

    file_path = record.get("file_path")
    if file_path:
        add(normalize_path(file_path))  # canonical
        add(str(file_path))             # legacy: raw, un-normalized path
    add(record.get("clip_id"))          # legacy: clip_id-first scheme
    add(record.get("media_id"))
    if not hashes:
        add(record.get("clip_name") or "clip")
    return hashes


def clip_directory_hash(name: Any) -> Optional[str]:
    """Extract the trailing stable hash from a clip report folder name.

    Folder names are ``<label>-<hash>`` where ``<label>`` is the (rename-prone)
    display slug and ``<hash>`` is :func:`stable_clip_hash`. A bare ``<hash>``
    folder (no slug) is also accepted. Returns the hash, or ``None`` if the
    trailing token is not a 12-char hex hash.
    """
    base = os.path.basename(str(name or "").rstrip("/\\"))
    suffix = base.rsplit("-", 1)[-1]
    if re.fullmatch(r"[0-9a-f]{12}", suffix):
        return suffix
    return None


def stable_clip_directory(record: Dict[str, Any]) -> str:
    label = slugify(record.get("clip_name") or Path(str(record.get("file_path") or "clip")).stem, "clip")
    return f"{label}-{stable_clip_hash(record)}"


def resolve_clip_directory(project_root: str, record: Dict[str, Any]) -> str:
    """Return the report directory for a clip, reusing an existing one if found.

    Writes go through here so a clip that was renamed, or analyzed under a legacy
    hash basis (e.g. clip_id-first, or a path-based batch report), reuses its
    existing folder instead of orphaning it under a freshly minted name. Matches
    by canonical hash first, then any legacy hash; falls back to the canonical
    new path when nothing exists yet.
    """
    clips_root = os.path.join(project_root, "clips")
    # Fast path: the canonical folder already exists by exact name. This is the
    # steady state (re-analysis of an already-canonical clip) and avoids a full
    # directory scan per clip on a batch run.
    canonical_dir = os.path.join(clips_root, stable_clip_directory(record))
    if os.path.isdir(canonical_dir):
        return normalize_path(canonical_dir)
    match = stable_clip_match_hashes(record)
    if match and os.path.isdir(clips_root):
        canonical = match[0]
        match_set = set(match)
        legacy_hit: Optional[str] = None
        try:
            entries = sorted(os.listdir(clips_root))
        except OSError:
            entries = []
        for entry in entries:
            candidate = os.path.join(clips_root, entry)
            if not os.path.isdir(candidate):
                continue
            folder_hash = clip_directory_hash(entry)
            if not folder_hash:
                continue
            if folder_hash == canonical:
                return normalize_path(candidate)
            if folder_hash in match_set and legacy_hit is None:
                legacy_hit = candidate
        if legacy_hit:
            return normalize_path(legacy_hit)
    return normalize_path(os.path.join(clips_root, stable_clip_directory(record)))


CLIP_INDEX_SCHEMA_VERSION = 1


def clip_index_path(project_root: str) -> str:
    """Path of the per-project clip index (a sidecar under clips/)."""
    return os.path.join(project_root, "clips", "index.json")


def _clip_dir_signature(clips_root: str) -> str:
    """Cheap fingerprint of the analyzed clip dirs (each analysis.json's name,
    mtime, and size) so the persisted index can be reused until a report is
    added, removed, or rewritten — without reparsing every report each poll."""
    parts: List[str] = []
    try:
        entries = sorted(os.listdir(clips_root))
    except OSError:
        return "0:none"
    for entry in entries:
        report = os.path.join(clips_root, entry, "analysis.json")
        try:
            stat = os.stat(report)
        except OSError:
            continue
        parts.append(f"{entry}:{stat.st_mtime_ns}:{stat.st_size}")
    return f"{len(parts)}:{short_hash('|'.join(parts), 16)}"


def build_clip_index(project_root: str) -> Dict[str, Any]:
    """Build and persist a hash -> folder index for the project's reports.

    Unlike a folder-name scan (which only knows the single hash baked into each
    directory name), this reads each report's ``clip`` block and indexes ALL of
    its stable ids (normalized + raw file path, clip_id, media_id). That lets the
    analyzed-count match a clip by any id it still carries — e.g. an offline clip
    that no longer reports a file path but still has its clip_id. See #51.
    """
    clips_root = os.path.join(project_root, "clips")
    hash_to_folder: Dict[str, str] = {}
    if os.path.isdir(clips_root):
        try:
            entries = sorted(os.listdir(clips_root))
        except OSError:
            entries = []
        for entry in entries:
            report_path = os.path.join(clips_root, entry, "analysis.json")
            if not os.path.isfile(report_path):
                continue
            try:
                report = _read_json(report_path)
            except (OSError, json.JSONDecodeError):
                continue
            clip_block = report.get("clip") if isinstance(report.get("clip"), dict) else {}
            hashes = set(stable_clip_match_hashes(clip_block))
            folder_hash = clip_directory_hash(entry)  # the hash baked into the name
            if folder_hash:
                hashes.add(folder_hash)
            for digest in hashes:
                hash_to_folder.setdefault(digest, entry)
    payload = {
        "schema_version": CLIP_INDEX_SCHEMA_VERSION,
        "signature": _clip_dir_signature(clips_root),
        "hash_to_folder": hash_to_folder,
    }
    if os.path.isdir(clips_root):
        try:
            _write_json(clip_index_path(project_root), payload)
        except OSError:
            pass
    return payload


def load_clip_index(project_root: str, *, rebuild_if_stale: bool = True) -> Dict[str, Any]:
    """Load the persisted clip index, rebuilding it if missing or stale.

    Freshness is decided by the cheap directory signature, so the common poll
    pays a stat-per-report instead of a full JSON reparse; a rebuild only happens
    when a report is added, removed, or rewritten.
    """
    clips_root = os.path.join(project_root, "clips")
    current_sig = _clip_dir_signature(clips_root)
    try:
        data = _read_json(clip_index_path(project_root))
    except (OSError, json.JSONDecodeError):
        data = None
    if (
        isinstance(data, dict)
        and data.get("schema_version") == CLIP_INDEX_SCHEMA_VERSION
        and data.get("signature") == current_sig
        and isinstance(data.get("hash_to_folder"), dict)
    ):
        return data
    if rebuild_if_stale:
        return build_clip_index(project_root)
    return {
        "schema_version": CLIP_INDEX_SCHEMA_VERSION,
        "signature": current_sig,
        "hash_to_folder": {},
    }


def normalize_path(path: Any) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))


def _is_relative_to(path: str, parent: str) -> bool:
    try:
        common = os.path.commonpath([path, parent])
    except ValueError:
        return False
    return common == parent


def _non_empty_source_paths(source_paths: Optional[Iterable[Any]]) -> List[str]:
    out = []
    for source in source_paths or []:
        if source:
            out.append(normalize_path(source))
    return out


def validate_output_root(output_root: Any, source_paths: Optional[Iterable[Any]] = None) -> Tuple[bool, List[str]]:
    """Validate that an analysis output root is not adjacent to source media."""
    errors: List[str] = []
    root = normalize_path(output_root)

    for source in _non_empty_source_paths(source_paths):
        if root == source:
            errors.append(f"analysis root cannot equal a source file path: {source}")
            continue
        parent = os.path.dirname(source)
        if parent and _is_relative_to(root, parent):
            errors.append(
                "analysis root cannot be inside a source media directory: "
                f"{root} is under {parent}"
            )

    return not errors, errors


def _analysis_root_contains_reports(project_root: str) -> bool:
    clips_root = os.path.join(project_root, "clips")
    if not os.path.isdir(clips_root):
        return False
    for _, _, filenames in os.walk(clips_root):
        if "analysis.json" in filenames:
            return True
    return False


def related_analysis_project_roots(project_root: Any, *, limit: int = DEFAULT_MAX_RELATED_PROJECT_ROOTS) -> List[str]:
    """Return sibling project analysis roots that contain reports.

    Published projects can be duplicated or renamed in Resolve, which changes
    the active project root while the source media and prior reports remain
    valid. This bounded sibling scan lets reuse find those reports by signature.
    """
    if not project_root:
        return []
    active = normalize_path(project_root)
    base_root = os.path.dirname(active)
    if not os.path.isdir(base_root):
        return []

    candidates: List[Tuple[float, str]] = []
    try:
        entries = os.listdir(base_root)
    except OSError:
        return []
    for entry in entries:
        candidate = normalize_path(os.path.join(base_root, entry))
        if candidate == active or not os.path.isdir(candidate):
            continue
        if not _analysis_root_contains_reports(candidate):
            continue
        try:
            mtime = os.path.getmtime(os.path.join(candidate, "clips"))
        except OSError:
            mtime = 0.0
        candidates.append((mtime, candidate))

    candidates.sort(key=lambda row: (-row[0], row[1]))
    return [candidate for _, candidate in candidates[: max(0, int(limit or 0))]]


def _analysis_base_root_for_project_root(project_root: Any) -> Optional[str]:
    if not project_root:
        return None
    return os.path.dirname(normalize_path(project_root))


def analysis_registry_path(project_root: Any) -> Optional[str]:
    base_root = _analysis_base_root_for_project_root(project_root)
    if not base_root:
        return None
    return os.path.join(base_root, ANALYSIS_REGISTRY_FILENAME)


def _analysis_report_project_root(path: Any) -> Optional[str]:
    candidate = normalize_path(path)
    if os.path.basename(candidate) != "analysis.json":
        return None
    clip_dir = os.path.dirname(candidate)
    clips_dir = os.path.dirname(clip_dir)
    if os.path.basename(clips_dir) != "clips":
        return None
    return os.path.dirname(clips_dir)


def _registry_entry_from_report(report_path: str, report: Dict[str, Any]) -> Dict[str, Any]:
    clip = report.get("clip") if isinstance(report.get("clip"), dict) else {}
    signature = report.get("analysis_signature") if isinstance(report.get("analysis_signature"), dict) else {}
    profile = report.get("analysis_profile") if isinstance(report.get("analysis_profile"), dict) else {}
    project_root = _analysis_report_project_root(report_path)
    return {
        "analysis_json": normalize_path(report_path),
        "project_root": project_root,
        "source_file": normalize_path(report.get("source_file") or clip.get("file_path")) if (report.get("source_file") or clip.get("file_path")) else "",
        "clip_id": str(clip.get("clip_id") or ""),
        "media_id": str(clip.get("media_id") or ""),
        "clip_name": str(clip.get("clip_name") or ""),
        "analysis_version": str(report.get("analysis_version") or ""),
        "analysis_signature": signature,
        "signature_hash": str(signature.get("signature_hash") or ""),
        "depth": profile.get("depth", ""),
        "source_trust": str(profile.get("source_trust") or "") or DEFAULT_SOURCE_TRUST,
        "vision_enabled": bool(profile.get("vision_enabled", False)),
        "transcription_enabled": bool(profile.get("transcription_enabled", False)),
        "analyzed_at": report.get("analyzed_at"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _read_analysis_registry(project_root: Any) -> Dict[str, Any]:
    path = analysis_registry_path(project_root)
    if not path or not os.path.isfile(path):
        return {"entries": []}
    try:
        payload = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return {"entries": []}
    if not isinstance(payload, dict):
        return {"entries": []}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        payload["entries"] = []
    return payload


def _registry_entry_matches_record(entry: Dict[str, Any], record: Dict[str, Any]) -> bool:
    entry_source = _normalized_report_match_value(entry.get("source_file"), path_like=True)
    record_source = _normalized_report_match_value(record.get("file_path"), path_like=True)
    if entry_source and record_source and entry_source == record_source:
        return True
    for key in ("clip_id", "media_id"):
        entry_value = _normalized_report_match_value(entry.get(key))
        record_value = _normalized_report_match_value(record.get(key))
        if entry_value and record_value and entry_value == record_value:
            return True
    return False


REGISTRY_PRESERVED_FIELDS = ("superseded_by_relink", "superseded_at", "superseded_reason")


def update_analysis_registry(project_root: str, report_paths: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    """Update the per-analysis-root report registry from known analysis reports.

    Preserves relink-invalidation flags (superseded_by_relink, superseded_at,
    superseded_reason) across rebuilds so re-running analysis writeback does
    not silently clear a stale-mark applied by a prior replace_clip event.
    """
    root = normalize_path(project_root)
    base_root = _analysis_base_root_for_project_root(root)
    registry_path = analysis_registry_path(root)
    if not base_root or not registry_path:
        return {"success": False, "error": "Invalid analysis project root for registry"}

    existing = _read_analysis_registry(root)
    entries_by_path: Dict[str, Dict[str, Any]] = {}
    preserved_flags_by_path: Dict[str, Dict[str, Any]] = {}
    for entry in existing.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        report_path = entry.get("analysis_json")
        if not report_path:
            continue
        normalized_path = normalize_path(report_path)
        preserved = {key: entry[key] for key in REGISTRY_PRESERVED_FIELDS if entry.get(key) not in (None, "", False)}
        if preserved:
            preserved_flags_by_path[normalized_path] = preserved
        if os.path.isfile(normalized_path):
            entries_by_path[normalized_path] = dict(entry, analysis_json=normalized_path)

    if report_paths is None:
        candidate_paths = list(_iter_analysis_report_files(root))
    else:
        candidate_paths = [normalize_path(path) for path in report_paths if path]

    failed_reports: List[Dict[str, str]] = []
    updated_count = 0
    for report_path in candidate_paths:
        normalized_path = normalize_path(report_path)
        report_project_root = _analysis_report_project_root(normalized_path)
        if not report_project_root or not os.path.isfile(normalized_path):
            continue
        try:
            if os.path.commonpath([normalize_path(report_project_root), base_root]) != base_root:
                continue
        except ValueError:
            continue
        try:
            report = _read_json(normalized_path)
        except (OSError, json.JSONDecodeError) as exc:
            failed_reports.append({"path": normalized_path, "error": str(exc)})
            continue
        new_entry = _registry_entry_from_report(normalized_path, report)
        preserved = preserved_flags_by_path.get(normalized_path)
        if preserved:
            new_entry.update(preserved)
        entries_by_path[normalized_path] = new_entry
        updated_count += 1

    payload = {
        "success": True,
        "schema_version": ANALYSIS_REGISTRY_SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "base_root": base_root,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entry_count": len(entries_by_path),
        "updated_count": updated_count,
        "failed_report_count": len(failed_reports),
        "failed_reports": failed_reports[:50],
        "entries": sorted(entries_by_path.values(), key=lambda row: (str(row.get("source_file") or ""), str(row.get("analysis_json") or ""))),
    }
    try:
        _write_json(registry_path, payload)
    except OSError as exc:
        return {"success": False, "error": str(exc), "registry_path": registry_path}
    return {k: v for k, v in payload.items() if k != "entries"} | {"registry_path": registry_path}


def mark_registry_stale_for_clip(
    *,
    project_name: Any = None,
    project_id: Any = None,
    project_root: Any = None,
    analysis_root: Any = None,
    clip_id: Any = None,
    media_id: Any = None,
    source_file: Any = None,
    reason: str = "source_relinked",
) -> Dict[str, Any]:
    """Mark analysis_registry entries matching this clip as superseded by relink.

    Called from Resolve clip-replacement operations (replace_clip and friends)
    after a successful mutation so coverage_report and the reuse pipeline stop
    silently reusing the prior analysis for what is now a different underlying
    media file.

    Either `project_root` OR `project_name` (with optional `project_id`) must
    be supplied so the active analysis registry can be located.

    Matches entries by clip_id, media_id, or source_file (any match flags the
    entry). Does NOT delete the report file on disk — colorists and editors
    may still want the prior context. Sets `superseded_by_relink=true`,
    `superseded_at`, and `superseded_reason` on the registry entry; these
    flags are preserved across future `update_analysis_registry` rebuilds.

    Returns {"success": bool, "matched": int, "registry_path": str, ...}.
    """
    if not (clip_id or media_id or source_file):
        return {
            "success": False,
            "error": "mark_registry_stale_for_clip requires at least one of clip_id, media_id, or source_file",
        }

    resolved_root: Optional[str] = None
    if project_root:
        resolved_root = normalize_path(project_root)
    else:
        if project_name is None:
            return {
                "success": False,
                "error": "mark_registry_stale_for_clip requires project_root or project_name",
            }
        resolved = resolve_output_root(
            project_name=project_name,
            project_id=project_id,
            analysis_root=analysis_root,
            source_paths=[source_file] if source_file else [],
            create=False,
        )
        if not resolved.get("success"):
            return {
                "success": False,
                "error": "Could not resolve analysis project root for registry invalidation",
                "details": resolved,
            }
        resolved_root = resolved["project_root"]

    registry_path = analysis_registry_path(resolved_root)
    if not registry_path:
        return {"success": False, "error": "No registry path available for project root", "project_root": resolved_root}
    if not os.path.isfile(registry_path):
        return {
            "success": True,
            "matched": 0,
            "registry_path": registry_path,
            "project_root": resolved_root,
            "note": "No registry on disk yet; nothing to invalidate.",
        }

    payload = _read_analysis_registry(resolved_root)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return {"success": False, "error": "Registry corrupted: entries is not a list", "registry_path": registry_path}

    record_like: Dict[str, Any] = {}
    if clip_id:
        record_like["clip_id"] = str(clip_id)
    if media_id:
        record_like["media_id"] = str(media_id)
    if source_file:
        record_like["file_path"] = str(source_file)

    superseded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    matched_entries: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not _registry_entry_matches_record(entry, record_like):
            continue
        entry["superseded_by_relink"] = True
        entry["superseded_at"] = superseded_at
        entry["superseded_reason"] = str(reason or "source_relinked")
        matched_entries.append(str(entry.get("analysis_json") or ""))

    if not matched_entries:
        return {
            "success": True,
            "matched": 0,
            "registry_path": registry_path,
            "project_root": resolved_root,
            "note": "No registry entries matched the supplied clip identifiers.",
        }

    payload["entries"] = entries
    payload["updated_at"] = superseded_at
    try:
        _write_json(registry_path, payload)
    except OSError as exc:
        return {"success": False, "error": str(exc), "registry_path": registry_path}
    return {
        "success": True,
        "matched": len(matched_entries),
        "matched_report_paths": matched_entries,
        "registry_path": registry_path,
        "project_root": resolved_root,
        "reason": str(reason or "source_relinked"),
        "superseded_at": superseded_at,
    }


def registry_entry_superseded_info(project_root: Any, report_path: Any) -> Optional[Dict[str, Any]]:
    """Return the superseded-by-relink metadata for a report path, if any.

    Used by reuse-check and coverage_report to surface relink staleness even
    when the on-disk report still passes signature checks.
    """
    if not project_root or not report_path:
        return None
    normalized_path = normalize_path(report_path)
    payload = _read_analysis_registry(project_root)
    for entry in payload.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if normalize_path(entry.get("analysis_json") or "") != normalized_path:
            continue
        if entry.get("superseded_by_relink"):
            return {
                "superseded_by_relink": True,
                "superseded_at": entry.get("superseded_at"),
                "superseded_reason": entry.get("superseded_reason") or "source_relinked",
            }
        return None
    return None


def resolve_output_root(
    *,
    project_name: Any,
    project_id: Any = None,
    analysis_root: Any = None,
    source_paths: Optional[Iterable[Any]] = None,
    create: bool = False,
) -> Dict[str, Any]:
    """Resolve a project-scoped analysis root and validate source separation."""
    project_dir = project_directory_name(project_name, project_id)
    if analysis_root:
        base_root = normalize_path(analysis_root)
    else:
        base_root = normalize_path(Path.home() / "Documents" / ANALYSIS_DIR_NAME)

    # V2 P13: Don't double-append project_dir when the caller passed an
    # analysis_root that already terminates in the project slug (e.g. when
    # a previous call's project_root is re-used as the new analysis_root).
    # Previous behavior created nested {base}/{slug}/{slug}/ trees on disk.
    base_basename = os.path.basename(base_root.rstrip("/"))
    if base_basename == project_dir:
        output_root = base_root
    else:
        # Treat the provided root as a base by default so every project remains
        # isolated even when users choose a shared custom analysis location.
        output_root = normalize_path(os.path.join(base_root, project_dir))
    ok, errors = validate_output_root(output_root, source_paths)

    if ok and create:
        os.makedirs(output_root, exist_ok=True)

    return {
        "success": ok,
        "analysis_version": ANALYSIS_VERSION,
        "base_root": base_root,
        "project_root": output_root,
        "project_directory": project_dir,
        "project_name": project_name,
        "project_id": project_id,
        "errors": errors,
    }


# ── Runtime-tool install metadata ────────────────────────────────────────────
# Per-tool install commands keyed by platform. The dashboard reads this through
# detect_capabilities() so each missing-tool chip can render a one-click "Copy"
# or "Ask Claude/Codex" affordance. We never execute installs server-side; the
# user runs the command themselves, or lets their agent (Claude Code / Codex)
# run it with its own confirmation gating.
TOOL_INSTALL: Dict[str, Dict[str, Any]] = {
    "ffprobe": {
        "label": "ffprobe",
        "bundle": "ffmpeg_suite",
        "required_for": ["technical metadata", "scene detection", "sync detection"],
        "commands": {
            "macos": "brew install ffmpeg",
            "linux_debian": "sudo apt install ffmpeg",
            "linux_rhel": "sudo dnf install ffmpeg",
            "linux_arch": "sudo pacman -S ffmpeg",
            "windows": "winget install --id=Gyan.FFmpeg -e",
        },
        "verify": "ffprobe -version",
        "notes": "Bundled with ffmpeg. One install covers both ffprobe and ffmpeg.",
    },
    "ffmpeg": {
        "label": "ffmpeg",
        "bundle": "ffmpeg_suite",
        "required_for": ["frame extraction", "motion analysis", "audio decode for sync"],
        "commands": {
            "macos": "brew install ffmpeg",
            "linux_debian": "sudo apt install ffmpeg",
            "linux_rhel": "sudo dnf install ffmpeg",
            "linux_arch": "sudo pacman -S ffmpeg",
            "windows": "winget install --id=Gyan.FFmpeg -e",
        },
        "verify": "ffmpeg -version",
        "notes": "Bundled with ffprobe. One install covers both.",
    },
    "whisper_cli": {
        "label": "openai-whisper",
        "bundle": "transcription",
        "required_for": ["transcription (CPU/GPU, Python)"],
        "commands": {
            "all": "pip install -U openai-whisper",
        },
        "verify": "whisper --help",
        "notes": "Pure-Python reference implementation. Choose this OR whisper_cpp OR mlx_whisper.",
    },
    "ollama_embeddings": {
        "label": "ollama + nomic-embed-text",
        "bundle": "embeddings",
        "required_for": ["semantic search (text embeddings)", "find_similar"],
        "commands": {
            "macos": "brew install ollama && ollama pull nomic-embed-text",
            "linux": "curl -fsSL https://ollama.com/install.sh | sh && ollama pull nomic-embed-text",
            "windows": "winget install Ollama.Ollama, then: ollama pull nomic-embed-text",
        },
        "verify": "ollama list",
        "notes": "Local embedding model (~270 MB). sentence-transformers is an alternative text backend.",
    },
    "open_clip": {
        "label": "open_clip (CLIP visual embeddings)",
        "bundle": "embeddings",
        "required_for": ["visual similarity (find_similar kind=visual)", "cross-clip entity clustering"],
        "commands": {
            "all": "pip install open_clip_torch",
        },
        "verify": "python -c \"import open_clip\"",
        "notes": "Needs torch. Model weights (~350 MB) download on first use.",
    },
    "clap_audio": {
        "label": "CLAP (audio embeddings)",
        "bundle": "embeddings",
        "required_for": ["audio similarity (find_similar kind=audio)"],
        "commands": {
            "all": "pip install transformers",
        },
        "verify": "python -c \"import transformers\"",
        "notes": (
            "Needs torch + ffmpeg. Uses laion/clap-htsat-unfused (~600 MB, "
            "downloads on first use); the laion_clap package works as an "
            "alternative backend."
        ),
    },
    "whisper_cpp": {
        "label": "whisper.cpp",
        "bundle": "transcription",
        "required_for": ["transcription (fast C++ backend)"],
        "commands": {
            "macos": "brew install whisper-cpp",
            "linux_debian": "Build from source: https://github.com/ggerganov/whisper.cpp",
            "linux_rhel": "Build from source: https://github.com/ggerganov/whisper.cpp",
            "linux_arch": "yay -S whisper.cpp",
            "windows": "Build from source or use WSL: https://github.com/ggerganov/whisper.cpp",
        },
        "verify": "whisper-cli --help",
        "notes": "Fastest CPU option. Choose this OR whisper_cli OR mlx_whisper.",
    },
    "mlx_whisper": {
        "label": "mlx-whisper",
        "bundle": "transcription",
        "required_for": ["transcription on Apple Silicon (MLX backend)"],
        "commands": {
            "macos_apple_silicon": "pip install mlx-whisper",
        },
        "verify": "python -c 'import mlx_whisper'",
        "requires": "apple_silicon",
        "notes": "Apple Silicon only. Choose this OR whisper_cli OR whisper_cpp.",
    },
    "opencv": {
        "label": "opencv-python",
        "required_for": ["optical-flow motion scoring (optional)"],
        "commands": {
            "all": "pip install opencv-python",
        },
        "verify": "python -c 'import cv2'",
        "notes": "Optional. Standard frame-difference motion scoring works without it.",
    },
}


def _runtime_platform_id() -> Tuple[str, str]:
    """Return (platform_id, machine) for install-command resolution.

    platform_id is one of: "macos", "macos_apple_silicon", "linux_debian",
    "linux_rhel", "linux_arch", "linux", "windows", "unknown".
    """
    machine = (_platform.machine() or "").lower()
    if sys.platform == "darwin":
        if machine in ("arm64", "aarch64"):
            return "macos_apple_silicon", machine
        return "macos", machine
    if sys.platform.startswith("win"):
        return "windows", machine
    if sys.platform.startswith("linux"):
        # Detect distro family for the most-likely package manager. Best-effort;
        # the dashboard always shows the resolved command so a wrong guess is a
        # one-click copy-and-tweak, not a silent failure.
        os_release = "/etc/os-release"
        try:
            with open(os_release, "r", encoding="utf-8") as fh:
                data = fh.read().lower()
            if "id=debian" in data or "id_like=debian" in data or "ubuntu" in data:
                return "linux_debian", machine
            if "id=fedora" in data or "rhel" in data or "centos" in data or "id_like=\"rhel" in data:
                return "linux_rhel", machine
            if "id=arch" in data or "manjaro" in data:
                return "linux_arch", machine
        except OSError:
            pass
        return "linux", machine
    return "unknown", machine


def install_plan_for(tool_name: str, platform_id: Optional[str] = None) -> Dict[str, Any]:
    """Return a structured install plan for a single tool.

    The plan resolves the best command for the current platform, includes
    alternates so the UI/agent can offer choices, and surfaces the verify
    command and any platform requirement (e.g. Apple Silicon for mlx_whisper).
    """
    meta = TOOL_INSTALL.get(tool_name)
    if not meta:
        return {"tool": tool_name, "available": False, "command": None, "notes": "No install plan registered."}
    if platform_id is None:
        platform_id, _ = _runtime_platform_id()

    commands = meta.get("commands") or {}
    # Resolution order: exact platform → family fallback → "all" → None.
    # macos_apple_silicon falls through to macos; linux_<distro> falls through
    # to a generic "linux" key. We don't pick a random first command — better to
    # tell the UI we don't know and let it surface "no suggested command".
    resolved_key = None
    if platform_id in commands:
        resolved_key = platform_id
    elif platform_id == "macos_apple_silicon" and "macos" in commands:
        resolved_key = "macos"
    elif platform_id.startswith("linux_") and "linux" in commands:
        resolved_key = "linux"
    elif "all" in commands:
        resolved_key = "all"
    resolved = commands.get(resolved_key) if resolved_key else None

    # Alternates: every other distinct command we know about, keyed for display.
    alternates: Dict[str, str] = {}
    for key, value in commands.items():
        if key == resolved_key:
            continue
        if value == resolved:
            continue  # don't show the same command twice under a different label
        alternates[key] = value

    requires = meta.get("requires")
    requirement_met = True
    requirement_note = None
    if requires == "apple_silicon":
        # Use the resolved platform_id (caller's view of the world) rather than the
        # current process, so a Linux user querying mlx_whisper sees "not for you".
        if platform_id != "macos_apple_silicon":
            requirement_met = False
            requirement_note = "Requires Apple Silicon (arm64 macOS). Use whisper_cli or whisper_cpp on other platforms."

    return {
        "tool": tool_name,
        "label": meta.get("label", tool_name),
        "bundle": meta.get("bundle"),
        "platform_id": platform_id,
        "command": resolved,
        "alternates": alternates,
        "verify": meta.get("verify"),
        "required_for": meta.get("required_for", []),
        "notes": meta.get("notes"),
        "requires": requires,
        "requirement_met": requirement_met,
        "requirement_note": requirement_note,
    }


def detect_capabilities(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Detect available analysis helpers without installing or downloading."""
    env = env if env is not None else os.environ
    whisper_cli = shutil.which("whisper")
    # Modern brew whisper-cpp ships the binary as `whisper-cli`; older builds
    # used `whisper-cpp`. Accept either so a fresh `brew install whisper-cpp`
    # is detected. (Distinct from the `whisper_cli` slot above, which is the
    # openai-whisper Python CLI invoked as `whisper`.)
    whisper_cpp = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
    mlx_whisper = importlib.util.find_spec("mlx_whisper") is not None
    cv2 = importlib.util.find_spec("cv2") is not None
    provider = env.get("DAVINCI_RESOLVE_MCP_VISION_PROVIDER")

    sync_events = detect_sync_event_capabilities()

    # Phase C — embedding backends (detected like the whisper backends; the
    # ollama probe is a short local HTTP call and fails fast when not serving).
    try:
        from src.utils import embeddings as _embeddings

        embedding_caps = _embeddings.detect_embedding_capabilities()
    except Exception:  # noqa: BLE001 — detection must never break capabilities
        embedding_caps = {"text": {"available": False, "backends": []},
                          "visual": {"available": False, "backends": []},
                          "install_guidance": {}}

    platform_id, machine = _runtime_platform_id()

    def _tool_entry(name: str, available: bool, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"available": bool(available)}
        if extra:
            entry.update(extra)
        if not available:
            entry["install"] = install_plan_for(name, platform_id=platform_id)
        return entry

    return {
        "success": True,
        "analysis_version": ANALYSIS_VERSION,
        "no_auto_install": True,
        "platform": {"id": platform_id, "machine": machine, "sys_platform": sys.platform},
        "tools": {
            "ffprobe": _tool_entry("ffprobe", bool(shutil.which("ffprobe")), {"path": shutil.which("ffprobe")}),
            "ffmpeg": _tool_entry("ffmpeg", bool(shutil.which("ffmpeg")), {"path": shutil.which("ffmpeg")}),
            "whisper_cli": _tool_entry("whisper_cli", bool(whisper_cli), {"path": whisper_cli}),
            "whisper_cpp": _tool_entry("whisper_cpp", bool(whisper_cpp), {"path": whisper_cpp}),
            "mlx_whisper": _tool_entry("mlx_whisper", bool(mlx_whisper), {"python_module": "mlx_whisper"}),
            "opencv": _tool_entry("opencv", bool(cv2), {"python_module": "cv2"}),
            "ollama_embeddings": _tool_entry(
                "ollama_embeddings",
                bool(embedding_caps.get("text", {}).get("available")),
                {"backends": embedding_caps.get("text", {}).get("backends", [])},
            ),
            "open_clip": _tool_entry(
                "open_clip",
                bool(embedding_caps.get("visual", {}).get("available")),
                {"python_module": "open_clip"},
            ),
            "clap_audio": _tool_entry(
                "clap_audio",
                bool(embedding_caps.get("audio", {}).get("available")),
                {"backends": embedding_caps.get("audio", {}).get("backends", [])},
            ),
        },
        "embeddings": embedding_caps,
        "transcription": {
            "available": bool(whisper_cli or whisper_cpp or mlx_whisper),
            "backends": [
                name for name, available in (
                    ("whisper_cli", bool(whisper_cli)),
                    ("whisper_cpp", bool(whisper_cpp)),
                    ("mlx_whisper", bool(mlx_whisper)),
                )
                if available
            ],
        },
        "vision": {
            "available": True,
            "provider": provider or HOST_CHAT_PATHS_PROVIDER,
            "default_provider": HOST_CHAT_PATHS_PROVIDER,
            "enabled_by_default": True,
            "note": (
                "Media-analysis tools default to host_chat_paths vision: the analyze "
                "actions return absolute paths to extracted analysis frames in a "
                "deferred-vision payload. The host chat model reads those frames as "
                "local images, produces JSON per the included schema, and calls "
                "media_analysis(action='commit_vision', ...) to merge the result, "
                "rebuild markers, and publish vision-dependent metadata to Resolve. "
                "Works with any MCP client whose chat model is vision-capable; no "
                "sampling/createMessage support required. The 'mock' provider is "
                "local-only for tests and never sends frames off-machine."
            ),
        },
        "sync_events": {
            "available": bool(sync_events.get("available")),
            "event_types": sync_events.get("event_types", []),
            "source_safe": True,
            "requires": ["ffmpeg", "ffprobe"],
            "note": "Detects likely audio 2-pops and slate claps for advisory sync offset planning.",
        },
    }


def install_guidance(capabilities: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    caps = capabilities or detect_capabilities()
    tools = caps.get("tools", {})
    missing = {}

    if not tools.get("ffprobe", {}).get("available") or not tools.get("ffmpeg", {}).get("available"):
        missing["ffmpeg_suite"] = {
            "required_for": [
                "technical metadata",
                "scene detection",
                "motion and variance analysis",
                "2-pop and slate-clap sync detection",
            ],
            "macos": "Ask the user before running: brew install ffmpeg",
            "linux": "Ask the user to install ffmpeg with their distribution package manager.",
            "windows": "Ask the user to install ffmpeg and add ffmpeg/ffprobe to PATH.",
        }
    if not caps.get("transcription", {}).get("available"):
        missing["transcription"] = {
            "required_for": ["transcription analysis", "default Resolve media analysis"],
            "options": [
                "Install/configure whisper CLI",
                "Install/configure whisper-cpp",
                "Install mlx-whisper on supported Apple Silicon systems",
            ],
            "macos": "Ask the user before running: brew install whisper-cpp, or configure another supported local Whisper backend.",
            "note": "The MCP server must not install these automatically.",
        }
    if not tools.get("opencv", {}).get("available"):
        missing["opencv"] = {
            "required_for": ["optional optical-flow motion scoring"],
            "note": "OpenCV is optional; standard frame-difference motion scoring can work without it.",
        }
    # Vision uses host_chat_paths by default and is always advertised available;
    # the host chat reads frame files locally and posts results back via
    # media_analysis(action="commit_vision"). No external provider install is required.

    return {
        "success": True,
        "no_auto_install": True,
        "missing": missing,
    }


def normalize_depth(value: Any) -> Tuple[Optional[str], Optional[str]]:
    depth = str(value or DEFAULT_DEPTH).strip().lower()
    if depth not in DEPTHS:
        return None, f"Unknown analysis depth '{value}'. Valid: {sorted(DEPTHS)}"
    return depth, None


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _coerce_optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stable_json_hash(value: Any, length: int = 12) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def _source_file_signature(path: Any) -> Dict[str, Any]:
    payload = {
        "path": normalize_path(path) if path else None,
        "exists": False,
        "size_bytes": None,
        "mtime_ns": None,
    }
    if not payload["path"]:
        return payload
    try:
        stat = os.stat(payload["path"])
    except OSError:
        return payload
    payload.update({
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    })
    return payload


def analysis_request_signature(
    record: Dict[str, Any],
    depth: str,
    options: Dict[str, Any],
    frame_count: int,
    sampling: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the cache signature for a requested analysis profile."""
    transcription = options.get("transcription") or {}
    vision = options.get("vision") or {}
    marker_plan = options.get("marker_plan") or {}
    vision_prompt = vision.get("prompt") or DEFAULT_VISION_ANALYSIS_PROMPT
    signature = {
        "analysis_version": ANALYSIS_VERSION,
        "depth": depth,
        "analysis_keyframe_budget": int(frame_count or 0),
        "source_file": _source_file_signature(record.get("file_path")),
        "layers": {
            "technical": True,
            "readthrough": depth in {"standard", "deep", "custom"},
            "motion": depth in {"standard", "deep", "custom"},
            "transcription": {
                "enabled": _coerce_bool(transcription.get("enabled"), default=DEFAULT_TRANSCRIPTION_ENABLED),
                "backend": transcription.get("backend"),
                "model": transcription.get("model"),
                "language": transcription.get("language"),
            },
            "vision": {
                "enabled": _coerce_bool(vision.get("enabled"), default=False),
                "provider": vision.get("provider"),
                "prompt_hash": _stable_json_hash(vision_prompt),
            },
            "marker_plan": {
                "enabled": _coerce_bool(marker_plan.get("enabled"), default=True),
                "min_shot_duration_seconds": marker_plan.get("min_shot_duration_seconds"),
                "colors_hash": _stable_json_hash(marker_plan.get("colors") or {}),
            },
            "cut_boundary_analysis": {
                "enabled": depth in {"standard", "deep", "custom"},
                "version": 1,
                "hard_frame_cap": HARD_FRAME_CAP,
            },
        },
        "signature_hash": _stable_json_hash({
            "analysis_version": ANALYSIS_VERSION,
            "depth": depth,
            "frame_count": int(frame_count or 0),
            "source_file": _source_file_signature(record.get("file_path")),
            "transcription": {
                "enabled": _coerce_bool(transcription.get("enabled"), default=DEFAULT_TRANSCRIPTION_ENABLED),
                "backend": transcription.get("backend"),
                "model": transcription.get("model"),
                "language": transcription.get("language"),
            },
            "vision": {
                "enabled": _coerce_bool(vision.get("enabled"), default=False),
                "provider": vision.get("provider"),
                "prompt_hash": _stable_json_hash(vision_prompt),
            },
            "marker_plan": {
                "enabled": _coerce_bool(marker_plan.get("enabled"), default=True),
                "min_shot_duration_seconds": marker_plan.get("min_shot_duration_seconds"),
                "colors_hash": _stable_json_hash(marker_plan.get("colors") or {}),
            },
            "cut_boundary_analysis": {
                "enabled": depth in {"standard", "deep", "custom"},
                "version": 1,
                "hard_frame_cap": HARD_FRAME_CAP,
            },
        }),
    }
    # Recorded outside signature_hash so it doesn't bust pre-existing caches;
    # mode changes are reconciled by thoroughness rank in _report_cache_state.
    if sampling:
        signature["analysis_sampling"] = {
            "mode": sampling.get("mode"),
            "frames_per_minute": sampling.get("frames_per_minute"),
            "frame_floor": sampling.get("frame_floor"),
            "frame_ceiling": sampling.get("frame_ceiling"),
        }
    return signature


def _timestamp_from_analyzed_at(value: Any) -> Optional[float]:
    if not value:
        return None
    raw = str(value).strip()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        pass
    try:
        return time.mktime(time.strptime(raw, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return None


def vision_uses_host_chat(options: Dict[str, Any], capabilities: Optional[Dict[str, Any]] = None) -> bool:
    vision = options.get("vision") or {}
    if not _coerce_bool(vision.get("enabled"), default=False):
        return False
    provider = vision.get("provider") or (capabilities or {}).get("vision", {}).get("provider")
    return provider in HOST_CHAT_VISION_PROVIDERS


vision_uses_chat_context = vision_uses_host_chat


def vision_requested(options: Dict[str, Any]) -> bool:
    return _coerce_bool((options.get("vision") or {}).get("enabled"), default=False)


def vision_is_pending_host_analysis(vision: Dict[str, Any]) -> bool:
    if not isinstance(vision, dict):
        return False
    return str(vision.get("status") or "").strip().lower() == "pending_host_analysis"


def visual_analysis_completed(vision: Dict[str, Any]) -> bool:
    if not isinstance(vision, dict):
        return False
    if not vision.get("success"):
        return False
    status = str(vision.get("status") or "").strip().lower()
    if status in {"skipped", "disabled", "pending_host_analysis"}:
        return False
    return bool(
        vision.get("clip_summary")
        or vision.get("content")
        or vision.get("editing_notes")
        or vision.get("analysis_keyframes")
        or vision.get("slate")
        or vision.get("shot_and_style")
    )


def _bounded_frame_count(depth: str, requested: Any = None) -> int:
    default = FRAME_CAPS.get(depth, FRAME_CAPS[DEFAULT_DEPTH])
    if requested is None:
        return default
    try:
        count = int(requested)
    except (TypeError, ValueError):
        return default
    return max(0, min(count, HARD_FRAME_CAP))


def _artifact_paths(project_root: str, record: Dict[str, Any], depth: str, options: Dict[str, Any]) -> Dict[str, Any]:
    clip_dir = resolve_clip_directory(project_root, record)
    artifacts: Dict[str, Any] = {
        "clip_dir": clip_dir,
        "analysis_json": os.path.join(clip_dir, "analysis.json"),
        "technical_json": os.path.join(clip_dir, "technical.json"),
        "marker_plan_json": os.path.join(clip_dir, "clip_analysis_markers.json"),
    }

    if depth in {"standard", "deep", "custom"}:
        artifacts["motion_json"] = os.path.join(clip_dir, "motion.json")
        artifacts["frames_dir"] = os.path.join(clip_dir, "frames")

    transcription = options.get("transcription") or {}
    if _coerce_bool(transcription.get("enabled"), default=DEFAULT_TRANSCRIPTION_ENABLED):
        artifacts["transcript_json"] = os.path.join(clip_dir, "transcript.json")
        artifacts["transcript_srt"] = os.path.join(clip_dir, "transcript.srt")
        artifacts["transcript_vtt"] = os.path.join(clip_dir, "transcript.vtt")

    vision = options.get("vision") or {}
    if _coerce_bool(vision.get("enabled"), default=False):
        artifacts["visual_json"] = os.path.join(clip_dir, "visual.json")

    return artifacts


def _required_capability_gaps(depth: str, options: Dict[str, Any], capabilities: Dict[str, Any]) -> List[Dict[str, Any]]:
    tools = capabilities.get("tools", {})
    gaps: List[Dict[str, Any]] = []
    if not tools.get("ffprobe", {}).get("available"):
        gaps.append({"capability": "ffprobe", "required_for": ["quick", "standard", "deep"]})
    if depth in {"standard", "deep", "custom"} and not tools.get("ffmpeg", {}).get("available"):
        gaps.append({"capability": "ffmpeg", "required_for": ["standard", "deep"]})

    transcription = options.get("transcription") or {}
    if _coerce_bool(transcription.get("enabled"), default=DEFAULT_TRANSCRIPTION_ENABLED):
        backend = transcription.get("backend")
        if backend in {"mock", "local_mock"}:
            pass
        elif not capabilities.get("transcription", {}).get("available"):
            gaps.append({"capability": "transcription_backend", "required_for": ["transcription"]})

    vision = options.get("vision") or {}
    if _coerce_bool(vision.get("enabled"), default=False):
        provider = vision.get("provider") or capabilities.get("vision", {}).get("provider")
        if provider in {"mock", "local_mock"} or provider in HOST_CHAT_VISION_PROVIDERS:
            pass
        elif not capabilities.get("vision", {}).get("available"):
            gaps.append({"capability": "vision_provider", "required_for": ["vision"]})

    return gaps


def build_plan(
    *,
    project_name: Any,
    project_id: Any = None,
    records: List[Dict[str, Any]],
    target: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
    capabilities: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = params or {}
    depth, depth_error = normalize_depth(params.get("depth"))
    if depth_error:
        return {"success": False, "error": depth_error}
    assert depth is not None

    source_paths = [record.get("file_path") for record in records if record.get("file_path")]
    root = resolve_output_root(
        project_name=project_name,
        project_id=project_id,
        analysis_root=params.get("analysis_root"),
        source_paths=source_paths,
        create=False,
    )
    if not root.get("success"):
        return {"success": False, "error": "Invalid analysis output root", "output_root": root}

    caps = capabilities or detect_capabilities()
    options = {
        "transcription": params.get("transcription") or {},
        "vision": params.get("vision") or {},
        "marker_plan": params.get("marker_plan") or params.get("markerPlan") or {},
    }
    gaps = _required_capability_gaps(depth, options, caps)
    frame_count = _bounded_frame_count(depth, params.get("max_analysis_frames"))
    sampling_config = _resolve_sampling_config(params)
    transcription_enabled = _coerce_bool((options.get("transcription") or {}).get("enabled"), default=DEFAULT_TRANSCRIPTION_ENABLED)
    notes = [
        "Plans describe analysis before execution.",
        "All planned artifacts are under the project analysis root, never beside source media.",
        "Missing optional tools are reported as guidance only; nothing is installed automatically.",
        "Session-only execution returns reports to the MCP response and removes scratch artifacts unless keep_artifacts=true.",
    ]
    if caps.get("transcription", {}).get("available") and not transcription_enabled:
        notes.append(
            "Transcription is available but disabled; for story, sound, or audio-spine decisions, "
            "rerun with transcription.enabled=true and allow_model_download=true only if local model use is approved."
        )
    reuse_existing = _coerce_bool(params.get("reuse_existing", params.get("reuseExisting")), default=True)
    force_refresh = _coerce_bool(params.get("force_refresh", params.get("forceRefresh")), default=False)
    max_report_age_days = _coerce_optional_float(params.get("max_report_age_days", params.get("maxReportAgeDays")))
    reuse_policy = str(params.get("reuse_policy", params.get("reusePolicy") or "compatible")).strip().lower()
    if reuse_policy not in {"compatible", "fresh", "strict"}:
        reuse_policy = "compatible"
    if params.get("_reuse_default_analysis_root"):
        reuse_root_payload = resolve_output_root(
            project_name=project_name,
            project_id=project_id,
            analysis_root=None,
            source_paths=source_paths,
            create=False,
        )
        reuse_project_root = reuse_root_payload.get("project_root")
    else:
        reuse_project_root = params.get("reuse_project_root") or params.get("reuseProjectRoot") or root["project_root"]
        reuse_project_root = normalize_path(reuse_project_root) if reuse_project_root else root["project_root"]
    raw_reuse_project_roots = params.get("reuse_project_roots") or params.get("reuseProjectRoots") or []
    if isinstance(raw_reuse_project_roots, str):
        raw_reuse_project_roots = [raw_reuse_project_roots]
    elif not isinstance(raw_reuse_project_roots, list):
        raw_reuse_project_roots = []
    reuse_project_roots = []
    search_related_project_roots = _coerce_bool(
        params.get("search_related_project_roots", params.get("searchRelatedProjectRoots")),
        default=True,
    )
    max_related_project_roots = int(
        _coerce_optional_float(params.get("max_related_project_roots", params.get("maxRelatedProjectRoots")))
        or DEFAULT_MAX_RELATED_PROJECT_ROOTS
    )
    related_project_roots = (
        related_analysis_project_roots(reuse_project_root, limit=max_related_project_roots)
        if search_related_project_roots
        else []
    )
    for candidate_root in [reuse_project_root, *raw_reuse_project_roots]:
        if not candidate_root:
            continue
        normalized_root = normalize_path(candidate_root)
        if normalized_root not in reuse_project_roots:
            reuse_project_roots.append(normalized_root)
    for candidate_root in related_project_roots:
        if candidate_root not in reuse_project_roots:
            reuse_project_roots.append(candidate_root)

    clip_plans = []
    for record in records:
        artifacts = _artifact_paths(root["project_root"], record, depth, options)
        request_signature = analysis_request_signature(record, depth, options, frame_count, sampling=sampling_config)
        existing: Optional[Dict[str, Any]] = None
        clip_plan = {
            "record": record,
            "analysis_keyframe_budget": frame_count,
            "sampling": sampling_config,
            "analysis_signature": request_signature,
            "cache_status": "not_checked",
            "artifacts": artifacts,
        }
        if not reuse_existing:
            clip_plan["cache_status"] = "reuse_disabled"
        elif force_refresh:
            clip_plan["cache_status"] = "refresh_forced"
        else:
            candidates: List[Dict[str, Any]] = []
            for report_path in _record_analysis_report_paths(record):
                candidate = find_reusable_report_from_path(
                    report_path,
                    record,
                    depth,
                    options,
                    request_signature=request_signature,
                    max_report_age_days=max_report_age_days,
                    reuse_policy=reuse_policy,
                )
                if candidate:
                    candidates.append(candidate)
            registry_candidate = find_reusable_report_from_registry(
                reuse_project_root,
                record,
                depth,
                options,
                request_signature=request_signature,
                max_report_age_days=max_report_age_days,
                reuse_policy=reuse_policy,
            )
            if registry_candidate:
                candidates.append(registry_candidate)
            existing = find_reusable_report_across_roots(
                reuse_project_roots,
                record,
                depth,
                options,
                request_signature=request_signature,
                max_report_age_days=max_report_age_days,
                reuse_policy=reuse_policy,
            )
            if existing:
                candidates.append(existing)
            if candidates:
                reusable_candidates = [row for row in candidates if row.get("reusable")]
                pool = reusable_candidates or candidates
                pool.sort(key=_report_reuse_score)
                existing = pool[0]
            if existing:
                clip_plan["existing_report"] = {
                    "path": existing.get("path"),
                    "reusable": existing.get("reusable", False),
                    "missing_layers": existing.get("missing_layers", []),
                    "cache_issues": existing.get("cache_issues", []),
                    "cache_warnings": existing.get("cache_warnings", []),
                    "analyzed_at": existing.get("analyzed_at"),
                    "project_root": existing.get("project_root"),
                    "source": existing.get("source") or "analysis_root_search",
                    "registry_path": existing.get("registry_path"),
                    "superseded_by_relink": bool(existing.get("superseded_by_relink")),
                    "superseded_at": existing.get("superseded_at"),
                    "superseded_reason": existing.get("superseded_reason"),
                }
                if existing.get("reusable"):
                    clip_plan["skip_execution"] = True
                    clip_plan["cache_status"] = "reusable"
                    clip_plan["reused_from"] = existing.get("path")
                    clip_plan["reuse_source"] = existing.get("source") or "analysis_root_search"
                    if existing.get("source") == "record_analysis_report_path":
                        clip_plan["reuse_reason"] = "Resolve clip metadata points to an existing analysis report that satisfies the requested depth and modalities."
                    elif existing.get("source") == "analysis_registry":
                        clip_plan["reuse_reason"] = "Global analysis registry points to an existing report that satisfies the requested depth and modalities."
                    elif existing.get("project_root") and existing.get("project_root") != root["project_root"]:
                        clip_plan["reuse_reason"] = "Existing analysis report from a related project version satisfies the requested depth and modalities."
                    else:
                        clip_plan["reuse_reason"] = "Existing analysis report satisfies the requested depth and modalities."
                else:
                    clip_plan["cache_status"] = "stale_or_incomplete"
                    clip_plan["why_not_reused"] = _why_not_reused(existing)
            else:
                clip_plan["cache_status"] = "miss"
                clip_plan["why_not_reused"] = _why_not_reused(None, provenance_present=_record_has_analysis_provenance(record))
        if (
            reuse_existing
            and not force_refresh
            and not clip_plan.get("skip_execution")
            and clip_plan.get("cache_status") not in {"reuse_disabled", "refresh_forced"}
            and _record_has_analysis_provenance(record)
        ):
            _mark_reuse_blocked(clip_plan, record, existing)
        clip_plans.append(clip_plan)

    per_clip_seconds = {"quick": 2, "standard": 45, "deep": 180, "custom": 45}.get(depth, 45)
    reusable_count = sum(1 for clip in clip_plans if clip.get("skip_execution"))
    stale_count = sum(1 for clip in clip_plans if clip.get("cache_status") == "stale_or_incomplete")
    blocked_count = sum(1 for clip in clip_plans if clip.get("reuse_blocked"))
    miss_count = sum(1 for clip in clip_plans if clip.get("cache_status") == "miss")
    reused_sources: Dict[str, int] = {}
    for clip in clip_plans:
        source = clip.get("reuse_source")
        if source:
            reused_sources[str(source)] = reused_sources.get(str(source), 0) + 1
    reuse_summary = {
        "checked": reuse_existing and not force_refresh,
        "reusable_clip_count": reusable_count,
        "blocked_clip_count": blocked_count,
        "stale_or_incomplete_clip_count": stale_count,
        "miss_clip_count": miss_count,
        "estimated_seconds_saved": per_clip_seconds * reusable_count,
        "sources": reused_sources,
        "registry_path": analysis_registry_path(reuse_project_root),
    }
    return {
        "success": True,
        "analysis_version": ANALYSIS_VERSION,
        "dry_run": _coerce_bool(params.get("dry_run"), default=True),
        "session_only": _coerce_bool(params.get("session_only"), default=False),
        "target": target,
        "depth": depth,
        "clip_count": len(records),
        "output_root": root,
        "capability_gaps": gaps,
        "install_guidance": install_guidance(caps) if gaps else {"success": True, "missing": {}},
        "estimated_seconds": per_clip_seconds * len(records),
        "estimated_seconds_after_reuse": per_clip_seconds * max(0, len(records) - reusable_count),
        "analysis_keyframe_budget_per_clip": frame_count,
        "sampling": sampling_config,
        "sampling_mode": sampling_config.get("mode"),
        "reuse_existing": reuse_existing,
        "force_refresh": force_refresh,
        "reuse_policy": reuse_policy,
        "max_report_age_days": max_report_age_days,
        "reuse_project_root": reuse_project_root,
        "reuse_project_roots": reuse_project_roots,
        "search_related_project_roots": search_related_project_roots,
        "related_project_roots": related_project_roots,
        "reusable_clip_count": reusable_count,
        "stale_or_incomplete_clip_count": stale_count,
        "reuse_blocked_clip_count": blocked_count,
        "reuse_summary": reuse_summary,
        "clips": clip_plans,
        "notes": notes,
    }


def _run_command(args: List[str], timeout: int = COMMAND_TIMEOUT_SECONDS) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
        stderr_tail = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        return 124, stdout, f"Command timed out after {timeout}s. {stderr_tail}".strip()
    except OSError as exc:
        return 127, "", str(exc)
    stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
    return proc.returncode, stdout, stderr


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp-{os.getpid()}-{threading.get_ident()}-{time.time_ns()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _ingest_report_into_db(project_root: str, report: Dict[str, Any], clip_dir: Optional[str]) -> Dict[str, Any]:
    """C1 — write a report into the DB-canonical store (rows in a transaction).

    Best-effort by design: a DB failure must never break the analysis run,
    because the JSON export still lands on disk and every reader falls back
    to it. The failure is surfaced in the result for the caller to report.
    """
    try:
        from src.utils import analysis_store

        return analysis_store.ingest_report(project_root, report, clip_dir=clip_dir)
    except Exception as exc:  # noqa: BLE001 — DB trouble must not kill analysis
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def _fraction_to_float(value: Any) -> Optional[float]:
    if value in (None, "", "0/0"):
        return None
    raw = str(value)
    if "/" in raw:
        num, den = raw.split("/", 1)
        try:
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        except ValueError:
            return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ffprobe(path: str) -> Dict[str, Any]:
    code, stdout, stderr = _run_command([
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-show_chapters",
        path,
    ])
    if code != 0:
        return {"success": False, "error": stderr.strip() or "ffprobe failed"}
    try:
        raw = json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"ffprobe returned invalid JSON: {exc}"}
    return {"success": True, "raw": raw, "summary": _ffprobe_summary(raw)}


def _ffprobe_summary(raw: Dict[str, Any]) -> Dict[str, Any]:
    streams = raw.get("streams") or []
    fmt = raw.get("format") or {}
    video = []
    audio = []
    warnings = []
    for stream in streams:
        codec_type = stream.get("codec_type")
        if codec_type == "video":
            r_fps = _fraction_to_float(stream.get("r_frame_rate"))
            avg_fps = _fraction_to_float(stream.get("avg_frame_rate"))
            is_vfr = bool(r_fps and avg_fps and abs(r_fps - avg_fps) > 0.01)
            if is_vfr:
                warnings.append("Container frame rate and average frame rate differ; possible VFR media")
            video.append({
                "index": stream.get("index"),
                "codec": stream.get("codec_name"),
                "codec_long": stream.get("codec_long_name"),
                "profile": stream.get("profile"),
                "pixel_format": stream.get("pix_fmt"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "r_frame_rate": stream.get("r_frame_rate"),
                "avg_frame_rate": stream.get("avg_frame_rate"),
                "frame_rate": avg_fps or r_fps,
                "is_vfr": is_vfr,
                "color_primaries": stream.get("color_primaries"),
                "transfer_characteristics": stream.get("color_transfer"),
                "matrix_coefficients": stream.get("color_space"),
                "field_order": stream.get("field_order"),
                "duration_seconds": _parse_float(stream.get("duration")),
                "frame_count": int(stream["nb_frames"]) if str(stream.get("nb_frames", "")).isdigit() else None,
            })
        elif codec_type == "audio":
            audio.append({
                "index": stream.get("index"),
                "codec": stream.get("codec_name"),
                "codec_long": stream.get("codec_long_name"),
                "sample_rate": int(stream["sample_rate"]) if str(stream.get("sample_rate", "")).isdigit() else None,
                "channels": stream.get("channels"),
                "channel_layout": stream.get("channel_layout"),
                "duration_seconds": _parse_float(stream.get("duration")),
            })
    return {
        "format": {
            "filename": fmt.get("filename"),
            "format_name": fmt.get("format_name"),
            "duration_seconds": _parse_float(fmt.get("duration")),
            "size_bytes": int(fmt["size"]) if str(fmt.get("size", "")).isdigit() else None,
            "bit_rate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
            "tags": fmt.get("tags") or {},
        },
        "video": video,
        "audio": audio,
        "chapters": raw.get("chapters") or [],
        "warnings": warnings,
    }


def _media_duration_seconds(record: Dict[str, Any], technical: Dict[str, Any]) -> Optional[float]:
    summary = technical.get("summary") or {}
    duration = ((summary.get("format") or {}).get("duration_seconds"))
    if duration:
        return duration
    videos = summary.get("video") or []
    for video in videos:
        if video.get("duration_seconds"):
            return video["duration_seconds"]
    return None


def _ffmpeg_stderr_filter(path: str, video_filter: Optional[str] = None, audio_filter: Optional[str] = None, frames: Optional[int] = None) -> Tuple[int, str]:
    args = ["ffmpeg", "-hide_banner", "-nostats", "-i", path]
    if video_filter:
        args.extend(["-vf", video_filter])
    if audio_filter:
        args.extend(["-af", audio_filter])
    if frames is not None:
        args.extend(["-frames:v", str(frames)])
    args.extend(["-f", "null", "-"])
    code, _, stderr = _run_command(args)
    return code, stderr


def _parse_loudness(stderr: str) -> Dict[str, Any]:
    def latest(pattern: str) -> Optional[float]:
        matches = re.findall(pattern, stderr)
        if not matches:
            return None
        return _parse_float(matches[-1])

    return {
        "integrated_lufs": latest(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS"),
        "loudness_range_lu": latest(r"LRA:\s*(-?\d+(?:\.\d+)?)\s*LU"),
        "true_peak_dbtp": latest(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS"),
    }


def _parse_scene_changes(stderr: str) -> List[Dict[str, Any]]:
    scenes = []
    for match in re.finditer(r"pts_time:([0-9.]+)", stderr):
        t = _parse_float(match.group(1))
        if t is not None:
            scenes.append({"time_seconds": t})
    return scenes


def _parse_scene_score_pairs(stderr: str) -> List[Tuple[float, float]]:
    """Pair (pts_time, lavfi.scene_score) from showinfo + metadata=print output.

    The filtergraph ``select='gt(scene,0)',metadata=print:key=lavfi.scene_score,showinfo``
    emits, per qualifying frame, a showinfo line carrying ``pts_time:...`` followed by a
    metadata line carrying ``lavfi.scene_score=...``. Pair them in stream order.
    """
    pairs: List[Tuple[float, float]] = []
    current_time: Optional[float] = None
    for line in stderr.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            current_time = _parse_float(m.group(1))
            continue
        m = re.search(r"lavfi\.scene_score=([0-9.]+)", line)
        if m and current_time is not None:
            score = _parse_float(m.group(1))
            if score is not None:
                pairs.append((current_time, score))
                current_time = None
    return pairs


def _adaptive_scene_threshold(
    scores: List[Tuple[float, float]],
    *,
    min_floor: float = 0.15,
    k_sd: float = 2.5,
    threshold_cap: float = 0.40,
    fallback: float = 0.30,
) -> Tuple[float, Dict[str, Any]]:
    """Pick a content-aware scene-change threshold from the score distribution.

    ``threshold = clamp(mean + k_sd*sd, [min_floor, threshold_cap])``. The floor protects
    low-motion footage (interview / locked-off) where ``mean+sd`` is tiny; the cap guards
    against a few extreme flashes inflating SD. Falls back to ``fallback`` (the legacy
    0.30) if the distribution is empty.
    """
    values = [s for _, s in scores if s is not None]
    if not values:
        return fallback, {"reason": "no_scores", "chosen": fallback, "source": "fallback"}

    n = len(values)
    mean = sum(values) / n
    if n > 1:
        var = sum((v - mean) * (v - mean) for v in values) / (n - 1)
        sd = math.sqrt(var)
    else:
        sd = 0.0

    candidate = mean + k_sd * sd
    chosen = max(min_floor, min(candidate, threshold_cap))

    sorted_vals = sorted(values)
    def _pctl(p: float) -> float:
        idx = max(0, min(n - 1, int(round((p / 100.0) * (n - 1)))))
        return sorted_vals[idx]

    return chosen, {
        "n": n,
        "mean": round(mean, 5),
        "sd": round(sd, 5),
        "p95": round(_pctl(95), 5),
        "p99": round(_pctl(99), 5),
        "candidate": round(candidate, 5),
        "min_floor": min_floor,
        "k_sd": k_sd,
        "threshold_cap": threshold_cap,
        "chosen": round(chosen, 5),
        "source": "adaptive",
    }


def _parse_blackdetect(stderr: str) -> List[Dict[str, Any]]:
    out = []
    pattern = r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)"
    for start, end, duration in re.findall(pattern, stderr):
        out.append({
            "start": _parse_float(start),
            "end": _parse_float(end),
            "duration": _parse_float(duration),
        })
    return out


def _parse_silencedetect(stderr: str) -> List[Dict[str, Any]]:
    starts = [_parse_float(v) for v in re.findall(r"silence_start:\s*([0-9.]+)", stderr)]
    ends = [(_parse_float(end), _parse_float(duration)) for end, duration in re.findall(r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)", stderr)]
    intervals = []
    for index, start in enumerate(starts):
        end = ends[index][0] if index < len(ends) else None
        duration = ends[index][1] if index < len(ends) else None
        intervals.append({"start": start, "end": end, "duration": duration})
    return intervals


def _parse_idet(stderr: str) -> Dict[str, Any]:
    match = re.search(
        r"Multi frame detection:\s*TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*Progressive:\s*(\d+)\s*Undetermined:\s*(\d+)",
        stderr,
    )
    if not match:
        return {}
    tff, bff, progressive, undetermined = [int(v) for v in match.groups()]
    dominant = max(
        [("tff", tff), ("bff", bff), ("progressive", progressive), ("undetermined", undetermined)],
        key=lambda row: row[1],
    )[0]
    return {
        "tff": tff,
        "bff": bff,
        "progressive": progressive,
        "undetermined": undetermined,
        "dominant": dominant,
    }


def _readthrough_analysis(path: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"success": True}

    loud_code, loud_stderr = _ffmpeg_stderr_filter(path, audio_filter="ebur128=peak=true")
    result["loudness"] = {
        "success": loud_code == 0,
        "metrics": _parse_loudness(loud_stderr),
    }

    # Adaptive scene detection. One ffmpeg pass dumps a (pts_time, scene_score) pair
    # for every frame whose scene score is > 0 (i.e. every non-first frame); we then
    # compute a content-aware threshold from that distribution and keep peaks above it.
    # Replaces the legacy hardcoded ``gt(scene,0.3)``, which was too coarse on
    # high-motion content (missed real cuts) and too sensitive on locked-off content.
    scene_code, scene_stderr = _ffmpeg_stderr_filter(
        path,
        video_filter="select='gt(scene,0)',metadata=print:key=lavfi.scene_score,showinfo",
    )
    scene_score_pairs = _parse_scene_score_pairs(scene_stderr)
    scene_threshold, scene_threshold_stats = _adaptive_scene_threshold(scene_score_pairs)
    adaptive_scene_items = [
        {"time_seconds": pts, "score": score}
        for pts, score in scene_score_pairs
        if score is not None and score > scene_threshold
    ]
    result["scenes"] = {
        "success": scene_code == 0,
        "items": adaptive_scene_items,
        "threshold": scene_threshold,
        "threshold_stats": scene_threshold_stats,
    }

    black_code, black_stderr = _ffmpeg_stderr_filter(path, video_filter="blackdetect=d=0.5:pix_th=0.10")
    result["black_frames"] = {
        "success": black_code == 0,
        "items": _parse_blackdetect(black_stderr),
    }

    silence_code, silence_stderr = _ffmpeg_stderr_filter(path, audio_filter="silencedetect=noise=-50dB:d=1")
    result["silence"] = {
        "success": silence_code == 0,
        "items": _parse_silencedetect(silence_stderr),
    }

    idet_code, idet_stderr = _ffmpeg_stderr_filter(path, video_filter="idet", frames=500)
    result["interlace"] = {
        "success": idet_code == 0,
        "metrics": _parse_idet(idet_stderr),
    }

    return result


def _frame_number_for_time(seconds: Optional[float], fps: Optional[float]) -> Optional[int]:
    if seconds is None:
        return None
    try:
        return int(round(max(0.0, float(seconds)) * max(float(fps or 24.0), 1.0)))
    except (TypeError, ValueError):
        return None


def _frame_step_seconds(fps: Optional[float]) -> float:
    try:
        parsed = float(fps or 24.0)
    except (TypeError, ValueError):
        parsed = 24.0
    return 1.0 / max(parsed, 1.0)


def _clamp_sample_time(value: float, duration: Optional[float]) -> float:
    if duration is None or duration <= 0:
        return max(0.0, value)
    return min(max(0.0, value), max(0.0, duration - 0.001))


def _cut_boundary_analysis(
    duration: Optional[float],
    scene_items: List[Dict[str, Any]],
    fps: Optional[float],
    *,
    min_shot_duration_seconds: float = 0.75,
    flash_frame_max_duration_seconds: float = 0.25,
) -> Dict[str, Any]:
    frame_step = _frame_step_seconds(fps)
    scene_times = []
    for item in scene_items or []:
        if not isinstance(item, dict):
            continue
        t = _parse_float(item.get("time_seconds"))
        if t is None or t <= 0:
            continue
        if duration is not None and t >= duration:
            continue
        scene_times.append(round(t, 3))
    scene_times = sorted(set(scene_times))

    cut_points = []
    for index, t in enumerate(scene_times, 1):
        before_time = _clamp_sample_time(t - frame_step, duration)
        after_time = _clamp_sample_time(t + frame_step, duration)
        cut_points.append({
            "index": index,
            "time_seconds": t,
            "frame": _frame_number_for_time(t, fps),
            "before_time_seconds": before_time,
            "before_frame": _frame_number_for_time(before_time, fps),
            "after_time_seconds": after_time,
            "after_frame": _frame_number_for_time(after_time, fps),
            "needs_visual_confirmation": True,
            "source": "ffmpeg_scene_detection",
        })

    raw_shot_ranges = []
    boundaries: List[float] = [0.0]
    boundaries.extend(scene_times)
    if duration is not None and duration > 0:
        boundaries.append(float(duration))
    for index in range(max(0, len(boundaries) - 1)):
        start = boundaries[index]
        end = boundaries[index + 1]
        if end <= start:
            continue
        raw_shot_ranges.append({
            "index": index + 1,
            "start": start,
            "end": end,
            "duration": end - start,
            "start_frame": _frame_number_for_time(start, fps),
            "end_frame": _frame_number_for_time(end, fps),
        })

    shot_ranges = []
    flash_candidates = []
    short_shot_candidates = []
    flash_keys = set()
    short_keys = set()
    for raw_shot in raw_shot_ranges:
        shot_duration = _parse_float(raw_shot.get("duration"))
        start = _parse_float(raw_shot.get("start"))
        end = _parse_float(raw_shot.get("end"))
        if shot_duration is not None and shot_duration <= float(min_shot_duration_seconds):
            short_keys.add((round(start or 0.0, 3), round(end or 0.0, 3)))
            short_shot_candidates.append(dict(raw_shot))
        if (
            shot_duration is not None
            and shot_duration <= float(flash_frame_max_duration_seconds)
            and start not in (None, 0.0)
            and end is not None
            and duration is not None
            and end < duration
        ):
            flash_keys.add((round(start, 3), round(end, 3)))
            flash_candidates.append({
                **raw_shot,
                "mid_sample_time_seconds": _clamp_sample_time(start + shot_duration / 2.0, duration),
                "reason": "adjacent scene detections bound a very short segment",
                "needs_visual_confirmation": True,
            })

    for shot in _shot_ranges_from_scenes(
        duration,
        [{"time_seconds": t} for t in scene_times],
        min_duration_seconds=float(min_shot_duration_seconds),
    ):
        start = _parse_float(shot.get("start"))
        end = _parse_float(shot.get("end"))
        shot_duration = (end - start) if start is not None and end is not None else None
        # 2*frame_step inset (~66ms at 30fps) keeps boundary samples clear of
        # cut-detector imprecision — a single-frame margin can land ON the cut.
        boundary_inset = frame_step * 2
        first_sample = _clamp_sample_time((start or 0.0) + boundary_inset, duration)
        if end is not None:
            last_sample = _clamp_sample_time(max(start or 0.0, end - boundary_inset), duration)
        else:
            last_sample = first_sample
        row = {
            "index": shot.get("index"),
            "start": start,
            "end": end,
            "duration": shot_duration,
            "start_frame": _frame_number_for_time(start, fps),
            "end_frame": _frame_number_for_time(end, fps),
            "first_sample_time_seconds": first_sample,
            "last_sample_time_seconds": last_sample,
            "first_sample_frame": _frame_number_for_time(first_sample, fps),
            "last_sample_frame": _frame_number_for_time(last_sample, fps),
        }
        shot_ranges.append(row)
        short_key = (round(start or 0.0, 3), round(end or 0.0, 3))
        if shot_duration is not None and shot_duration <= float(min_shot_duration_seconds) and short_key not in short_keys:
            short_keys.add(short_key)
            short_shot_candidates.append(row)
        if (
            shot_duration is not None
            and shot_duration <= float(flash_frame_max_duration_seconds)
            and start not in (None, 0.0)
            and end is not None
            and duration is not None
            and end < duration
            and (round(start, 3), round(end, 3)) not in flash_keys
        ):
            flash_candidates.append({
                **row,
                "mid_sample_time_seconds": _clamp_sample_time(start + shot_duration / 2.0, duration),
                "reason": "scene-bounded shot shorter than flash frame threshold",
                "needs_visual_confirmation": True,
            })

    cut_density_per_minute = (len(cut_points) / max(float(duration or 0.0), 1.0)) * 60.0 if duration else 0.0
    return {
        "success": True,
        "source": "ffmpeg_scene_detection",
        "threshold": 0.3,
        "fps": fps,
        "frame_step_seconds": frame_step,
        "duration_seconds": duration,
        "cut_count": len(cut_points),
        "cut_density_per_minute": cut_density_per_minute,
        "likely_edited_sequence": bool(len(cut_points) >= 2 or cut_density_per_minute >= 3.0),
        "cut_points": cut_points,
        "raw_shot_ranges": raw_shot_ranges,
        "shot_ranges": shot_ranges,
        "short_shot_candidates": short_shot_candidates,
        "flash_frame_candidates": flash_candidates,
        "notes": [
            "FFmpeg scene detection reads the full video stream; boundary frames are sampled for visual confirmation when available.",
            "Short scene-bounded ranges are candidates only until LLM/frame review distinguishes flash frames from deliberate cuts or high motion.",
        ],
    }


def _demand_frame_count(
    cut_analysis: Dict[str, Any],
    duration_seconds: Optional[float],
) -> int:
    """Frames the content *demands* so vision can populate the per-shot schema.

    Demand sources:
      - Per shot: 1 representative (midpoint) + 2 boundary frames + duration-scaled extras
        (+1 for shots >5s, +1 for shots >15s, +1 per additional 15s beyond 30s)
      - Per flash_candidate: 1 mid-frame for vision adjudication (preserve all)
      - Per cut_point: a small buffer for cuts not covered by shot boundaries
      - Clip-level: first_usable, last_usable, midpoint
    """
    per_shot_demand = 0
    for shot in cut_analysis.get("shot_ranges") or []:
        if not isinstance(shot, dict):
            continue
        start = _parse_float(shot.get("start"))
        end = _parse_float(shot.get("end"))
        if start is None or end is None or end <= start:
            continue
        d = end - start
        # Base: representative + 2 boundaries
        per_shot_demand += 3
        if d > 5.0:
            per_shot_demand += 1
        if d > 15.0:
            per_shot_demand += 1
        if d > 30.0:
            per_shot_demand += int((d - 30.0) / 15.0)

    flash_count = len(cut_analysis.get("flash_frame_candidates") or [])
    cut_count = len(cut_analysis.get("cut_points") or [])

    # Cut points mostly overlap with shot boundaries; add a small buffer
    cut_buffer = min(cut_count, 8)
    # Clip-level frames (first_usable, last_usable, midpoint)
    clip_buffer = 4

    return per_shot_demand + flash_count + cut_buffer + clip_buffer


def _compute_demand_driven_budget(
    requested_budget: int,
    cut_analysis: Optional[Dict[str, Any]],
    duration_seconds: Optional[float],
    sampling: Optional[Dict[str, Any]] = None,
) -> int:
    """Resolve the effective frame-sampling budget for the active sampling mode.

    Modes (see SAMPLING_MODES):
      - fixed:           flat `requested_budget`, duration-independent.
      - per_minute:      clamp(minutes * frames_per_minute, floor, ceiling); content-blind.
      - adaptive_capped: content demand (see _demand_frame_count), clamped to [floor, ceiling].
      - adaptive:        content demand, clamped only by a generous duration-scaled HARD_FRAME_CAP
                         (legacy behaviour; the default when no sampling config is threaded).

    `requested_budget` (depth-derived / max_analysis_frames) acts as a floor for the
    adaptive modes so an explicit request is never undercut.
    """
    sampling = sampling or {}
    mode = normalize_sampling_mode(sampling.get("mode"), default=DEFAULT_SAMPLING_MODE) or DEFAULT_SAMPLING_MODE
    rate = sampling.get("frames_per_minute") or DEFAULT_FRAMES_PER_MINUTE
    floor = int(sampling.get("frame_floor") or DEFAULT_FRAME_FLOOR)
    ceiling = int(sampling.get("frame_ceiling") or DEFAULT_FRAME_CEILING)
    if ceiling < floor:
        ceiling = floor
    requested = max(int(requested_budget or 0), 0)
    minutes = max(0.0, float(duration_seconds or 0) / 60.0)
    per_minute_count = int(round(minutes * float(rate)))

    if mode == "fixed":
        return min(requested, HARD_FRAME_CAP)

    if mode == "per_minute":
        return _clamp_int(per_minute_count, floor, min(ceiling, HARD_FRAME_CAP))

    # Adaptive modes need shot/cut analysis. Without it, fall back to a duration
    # estimate (adaptive_capped) or the legacy requested-only budget (adaptive).
    if not isinstance(cut_analysis, dict):
        if mode == "adaptive_capped":
            return _clamp_int(max(requested, per_minute_count), floor, min(ceiling, HARD_FRAME_CAP))
        return min(max(requested, 0), HARD_FRAME_CAP)

    demand = _demand_frame_count(cut_analysis, duration_seconds)
    target = max(requested, demand, floor)

    if mode == "adaptive_capped":
        return _clamp_int(target, floor, min(ceiling, HARD_FRAME_CAP))

    # adaptive (uncapped): only the absolute hard cap, scaled by duration so a
    # 10s clip cannot request 500 frames. Floor at 64 for short-clip headroom.
    duration_cap = max(64, min(HARD_FRAME_CAP, int(float(duration_seconds or 0) * 2)))
    return _clamp_int(target, floor, duration_cap)


def _even_interval_samples(
    duration: float,
    count: int,
    frame_step: float,
) -> List[Dict[str, Any]]:
    """Content-blind evenly-spaced samples (Economy / Balanced modes).

    Returns exactly `count` frames at the midpoints of `count` equal slices of
    [0, duration], so cost is a clean function of `count` and never inflated by
    shot/cut demand. Used when the user has chosen a predictable, content-blind mode.
    """
    if count <= 0 or duration <= 0:
        return []
    out: List[Dict[str, Any]] = []
    for i in range(count):
        t = duration * (i + 0.5) / count
        out.append({
            "time_seconds": _clamp_sample_time(float(t), duration),
            "selection_reason": "interval",
        })
    return out


def _sample_times(
    duration: Optional[float],
    scene_items: List[Dict[str, Any]],
    budget: int,
    *,
    fps: Optional[float] = None,
    cut_analysis: Optional[Dict[str, Any]] = None,
    sampling: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Frame allocation. Content-blind for Economy/Balanced; demand-driven otherwise.

    Economy (fixed) / Balanced (per_minute): exactly `budget` evenly-spaced frames
    (see _even_interval_samples) — predictable cost, ignores shot structure.

    Thorough (adaptive / adaptive_capped) — two-pass demand-driven allocation:
      Pass 1 (reservations, always allocated — demand-driven, not budget-bounded):
        - Per shot: shot_representative (midpoint), shot_start, shot_end boundaries,
          duration-scaled progress samples (+1 for shots >5s, +1 for shots >15s,
          +1 per 15s beyond 30s).
        - Per flash_candidate: mid-frame for vision adjudication.
      Pass 2 (priority fill, consumes remaining budget):
        - cut_before/cut_after pairs (for cuts not covered by shot boundaries)
        - first_usable, last_usable, scene_change, midpoint, interval fillers

      The caller passes `budget` as the soft target. Reservations always land
      (demand-driven); priority fill is what `budget` constrains.

    Returns a time-sorted list of sample candidates.
    """
    if budget <= 0:
        return []
    duration = duration or 0
    cut_analysis = cut_analysis if isinstance(cut_analysis, dict) else {}
    frame_step = _frame_step_seconds(fps)

    # Content-blind modes: even-interval sampling of exactly `budget` frames so
    # cost stays predictable and is not inflated by per-shot reservations.
    mode = normalize_sampling_mode((sampling or {}).get("mode"), default=DEFAULT_SAMPLING_MODE) or DEFAULT_SAMPLING_MODE
    if mode in {"fixed", "per_minute"}:
        return _even_interval_samples(duration, budget, frame_step)

    # ===================== Pass 1: Reservations =====================
    reserved: List[Dict[str, Any]] = []

    def add_reserved(time_seconds: Optional[float], reason: str, **extra: Any) -> None:
        if time_seconds is None:
            return
        reserved.append({
            "time_seconds": _clamp_sample_time(float(time_seconds), duration),
            "selection_reason": reason,
            **extra,
        })

    # Per-shot reservations
    for shot in cut_analysis.get("shot_ranges") or []:
        if not isinstance(shot, dict):
            continue
        shot_index = shot.get("index")
        start = _parse_float(shot.get("start"))
        end = _parse_float(shot.get("end"))
        if start is None or end is None or end <= start:
            continue
        d = end - start
        common = {"shot_index": shot_index, "shot_start": start, "shot_end": end}
        # Always: mid-shot representative
        add_reserved((start + end) / 2.0, "shot_representative", **common)
        # Boundary frames if shot is long enough to distinguish them from the midpoint.
        # Use 2*frame_step inset (~66ms at 30fps) instead of 1*frame_step to clear
        # cut-detector imprecision — a single-frame margin can land ON the cut.
        boundary_inset = frame_step * 2
        if d >= boundary_inset * 4:
            add_reserved(
                shot.get("first_sample_time_seconds") or _clamp_sample_time(start + boundary_inset, duration),
                "shot_start",
                boundary_role="first_frame_in_shot",
                **common,
            )
            add_reserved(
                shot.get("last_sample_time_seconds") or _clamp_sample_time(end - boundary_inset, duration),
                "shot_end",
                boundary_role="last_frame_in_shot",
                **common,
            )
        # Duration-scaled progress samples
        if d > 5.0:
            add_reserved(start + d * (1.0 / 3.0), "shot_progress", **common)
        if d > 15.0:
            add_reserved(start + d * (2.0 / 3.0), "shot_progress", **common)
        if d > 30.0:
            extras = int((d - 30.0) / 15.0)
            for i in range(extras):
                frac = (i + 0.5) / max(extras, 1)
                add_reserved(start + 30.0 + (d - 30.0) * frac, "shot_progress", **common)

    # Per-flash-candidate reservations (preserved for vision adjudication)
    for flash in cut_analysis.get("flash_frame_candidates") or []:
        if not isinstance(flash, dict):
            continue
        add_reserved(
            flash.get("mid_sample_time_seconds"),
            "flash_candidate",
            shot_index=flash.get("index"),
            shot_start=flash.get("start"),
            shot_end=flash.get("end"),
        )

    # ===================== Pass 2: Priority fill =====================
    candidates: List[Dict[str, Any]] = []

    def add_candidate(time_seconds: Optional[float], reason: str, priority: int, **extra: Any) -> None:
        if time_seconds is None:
            return
        candidates.append({
            "time_seconds": _clamp_sample_time(float(time_seconds), duration),
            "selection_reason": reason,
            "priority": priority,
            **extra,
        })

    # Cut boundary pairs (for cuts not already covered by shot boundaries)
    for cut in cut_analysis.get("cut_points") or []:
        if not isinstance(cut, dict):
            continue
        cut_index = cut.get("index")
        add_candidate(
            cut.get("before_time_seconds"), "cut_before", 5,
            cut_index=cut_index, cut_time_seconds=cut.get("time_seconds"),
            boundary_role="last_frame_before_cut",
        )
        add_candidate(
            cut.get("after_time_seconds"), "cut_after", 5,
            cut_index=cut_index, cut_time_seconds=cut.get("time_seconds"),
            boundary_role="first_frame_after_cut",
        )

    # Clip-level usable frames
    if duration > 0:
        add_candidate(min(duration * 0.05, max(duration - 0.05, 0)), "first_usable", 6)
        add_candidate(max(duration - min(duration * 0.05, 0.5), 0), "last_usable", 6)
        add_candidate(duration * 0.5, "midpoint", 70)

    # Scene change candidates
    for scene in scene_items[: max(budget, 1)]:
        t = scene.get("time_seconds")
        if isinstance(t, (int, float)) and t >= 0:
            add_candidate(float(t), "scene_change", 15)

    # Interval filler (low priority)
    if duration > 0:
        interval_count = max(0, min(budget, 6) - 3)
        for index in range(interval_count):
            add_candidate(duration * ((index + 1) / (interval_count + 1)), "interval", 80)

    # ===================== Assemble: reservations first, then priority fill =====================
    unique: List[Dict[str, Any]] = []
    seen = set()

    def maybe_add(row: Dict[str, Any]) -> bool:
        rounded = round(max(float(row.get("time_seconds") or 0.0), 0), 3)
        key = round(rounded / max(frame_step, 0.001))
        if key in seen:
            return False
        seen.add(key)
        r = dict(row)
        r["time_seconds"] = rounded
        r.pop("priority", None)
        unique.append(r)
        return True

    # Reservations always land (demand-driven); budget bounds only priority fill.
    for r in sorted(reserved, key=lambda row: float(row.get("time_seconds") or 0.0)):
        maybe_add(r)

    # Effective budget for priority fill: max(budget, len(reservations))
    fill_budget = max(int(budget or 0), len(unique))
    for candidate in sorted(candidates, key=lambda row: (int(row.get("priority", 99)), float(row.get("time_seconds") or 0.0))):
        if len(unique) >= fill_budget:
            break
        maybe_add(candidate)

    return sorted(unique, key=lambda row: float(row.get("time_seconds") or 0.0))


def _raw_frame(path: str, time_seconds: float, width: int = 96, height: int = 54) -> Optional[bytes]:
    args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{time_seconds:.3f}",
        "-i",
        path,
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=rgb24",
        "-f",
        "rawvideo",
        "-",
    ]
    try:
        proc = subprocess.run(args, capture_output=True, timeout=180, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    expected = width * height * 3
    if proc.returncode != 0 or len(proc.stdout) < expected:
        return None
    return proc.stdout[:expected]


def _frame_metrics(raw: bytes) -> Dict[str, Any]:
    count = max(1, len(raw) // 3)
    lum_sum = 0.0
    bins = [0] * 16
    r_sum = g_sum = b_sum = 0
    for idx in range(0, len(raw), 3):
        r, g, b = raw[idx], raw[idx + 1], raw[idx + 2]
        r_sum += r
        g_sum += g
        b_sum += b
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        lum_sum += lum
        bins[min(15, int(lum // 16))] += 1
    return {
        "mean_luma": lum_sum / count,
        "mean_rgb": [r_sum / count, g_sum / count, b_sum / count],
        "luma_histogram_16": bins,
    }


def _frame_delta(raw_a: Optional[bytes], raw_b: Optional[bytes]) -> Optional[float]:
    if not raw_a or not raw_b:
        return None
    total = 0
    n = min(len(raw_a), len(raw_b))
    for idx in range(n):
        total += abs(raw_a[idx] - raw_b[idx])
    return total / max(1, n) / 255.0


def _export_analysis_frame(path: str, time_seconds: float, output_path: str) -> bool:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    code, _, _ = _run_command([
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{time_seconds:.3f}",
        "-i",
        path,
        "-frames:v",
        "1",
        "-q:v",
        "3",
        "-y",
        output_path,
    ], timeout=180)
    return code == 0 and os.path.isfile(output_path)


def _motion_and_keyframes(
    path: str,
    duration: Optional[float],
    scene_items: List[Dict[str, Any]],
    artifacts: Dict[str, Any],
    budget: int,
    *,
    fps: Optional[float] = None,
    cut_analysis: Optional[Dict[str, Any]] = None,
    write_frames: bool = True,
    sampling: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    sampled = []
    previous_raw = None
    required_boundary_frames = 0
    if isinstance(cut_analysis, dict):
        required_boundary_frames += len(cut_analysis.get("cut_points") or []) * 2
        required_boundary_frames += len(cut_analysis.get("flash_frame_candidates") or [])
    effective_budget = _compute_demand_driven_budget(budget, cut_analysis, duration, sampling=sampling)
    times = _sample_times(duration, scene_items, effective_budget, fps=fps, cut_analysis=cut_analysis, sampling=sampling)
    frames_dir = artifacts.get("frames_dir")
    for index, sample in enumerate(times, 1):
        time_seconds = float(sample.get("time_seconds") or 0.0)
        raw = _raw_frame(path, time_seconds)
        if not raw:
            continue
        metrics = _frame_metrics(raw)
        delta = _frame_delta(previous_raw, raw)
        previous_raw = raw
        frame_path = None
        if write_frames and frames_dir:
            candidate = os.path.join(frames_dir, f"sampled_{index:04d}.jpg")
            if _export_analysis_frame(path, time_seconds, candidate):
                frame_path = candidate
        sampled_row = {
            "index": index,
            "time_seconds": time_seconds,
            "selection_reason": sample.get("selection_reason") or "interval",
            "frame_path": frame_path,
            "metrics": metrics,
            "delta_from_previous": delta,
        }
        for key in ("cut_index", "cut_time_seconds", "boundary_role", "shot_index", "shot_start", "shot_end", "motion_peak"):
            if sample.get(key) not in (None, ""):
                sampled_row[key] = sample.get(key)
        sampled.append(sampled_row)
    deltas = [row["delta_from_previous"] for row in sampled if row.get("delta_from_previous") is not None]
    avg_delta = sum(deltas) / len(deltas) if deltas else 0.0
    max_delta = max(deltas) if deltas else 0.0
    if max_delta >= 0.08:
        for row in sampled:
            if row.get("delta_from_previous") == max_delta:
                row["motion_peak"] = True
                row["motion_peak_source_reason"] = row.get("selection_reason")
    if max_delta >= 0.2 or avg_delta >= 0.1:
        level = "high"
    elif max_delta >= 0.08 or avg_delta >= 0.035:
        level = "medium"
    else:
        level = "low"
    total_cut_points = len(cut_analysis.get("cut_points") or []) if isinstance(cut_analysis, dict) else 0
    cut_roles: Dict[Any, set] = {}
    for row in sampled:
        cut_index = row.get("cut_index")
        boundary_role = row.get("boundary_role")
        if cut_index in (None, "") or boundary_role in (None, ""):
            continue
        cut_roles.setdefault(cut_index, set()).add(boundary_role)
    paired_cut_boundaries = sum(
        1
        for roles in cut_roles.values()
        if {"last_frame_before_cut", "first_frame_after_cut"}.issubset(roles)
    )
    return {
        "success": True,
        "requested_sample_budget": int(budget or 0),
        "effective_sample_budget": effective_budget,
        "hard_frame_cap": HARD_FRAME_CAP,
        "cut_boundary_frames_requested": required_boundary_frames,
        "cut_boundary_sampling_capped": required_boundary_frames + 3 > HARD_FRAME_CAP,
        "cut_boundary_pairs_total": total_cut_points,
        "cut_boundary_pairs_sampled": paired_cut_boundaries,
        "cut_boundary_pair_coverage": paired_cut_boundaries / total_cut_points if total_cut_points else 1.0,
        "sample_count": len(sampled),
        "overall_motion_level": level,
        "average_frame_delta": avg_delta,
        "max_frame_delta": max_delta,
        "analysis_keyframes": sampled,
        "cut_analysis": cut_analysis or {},
    }


def seconds_to_srt_time(seconds: float) -> str:
    ms_total = int(round(max(0.0, seconds) * 1000))
    hours, rem = divmod(ms_total, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def seconds_to_vtt_time(seconds: float) -> str:
    return seconds_to_srt_time(seconds).replace(",", ".")


def segments_to_srt(segments: List[Dict[str, Any]]) -> str:
    lines = []
    for index, segment in enumerate(segments, 1):
        start = seconds_to_srt_time(float(segment.get("start", 0)))
        end = seconds_to_srt_time(float(segment.get("end", segment.get("start", 0))))
        text = str(segment.get("text", "")).strip()
        lines.append(f"{index}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def segments_to_vtt(segments: List[Dict[str, Any]]) -> str:
    lines = ["WEBVTT\n"]
    for segment in segments:
        start = seconds_to_vtt_time(float(segment.get("start", 0)))
        end = seconds_to_vtt_time(float(segment.get("end", segment.get("start", 0))))
        text = str(segment.get("text", "")).strip()
        lines.append(f"{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp-{os.getpid()}-{threading.get_ident()}-{time.time_ns()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _iter_analysis_reports(project_root: str) -> List[Tuple[str, Dict[str, Any]]]:
    clips_root = os.path.join(normalize_path(project_root), "clips")
    reports: List[Tuple[str, Dict[str, Any]]] = []
    if not os.path.isdir(clips_root):
        return reports
    for dirpath, _, filenames in os.walk(clips_root):
        if "analysis.json" not in filenames:
            continue
        path = os.path.join(dirpath, "analysis.json")
        try:
            reports.append((path, _read_json(path)))
        except (OSError, json.JSONDecodeError):
            continue
    return reports


def _normalized_report_match_value(value: Any, *, path_like: bool = False) -> Optional[str]:
    if value in (None, ""):
        return None
    if path_like:
        try:
            return normalize_path(value)
        except Exception:
            return str(value)
    return str(value)


def _report_matches_record(report: Dict[str, Any], record: Dict[str, Any]) -> bool:
    clip = report.get("clip") or {}
    report_source = _normalized_report_match_value(report.get("source_file") or clip.get("file_path"), path_like=True)
    record_source = _normalized_report_match_value(record.get("file_path"), path_like=True)
    if report_source and record_source and report_source == record_source:
        return True
    for key in ("clip_id", "media_id"):
        report_value = _normalized_report_match_value(clip.get(key))
        record_value = _normalized_report_match_value(record.get(key))
        if report_value and record_value and report_value == record_value:
            return True
    return False


def _report_missing_layers(report: Dict[str, Any], depth: str, options: Dict[str, Any]) -> List[str]:
    missing = []
    if not report.get("technical"):
        missing.append("technical")
    if not report.get("clip_analysis_markers"):
        missing.append("marker_plan")
    if depth in {"standard", "deep", "custom"}:
        motion = report.get("motion") or {}
        readthrough = report.get("readthrough") or {}
        if not motion or motion.get("status") == "skipped":
            missing.append("motion")
        if not readthrough or readthrough.get("reason") == "quick analysis depth":
            missing.append("readthrough")
        if not isinstance(readthrough.get("cut_analysis"), dict):
            missing.append("cut_analysis")
    transcription = options.get("transcription") or {}
    if _coerce_bool(transcription.get("enabled"), default=DEFAULT_TRANSCRIPTION_ENABLED):
        transcript = report.get("transcription") or {}
        if not transcript.get("success") or transcript.get("status") == "skipped":
            missing.append("transcription")
    vision = options.get("vision") or {}
    if _coerce_bool(vision.get("enabled"), default=False):
        visual = report.get("visual") or {}
        if not visual.get("success") or visual.get("status") == "skipped":
            missing.append("vision")
    return missing


def _report_cache_state(
    report: Dict[str, Any],
    request_signature: Dict[str, Any],
    *,
    max_report_age_days: Optional[float] = None,
    reuse_policy: str = "compatible",
) -> Tuple[List[str], List[str]]:
    issues: List[str] = []
    warnings: List[str] = []

    analyzed_ts = _timestamp_from_analyzed_at(report.get("analyzed_at"))
    if max_report_age_days is not None:
        if analyzed_ts is None:
            issues.append("analysis_age_unknown")
        else:
            age_days = (time.time() - analyzed_ts) / 86400.0
            if age_days > max_report_age_days:
                issues.append(f"analysis_older_than_{max_report_age_days:g}_days")

    report_signature = report.get("analysis_signature") or {}
    if not report_signature:
        message = "analysis_signature_missing"
        if reuse_policy in {"fresh", "strict"}:
            issues.append(message)
        else:
            warnings.append(message)
        return issues, warnings

    if report_signature.get("analysis_version") != request_signature.get("analysis_version"):
        issues.append("analysis_version_changed")

    report_source = report_signature.get("source_file") or {}
    request_source = request_signature.get("source_file") or {}
    if report_source.get("path") and request_source.get("path") and report_source.get("path") != request_source.get("path"):
        issues.append("source_path_changed")
    for key in ("size_bytes", "mtime_ns"):
        report_value = report_source.get(key)
        request_value = request_source.get(key)
        if report_value is not None and request_value is not None and report_value != request_value:
            issues.append(f"source_{key}_changed")

    report_budget = int(report_signature.get("analysis_keyframe_budget") or 0)
    request_budget = int(request_signature.get("analysis_keyframe_budget") or 0)
    if report_budget < request_budget:
        issues.append("analysis_keyframe_budget_lower_than_requested")

    # Sampling-mode reconciliation: a prior report sampled under a less-thorough
    # mode can't satisfy a request for a more-thorough one. The reverse (richer
    # report, cheaper request) is reused as a free upgrade.
    report_mode = (report_signature.get("analysis_sampling") or {}).get("mode")
    request_mode = (request_signature.get("analysis_sampling") or {}).get("mode")
    if request_mode and report_mode and request_mode != report_mode:
        if SAMPLING_MODE_RANK.get(request_mode, 0) > SAMPLING_MODE_RANK.get(report_mode, 0):
            issues.append("sampling_mode_increased")

    report_layers = report_signature.get("layers") or {}
    request_layers = request_signature.get("layers") or {}
    report_vision = report_layers.get("vision") or {}
    request_vision = request_layers.get("vision") or {}
    if request_vision.get("enabled"):
        if report_vision.get("provider") and request_vision.get("provider") and report_vision.get("provider") != request_vision.get("provider"):
            issues.append("vision_provider_changed")
        if report_vision.get("prompt_hash") and request_vision.get("prompt_hash") and report_vision.get("prompt_hash") != request_vision.get("prompt_hash"):
            issues.append("vision_prompt_changed")

    report_transcription = report_layers.get("transcription") or {}
    request_transcription = request_layers.get("transcription") or {}
    if request_transcription.get("enabled"):
        for key in ("backend", "model", "language"):
            report_value = report_transcription.get(key)
            request_value = request_transcription.get(key)
            if report_value and request_value and report_value != request_value:
                issues.append(f"transcription_{key}_changed")

    return issues, warnings


def find_reusable_report(
    project_root: str,
    record: Dict[str, Any],
    depth: str,
    options: Dict[str, Any],
    *,
    request_signature: Optional[Dict[str, Any]] = None,
    max_report_age_days: Optional[float] = None,
    reuse_policy: str = "compatible",
) -> Optional[Dict[str, Any]]:
    """Find an existing analysis report that satisfies the requested layers."""
    frame_count = int((request_signature or {}).get("analysis_keyframe_budget") or FRAME_CAPS.get(depth, FRAME_CAPS[DEFAULT_DEPTH]))
    request_signature = request_signature or analysis_request_signature(record, depth, options, frame_count)
    matches = []
    for path, report in _iter_analysis_reports(project_root):
        if not _report_matches_record(report, record):
            continue
        missing = _report_missing_layers(report, depth, options)
        cache_issues, cache_warnings = _report_cache_state(
            report,
            request_signature,
            max_report_age_days=max_report_age_days,
            reuse_policy=reuse_policy,
        )
        superseded = registry_entry_superseded_info(project_root, path)
        if superseded:
            cache_issues = list(cache_issues) + [
                f"source_relinked:{superseded.get('superseded_reason') or 'source_relinked'}"
            ]
        matches.append({
            "path": path,
            "report": report,
            "missing_layers": missing,
            "cache_issues": cache_issues,
            "cache_warnings": cache_warnings,
            "analyzed_at": report.get("analyzed_at"),
            "analyzed_timestamp": _timestamp_from_analyzed_at(report.get("analyzed_at")) or 0,
            "superseded_by_relink": bool(superseded),
            "superseded_at": (superseded or {}).get("superseded_at"),
            "superseded_reason": (superseded or {}).get("superseded_reason"),
        })
    if not matches:
        return None
    matches.sort(key=lambda row: (
        len(row["missing_layers"]) + len(row["cache_issues"]),
        -float(row.get("analyzed_timestamp") or 0),
    ))
    best = matches[0]
    result: Dict[str, Any] = {
        "path": best["path"],
        "missing_layers": best["missing_layers"],
        "cache_issues": best["cache_issues"],
        "cache_warnings": best["cache_warnings"],
        "analyzed_at": best.get("analyzed_at"),
    }
    if best.get("superseded_by_relink"):
        result["superseded_by_relink"] = True
        result["superseded_at"] = best.get("superseded_at")
        result["superseded_reason"] = best.get("superseded_reason")
    if best["missing_layers"] or best["cache_issues"]:
        result["reusable"] = False
        return result
    result["reusable"] = True
    result["report"] = best["report"]
    return result


def _record_analysis_report_paths(record: Dict[str, Any]) -> List[str]:
    paths: List[str] = []
    for key in (
        "analysis_report_path",
        "analysisReportPath",
        "published_analysis_report_path",
        "publishedAnalysisReportPath",
    ):
        value = record.get(key)
        if isinstance(value, str):
            paths.append(value)
        elif isinstance(value, list):
            paths.extend(str(item) for item in value if item)

    third_party = record.get("third_party_metadata") or record.get("thirdPartyMetadata")
    if isinstance(third_party, dict):
        value = third_party.get("davinci_resolve_mcp.analysis_report_path")
        if value:
            paths.append(str(value))

    deduped: List[str] = []
    for path in paths:
        normalized = normalize_path(path)
        if normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _analysis_project_root_from_report_path(path: str) -> Optional[str]:
    return _analysis_report_project_root(path)


def _record_analysis_provenance(record: Dict[str, Any]) -> Dict[str, Any]:
    provenance = record.get("analysis_provenance")
    if isinstance(provenance, dict) and provenance:
        return dict(provenance)

    found: Dict[str, Any] = {}
    report_paths = _record_analysis_report_paths(record)
    if report_paths:
        found["analysis_report_paths"] = report_paths
    for key in ("published_analysis_signature", "publishedAnalysisSignature"):
        if record.get(key):
            found["analysis_signature"] = record.get(key)
            break
    for key in ("published_analysis_at", "publishedAnalysisAt"):
        if record.get(key):
            found["published_at"] = record.get(key)
            break
    third_party = record.get("third_party_metadata") or record.get("thirdPartyMetadata")
    if isinstance(third_party, dict):
        third_party_keys = sorted(
            key for key in third_party
            if str(key).startswith("davinci_resolve_mcp.")
        )
        if third_party_keys:
            found["third_party_keys"] = third_party_keys
    if record.get("analysis_metadata_present"):
        found["standard_metadata_present"] = True
        if record.get("analysis_metadata_fields"):
            found["standard_metadata_fields"] = list(record.get("analysis_metadata_fields") or [])
    return found


def _record_has_analysis_provenance(record: Dict[str, Any]) -> bool:
    return bool(_record_analysis_provenance(record))


def _reuse_issue_summary(existing: Optional[Dict[str, Any]]) -> List[str]:
    if not existing:
        return []
    issues: List[str] = []
    issues.extend(str(item) for item in existing.get("missing_layers") or [])
    issues.extend(str(item) for item in existing.get("cache_issues") or [])
    return issues


def _why_not_reused(existing: Optional[Dict[str, Any]], *, provenance_present: bool = False) -> str:
    if existing:
        issues = _reuse_issue_summary(existing)
        if issues:
            return "Existing analysis was found but could not be reused: " + ", ".join(issues)
        return "Existing analysis was found but was not marked reusable."
    if provenance_present:
        return "Resolve metadata indicates prior MCP analysis, but no reusable analysis report could be validated."
    return "No existing compatible analysis report was found."


def _mark_reuse_blocked(clip_plan: Dict[str, Any], record: Dict[str, Any], existing: Optional[Dict[str, Any]]) -> None:
    provenance = _record_analysis_provenance(record)
    clip_plan["cache_status"] = "reuse_blocked"
    clip_plan["reuse_blocked"] = True
    clip_plan["analysis_provenance"] = provenance
    clip_plan["why_not_reused"] = _why_not_reused(existing, provenance_present=True)
    clip_plan["reuse_block_reason"] = (
        "Analysis provenance is already published on this Resolve clip, but the planner "
        "could not validate a compatible report. Pass force_refresh=true to intentionally "
        "reanalyze, or restore the referenced analysis report."
    )
    if existing:
        clip_plan["reuse_block_issues"] = _reuse_issue_summary(existing)


def _report_path_candidate_issue(path: str, issue: str) -> Dict[str, Any]:
    return {
        "path": normalize_path(path),
        "missing_layers": [],
        "cache_issues": [issue],
        "cache_warnings": [],
        "analyzed_at": None,
        "reusable": False,
        "source": "record_analysis_report_path",
    }


def find_reusable_report_from_path(
    report_path: str,
    record: Dict[str, Any],
    depth: str,
    options: Dict[str, Any],
    *,
    request_signature: Optional[Dict[str, Any]] = None,
    max_report_age_days: Optional[float] = None,
    reuse_policy: str = "compatible",
) -> Optional[Dict[str, Any]]:
    """Validate a report path published on the Resolve clip and score it for reuse."""
    candidate_path = normalize_path(report_path)
    project_root = _analysis_project_root_from_report_path(candidate_path)
    if not project_root:
        return _report_path_candidate_issue(candidate_path, "analysis_report_path_not_analysis_json_layout")
    if not os.path.isfile(candidate_path):
        return _report_path_candidate_issue(candidate_path, "analysis_report_path_missing")

    try:
        report = _read_json(candidate_path)
    except (OSError, json.JSONDecodeError):
        return _report_path_candidate_issue(candidate_path, "analysis_report_path_unreadable")

    if not _report_matches_record(report, record):
        return _report_path_candidate_issue(candidate_path, "analysis_report_path_record_mismatch")

    frame_count = int((request_signature or {}).get("analysis_keyframe_budget") or FRAME_CAPS.get(depth, FRAME_CAPS[DEFAULT_DEPTH]))
    request_signature = request_signature or analysis_request_signature(record, depth, options, frame_count)
    missing = _report_missing_layers(report, depth, options)
    cache_issues, cache_warnings = _report_cache_state(
        report,
        request_signature,
        max_report_age_days=max_report_age_days,
        reuse_policy=reuse_policy,
    )
    superseded = registry_entry_superseded_info(project_root, candidate_path)
    if superseded:
        cache_issues = list(cache_issues) + [
            f"source_relinked:{superseded.get('superseded_reason') or 'source_relinked'}"
        ]
    base = {
        "path": candidate_path,
        "missing_layers": missing,
        "cache_issues": cache_issues,
        "cache_warnings": cache_warnings,
        "analyzed_at": report.get("analyzed_at"),
        "project_root": project_root,
        "source": "record_analysis_report_path",
    }
    if superseded:
        base["superseded_by_relink"] = True
        base["superseded_at"] = superseded.get("superseded_at")
        base["superseded_reason"] = superseded.get("superseded_reason")
    if missing or cache_issues:
        return {**base, "reusable": False}
    return {**base, "reusable": True, "report": report}


def find_reusable_report_from_registry(
    project_root: str,
    record: Dict[str, Any],
    depth: str,
    options: Dict[str, Any],
    *,
    request_signature: Optional[Dict[str, Any]] = None,
    max_report_age_days: Optional[float] = None,
    reuse_policy: str = "compatible",
) -> Optional[Dict[str, Any]]:
    registry = _read_analysis_registry(project_root)
    candidates: List[Dict[str, Any]] = []
    for entry in registry.get("entries") or []:
        if not isinstance(entry, dict) or not _registry_entry_matches_record(entry, record):
            continue
        report_path = entry.get("analysis_json")
        if not report_path:
            continue
        candidate = find_reusable_report_from_path(
            str(report_path),
            record,
            depth,
            options,
            request_signature=request_signature,
            max_report_age_days=max_report_age_days,
            reuse_policy=reuse_policy,
        )
        if not candidate:
            continue
        candidate = dict(candidate)
        candidate["source"] = "analysis_registry"
        candidate["registry_path"] = analysis_registry_path(project_root)
        candidates.append(candidate)
    if not candidates:
        return None
    reusable = [row for row in candidates if row.get("reusable")]
    pool = reusable or candidates
    pool.sort(key=_report_reuse_score)
    return pool[0]


def _report_reuse_score(candidate: Optional[Dict[str, Any]]) -> Tuple[int, float]:
    if not candidate:
        return (9999, 0.0)
    missing = candidate.get("missing_layers") or []
    issues = candidate.get("cache_issues") or []
    timestamp = _timestamp_from_analyzed_at(candidate.get("analyzed_at")) or 0
    return (len(missing) + len(issues), -float(timestamp))


def find_reusable_report_across_roots(
    project_roots: Iterable[Any],
    record: Dict[str, Any],
    depth: str,
    options: Dict[str, Any],
    *,
    request_signature: Optional[Dict[str, Any]] = None,
    max_report_age_days: Optional[float] = None,
    reuse_policy: str = "compatible",
) -> Optional[Dict[str, Any]]:
    """Find the best compatible report across active and prior project roots."""
    candidates: List[Dict[str, Any]] = []
    seen_roots = set()
    for raw_root in project_roots or []:
        if not raw_root:
            continue
        root = normalize_path(raw_root)
        if root in seen_roots:
            continue
        seen_roots.add(root)
        candidate = find_reusable_report(
            root,
            record,
            depth,
            options,
            request_signature=request_signature,
            max_report_age_days=max_report_age_days,
            reuse_policy=reuse_policy,
        )
        if not candidate:
            continue
        candidate = dict(candidate)
        candidate["project_root"] = root
        candidates.append(candidate)
    if not candidates:
        return None
    reusable = [row for row in candidates if row.get("reusable")]
    pool = reusable or candidates
    pool.sort(key=_report_reuse_score)
    return pool[0]


def _normalize_word_timestamps(raw_words: Any) -> List[Dict[str, Any]]:
    words: List[Dict[str, Any]] = []
    if not isinstance(raw_words, list):
        return words
    for raw_word in raw_words:
        if not isinstance(raw_word, dict):
            continue
        text = str(raw_word.get("word", raw_word.get("text", ""))).strip()
        start = _parse_float(raw_word.get("start"))
        end = _parse_float(raw_word.get("end"))
        word: Dict[str, Any] = {
            "word": text,
            "start": start,
            "end": end if end is not None else start,
        }
        for key in ("probability", "confidence", "score"):
            value = _parse_float(raw_word.get(key))
            if value is not None:
                word[key] = value
        words.append({key: value for key, value in word.items() if value not in (None, "")})
    return words


def _normalize_transcript_payload(raw: Dict[str, Any], backend: str, language: Optional[str] = None) -> Dict[str, Any]:
    segments = []
    all_words: List[Dict[str, Any]] = []
    for segment in raw.get("segments") or []:
        start = _parse_float(segment.get("start")) or 0.0
        end = _parse_float(segment.get("end"))
        if end is None:
            end = start
        normalized_segment = {
            "start": start,
            "end": end,
            "text": str(segment.get("text", "")).strip(),
        }
        words = _normalize_word_timestamps(segment.get("words"))
        if words:
            normalized_segment["words"] = words
            all_words.extend(words)
        segments.append(normalized_segment)
    top_level_words = _normalize_word_timestamps(raw.get("words"))
    if top_level_words:
        all_words = top_level_words
    text = raw.get("text")
    if text is None:
        text = " ".join(segment.get("text", "") for segment in segments).strip()
    payload = {
        "success": True,
        "backend": backend,
        "language": raw.get("language") or language or "unknown",
        "text": text,
        "segments": segments,
    }
    if all_words:
        payload["words"] = all_words
    return payload


def _write_transcript_artifacts(payload: Dict[str, Any], artifacts: Dict[str, Any]) -> None:
    if artifacts.get("transcript_json"):
        _write_json(artifacts["transcript_json"], payload)
    if artifacts.get("transcript_srt"):
        _write_text(artifacts["transcript_srt"], segments_to_srt(payload.get("segments", [])))
    if artifacts.get("transcript_vtt"):
        _write_text(artifacts["transcript_vtt"], segments_to_vtt(payload.get("segments", [])))


def _transcribe_with_whisper_cli(path: str, artifacts: Dict[str, Any], transcription: Dict[str, Any]) -> Dict[str, Any]:
    whisper = shutil.which("whisper")
    if not whisper:
        return {"success": False, "status": "skipped", "backend": "whisper_cli", "reason": "whisper CLI not found"}
    work_dir = os.path.join(os.path.dirname(artifacts.get("transcript_json") or artifacts["analysis_json"]), "transcript-work")
    os.makedirs(work_dir, exist_ok=True)
    # Default to capturing per-word timestamps so editor / word-snap features
    # work out of the box. Callers can opt out with word_timestamps=False.
    want_words = _coerce_bool(transcription.get("word_timestamps", True), default=True)
    cmd = [
        whisper,
        path,
        "--model",
        str(transcription.get("model") or "base"),
        "--output_format",
        "json",
        "--output_dir",
        work_dir,
        "--word_timestamps",
        "True" if want_words else "False",
    ]
    if transcription.get("language"):
        cmd.extend(["--language", str(transcription["language"])])
    code, _, stderr = _run_command(cmd, timeout=int(transcription.get("timeout", 1800)))
    if code != 0:
        return {"success": False, "backend": "whisper_cli", "error": stderr.strip() or "whisper CLI failed"}
    json_files = sorted(Path(work_dir).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_files:
        return {"success": False, "backend": "whisper_cli", "error": "whisper CLI produced no JSON output"}
    raw = _read_json(str(json_files[0]))
    payload = _normalize_transcript_payload(raw, "whisper_cli", transcription.get("language"))
    _write_transcript_artifacts(payload, artifacts)
    return payload


def _transcribe_with_mlx_whisper(path: str, artifacts: Dict[str, Any], transcription: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import mlx_whisper  # type: ignore[import-not-found]
    except ImportError:
        return {"success": False, "status": "skipped", "backend": "mlx_whisper", "reason": "mlx_whisper module not found"}
    model = transcription.get("model") or "mlx-community/whisper-large-v3-turbo"
    kwargs = {}
    if transcription.get("language"):
        kwargs["language"] = transcription["language"]
    raw = mlx_whisper.transcribe(
        path,
        path_or_hf_repo=model,
        word_timestamps=_coerce_bool(transcription.get("word_timestamps", True), default=True),
        verbose=False,
        **kwargs,
    )
    payload = _normalize_transcript_payload(raw, "mlx_whisper", transcription.get("language"))
    _write_transcript_artifacts(payload, artifacts)
    return payload


def _transcribe(path: str, artifacts: Dict[str, Any], options: Dict[str, Any], capabilities: Dict[str, Any]) -> Dict[str, Any]:
    transcription = options.get("transcription") or {}
    if not _coerce_bool(transcription.get("enabled"), default=DEFAULT_TRANSCRIPTION_ENABLED):
        return {"success": True, "status": "skipped", "reason": "transcription disabled"}
    backend = transcription.get("backend")
    if not backend:
        backends = capabilities.get("transcription", {}).get("backends") or []
        backend = backends[0] if backends else None

    # Pre-call refusal: transcription token cost roughly scales with audio
    # duration. We don't always know duration upfront, but if the caller
    # injected it via options['duration_seconds'] we can estimate and refuse.
    duration_seconds = 0
    try:
        duration_seconds = int(float(options.get("duration_seconds") or transcription.get("duration_seconds") or 0))
    except (TypeError, ValueError):
        duration_seconds = 0
    if duration_seconds > 0:
        estimated_tokens = duration_seconds * AVG_TRANSCRIPTION_TOKENS_PER_SECOND
        refusal = _check_caps_pre_call(
            project_root=options.get("project_root"),
            estimated_vision_tokens=estimated_tokens,
            clip_id=options.get("clip_id"),
            job_id=options.get("job_id"),
        )
        if refusal is not None:
            refusal["backend"] = backend
            return refusal

    # Wall-clock timeout wrapper. Whisper / mlx_whisper / ffmpeg can hang on a
    # corrupt file or take far longer than expected on a long clip; cap them.
    caps = _resolve_active_caps()
    timeout = caps.wall_clock_seconds_per_call
    started_at = time.time()

    def _run_backend() -> Dict[str, Any]:
        if backend in {"mock", "local_mock"}:
            segments = transcription.get("segments") or [{"start": 0.0, "end": 1.0, "text": "Mock local transcript segment."}]
            payload = {"success": True, "backend": backend, "language": transcription.get("language", "unknown"), "segments": segments, "text": " ".join(s.get("text", "") for s in segments)}
            _write_transcript_artifacts(payload, artifacts)
            return payload
        if backend in {"whisper_cli", "mlx_whisper"}:
            if not _coerce_bool(transcription.get("allow_model_download"), default=False):
                return {
                    "success": False,
                    "status": "skipped",
                    "backend": backend,
                    "reason": "Local transcription may download model files; set allow_model_download=true explicitly to run it.",
                }
            if backend == "whisper_cli":
                return _transcribe_with_whisper_cli(path, artifacts, transcription)
            return _transcribe_with_mlx_whisper(path, artifacts, transcription)
        return {"success": False, "status": "fallthrough", "backend": backend}

    try:
        result = _analysis_caps.run_with_timeout(_run_backend, timeout)
    except _analysis_caps.WallClockTimeout as exc:
        elapsed = round((time.time() - started_at) * 1000)
        return {
            "success": False,
            "status": "wall_clock_timeout",
            "backend": backend,
            "reason": str(exc),
            "elapsed_ms": elapsed,
        }
    # Record actual wall-clock for caps usage tracking.
    try:
        elapsed_ms = round((time.time() - started_at) * 1000)
        if options.get("project_root"):
            _record_caps_usage(
                project_root=options.get("project_root"),
                clip_id=options.get("clip_id"),
                job_id=options.get("job_id"),
                wall_clock_ms=elapsed_ms,
            )
    except Exception:
        pass

    # The fallthrough for non-(mock|whisper) backends still happens via the
    # original branches below so behaviour stays identical for those.
    if result is not None and result.get("status") != "fallthrough":
        return result
    if backend in {"mock", "local_mock", "whisper_cli", "mlx_whisper"}:
        return result if result is not None else {"success": False, "backend": backend}
    elif backend == "whisper_cpp":
        if not transcription.get("model_path"):
            return {
                "success": False,
                "status": "skipped",
                "backend": backend,
                "reason": "whisper_cpp requires an explicit model_path; no model files are downloaded automatically.",
            }
        return {
            "success": False,
            "status": "not_implemented",
            "backend": backend,
            "reason": "whisper_cpp execution needs per-install CLI validation before enabling.",
        }
    elif backend == "resolve":
        return {
            "success": False,
            "status": "skipped",
            "backend": backend,
            "reason": "Resolve-native transcription mutates Resolve project state; use explicit media_pool_item/folder transcription actions.",
        }
    else:
        return {"success": False, "status": "skipped", "reason": "No local transcription backend available"}


_SUMMARY_STYLE_DIRECTIVES = {
    "full": (
        "Use the full schema as written. Populate every applicable field; "
        "do not trim narrative content or omit observations to save words."
    ),
    "concise": (
        "Bias narrative fields toward brevity while keeping every schema field "
        "populated. Targets: `clip_summary` is 1-2 sentences (not 2-4); each "
        "shot `description` is 1 sentence; `composition_notes`, `pacing_note`, "
        "and `emotional_register` reduce to the single most important "
        "observation or `null` if there is nothing distinct to say. Do not "
        "drop fields; do not fabricate detail to fill them either."
    ),
    "creative": (
        "Bias narrative fields toward editorial vibes — tone, atmosphere, "
        "intent, performance, and how the shot might earn its place in a cut. "
        "`clip_summary` and shot `description` should read like an assistant "
        "editor's first-impression note (concrete imagery + editorial read), "
        "not a forensic inventory. `editorial_role`, `select_potential`, "
        "`best_moment`, `pacing`, and `emotional_register` deserve full "
        "attention. Keep `confidence` values honest and continue to hedge "
        "identity / intent claims when frame evidence is thin."
    ),
    "technical": (
        "Bias narrative fields toward camera, exposure, lighting, and QC. "
        "`composition_notes`, `framing`, `camera_height`, `camera_motion`, "
        "`lens_character`, `lens_format`, `lighting`, `color_mood`, "
        "`audio_character`, and `qc_flags` deserve full attention. Subject "
        "performance / emotional register stays terse (one observation or "
        "`null`). `clip_summary` reads like a camera operator's or QC pass "
        "note — what's in the frame technically, what works or doesn't, "
        "what an editor needs to know to use this shot."
    ),
}


def _build_summary_style_directive(value: Any) -> Optional[str]:
    """Map an analysis_summary_style value to a short narrative-tone directive
    that biases the vision model's wording without changing the schema.

    Returns the directive string, or None for `full` (default behavior).
    """
    style = (str(value).strip().lower() if value else "")
    if not style or style == "full":
        return None
    # Backwards-compat: legacy enum values get folded into the new four-option
    # scheme. Saved prefs files from older installs may still have these.
    legacy = {
        "assistant_editor": "creative",
        "assistant": "creative",
        "editor": "creative",
        "producer": "creative",
        "qc": "technical",
        "qc_focus": "technical",
        "qc_focused": "technical",
    }
    style = legacy.get(style, style)
    return _SUMMARY_STYLE_DIRECTIVES.get(style)


def _build_vision_prompt_with_source_trust(
    *,
    base_prompt: str,
    source_trust: Optional[str],
    file_path: Optional[str],
    clip_name: Optional[str],
    summary_style: Optional[str] = None,
) -> str:
    """V2 P11: Prepend a source-trust preamble when the caller has signaled
    that the clip's filename / context can be used as supporting evidence.

    Trust levels:
      - None / "auto" (default) — no preamble; conservative-by-default
      - "filename" — filename may corroborate frame evidence; hedge if uncorroborated
      - "low" / "medium" / "high" — explicit trust for all available context

    The preamble adjusts conservative-by-default tone *upward* (allows using
    available context) without raising the per-field confidence ceiling
    (vision still hedges via confidence values when evidence is thin).
    """
    trust = (str(source_trust).strip().lower() if source_trust else "auto")
    style_directive = _build_summary_style_directive(summary_style)

    if trust in ("", "auto", "none"):
        if not style_directive:
            return base_prompt
        style_preamble = (
            f"\n=== NARRATIVE STYLE ===\n"
            f"analysis_summary_style: {str(summary_style).strip().lower()}\n\n"
            f"{style_directive}\n"
            f"=== END NARRATIVE STYLE ===\n\n"
        )
        return style_preamble + base_prompt

    if trust == "filename":
        explanation = (
            "The clip filename and any visible on-screen text may be used as supporting "
            "evidence for identity, location, and editorial classification claims. Still "
            "hedge in the `confidence` fields when frame evidence alone wouldn't support "
            "the claim — the trust override raises the floor for using available context, "
            "not the ceiling for asserting facts."
        )
    elif trust == "low":
        explanation = (
            "Source trust is LOW. Treat frames as the primary evidence; ignore filename and "
            "outside context. Hedge identity / intent / value claims aggressively; default "
            "confidence to `low` unless frame evidence is unambiguous."
        )
    elif trust == "medium":
        explanation = (
            "Source trust is MEDIUM. Use frames as primary evidence; filename and visible "
            "text may corroborate. Cultural recognition (well-known people, locations, "
            "brands) is allowed when frames support it. Maintain conservative confidence."
        )
    elif trust == "high":
        explanation = (
            "Source trust is HIGH. The clip is from a known archival or trusted source. "
            "Use filename, visible text, frame evidence, and cultural recognition together "
            "to make confident editorial claims. Hedge only when sources actively conflict "
            "(e.g. filename says X but frames clearly show Y)."
        )
    else:
        # Unknown trust level — pass through with a note instead of failing
        explanation = (
            f"Source trust level '{trust}' is not a recognized value (use one of: "
            "auto, filename, low, medium, high). Defaulting to conservative-by-default."
        )

    filename_line = ""
    if file_path or clip_name:
        import os as _os
        basename = _os.path.basename(file_path) if file_path else None
        filename_line = f"\nClip filename: {basename or clip_name}"

    preamble = (
        f"\n=== SOURCE TRUST CONTEXT ===\n"
        f"source_trust: {trust}{filename_line}\n\n"
        f"{explanation}\n"
        f"=== END SOURCE TRUST CONTEXT ===\n\n"
    )
    if style_directive:
        style_preamble = (
            f"\n=== NARRATIVE STYLE ===\n"
            f"analysis_summary_style: {str(summary_style).strip().lower()}\n\n"
            f"{style_directive}\n"
            f"=== END NARRATIVE STYLE ===\n\n"
        )
        return style_preamble + preamble + base_prompt
    return preamble + base_prompt


def build_host_chat_paths_payload(
    record: Dict[str, Any],
    motion: Dict[str, Any],
    options: Dict[str, Any],
    artifacts: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the deferred-vision payload the host chat must complete via commit_vision.

    Returns a dict with absolute frame_paths, per-frame metadata, the analysis prompt,
    the response schema, and a commit_action describing the follow-up tool call.
    """
    vision = options.get("vision") or {}
    frame_metadata: List[Dict[str, Any]] = []
    frame_paths: List[str] = []
    for index, frame in enumerate(motion.get("analysis_keyframes") or [], 1):
        frame_path = frame.get("frame_path")
        if not frame_path or not os.path.isfile(frame_path):
            continue
        absolute = normalize_path(frame_path)
        frame_paths.append(absolute)
        row: Dict[str, Any] = {
            "frame_index": index,
            "frame_path": absolute,
            "time_seconds": frame.get("time_seconds"),
            "selection_reason": frame.get("selection_reason"),
            "delta_from_previous": frame.get("delta_from_previous"),
        }
        for key in (
            "cut_index", "cut_time_seconds", "boundary_role",
            "shot_index", "shot_start", "shot_end",
            "motion_peak", "motion_peak_source_reason",
        ):
            if frame.get(key) not in (None, ""):
                row[key] = frame.get(key)
        frame_metadata.append(row)

    clip_dir = artifacts.get("clip_dir") or ""
    project_root = normalize_path(os.path.dirname(os.path.dirname(clip_dir))) if clip_dir else None
    clip_id = record.get("clip_id") or record.get("media_id")
    file_path = record.get("file_path")
    vision_token = short_hash(json.dumps({
        "clip_id": clip_id,
        "file_path": file_path,
        "clip_dir": clip_dir,
        "frame_paths": frame_paths,
        "analysis_version": ANALYSIS_VERSION,
    }, sort_keys=True), length=16)

    motion_summary = {
        key: motion.get(key)
        for key in (
            "overall_motion_level",
            "average_frame_delta",
            "max_frame_delta",
            "requested_sample_budget",
            "effective_sample_budget",
            "cut_boundary_pairs_total",
            "cut_boundary_pairs_sampled",
            "cut_boundary_pair_coverage",
            "cut_boundary_sampling_capped",
        )
        if motion.get(key) is not None
    }
    cut_analysis = motion.get("cut_analysis") if isinstance(motion.get("cut_analysis"), dict) else {}
    cut_summary = {
        "cut_count": cut_analysis.get("cut_count", 0),
        "cut_density_per_minute": cut_analysis.get("cut_density_per_minute"),
        "likely_edited_sequence": bool(cut_analysis.get("likely_edited_sequence")),
        "flash_frame_candidates": cut_analysis.get("flash_frame_candidates") or [],
        "cut_points": (cut_analysis.get("cut_points") or [])[:48],
        "notes": cut_analysis.get("notes") or [],
    }

    shot_table: List[Dict[str, Any]] = []
    for shot in cut_analysis.get("shot_ranges") or []:
        if not isinstance(shot, dict):
            continue
        s_index = shot.get("index")
        s_start = _parse_float(shot.get("start"))
        s_end = _parse_float(shot.get("end"))
        if s_index in (None, "") or s_start is None or s_end is None:
            continue
        frame_indices: List[int] = []
        for row in frame_metadata:
            t = _parse_float(row.get("time_seconds"))
            if t is None:
                continue
            if s_start <= t < s_end or (s_end == t and row is frame_metadata[-1]):
                frame_indices.append(int(row.get("frame_index")))
        shot_table.append({
            "shot_index": int(s_index),
            "time_seconds_start": float(s_start),
            "time_seconds_end": float(s_end),
            "duration_seconds": float(s_end) - float(s_start),
            "frame_indices": frame_indices,
            "has_in_shot_frame": bool(frame_indices),
        })

    commit_params: Dict[str, Any] = {
        "vision_token": vision_token,
        "visual": "<host chat: fill this with JSON matching `schema`>",
    }
    if clip_id:
        commit_params["clip_id"] = str(clip_id)
    if file_path:
        commit_params["file_path"] = file_path
    if project_root:
        commit_params["analysis_root"] = project_root

    effective_source_trust = _resolve_source_trust(options)
    # Apply caps: clip frame_paths to caps.frames_per_clip and downscale each
    # frame to caps.max_frame_dim_pixels (in place). frame_metadata stays a
    # superset — the host can still see what would have been sent at higher caps.
    frame_paths_capped = _cap_frames_for_active_caps(frame_paths)
    if len(frame_paths_capped) != len(frame_paths):
        # Drop metadata rows for frames we excluded; host shouldn't be told to read
        # files we're not actually sending.
        kept_set = set(frame_paths_capped)
        frame_metadata = [m for m in frame_metadata if m.get("frame_path") in kept_set]

    # Pre-call budget refusal: estimate tokens this call WILL spend if the host
    # processes it, and refuse if any cumulative cap is exhausted. The host
    # might have a cheaper tokenizer, but estimating high is the safe default —
    # the alternative is "discovering" the overrun after the fact.
    estimated_tokens = len(frame_paths_capped) * AVG_VISION_TOKENS_PER_FRAME
    refusal = _check_caps_pre_call(
        project_root=project_root,
        estimated_vision_tokens=estimated_tokens,
        clip_id=clip_id,
        job_id=options.get("job_id") if isinstance(options, dict) else None,
    )
    if refusal is not None:
        return refusal

    payload: Dict[str, Any] = {
        "success": True,
        "status": "pending_host_analysis",
        "provider": HOST_CHAT_PATHS_PROVIDER,
        "vision_token": vision_token,
        "source_trust": effective_source_trust,
        "frame_count": len(frame_paths_capped),
        "frame_paths": frame_paths_capped,
        "frame_metadata": frame_metadata,
        "clip": {
            "clip_id": clip_id,
            "clip_name": record.get("clip_name"),
            "file_path": file_path,
        },
        "motion_summary": motion_summary,
        "cut_analysis": cut_summary,
        "shot_table": shot_table,
        "prompt": _build_vision_prompt_with_source_trust(
            base_prompt=str(vision.get("prompt") or DEFAULT_VISION_ANALYSIS_PROMPT),
            source_trust=effective_source_trust,
            summary_style=(
                options.get("analysis_summary_style") or options.get("analysisSummaryStyle")
                or vision.get("analysis_summary_style") or vision.get("analysisSummaryStyle")
            ),
            file_path=file_path,
            clip_name=record.get("clip_name"),
        ),
        "schema_reference": VISION_SCHEMA_REFERENCE,
        "commit_action": {
            "tool": "media_analysis",
            "action": "commit_vision",
            "params": commit_params,
        },
        # C3 — Host tool_choice hint. Hosts that respect this can hard-lock the
        # next API turn to media_analysis(action=commit_vision) so the agent
        # can't drift away from the deferred-vision flow. Hosts that don't
        # respect it ignore the field; the deferred-payload flow is unchanged.
        "host_tool_choice_hint": {
            "type": "tool",
            "name": "media_analysis",
            "params_template": {"action": "commit_vision", **commit_params},
            "rationale": (
                "Pending visual analysis on clip {clip}. Reading frame_paths and calling "
                "commit_vision is the only correct next action; skipping it leaves the run "
                "in pending_host_vision_analysis."
            ).format(clip=record.get("clip_id") or record.get("clip_name") or "<clip>"),
        },
        "instructions": (
            "Read every file under frame_paths as a local image using your client's "
            "image-reading capability (Claude Code's Read tool handles JPG/PNG natively). "
            "Produce a single JSON object that matches the structure of `prompt`/`schema` "
            "(no markdown fences, no prose outside JSON). The response MUST include a "
            "`shot_descriptions` entry for every `shot_index` listed in `shot_table` — "
            "each description should be grounded in the frames whose indices appear in "
            "`shot_table[i].frame_indices`, never in unrelated shots. Then call the tool in "
            "`commit_action` with `visual` set to that JSON object — the server will merge it "
            "into the analysis report, rebuild Media Pool clip markers, and publish "
            "vision-dependent metadata to Resolve. Non-vision layers "
            "(technical/loudness/scenes/motion/transcription) are already persisted under "
            "the clip's analysis directory; commit_vision finishes the run."
        ),
    }
    # Phase B — deep depth: each shot_descriptions entry must additionally
    # carry the per-shot field groups. The extra keys flow through
    # commit_vision → canonical blob → subjective_fields rows unchanged.
    if str(options.get("depth") or "").lower() == "deep":
        from src.utils import deep_vision as _deep_vision

        payload["deep_shot_schema"] = _deep_vision.deep_shot_schema()
        payload["deep_schema_reference"] = _deep_vision.DEEP_SHOT_SCHEMA_REFERENCE
        payload["instructions"] += (
            " DEEP PASS: in addition to `description`, every shot_descriptions "
            "entry MUST include the field groups in `deep_shot_schema` (visual, "
            "content, production, editorial, cuttability, confidence), using the "
            "enum values verbatim and 'unknown'/null when frame evidence is thin."
        )
    return payload


def _vision_analysis(record: Dict[str, Any], motion: Dict[str, Any], options: Dict[str, Any], artifacts: Dict[str, Any], capabilities: Dict[str, Any]) -> Dict[str, Any]:
    vision = options.get("vision") or {}
    if not _coerce_bool(vision.get("enabled"), default=False):
        return {"success": True, "status": "skipped", "reason": "vision disabled"}
    provider = vision.get("provider") or capabilities.get("vision", {}).get("provider") or HOST_CHAT_PATHS_PROVIDER
    if provider in HOST_CHAT_VISION_PROVIDERS:
        payload = build_host_chat_paths_payload(record, motion, options, artifacts)
        # Pre-call caps refusal is returned as {success: False, status: "caps_exhausted", ...}
        # with no frame_paths key. Pass it through unchanged so the manifest-level
        # _annotate_clip_vision_failure can surface a CAPS_REFUSAL envelope instead
        # of getting overwritten by the no-frames fallthrough below.
        if not payload.get("success", True):
            return payload
        if not payload.get("frame_paths"):
            return {
                "success": False,
                "status": "skipped",
                "provider": HOST_CHAT_PATHS_PROVIDER,
                "reason": "No sampled analysis frames were available for host-chat vision.",
            }
        if artifacts.get("visual_json"):
            _write_json(artifacts["visual_json"], payload)
        return payload
    if provider not in {"mock", "local_mock"}:
        return {
            "success": False,
            "status": "skipped",
            "provider": provider,
            "reason": f"Unknown vision provider '{provider}'. Set DAVINCI_RESOLVE_MCP_VISION_PROVIDER to '{HOST_CHAT_PATHS_PROVIDER}' or use the 'mock' provider for tests.",
        }
    keyframes = []
    for frame in motion.get("analysis_keyframes", []):
        frame_row = {
            "time_seconds": frame.get("time_seconds"),
            "selection_reason": frame.get("selection_reason"),
            "description": "Local mock vision description for representative frame.",
            "editing_value": "Use as a searchable representative moment.",
            "qc_flags": [],
        }
        for key in ("cut_index", "cut_time_seconds", "boundary_role", "shot_index", "shot_start", "shot_end", "motion_peak", "motion_peak_source_reason"):
            if frame.get(key) not in (None, ""):
                frame_row[key] = frame.get(key)
        keyframes.append(frame_row)
    cut_analysis = motion.get("cut_analysis") if isinstance(motion.get("cut_analysis"), dict) else {}
    payload = {
        "success": True,
        "provider": provider,
        "clip_summary": f"Local mock visual analysis for {record.get('clip_name') or record.get('file_path')}.",
        "editorial_classification": {
            "primary_use": "unknown",
            "select_potential": "medium" if motion.get("overall_motion_level") != "low" else "low",
            "reason": "Derived from local motion/variance evidence only.",
        },
        "content": {
            "locations": [],
            "people_visible": "unknown",
            "actions": [],
            "objects": [],
            "visible_text": [],
            "notable_audio_context": [],
        },
        "shot_and_style": {
            "shot_sizes": [],
            "camera_motion": [motion.get("overall_motion_level", "unknown")],
            "composition_notes": "",
            "lighting_mood": "",
            "color_mood": "",
        },
        "motion": {
            "overall_level": motion.get("overall_motion_level", "unknown"),
            "motion_events": [],
            "quiet_regions": [],
        },
        "cut_understanding": {
            "cut_count": cut_analysis.get("cut_count", 0),
            "likely_edited_sequence": bool(cut_analysis.get("likely_edited_sequence")),
            "flash_frame_candidates": cut_analysis.get("flash_frame_candidates", []),
            "notes": cut_analysis.get("notes", []),
        },
        "analysis_keyframes": keyframes,
        "editing_notes": {
            "best_moments": [],
            "continuity_flags": [],
            "qc_flags": [],
            "search_tags": [slugify(record.get("clip_name"), "clip")],
        },
        "confidence": {
            "visual": "low",
            "motion": "computed",
            "transcript": "unavailable",
        },
    }
    if artifacts.get("visual_json"):
        _write_json(artifacts["visual_json"], payload)
    return payload


def _analysis_fps(record: Dict[str, Any], technical: Dict[str, Any]) -> float:
    raw = record.get("fps") or record.get("frame_rate") or record.get("frameRate")
    if raw not in (None, ""):
        if isinstance(raw, str):
            fraction = _fraction_to_float(raw)
            if fraction:
                return fraction
            match = re.search(r"\d+(?:\.\d+)?", raw)
            if match:
                parsed = _parse_float(match.group(0))
                if parsed:
                    return parsed
        parsed = _parse_float(raw)
        if parsed:
            return parsed
    summary = technical.get("summary") if isinstance(technical.get("summary"), dict) else {}
    for video in summary.get("video") or []:
        parsed = _parse_float(video.get("frame_rate"))
        if parsed:
            return parsed
    return 24.0


def _seconds_to_frame(seconds: Optional[float], fps: float) -> Optional[int]:
    if seconds is None:
        return None
    try:
        return int(round(max(0.0, float(seconds)) * max(float(fps), 1.0)))
    except (TypeError, ValueError):
        return None


def _duration_frames(start_seconds: Optional[float], end_seconds: Optional[float], fps: float, *, fallback: int = 1) -> int:
    if start_seconds is None or end_seconds is None:
        return fallback
    start_frame = _seconds_to_frame(start_seconds, fps)
    end_frame = _seconds_to_frame(end_seconds, fps)
    if start_frame is None or end_frame is None:
        return fallback
    return max(1, end_frame - start_frame)


def _time_seconds_from_text(value: Any) -> Optional[float]:
    if isinstance(value, dict):
        for key in ("time_seconds", "timeSeconds", "start", "start_seconds", "startSeconds"):
            parsed = _parse_float(value.get(key))
            if parsed is not None:
                return parsed
        value = value.get("text") or value.get("note") or value.get("description")
    raw = str(value or "")
    colon = re.search(r"\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})([.,]\d+)?\b", raw)
    if colon:
        hours = int(colon.group(1) or 0)
        minutes = int(colon.group(2))
        seconds = int(colon.group(3))
        fraction = float((colon.group(4) or "0").replace(",", "."))
        return hours * 3600 + minutes * 60 + seconds + fraction
    seconds_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)\b", raw, flags=re.IGNORECASE)
    if seconds_match:
        return _parse_float(seconds_match.group(1))
    return None


def _trim_text(value: Any, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _ranges_overlap(
    start_a: Optional[float],
    end_a: Optional[float],
    start_b: Optional[float],
    end_b: Optional[float],
) -> bool:
    if start_a is None:
        start_a = 0.0
    if start_b is None:
        start_b = 0.0
    if end_a is None:
        end_a = start_a
    if end_b is None:
        end_b = start_b
    return max(start_a, start_b) <= min(end_a, end_b)


def _transcript_words_from_payload(transcript: Dict[str, Any]) -> List[Dict[str, Any]]:
    words = transcript.get("words") if isinstance(transcript.get("words"), list) else []
    if words:
        return [word for word in words if isinstance(word, dict)]
    out: List[Dict[str, Any]] = []
    segments = transcript.get("segments") if isinstance(transcript.get("segments"), list) else []
    for segment in segments:
        if isinstance(segment, dict) and isinstance(segment.get("words"), list):
            out.extend(word for word in segment["words"] if isinstance(word, dict))
    return out


def _transcript_excerpt_for_range(transcript: Dict[str, Any], start: Optional[float], end: Optional[float]) -> str:
    words = _transcript_words_from_payload(transcript)
    if words:
        selected_words = []
        for word in words:
            if not isinstance(word, dict):
                continue
            word_start = _parse_float(word.get("start"))
            word_end = _parse_float(word.get("end"))
            if _ranges_overlap(start, end, word_start, word_end):
                selected_words.append(str(word.get("word") or "").strip())
        if selected_words:
            return _trim_text(" ".join(word for word in selected_words if word), 280)

    segments = transcript.get("segments") if isinstance(transcript.get("segments"), list) else []
    selected_segments = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        seg_start = _parse_float(segment.get("start"))
        seg_end = _parse_float(segment.get("end"))
        if _ranges_overlap(start, end, seg_start, seg_end):
            selected_segments.append(str(segment.get("text") or "").strip())
    return _trim_text(" ".join(text for text in selected_segments if text), 280)


_VISUAL_DESCRIPTION_UNAVAILABLE = "Visual description unavailable from this analysis pass."


def _shot_description_entry(
    vision: Dict[str, Any], shot_index: Optional[int], start: Optional[float], end: Optional[float]
) -> Optional[Dict[str, Any]]:
    """Return the matching shot_descriptions entry by index, or by time-range overlap."""
    rows = vision.get("shot_descriptions") if isinstance(vision.get("shot_descriptions"), list) else []
    if not rows:
        return None
    target_index = None
    try:
        if shot_index is not None:
            target_index = int(shot_index)
    except (TypeError, ValueError):
        target_index = None
    if target_index is not None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                if int(row.get("shot_index")) == target_index:
                    return row
            except (TypeError, ValueError):
                continue
    if start is None or end is None:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        r_start = _parse_float(row.get("time_seconds_start"))
        r_end = _parse_float(row.get("time_seconds_end"))
        if r_start is None or r_end is None:
            continue
        if abs(r_start - float(start)) <= 0.05 and abs(r_end - float(end)) <= 0.05:
            return row
    return None


def _keyframe_description_in_range(
    vision: Dict[str, Any], start: Optional[float], end: Optional[float]
) -> Optional[str]:
    """Return the first analysis_keyframe description whose time falls inside [start, end]."""
    if start is None or end is None:
        return None
    keyframes = vision.get("analysis_keyframes") if isinstance(vision.get("analysis_keyframes"), list) else []
    for keyframe in keyframes:
        if not isinstance(keyframe, dict):
            continue
        description = keyframe.get("description") or keyframe.get("visual_description")
        if not description:
            continue
        frame_time = _parse_float(keyframe.get("time_seconds"))
        if frame_time is None:
            continue
        if float(start) <= frame_time <= float(end):
            return description
    return None


def _visual_description_for_shot(
    vision: Dict[str, Any],
    shot_index: Optional[int],
    start: Optional[float],
    end: Optional[float],
) -> str:
    """Layered shot-description lookup.

    1. Exact match in vision.shot_descriptions (by shot_index, then by [start,end]).
    2. analysis_keyframe whose time falls inside [start, end].
    3. clip_summary as a clearly-marked fallback.
    4. Sentinel placeholder if nothing usable exists.
    """
    entry = _shot_description_entry(vision, shot_index, start, end)
    if entry:
        description = entry.get("description") or entry.get("visual_description")
        if description:
            return _trim_text(description, 360)
    in_range = _keyframe_description_in_range(vision, start, end)
    if in_range:
        return _trim_text(in_range, 360)
    summary = vision.get("clip_summary")
    if summary:
        return _trim_text(f"[shot description unavailable — falling back to clip summary] {summary}", 360)
    return _VISUAL_DESCRIPTION_UNAVAILABLE


def _visual_description_for_time(vision: Dict[str, Any], start: Optional[float], end: Optional[float]) -> str:
    """Used by point-in-time markers (best_moments, qc_warnings).

    Picks the nearest analysis_keyframe whose time is within roughly the marker's
    own range. Outside that window, falls back to clip_summary or the sentinel —
    never copies a far-away keyframe's description.
    """
    keyframes = vision.get("analysis_keyframes") if isinstance(vision.get("analysis_keyframes"), list) else []
    midpoint = None
    if start is not None and end is not None:
        midpoint = (float(start) + float(end)) / 2.0
    elif start is not None:
        midpoint = float(start)
    if midpoint is not None:
        in_range = _keyframe_description_in_range(vision, start, end)
        if in_range:
            return _trim_text(in_range, 360)
        best = None
        best_distance = None
        for keyframe in keyframes:
            if not isinstance(keyframe, dict):
                continue
            description = keyframe.get("description") or keyframe.get("visual_description")
            if not description:
                continue
            frame_time = _parse_float(keyframe.get("time_seconds"))
            if frame_time is None:
                continue
            distance = abs(frame_time - midpoint)
            if distance > 2.0:
                continue
            if best_distance is None or distance < best_distance:
                best = description
                best_distance = distance
        if best:
            return _trim_text(best, 360)
    if vision.get("clip_summary"):
        return _trim_text(vision.get("clip_summary"), 360)
    return _VISUAL_DESCRIPTION_UNAVAILABLE


def _shot_ranges_from_scenes(
    duration: Optional[float],
    scene_items: List[Dict[str, Any]],
    *,
    min_duration_seconds: float = 0.75,
) -> List[Dict[str, Any]]:
    scene_times = []
    for item in scene_items:
        if not isinstance(item, dict):
            continue
        t = _parse_float(item.get("time_seconds"))
        if t is None or t <= 0:
            continue
        if duration is not None and t >= duration:
            continue
        scene_times.append(t)
    scene_times = sorted(set(round(t, 3) for t in scene_times))

    if duration is not None and duration > 0:
        boundaries = [0.0]
        for t in scene_times:
            if t - boundaries[-1] >= min_duration_seconds:
                boundaries.append(t)
        if duration - boundaries[-1] >= 0.05:
            boundaries.append(float(duration))
        if len(boundaries) < 2:
            boundaries = [0.0, float(duration)]
        return [
            {"index": index + 1, "start": boundaries[index], "end": boundaries[index + 1]}
            for index in range(len(boundaries) - 1)
        ]

    if scene_times:
        starts = [0.0] + scene_times
        return [
            {"index": index + 1, "start": start, "end": starts[index + 1] if index + 1 < len(starts) else None}
            for index, start in enumerate(starts)
        ]
    return [{"index": 1, "start": 0.0, "end": duration}]


def _marker_sound_note(transcript: Dict[str, Any], readthrough: Dict[str, Any], start: Optional[float], end: Optional[float]) -> Tuple[str, str]:
    transcript_text = _transcript_excerpt_for_range(transcript, start, end)
    if transcript_text:
        return f"Transcript: {transcript_text}", transcript_text
    silence_items = ((readthrough.get("silence") or {}).get("items") or []) if isinstance(readthrough.get("silence"), dict) else []
    for item in silence_items:
        if isinstance(item, dict) and _ranges_overlap(start, end, _parse_float(item.get("start")), _parse_float(item.get("end"))):
            return "Sound: detected silence or very low-level audio in this range.", ""
    return "Sound: no transcript excerpt available for this range.", ""


def _build_marker_entry(
    *,
    marker_id: str,
    marker_type: str,
    color: str,
    name: str,
    start: Optional[float],
    end: Optional[float],
    fps: float,
    visual_description: str,
    sound_note: str,
    transcript_text: str = "",
    source: str,
    confidence: str = "computed",
    subtype: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {
        "id": marker_id,
        "type": marker_type,
        "subtype": subtype,
        "color": color,
        "name": name,
        "start_seconds": start,
        "end_seconds": end,
        "start_frame": _seconds_to_frame(start, fps),
        "duration_frames": _duration_frames(start, end, fps),
        "visual_description": visual_description,
        "sound_note": sound_note,
        "transcript_text": transcript_text,
        "source": source,
        "confidence": confidence,
        "write_to_resolve": True,
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}


def _build_clip_marker_plan(
    record: Dict[str, Any],
    technical: Dict[str, Any],
    readthrough: Dict[str, Any],
    motion: Dict[str, Any],
    transcript: Dict[str, Any],
    vision: Dict[str, Any],
    *,
    options: Dict[str, Any],
    analysis_signature: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    fps = _analysis_fps(record, technical)
    duration = _media_duration_seconds(record, technical)
    marker_options = options.get("marker_plan") if isinstance(options.get("marker_plan"), dict) else {}
    min_shot_duration = _parse_float(marker_options.get("min_shot_duration_seconds"))
    if min_shot_duration is None:
        min_shot_duration = 0.75
    color_scheme = {
        **MARKER_PLAN_DEFAULT_COLORS,
        **({
            str(key): str(value)
            for key, value in marker_options.get("colors", {}).items()
            if value not in (None, "")
        } if isinstance(marker_options.get("colors"), dict) else {}),
    }
    markers: List[Dict[str, Any]] = []
    untimed_notes: List[Dict[str, Any]] = []
    scene_items = ((readthrough.get("scenes") or {}).get("items") or []) if isinstance(readthrough.get("scenes"), dict) else []
    cut_analysis = readthrough.get("cut_analysis") if isinstance(readthrough.get("cut_analysis"), dict) else {}
    shot_ranges = cut_analysis.get("shot_ranges") if isinstance(cut_analysis.get("shot_ranges"), list) else None
    if not shot_ranges:
        shot_ranges = _shot_ranges_from_scenes(duration, scene_items, min_duration_seconds=float(min_shot_duration))
    for shot in shot_ranges:
        start = _parse_float(shot.get("start"))
        end = _parse_float(shot.get("end"))
        try:
            shot_index = int(shot.get("index"))
        except (TypeError, ValueError):
            shot_index = None
        sound_note, transcript_text = _marker_sound_note(transcript, readthrough, start, end)
        markers.append(_build_marker_entry(
            marker_id=f"shot-{int(shot['index']):03d}",
            marker_type="shot",
            color=color_scheme["shot"],
            name=f"Shot {int(shot['index']):03d}",
            start=start,
            end=end,
            fps=fps,
            visual_description=_visual_description_for_shot(vision, shot_index, start, end),
            sound_note=sound_note,
            transcript_text=transcript_text,
            source="scene_detection",
        ))

    flash_candidates = cut_analysis.get("flash_frame_candidates") if isinstance(cut_analysis.get("flash_frame_candidates"), list) else []
    for index, item in enumerate(flash_candidates, 1):
        if not isinstance(item, dict):
            continue
        start = _parse_float(item.get("start"))
        end = _parse_float(item.get("end"))
        sound_note, transcript_text = _marker_sound_note(transcript, readthrough, start, end)
        markers.append(_build_marker_entry(
            marker_id=f"flash-frame-candidate-{index:03d}",
            marker_type="qc_warning",
            subtype="flash_frame_candidate",
            color=color_scheme["qc_warning"],
            name="QC: Flash Frame Candidate",
            start=start,
            end=end,
            fps=fps,
            visual_description=(
                "FFmpeg detected a very short scene-bounded range. Review boundary frames to distinguish "
                "a flash frame, title/black insertion, or deliberate rapid cut from a high-motion moment."
            ),
            sound_note=sound_note,
            transcript_text=transcript_text,
            source="cut_boundary_analysis",
            confidence="computed_needs_visual_confirmation",
        ))

    black_items = ((readthrough.get("black_frames") or {}).get("items") or []) if isinstance(readthrough.get("black_frames"), dict) else []
    for index, item in enumerate(black_items, 1):
        if not isinstance(item, dict):
            continue
        start = _parse_float(item.get("start"))
        end = _parse_float(item.get("end"))
        sound_note, transcript_text = _marker_sound_note(transcript, readthrough, start, end)
        markers.append(_build_marker_entry(
            marker_id=f"black-or-title-{index:03d}",
            marker_type="qc_warning",
            subtype="black_or_title",
            color=color_scheme["black_or_title"],
            name="QC: Black/Very Dark Range",
            start=start,
            end=end,
            fps=fps,
            visual_description=(
                "Detected black or very dark picture. Review as true black, scanned tape black, "
                "dropout, or title fade before using as an edit point."
            ),
            sound_note=sound_note,
            transcript_text=transcript_text,
            source="blackdetect",
            confidence="computed",
        ))

    editing_notes = vision.get("editing_notes") if isinstance(vision.get("editing_notes"), dict) else {}
    for index, item in enumerate(editing_notes.get("best_moments") or [], 1):
        start = _time_seconds_from_text(item)
        if start is None:
            untimed_notes.append({"type": "best_moment", "note": _trim_text(item), "reason": "missing_time"})
            continue
        end = min(start + 1.0, duration) if duration else start + 1.0
        sound_note, transcript_text = _marker_sound_note(transcript, readthrough, start, end)
        markers.append(_build_marker_entry(
            marker_id=f"best-moment-{index:03d}",
            marker_type="best_moment",
            color=color_scheme["best_moment"],
            name="Best Moment",
            start=start,
            end=end,
            fps=fps,
            visual_description=_visual_description_for_time(vision, start, end),
            sound_note=sound_note or _trim_text(item),
            transcript_text=transcript_text,
            source="visual_editing_notes",
            confidence="model_suggested",
        ))

    qc_sources = list(technical.get("summary", {}).get("warnings") or []) + list(editing_notes.get("qc_flags") or [])
    for index, item in enumerate(qc_sources, 1):
        start = _time_seconds_from_text(item)
        if start is None:
            untimed_notes.append({"type": "qc_warning", "note": _trim_text(item), "reason": "missing_time"})
            continue
        end = min(start + 1.0, duration) if duration else start + 1.0
        sound_note, transcript_text = _marker_sound_note(transcript, readthrough, start, end)
        markers.append(_build_marker_entry(
            marker_id=f"qc-warning-{index:03d}",
            marker_type="qc_warning",
            color=color_scheme["qc_warning"],
            name="QC Warning",
            start=start,
            end=end,
            fps=fps,
            visual_description=_visual_description_for_time(vision, start, end),
            sound_note=sound_note,
            transcript_text=transcript_text,
            source="analysis_warning",
            confidence="model_suggested",
        ))

    markers.sort(key=lambda row: (float(row.get("start_seconds") or 0.0), row.get("type") or "", row.get("id") or ""))
    words = _transcript_words_from_payload(transcript)
    return {
        "success": True,
        "schema": "davinci_resolve_mcp.clip_analysis_markers.v1",
        "analysis_version": ANALYSIS_VERSION,
        "analysis_signature": analysis_signature or {},
        "clip": record,
        "fps": fps,
        "duration_seconds": duration,
        "color_scheme": color_scheme,
        "write_to_resolve_default": True,
        "resolve_marker_writeback": {
            "optional": True,
            "enabled": True,
            "default_behavior": (
                "Written during executed Resolve-target analysis and metadata publish unless "
                "timed_markers=no or dry_run=true."
            ),
            "write_action": "publish_clip_metadata",
            "disable_flags": {"timed_markers": "no", "dry_run": True, "publish_metadata": False},
        },
        "transcript_index": {
            "available": bool(transcript.get("text") or transcript.get("segments")),
            "segments": len(transcript.get("segments") or []),
            "word_timestamps": bool(words),
            "words": len(words),
        },
        "timeline_occurrences": record.get("timeline_occurrences") or [],
        "cut_analysis": {
            "cut_count": cut_analysis.get("cut_count", 0),
            "likely_edited_sequence": bool(cut_analysis.get("likely_edited_sequence")),
            "flash_frame_candidates": len(flash_candidates),
        },
        "marker_count": len(markers),
        "markers": markers,
        "untimed_notes": untimed_notes,
        "motion_summary": {
            "overall_motion_level": motion.get("overall_motion_level"),
            "average_frame_delta": motion.get("average_frame_delta"),
            "max_frame_delta": motion.get("max_frame_delta"),
        },
    }


def _synthesize_analysis(
    record: Dict[str, Any],
    technical: Dict[str, Any],
    readthrough: Dict[str, Any],
    motion: Dict[str, Any],
    transcript: Dict[str, Any],
    vision: Dict[str, Any],
    *,
    depth: str = DEFAULT_DEPTH,
    options: Optional[Dict[str, Any]] = None,
    frame_count: int = 0,
    analysis_signature: Optional[Dict[str, Any]] = None,
    marker_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    warnings = []
    if technical.get("summary", {}).get("warnings"):
        warnings.extend(technical["summary"]["warnings"])
    for key in ("loudness", "scenes", "black_frames", "silence", "interlace"):
        item = readthrough.get(key)
        if isinstance(item, dict) and item.get("success") is False:
            warnings.append(f"{key} analysis did not complete")
    summary_parts = []
    if record.get("clip_name"):
        summary_parts.append(str(record["clip_name"]))
    duration = _media_duration_seconds(record, technical)
    if duration is not None:
        summary_parts.append(f"{duration:.1f}s")
    if motion.get("overall_motion_level"):
        summary_parts.append(f"{motion['overall_motion_level']} motion")
    return {
        "success": True,
        "analysis_version": ANALYSIS_VERSION,
        "analysis_signature": analysis_signature or analysis_request_signature(record, depth, options or {}, frame_count),
        "analysis_profile": {
            "depth": depth,
            "analysis_keyframe_budget": int(frame_count or 0),
            "transcription_enabled": _coerce_bool(((options or {}).get("transcription") or {}).get("enabled"), default=DEFAULT_TRANSCRIPTION_ENABLED),
            "vision_enabled": _coerce_bool(((options or {}).get("vision") or {}).get("enabled"), default=False),
            "source_trust": _resolve_source_trust(options),
        },
        "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_file": record.get("file_path"),
        "clip": record,
        "summary": ", ".join(summary_parts) if summary_parts else "Analyzed media clip",
        "technical_warnings": warnings,
        "technical": technical.get("summary", {}),
        "readthrough": readthrough,
        "cut_analysis": readthrough.get("cut_analysis") if isinstance(readthrough.get("cut_analysis"), dict) else {},
        "motion": motion,
        "transcription": transcript,
        "visual": vision,
        "analysis_keyframes": motion.get("analysis_keyframes", []),
        "clip_analysis_markers": marker_plan or {},
    }


async def _maybe_run_vision_analysis(
    record: Dict[str, Any],
    motion: Dict[str, Any],
    options: Dict[str, Any],
    artifacts: Dict[str, Any],
    capabilities: Dict[str, Any],
    vision_runner: Any = None,
) -> Dict[str, Any]:
    if vision_runner is not None and vision_uses_chat_context(options, capabilities):
        payload = vision_runner(record, motion, options, artifacts, capabilities)
        if inspect.isawaitable(payload):
            payload = await payload
        if isinstance(payload, dict):
            if artifacts.get("visual_json"):
                _write_json(artifacts["visual_json"], payload)
            return payload
    return _vision_analysis(record, motion, options, artifacts, capabilities)


def _clip_is_reused(clip: Any) -> bool:
    """A clip is satisfied by an existing report and runs no fresh analysis."""
    return bool(
        isinstance(clip, dict)
        and clip.get("skip_execution")
        and (clip.get("existing_report") or {}).get("path")
    )


def executing_clips(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Clips in ``plan`` that still require fresh analysis (not pure reuse)."""
    return [
        clip
        for clip in plan.get("clips", [])
        if isinstance(clip, dict) and not _clip_is_reused(clip)
    ]


def plan_requires_capabilities(plan: Dict[str, Any]) -> bool:
    """True when at least one clip needs fresh analysis.

    ``build_plan`` records ``capability_gaps`` from the *requested* options
    before the per-clip reuse decision runs. When every clip is satisfied by an
    existing reusable report, execution only re-keys/imports those reports into
    the current root and performs no fresh transcription/vision/ffprobe — so the
    missing-capability gate must not fire. Callers gate with
    ``plan.get("capability_gaps") and plan_requires_capabilities(plan)``.
    """
    return bool(executing_clips(plan))


async def execute_plan_async(
    plan: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
    capabilities: Optional[Dict[str, Any]] = None,
    vision_runner: Any = None,
) -> Dict[str, Any]:
    params = params or {}
    caps = capabilities or detect_capabilities()
    session_only = _coerce_bool(params.get("session_only"), default=False)
    keep_artifacts = _coerce_bool(params.get("keep_artifacts"), default=False)
    if not plan.get("success"):
        return plan
    blocked = [
        clip for clip in plan.get("clips", [])
        if isinstance(clip, dict) and clip.get("reuse_blocked")
    ]
    if blocked:
        return {
            "success": False,
            "status": "reuse_blocked",
            "error": (
                "Analysis provenance exists for one or more Resolve clips, but no reusable "
                "report could be validated. Pass force_refresh=true to intentionally reanalyze."
            ),
            "blocked_clip_count": len(blocked),
            "reuse_summary": plan.get("reuse_summary"),
            "clips": [
                {
                    "record": clip.get("record"),
                    "cache_status": clip.get("cache_status"),
                    "why_not_reused": clip.get("why_not_reused"),
                    "reuse_block_reason": clip.get("reuse_block_reason"),
                    "existing_report": clip.get("existing_report"),
                    "analysis_provenance": clip.get("analysis_provenance"),
                }
                for clip in blocked
            ],
        }
    fresh_clips = executing_clips(plan)
    if plan.get("capability_gaps") and fresh_clips:
        return {
            "success": False,
            "error": "Cannot execute analysis with missing required capabilities",
            "capability_gaps": plan.get("capability_gaps"),
            "install_guidance": plan.get("install_guidance"),
        }
    output_root = plan["output_root"]["project_root"]
    os.makedirs(output_root, exist_ok=True)
    options = {
        "transcription": params.get("transcription") or {},
        "vision": params.get("vision") or {},
        "marker_plan": params.get("marker_plan") or params.get("markerPlan") or {},
        # Thread the batch-runner's job_id (if any) into per-clip options so
        # _record_caps_usage + _check_caps_pre_call can populate the JOB scope.
        "job_id": params.get("job_id"),
        # Same for project_root — caps recording needs it to address the per-
        # project usage DB; falling back to the plan's output_root is fine.
        "project_root": params.get("project_root") or output_root,
        # Phase B — depth threads into the vision payload builder so deep runs
        # carry the per-shot field-group schema.
        "depth": plan.get("depth", DEFAULT_DEPTH),
    }
    keep_frame_artifacts_for_vision = vision_uses_chat_context(options, caps)
    depth = plan.get("depth", DEFAULT_DEPTH)
    manifest = {
        "success": True,
        "analysis_version": ANALYSIS_VERSION,
        "target": plan.get("target"),
        "depth": depth,
        "session_only": session_only,
        "persistent": not session_only,
        "keep_artifacts": keep_artifacts,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project_root": output_root,
        "reuse_summary": plan.get("reuse_summary"),
        "clips": [],
    }
    _write_json(os.path.join(output_root, "capabilities.json"), caps)

    # Phase B — deep depth is opt-in with an explicit cost estimate first.
    # The per-shot field-group pass multiplies vision spend, so the first call
    # returns the estimate; re-call with confirm_deep=true to run. Caps still
    # apply downstream — confirmation does not bypass budgets.
    if (
        depth == "deep"
        and vision_uses_chat_context(options, caps)
        and not _coerce_bool(params.get("confirm_deep") or params.get("confirmDeep"), default=False)
    ):
        estimated_frames = sum(int(c.get("analysis_keyframe_budget") or 0) for c in fresh_clips)
        return {
            "success": True,
            "status": "confirmation_required",
            "reason": "deep_depth_cost_estimate",
            "estimate": {
                "clip_count": len(fresh_clips),
                "estimated_frames": estimated_frames,
                "estimated_vision_tokens": estimated_frames * AVG_VISION_TOKENS_PER_FRAME,
                "tokens_per_frame_assumption": AVG_VISION_TOKENS_PER_FRAME,
            },
            "note": (
                "Deep analysis fills per-shot Visual/Content/Editorial field groups "
                "and costs vision tokens accordingly. Re-call the same analyze action "
                "with confirm_deep=true to proceed, or drop depth to 'standard'."
            ),
        }

    for clip_plan in plan.get("clips", []):
        record = clip_plan["record"]
        artifacts = clip_plan["artifacts"]
        source = record.get("file_path")
        existing_report = clip_plan.get("existing_report") or {}
        clip_result = {
            "record": record,
            "artifacts": artifacts,
            "success": False,
        }
        if clip_plan.get("skip_execution") and existing_report.get("path"):
            # DB-canonical (C1): a reused report — especially one matched from
            # ANOTHER project's root via the registry — must still land rows
            # and a lockstep export in THIS root, keyed to THIS project's clip
            # identity. Without this, media_ref lookups against the current
            # media pool (edit_engine planners, panel readers) find nothing
            # even though the manifest reports success.
            local_analysis_json = existing_report["path"]
            try:
                with open(existing_report["path"], "r", encoding="utf-8") as handle:
                    reused_report = json.load(handle)
            except (OSError, json.JSONDecodeError):
                reused_report = None
            if isinstance(reused_report, dict):
                reused_report = dict(reused_report)
                clip_block = dict(reused_report.get("clip") or {})
                for key in ("clip_id", "clip_name", "media_id", "bin_path"):
                    if record.get(key):
                        clip_block[key] = record[key]
                if record.get("file_path"):
                    clip_block["file_path"] = record["file_path"]
                reused_report["clip"] = clip_block
                db_ingest = _ingest_report_into_db(
                    output_root,
                    reused_report,
                    os.path.dirname(artifacts["analysis_json"]),
                )
                if not db_ingest.get("success"):
                    clip_result["db_ingest_error"] = db_ingest.get("error")
                if os.path.normpath(artifacts["analysis_json"]) != os.path.normpath(existing_report["path"]):
                    _write_json(artifacts["analysis_json"], reused_report)
                local_analysis_json = artifacts["analysis_json"]
            clip_result.update({
                "success": True,
                "reused": True,
                "analysis_json": local_analysis_json,
                "reuse_reason": clip_plan.get("reuse_reason"),
                "cache_status": clip_plan.get("cache_status"),
                "cache_warnings": existing_report.get("cache_warnings", []),
                "reuse_source": clip_plan.get("reuse_source"),
                "reused_from": clip_plan.get("reused_from") or existing_report["path"],
            })
            manifest["clips"].append(clip_result)
            continue
        if not source or not os.path.isfile(source):
            clip_result["error"] = f"Source media not found: {source}"
            manifest["clips"].append(clip_result)
            continue

        technical = _ffprobe(source)
        if not technical.get("success"):
            clip_result["error"] = technical.get("error")
            manifest["clips"].append(clip_result)
            continue
        _write_json(artifacts["technical_json"], technical)

        readthrough: Dict[str, Any] = {"success": True, "status": "skipped", "reason": "quick analysis depth"}
        motion: Dict[str, Any] = {"success": True, "status": "skipped", "analysis_keyframes": []}
        if depth in {"standard", "deep", "custom"}:
            readthrough = _readthrough_analysis(source)
            duration = _media_duration_seconds(record, technical)
            fps = _analysis_fps(record, technical)
            readthrough["cut_analysis"] = _cut_boundary_analysis(
                duration,
                (readthrough.get("scenes") or {}).get("items", []),
                fps,
            )
            motion = _motion_and_keyframes(
                source,
                duration,
                (readthrough.get("scenes") or {}).get("items", []),
                artifacts,
                int(clip_plan.get("analysis_keyframe_budget") or 0),
                fps=fps,
                cut_analysis=readthrough.get("cut_analysis"),
                write_frames=keep_frame_artifacts_for_vision or not _coerce_bool(params.get("cleanup_frames"), default=False),
                sampling=clip_plan.get("sampling"),
            )
            if artifacts.get("motion_json"):
                _write_json(artifacts["motion_json"], motion)

        transcript = _transcribe(source, artifacts, options, caps)
        vision = await _maybe_run_vision_analysis(record, motion, options, artifacts, caps, vision_runner)
        vision_pending = vision_is_pending_host_analysis(vision)
        vision_failed = (
            vision_requested(options)
            and not vision_pending
            and not visual_analysis_completed(vision)
        )
        frame_count = int(clip_plan.get("analysis_keyframe_budget") or 0)
        marker_plan = _build_clip_marker_plan(
            record,
            technical,
            readthrough,
            motion,
            transcript,
            vision,
            options=options,
            analysis_signature=clip_plan.get("analysis_signature"),
        )
        if vision_pending:
            marker_plan["vision_status"] = "pending_host_analysis"
        if artifacts.get("marker_plan_json"):
            marker_plan["path"] = artifacts["marker_plan_json"]
            _write_json(artifacts["marker_plan_json"], marker_plan)
        analysis = _synthesize_analysis(
            record,
            technical,
            readthrough,
            motion,
            transcript,
            vision,
            depth=depth,
            options=options,
            frame_count=frame_count,
            analysis_signature=clip_plan.get("analysis_signature"),
            marker_plan=marker_plan,
        )
        if vision_pending:
            analysis["vision_status"] = "pending_host_analysis"
            analysis["vision_token"] = vision.get("vision_token")
        # C1 — DB rows first (canonical), then the derived JSON export. The DB
        # lives under output_root (same root as clips/), not the caps root.
        db_ingest = _ingest_report_into_db(
            output_root,
            analysis,
            os.path.dirname(artifacts["analysis_json"]),
        )
        if not db_ingest.get("success"):
            clip_result["db_ingest_error"] = db_ingest.get("error")
        _write_json(artifacts["analysis_json"], analysis)
        cleanup_frames_requested = _coerce_bool(params.get("cleanup_frames"), default=False)
        if cleanup_frames_requested and not vision_pending and artifacts.get("frames_dir"):
            shutil.rmtree(artifacts["frames_dir"], ignore_errors=True)
        clip_result.update({
            "success": True,
            "analysis_json": artifacts["analysis_json"],
            "marker_plan_json": artifacts.get("marker_plan_json"),
            "marker_count": marker_plan.get("marker_count"),
        })
        if vision_pending:
            clip_result.update({
                "vision_status": "pending_host_analysis",
                "vision_token": vision.get("vision_token"),
                "visual": vision,
            })
            manifest["vision_pending"] = True
        elif vision_failed:
            _annotate_clip_vision_failure(clip_result, vision)
        manifest["clips"].append(clip_result)

    manifest["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest["clip_count"] = len(manifest["clips"])
    manifest["successful_clip_count"] = sum(1 for row in manifest["clips"] if row.get("success"))
    manifest["failed_clip_count"] = manifest["clip_count"] - manifest["successful_clip_count"]
    manifest["vision_pending_clip_count"] = sum(
        1 for row in manifest["clips"] if row.get("vision_status") == "pending_host_analysis"
    )
    manifest["vision_pending"] = bool(manifest["vision_pending_clip_count"])
    manifest["success"] = manifest["failed_clip_count"] == 0
    # D3 — partial-success preservation. When some clips succeeded and others
    # failed, surface explicit completed/failed clip-id lists so callers can
    # retry only the failed subset instead of redoing completed work.
    _annotate_partial_success(manifest)
    _annotate_manifest_caps_refusal(manifest)
    if manifest["vision_pending"]:
        manifest["pending_action"] = {
            "tool": "media_analysis",
            "action": "commit_vision",
            "note": (
                "Host chat must read each clip's frame_paths, produce visual analysis "
                "JSON, and call commit_vision with the result. Until then, vision-derived "
                "metadata (Description, Keywords, slate fields) and vision-derived clip "
                "markers (best_moments, visual qc_flags) are deferred."
            ),
        }

    if (
        not session_only
        and manifest["successful_clip_count"]
        and _coerce_bool(params.get("auto_build_index"), default=True)
    ):
        manifest["index"] = build_analysis_index(output_root)

    if not session_only and manifest["successful_clip_count"]:
        report_paths = [
            row.get("analysis_json")
            for row in manifest["clips"]
            if row.get("success") and row.get("analysis_json") and os.path.isfile(str(row.get("analysis_json")))
        ]
        if report_paths:
            manifest["analysis_registry"] = update_analysis_registry(output_root, report_paths=report_paths)

    # V2 memory + heartbeat layer (per V2 shot schema spec §9).
    # Heartbeat tracks current project state for session-start awareness.
    # Bin summary is the machine's "first impression" briefing of the bin.
    if not session_only and manifest["successful_clip_count"]:
        try:
            analysis_memory.ensure_memory_structure(output_root)
            analysis_memory.ensure_soul_structure(os.path.dirname(output_root))
            pending_clips = [
                {"clip_id": (row.get("record") or {}).get("clip_id"), "reason": "vision_pending"}
                for row in manifest["clips"]
                if row.get("vision_status") == "pending_host_analysis"
            ]
            failed_clips = [
                {"clip_id": (row.get("record") or {}).get("clip_id"), "error": row.get("error")}
                for row in manifest["clips"]
                if not row.get("success") and row.get("vision_status") != "pending_host_analysis"
            ]
            analysis_memory.update_heartbeat(
                output_root,
                last_run={
                    "completed_at": manifest.get("completed_at"),
                    "depth": manifest.get("depth"),
                    "analysis_version": manifest.get("analysis_version"),
                    "schema_version": "2.0",
                },
                clip_counts={
                    "total": manifest["clip_count"],
                    "analyzed": manifest["successful_clip_count"],
                    "failed": manifest["failed_clip_count"],
                    "vision_pending": manifest["vision_pending_clip_count"],
                },
                pending=pending_clips,
                recent_failures=failed_clips,
            )
            # Regenerate bin summary only when vision has actually committed
            # (otherwise per-clip summaries don't exist yet).
            if not manifest.get("vision_pending"):
                analysis_memory.regenerate_bin_summary_from_manifest(
                    output_root, manifest, project_name=manifest.get("project_name"),
                )
        except Exception as exc:  # defensive: memory layer must never break analysis
            manifest.setdefault("memory_layer_warnings", []).append(
                f"{type(exc).__name__}: {exc}"
            )

    _write_json(os.path.join(output_root, "manifest.json"), manifest)

    if session_only:
        reports = []
        for row in manifest["clips"]:
            report_path = row.get("analysis_json")
            if report_path and os.path.isfile(report_path):
                try:
                    reports.append(_read_json(report_path))
                except (OSError, json.JSONDecodeError):
                    continue
        manifest["reports"] = reports
        manifest["project_summary"] = summarize_reports(output_root)
        manifest["artifacts_cleaned_up"] = False
        if not keep_artifacts:
            cleanup_root = output_root
            session_temp_base = params.get("_session_temp_base_root")
            if session_temp_base:
                candidate = normalize_path(session_temp_base)
                if (
                    os.path.basename(candidate).startswith("davinci-resolve-mcp-analysis-session-")
                    and _is_relative_to(output_root, candidate)
                ):
                    cleanup_root = candidate
            shutil.rmtree(cleanup_root, ignore_errors=True)
            manifest["artifacts_cleaned_up"] = True
            manifest["artifact_cleanup_root"] = cleanup_root

    return manifest


def execute_plan(plan: Dict[str, Any], params: Optional[Dict[str, Any]] = None, capabilities: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(execute_plan_async(plan, params=params, capabilities=capabilities))

    # A loop is already running in this thread (e.g. invoked from an async MCP handler).
    # Run the coroutine in a worker thread with its own loop so we can block-wait here.
    result: Dict[str, Any] = {}
    error: Dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(
                execute_plan_async(plan, params=params, capabilities=capabilities)
            )
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller thread
            error["exc"] = exc

    worker = threading.Thread(target=_runner, name="execute_plan_worker", daemon=True)
    worker.start()
    worker.join()
    if "exc" in error:
        raise error["exc"]
    return result["value"]


def _walk_set(container: Any, path_parts: List[str], value: Any) -> bool:
    """Set value at a dotted path inside a nested dict, creating intermediate dicts as needed.

    Returns True if the leaf node was modified, False if container is not navigable.
    """
    if not path_parts:
        return False
    cursor = container
    for part in path_parts[:-1]:
        if not isinstance(cursor, dict):
            return False
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[part] = nxt
        cursor = nxt
    if not isinstance(cursor, dict):
        return False
    cursor[path_parts[-1]] = value
    return True


def _walk_get(container: Any, path_parts: List[str]) -> Tuple[bool, Any]:
    """Return (found, value) for a dotted path inside a nested dict."""
    cursor = container
    for part in path_parts:
        if not isinstance(cursor, dict) or part not in cursor:
            return False, None
        cursor = cursor[part]
    return True, cursor


def _find_shot_entry(shot_descriptions: List[Dict[str, Any]], entity_uuid: str) -> Optional[Dict[str, Any]]:
    """Locate a shot in shot_descriptions by shot_uuid or shot_index match."""
    if not isinstance(shot_descriptions, list):
        return None
    target = str(entity_uuid)
    # First pass: match shot_uuid
    for entry in shot_descriptions:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("shot_uuid") or "") == target:
            return entry
    # Second pass: match shot_index (V1/sidecar identifier)
    try:
        target_int = int(target)
    except (TypeError, ValueError):
        target_int = None
    if target_int is not None:
        for entry in shot_descriptions:
            if not isinstance(entry, dict):
                continue
            entry_idx = entry.get("shot_index")
            if entry_idx is None:
                continue
            try:
                if int(entry_idx) == target_int:
                    return entry
            except (TypeError, ValueError):
                continue
    return None


def preserve_human_corrections(
    clip_dir_path: str,
    normalized_visual: Dict[str, Any],
    *,
    clip_id: Optional[str] = None,
) -> Dict[str, Any]:
    """V2 contract: read corrections.json sidecar and re-apply human-edited fields.

    Called from commit_visual_analysis between normalization and persistence so
    that re-analyzing a clip never silently overwrites editor corrections.

    Returns a metrics dict:
      {preserved_count, applied: [{entity_type, entity_uuid, field_path}],
       skipped: [{key, reason}], changelog_added}
    """
    corrections_path = os.path.join(clip_dir_path, "corrections.json")
    metrics: Dict[str, Any] = {
        "preserved_count": 0,
        "applied": [],
        "skipped": [],
        "changelog_added": 0,
        "corrections_path": corrections_path,
    }
    if not os.path.isfile(corrections_path):
        return metrics

    try:
        with open(corrections_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        metrics["error"] = f"Failed to read corrections.json: {exc}"
        return metrics

    if not isinstance(data, dict):
        metrics["error"] = "corrections.json is not a JSON object"
        return metrics

    current = data.get("current") if isinstance(data.get("current"), dict) else {}
    changelog = data.get("changelog") if isinstance(data.get("changelog"), list) else []
    data.setdefault("schema_version", "2.0")
    data["current"] = current
    data["changelog"] = changelog
    if clip_id and not data.get("clip_id"):
        data["clip_id"] = str(clip_id)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    shot_descriptions = normalized_visual.get("shot_descriptions") if isinstance(normalized_visual.get("shot_descriptions"), list) else []
    new_changelog_entries: List[Dict[str, Any]] = []

    for key, entry in list(current.items()):
        if not isinstance(entry, dict):
            metrics["skipped"].append({"key": key, "reason": "entry not a dict"})
            continue
        if entry.get("source") != "human":
            continue
        # Key format: "{entity_type}:{entity_uuid}:{field_path}"
        parts = key.split(":", 2)
        if len(parts) != 3:
            metrics["skipped"].append({"key": key, "reason": "malformed key"})
            continue
        entity_type, entity_uuid, field_path = parts
        path_parts = [p for p in field_path.split(".") if p]
        if not path_parts:
            metrics["skipped"].append({"key": key, "reason": "empty field_path"})
            continue
        human_value = entry.get("value")

        if entity_type == "clip":
            target_container = normalized_visual
        elif entity_type == "shot":
            target_container = _find_shot_entry(shot_descriptions, entity_uuid)
            if target_container is None:
                metrics["skipped"].append({"key": key, "reason": "shot not found in vision output"})
                continue
        else:
            metrics["skipped"].append({"key": key, "reason": f"unknown entity_type '{entity_type}'"})
            continue

        found, machine_value = _walk_get(target_container, path_parts)
        if not _walk_set(target_container, path_parts, human_value):
            metrics["skipped"].append({"key": key, "reason": "could not write into target container"})
            continue
        metrics["preserved_count"] += 1
        metrics["applied"].append({
            "entity_type": entity_type,
            "entity_uuid": entity_uuid,
            "field_path": field_path,
        })

        if found and machine_value != human_value:
            new_changelog_entries.append({
                "entity_type": entity_type,
                "entity_uuid": entity_uuid,
                "field_path": field_path,
                "previous_value": machine_value,
                "new_value": human_value,
                "previous_source": "vision",
                "new_source": "human",
                "previous_author": "system",
                "new_author": entry.get("author") or "unknown",
                "change_reason": "preserved across re-analysis",
                "timestamp": now,
            })

    if new_changelog_entries:
        changelog.extend(new_changelog_entries)
        metrics["changelog_added"] = len(new_changelog_entries)
        try:
            os.makedirs(os.path.dirname(corrections_path), exist_ok=True)
            tmp_path = corrections_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, corrections_path)
        except OSError as exc:
            metrics["error"] = f"Failed to write corrections.json: {exc}"

    return metrics


def _normalize_host_chat_visual(payload: Any, *, fallback_record: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Coerce a host-chat visual payload into the canonical visual shape.

    Returns (normalized_visual, error). If the payload is missing required structure
    that we cannot safely default, returns (None, reason).
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            return None, f"visual payload was a string but not valid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "visual payload must be a JSON object matching the vision schema"

    normalized: Dict[str, Any] = dict(payload)
    normalized["success"] = True
    normalized["provider"] = HOST_CHAT_PATHS_PROVIDER
    normalized.pop("status", None)

    clip_summary = normalized.get("clip_summary")
    if not isinstance(clip_summary, str) or not clip_summary.strip():
        if fallback_record:
            normalized["clip_summary"] = f"Host-chat visual analysis for {fallback_record.get('clip_name') or fallback_record.get('file_path') or 'clip'}."
        else:
            normalized["clip_summary"] = "Host-chat visual analysis (no summary provided)."

    def _ensure_dict(key: str, default: Dict[str, Any]) -> None:
        value = normalized.get(key)
        if not isinstance(value, dict):
            normalized[key] = dict(default)

    def _ensure_list(container: Dict[str, Any], key: str) -> None:
        if not isinstance(container.get(key), list):
            container[key] = []

    _ensure_dict("editorial_classification", {"primary_use": "unknown", "select_potential": "medium", "reason": ""})
    _ensure_dict("content", {"locations": [], "people_visible": "unknown", "actions": [], "objects": [], "visible_text": [], "notable_audio_context": []})
    for list_key in ("locations", "actions", "objects", "visible_text", "notable_audio_context"):
        _ensure_list(normalized["content"], list_key)
    _ensure_dict("shot_and_style", {"shot_sizes": [], "camera_motion": [], "composition_notes": "", "lighting_mood": "", "color_mood": ""})
    for list_key in ("shot_sizes", "camera_motion"):
        _ensure_list(normalized["shot_and_style"], list_key)
    _ensure_dict("slate", {"slate_visible": False, "scene": "", "shot": "", "take": "", "camera": "", "roll": "", "date": "", "production": "", "visible_text": [], "confidence": {}})
    _ensure_list(normalized["slate"], "visible_text")
    _ensure_dict("motion", {"overall_level": "unknown", "motion_events": [], "quiet_regions": []})
    _ensure_list(normalized["motion"], "motion_events")
    _ensure_list(normalized["motion"], "quiet_regions")
    _ensure_dict("cut_understanding", {"cut_count": 0, "likely_edited_sequence": False, "flash_frame_candidates": [], "notes": []})
    _ensure_list(normalized["cut_understanding"], "flash_frame_candidates")
    _ensure_list(normalized["cut_understanding"], "notes")
    if not isinstance(normalized.get("analysis_keyframes"), list):
        normalized["analysis_keyframes"] = []
    raw_shot_descriptions = normalized.get("shot_descriptions")
    coerced_shot_descriptions: List[Dict[str, Any]] = []
    if isinstance(raw_shot_descriptions, list):
        for row in raw_shot_descriptions:
            if not isinstance(row, dict):
                continue
            entry: Dict[str, Any] = dict(row)
            try:
                entry["shot_index"] = int(entry.get("shot_index"))
            except (TypeError, ValueError):
                entry.pop("shot_index", None)
            for time_key in ("time_seconds_start", "time_seconds_end"):
                parsed = _parse_float(entry.get(time_key))
                if parsed is not None:
                    entry[time_key] = parsed
                else:
                    entry.pop(time_key, None)
            description = entry.get("description") or entry.get("visual_description")
            entry["description"] = str(description).strip() if description else ""
            if not isinstance(entry.get("qc_flags"), list):
                entry["qc_flags"] = []
            if not isinstance(entry.get("frame_indices_used"), list):
                entry.pop("frame_indices_used", None)
            coerced_shot_descriptions.append(entry)
    normalized["shot_descriptions"] = coerced_shot_descriptions
    _ensure_dict("editing_notes", {"best_moments": [], "continuity_flags": [], "qc_flags": [], "search_tags": []})
    for list_key in ("best_moments", "continuity_flags", "qc_flags", "search_tags"):
        _ensure_list(normalized["editing_notes"], list_key)
    _ensure_dict("confidence", {"visual": "low", "motion": "computed", "transcript": "unavailable"})

    return normalized, None


def _find_clip_dir_for_commit(
    project_root: str,
    *,
    clip_id: Optional[str] = None,
    file_path: Optional[str] = None,
    clip_dir: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    root = normalize_path(project_root)
    clips_root = os.path.join(root, "clips")
    if clip_dir:
        candidate = normalize_path(clip_dir if os.path.isabs(clip_dir) else os.path.join(clips_root, clip_dir))
        if not _is_relative_to(candidate, root):
            return None, "clip_dir must be under the project analysis root"
        if os.path.isdir(candidate):
            return candidate, None
        return None, f"clip_dir not found: {candidate}"
    if not os.path.isdir(clips_root):
        return None, f"No clips directory under analysis root: {clips_root}"
    target_clip_id = str(clip_id) if clip_id else None
    target_file = normalize_path(file_path) if file_path else None
    for entry in sorted(os.listdir(clips_root)):
        candidate = os.path.join(clips_root, entry)
        analysis_path = os.path.join(candidate, "analysis.json")
        if not os.path.isfile(analysis_path):
            continue
        try:
            with open(analysis_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        clip_block = report.get("clip") or {}
        if target_clip_id and str(clip_block.get("clip_id") or "") == target_clip_id:
            return candidate, None
        if target_file and normalize_path(clip_block.get("file_path") or "") == target_file:
            return candidate, None
    if target_clip_id:
        return None, f"No persisted analysis found for clip_id={target_clip_id} under {clips_root}"
    if target_file:
        return None, f"No persisted analysis found for file_path={target_file} under {clips_root}"
    return None, "commit_vision requires clip_id, file_path, or clip_dir"


def commit_visual_analysis(
    *,
    project_root: str,
    visual: Any,
    clip_id: Optional[str] = None,
    file_path: Optional[str] = None,
    clip_dir: Optional[str] = None,
    vision_token: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge host-chat visual analysis into an already-persisted clip report.

    Reads analysis.json under <project_root>/clips/<clip_dir>/, validates the
    optional vision_token against the stored deferred payload, normalizes the
    visual JSON, rewrites visual.json + analysis.json + clip_analysis_markers.json,
    refreshes the SQLite index entry, and returns the new report path.
    """
    root = normalize_path(project_root)
    if not os.path.isdir(root):
        return {"success": False, "error": f"Project analysis root not found: {root}"}

    clip_dir_path, lookup_err = _find_clip_dir_for_commit(
        root, clip_id=clip_id, file_path=file_path, clip_dir=clip_dir,
    )
    if lookup_err:
        return {"success": False, "error": lookup_err}

    analysis_json_path = os.path.join(clip_dir_path, "analysis.json")
    try:
        with open(analysis_json_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return {"success": False, "error": f"Failed to read analysis.json: {exc}"}

    existing_vision = report.get("visual") if isinstance(report.get("visual"), dict) else {}
    stored_token = existing_vision.get("vision_token") or report.get("vision_token")
    if vision_token and stored_token and str(vision_token) != str(stored_token):
        return {
            "success": False,
            "error": "vision_token mismatch; the analysis report has been re-analyzed since the deferred payload was issued.",
            "expected_vision_token": stored_token,
            "received_vision_token": vision_token,
        }

    record = report.get("clip") or {}
    normalized_visual, normalize_err = _normalize_host_chat_visual(visual, fallback_record=record)
    if normalize_err:
        return {"success": False, "error": normalize_err}

    # V2 trust-but-fix-optionally contract: re-apply human corrections so
    # re-analysis never silently overwrites editor edits.
    corrections_metrics = preserve_human_corrections(
        clip_dir_path,
        normalized_visual,
        clip_id=record.get("clip_id"),
    )

    technical = {"summary": report.get("technical") or {}}
    if isinstance(report.get("readthrough"), dict):
        readthrough = report["readthrough"]
    else:
        readthrough = {}
    motion = report.get("motion") if isinstance(report.get("motion"), dict) else {}
    transcript = report.get("transcription") if isinstance(report.get("transcription"), dict) else {}
    analysis_signature = report.get("analysis_signature") or {}
    profile = report.get("analysis_profile") or {}

    merged_options: Dict[str, Any] = {
        "vision": {"enabled": True, "provider": HOST_CHAT_PATHS_PROVIDER},
        "transcription": {"enabled": bool(profile.get("transcription_enabled", DEFAULT_TRANSCRIPTION_ENABLED))},
        "marker_plan": (options or {}).get("marker_plan") or {},
    }

    marker_plan = _build_clip_marker_plan(
        record,
        technical,
        readthrough,
        motion,
        transcript,
        normalized_visual,
        options=merged_options,
        analysis_signature=analysis_signature,
    )
    marker_plan_path = os.path.join(clip_dir_path, "clip_analysis_markers.json")
    marker_plan["path"] = marker_plan_path
    _write_json(marker_plan_path, marker_plan)

    visual_json_path = os.path.join(clip_dir_path, "visual.json")
    _write_json(visual_json_path, normalized_visual)

    report["visual"] = normalized_visual
    report["clip_analysis_markers"] = marker_plan
    report["analysis_profile"] = {
        **(profile if isinstance(profile, dict) else {}),
        "vision_enabled": True,
    }
    report.pop("vision_status", None)
    report.pop("vision_token", None)
    report["vision_committed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # C1 — DB rows first (canonical), then the derived JSON export.
    db_ingest = _ingest_report_into_db(root, report, clip_dir_path)
    _write_json(analysis_json_path, report)

    index_status_info: Dict[str, Any] = {}
    try:
        index_status_info = build_analysis_index(root)
    except Exception as exc:  # noqa: BLE001 — index refresh is best-effort
        index_status_info = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        registry_status = update_analysis_registry(root, report_paths=[analysis_json_path])
    except Exception as exc:  # noqa: BLE001 — registry refresh is best-effort
        registry_status = {"success": False, "error": f"{type(exc).__name__}: {exc}"}

    # Record caps usage if the host reported token counts in the visual payload.
    # Host clients that don't report tokens fall through with zeros (recorded as
    # frames_uploaded so the per-clip + per-day rollups still show activity).
    try:
        visual_dict = visual if isinstance(visual, dict) else {}
        usage_block = visual_dict.get("usage") if isinstance(visual_dict.get("usage"), dict) else {}
        vision_tokens = int(usage_block.get("vision_tokens") or usage_block.get("total_tokens") or 0)
        frames_uploaded = int(usage_block.get("frames_uploaded") or len(record.get("frame_paths") or []) or 0)
        _record_caps_usage(
            project_root=root,
            clip_id=record.get("clip_id") or clip_id,
            vision_tokens=vision_tokens,
            frames_uploaded=frames_uploaded,
        )
    except Exception:
        pass

    return _apply_caps_to_response({
        "success": True,
        "analysis_json": analysis_json_path,
        "visual_json": visual_json_path,
        "marker_plan_json": marker_plan_path,
        "marker_count": marker_plan.get("marker_count"),
        "clip_dir": clip_dir_path,
        "record": record,
        "index": index_status_info,
        "analysis_registry": registry_status,
        "corrections": corrections_metrics,
        "db_ingest": db_ingest,
    })


def _safe_report_path(project_root: str, report_path: str) -> Tuple[Optional[str], Optional[str]]:
    root = normalize_path(project_root)
    candidate = normalize_path(report_path)
    if not _is_relative_to(candidate, root):
        return None, "report_path must be under the project analysis root"
    if not os.path.isfile(candidate):
        return None, f"Report not found: {candidate}"
    return candidate, None


def load_report(project_root: str, report_path: Optional[str] = None, clip_dir: Optional[str] = None) -> Dict[str, Any]:
    if report_path:
        path, err = _safe_report_path(project_root, report_path)
        if err:
            return {"success": False, "error": err}
    elif clip_dir:
        path, err = _safe_report_path(project_root, os.path.join(project_root, "clips", clip_dir, "analysis.json"))
        if err:
            return {"success": False, "error": err}
    else:
        path, err = _safe_report_path(project_root, os.path.join(project_root, "manifest.json"))
        if err:
            return {"success": False, "error": err}
    payload = _read_json(path)
    return {"success": True, "path": path, "report": payload}


def _collect_reports_for_summary(root: str) -> Tuple[List[Dict[str, Any]], List[str], str]:
    """(reports, report_paths, source) for summarize_reports.

    DB-first: when every report dir on disk is covered by an ingested clip
    row, reports come from the DB-canonical store (blob + human overlay —
    identical content to the lockstep JSON export). Pre-v9 roots and MIXED
    roots (some clips not ingested) fall back WHOLESALE to the JSON walk —
    a partial DB view would silently under-report.
    """
    clips_root = os.path.join(root, "clips")
    disk_paths: List[str] = []
    if os.path.isdir(clips_root):
        for dirpath, _, filenames in os.walk(clips_root):
            if "analysis.json" in filenames:
                disk_paths.append(os.path.join(dirpath, "analysis.json"))
    disk_paths.sort()

    try:
        from src.utils import analysis_store, timeline_brain_db

        conn = timeline_brain_db.connect(root)
        db_dirs = {
            str(r["clip_dir"]): str(r["clip_uuid"])
            for r in conn.execute(
                "SELECT clip_dir, clip_uuid FROM clips WHERE clip_dir IS NOT NULL"
            ).fetchall()
        }
    except Exception:  # noqa: BLE001 — no DB (pre-v9) → JSON
        db_dirs = {}
    if disk_paths and db_dirs:
        dir_names = [os.path.basename(os.path.dirname(p)) for p in disk_paths]
        if all(name in db_dirs for name in dir_names):
            from src.utils import analysis_store

            reports: List[Dict[str, Any]] = []
            complete = True
            for path, name in zip(disk_paths, dir_names):
                try:
                    report = analysis_store.export_report(root, db_dirs[name])
                except Exception:  # noqa: BLE001
                    report = None
                if not isinstance(report, dict):
                    complete = False
                    break
                reports.append(report)
            if complete:
                return reports, disk_paths, "db"

    reports = []
    report_paths: List[str] = []
    for path in disk_paths:
        try:
            reports.append(_read_json(path))
            report_paths.append(path)
        except (OSError, json.JSONDecodeError):
            continue
    return reports, report_paths, "json"


def summarize_reports(project_root: str) -> Dict[str, Any]:
    root = normalize_path(project_root)
    reports, report_paths, reports_source = _collect_reports_for_summary(root)
    warnings = []
    motion_counts: Dict[str, int] = {}
    tags: Dict[str, int] = {}
    signed_report_count = 0
    newest_ts = 0.0
    # F1 — provenance source list, parallel to `reports`.
    source_reports: List[Dict[str, Any]] = []
    missing_reports: List[Dict[str, Any]] = []
    for report, report_path in zip(reports, report_paths):
        if report.get("analysis_signature"):
            signed_report_count += 1
        else:
            # Unsigned reports surface in `missing_reports` so the caller can
            # tell which contributing clips would need re-analysis to verify.
            missing_reports.append({
                "report_path": report_path,
                "reason": "unsigned_report",
            })
        analyzed_ts = _timestamp_from_analyzed_at(report.get("analyzed_at")) or 0
        newest_ts = max(newest_ts, analyzed_ts)
        warnings.extend(report.get("technical_warnings") or [])
        level = ((report.get("motion") or {}).get("overall_motion_level") or "unknown")
        motion_counts[level] = motion_counts.get(level, 0) + 1
        visual = report.get("visual") or {}
        editing_notes = visual.get("editing_notes") or {}
        for tag in editing_notes.get("search_tags") or []:
            tags[tag] = tags.get(tag, 0) + 1
        # F1 source-report citation entry.
        record = report.get("record") or {}
        source_reports.append({
            "clip_id": record.get("clip_id") or report.get("clip_id"),
            "clip_name": record.get("clip_name") or report.get("clip_name"),
            "analysis_signature": report.get("analysis_signature"),
            "analysis_report_path": report_path,
            "analyzed_at": report.get("analyzed_at"),
        })
    summary = {
        "success": True,
        "project_root": root,
        "source": reports_source,  # "db" (canonical store) | "json" (walk fallback)
        "clip_reports": len(reports),
        "motion_distribution": motion_counts,
        "technical_warning_count": len(warnings),
        "technical_warnings": warnings[:50],
        "search_tags": sorted(tags, key=tags.get, reverse=True)[:50],
        "cache": {
            "signed_report_count": signed_report_count,
            "unsigned_report_count": max(0, len(reports) - signed_report_count),
            "newest_analysis_at": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(newest_ts))
                if newest_ts else None
            ),
        },
        # F1 — provenance citation map. Lets callers (and the model) trace
        # each summary claim back to the underlying analysis reports, so
        # cross-clip statements aren't load-bearing without verification.
        "provenance": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scope": {"type": "project", "project_root": root},
            "source_reports": source_reports,
            "missing_reports": missing_reports,
        },
    }
    _write_json(os.path.join(root, "project_summary.json"), summary)
    return summary


_SOURCE_TRUST_RANK = {
    "unknown": -1,
    "auto": 0,
    "filename": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
}


def _source_trust_rank(value: Any) -> int:
    return _SOURCE_TRUST_RANK.get(str(value or "auto").strip().lower(), 0)


def _normalize_min_source_trust(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    candidate = str(value).strip().lower()
    if candidate not in SOURCE_TRUST_VALUES:
        return None
    return candidate


def _layers_present_in_report(report: Optional[Dict[str, Any]]) -> List[str]:
    """Return the analysis layers that have meaningful content in this report.

    Layer names match the planner's vocabulary (technical, readthrough,
    cut_analysis, motion, transcription, vision, marker_plan).
    """
    if not isinstance(report, dict):
        return []
    present: List[str] = []
    technical = report.get("technical")
    if isinstance(technical, dict) and technical:
        present.append("technical")
    readthrough = report.get("readthrough")
    if isinstance(readthrough, dict):
        if any(
            isinstance(readthrough.get(k), dict) and readthrough.get(k, {}).get("success") is not False
            for k in ("loudness", "scenes", "black_frames", "silence", "interlace")
        ):
            present.append("readthrough")
        if isinstance(readthrough.get("cut_analysis"), dict):
            present.append("cut_analysis")
    motion = report.get("motion")
    if isinstance(motion, dict) and (motion.get("analysis_keyframes") or motion.get("overall_motion_level")):
        present.append("motion")
    transcript = report.get("transcription")
    if isinstance(transcript, dict) and (transcript.get("text") or transcript.get("segments")):
        present.append("transcription")
    visual = report.get("visual")
    if isinstance(visual, dict):
        status = visual.get("status")
        is_pending = status == "pending_host_analysis" or visual.get("vision_token") is not None
        has_content = bool(
            visual.get("clip_summary")
            or visual.get("shot_descriptions")
            or visual.get("editorial_classification")
        )
        if has_content and not is_pending:
            present.append("vision")
    markers = report.get("clip_analysis_markers")
    if isinstance(markers, dict) and markers:
        present.append("marker_plan")
    return present


def _recommend_coverage_action(
    *,
    cache_status: str,
    reuse_blocked: bool,
    below_min_source_trust: bool,
    superseded_by_relink: bool,
    missing_layers: List[str],
    staleness_reasons: List[str],
    record: Dict[str, Any],
) -> str:
    if superseded_by_relink:
        return (
            "The Media Pool clip was replaced or relinked after analysis. The prior "
            "report is preserved for reference but should not be reused. Re-analyze "
            "with the current source media."
        )
    if reuse_blocked:
        return (
            "Resolve clip metadata claims prior analysis but no compatible report "
            "could be validated. Restore the referenced report or pass force_refresh=true."
        )
    if below_min_source_trust:
        return (
            "Existing analysis is below the requested min_source_trust. Re-run with "
            "source_trust raised (analyze_clip with source_trust=...) once the higher "
            "trust is justified."
        )
    if cache_status == "miss":
        clip_id = record.get("clip_id")
        target = f"clip_id={clip_id}" if clip_id else "this clip"
        return f"No analysis on disk. Run media_analysis(action=\"analyze_clip\", target={{...{target}...}})."
    if cache_status == "stale_or_incomplete":
        if missing_layers:
            return (
                "Existing report is missing layers: "
                + ", ".join(missing_layers)
                + ". Re-analyze with those layers enabled."
            )
        if staleness_reasons:
            return (
                "Existing report is stale ("
                + ", ".join(staleness_reasons)
                + "). Re-analyze or pass force_refresh=true."
            )
        return "Existing report exists but is not currently reusable. Re-analyze."
    if cache_status == "reusable":
        return "Report is current and reusable for the requested depth and modalities."
    return "Coverage state could not be determined; inspect clip details."


def _coverage_evidence_line(summary: Dict[str, Any]) -> str:
    total = int(summary.get("clips_total") or 0)
    if not total:
        return "evidence base: no clips in target."
    analyzed = int(summary.get("clips_analyzed") or 0)
    stale = int(summary.get("clips_stale") or 0)
    missing = int(summary.get("clips_missing") or 0)
    blocked = int(summary.get("clips_reuse_blocked") or 0)
    needs_trust = int(summary.get("clips_needs_higher_trust") or 0)
    pct = (analyzed / total) * 100.0
    fragments = [
        f"{analyzed}/{total} clips analyzed ({pct:.0f}%)",
    ]
    if stale:
        fragments.append(f"{stale} stale")
    if missing:
        fragments.append(f"{missing} missing")
    if blocked:
        fragments.append(f"{blocked} reuse-blocked")
    if needs_trust:
        fragments.append(f"{needs_trust} below min_source_trust")
    return "evidence base: " + ", ".join(fragments) + "."


def build_coverage_report(
    *,
    project_name: Any,
    project_id: Any = None,
    records: List[Dict[str, Any]],
    target: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
    capabilities: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pure-read coverage assessment for a target's clips.

    Reports per-clip analysis state (reusable / stale_or_incomplete / miss /
    reuse_blocked), layer presence, source_trust, and a recommended next action.
    Never triggers analysis. Builds on the planner's existing reuse pipeline
    (signature, registry, related project roots, provenance integrity).

    Optional params:
      min_source_trust: filter clips below this trust tier. Tiers in ascending
        order: auto < filename < low < medium < high. Clips below the threshold
        are classified `needs_higher_trust` regardless of report freshness.
      include_layers: ignored for now — layer expectations follow the planner's
        depth-driven requirements. Future extension point.
      max_report_age_days: forwarded to planner for freshness gating.
    """
    coverage_params = dict(params or {})
    coverage_params.setdefault("dry_run", True)
    coverage_params.setdefault("session_only", False)
    min_source_trust = _normalize_min_source_trust(coverage_params.pop("min_source_trust", coverage_params.pop("minSourceTrust", None)))

    plan = build_plan(
        project_name=project_name,
        project_id=project_id,
        records=records,
        target=target,
        params=coverage_params,
        capabilities=capabilities,
    )
    if not plan.get("success"):
        return plan

    coverage_clips: List[Dict[str, Any]] = []
    source_trust_dist: Dict[str, int] = {}
    layer_coverage: Dict[str, int] = {}
    summary_counts = {
        "analyzed": 0,
        "missing": 0,
        "stale": 0,
        "reuse_blocked": 0,
        "needs_higher_trust": 0,
    }

    for clip_plan in plan.get("clips") or []:
        if not isinstance(clip_plan, dict):
            continue
        record = clip_plan.get("record") or {}
        existing = clip_plan.get("existing_report") or {}
        report_path = existing.get("path")
        report: Optional[Dict[str, Any]] = None
        if report_path and os.path.isfile(str(report_path)):
            try:
                report = _read_json(str(report_path))
            except (OSError, json.JSONDecodeError):
                report = None
        layers_present = _layers_present_in_report(report)
        for layer in layers_present:
            layer_coverage[layer] = layer_coverage.get(layer, 0) + 1

        source_trust = "unknown"
        if isinstance(report, dict):
            profile = report.get("analysis_profile") if isinstance(report.get("analysis_profile"), dict) else {}
            value = profile.get("source_trust")
            if value:
                source_trust = str(value).strip().lower()
        source_trust_dist[source_trust] = source_trust_dist.get(source_trust, 0) + 1

        cache_status = str(clip_plan.get("cache_status") or "not_checked")
        is_reusable = bool(clip_plan.get("skip_execution"))
        reuse_blocked = bool(clip_plan.get("reuse_blocked"))
        missing_layers = list(existing.get("missing_layers") or [])
        staleness_reasons = list(existing.get("cache_issues") or [])
        cache_warnings = list(existing.get("cache_warnings") or [])
        superseded_by_relink = bool(existing.get("superseded_by_relink"))

        below_min_source_trust = False
        if min_source_trust and source_trust != "unknown":
            below_min_source_trust = _source_trust_rank(source_trust) < _source_trust_rank(min_source_trust)

        if superseded_by_relink:
            summary_counts["stale"] += 1
        elif reuse_blocked:
            summary_counts["reuse_blocked"] += 1
        elif below_min_source_trust:
            summary_counts["needs_higher_trust"] += 1
        elif is_reusable:
            summary_counts["analyzed"] += 1
        elif report_path and (missing_layers or staleness_reasons):
            summary_counts["stale"] += 1
        else:
            summary_counts["missing"] += 1

        recommended_action = _recommend_coverage_action(
            cache_status=cache_status,
            reuse_blocked=reuse_blocked,
            below_min_source_trust=below_min_source_trust,
            superseded_by_relink=superseded_by_relink,
            missing_layers=missing_layers,
            staleness_reasons=staleness_reasons,
            record=record,
        )

        coverage_clips.append({
            "clip_id": record.get("clip_id"),
            "clip_name": record.get("clip_name"),
            "file_path": record.get("file_path"),
            "media_id": record.get("media_id"),
            "analyzed": is_reusable and not superseded_by_relink,
            "report_path": report_path,
            "report_project_root": existing.get("project_root"),
            "report_source": existing.get("source"),
            "cache_status": cache_status,
            "reuse_blocked": reuse_blocked,
            "superseded_by_relink": superseded_by_relink,
            "superseded_at": existing.get("superseded_at"),
            "superseded_reason": existing.get("superseded_reason"),
            "layers_present": layers_present,
            "missing_layers": missing_layers,
            "staleness_reasons": staleness_reasons,
            "cache_warnings": cache_warnings,
            "source_trust": source_trust,
            "below_min_source_trust": below_min_source_trust,
            "provenance_present": _record_has_analysis_provenance(record),
            "analyzed_at": existing.get("analyzed_at"),
            "why_not_reused": clip_plan.get("why_not_reused"),
            "recommended_action": recommended_action,
        })

    total = len(coverage_clips)
    summary = {
        "clips_total": total,
        "clips_analyzed": summary_counts["analyzed"],
        "clips_missing": summary_counts["missing"],
        "clips_stale": summary_counts["stale"],
        "clips_reuse_blocked": summary_counts["reuse_blocked"],
        "clips_needs_higher_trust": summary_counts["needs_higher_trust"],
        "coverage_percent": (summary_counts["analyzed"] / total * 100.0) if total else 0.0,
        "layer_coverage": layer_coverage,
        "source_trust_distribution": source_trust_dist,
    }

    return {
        "success": True,
        "action": "coverage_report",
        "target": plan.get("target"),
        "min_source_trust": min_source_trust,
        "evidence_base": _coverage_evidence_line(summary),
        "summary": summary,
        "clips": coverage_clips,
        "output_root": plan.get("output_root"),
        "reuse_project_roots": plan.get("reuse_project_roots"),
        "related_project_roots": plan.get("related_project_roots"),
        "analysis_version": ANALYSIS_VERSION,
        "notes": [
            "coverage_report is a pure read — it never triggers analysis.",
            "Editorial and color tools should call this first and lead any recommendation with `evidence_base`.",
        ],
    }


def analysis_root_coverage(project_root: str) -> Dict[str, Any]:
    """Standalone coverage summary — reads on-disk reports + registry, no Resolve required.

    Powers the control panel Readiness widget. Reports per-layer coverage
    counts, source_trust distribution, superseded_by_relink counts (from the
    registry), recent activity, and warning counts. Returns roughly the same
    shape as `build_coverage_report.summary` plus an `analyzed_clips` list,
    minus per-clip target/missing-layer detail (those require live records).
    """
    root = normalize_path(project_root)
    if not os.path.isdir(root):
        return {"success": False, "error": f"Analysis project root not found: {root}"}

    reports: List[Tuple[str, Dict[str, Any]]] = []
    clips_root = os.path.join(root, "clips")
    if os.path.isdir(clips_root):
        for dirpath, _, filenames in os.walk(clips_root):
            if "analysis.json" not in filenames:
                continue
            report_path = os.path.join(dirpath, "analysis.json")
            try:
                reports.append((report_path, _read_json(report_path)))
            except (OSError, json.JSONDecodeError):
                continue

    registry = _read_analysis_registry(root)
    superseded_by_path: Dict[str, Dict[str, Any]] = {}
    for entry in registry.get("entries") or []:
        if not isinstance(entry, dict) or not entry.get("superseded_by_relink"):
            continue
        path = normalize_path(entry.get("analysis_json") or "")
        if path:
            superseded_by_path[path] = {
                "superseded_at": entry.get("superseded_at"),
                "superseded_reason": entry.get("superseded_reason"),
            }

    layer_coverage: Dict[str, int] = {}
    source_trust_dist: Dict[str, int] = {}
    motion_dist: Dict[str, int] = {}
    warnings: List[str] = []
    signed_count = 0
    newest_ts = 0.0
    analyzed_clips: List[Dict[str, Any]] = []
    superseded_count = 0

    for report_path, report in reports:
        normalized_report_path = normalize_path(report_path)
        layers = _layers_present_in_report(report)
        for layer in layers:
            layer_coverage[layer] = layer_coverage.get(layer, 0) + 1

        profile = report.get("analysis_profile") if isinstance(report.get("analysis_profile"), dict) else {}
        trust = str(profile.get("source_trust") or "").strip().lower() or "unknown"
        source_trust_dist[trust] = source_trust_dist.get(trust, 0) + 1

        motion_level = (report.get("motion") or {}).get("overall_motion_level") or "unknown"
        motion_dist[str(motion_level)] = motion_dist.get(str(motion_level), 0) + 1

        warnings.extend(str(w) for w in (report.get("technical_warnings") or []))

        if report.get("analysis_signature"):
            signed_count += 1
        analyzed_ts = _timestamp_from_analyzed_at(report.get("analyzed_at")) or 0
        newest_ts = max(newest_ts, analyzed_ts)

        clip_info = report.get("clip") if isinstance(report.get("clip"), dict) else {}
        superseded_info = superseded_by_path.get(normalized_report_path)
        if superseded_info:
            superseded_count += 1
        analyzed_clips.append({
            "clip_id": clip_info.get("clip_id"),
            "clip_name": clip_info.get("clip_name"),
            "source_file": report.get("source_file") or clip_info.get("file_path"),
            "report_path": normalized_report_path,
            "analyzed_at": report.get("analyzed_at"),
            "layers_present": layers,
            "source_trust": trust,
            "superseded_by_relink": bool(superseded_info),
            "superseded_reason": (superseded_info or {}).get("superseded_reason"),
            "vision_pending": bool(
                (report.get("visual") or {}).get("status") == "pending_host_analysis"
                or (report.get("visual") or {}).get("vision_token")
            ),
            "depth": profile.get("depth"),
        })

    return {
        "success": True,
        "project_root": root,
        "registry_path": analysis_registry_path(root),
        "summary": {
            "clips_total_with_reports": len(reports),
            "clips_signed": signed_count,
            "clips_unsigned": max(0, len(reports) - signed_count),
            "clips_superseded_by_relink": superseded_count,
            "clips_vision_pending": sum(1 for clip in analyzed_clips if clip["vision_pending"]),
            "layer_coverage": layer_coverage,
            "source_trust_distribution": source_trust_dist,
            "motion_distribution": motion_dist,
            "technical_warning_count": len(warnings),
            "newest_analysis_at": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(newest_ts)) if newest_ts else None
            ),
        },
        "warnings": warnings[:50],
        "analyzed_clips": sorted(
            analyzed_clips,
            key=lambda row: (
                0 if row.get("superseded_by_relink") else 1,
                -float(_timestamp_from_analyzed_at(row.get("analyzed_at")) or 0),
            ),
        )[:200],
        "notes": [
            "analysis_root_coverage is a standalone read of the analysis directory.",
            "It does NOT compare against live Resolve clips; use coverage_report (action) for per-target missing-clip detection.",
        ],
    }


def cleanup_artifacts(project_root: str, *, frames_only: bool = True) -> Dict[str, Any]:
    root = normalize_path(project_root)
    if not os.path.isdir(root):
        return {"success": False, "error": f"Project analysis root not found: {root}"}
    removed = []
    if frames_only:
        for dirpath, dirnames, _ in os.walk(root):
            for dirname in list(dirnames):
                if dirname == "frames":
                    full = os.path.join(dirpath, dirname)
                    shutil.rmtree(full, ignore_errors=True)
                    removed.append(full)
    else:
        shutil.rmtree(root, ignore_errors=True)
        removed.append(root)
    return {"success": True, "removed": removed, "frames_only": frames_only}


def _analysis_index_path(project_root: str, index_path: Optional[Any] = None) -> Tuple[Optional[str], Optional[str]]:
    root = normalize_path(project_root)
    candidate = normalize_path(index_path) if index_path else os.path.join(root, ANALYSIS_INDEX_FILENAME)
    if not _is_relative_to(candidate, root):
        return None, "index_path must be under the project analysis root"
    return candidate, None


def _iter_analysis_report_files(project_root: str) -> Iterable[str]:
    root = normalize_path(project_root)
    seen: set = set()
    clips_root = os.path.join(root, "clips")
    if not os.path.isdir(clips_root):
        clips_root = ""
    if clips_root:
        for dirpath, _, filenames in os.walk(clips_root):
            if "analysis.json" in filenames:
                path = os.path.join(dirpath, "analysis.json")
                real_path = os.path.realpath(path)
                seen.add(real_path)
                yield path

    db_path = os.path.join(root, "jobs.sqlite")
    if not os.path.isfile(db_path):
        return
    base_root = os.path.dirname(root)
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                """
                SELECT report_path, status
                FROM job_clips
                WHERE report_path IS NOT NULL
                  AND status IN ('succeeded', 'skipped', 'analyzed')
                ORDER BY updated_at DESC
                """
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return
    for row in rows:
        report_path = str(row[0] or "")
        if not report_path:
            continue
        path = normalize_path(report_path)
        real_path = os.path.realpath(path)
        if real_path in seen:
            continue
        if os.path.basename(real_path) != "analysis.json" or not os.path.isfile(real_path):
            continue
        try:
            if os.path.commonpath([real_path, base_root]) != base_root:
                continue
        except ValueError:
            continue
        seen.add(real_path)
        yield path


def _index_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _index_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _index_as_list(value: Any) -> List[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _first_video_summary(technical: Dict[str, Any]) -> Dict[str, Any]:
    videos = technical.get("video") if isinstance(technical.get("video"), list) else []
    return videos[0] if videos and isinstance(videos[0], dict) else {}


def _index_report_duration(report: Dict[str, Any]) -> Optional[float]:
    marker_plan = report.get("clip_analysis_markers") if isinstance(report.get("clip_analysis_markers"), dict) else {}
    duration = _parse_float(marker_plan.get("duration_seconds"))
    if duration is not None:
        return duration
    technical = report.get("technical") if isinstance(report.get("technical"), dict) else {}
    fmt = technical.get("format") if isinstance(technical.get("format"), dict) else {}
    duration = _parse_float(fmt.get("duration_seconds"))
    if duration is not None:
        return duration
    return _parse_float(_first_video_summary(technical).get("duration_seconds"))


def _index_report_fps(report: Dict[str, Any]) -> Optional[float]:
    marker_plan = report.get("clip_analysis_markers") if isinstance(report.get("clip_analysis_markers"), dict) else {}
    fps = _parse_float(marker_plan.get("fps"))
    if fps is not None:
        return fps
    clip = report.get("clip") if isinstance(report.get("clip"), dict) else {}
    technical = report.get("technical") if isinstance(report.get("technical"), dict) else {}
    return _parse_float(_analysis_fps(clip, {"summary": technical}))


def _index_visual_tags(report: Dict[str, Any]) -> List[Tuple[str, str]]:
    visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
    tags: List[Tuple[str, str]] = []
    editing_notes = visual.get("editing_notes") if isinstance(visual.get("editing_notes"), dict) else {}
    for tag in _index_as_list(editing_notes.get("search_tags")):
        text = _index_text(tag)
        if text:
            tags.append((text, "visual.search_tags"))
    content = visual.get("content") if isinstance(visual.get("content"), dict) else {}
    for key in ("locations", "actions", "objects", "visible_text", "notable_audio_context"):
        for item in _index_as_list(content.get(key)):
            text = _index_text(item)
            if text:
                tags.append((text, f"visual.content.{key}"))
    slate = visual.get("slate") if isinstance(visual.get("slate"), dict) else {}
    for key in ("scene", "shot", "take", "camera", "roll", "production"):
        text = _index_text(slate.get(key))
        if text:
            tags.append((text, f"visual.slate.{key}"))
    for item in _index_as_list(slate.get("visible_text")):
        text = _index_text(item)
        if text:
            tags.append((text, "visual.slate.visible_text"))
    classification = visual.get("editorial_classification") if isinstance(visual.get("editorial_classification"), dict) else {}
    for key in ("primary_use", "select_potential", "energy_arc", "style"):
        text = _index_text(classification.get(key))
        if text:
            tags.append((text, f"visual.editorial_classification.{key}"))
    for item in _index_as_list(classification.get("genre_indicators")):
        text = _index_text(item)
        if text:
            tags.append((text, "visual.editorial_classification.genre_indicators"))
    shot_and_style = visual.get("shot_and_style") if isinstance(visual.get("shot_and_style"), dict) else {}
    for key in ("shot_sizes", "camera_motion"):
        for item in _index_as_list(shot_and_style.get(key)):
            text = _index_text(item)
            if text:
                tags.append((text, f"visual.shot_and_style.{key}"))
    for row in visual.get("shot_descriptions") or []:
        if not isinstance(row, dict):
            continue
        text = _index_text(row.get("description"))
        if text:
            tags.append((text, "visual.shot_descriptions"))
    seen = set()
    unique: List[Tuple[str, str]] = []
    for tag, source in tags:
        key = (tag.lower(), source)
        if key in seen:
            continue
        seen.add(key)
        unique.append((tag, source))
    return unique


def _index_editorial_corpus(report: Dict[str, Any]) -> str:
    """Concatenate every long-form editorial text field from the V2 visual layer
    into a single searchable string. Used to populate the FTS `summary` column
    so the Review page search box can find clips by their editorial content,
    not just by chips and slate metadata.
    """
    visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
    parts: List[str] = []

    def push(value: Any) -> None:
        text = _index_text(value)
        if text:
            parts.append(text)

    push(visual.get("clip_summary"))
    push(visual.get("clip_summary_oneliner"))

    classification = visual.get("editorial_classification") if isinstance(visual.get("editorial_classification"), dict) else {}
    push(classification.get("reason"))
    for item in _index_as_list(classification.get("genre_indicators")):
        push(item)

    shot_and_style = visual.get("shot_and_style") if isinstance(visual.get("shot_and_style"), dict) else {}
    for key in ("composition_notes", "lighting_mood", "color_mood"):
        push(shot_and_style.get(key))

    cut_understanding = visual.get("cut_understanding") if isinstance(visual.get("cut_understanding"), dict) else {}
    for item in _index_as_list(cut_understanding.get("notes")):
        push(item)
    for item in _index_as_list(cut_understanding.get("flash_frame_candidates")):
        push(item)

    editing_notes = visual.get("editing_notes") if isinstance(visual.get("editing_notes"), dict) else {}
    for key in ("best_moments", "continuity_flags", "qc_flags"):
        for item in _index_as_list(editing_notes.get(key)):
            push(item)

    qc = visual.get("qc") if isinstance(visual.get("qc"), dict) else {}
    for key in ("warnings", "continuity_observations", "coverage_gaps"):
        for item in _index_as_list(qc.get(key)):
            push(item)

    motion = visual.get("motion") if isinstance(visual.get("motion"), dict) else {}
    for key in ("motion_events", "quiet_regions"):
        for item in _index_as_list(motion.get(key)):
            push(item)

    for row in visual.get("shot_descriptions") or []:
        if not isinstance(row, dict):
            continue
        push(row.get("description"))

    return " ".join(parts)


def _index_report_key(report_path: str, report: Dict[str, Any]) -> str:
    clip = report.get("clip") if isinstance(report.get("clip"), dict) else {}
    parent = os.path.basename(os.path.dirname(report_path))
    if parent and parent != "clips":
        return parent
    return stable_clip_directory(clip)


def _create_analysis_index_schema(conn: sqlite3.Connection) -> bool:
    conn.executescript(
        """
        CREATE TABLE index_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE clips (
            clip_key TEXT PRIMARY KEY,
            clip_id TEXT,
            media_id TEXT,
            clip_name TEXT,
            file_path TEXT,
            bin_path TEXT,
            media_type TEXT,
            duration_seconds REAL,
            fps REAL,
            summary TEXT,
            analyzed_at TEXT,
            report_path TEXT NOT NULL,
            marker_plan_path TEXT,
            technical_warning_count INTEGER NOT NULL DEFAULT 0,
            motion_level TEXT,
            transcript_available INTEGER NOT NULL DEFAULT 0,
            visual_available INTEGER NOT NULL DEFAULT 0,
            source_size_bytes INTEGER,
            source_mtime_ns INTEGER,
            signature_hash TEXT
        );

        CREATE INDEX idx_clips_file_path ON clips(file_path);
        CREATE INDEX idx_clips_clip_id ON clips(clip_id);
        CREATE INDEX idx_clips_motion_level ON clips(motion_level);

        CREATE TABLE technical_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_key TEXT NOT NULL,
            warning TEXT NOT NULL,
            FOREIGN KEY (clip_key) REFERENCES clips(clip_key) ON DELETE CASCADE
        );

        CREATE TABLE markers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_key TEXT NOT NULL,
            marker_id TEXT,
            marker_type TEXT,
            subtype TEXT,
            color TEXT,
            name TEXT,
            start_seconds REAL,
            end_seconds REAL,
            start_frame INTEGER,
            duration_frames INTEGER,
            visual_description TEXT,
            sound_note TEXT,
            transcript_text TEXT,
            source TEXT,
            confidence TEXT,
            FOREIGN KEY (clip_key) REFERENCES clips(clip_key) ON DELETE CASCADE
        );

        CREATE INDEX idx_markers_clip_key ON markers(clip_key);
        CREATE INDEX idx_markers_type ON markers(marker_type);
        CREATE INDEX idx_markers_start_seconds ON markers(start_seconds);

        CREATE TABLE transcript_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_key TEXT NOT NULL,
            segment_index INTEGER NOT NULL,
            start_seconds REAL,
            end_seconds REAL,
            text TEXT NOT NULL,
            FOREIGN KEY (clip_key) REFERENCES clips(clip_key) ON DELETE CASCADE
        );

        CREATE INDEX idx_transcript_segments_clip_key ON transcript_segments(clip_key);
        CREATE INDEX idx_transcript_segments_start_seconds ON transcript_segments(start_seconds);

        CREATE TABLE visual_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_key TEXT NOT NULL,
            tag TEXT NOT NULL,
            source TEXT,
            FOREIGN KEY (clip_key) REFERENCES clips(clip_key) ON DELETE CASCADE
        );

        CREATE INDEX idx_visual_tags_tag ON visual_tags(tag);
        CREATE INDEX idx_visual_tags_clip_key ON visual_tags(clip_key);

        CREATE TABLE timeline_occurrences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_key TEXT NOT NULL,
            timeline_id TEXT,
            timeline_name TEXT,
            track_type TEXT,
            track_index INTEGER,
            item_index INTEGER,
            start_frame INTEGER,
            end_frame INTEGER,
            record_frame INTEGER,
            occurrence_json TEXT NOT NULL,
            FOREIGN KEY (clip_key) REFERENCES clips(clip_key) ON DELETE CASCADE
        );

        CREATE INDEX idx_timeline_occurrences_clip_key ON timeline_occurrences(clip_key);
        CREATE INDEX idx_timeline_occurrences_timeline ON timeline_occurrences(timeline_id, timeline_name);

        CREATE TABLE analysis_keyframes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_key TEXT NOT NULL,
            keyframe_index INTEGER,
            time_seconds REAL,
            selection_reason TEXT,
            mean_luma REAL,
            delta_from_previous REAL,
            FOREIGN KEY (clip_key) REFERENCES clips(clip_key) ON DELETE CASCADE
        );

        CREATE INDEX idx_analysis_keyframes_clip_key ON analysis_keyframes(clip_key);
        CREATE INDEX idx_analysis_keyframes_time_seconds ON analysis_keyframes(time_seconds);
        """
    )
    try:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE clips_fts USING fts5(
                clip_key UNINDEXED,
                clip_name,
                summary,
                file_path,
                tags,
                warnings
            );
            CREATE VIRTUAL TABLE markers_fts USING fts5(
                marker_rowid UNINDEXED,
                clip_key UNINDEXED,
                name,
                visual_description,
                sound_note,
                transcript_text
            );
            CREATE VIRTUAL TABLE transcripts_fts USING fts5(
                segment_rowid UNINDEXED,
                clip_key UNINDEXED,
                text
            );
            """
        )
        return True
    except sqlite3.OperationalError:
        return False


def _insert_analysis_report_into_index(conn: sqlite3.Connection, report_path: str, report: Dict[str, Any], *, fts_enabled: bool) -> Dict[str, int]:
    clip = report.get("clip") if isinstance(report.get("clip"), dict) else {}
    technical = report.get("technical") if isinstance(report.get("technical"), dict) else {}
    motion = report.get("motion") if isinstance(report.get("motion"), dict) else {}
    transcription = report.get("transcription") if isinstance(report.get("transcription"), dict) else {}
    visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
    marker_plan = report.get("clip_analysis_markers") if isinstance(report.get("clip_analysis_markers"), dict) else {}
    signature = report.get("analysis_signature") if isinstance(report.get("analysis_signature"), dict) else {}
    source_signature = signature.get("source_file") if isinstance(signature.get("source_file"), dict) else {}

    clip_key = _index_report_key(report_path, report)
    source_file = report.get("source_file") or clip.get("file_path")
    marker_plan_path = os.path.join(os.path.dirname(report_path), "clip_analysis_markers.json")
    if not os.path.isfile(marker_plan_path):
        marker_plan_path = None

    warnings = [_index_text(item) for item in _index_as_list(report.get("technical_warnings")) if _index_text(item)]
    warnings.extend(
        _index_text(item)
        for item in _index_as_list(technical.get("warnings") if isinstance(technical, dict) else None)
        if _index_text(item)
    )
    warnings = list(dict.fromkeys(warnings))
    visual_tags = _index_visual_tags(report)
    # If the user has saved transcript corrections, index those instead of the
    # raw transcription. Keeps the search box in sync with edits.
    transcript_segments = transcription.get("segments") if isinstance(transcription.get("segments"), list) else []
    if report_path:
        corrections_path = os.path.join(os.path.dirname(report_path), "transcript-corrections.json")
        if os.path.isfile(corrections_path):
            try:
                with open(corrections_path, "r", encoding="utf-8") as handle:
                    corr = json.load(handle)
                if isinstance(corr, dict) and isinstance(corr.get("segments"), list):
                    transcript_segments = [s for s in corr["segments"] if isinstance(s, dict) and not s.get("deleted")]
            except Exception:
                pass
    transcript_text = _index_text(transcription.get("text"))
    transcript_available = bool(transcript_text or transcript_segments)
    visual_available = bool(
        visual.get("success")
        and (
            visual.get("clip_summary")
            or visual_tags
            or visual.get("analysis_keyframes")
            or visual.get("shot_descriptions")
        )
    )

    conn.execute(
        """
        INSERT INTO clips (
            clip_key, clip_id, media_id, clip_name, file_path, bin_path, media_type,
            duration_seconds, fps, summary, analyzed_at, report_path, marker_plan_path,
            technical_warning_count, motion_level, transcript_available, visual_available,
            source_size_bytes, source_mtime_ns, signature_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            clip_key,
            clip.get("clip_id"),
            clip.get("media_id"),
            clip.get("clip_name") or (os.path.basename(str(source_file)) if source_file else None),
            source_file,
            clip.get("bin_path"),
            clip.get("media_type"),
            _index_report_duration(report),
            _index_report_fps(report),
            report.get("summary"),
            report.get("analyzed_at"),
            report_path,
            marker_plan_path,
            len(warnings),
            motion.get("overall_motion_level"),
            int(transcript_available),
            int(visual_available),
            source_signature.get("size_bytes"),
            source_signature.get("mtime_ns"),
            signature.get("signature_hash"),
        ),
    )

    for warning in warnings:
        conn.execute("INSERT INTO technical_warnings (clip_key, warning) VALUES (?, ?)", (clip_key, warning))

    for tag, source in visual_tags:
        conn.execute("INSERT INTO visual_tags (clip_key, tag, source) VALUES (?, ?, ?)", (clip_key, tag, source))

    marker_count = 0
    for marker in marker_plan.get("markers") or []:
        if not isinstance(marker, dict):
            continue
        cur = conn.execute(
            """
            INSERT INTO markers (
                clip_key, marker_id, marker_type, subtype, color, name, start_seconds,
                end_seconds, start_frame, duration_frames, visual_description, sound_note,
                transcript_text, source, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_key,
                marker.get("id"),
                marker.get("type"),
                marker.get("subtype"),
                marker.get("color"),
                marker.get("name"),
                _parse_float(marker.get("start_seconds")),
                _parse_float(marker.get("end_seconds")),
                marker.get("start_frame"),
                marker.get("duration_frames"),
                marker.get("visual_description"),
                marker.get("sound_note"),
                marker.get("transcript_text"),
                marker.get("source"),
                marker.get("confidence"),
            ),
        )
        marker_count += 1
        if fts_enabled:
            conn.execute(
                """
                INSERT INTO markers_fts (
                    marker_rowid, clip_key, name, visual_description, sound_note, transcript_text
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cur.lastrowid,
                    clip_key,
                    marker.get("name"),
                    marker.get("visual_description"),
                    marker.get("sound_note"),
                    marker.get("transcript_text"),
                ),
            )

    segment_count = 0
    if transcript_segments:
        for index, segment in enumerate(transcript_segments):
            if not isinstance(segment, dict):
                continue
            text = _index_text(segment.get("text"))
            if not text:
                continue
            cur = conn.execute(
                """
                INSERT INTO transcript_segments (
                    clip_key, segment_index, start_seconds, end_seconds, text
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    clip_key,
                    index,
                    _parse_float(segment.get("start")),
                    _parse_float(segment.get("end")),
                    text,
                ),
            )
            segment_count += 1
            if fts_enabled:
                conn.execute(
                    "INSERT INTO transcripts_fts (segment_rowid, clip_key, text) VALUES (?, ?, ?)",
                    (cur.lastrowid, clip_key, text),
                )
    elif transcript_text:
        cur = conn.execute(
            """
            INSERT INTO transcript_segments (
                clip_key, segment_index, start_seconds, end_seconds, text
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (clip_key, 0, None, None, transcript_text),
        )
        segment_count += 1
        if fts_enabled:
            conn.execute(
                "INSERT INTO transcripts_fts (segment_rowid, clip_key, text) VALUES (?, ?, ?)",
                (cur.lastrowid, clip_key, transcript_text),
            )

    occurrence_count = 0
    occurrences = marker_plan.get("timeline_occurrences") or clip.get("timeline_occurrences") or []
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            continue
        conn.execute(
            """
            INSERT INTO timeline_occurrences (
                clip_key, timeline_id, timeline_name, track_type, track_index,
                item_index, start_frame, end_frame, record_frame, occurrence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_key,
                occurrence.get("timeline_id") or occurrence.get("timelineId"),
                occurrence.get("timeline_name") or occurrence.get("timelineName"),
                occurrence.get("track_type") or occurrence.get("trackType"),
                occurrence.get("track_index") or occurrence.get("trackIndex"),
                occurrence.get("item_index") or occurrence.get("itemIndex"),
                occurrence.get("start_frame") or occurrence.get("startFrame"),
                occurrence.get("end_frame") or occurrence.get("endFrame"),
                occurrence.get("record_frame") or occurrence.get("recordFrame"),
                _index_json(occurrence),
            ),
        )
        occurrence_count += 1

    keyframe_count = 0
    for index, keyframe in enumerate(report.get("analysis_keyframes") or []):
        if not isinstance(keyframe, dict):
            continue
        metrics = keyframe.get("metrics") if isinstance(keyframe.get("metrics"), dict) else {}
        conn.execute(
            """
            INSERT INTO analysis_keyframes (
                clip_key, keyframe_index, time_seconds, selection_reason, mean_luma, delta_from_previous
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                clip_key,
                keyframe.get("index", index + 1),
                _parse_float(keyframe.get("time_seconds")),
                keyframe.get("selection_reason"),
                _parse_float(metrics.get("mean_luma")),
                _parse_float(keyframe.get("delta_from_previous")),
            ),
        )
        keyframe_count += 1

    if fts_enabled:
        editorial_corpus = _index_editorial_corpus(report)
        technical_summary = report.get("summary") or ""
        # Stuff both into the FTS `summary` column so the search box on the
        # Review page can find clips by any editorial text (summaries,
        # composition notes, qc observations, motion events, shot
        # descriptions) in addition to the technical pass.
        combined_summary = " ".join(part for part in (technical_summary, editorial_corpus) if part).strip() or None
        conn.execute(
            """
            INSERT INTO clips_fts (clip_key, clip_name, summary, file_path, tags, warnings)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                clip_key,
                clip.get("clip_name") or (os.path.basename(str(source_file)) if source_file else None),
                combined_summary,
                source_file,
                " ".join(tag for tag, _ in visual_tags),
                " ".join(warnings),
            ),
        )

    return {
        "warnings": len(warnings),
        "markers": marker_count,
        "transcript_segments": segment_count,
        "visual_tags": len(visual_tags),
        "timeline_occurrences": occurrence_count,
        "analysis_keyframes": keyframe_count,
    }


def build_analysis_index(project_root: str, *, index_path: Optional[Any] = None) -> Dict[str, Any]:
    """Build a single-user SQLite index derived from media analysis JSON reports."""
    root = normalize_path(project_root)
    if not os.path.isdir(root):
        return {"success": False, "error": f"Project analysis root not found: {root}"}
    db_path, err = _analysis_index_path(root, index_path)
    if err or not db_path:
        return {"success": False, "error": err}

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    tmp_path = f"{db_path}.tmp"
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(f"{tmp_path}{suffix}")
        except OSError:
            pass

    counts = {
        "clips": 0,
        "warnings": 0,
        "markers": 0,
        "transcript_segments": 0,
        "visual_tags": 0,
        "timeline_occurrences": 0,
        "analysis_keyframes": 0,
    }
    failed_reports: List[Dict[str, Any]] = []
    built_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = sqlite3.connect(tmp_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        fts_enabled = _create_analysis_index_schema(conn)
        conn.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("schema_version", str(ANALYSIS_INDEX_SCHEMA_VERSION)))
        conn.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("analysis_version", ANALYSIS_VERSION))
        conn.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("built_at", built_at))
        conn.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("fts_enabled", "1" if fts_enabled else "0"))
        conn.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("image_blob_policy", "excluded"))

        # DB-first sourcing: local reports whose clip dir is ingested come from
        # the DB-canonical store (blob + human overlay — identical content to
        # the lockstep JSON export) instead of re-parsing every analysis.json.
        # Pre-v9 dirs and job-linked EXTERNAL report paths (their rows live
        # under another project's DB) keep the JSON read. The index schema and
        # the query surface are unchanged either way.
        clips_root_prefix = os.path.realpath(os.path.join(root, "clips")) + os.sep
        try:
            from src.utils import timeline_brain_db as _brain_db

            _db_dirs = {
                str(r["clip_dir"]): str(r["clip_uuid"])
                for r in _brain_db.connect(root).execute(
                    "SELECT clip_dir, clip_uuid FROM clips WHERE clip_dir IS NOT NULL"
                ).fetchall()
            }
        except Exception:  # noqa: BLE001 — no DB (pre-v9) → JSON for everything
            _db_dirs = {}
        report_sources = {"db": 0, "json": 0}
        for report_path in sorted(_iter_analysis_report_files(root)):
            try:
                report = None
                if _db_dirs and os.path.realpath(report_path).startswith(clips_root_prefix):
                    clip_uuid = _db_dirs.get(os.path.basename(os.path.dirname(report_path)))
                    if clip_uuid:
                        try:
                            from src.utils import analysis_store as _analysis_store

                            report = _analysis_store.export_report(root, clip_uuid)
                        except Exception:  # noqa: BLE001 — fall back per-report
                            report = None
                if isinstance(report, dict):
                    report_sources["db"] += 1
                else:
                    report = _read_json(report_path)
                    report_sources["json"] += 1
                row_counts = _insert_analysis_report_into_index(conn, report_path, report, fts_enabled=fts_enabled)
                counts["clips"] += 1
                for key, value in row_counts.items():
                    counts[key] += value
            except Exception as exc:  # pragma: no cover - defensive for arbitrary user reports
                failed_reports.append({"path": report_path, "error": str(exc)})
        for key, value in counts.items():
            conn.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", (f"count.{key}", str(value)))
        conn.commit()
    finally:
        conn.close()

    for suffix in ("-wal", "-shm"):
        try:
            os.remove(f"{db_path}{suffix}")
        except OSError:
            pass
    os.replace(tmp_path, db_path)
    try:
        final_conn = sqlite3.connect(db_path)
        final_conn.execute("PRAGMA journal_mode=WAL")
        final_conn.close()
    except sqlite3.Error:
        pass
    try:
        registry_status = update_analysis_registry(root)
    except Exception as exc:  # pragma: no cover - registry is an auxiliary cache
        registry_status = {"success": False, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "success": True,
        "project_root": root,
        "index_path": db_path,
        "schema_version": ANALYSIS_INDEX_SCHEMA_VERSION,
        "built_at": built_at,
        "single_user": True,
        "image_blob_policy": "excluded",
        "fts_enabled": bool(counts["clips"]) and _sqlite_table_exists(db_path, "clips_fts"),
        "counts": counts,
        "report_sources": report_sources,  # how many reports came from the DB vs JSON
        "failed_report_count": len(failed_reports),
        "failed_reports": failed_reports[:50],
        "size_bytes": os.path.getsize(db_path) if os.path.isfile(db_path) else 0,
        "analysis_registry": registry_status,
    }


def _sqlite_table_exists(db_path: str, table_name: str) -> bool:
    if not os.path.isfile(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = ? LIMIT 1",
                (table_name,),
            ).fetchone()
            return bool(row)
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _analysis_index_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    counts = {}
    for table in (
        "clips",
        "technical_warnings",
        "markers",
        "transcript_segments",
        "visual_tags",
        "timeline_occurrences",
        "analysis_keyframes",
    ):
        try:
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.Error:
            counts[table] = 0
    return counts


def analysis_index_status(project_root: str, *, index_path: Optional[Any] = None) -> Dict[str, Any]:
    root = normalize_path(project_root)
    db_path, err = _analysis_index_path(root, index_path)
    if err or not db_path:
        return {"success": False, "error": err}
    if not os.path.isfile(db_path):
        return {
            "success": True,
            "exists": False,
            "project_root": root,
            "index_path": db_path,
            "hint": "Persisted analysis builds this automatically; run media_analysis(action='build_index') to rebuild from existing reports.",
        }
    conn = sqlite3.connect(db_path)
    try:
        metadata = {
            row[0]: row[1]
            for row in conn.execute("SELECT key, value FROM index_metadata")
        }
        counts = _analysis_index_counts(conn)
    finally:
        conn.close()
    return {
        "success": True,
        "exists": True,
        "project_root": root,
        "index_path": db_path,
        "schema_version": int(metadata.get("schema_version") or 0),
        "analysis_version": metadata.get("analysis_version"),
        "built_at": metadata.get("built_at"),
        "single_user": True,
        "image_blob_policy": metadata.get("image_blob_policy") or "excluded",
        "fts_enabled": metadata.get("fts_enabled") == "1",
        "counts": counts,
        "size_bytes": os.path.getsize(db_path),
    }


def _fts_query(value: Any) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", str(value or ""))
    return " OR ".join(f'"{token}"' for token in tokens[:12])


def _row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _normalize_index_result_types(result_types: Optional[Iterable[str]]) -> set:
    if result_types in (None, ""):
        return set()
    if isinstance(result_types, str):
        raw_items = [result_types]
    else:
        raw_items = list(result_types)
    allowed_values = {"clip", "marker", "transcript"}
    return {
        str(value).strip().lower()
        for value in raw_items
        if str(value).strip().lower() in allowed_values
    }


def _query_analysis_index_fts(conn: sqlite3.Connection, query: str, limit: int, result_types: Optional[Iterable[str]]) -> List[Dict[str, Any]]:
    fts = _fts_query(query)
    if not fts:
        return []
    allowed = _normalize_index_result_types(result_types)
    results: List[Dict[str, Any]] = []
    # FTS5 snippet() builds an excerpt around the match with marker tokens around
    # the matched terms. We use sentinel braces here (NOT HTML) and convert them
    # to <mark> tags on the client; this keeps the raw SQL output safe to pass
    # through escapeHtml on the way to the DOM.
    SNIP_START = "[[hi]]"
    SNIP_END = "[[/hi]]"
    SNIP_ELLIPSIS = "…"
    SNIP_TOKENS = 24
    if not allowed or "clip" in allowed:
        for row in conn.execute(
            f"""
            SELECT
                'clip' AS result_type,
                c.clip_key,
                c.clip_id,
                c.media_id,
                c.clip_name,
                c.file_path,
                c.summary,
                snippet(clips_fts, -1, '{SNIP_START}', '{SNIP_END}', '{SNIP_ELLIPSIS}', {SNIP_TOKENS}) AS snippet,
                c.report_path,
                NULL AS marker_type,
                NULL AS start_seconds,
                NULL AS end_seconds,
                bm25(clips_fts) AS rank
            FROM clips_fts
            JOIN clips c ON c.clip_key = clips_fts.clip_key
            WHERE clips_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts, limit),
        ):
            results.append(_row_dict(row))
    if not allowed or "marker" in allowed:
        for row in conn.execute(
            f"""
            SELECT
                'marker' AS result_type,
                c.clip_key,
                c.clip_id,
                c.media_id,
                c.clip_name,
                c.file_path,
                m.visual_description AS summary,
                snippet(markers_fts, -1, '{SNIP_START}', '{SNIP_END}', '{SNIP_ELLIPSIS}', {SNIP_TOKENS}) AS snippet,
                c.report_path,
                m.marker_type,
                m.start_seconds,
                m.end_seconds,
                bm25(markers_fts) AS rank
            FROM markers_fts
            JOIN markers m ON m.id = markers_fts.marker_rowid
            JOIN clips c ON c.clip_key = m.clip_key
            WHERE markers_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts, limit),
        ):
            results.append(_row_dict(row))
    if not allowed or "transcript" in allowed:
        for row in conn.execute(
            f"""
            SELECT
                'transcript' AS result_type,
                c.clip_key,
                c.clip_id,
                c.media_id,
                c.clip_name,
                c.file_path,
                s.text AS summary,
                snippet(transcripts_fts, -1, '{SNIP_START}', '{SNIP_END}', '{SNIP_ELLIPSIS}', {SNIP_TOKENS}) AS snippet,
                c.report_path,
                NULL AS marker_type,
                s.start_seconds,
                s.end_seconds,
                bm25(transcripts_fts) AS rank
            FROM transcripts_fts
            JOIN transcript_segments s ON s.id = transcripts_fts.segment_rowid
            JOIN clips c ON c.clip_key = s.clip_key
            WHERE transcripts_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts, limit),
        ):
            results.append(_row_dict(row))
    results.sort(key=lambda row: (float(row.get("rank") or 0.0), row.get("result_type") or ""))
    return results[:limit]


def _query_analysis_index_like(conn: sqlite3.Connection, query: str, limit: int, result_types: Optional[Iterable[str]]) -> List[Dict[str, Any]]:
    needle = f"%{str(query or '').lower()}%"
    allowed = _normalize_index_result_types(result_types)
    results: List[Dict[str, Any]] = []
    if not allowed or "clip" in allowed:
        for row in conn.execute(
            """
            SELECT
                'clip' AS result_type,
                clip_key, clip_id, media_id, clip_name, file_path, summary, report_path,
                NULL AS marker_type, NULL AS start_seconds, NULL AS end_seconds, 0.0 AS rank
            FROM clips
            WHERE lower(coalesce(clip_name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(file_path, '')) LIKE ?
            LIMIT ?
            """,
            (needle, limit),
        ):
            results.append(_row_dict(row))
    if not allowed or "marker" in allowed:
        for row in conn.execute(
            """
            SELECT
                'marker' AS result_type,
                c.clip_key, c.clip_id, c.media_id, c.clip_name, c.file_path,
                m.visual_description AS summary, c.report_path, m.marker_type,
                m.start_seconds, m.end_seconds, 0.0 AS rank
            FROM markers m
            JOIN clips c ON c.clip_key = m.clip_key
            WHERE lower(
                coalesce(m.name, '') || ' ' || coalesce(m.visual_description, '') || ' ' ||
                coalesce(m.sound_note, '') || ' ' || coalesce(m.transcript_text, '')
            ) LIKE ?
            LIMIT ?
            """,
            (needle, limit),
        ):
            results.append(_row_dict(row))
    if not allowed or "transcript" in allowed:
        for row in conn.execute(
            """
            SELECT
                'transcript' AS result_type,
                c.clip_key, c.clip_id, c.media_id, c.clip_name, c.file_path,
                s.text AS summary, c.report_path, NULL AS marker_type,
                s.start_seconds, s.end_seconds, 0.0 AS rank
            FROM transcript_segments s
            JOIN clips c ON c.clip_key = s.clip_key
            WHERE lower(s.text) LIKE ?
            LIMIT ?
            """,
            (needle, limit),
        ):
            results.append(_row_dict(row))
    return results[:limit]


def query_analysis_index(
    project_root: str,
    query: Any,
    *,
    limit: Any = 20,
    result_types: Optional[Iterable[str]] = None,
    index_path: Optional[Any] = None,
) -> Dict[str, Any]:
    root = normalize_path(project_root)
    db_path, err = _analysis_index_path(root, index_path)
    if err or not db_path:
        return {"success": False, "error": err}
    if not os.path.isfile(db_path):
        return {"success": False, "error": f"Analysis index not found: {db_path}", "index_path": db_path}
    try:
        max_results = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        max_results = 20
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        has_fts = _sqlite_table_exists(db_path, "clips_fts")
        if _index_text(query):
            try:
                results = _query_analysis_index_fts(conn, str(query), max_results, result_types) if has_fts else []
            except sqlite3.Error:
                results = []
            if not results:
                results = _query_analysis_index_like(conn, str(query), max_results, result_types)
        else:
            results = [
                _row_dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        'clip' AS result_type,
                        clip_key, clip_id, media_id, clip_name, file_path, summary, report_path,
                        NULL AS marker_type, NULL AS start_seconds, NULL AS end_seconds, 0.0 AS rank
                    FROM clips
                    ORDER BY analyzed_at DESC, clip_name
                    LIMIT ?
                    """,
                    (max_results,),
                )
            ]
    finally:
        conn.close()
    return {
        "success": True,
        "project_root": root,
        "index_path": db_path,
        "query": query,
        "limit": max_results,
        "result_count": len(results),
        "results": results,
    }
