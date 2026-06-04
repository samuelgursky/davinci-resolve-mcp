"""Soft governance tiers for the Resolve 21 media-creating AI ops.

The two media-creating ops (`remove_motion_blur`, `generate_speech`) render new
files on Resolve's GPU/AI engine. They are already confirm-token gated, so
governance here is intentionally **advisory**: it reads the AI-ops ledger for the
current session and reports how the *next* run sits against a named tier's soft
thresholds. The result is surfaced in the confirm preview and the control panel —
it never hard-blocks (the analysis-caps layer meters Claude tokens; this is a
different, local concern).

Tiers (per session):

| dimension                 | off  | lenient | standard | strict |
|---------------------------|-----:|--------:|---------:|-------:|
| deblur_runs               | None | 50      | 15       | 5      |
| speech_runs               | None | 50      | 15       | 5      |
| render_bytes (new media)  | None | 50 GB   | 10 GB    | 2 GB   |
| render_wall_clock_ms       | None | 1 h     | 20 min   | 5 min  |

`standard` is the default. Only the render ops are governed; analysis ops
(classify / IntelliSearch / slate / transcribe) are always within-tier.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.utils import resolve_ai_ledger

logger = logging.getLogger("resolve-mcp.resolve-ai-governance")

TIER_OFF = "off"
TIER_LENIENT = "lenient"
TIER_STANDARD = "standard"
TIER_STRICT = "strict"
DEFAULT_TIER = TIER_STANDARD

_GB = 1024 ** 3

# dimension -> value (None = uncapped)
TIERS: Dict[str, Dict[str, Optional[int]]] = {
    TIER_OFF: {
        "deblur_runs": None, "speech_runs": None,
        "render_bytes": None, "render_wall_clock_ms": None,
    },
    TIER_LENIENT: {
        "deblur_runs": 50, "speech_runs": 50,
        "render_bytes": 50 * _GB, "render_wall_clock_ms": 60 * 60 * 1000,
    },
    TIER_STANDARD: {
        "deblur_runs": 15, "speech_runs": 15,
        "render_bytes": 10 * _GB, "render_wall_clock_ms": 20 * 60 * 1000,
    },
    TIER_STRICT: {
        "deblur_runs": 5, "speech_runs": 5,
        "render_bytes": 2 * _GB, "render_wall_clock_ms": 5 * 60 * 1000,
    },
}

VALID_TIERS = frozenset(TIERS)

_OVERRIDE_KEYS = frozenset({"deblur_runs", "speech_runs", "render_bytes", "render_wall_clock_ms"})

# Which ledger op feeds which run-count dimension.
_OP_RUN_DIM = {
    "remove_motion_blur": "deblur_runs",
    "generate_speech": "speech_runs",
}

GOVERNED_OPS = frozenset(_OP_RUN_DIM)


def list_tiers() -> Dict[str, Dict[str, Optional[int]]]:
    return {name: dict(vals) for name, vals in TIERS.items()}


def resolve_tier(preset: Optional[str] = None, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return the effective thresholds dict for `preset` with `overrides` applied.

    An override value of None / "unlimited" means uncapped on that dimension.
    """
    name = (preset or DEFAULT_TIER).strip().lower()
    if name not in TIERS:
        name = DEFAULT_TIER
    effective = dict(TIERS[name])
    if isinstance(overrides, dict):
        for key, val in overrides.items():
            if key not in _OVERRIDE_KEYS:
                continue
            if val is None or (isinstance(val, str) and val.strip().lower() == "unlimited"):
                effective[key] = None
            else:
                try:
                    effective[key] = int(val)
                except (TypeError, ValueError):
                    continue
    return {"preset": name, "thresholds": effective}


def _render_usage(project_root: str, session_id: Optional[str]) -> Dict[str, int]:
    """Aggregate this session's render-op usage from the ledger."""
    summary = resolve_ai_ledger.get_summary(project_root=project_root, session_id=session_id)
    by_op = summary.get("by_op", {})
    deblur = by_op.get("remove_motion_blur", {})
    speech = by_op.get("generate_speech", {})
    render_bytes = (deblur.get("bytes_created", 0) or 0) + (speech.get("bytes_created", 0) or 0)
    render_ms = (deblur.get("wall_clock_ms", 0) or 0) + (speech.get("wall_clock_ms", 0) or 0)
    return {
        "deblur_runs": deblur.get("runs", 0) or 0,
        "speech_runs": speech.get("runs", 0) or 0,
        "render_bytes": render_bytes,
        "render_wall_clock_ms": render_ms,
    }


def check(
    *,
    project_root: Optional[str],
    session_id: Optional[str],
    op: str,
    preset: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Advisory governance status for the NEXT run of `op`.

    Returns {applies, exceeded, near, tier, thresholds, usage, projected, warnings}.
    `applies` is False for non-render ops (no governance) or missing project_root.
    `exceeded` is True if the projected run-count is over the tier's run cap, or a
    cumulative dimension (bytes/time) is already over. `near` is True at >=80%.
    Never blocks — purely informational.
    """
    resolved = resolve_tier(preset, overrides)
    base = {
        "applies": False,
        "exceeded": False,
        "near": False,
        "tier": resolved["preset"],
        "thresholds": resolved["thresholds"],
        "usage": {},
        "projected": {},
        "warnings": [],
    }
    if op not in GOVERNED_OPS or not project_root:
        return base
    thresholds = resolved["thresholds"]
    usage = _render_usage(project_root, session_id)
    run_dim = _OP_RUN_DIM[op]
    projected = dict(usage)
    projected[run_dim] = usage[run_dim] + 1  # this run adds one

    warnings: List[str] = []
    exceeded = False
    near = False

    def _assess(dim: str, value: int, label: str, fmt) -> None:
        nonlocal exceeded, near
        cap = thresholds.get(dim)
        if cap is None:
            return
        if value > cap:
            exceeded = True
            warnings.append(f"{label}: {fmt(value)} exceeds the {resolved['preset']} limit of {fmt(cap)}.")
        elif value >= cap * 0.8:
            near = True
            warnings.append(f"{label}: {fmt(value)} is approaching the {resolved['preset']} limit of {fmt(cap)}.")

    def _fmt_bytes(n: int) -> str:
        if not n:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        v = float(n)
        i = 0
        while v >= 1024 and i < len(units) - 1:
            v /= 1024
            i += 1
        return f"{v:.1f} {units[i]}"

    def _fmt_min(ms: int) -> str:
        return f"{ms / 60000:.1f} min"

    _assess(run_dim, projected[run_dim], "Runs this session", str)
    _assess("render_bytes", usage["render_bytes"], "Media created this session", _fmt_bytes)
    _assess("render_wall_clock_ms", usage["render_wall_clock_ms"], "Render time this session", _fmt_min)

    base.update({
        "applies": True,
        "exceeded": exceeded,
        "near": near,
        "usage": usage,
        "projected": projected,
        "warnings": warnings,
    })
    return base


def status(
    *,
    project_root: Optional[str],
    session_id: Optional[str],
    preset: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Current session render usage vs the effective tier (for the panel/MCP)."""
    resolved = resolve_tier(preset, overrides)
    usage = _render_usage(project_root, session_id) if project_root else {
        "deblur_runs": 0, "speech_runs": 0, "render_bytes": 0, "render_wall_clock_ms": 0,
    }
    return {
        "tier": resolved["preset"],
        "thresholds": resolved["thresholds"],
        "usage": usage,
        "tiers_available": list_tiers(),
    }
