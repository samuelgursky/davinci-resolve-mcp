"""Memory and heartbeat layer for V2 analysis architecture.

Per the V2 shot schema spec §9 and the project_v2_architecture memory,
each project's analysis root carries narrative memory alongside the structured DB:

    {analysis_root}/memory/
        bin_summary.md          - Regenerated post-analysis: machine's first impression of the bin.
        session_notes/          - One file per chat session, dated.
        corrections.md          - Running log of what humans fixed and why.
        decisions.md            - Load-bearing conclusions reached together.

    {analysis_root}/heartbeat.json
        Current-state snapshot updated by the analysis pipeline:
        last run timestamp, clip counts, what's pending, recent failures,
        what's new since session N. Read at session start so the LLM walks in
        knowing what changed overnight.

The user-scoped Soul layer lives separately at ~/davinci-resolve-mcp/soul/
(see soul scaffolding in P5).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


MEMORY_DIR_NAME = "memory"
HEARTBEAT_FILENAME = "heartbeat.json"
BIN_SUMMARY_FILENAME = "bin_summary.md"
SESSION_NOTES_DIR_NAME = "session_notes"
CORRECTIONS_FILENAME = "corrections.md"
DECISIONS_FILENAME = "decisions.md"

# V2 B6: panel_state.json — shared state between chat and the control panel.
# Lives next to heartbeat.json at the project's analysis root. Either side can
# write; both read at session start. Single-user model, last-write-wins.
PANEL_STATE_FILENAME = "panel_state.json"
PANEL_STATE_SCHEMA_VERSION = "2.0"

HEARTBEAT_SCHEMA_VERSION = "2.0"

# ---- User-scoped soul layer (cross-project) ----
# Soul lives outside any specific project's analysis root, under a `_soul`
# directory sibling to project directories. The underscore prefix marks it
# as user-scoped, not a project. Cross-project continuity: when Sam starts a
# new project the soul still applies; per-project memory + DB are fresh.
SOUL_DIR_NAME = "_soul"
SOUL_PERSPECTIVE_FILENAME = "perspective.md"
SOUL_WORKING_STYLE_FILENAME = "working_style.md"
SOUL_LEARNED_FILENAME = "learned_from_corrections.md"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _today_date() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def memory_dir(project_root: str) -> str:
    return os.path.join(project_root, MEMORY_DIR_NAME)


def session_notes_dir(project_root: str) -> str:
    return os.path.join(memory_dir(project_root), SESSION_NOTES_DIR_NAME)


def heartbeat_path(project_root: str) -> str:
    return os.path.join(project_root, HEARTBEAT_FILENAME)


def bin_summary_path(project_root: str) -> str:
    return os.path.join(memory_dir(project_root), BIN_SUMMARY_FILENAME)


def corrections_path(project_root: str) -> str:
    return os.path.join(memory_dir(project_root), CORRECTIONS_FILENAME)


def decisions_path(project_root: str) -> str:
    return os.path.join(memory_dir(project_root), DECISIONS_FILENAME)


def ensure_memory_structure(project_root: str) -> Dict[str, Any]:
    """Create the memory directory structure if it doesn't exist. Idempotent."""
    created = []
    for d in (memory_dir(project_root), session_notes_dir(project_root)):
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            created.append(d)
    # Seed the long-running narrative files if absent
    for path, header in (
        (corrections_path(project_root), "# Corrections log\n\nRunning record of what was corrected, by whom, when, and why.\n\n"),
        (decisions_path(project_root), "# Decisions log\n\nLoad-bearing conclusions reached during work on this project.\n\n"),
    ):
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(header)
            created.append(path)
    return {
        "success": True,
        "project_root": project_root,
        "memory_dir": memory_dir(project_root),
        "session_notes_dir": session_notes_dir(project_root),
        "created": created,
    }


# ============ Heartbeat ============

