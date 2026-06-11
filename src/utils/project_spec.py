"""Declarative project spec — "kubectl apply" for a Resolve project.

A `project.dvr.yaml` (or .json) describes the *desired* project: settings, color
preset, timelines, markers, and optional before/after hooks. `plan_spec` diffs
the desired state against live state and emits an ordered `Action` list **without
mutating**; `apply_spec` executes that plan through an injected executor.

Separation of concerns so it unit-tests without Resolve:
  - load_spec / validation / plan_spec  → pure (dicts + dataclasses)
  - apply_spec                          → orchestrator over an injected executor
                                          (the server provides a live executor;
                                          tests provide a fake one)

Structure adapted from the MIT-licensed `mhadifilms/dvr` `spec.py`/`apply`:
SETTINGS_ORDER (color framework before dependent keys), preset-merge (explicit
settings override the named preset), marker idempotency, and error accumulation.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.utils import structural_diff


# ── Color presets ────────────────────────────────────────────────────────────
# Minimal, real starting set. Explicit `settings:` in the spec override these.
COLOR_PRESETS: Dict[str, Dict[str, str]] = {
    "rec709_gamma24": {
        "colorScienceMode": "davinciYRGBColorManagedv2",
        "colorSpaceTimeline": "Rec.709 (Scene)",
        "colorSpaceOutput": "Rec.709 Gamma 2.4",
    },
    "rec2020_pq_4000": {
        "colorScienceMode": "davinciYRGBColorManagedv2",
        "colorSpaceTimeline": "Rec.2020",
        "colorSpaceOutput": "Rec.2020 ST2084 (4000 nits)",
        "hdrMasteringLuminanceMax": "4000",
    },
    "aces_cct": {
        "colorScienceMode": "acescct",
        "colorAcesIDT": "ACES",
        "colorAcesODT": "Rec.709",
    },
}

# Keys applied first (in this relative order) so the color framework is enabled
# before dependent input/output/HDR keys. Everything not listed is applied after.
SETTINGS_ORDER: List[str] = [
    "colorScienceMode",
    "rcmPresetMode",
    "colorVersion",
    "colorAcesIDT",
    "colorAcesNodeLUTProcessingSpace",
    "colorAcesODT",
    "colorSpaceInput",
    "colorSpaceTimeline",
    "colorSpaceOutput",
    "hdrMasteringLuminanceMax",
]


# ── Dataclasses ──────────────────────────────────────────────────────────────
@dataclass
class TimelineSpec:
    name: str
    fps: Optional[float] = None
    settings: Dict[str, str] = field(default_factory=dict)
    markers: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Hook:
    when: str          # "before" | "after"
    command: str
    name: str = ""


@dataclass
class Spec:
    project: str
    color_preset: Optional[str] = None
    settings: Dict[str, str] = field(default_factory=dict)
    bins: List[str] = field(default_factory=list)
    timelines: List[TimelineSpec] = field(default_factory=list)
    hooks: List[Hook] = field(default_factory=list)


@dataclass
class Action:
    op: str            # create | ensure | set | noop
    target: str        # "project:Show", "timeline:Edit_v2/setting:timelineFrameRate", ...
    detail: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"op": self.op, "target": self.target, "detail": self.detail, "payload": self.payload}


class SpecError(Exception):
    """Raised on malformed spec or accumulated apply failures.

    Carries `state` so the server can surface it in the structured error envelope.
    """

    def __init__(self, message: str, *, state: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.state = state or {}


# ── Loading & validation ─────────────────────────────────────────────────────
def _parse_hooks(raw: Any) -> List[Hook]:
    hooks: List[Hook] = []
    if not raw:
        return hooks
    for when in ("before", "after"):
        for entry in (raw.get(when) or []) if isinstance(raw, dict) else []:
            if isinstance(entry, str):
                hooks.append(Hook(when=when, command=entry))
            elif isinstance(entry, dict) and entry.get("command"):
                hooks.append(Hook(when=when, command=str(entry["command"]), name=str(entry.get("name", ""))))
            else:
                raise SpecError(f"Invalid {when}-hook entry: {entry!r}")
    return hooks


def spec_from_dict(data: Dict[str, Any]) -> Spec:
    """Validate a plain dict into a `Spec`. Raises `SpecError` on bad shape."""
    if not isinstance(data, dict):
        raise SpecError("Spec must be a mapping at the top level.")
    project = data.get("project")
    if not project or not isinstance(project, str):
        raise SpecError("Spec requires a non-empty string `project`.", state={"got": data.get("project")})

    preset = data.get("color_preset")
    if preset is not None and preset not in COLOR_PRESETS:
        raise SpecError(
            f"Unknown color_preset '{preset}'.",
            state={"known_presets": sorted(COLOR_PRESETS)},
        )

    settings = data.get("settings") or {}
    if not isinstance(settings, dict):
        raise SpecError("`settings` must be a mapping.")

    bins: List[str] = []
    for raw_bin in data.get("bins") or []:
        if isinstance(raw_bin, str) and raw_bin.strip():
            bin_path = raw_bin.strip().strip("/")
        elif isinstance(raw_bin, dict) and raw_bin.get("path"):
            bin_path = str(raw_bin["path"]).strip().strip("/")
        else:
            raise SpecError(f"Each bin needs a non-empty path: {raw_bin!r}")
        # Live bin paths are always reported Master-prefixed; normalize here so
        # an unprefixed spec bin doesn't read as a perpetually-pending change.
        if bin_path != "Master" and not bin_path.startswith("Master/"):
            bin_path = f"Master/{bin_path}"
        bins.append(bin_path)

    timelines: List[TimelineSpec] = []
    for raw_tl in (data.get("timelines") or []):
        if not isinstance(raw_tl, dict) or not raw_tl.get("name"):
            raise SpecError(f"Each timeline needs a `name`: {raw_tl!r}")
        timelines.append(TimelineSpec(
            name=str(raw_tl["name"]),
            fps=float(raw_tl["fps"]) if raw_tl.get("fps") is not None else None,
            settings=dict(raw_tl.get("settings") or {}),
            markers=list(raw_tl.get("markers") or []),
        ))

    return Spec(
        project=str(project),
        color_preset=preset,
        settings={str(k): str(v) for k, v in settings.items()},
        bins=bins,
        timelines=timelines,
        hooks=_parse_hooks(data.get("hooks")),
    )


def load_spec(path: str) -> Spec:
    """Load a spec from a YAML or JSON file. YAML needs PyYAML; JSON always works."""
    if not os.path.isfile(path):
        raise SpecError(f"Spec file not found: {path}", state={"path": path})
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    data: Any
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise SpecError(
                "PyYAML is required to load .yaml specs (pip install pyyaml), "
                "or provide the spec as .json.",
                state={"path": path},
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return spec_from_dict(data)


# ── Effective settings (preset merge + ordering) ─────────────────────────────
def effective_settings(spec: Spec) -> "Dict[str, str]":
    """Preset settings overlaid by explicit spec.settings (explicit wins)."""
    merged: Dict[str, str] = {}
    if spec.color_preset:
        merged.update(COLOR_PRESETS[spec.color_preset])
    merged.update(spec.settings)
    return merged


def _ordered_setting_keys(keys: List[str]) -> List[str]:
    head = [k for k in SETTINGS_ORDER if k in keys]
    tail = sorted(k for k in keys if k not in SETTINGS_ORDER)
    return head + tail


def _norm_setting_value(value: Any) -> str:
    """Canonicalize a setting value for comparison. Resolve reports numeric
    settings with float formatting (e.g. timelineFrameRate -> "24.0") even when
    the spec says "24"; normalize both so reconcile actually converges (and apply
    is idempotent). Non-numeric values are returned as plain strings."""
    s = str(value)
    try:
        f = float(s)
    except (TypeError, ValueError):
        return s
    return str(int(f)) if f == int(f) else repr(f)


def _settings_equal(a: Any, b: Any) -> bool:
    return _norm_setting_value(a) == _norm_setting_value(b)


# ── Plan ─────────────────────────────────────────────────────────────────────
def plan_spec(spec: Spec, live: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the ordered action list + a structural diff. PURE — no mutation.

    `live` is the current state:
        {"project": str|None, "projects": [names],
         "settings": {k: v},
         "timelines": [{"name", "fps", "settings": {...}, "markers": [{frame,...}]}]}
    """
    live = live or {}
    actions: List[Action] = []

    # Project
    known = set(live.get("projects") or [])
    if spec.project in known or live.get("project") == spec.project:
        actions.append(Action("noop", f"project:{spec.project}", "exists"))
    else:
        actions.append(Action("create", f"project:{spec.project}", "create project"))

    # Project settings (preset-merged, dependency-ordered)
    live_settings = live.get("settings") or {}
    desired = effective_settings(spec)
    for key in _ordered_setting_keys(list(desired)):
        want = desired[key]
        if _settings_equal(live_settings.get(key, ""), want):
            actions.append(Action("noop", f"project:{spec.project}/setting:{key}", "matches"))
        else:
            actions.append(Action(
                "set", f"project:{spec.project}/setting:{key}",
                f"{live_settings.get(key)!r} -> {want!r}", {"key": key, "value": want},
            ))

    # Media Pool bins. Paths are slash-delimited from Master, e.g.
    # "Master/Media/Scene_01"; creation is idempotent in the executor.
    live_bins = set(live.get("bins") or [])
    for bin_path in spec.bins:
        if bin_path in live_bins:
            actions.append(Action("noop", f"bin:{bin_path}", "exists"))
        else:
            actions.append(Action("ensure", f"bin:{bin_path}", "ensure media-pool bin", {"path": bin_path}))

    # Timelines + their settings + markers. NOTE: `fps` is a *creation-time*
    # property handled by ensure_timeline — Resolve refuses SetSetting on
    # timelineFrameRate after a timeline exists — so it is never emitted as a
    # per-timeline `set` action.
    live_tls = {tl.get("name"): tl for tl in (live.get("timelines") or [])}
    for tl in spec.timelines:
        live_tl = live_tls.get(tl.name)
        if live_tl is None:
            actions.append(Action("ensure", f"timeline:{tl.name}", "create timeline",
                                   {"fps": tl.fps}))
        else:
            actions.append(Action("noop", f"timeline:{tl.name}", "exists"))

        live_tl_settings = (live_tl or {}).get("settings") or {}
        for key in _ordered_setting_keys(list(tl.settings)):
            want = tl.settings[key]
            if _settings_equal(live_tl_settings.get(key, ""), want):
                actions.append(Action("noop", f"timeline:{tl.name}/setting:{key}", "matches"))
            else:
                actions.append(Action("set", f"timeline:{tl.name}/setting:{key}",
                                       f"{live_tl_settings.get(key)!r} -> {want!r}",
                                       {"key": key, "value": want}))

        live_frames = {m.get("frame") for m in ((live_tl or {}).get("markers") or [])}
        for marker in tl.markers:
            frame = marker.get("frame")
            if frame in live_frames:
                actions.append(Action("noop", f"timeline:{tl.name}/marker:{frame}", "exists"))
            else:
                actions.append(Action("set", f"timeline:{tl.name}/marker:{frame}",
                                       "add marker", {"marker": marker}))

    diff = structural_diff.compare(
        _spec_normalized_state(live, spec),
        _spec_desired_state(spec),
        left_label="live", right_label="spec",
    )
    return {
        "actions": [a.to_dict() for a in actions],
        "diff": diff.to_dict(),
        "change_count": sum(1 for a in actions if a.op != "noop"),
    }


