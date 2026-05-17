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
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.utils.sync_detection import detect_sync_event_capabilities


ANALYSIS_DIR_NAME = "davinci-resolve-mcp-analysis"
HIDDEN_ANALYSIS_DIR_NAME = ".davinci-resolve-mcp-analysis"
ANALYSIS_VERSION = "0.1"
ANALYSIS_INDEX_FILENAME = "index.sqlite"
ANALYSIS_INDEX_SCHEMA_VERSION = 1
COMMAND_TIMEOUT_SECONDS = 300
CHAT_CONTEXT_VISION_PROVIDERS = {"chat_context", "mcp_sampling", "host_chat", "current_chat"}
MARKER_PLAN_DEFAULT_COLORS = {
    "shot": "Blue",
    "best_moment": "Green",
    "qc_warning": "Red",
    "black_or_title": "Red",
}

DEFAULT_VISION_ANALYSIS_PROMPT = """Return only strict JSON for editorial media analysis.

Use the full sequence of sampled keyframes plus the computed motion/variance
and cut-boundary evidence. Describe what changes across the clip; do not treat
one frame as the whole clip unless only one frame was provided. When frames are
tagged shot_start, shot_end, cut_before, or cut_after, explicitly compare the
adjacent boundary frames and say whether they look like a real cut, a flash
frame, a title/black insertion, or a high-motion moment inside one continuous
shot. If a slate or clapper is visible in any sampled frame, confirm it in the
slate block and extract only clearly readable details. Do not infer slate fields
from audio cues alone.

Use this schema:
{
  "success": true,
  "provider": "chat_context",
  "clip_summary": "One concise natural-language summary of the full clip evidence.",
  "editorial_classification": {
    "primary_use": "b-roll|interview|action|establishing|detail|screen|unknown",
    "select_potential": "low|medium|high",
    "reason": "Why this clip may or may not be useful editorially."
  },
  "content": {
    "locations": [],
    "people_visible": "none|one|multiple|unknown",
    "actions": [],
    "objects": [],
    "visible_text": [],
    "notable_audio_context": []
  },
  "shot_and_style": {
    "shot_sizes": [],
    "camera_motion": [],
    "composition_notes": "",
    "lighting_mood": "",
    "color_mood": ""
  },
  "slate": {
    "slate_visible": false,
    "scene": "",
    "shot": "",
    "take": "",
    "camera": "",
    "roll": "",
    "date": "",
    "production": "",
    "visible_text": [],
    "confidence": {
      "overall": "low|medium|high",
      "scene": "low|medium|high",
      "shot": "low|medium|high",
      "take": "low|medium|high",
      "camera": "low|medium|high"
    }
  },
  "motion": {
    "overall_level": "low|medium|high|unknown",
    "motion_events": [],
    "quiet_regions": []
  },
  "cut_understanding": {
    "cut_count": 0,
    "likely_edited_sequence": false,
    "flash_frame_candidates": [],
    "notes": []
  },
  "analysis_keyframes": [
    {
      "time_seconds": 0.0,
      "selection_reason": "first_usable|midpoint|last_usable|scene_change|cut_before|cut_after|shot_start|shot_end|flash_candidate|motion_peak|interval",
      "description": "What is visible in this frame.",
      "editing_value": "How an editor might use this moment.",
      "qc_flags": []
    }
  ],
  "editing_notes": {
    "best_moments": [],
    "continuity_flags": [],
    "qc_flags": [],
    "search_tags": []
  },
  "confidence": {
    "visual": "low|medium|high",
    "motion": "computed",
    "transcript": "unavailable|provided"
  }
}
Do not include markdown fences, prose outside JSON, or keys outside this schema."""

DEPTHS = {"quick", "standard", "deep", "custom"}
DEFAULT_DEPTH = "standard"
FRAME_CAPS = {
    "quick": 0,
    "standard": 8,
    "deep": 24,
    "custom": 8,
}
HARD_FRAME_CAP = 48


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