def read_heartbeat(project_root: str) -> Optional[Dict[str, Any]]:
    """Read heartbeat.json. Returns None if it doesn't exist or is malformed."""
    path = heartbeat_path(project_root)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def write_heartbeat(project_root: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Write heartbeat.json atomically."""
    ensure_memory_structure(project_root)
    payload = dict(payload)
    payload.setdefault("schema_version", HEARTBEAT_SCHEMA_VERSION)
    payload["updated_at"] = _now_iso()
    path = heartbeat_path(project_root)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
        return {"success": True, "path": path}
    except OSError as exc:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def update_heartbeat(
    project_root: str,
    *,
    last_run: Optional[Dict[str, Any]] = None,
    clip_counts: Optional[Dict[str, int]] = None,
    pending: Optional[List[Dict[str, Any]]] = None,
    recent_failures: Optional[List[Dict[str, Any]]] = None,
    new_since_last_session: Optional[List[Dict[str, Any]]] = None,
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Update heartbeat fields, preserving keys not explicitly overridden."""
    existing = read_heartbeat(project_root) or {}
    payload = dict(existing)
    if last_run is not None:
        payload["last_run"] = last_run
    if clip_counts is not None:
        payload["clip_counts"] = clip_counts
    if pending is not None:
        payload["pending"] = pending
    if recent_failures is not None:
        payload["recent_failures"] = recent_failures
    if new_since_last_session is not None:
        payload["new_since_last_session"] = new_since_last_session
    if notes is not None:
        payload["notes"] = notes
    return write_heartbeat(project_root, payload)


# ============ Bin summary ============

def regenerate_bin_summary_from_manifest(
    project_root: str,
    manifest: Dict[str, Any],
    *,
    project_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Write bin_summary.md from a manifest's per-clip rows.

    V2.0 (this function): a smart aggregator that synthesizes a bin-level
    overview from per-clip summaries — clip counts, dominant editorial roles,
    top search_tags, recurring locations, select-potential distribution,
    energy arc, and a per-clip listing. It's NOT a vision-synthesized
    briefing yet.

    V2.1 (deferred): replace with a separate vision pass that reads all
    per-clip clip_summary fields + a representative frame per clip, and
    produces a true colleague-style briefing paragraph. See C2 in the
    gameplan; implementation pattern follows the per-clip vision flow
    (deferred payload + commit_bin_summary action).
    """
    ensure_memory_structure(project_root)
    clips = manifest.get("clips") or []
    project_name = project_name or manifest.get("project_name") or "(unknown project)"

    # Read per-clip analyses from disk so we can aggregate
    enriched: List[Dict[str, Any]] = []
    for clip in clips:
        info = {
            "record": clip.get("record") or {},
            "clip": clip,
            "report": None,
        }
        analysis_path = clip.get("analysis_json")
        if analysis_path and os.path.isfile(analysis_path):
            try:
                with open(analysis_path, "r", encoding="utf-8") as handle:
                    info["report"] = json.load(handle)
            except (OSError, json.JSONDecodeError):
                pass
        enriched.append(info)

    # Aggregate fields from the per-clip visual analyses
    primary_use_counts: Dict[str, int] = {}
    select_potential_counts: Dict[str, int] = {}
    style_counts: Dict[str, int] = {}
    energy_counts: Dict[str, int] = {}
    tag_counts: Dict[str, int] = {}
    location_counts: Dict[str, int] = {}
    total_duration = 0.0
    longest_clips: List[Tuple[float, str, Optional[str]]] = []
    high_select_clips: List[Tuple[str, str, Optional[str]]] = []
    pending_vision_count = 0

    def _bump(d: Dict[str, int], key: Optional[str]) -> None:
        if key:
            d[str(key)] = d.get(str(key), 0) + 1

    for info in enriched:
        record = info["record"]
        report = info["report"] or {}
        visual = report.get("visual") if isinstance(report.get("visual"), dict) else None
        duration = _extract_duration_seconds(record)
        total_duration += float(duration or 0.0)
        clip_name = record.get("clip_name") or "Untitled"
        clip_id = record.get("clip_id")
        if duration:
            longest_clips.append((float(duration), clip_name, clip_id))

        if visual is None:
            pending_vision_count += 1
            continue
        classification = visual.get("editorial_classification") or {}
        _bump(primary_use_counts, classification.get("primary_use"))
        _bump(select_potential_counts, classification.get("select_potential"))
        _bump(style_counts, classification.get("style"))
        _bump(energy_counts, classification.get("energy_arc"))
        if classification.get("select_potential") == "high":
            high_select_clips.append((clip_name, classification.get("primary_use") or "", clip_id))
        # Aggregate search tags
        editing_notes = visual.get("editing_notes") or {}
        for tag in (editing_notes.get("search_tags") or []):
            if isinstance(tag, str) and tag.strip():
                _bump(tag_counts, tag.strip().lower())
        # Aggregate locations from content if structured
        content = visual.get("content") or {}
        for loc in (content.get("locations") or []):
            if isinstance(loc, str) and loc.strip():
                _bump(location_counts, loc.strip())

    def _top(d: Dict[str, int], n: int = 5) -> List[Tuple[str, int]]:
        return sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:n]

    longest_clips.sort(reverse=True)
    top_5_longest = longest_clips[:5]

    # Build the markdown
    lines: List[str] = []
    lines.append(f"# Bin summary — {project_name}\n")
    lines.append(f"_Regenerated: {_now_iso()}_\n")
    lines.append("_(V2.0 aggregated overview; V2.1 will replace with a vision-synthesized colleague briefing — see C2 in the gameplan.)_\n\n")

    lines.append("## Overview\n\n")
    lines.append(f"- **Clip count**: {len(clips)}")
    if pending_vision_count:
        lines.append(f" ({pending_vision_count} pending vision)")
    lines.append("\n")
    lines.append(f"- **Total duration**: ~{_fmt_duration(total_duration)}\n")
    lines.append(f"- **Analysis schema version**: {manifest.get('analysis_version', 'unknown')}\n\n")

    if primary_use_counts:
        lines.append("## Editorial composition\n\n")
        lines.append("**Primary use:**\n\n")
        for use, n in _top(primary_use_counts, 10):
            lines.append(f"- {use}: {n}\n")
        lines.append("\n")

    if select_potential_counts:
        lines.append("**Select potential distribution:**\n\n")
        for level in ("high", "medium", "low"):
            if level in select_potential_counts:
                lines.append(f"- {level}: {select_potential_counts[level]}\n")
        lines.append("\n")

    if style_counts:
        lines.append("**Dominant style:**\n\n")
        for s, n in _top(style_counts, 5):
            lines.append(f"- {s}: {n}\n")
        lines.append("\n")

    if energy_counts:
        lines.append("**Energy arcs:**\n\n")
        for e, n in _top(energy_counts, 5):
            lines.append(f"- {e}: {n}\n")
        lines.append("\n")

    if tag_counts:
        lines.append("## Top tags\n\n")
        top_tags = _top(tag_counts, 20)
        lines.append("`" + "` `".join(f"{t} ({n})" for t, n in top_tags) + "`\n\n")

    if location_counts:
        lines.append("## Recurring locations\n\n")
        for loc, n in _top(location_counts, 10):
            lines.append(f"- {loc}: {n}\n")
        lines.append("\n")

    if high_select_clips:
        lines.append("## High select-potential clips\n\n")
        for name, use, cid in high_select_clips[:10]:
            cid_text = f" `{cid}`" if cid else ""
            lines.append(f"- **{name}**{cid_text} — {use}\n")
        lines.append("\n")

    if top_5_longest:
        lines.append("## Longest clips\n\n")
        for dur, name, cid in top_5_longest:
            cid_text = f" `{cid}`" if cid else ""
            lines.append(f"- **{name}**{cid_text} — {_fmt_duration(dur)}\n")
        lines.append("\n")

    lines.append("## Clips\n\n")
    for index, info in enumerate(enriched, 1):
        record = info["record"]
        name = record.get("clip_name") or record.get("file_path") or f"Clip {index}"
        clip_id = record.get("clip_id") or "(no id)"
        duration = _fmt_duration(_extract_duration_seconds(record))
        bin_path = record.get("bin_path") or ""
        lines.append(f"### {index}. {name}\n\n")
        lines.append(f"- **clip_id**: `{clip_id}`\n")
        lines.append(f"- **duration**: {duration}\n")
        if bin_path:
            lines.append(f"- **bin**: {bin_path}\n")

        summary = _read_clip_summary(info["clip"])
        if summary:
            lines.append(f"\n{summary}\n")
        else:
            lines.append("\n_Summary not yet available (vision pending or analysis incomplete)._\n")
        lines.append("\n")

    path = bin_summary_path(project_root)
    # Atomic write (temp + os.replace): a crash mid-write must not truncate the
    # bin summary that session_start_context reads at startup (PS4).
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
        os.replace(tmp_path, path)
        return {
            "success": True,
            "path": path,
            "clip_count": len(clips),
            "pending_vision_count": pending_vision_count,
            "aggregates": {
                "primary_use": primary_use_counts,
                "select_potential": select_potential_counts,
                "style": style_counts,
                "energy_arc": energy_counts,
                "top_tags": dict(_top(tag_counts, 20)),
                "top_locations": dict(_top(location_counts, 10)),
            },
        }
    except OSError as exc:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def _extract_duration_seconds(record: Dict[str, Any]) -> float:
    # Try a few common shapes the record may carry duration in
    for key in ("duration_seconds", "duration", "Duration"):
        value = record.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _fmt_duration(seconds: float) -> str:
    if seconds <= 0:
        return "0s"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _read_clip_summary(clip: Dict[str, Any]) -> Optional[str]:
    """Try to read the clip_summary from the clip's analysis.json if present."""
    analysis_json_path = clip.get("analysis_json")
    if not analysis_json_path or not os.path.isfile(analysis_json_path):
        return None
    try:
        with open(analysis_json_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    visual = report.get("visual") or {}
    summary = visual.get("clip_summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    if isinstance(summary, dict):
        para = summary.get("paragraph") or summary.get("one_line")
        if isinstance(para, str) and para.strip():
            return para.strip()
    return None


# ============ Session notes ============

def record_session_note(project_root: str, note: str, *, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Append a session note to today's session_notes file."""
    ensure_memory_structure(project_root)
    date = _today_date()
    path = os.path.join(session_notes_dir(project_root), f"{date}.md")
    header = f"# Session notes — {date}\n\n" if not os.path.isfile(path) else ""
    entry = f"## {_now_iso()}" + (f" ({session_id})" if session_id else "") + "\n\n" + note.strip() + "\n\n"
    try:
        with open(path, "a", encoding="utf-8") as handle:
            if header:
                handle.write(header)
            handle.write(entry)
        return {"success": True, "path": path}
    except OSError as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def record_correction(
    project_root: str,
    *,
    entity_type: str,
    entity_uuid: str,
    field_path: str,
    previous_value: Any,
    new_value: Any,
    author: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a correction entry to corrections.md."""
    ensure_memory_structure(project_root)
    path = corrections_path(project_root)
    entry_lines = [
        f"## {_now_iso()} — {author}\n",
        f"- **target**: {entity_type} `{entity_uuid}` field `{field_path}`\n",
        f"- **previous**: `{_short_repr(previous_value)}`\n",
        f"- **new**: `{_short_repr(new_value)}`\n",
    ]
    if reason:
        entry_lines.append(f"- **why**: {reason}\n")
    entry_lines.append("\n")
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("".join(entry_lines))
        return {"success": True, "path": path}
    except OSError as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def record_decision(
    project_root: str,
    *,
    title: str,
    description: str,
    author: str,
    tags: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Append a load-bearing decision to decisions.md."""
    ensure_memory_structure(project_root)
    path = decisions_path(project_root)
    tag_line = ""
    if tags:
        tag_str = ", ".join(f"`{t}`" for t in tags)
        tag_line = f"_Tags: {tag_str}_\n\n"
    entry = f"## {_now_iso()} — {title}\n\n_By: {author}_\n\n{tag_line}{description.strip()}\n\n"
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(entry)
        return {"success": True, "path": path}
    except OSError as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def _short_repr(value: Any, limit: int = 200) -> str:
    if value is None:
        return "null"
    if isinstance(value, (str, int, float, bool)):
        s = str(value)
    else:
        try:
            s = json.dumps(value, sort_keys=True)
        except (TypeError, ValueError):
            s = repr(value)
    return s if len(s) <= limit else s[:limit] + "…"


# ============ Panel state (V2 B6 — chat ↔ control panel sync) ============

def panel_state_path(project_root: str) -> str:
    return os.path.join(project_root, PANEL_STATE_FILENAME)


def read_panel_state(project_root: str) -> Optional[Dict[str, Any]]:
    """Read panel_state.json. Returns None if absent or unreadable.

    The state file holds: current_clip_id, current_shot_index, current_view
    ('bin' | 'clip' | 'shot'), focus_history, plus whatever either chat or
    the panel writes. Either side can read; either side can write.
    """
    path = panel_state_path(project_root)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def write_panel_state(
    project_root: str,
    updates: Dict[str, Any],
    *,
    written_by: Optional[str] = None,
    merge: bool = True,
) -> Dict[str, Any]:
    """Write panel_state.json atomically.

    `updates` is merged into the existing state by default (merge=True) so
    callers can partial-update fields. Pass merge=False to replace.
    """
    ensure_memory_structure(project_root)
    path = panel_state_path(project_root)
    if merge:
        existing = read_panel_state(project_root) or {}
        payload = dict(existing)
        payload.update(updates)
    else:
        payload = dict(updates)
    payload["schema_version"] = PANEL_STATE_SCHEMA_VERSION
    payload["updated_at"] = _now_iso()
    if written_by:
        payload["last_written_by"] = written_by
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
        return {"success": True, "path": path, "state": payload}
    except OSError as exc:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


# ============ Soul (user-scoped, cross-project) ============

def soul_dir(analysis_base_root: str) -> str:
    """Return the user-scoped soul directory path.

    `analysis_base_root` is the parent of all project analysis roots
    (typically `~/Documents/davinci-resolve-mcp-analysis`). The soul lives
    at `{base}/_soul/` so it's discoverable alongside project data but
    clearly marked user-scoped via the underscore prefix.
    """
    return os.path.join(analysis_base_root, SOUL_DIR_NAME)


def ensure_soul_structure(analysis_base_root: str) -> Dict[str, Any]:
    """Create the soul directory + initial files if absent. Idempotent."""
    d = soul_dir(analysis_base_root)
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)

    created = []
    seeds = {
        SOUL_PERSPECTIVE_FILENAME: _SOUL_PERSPECTIVE_TEMPLATE,
        SOUL_WORKING_STYLE_FILENAME: _SOUL_WORKING_STYLE_TEMPLATE,
        SOUL_LEARNED_FILENAME: _SOUL_LEARNED_TEMPLATE,
    }
    for filename, template in seeds.items():
        path = os.path.join(d, filename)
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(template)
            created.append(path)

    return {
        "success": True,
        "soul_dir": d,
        "created": created,
    }


def read_soul(analysis_base_root: str) -> Dict[str, Optional[str]]:
    """Read all soul files. Returns dict mapping filename → contents (or None)."""
    d = soul_dir(analysis_base_root)
    out: Dict[str, Optional[str]] = {}
    for name in (SOUL_PERSPECTIVE_FILENAME, SOUL_WORKING_STYLE_FILENAME, SOUL_LEARNED_FILENAME):
        path = os.path.join(d, name)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    out[name] = handle.read()
            except OSError:
                out[name] = None
        else:
            out[name] = None
    return out


def append_to_soul(
    analysis_base_root: str,
    filename: str,
    entry: str,
    *,
    author: str,
    why: Optional[str] = None,
) -> Dict[str, Any]:
    """Append an entry to a soul file, with timestamp and author header.

    The soul evolves slowly; entries are added when an observation generalizes
    beyond a single project. Pruning / consolidation is V2.1+ work.
    """
    if filename not in (SOUL_PERSPECTIVE_FILENAME, SOUL_WORKING_STYLE_FILENAME, SOUL_LEARNED_FILENAME):
        return {"success": False, "error": f"Unknown soul file: {filename}"}
    ensure_soul_structure(analysis_base_root)
    path = os.path.join(soul_dir(analysis_base_root), filename)
    block = [f"\n## {_now_iso()} — {author}\n"]
    if why:
        block.append(f"_Why: {why}_\n\n")
    block.append(entry.strip() + "\n")
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("".join(block))
        return {"success": True, "path": path}
    except OSError as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


_SOUL_PERSPECTIVE_TEMPLATE = """# Soul — Perspective

User-scoped, cross-project. The accumulated aesthetic and editorial perspective
that carries between projects. Slow-evolving. Updated when something
generalizes beyond a single project's specifics.

This file is one of three soul layers. The others:
- `working_style.md` — how the user and I collaborate
- `learned_from_corrections.md` — patterns from corrections across projects

---
"""

_SOUL_WORKING_STYLE_TEMPLATE = """# Soul — Working style

User-scoped, cross-project. How the user and I work together — pace,
preferences, the rhythm of our collaboration.

Entries added when a working-style observation feels durable across projects,
not specific to this one.

---
"""

_SOUL_LEARNED_TEMPLATE = """# Soul — Learned from corrections

User-scoped, cross-project. Patterns from corrections the user has made across
projects. Generalized lessons, not specific fixes.

Example pattern: "User consistently prefers concrete physical description over
interpretation when subject identity is uncertain. Hedge identity claims;
describe what's visible."

Specific per-project corrections live in `{project}/memory/corrections.md`.
This file is for what generalizes across projects.

---
"""


# ============ Session start protocol ============

def session_start_context(
    project_root: str,
    *,
    analysis_base_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble the context an LLM should load at session start.

    Read order: soul (cross-project) → project memory → heartbeat → DB on demand.

    Args:
        project_root: This project's analysis root.
        analysis_base_root: Parent of all project analysis roots, for the soul.
            If None, derived as the parent of project_root.
    """
    ensure_memory_structure(project_root)
    if analysis_base_root is None:
        analysis_base_root = os.path.dirname(project_root)
    ensure_soul_structure(analysis_base_root)

    heartbeat = read_heartbeat(project_root)
    summary_path = bin_summary_path(project_root)
    notes_dir = session_notes_dir(project_root)
    recent_notes: List[str] = []
    if os.path.isdir(notes_dir):
        try:
            files = sorted(os.listdir(notes_dir), reverse=True)
            recent_notes = [os.path.join(notes_dir, f) for f in files[:7] if f.endswith(".md")]
        except OSError:
            pass

    return {
        "project_root": project_root,
        "analysis_base_root": analysis_base_root,
        # Soul (cross-project, user-scoped) — read first; informs perspective.
        "soul_dir": soul_dir(analysis_base_root),
        "soul_files": read_soul(analysis_base_root),
        # Project-scoped narrative
        "heartbeat": heartbeat,
        "heartbeat_path": heartbeat_path(project_root),
        "bin_summary_path": summary_path if os.path.isfile(summary_path) else None,
        "recent_session_notes": recent_notes,
        "corrections_path": corrections_path(project_root) if os.path.isfile(corrections_path(project_root)) else None,
        "decisions_path": decisions_path(project_root) if os.path.isfile(decisions_path(project_root)) else None,
        # Shared state with control panel (V2 B6)
        "panel_state": read_panel_state(project_root),
        "panel_state_path": panel_state_path(project_root),
    }