def _spec_desired_state(spec: Spec) -> Dict[str, Any]:
    return {
        "project": spec.project,
        "settings": {k: _norm_setting_value(v) for k, v in effective_settings(spec).items()},
        "bins": list(spec.bins),
        "timelines": [
            {
                "name": tl.name,
                "settings": {k: _norm_setting_value(v) for k, v in tl.settings.items()},
                "markers": [{"frame": m.get("frame"), **{k: v for k, v in m.items() if k != "frame"}}
                            for m in tl.markers],
            }
            for tl in spec.timelines
        ],
    }


def _spec_normalized_state(live: Dict[str, Any], spec: Spec) -> Dict[str, Any]:
    """Project live state onto only the keys the spec cares about, so the diff
    reports drift toward the spec rather than every unrelated live setting.
    Values are normalized so numeric formatting (24 vs 24.0) is not a phantom
    diff."""
    desired = effective_settings(spec)
    live_settings = live.get("settings") or {}
    spec_tl_names = {tl.name for tl in spec.timelines}
    live_tls = {tl.get("name"): tl for tl in (live.get("timelines") or [])}
    return {
        "project": live.get("project"),
        "settings": {k: _norm_setting_value(live_settings.get(k)) for k in desired if k in live_settings},
        "bins": [path for path in (live.get("bins") or []) if path in set(spec.bins)],
        "timelines": [
            {
                "name": name,
                "settings": {k: _norm_setting_value((live_tls[name].get("settings") or {}).get(k))
                             for k in (next((t.settings for t in spec.timelines if t.name == name), {}))
                             if k in (live_tls[name].get("settings") or {})},
                "markers": live_tls[name].get("markers") or [],
            }
            for name in spec_tl_names if name in live_tls
        ],
    }