def stable_clip_directory(record: Dict[str, Any]) -> str:
    basis = (
        record.get("clip_id")
        or record.get("media_id")
        or record.get("file_path")
        or record.get("clip_name")
        or "clip"
    )
    label = slugify(record.get("clip_name") or Path(str(record.get("file_path") or "clip")).stem, "clip")
    return f"{label}-{short_hash(basis, 12)}"


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


def detect_capabilities(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Detect available analysis helpers without installing or downloading."""
    env = env if env is not None else os.environ
    whisper_cli = shutil.which("whisper")
    whisper_cpp = shutil.which("whisper-cpp")
    mlx_whisper = importlib.util.find_spec("mlx_whisper") is not None
    cv2 = importlib.util.find_spec("cv2") is not None
    provider = env.get("DAVINCI_RESOLVE_MCP_VISION_PROVIDER")

    sync_events = detect_sync_event_capabilities()

    return {
        "success": True,
        "analysis_version": ANALYSIS_VERSION,
        "no_auto_install": True,
        "tools": {
            "ffprobe": {"available": bool(shutil.which("ffprobe")), "path": shutil.which("ffprobe")},
            "ffmpeg": {"available": bool(shutil.which("ffmpeg")), "path": shutil.which("ffmpeg")},
            "whisper_cli": {"available": bool(whisper_cli), "path": whisper_cli},
            "whisper_cpp": {"available": bool(whisper_cpp), "path": whisper_cpp},
            "mlx_whisper": {"available": bool(mlx_whisper), "python_module": "mlx_whisper"},
            "opencv": {"available": bool(cv2), "python_module": "cv2"},
        },
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
            "available": bool(provider),
            "provider": provider,
            "enabled_by_default": False,
            "note": (
                "Vision analysis is opt-in and requires a configured provider. "
                "The 'mock' provider is local-only for tests and never sends frames."
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
            "required_for": ["deep transcription analysis"],
            "options": [
                "Install/configure whisper CLI",
                "Install/configure whisper-cpp",
                "Install mlx-whisper on supported Apple Silicon systems",
            ],
            "note": "The MCP server must not install these automatically.",
        }
    if not tools.get("opencv", {}).get("available"):
        missing["opencv"] = {
            "required_for": ["optional optical-flow motion scoring"],
            "note": "OpenCV is optional; standard frame-difference motion scoring can work without it.",
        }
    if not caps.get("vision", {}).get("available"):
        missing["vision"] = {
            "required_for": ["LLM visual analysis"],
            "note": (
                "Prefer chat-context vision when the MCP client supports sampling/createMessage. "
                "If unavailable, ask the user whether to continue without visuals or provide setup "
                "steps for a supported vision path. Never send frames off-machine without explicit approval."
            ),
        }

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
) -> Dict[str, Any]:
    """Return the cache signature for a requested analysis profile."""
    transcription = options.get("transcription") or {}
    vision = options.get("vision") or {}
    marker_plan = options.get("marker_plan") or {}
    vision_prompt = vision.get("prompt") or DEFAULT_VISION_ANALYSIS_PROMPT
    return {
        "analysis_version": ANALYSIS_VERSION,
        "depth": depth,
        "analysis_keyframe_budget": int(frame_count or 0),
        "source_file": _source_file_signature(record.get("file_path")),
        "layers": {
            "technical": True,
            "readthrough": depth in {"standard", "deep", "custom"},
            "motion": depth in {"standard", "deep", "custom"},
            "transcription": {
                "enabled": _coerce_bool(transcription.get("enabled"), default=(depth == "deep")),
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
                "enabled": _coerce_bool(transcription.get("enabled"), default=(depth == "deep")),
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


def vision_uses_chat_context(options: Dict[str, Any], capabilities: Optional[Dict[str, Any]] = None) -> bool:
    vision = options.get("vision") or {}
    if not _coerce_bool(vision.get("enabled"), default=False):
        return False
    provider = vision.get("provider") or (capabilities or {}).get("vision", {}).get("provider")
    return provider in CHAT_CONTEXT_VISION_PROVIDERS


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
    clip_dir = normalize_path(os.path.join(project_root, "clips", stable_clip_directory(record)))
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
    if _coerce_bool(transcription.get("enabled"), default=(depth == "deep")):
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
    if _coerce_bool(transcription.get("enabled"), default=(depth == "deep")):
        backend = transcription.get("backend")
        if backend in {"mock", "local_mock"}:
            pass
        elif not capabilities.get("transcription", {}).get("available"):
            gaps.append({"capability": "transcription_backend", "required_for": ["transcription"]})

    vision = options.get("vision") or {}
    if _coerce_bool(vision.get("enabled"), default=False):
        provider = vision.get("provider") or capabilities.get("vision", {}).get("provider")
        if provider in {"mock", "local_mock"} or provider in CHAT_CONTEXT_VISION_PROVIDERS:
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
    transcription_enabled = _coerce_bool((options.get("transcription") or {}).get("enabled"), default=(depth == "deep"))
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
    for candidate_root in [reuse_project_root, *raw_reuse_project_roots]:
        if not candidate_root:
            continue
        normalized_root = normalize_path(candidate_root)
        if normalized_root not in reuse_project_roots:
            reuse_project_roots.append(normalized_root)

    clip_plans = []
    for record in records:
        artifacts = _artifact_paths(root["project_root"], record, depth, options)
        request_signature = analysis_request_signature(record, depth, options, frame_count)
        clip_plan = {
            "record": record,
            "analysis_keyframe_budget": frame_count,
            "analysis_signature": request_signature,
            "cache_status": "not_checked",
            "artifacts": artifacts,
        }
        if not reuse_existing:
            clip_plan["cache_status"] = "reuse_disabled"
        elif force_refresh:
            clip_plan["cache_status"] = "refresh_forced"
        else:
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
                clip_plan["existing_report"] = {
                    "path": existing.get("path"),
                    "reusable": existing.get("reusable", False),
                    "missing_layers": existing.get("missing_layers", []),
                    "cache_issues": existing.get("cache_issues", []),
                    "cache_warnings": existing.get("cache_warnings", []),
                    "analyzed_at": existing.get("analyzed_at"),
                    "project_root": existing.get("project_root"),
                }
                if existing.get("reusable"):
                    clip_plan["skip_execution"] = True
                    clip_plan["cache_status"] = "reusable"
                    if existing.get("project_root") and existing.get("project_root") != root["project_root"]:
                        clip_plan["reuse_reason"] = "Existing analysis report from a related project version satisfies the requested depth and modalities."
                    else:
                        clip_plan["reuse_reason"] = "Existing analysis report satisfies the requested depth and modalities."
                else:
                    clip_plan["cache_status"] = "stale_or_incomplete"
            else:
                clip_plan["cache_status"] = "miss"
        clip_plans.append(clip_plan)

    per_clip_seconds = {"quick": 2, "standard": 45, "deep": 180, "custom": 45}.get(depth, 45)
    reusable_count = sum(1 for clip in clip_plans if clip.get("skip_execution"))
    stale_count = sum(1 for clip in clip_plans if clip.get("cache_status") == "stale_or_incomplete")
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
        "reuse_existing": reuse_existing,
        "force_refresh": force_refresh,
        "reuse_policy": reuse_policy,
        "max_report_age_days": max_report_age_days,
        "reuse_project_root": reuse_project_root,
        "reuse_project_roots": reuse_project_roots,
        "reusable_clip_count": reusable_count,
        "stale_or_incomplete_clip_count": stale_count,
        "clips": clip_plans,
        "notes": notes,
    }


def _run_command(args: List[str], timeout: int = COMMAND_TIMEOUT_SECONDS) -> Tuple[int, str, str]:
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, path)


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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

    scene_code, scene_stderr = _ffmpeg_stderr_filter(path, video_filter="select='gt(scene,0.3)',showinfo")
    result["scenes"] = {
        "success": scene_code == 0,
        "items": _parse_scene_changes(scene_stderr),
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
        first_sample = _clamp_sample_time((start or 0.0) + frame_step, duration)
        if end is not None:
            last_sample = _clamp_sample_time(max(start or 0.0, end - frame_step), duration)
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


def _sample_times(
    duration: Optional[float],
    scene_items: List[Dict[str, Any]],
    budget: int,
    *,
    fps: Optional[float] = None,
    cut_analysis: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    if budget <= 0:
        return []
    duration = duration or 0
    candidates: List[Dict[str, Any]] = []

    def add(time_seconds: Optional[float], reason: str, priority: int, **extra: Any) -> None:
        if time_seconds is None:
            return
        candidates.append({
            "time_seconds": _clamp_sample_time(float(time_seconds), duration),
            "selection_reason": reason,
            "priority": priority,
            **extra,
        })

    if duration > 0:
        add(min(duration * 0.05, max(duration - 0.05, 0)), "first_usable", 6)
        add(duration * 0.5, "midpoint", 70)
        add(max(duration - min(duration * 0.05, 0.5), 0), "last_usable", 6)

    cut_analysis = cut_analysis if isinstance(cut_analysis, dict) else {}
    for cut in cut_analysis.get("cut_points") or []:
        if not isinstance(cut, dict):
            continue
        cut_index = cut.get("index")
        add(
            cut.get("before_time_seconds"),
            "cut_before",
            5,
            cut_index=cut_index,
            cut_time_seconds=cut.get("time_seconds"),
            boundary_role="last_frame_before_cut",
        )
        add(
            cut.get("after_time_seconds"),
            "cut_after",
            5,
            cut_index=cut_index,
            cut_time_seconds=cut.get("time_seconds"),
            boundary_role="first_frame_after_cut",
        )

    for shot in cut_analysis.get("shot_ranges") or []:
        if not isinstance(shot, dict):
            continue
        shot_index = shot.get("index")
        add(
            shot.get("first_sample_time_seconds"),
            "shot_start",
            12,
            shot_index=shot_index,
            shot_start=shot.get("start"),
            shot_end=shot.get("end"),
        )
        add(
            shot.get("last_sample_time_seconds"),
            "shot_end",
            12,
            shot_index=shot_index,
            shot_start=shot.get("start"),
            shot_end=shot.get("end"),
        )

    for flash in cut_analysis.get("flash_frame_candidates") or []:
        if not isinstance(flash, dict):
            continue
        add(
            flash.get("mid_sample_time_seconds"),
            "flash_candidate",
            4,
            shot_index=flash.get("index"),
            shot_start=flash.get("start"),
            shot_end=flash.get("end"),
        )

    for scene in scene_items[: max(budget, 1)]:
        t = scene.get("time_seconds")
        if isinstance(t, (int, float)) and t >= 0:
            add(float(t), "scene_change", 15)

    if duration > 0:
        interval_count = max(0, min(budget, 6) - 3)
        for index in range(interval_count):
            add(duration * ((index + 1) / (interval_count + 1)), "interval", 80)

    unique: List[Dict[str, Any]] = []
    seen = set()
    frame_step = _frame_step_seconds(fps)
    for candidate in sorted(candidates, key=lambda row: (int(row.get("priority", 99)), float(row.get("time_seconds") or 0.0))):
        rounded = round(max(float(candidate.get("time_seconds") or 0.0), 0), 3)
        key = round(rounded / max(frame_step, 0.001))
        if key in seen:
            continue
        seen.add(key)
        row = dict(candidate)
        row["time_seconds"] = rounded
        row.pop("priority", None)
        unique.append(row)
        if len(unique) >= budget:
            break
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
    proc = subprocess.run(args, capture_output=True, timeout=60, check=False)
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
        output_path,
    ], timeout=60)
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
) -> Dict[str, Any]:
    sampled = []
    previous_raw = None
    required_boundary_frames = 0
    if isinstance(cut_analysis, dict):
        required_boundary_frames += len(cut_analysis.get("cut_points") or []) * 2
        required_boundary_frames += len(cut_analysis.get("flash_frame_candidates") or [])
    effective_budget = max(int(budget or 0), min(HARD_FRAME_CAP, required_boundary_frames + 3))
    times = _sample_times(duration, scene_items, effective_budget, fps=fps, cut_analysis=cut_analysis)
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
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


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
    if _coerce_bool(transcription.get("enabled"), default=(depth == "deep")):
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
        matches.append({
            "path": path,
            "report": report,
            "missing_layers": missing,
            "cache_issues": cache_issues,
            "cache_warnings": cache_warnings,
            "analyzed_at": report.get("analyzed_at"),
            "analyzed_timestamp": _timestamp_from_analyzed_at(report.get("analyzed_at")) or 0,
        })
    if not matches:
        return None
    matches.sort(key=lambda row: (
        len(row["missing_layers"]) + len(row["cache_issues"]),
        -float(row.get("analyzed_timestamp") or 0),
    ))
    best = matches[0]
    if best["missing_layers"] or best["cache_issues"]:
        return {
            "path": best["path"],
            "missing_layers": best["missing_layers"],
            "cache_issues": best["cache_issues"],
            "cache_warnings": best["cache_warnings"],
            "analyzed_at": best.get("analyzed_at"),
            "reusable": False,
        }
    return {
        "path": best["path"],
        "missing_layers": [],
        "cache_issues": [],
        "cache_warnings": best["cache_warnings"],
        "analyzed_at": best.get("analyzed_at"),
        "reusable": True,
        "report": best["report"],
    }


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
    cmd = [
        whisper,
        path,
        "--model",
        str(transcription.get("model") or "base"),
        "--output_format",
        "json",
        "--output_dir",
        work_dir,
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
        word_timestamps=bool(transcription.get("word_timestamps", False)),
        verbose=False,
        **kwargs,
    )
    payload = _normalize_transcript_payload(raw, "mlx_whisper", transcription.get("language"))
    _write_transcript_artifacts(payload, artifacts)
    return payload


def _transcribe(path: str, artifacts: Dict[str, Any], options: Dict[str, Any], capabilities: Dict[str, Any]) -> Dict[str, Any]:
    transcription = options.get("transcription") or {}
    if not _coerce_bool(transcription.get("enabled"), default=False):
        return {"success": True, "status": "skipped", "reason": "transcription disabled"}
    backend = transcription.get("backend")
    if not backend:
        backends = capabilities.get("transcription", {}).get("backends") or []
        backend = backends[0] if backends else None
    if backend in {"mock", "local_mock"}:
        segments = transcription.get("segments") or [{"start": 0.0, "end": 1.0, "text": "Mock local transcript segment."}]
        payload = {"success": True, "backend": backend, "language": transcription.get("language", "unknown"), "segments": segments, "text": " ".join(s.get("text", "") for s in segments)}
        _write_transcript_artifacts(payload, artifacts)
        return payload
    elif backend in {"whisper_cli", "mlx_whisper"}:
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


def _vision_analysis(record: Dict[str, Any], motion: Dict[str, Any], options: Dict[str, Any], artifacts: Dict[str, Any], capabilities: Dict[str, Any]) -> Dict[str, Any]:
    vision = options.get("vision") or {}
    if not _coerce_bool(vision.get("enabled"), default=False):
        return {"success": True, "status": "skipped", "reason": "vision disabled"}
    provider = vision.get("provider") or capabilities.get("vision", {}).get("provider")
    if provider in CHAT_CONTEXT_VISION_PROVIDERS:
        return {
            "success": False,
            "status": "skipped",
            "provider": provider,
            "reason": "Chat-context vision requires MCP client sampling support for this tool call.",
        }
    if provider not in {"mock", "local_mock"}:
        return {
            "success": False,
            "status": "skipped",
            "provider": provider,
            "reason": "Only local mock vision is implemented in this offline pass; no frames were sent externally.",
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


def _visual_description_for_time(vision: Dict[str, Any], start: Optional[float], end: Optional[float]) -> str:
    keyframes = vision.get("analysis_keyframes") if isinstance(vision.get("analysis_keyframes"), list) else []
    midpoint = None
    if start is not None and end is not None:
        midpoint = (float(start) + float(end)) / 2.0
    elif start is not None:
        midpoint = float(start)
    best = None
    best_distance = None
    for keyframe in keyframes:
        if not isinstance(keyframe, dict):
            continue
        description = keyframe.get("description") or keyframe.get("visual_description")
        if not description:
            continue
        frame_time = _parse_float(keyframe.get("time_seconds"))
        distance = abs((frame_time or 0.0) - (midpoint or frame_time or 0.0))
        if best_distance is None or distance < best_distance:
            best = description
            best_distance = distance
    if best:
        return _trim_text(best, 360)
    if vision.get("clip_summary"):
        return _trim_text(vision.get("clip_summary"), 360)
    return "Visual description unavailable from this analysis pass."


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
        "write_to_resolve": False,
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
        sound_note, transcript_text = _marker_sound_note(transcript, readthrough, start, end)
        markers.append(_build_marker_entry(
            marker_id=f"shot-{int(shot['index']):03d}",
            marker_type="shot",
            color=color_scheme["shot"],
            name=f"Shot {int(shot['index']):03d}",
            start=start,
            end=end,
            fps=fps,
            visual_description=_visual_description_for_time(vision, start, end),
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
        "write_to_resolve_default": False,
        "resolve_marker_writeback": {
            "optional": True,
            "enabled": False,
            "write_action": "publish_clip_metadata",
            "required_flags": {"write_markers": True, "confirm": True, "dry_run": False},
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
            "transcription_enabled": _coerce_bool(((options or {}).get("transcription") or {}).get("enabled"), default=(depth == "deep")),
            "vision_enabled": _coerce_bool(((options or {}).get("vision") or {}).get("enabled"), default=False),
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
    if plan.get("capability_gaps"):
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
        "clips": [],
    }
    _write_json(os.path.join(output_root, "capabilities.json"), caps)

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
            clip_result.update({
                "success": True,
                "reused": True,
                "analysis_json": existing_report["path"],
                "reuse_reason": clip_plan.get("reuse_reason"),
                "cache_status": clip_plan.get("cache_status"),
                "cache_warnings": existing_report.get("cache_warnings", []),
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
            )
            if artifacts.get("motion_json"):
                _write_json(artifacts["motion_json"], motion)

        transcript = _transcribe(source, artifacts, options, caps)
        vision = await _maybe_run_vision_analysis(record, motion, options, artifacts, caps, vision_runner)
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
        _write_json(artifacts["analysis_json"], analysis)
        if _coerce_bool(params.get("cleanup_frames"), default=False) and artifacts.get("frames_dir"):
            shutil.rmtree(artifacts["frames_dir"], ignore_errors=True)
        clip_result.update({
            "success": True,
            "analysis_json": artifacts["analysis_json"],
            "marker_plan_json": artifacts.get("marker_plan_json"),
            "marker_count": marker_plan.get("marker_count"),
        })
        manifest["clips"].append(clip_result)

    manifest["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest["clip_count"] = len(manifest["clips"])
    manifest["successful_clip_count"] = sum(1 for row in manifest["clips"] if row.get("success"))

    if (
        not session_only
        and manifest["successful_clip_count"]
        and _coerce_bool(params.get("auto_build_index"), default=True)
    ):
        manifest["index"] = build_analysis_index(output_root)

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
    return asyncio.run(execute_plan_async(plan, params=params, capabilities=capabilities))


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


def summarize_reports(project_root: str) -> Dict[str, Any]:
    root = normalize_path(project_root)
    clips_root = os.path.join(root, "clips")
    reports = []
    if os.path.isdir(clips_root):
        for dirpath, _, filenames in os.walk(clips_root):
            if "analysis.json" in filenames:
                try:
                    reports.append(_read_json(os.path.join(dirpath, "analysis.json")))
                except (OSError, json.JSONDecodeError):
                    continue
    warnings = []
    motion_counts: Dict[str, int] = {}
    tags: Dict[str, int] = {}
    signed_report_count = 0
    newest_ts = 0.0
    for report in reports:
        if report.get("analysis_signature"):
            signed_report_count += 1
        analyzed_ts = _timestamp_from_analyzed_at(report.get("analyzed_at")) or 0
        newest_ts = max(newest_ts, analyzed_ts)
        warnings.extend(report.get("technical_warnings") or [])
        level = ((report.get("motion") or {}).get("overall_motion_level") or "unknown")
        motion_counts[level] = motion_counts.get(level, 0) + 1
        visual = report.get("visual") or {}
        editing_notes = visual.get("editing_notes") or {}
        for tag in editing_notes.get("search_tags") or []:
            tags[tag] = tags.get(tag, 0) + 1
    summary = {
        "success": True,
        "project_root": root,
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
    }
    _write_json(os.path.join(root, "project_summary.json"), summary)
    return summary


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
    clips_root = os.path.join(normalize_path(project_root), "clips")
    if not os.path.isdir(clips_root):
        return
    for dirpath, _, filenames in os.walk(clips_root):
        if "analysis.json" in filenames:
            yield os.path.join(dirpath, "analysis.json")


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
    seen = set()
    unique: List[Tuple[str, str]] = []
    for tag, source in tags:
        key = (tag.lower(), source)
        if key in seen:
            continue
        seen.add(key)
        unique.append((tag, source))
    return unique


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
    transcript_segments = transcription.get("segments") if isinstance(transcription.get("segments"), list) else []
    transcript_text = _index_text(transcription.get("text"))
    transcript_available = bool(transcript_text or transcript_segments)
    visual_available = bool(visual.get("success") and (visual.get("clip_summary") or visual_tags or visual.get("analysis_keyframes")))

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
        conn.execute(
            """
            INSERT INTO clips_fts (clip_key, clip_name, summary, file_path, tags, warnings)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                clip_key,
                clip.get("clip_name") or (os.path.basename(str(source_file)) if source_file else None),
                report.get("summary"),
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

        for report_path in sorted(_iter_analysis_report_files(root)):
            try:
                report = _read_json(report_path)
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
        "failed_report_count": len(failed_reports),
        "failed_reports": failed_reports[:50],
        "size_bytes": os.path.getsize(db_path) if os.path.isfile(db_path) else 0,
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
    if not allowed or "clip" in allowed:
        for row in conn.execute(
            """
            SELECT
                'clip' AS result_type,
                c.clip_key,
                c.clip_id,
                c.media_id,
                c.clip_name,
                c.file_path,
                c.summary,
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
            """
            SELECT
                'marker' AS result_type,
                c.clip_key,
                c.clip_id,
                c.media_id,
                c.clip_name,
                c.file_path,
                m.visual_description AS summary,
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
            """
            SELECT
                'transcript' AS result_type,
                c.clip_key,
                c.clip_id,
                c.media_id,
                c.clip_name,
                c.file_path,
                s.text AS summary,
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
