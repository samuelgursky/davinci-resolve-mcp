"""Project health lint — a graded pre-flight the brain runs before editing.

Composes a plain *state* dict (gathered live by the MCP adapter from existing
probes) into a list of graded `Issue`s. Pure and Resolve-free so it unit-tests
against hand-built state.

The state dict shape (all keys optional; absence is itself a signal):
    {
      "project": str | None,
      "current_timeline": str | None,
      "timelines": [{"name": str, "fps": float|None, "item_count": int}, ...],
      "settings": {<key>: <value>},          # project settings
      "render": {"format": str|None, "codec": str|None},
      "offline_media_count": int,             # clips referencing missing files
      "unanalyzed_clip_count": int,           # media-pool clips w/o analysis record
    }

Inspired by the MIT `mhadifilms/dvr` `lint.py` check set; extended with our
analysis-aware checks (offline media, unanalyzed clips).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

SEVERITIES = ("error", "warning", "info")


@dataclass
class Issue:
    severity: str   # error | warning | info
    code: str
    message: str
    target: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.target:
            out["target"] = self.target
        if self.detail:
            out["detail"] = self.detail
        return out


def _color_science_unset(settings: Dict[str, Any]) -> bool:
    # Resolve reports "davinciYRGB" (managed off) when color science is the
    # default; ACES / managed modes set a different colorScienceMode.
    mode = str(settings.get("colorScienceMode", "")).strip()
    return mode in ("", "davinciYRGB")


def _timeline_has_items(timeline: Dict[str, Any]) -> bool:
    if int(timeline.get("item_count") or 0) > 0:
        return True
    for key in ("video_item_count", "audio_item_count", "subtitle_item_count"):
        if int(timeline.get(key) or 0) > 0:
            return True
    return False


def lint_state(state: Dict[str, Any]) -> List[Issue]:
    """Return graded issues for a project state dict, most-severe first."""
    issues: List[Issue] = []
    state = state or {}

    if not state.get("project"):
        issues.append(Issue("error", "no_project", "No project is open."))
        return issues  # nothing else is meaningful without a project

    timelines = state.get("timelines") or []
    if not state.get("current_timeline"):
        issues.append(Issue("warning", "no_current_timeline", "No timeline is active."))

    # mixed fps across timelines — a common conform foot-gun
    fps_values = {tl.get("fps") for tl in timelines if tl.get("fps") is not None}
    if len(fps_values) > 1:
        issues.append(Issue(
            "info", "mixed_fps",
            f"Timelines use {len(fps_values)} different frame rates.",
            detail=", ".join(str(f) for f in sorted(fps_values)),
        ))

    for tl in timelines:
        if not _timeline_has_items(tl):
            issues.append(Issue(
                "warning", "empty_timeline",
                f"Timeline '{tl.get('name')}' has no clips.",
                target=tl.get("name", ""),
            ))

    render = state.get("render") or {}
    if not render.get("format"):
        issues.append(Issue("info", "render_format_unset", "No render format is set."))

    settings = state.get("settings") or {}
    if _color_science_unset(settings):
        issues.append(Issue(
            "info", "color_science_unset",
            "Color science is unmanaged (DaVinci YRGB).",
            detail="Set a managed/ACES mode if a color-managed pipeline is expected.",
        ))

    offline = int(state.get("offline_media_count") or 0)
    if offline > 0:
        issues.append(Issue(
            "error", "offline_media",
            f"{offline} clip(s) reference offline/missing media.",
        ))

    unanalyzed = int(state.get("unanalyzed_clip_count") or 0)
    if unanalyzed > 0:
        issues.append(Issue(
            "info", "unanalyzed_clips",
            f"{unanalyzed} media-pool clip(s) have no analysis record.",
        ))

    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order.get(i.severity, 9))
    return issues


def lint_report(state: Dict[str, Any]) -> Dict[str, Any]:
    """Graded report envelope: counts + ok flag + serialized issues."""
    issues = lint_state(state)
    counts = {sev: sum(1 for i in issues if i.severity == sev) for sev in SEVERITIES}
    return {
        "ok": counts["error"] == 0,
        "counts": counts,
        "issues": [i.to_dict() for i in issues],
    }