# ── Apply (orchestrator over an injected executor) ───────────────────────────
def apply_spec(
    spec: Spec,
    executor: Any,
    *,
    dry_run: bool = False,
    run_hooks: bool = False,
    continue_on_error: bool = False,
    run_hook: Optional[Callable[[Hook], Any]] = None,
) -> Dict[str, Any]:
    """Reconcile live state toward `spec` through `executor`.

    `executor` is duck-typed; it must provide:
        live_state() -> dict
        ensure_project(name) -> bool
        set_project_setting(key, value) -> bool
        ensure_timeline(name, fps) -> bool
        set_timeline_setting(timeline_name, key, value) -> bool
        add_marker(timeline_name, marker: dict) -> bool
        ensure_bin(path) -> bool

    Hooks execute only when `run_hooks=True` AND a `run_hook` callable is given —
    arbitrary shell from a spec stays opt-in. Failures accumulate when
    `continue_on_error`; otherwise the first failure raises `SpecError`.
    """
    live = executor.live_state()
    plan = plan_spec(spec, live)
    if dry_run:
        return {"success": True, "dry_run": True, **plan}

    failures: List[Dict[str, Any]] = []
    applied: List[Dict[str, Any]] = []

    def _record(ok: bool, target: str, detail: str = "") -> None:
        entry = {"target": target, "detail": detail}
        if ok:
            applied.append(entry)
        else:
            failures.append(entry)
            if not continue_on_error:
                raise SpecError(
                    f"apply failed at {target}",
                    state={"project": spec.project, "failures": failures, "applied": applied},
                )

    befores = [h for h in spec.hooks if h.when == "before"]
    afters = [h for h in spec.hooks if h.when == "after"]

    if run_hooks and run_hook:
        for h in befores:
            _record(bool(run_hook(h)), f"hook:before:{h.name or h.command}")

    # Project + settings
    _record(bool(executor.ensure_project(spec.project)), f"project:{spec.project}")
    desired = effective_settings(spec)
    for key in _ordered_setting_keys(list(desired)):
        if _settings_equal((live.get("settings") or {}).get(key, ""), desired[key]):
            continue
        _record(bool(executor.set_project_setting(key, desired[key])),
                f"project:{spec.project}/setting:{key}", str(desired[key]))

    for bin_path in spec.bins:
        _record(bool(executor.ensure_bin(bin_path)), f"bin:{bin_path}")

    # Timelines. `fps` is creation-time only (ensure_timeline); never set as a
    # post-creation timelineFrameRate setting — Resolve refuses that.
    live_tls = {tl.get("name"): tl for tl in (live.get("timelines") or [])}
    for tl in spec.timelines:
        _record(bool(executor.ensure_timeline(tl.name, tl.fps)), f"timeline:{tl.name}")
        live_tl_settings = (live_tls.get(tl.name) or {}).get("settings") or {}
        for key in _ordered_setting_keys(list(tl.settings)):
            if _settings_equal(live_tl_settings.get(key, ""), tl.settings[key]):
                continue
            _record(bool(executor.set_timeline_setting(tl.name, key, tl.settings[key])),
                    f"timeline:{tl.name}/setting:{key}", str(tl.settings[key]))
        live_frames = {m.get("frame") for m in ((live_tls.get(tl.name) or {}).get("markers") or [])}
        for marker in tl.markers:
            if marker.get("frame") in live_frames:
                continue
            _record(bool(executor.add_marker(tl.name, marker)),
                    f"timeline:{tl.name}/marker:{marker.get('frame')}")

    if run_hooks and run_hook:
        for h in afters:
            _record(bool(run_hook(h)), f"hook:after:{h.name or h.command}")

    return {
        "success": not failures,
        "applied_count": len(applied),
        "applied": applied,
        "failures": failures,
        "project": spec.project,
    }
