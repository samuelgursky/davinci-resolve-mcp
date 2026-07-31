"""The project journal — the paperwork that makes a cutting room work.

Every craft role in post keeps written records as a primary deliverable, and
they are the first thing to be skipped and the first thing to be missed:

- the assistant editor's **ingest log** (what came in, what verified, what
  failed) and **known-issues list**
- the assistant colorist's **session-prep summary**, including the hours saved,
  because that is what justifies the prep next time
- the online editor's **technical handoff document**
- the post supervisor's **status report**

This tool changed timelines and said almost nothing about it. `edit_report`
fixed that for a single operation; this fixes it for the project. The
distinction matters: an operation report answers "what did that do", and a
journal answers "what has happened to this project, and what is still wrong
with it".

## Append-only, on purpose

Records are appended and never rewritten. A known-issues list that gets tidied
loses the thing it was for — the issue nobody got round to, still sitting there
three weeks later. Resolving an issue appends a resolution; it does not delete
the issue. That is the difference between a log and a status board, and the log
is what you want when someone asks why a shot shipped soft.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence

JOURNAL_DIRNAME = "project_journal"
JOURNAL_FILE = "journal.jsonl"

#: Record kinds. Open set — an unknown kind is stored and rendered generically
#: rather than rejected, because refusing to record something is worse than
#: recording it under a label we do not recognise.
KIND_INGEST = "ingest"
KIND_ISSUE = "issue"
KIND_RESOLUTION = "resolution"
KIND_MILESTONE = "milestone"


def _journal_path(project_root: str) -> str:
    return os.path.join(project_root, JOURNAL_DIRNAME, JOURNAL_FILE)


def append(project_root: str, *, kind: str, summary: str,
           detail: Optional[str] = None, ref: Optional[str] = None,
           data: Optional[Mapping[str, Any]] = None,
           timestamp: Optional[str] = None) -> Dict[str, Any]:
    """Append one record. Never rewrites, never deletes.

    `timestamp` is supplied by the caller rather than generated here so the
    journal stays deterministic and testable; the server passes the real clock.
    """
    if not str(summary).strip():
        return {"success": False, "error": "a record needs a summary"}
    path = _journal_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    record = {
        "seq": _next_seq(path),
        "kind": str(kind or "note"),
        "summary": str(summary).strip(),
        "detail": str(detail).strip() if detail else None,
        "ref": str(ref) if ref else None,
        "timestamp": timestamp,
        "data": dict(data) if data else None,
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({k: v for k, v in record.items() if v is not None}) + "\n")
    return {"success": True, "record": record}


def read(project_root: str, *, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    path = _journal_path(project_root)
    if not os.path.exists(path):
        return []
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                # A corrupt line must not hide the rest of the journal.
                out.append({"kind": "corrupt", "summary": "unreadable journal line"})
                continue
            if kind is None or record.get("kind") == kind:
                out.append(record)
    return out


def open_issues(project_root: str) -> Dict[str, Any]:
    """Issues with no matching resolution.

    Resolutions reference an issue by its `ref`. An issue whose resolution never
    arrived stays open forever, which is the entire point — this is the list
    that answers "why did that ship soft".
    """
    records = read(project_root)
    resolved = {r.get("ref") for r in records if r.get("kind") == KIND_RESOLUTION and r.get("ref")}
    issues = [r for r in records if r.get("kind") == KIND_ISSUE]
    still_open = [i for i in issues if i.get("ref") not in resolved]
    return {
        "open": still_open,
        "resolved_count": len(issues) - len(still_open),
        "total_raised": len(issues),
        "note": (
            f"{len(still_open)} of {len(issues)} issues still open. Resolving an "
            "issue appends a resolution; it never deletes the issue. A tidied "
            "known-issues list loses the one nobody got round to."
        ),
    }


KIND_PICTURE_LOCK = "picture_lock"


def timeline_fingerprint(items: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Shape-of-the-cut signature: item count, total duration, and edit points.

    It answers one question — "has this been re-cut since we locked" — and it
    has to answer it correctly, so the edit points themselves are hashed rather
    than only summarised. Counts and totals alone miss the case that matters
    most: shots redistributed inside an unchanged runtime, which is exactly what
    a trim pass produces and exactly the change that breaks a conform.

    Still deliberately blind to everything that is *not* the cut. A grade, a
    marker, a rename, a track change: none of these trip it, because none of
    them cost anything downstream.
    """
    boundaries: List[tuple] = []
    total = 0
    for item in items:
        start, end = item.get("timeline_start_frame"), item.get("timeline_end_frame")
        if start is None or end is None:
            continue
        boundaries.append((int(start), int(end)))
        total += max(0, int(end) - int(start))
    boundaries.sort()
    digest = hashlib.sha1(
        json.dumps(boundaries, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "item_count": len(boundaries),
        "total_frames": total,
        "edit_points_hash": digest,
    }


def set_picture_lock(project_root: str, *, timeline_name: str,
                     items: Sequence[Mapping[str, Any]],
                     timestamp: Optional[str] = None) -> Dict[str, Any]:
    """Record picture lock for a timeline, with the shape of the cut at that moment."""
    fingerprint = timeline_fingerprint(items)
    append(project_root, kind=KIND_PICTURE_LOCK,
           summary=f"picture lock: {timeline_name}",
           detail=f"{fingerprint['item_count']} items, {fingerprint['total_frames']} frames",
           ref=timeline_name, data=fingerprint, timestamp=timestamp)
    return {"success": True, "timeline_name": timeline_name, "fingerprint": fingerprint,
            "note": ("Locked. Editorial changes after this point are the expensive kind — "
                     "conform, colour and sound all key off this cut.")}


def check_picture_lock(project_root: str, *, timeline_name: str,
                       items: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Has a locked timeline been re-cut since?"""
    locks = [r for r in read(project_root, kind=KIND_PICTURE_LOCK)
             if r.get("ref") == timeline_name]
    if not locks:
        return {
            "locked": False,
            "note": (f"{timeline_name!r} has no picture lock recorded. Not an error — "
                     "but nothing downstream can tell an intended recut from an accident."),
        }
    locked = locks[-1]
    was = locked.get("data") or {}
    now = timeline_fingerprint(items)
    drifted = any(
        was.get(key) != now[key]
        for key in ("item_count", "total_frames", "edit_points_hash")
    )
    return {
        "locked": True,
        "drifted": drifted,
        "locked_fingerprint": was,
        "current_fingerprint": now,
        "locked_at": locked.get("timestamp"),
        "note": (
            f"{timeline_name!r} was locked at {was.get('item_count')} items / "
            f"{was.get('total_frames')} frames and is now {now['item_count']} / "
            f"{now['total_frames']}. **This has been re-cut since picture lock.** "
            "Conform, colour and sound all key off the locked cut; changes after it "
            "are the expensive kind. Confirm the recut is intended and tell "
            "downstream."
            if drifted else
            f"{timeline_name!r} matches its picture lock — the cut has not moved."
        ),
    }


def _next_seq(path: str) -> int:
    if not os.path.exists(path):
        return 1
    count = 0
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count + 1


# ── rendered documents ───────────────────────────────────────────────────────


def render_ingest_log(project_root: str) -> str:
    records = read(project_root, kind=KIND_INGEST)
    lines = ["# Ingest log", ""]
    if not records:
        return "\n".join(lines + ["_No ingest recorded._", ""])
    lines += ["| # | What | Detail |", "|---|---|---|"]
    for record in records:
        lines.append(
            f"| {record.get('seq')} | {record.get('summary')} | "
            f"{str(record.get('detail') or '').replace('|', '/')} |"
        )
    return "\n".join(lines) + "\n"


def render_known_issues(project_root: str) -> str:
    state = open_issues(project_root)
    lines = ["# Known issues", "", f"**{state['note']}**", ""]
    if not state["open"]:
        lines.append("_Nothing open._")
        return "\n".join(lines) + "\n"
    for issue in state["open"]:
        ref = f" `{issue['ref']}`" if issue.get("ref") else ""
        lines.append(f"- **{issue.get('summary')}**{ref}")
        if issue.get("detail"):
            lines.append(f"  {issue['detail']}")
    return "\n".join(lines) + "\n"


def render_session_prep(
    project_root: str,
    *,
    session_kind: str = "colour",
    prep_hours: Optional[float] = None,
    estimated_hours_saved: Optional[float] = None,
    hourly_rate: Optional[float] = None,
    ready: Optional[Sequence[str]] = None,
    outstanding: Optional[Sequence[str]] = None,
) -> str:
    """The assistant's session-prep summary, including what the prep was worth.

    The value figures are here because the craft is explicit that they are the
    argument for doing the prep at all — an assistant's pre-balance pass that
    saves two hours of a colourist's time has a number attached, and stating it
    is how the prep survives the next budget conversation.
    """
    lines = [f"# Session prep — {session_kind}", ""]
    for label, entries in (("Ready", ready), ("Outstanding", outstanding)):
        if entries:
            lines += [f"### {label}", ""] + [f"- {e}" for e in entries] + [""]
    state = open_issues(project_root)
    if state["open"]:
        lines += ["### Known issues carried into this session", ""]
        lines += [f"- {i.get('summary')}" for i in state["open"]] + [""]
    if prep_hours is not None or estimated_hours_saved is not None:
        lines += ["### Value", ""]
        if prep_hours is not None:
            lines.append(f"- Prep time: {prep_hours:g}h")
        if estimated_hours_saved is not None:
            lines.append(f"- Estimated session time saved: {estimated_hours_saved:g}h")
            if hourly_rate:
                lines.append(
                    f"- At {hourly_rate:g}/hour that is ~"
                    f"{estimated_hours_saved * hourly_rate:,.0f} of session time"
                )
        lines += ["", "_Estimates, stated as such. They exist because the prep has "
                  "to justify itself in the next budget conversation._", ""]
    return "\n".join(lines).rstrip() + "\n"


def render_handoff(
    *,
    project: str,
    to: str,
    timeline_name: Optional[str] = None,
    technical: Optional[Mapping[str, Any]] = None,
    included: Optional[Sequence[str]] = None,
    known_issues: Optional[Sequence[str]] = None,
    notes: Optional[str] = None,
) -> str:
    """The online editor's technical handoff document.

    Every field left blank is printed as `NOT STATED` rather than omitted. A
    handoff that silently drops the frame rate reads as complete, and the
    receiving facility discovers the gap after they have started.
    """
    lines = [f"# Technical handoff — {project}", "", f"**To:** {to}"]
    if timeline_name:
        lines.append(f"**Timeline:** {timeline_name}")
    lines.append("")

    spec_keys = ("frame_rate", "resolution", "timeline_color_space",
                 "output_color_space", "audio_layout", "start_timecode", "handles")
    lines += ["### Technical", "", "| Field | Value |", "|---|---|"]
    supplied = dict(technical or {})
    for key in spec_keys:
        value = supplied.pop(key, None)
        lines.append(f"| {key.replace('_', ' ')} | {value if value not in (None, '') else '**NOT STATED**'} |")
    for key, value in sorted(supplied.items()):
        lines.append(f"| {key.replace('_', ' ')} | {value} |")
    lines.append("")

    if included:
        lines += ["### Included", ""] + [f"- {i}" for i in included] + [""]
    if known_issues:
        lines += ["### Known issues", ""] + [f"- {i}" for i in known_issues] + [""]
    if notes:
        lines += ["### Notes", "", notes, ""]
    lines += ["---", "",
              "_Fields marked NOT STATED were not supplied. A handoff that omits "
              "them reads as complete and the gap surfaces after work has started._", ""]
    return "\n".join(lines)


def render_status(
    *,
    project: str,
    phase: str,
    percent_complete: Optional[float] = None,
    blockers: Optional[Sequence[str]] = None,
    next_milestone: Optional[str] = None,
    open_issue_count: Optional[int] = None,
) -> str:
    """The post supervisor's status summary. Short on purpose — they are busy."""
    overall = "BLOCKED" if blockers else "ON TRACK"
    lines = [
        f"# {project} — status", "",
        f"**{overall}** · phase: {phase}"
        + (f" · {percent_complete:g}% complete" if percent_complete is not None else ""),
        "",
    ]
    if blockers:
        lines += ["### Blockers", ""] + [f"- {b}" for b in blockers] + [""]
    else:
        lines += ["_No blockers._", ""]
    if open_issue_count:
        lines += [f"{open_issue_count} known issues still open.", ""]
    if next_milestone:
        lines += [f"**Next milestone:** {next_milestone}", ""]
    return "\n".join(lines).rstrip() + "\n"
