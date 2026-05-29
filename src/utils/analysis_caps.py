"""Analysis cap layer — token budgets, frame caps, response trimming.

Six cap dimensions, each with named presets (minimal/standard/generous/unlimited)
and per-field overrides. Caps are advisory at the call site: the analysis
pipeline consults `check_budget()` before vision/transcription calls and
`record_usage()` after; over-budget calls return a `BudgetDecision` with
`allowed=False` and the caller is expected to surface a clean error rather
than silently spending money.

Budgets are tracked in `analysis_token_usage` (schema v5 in
`timeline_brain_db.py`), scoped per-clip / per-job / per-day. The day_bucket
column makes per-day rollups one indexed scan.

Pricing-to-USD conversion is intentionally NOT in this module — the spec
deferred a "$ cost cap" axis. Token budgets are the unit of currency here.

## Preset rationale

| Dimension | minimal | standard | generous | unlimited |
|-----------|--------:|---------:|---------:|----------:|
| response_chars                | 5,000   | 25,000     | 100,000    | None |
| vision_tokens_per_clip        | 16,000  | 100,000    | 250,000    | None |
| frames_per_clip               | 12      | 80         | 200        | None |
| vision_tokens_per_job         | 60,000  | 1,000,000  | 3,000,000  | None |
| vision_tokens_per_day         | 150,000 | 2,000,000  | 6,000,000  | None |
| wall_clock_seconds_per_call   | 30      | 90         | 300        | None |
| max_frame_dim_pixels          | 512     | 768        | 1280       | None |

`minimal` = preview/triage mode. `standard` = realistic per-project default.
`generous` = high-fidelity analysis on a few specific clips. `unlimited` = all
guards off; use only when you're certain about the input size.

NOTE on `frames_per_clip`: this is a *safety ceiling*, not the primary frame
dial. How many frames a clip actually gets is chosen by the `sampling_mode`
(Economy/Balanced/Thorough — see media_analysis.SAMPLING_MODES), which is
duration- and content-aware. `frames_per_clip` only clips the result if the mode
would exceed it. The standard ceiling (80) matches the default Thorough ceiling
so the mode is never silently truncated; lower it to hard-cap cost, raise it for
unusually long/cutty clips. (Before sampling modes existed this defaulted to 8
and *was* the frame dial — that flat cap is what made long clips under-covered.)
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, List, Optional

from src.utils import timeline_brain_db

logger = logging.getLogger("resolve-mcp.analysis-caps")

PRESET_MINIMAL = "minimal"
PRESET_STANDARD = "standard"
PRESET_GENEROUS = "generous"
PRESET_UNLIMITED = "unlimited"
DEFAULT_PRESET = PRESET_STANDARD

SCOPE_CLIP = "clip"
SCOPE_JOB = "job"
SCOPE_DAY = "day"
SCOPE_SESSION = "session"


@dataclass(frozen=True)
class Caps:
    """Effective cap values. `None` means uncapped on that dimension."""
    response_chars: Optional[int]
    vision_tokens_per_clip: Optional[int]
    frames_per_clip: Optional[int]
    vision_tokens_per_job: Optional[int]
    vision_tokens_per_day: Optional[int]
    wall_clock_seconds_per_call: Optional[int]
    max_frame_dim_pixels: Optional[int]
    preset: str = DEFAULT_PRESET

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


CAP_PRESETS: Dict[str, Caps] = {
    PRESET_MINIMAL: Caps(
        preset=PRESET_MINIMAL,
        response_chars=5_000,
        vision_tokens_per_clip=16_000,
        frames_per_clip=12,
        vision_tokens_per_job=60_000,
        vision_tokens_per_day=150_000,
        wall_clock_seconds_per_call=30,
        max_frame_dim_pixels=512,
    ),
    PRESET_STANDARD: Caps(
        preset=PRESET_STANDARD,
        response_chars=25_000,
        vision_tokens_per_clip=100_000,
        frames_per_clip=80,
        vision_tokens_per_job=1_000_000,
        vision_tokens_per_day=2_000_000,
        wall_clock_seconds_per_call=90,
        max_frame_dim_pixels=768,
    ),
    PRESET_GENEROUS: Caps(
        preset=PRESET_GENEROUS,
        response_chars=100_000,
        vision_tokens_per_clip=250_000,
        frames_per_clip=200,
        vision_tokens_per_job=3_000_000,
        vision_tokens_per_day=6_000_000,
        wall_clock_seconds_per_call=300,
        max_frame_dim_pixels=1280,
    ),
    PRESET_UNLIMITED: Caps(
        preset=PRESET_UNLIMITED,
        response_chars=None,
        vision_tokens_per_clip=None,
        frames_per_clip=None,
        vision_tokens_per_job=None,
        vision_tokens_per_day=None,
        wall_clock_seconds_per_call=None,
        max_frame_dim_pixels=None,
    ),
}

VALID_PRESETS = frozenset(CAP_PRESETS)

_OVERRIDE_KEYS = frozenset({
    "response_chars",
    "vision_tokens_per_clip",
    "frames_per_clip",
    "vision_tokens_per_job",
    "vision_tokens_per_day",
    "wall_clock_seconds_per_call",
    "max_frame_dim_pixels",
})


# ── Public API: preset resolution ────────────────────────────────────────────


def resolve_caps(
    preset: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Caps:
    """Materialise the effective Caps for a given preset + optional overrides.

    Unknown preset falls back to standard (logged as warning). Override values:
    integers replace the preset value; `None` or "unlimited" lifts the cap on
    that dimension; unknown keys are ignored (logged at debug).
    """
    preset_key = (preset or DEFAULT_PRESET).strip().lower()
    if preset_key not in VALID_PRESETS:
        logger.warning("unknown preset '%s', falling back to %s", preset, DEFAULT_PRESET)
        preset_key = DEFAULT_PRESET
    base = CAP_PRESETS[preset_key]

    if not overrides:
        return base

    patch: Dict[str, Any] = {}
    for key, raw in overrides.items():
        if key not in _OVERRIDE_KEYS:
            logger.debug("ignoring unknown cap override: %s", key)
            continue
        if raw is None or (isinstance(raw, str) and raw.strip().lower() == "unlimited"):
            patch[key] = None
            continue
        try:
            patch[key] = int(raw)
        except (TypeError, ValueError):
            logger.debug("ignoring non-integer cap override %s=%r", key, raw)
            continue
    return replace(base, **patch) if patch else base


def list_presets() -> Dict[str, Dict[str, Any]]:
    """Render every preset as a plain dict (for dashboard + MCP introspection)."""
    return {key: caps.to_dict() for key, caps in CAP_PRESETS.items()}


# ── Public API: budget enforcement ───────────────────────────────────────────


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: Optional[str]  # e.g. "over_clip_cap", "over_job_cap", "over_day_cap"
    current_usage: Dict[str, int]
    cap: Dict[str, Optional[int]]
    headroom: Dict[str, Optional[int]]  # remaining tokens per scope; None if uncapped


def _day_bucket(when: Optional[float] = None) -> str:
    t = when if when is not None else time.time()
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def _iso(when: Optional[float] = None) -> str:
    t = when if when is not None else time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _sum_usage(
    conn,
    *,
    scope: str,
    scope_key: Optional[str] = None,
    day_bucket: Optional[str] = None,
) -> Dict[str, int]:
    clauses: List[str] = ["scope = ?"]
    args: List[Any] = [scope]
    if scope_key is not None:
        clauses.append("scope_key = ?")
        args.append(scope_key)
    if day_bucket is not None:
        clauses.append("day_bucket = ?")
        args.append(day_bucket)
    where = " AND ".join(clauses)
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(vision_tokens), 0) AS vision,
               COALESCE(SUM(transcription_tokens), 0) AS transcription,
               COALESCE(SUM(frames_uploaded), 0) AS frames,
               COALESCE(SUM(wall_clock_ms), 0) AS wall_clock_ms
        FROM analysis_token_usage
        WHERE {where}
        """,
        args,
    ).fetchone()
    return {
        "vision_tokens": int(row["vision"] or 0),
        "transcription_tokens": int(row["transcription"] or 0),
        "frames_uploaded": int(row["frames"] or 0),
        "wall_clock_ms": int(row["wall_clock_ms"] or 0),
    }


def check_budget(
    *,
    project_root: str,
    caps: Caps,
    estimated_vision_tokens: int = 0,
    clip_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> BudgetDecision:
    """Would adding `estimated_vision_tokens` exceed any active cap?

    Checks the three cumulative budgets: per-clip, per-job, per-day. If any is
    over (or would go over with this call), returns `allowed=False` with the
    reason. Uncapped dimensions never block.
    """
    conn = timeline_brain_db.connect(project_root)
    day = _day_bucket()

    clip_usage = (
        _sum_usage(conn, scope=SCOPE_CLIP, scope_key=clip_id)
        if clip_id else {"vision_tokens": 0, "transcription_tokens": 0, "frames_uploaded": 0, "wall_clock_ms": 0}
    )
    job_usage = (
        _sum_usage(conn, scope=SCOPE_JOB, scope_key=job_id)
        if job_id else {"vision_tokens": 0, "transcription_tokens": 0, "frames_uploaded": 0, "wall_clock_ms": 0}
    )
    day_usage = _sum_usage(conn, scope=SCOPE_DAY, day_bucket=day)

    def _check(usage_value: int, cap_value: Optional[int]) -> Optional[int]:
        if cap_value is None:
            return None
        return cap_value - usage_value

    cap_map = {
        "clip": caps.vision_tokens_per_clip,
        "job": caps.vision_tokens_per_job,
        "day": caps.vision_tokens_per_day,
    }
    headroom = {
        "clip": _check(clip_usage["vision_tokens"], caps.vision_tokens_per_clip),
        "job": _check(job_usage["vision_tokens"], caps.vision_tokens_per_job),
        "day": _check(day_usage["vision_tokens"], caps.vision_tokens_per_day),
    }

    # Identify the most-binding constraint. Order: clip → job → day so the
    # smallest scope reports first.
    for scope_key in ("clip", "job", "day"):
        remaining = headroom[scope_key]
        if remaining is None:
            continue
        if remaining - estimated_vision_tokens < 0:
            return BudgetDecision(
                allowed=False,
                reason=f"over_{scope_key}_cap",
                current_usage={
                    "clip_vision_tokens": clip_usage["vision_tokens"],
                    "job_vision_tokens": job_usage["vision_tokens"],
                    "day_vision_tokens": day_usage["vision_tokens"],
                },
                cap=cap_map,
                headroom=headroom,
            )

    return BudgetDecision(
        allowed=True,
        reason=None,
        current_usage={
            "clip_vision_tokens": clip_usage["vision_tokens"],
            "job_vision_tokens": job_usage["vision_tokens"],
            "day_vision_tokens": day_usage["vision_tokens"],
        },
        cap=cap_map,
        headroom=headroom,
    )


def record_usage(
    *,
    project_root: str,
    scope: str,
    scope_key: Optional[str],
    vision_tokens: int = 0,
    transcription_tokens: int = 0,
    frames_uploaded: int = 0,
    wall_clock_ms: int = 0,
    preset: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a token-usage row. Called after every vision/transcription call.

    Insert under each applicable scope. A single call typically writes 2 rows:
    one under `clip` (so per-clip caps are accurate) and one under `day` (so
    cross-clip rollups are accurate). When a job_id is in play, also write
    under `job`. Use separate calls for each scope; this function writes ONE
    row per call.
    """
    if scope not in (SCOPE_CLIP, SCOPE_JOB, SCOPE_DAY, SCOPE_SESSION):
        raise ValueError(f"unknown scope: {scope}")
    now = time.time()
    with timeline_brain_db.transaction(project_root) as txn:
        cursor = txn.execute(
            """
            INSERT INTO analysis_token_usage(
                scope, scope_key, vision_tokens, transcription_tokens,
                frames_uploaded, wall_clock_ms, preset_at_call,
                occurred_at, day_bucket
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scope, scope_key, int(vision_tokens), int(transcription_tokens),
                int(frames_uploaded), int(wall_clock_ms), preset,
                _iso(now), _day_bucket(now),
            ),
        )
        row_id = cursor.lastrowid
    return {"success": True, "row_id": row_id}


def record_usage_all_scopes(
    *,
    project_root: str,
    clip_id: Optional[str] = None,
    job_id: Optional[str] = None,
    vision_tokens: int = 0,
    transcription_tokens: int = 0,
    frames_uploaded: int = 0,
    wall_clock_ms: int = 0,
    preset: Optional[str] = None,
) -> Dict[str, Any]:
    """Record the same usage under every applicable scope in one call.

    Always writes a `day` row. Writes a `clip` row if clip_id is provided, a
    `job` row if job_id is provided. Atomicity is per-row — partial failure on
    one scope still records the others.
    """
    rows: List[Dict[str, Any]] = []
    rows.append(record_usage(
        project_root=project_root, scope=SCOPE_DAY, scope_key=None,
        vision_tokens=vision_tokens, transcription_tokens=transcription_tokens,
        frames_uploaded=frames_uploaded, wall_clock_ms=wall_clock_ms, preset=preset,
    ))
    if clip_id:
        rows.append(record_usage(
            project_root=project_root, scope=SCOPE_CLIP, scope_key=clip_id,
            vision_tokens=vision_tokens, transcription_tokens=transcription_tokens,
            frames_uploaded=frames_uploaded, wall_clock_ms=wall_clock_ms, preset=preset,
        ))
    if job_id:
        rows.append(record_usage(
            project_root=project_root, scope=SCOPE_JOB, scope_key=job_id,
            vision_tokens=vision_tokens, transcription_tokens=transcription_tokens,
            frames_uploaded=frames_uploaded, wall_clock_ms=wall_clock_ms, preset=preset,
        ))
    return {"success": True, "rows": rows}


def get_current_usage(
    *,
    project_root: str,
    scope: str = SCOPE_DAY,
    scope_key: Optional[str] = None,
    day_bucket: Optional[str] = None,
) -> Dict[str, int]:
    """Rollup query for the dashboard / get_usage MCP action."""
    conn = timeline_brain_db.connect(project_root)
    day = day_bucket if scope == SCOPE_DAY else None
    return _sum_usage(conn, scope=scope, scope_key=scope_key, day_bucket=day)


def log_caps_event(
    *,
    project_root: str,
    event_type: str,
    reason: Optional[str] = None,
    preset: Optional[str] = None,
    estimated_vision_tokens: int = 0,
    current_usage: Optional[Dict[str, Any]] = None,
    cap: Optional[Dict[str, Any]] = None,
    headroom: Optional[Dict[str, Any]] = None,
    clip_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a caps event row (refusal / timeout / etc) for dashboard visibility."""
    import json as _json
    now = time.time()
    with timeline_brain_db.transaction(project_root) as txn:
        cursor = txn.execute(
            """
            INSERT INTO caps_events(
                event_type, reason, preset, estimated_vision_tokens,
                current_usage_json, cap_json, headroom_json,
                clip_id, job_id, occurred_at, day_bucket
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type, reason, preset, int(estimated_vision_tokens),
                _json.dumps(current_usage) if current_usage else None,
                _json.dumps(cap) if cap else None,
                _json.dumps(headroom) if headroom else None,
                clip_id, job_id, _iso(now), _day_bucket(now),
            ),
        )
        row_id = cursor.lastrowid
    return {"success": True, "row_id": row_id}


def get_caps_events(
    *,
    project_root: str,
    event_type: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Most-recent-first caps events for the dashboard."""
    import json as _json
    conn = timeline_brain_db.connect(project_root)
    if event_type:
        rows = conn.execute(
            """
            SELECT * FROM caps_events WHERE event_type = ?
            ORDER BY id DESC LIMIT ?
            """,
            (event_type, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM caps_events ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for key in ("current_usage_json", "cap_json", "headroom_json"):
            raw = d.pop(key)
            d[key[:-5]] = _json.loads(raw) if raw else None
        out.append(d)
    return out


def get_usage_history(
    *,
    project_root: str,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Per-day vision token totals over the past `days` days. Newest first."""
    conn = timeline_brain_db.connect(project_root)
    rows = conn.execute(
        """
        SELECT day_bucket,
               COALESCE(SUM(vision_tokens), 0) AS vision_tokens,
               COALESCE(SUM(transcription_tokens), 0) AS transcription_tokens,
               COALESCE(SUM(frames_uploaded), 0) AS frames_uploaded,
               COALESCE(SUM(wall_clock_ms), 0) AS wall_clock_ms
        FROM analysis_token_usage
        WHERE scope = 'day'
        GROUP BY day_bucket
        ORDER BY day_bucket DESC
        LIMIT ?
        """,
        (int(days),),
    ).fetchall()
    return [dict(r) for r in rows]


def reset_day_usage(
    *,
    project_root: str,
    day_bucket: Optional[str] = None,
) -> Dict[str, Any]:
    """Delete day-scope usage rows for the given day (default today). Returns count deleted."""
    day = day_bucket or _day_bucket()
    with timeline_brain_db.transaction(project_root) as txn:
        cursor = txn.execute(
            "DELETE FROM analysis_token_usage WHERE scope = 'day' AND day_bucket = ?",
            (day,),
        )
        deleted = cursor.rowcount
    return {"success": True, "day_bucket": day, "deleted": deleted}


def get_usage_rollup(
    *,
    project_root: str,
    caps: Caps,
    clip_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Combined snapshot of usage vs caps across all three cumulative scopes."""
    day = _day_bucket()
    clip_usage = get_current_usage(project_root=project_root, scope=SCOPE_CLIP, scope_key=clip_id) if clip_id else None
    job_usage = get_current_usage(project_root=project_root, scope=SCOPE_JOB, scope_key=job_id) if job_id else None
    day_usage = get_current_usage(project_root=project_root, scope=SCOPE_DAY, day_bucket=day)

    def _percent(used: int, cap: Optional[int]) -> Optional[float]:
        if cap is None or cap == 0:
            return None
        return round(min(100.0, 100.0 * used / cap), 1)

    return {
        "preset": caps.preset,
        "caps": caps.to_dict(),
        "usage": {
            "clip": clip_usage,
            "job": job_usage,
            "day": day_usage,
        },
        "percent_consumed": {
            "clip": _percent(clip_usage["vision_tokens"], caps.vision_tokens_per_clip) if clip_usage else None,
            "job": _percent(job_usage["vision_tokens"], caps.vision_tokens_per_job) if job_usage else None,
            "day": _percent(day_usage["vision_tokens"], caps.vision_tokens_per_day),
        },
    }


# ── Response payload trimming ────────────────────────────────────────────────


def trim_response_payload(payload: Any, max_chars: Optional[int]) -> Any:
    """Truncate a JSON-serialisable payload so its string repr fits under max_chars.

    Strategy:
    1. If under cap or uncapped → return as-is.
    2. Recursively trim the largest list/string fields first (transcripts,
       frame_paths, segments) until under cap.
    3. Add a `_trimmed` marker dict so consumers can see what got dropped.
    """
    if max_chars is None:
        return payload

    import json
    raw = json.dumps(payload, default=str)
    if len(raw) <= max_chars:
        return payload
    if not isinstance(payload, dict):
        # Non-dict payloads: stringify + truncate.
        return raw[: max_chars - 32] + "…[truncated]"

    trimmed = dict(payload)
    drops: List[str] = []

    # 1) Drop very large list-valued keys first (in priority order).
    LARGE_KEYS = ("transcript_segments", "frame_paths", "sampled_frames", "segments", "tokens")
    for key in LARGE_KEYS:
        if key in trimmed:
            value = trimmed[key]
            if isinstance(value, list) and len(value) > 4:
                trimmed[key] = value[:4] + [{"_trimmed_count": len(value) - 4}]
                drops.append(f"{key}[{len(value) - 4} omitted]")
            elif isinstance(value, str) and len(value) > 1000:
                trimmed[key] = value[:1000] + "…[trimmed]"
                drops.append(f"{key}[len={len(value)}]")
            raw = json.dumps(trimmed, default=str)
            if len(raw) <= max_chars:
                break

    # 2) If still over, drop any long string values left.
    if len(raw) > max_chars:
        for key, value in list(trimmed.items()):
            if isinstance(value, str) and len(value) > 500:
                trimmed[key] = value[:500] + "…[trimmed]"
                drops.append(f"{key}[len={len(value)}]")
                raw = json.dumps(trimmed, default=str)
                if len(raw) <= max_chars:
                    break

    # 3) Last resort: stringify and truncate.
    if len(raw) > max_chars:
        return raw[: max_chars - 64] + "…[response cap hit; raw truncated]"

    if drops:
        trimmed["_trimmed"] = {
            "reason": "response_chars cap",
            "max_chars": max_chars,
            "fields": drops,
        }
    return trimmed


# ── Wall-clock timeout helper ────────────────────────────────────────────────


class WallClockTimeout(Exception):
    """Raised when a wrapped call exceeds caps.wall_clock_seconds_per_call."""


def run_with_timeout(fn, timeout_seconds: Optional[float], *args, **kwargs):
    """Run `fn` with a wall-clock timeout. Uses a thread + Event for portability.

    Returns whatever `fn` returns. Raises WallClockTimeout if elapsed > cap.
    Pass `timeout_seconds=None` (or 0) to disable. Accepts fractional seconds
    (handy in tests). The thread keeps running after timeout (we can't kill
    threads in Python); callers should treat the timed-out call as zombie and
    not wait for cleanup.
    """
    if timeout_seconds is None or timeout_seconds <= 0:
        return fn(*args, **kwargs)
    import threading
    result: Dict[str, Any] = {}
    err: Dict[str, BaseException] = {}

    def _target():
        try:
            result["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            err["exc"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        raise WallClockTimeout(f"call exceeded {timeout_seconds}s wall-clock cap")
    if "exc" in err:
        raise err["exc"]
    return result.get("value")


# ── Frame downscale helper ──────────────────────────────────────────────────


def downscale_frame_if_needed(image_path: str, max_dim: Optional[int]) -> str:
    """Downscale `image_path` in place if either dimension > max_dim.

    Uses PIL if available; silently no-ops if Pillow isn't installed (the
    analysis pipeline degrades to original-resolution uploads). Returns the
    path (may be the same path if not modified).
    """
    if max_dim is None or max_dim <= 0:
        return image_path
    try:
        from PIL import Image as PILImage
    except ImportError:
        logger.debug("Pillow not installed — frame downscale skipped")
        return image_path
    try:
        with PILImage.open(image_path) as img:
            w, h = img.size
            if w <= max_dim and h <= max_dim:
                return image_path
            img.thumbnail((max_dim, max_dim), PILImage.LANCZOS)
            img.save(image_path)
        logger.debug("downscaled %s from %dx%d to fit %dpx", image_path, w, h, max_dim)
    except Exception as exc:
        logger.debug("frame downscale failed for %s: %s", image_path, exc)
    return image_path
